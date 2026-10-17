# -*- coding: utf-8 -*-
"""Canvas de un PRODUCTO sin venta (PrintFlow · Fase 5).

Custodia:
  * ``action_open_product_flow`` crea el wizard y abre a pantalla completa;
  * ``timeline_json`` trae el canvas completo (eje por tipo, nodos con
    ``status``/``tone``/``status_label``), SIN panel ni tray de fallas;
  * ``flow_type`` lo detecta el motor (fabricable vs compra);
  * los pendientes por nodo se exponen con su acción de navegación.

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

import json

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_ORDER

AXIS_PURCHASE = [
    'purchase', 'receipt', 'stock', 'delivery', 'customer']
AXIS_MANUFACTURE = [
    'purchase', 'receipt', 'stock_supply', 'production', 'stock_finished',
    'delivery', 'customer']


@tagged('post_install', '-at_install')
class TestProductFlowCanvas(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Product Flow', 'supplier_rank': 1})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Product Flow'})
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

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _payload(self, wizard):
        return json.loads(wizard.timeline_json)

    def _purchasable(self, name):
        product = self._product(
            name, purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _manufacturable(self, name):
        component = self._product('%s COMPONENTE' % name)
        self._add_stock(component, 100.0)
        finished = self._product(name)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        return finished

    # ------------------------------------------------------------------
    # 1) Entrada
    # ------------------------------------------------------------------
    def test_action_open_product_flow_is_fullscreen(self):
        product = self._purchasable('PRODUCT FLOW ENTRADA')
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'current')
        self.assertTrue(action.get('res_id'))

    def test_action_without_product_notifies(self):
        action = self.Flow.action_open_product_flow(False)
        self.assertEqual(action['type'], 'ir.actions.client')

    # ------------------------------------------------------------------
    # 2) Canvas de compra
    # ------------------------------------------------------------------
    def test_purchase_canvas(self):
        product = self._purchasable('PRODUCT FLOW COMPRA')
        wizard = self._wizard(product)
        payload = self._payload(wizard)
        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        self.assertEqual(payload['flow_type'], 'purchase')
        self.assertEqual(payload['axis'], AXIS_PURCHASE)
        self.assertEqual(
            [node['key'] for node in payload['nodes']], AXIS_PURCHASE)
        for node in payload['nodes']:
            self.assertIn('status', node)
            self.assertIn('tone', node)
            self.assertIn('status_label', node)

    # ------------------------------------------------------------------
    # 3) Canvas de fabricación
    # ------------------------------------------------------------------
    def test_manufacture_canvas(self):
        finished = self._manufacturable('PRODUCT FLOW FAB')
        wizard = self._wizard(finished)
        payload = self._payload(wizard)
        self.assertEqual(payload['flow_type'], 'manufacture')
        self.assertEqual(payload['axis'], AXIS_MANUFACTURE)
        self.assertEqual(wizard.flow_type, 'manufacture')

    # ------------------------------------------------------------------
    # 4) Producto SANO: sin panel ni tray de fallas; CON traba: cadena +
    #    panel + tray (el producto ahora se comporta como el pedido).
    # ------------------------------------------------------------------
    def test_canvas_without_failure_has_no_panel_or_tray(self):
        product = self._purchasable('PRODUCT FLOW SANO')
        wizard = self._wizard(product)
        for node in self._payload(wizard)['nodes']:
            self.assertEqual(node['panel'], [])
            self.assertNotIn('tray', node)
            self.assertNotIn('root_link', node)
            self.assertEqual(node['role'], 'none')

    def test_canvas_with_failure_shows_chain_panel_and_tray(self):
        product = self._purchasable('PRODUCT FLOW CON TRABA')
        # Existencia negativa -> déficit físico -> Compras (raíz) e Inventario
        # (consecuencia): la cadena, el panel y el tray se materializan.
        self._add_stock(product, -3.0)
        wizard = self._wizard(product)
        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}

        self.assertTrue(
            any(node['role'] != 'none' for node in payload['nodes']))
        self.assertEqual(by_key['purchase']['role'], 'root')
        self.assertTrue(by_key['purchase']['panel'])
        self.assertIn('tray', by_key['purchase'])

        self.assertEqual(by_key['stock']['role'], 'consequence')
        self.assertTrue(by_key['stock']['panel'])
        self.assertEqual(
            by_key['stock']['root_link']['target_key'], 'purchase')

    # ------------------------------------------------------------------
    # 5) Pendientes por nodo + acción de navegación
    # ------------------------------------------------------------------
    def test_pending_badge_and_navigation(self):
        product = self._purchasable('PRODUCT FLOW PENDIENTES')
        self._add_stock(product, 5.0)
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 2.0,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()  # deja una entrega pendiente

        wizard = self._wizard(product)
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        delivery = by_key['delivery']
        self.assertGreater(delivery['pending'], 0)
        self.assertIsNotNone(delivery['pending_action'])
        self.assertEqual(
            delivery['pending_action']['method'], 'action_open_node_pending')
        self.assertEqual(delivery['pending_action']['res_model'],
                         'printflow.product.flow')

    # ------------------------------------------------------------------
    # 6) Reutiliza el motor de flujo (severidad calculada)
    # ------------------------------------------------------------------
    def test_reuses_engine_verdict(self):
        product = self._purchasable('PRODUCT FLOW MOTOR')
        wizard = self._wizard(product)
        self.assertIn(wizard.severity, ('ok', 'warning', 'danger'))
        self.assertTrue(wizard.name)
