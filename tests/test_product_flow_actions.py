# -*- coding: utf-8 -*-
"""Acciones ricas del diagrama de PRODUCTO (PrintFlow · Fase 5).

Custodia el dispatcher público ``action_run_pf_node`` y ``action_run_pf_plan``:
  * ``buy_product`` -> ``mrp.quick.purchase.wizard`` con ``sale_order_id=False``;
  * ``fabricate`` -> ``mrp.production`` (con BOM) y ``UserError`` (sin BOM);
  * ``fix_reservation`` -> saneo por producto (notification, no escribe si no hay);
  * ``blocking`` -> ``printflow.order.blocking.reservation``.

Son de SOLO LECTURA sobre el diagrama (el saneo es idempotente) y
``TransactionCase`` hace rollback al terminar.
"""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Acciones Producto', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']

    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _purchasable(self, name):
        product = self._product(
            name, purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _manufacturable(self, name):
        component = self._product('%s COMPONENTE' % name)
        self.env['stock.quant']._update_available_quantity(
            component, self.stock_location, 100.0)
        finished = self._product(name)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        return finished

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    # ------------------------------------------------------------------
    # 1) Comprar producto -> Compra Rápida SIN pedido de venta
    # ------------------------------------------------------------------
    def test_buy_product_opens_quick_purchase_without_sale(self):
        wizard = self._wizard(self._purchasable('ACCION COMPRAR PRODUCTO'))
        action = wizard.action_run_pf_node('buy_product')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        purchase = self.env['mrp.quick.purchase.wizard'].browse(
            action['res_id'])
        self.assertTrue(purchase)
        self.assertFalse(purchase.sale_order_id)

    def test_buy_components_opens_quick_purchase(self):
        # Componente SIN existencia -> la BOM reporta faltante.
        component = self._product('ACCION COMPONENTE FALTANTE')
        finished = self._product('ACCION COMPRAR COMPONENTES')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        wizard = self._wizard(finished)
        action = wizard.action_run_pf_node('buy_components')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        purchase = self.env['mrp.quick.purchase.wizard'].browse(
            action['res_id'])
        self.assertIn(component, purchase.purchase_line_ids.product_id)

    # ------------------------------------------------------------------
    # 2) Fabricar -> OF (con BOM) / bloqueo (sin BOM)
    # ------------------------------------------------------------------
    def test_fabricate_opens_production_with_bom(self):
        wizard = self._wizard(self._manufacturable('ACCION FABRICAR CON BOM'))
        action = wizard.action_run_pf_node('fabricate')
        self.assertEqual(action['res_model'], 'mrp.production')

    def test_fabricate_without_bom_raises(self):
        wizard = self._wizard(self._purchasable('ACCION FABRICAR SIN BOM'))
        with self.assertRaises(UserError):
            wizard.action_run_pf_node('fabricate')

    # ------------------------------------------------------------------
    # 3) Saneo por producto (re-reserva)
    # ------------------------------------------------------------------
    def test_fix_reservation_sanitizes_product(self):
        product = self._purchasable('ACCION SANEAR PRODUCTO')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        wizard = self._wizard(product)
        action = wizard.action_run_pf_node('fix_reservation')
        self.assertEqual(action['type'], 'ir.actions.client')

    # ------------------------------------------------------------------
    # 4) Ver quién me bloquea -> lista del producto
    # ------------------------------------------------------------------
    def test_blocking_opens_blocking_list(self):
        wizard = self._wizard(self._purchasable('ACCION BLOQUEO PRODUCTO'))
        action = wizard.action_run_pf_node('blocking')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(
            action['res_model'], 'printflow.order.blocking.reservation')

    # ------------------------------------------------------------------
    # 5) Fila del panel: ``action_run_pf_plan`` resuelve por causa
    # ------------------------------------------------------------------
    def test_plan_solution_dispatches_by_cause(self):
        wizard = self._wizard(self._purchasable('ACCION PLAN PRODUCTO'))
        action = wizard.action_run_pf_plan('buy_product', 'solution')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')

    # ------------------------------------------------------------------
    # 6) Claves desconocidas -> cierre seguro
    # ------------------------------------------------------------------
    def test_unknown_node_action_closes_safely(self):
        wizard = self._wizard(self._purchasable('ACCION DESCONOCIDA'))
        self.assertEqual(
            wizard.action_run_pf_node('no_existe')['type'],
            'ir.actions.act_window_close')
        self.assertEqual(
            wizard.action_run_pf_plan('buy_product', 'otra')['type'],
            'ir.actions.act_window_close')
