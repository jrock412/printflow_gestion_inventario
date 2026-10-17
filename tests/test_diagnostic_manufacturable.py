# -*- coding: utf-8 -*-
"""Fabricable vs COMPRADO en el diagnóstico de pedido (PrintFlow).

Regla del rediseño: ``_pf_product_production`` usa un flag explícito
``is_manufacturable`` (BoM o ruta de fabricación aplicable). Un insumo COMPRADO
—aunque tenga una ruta Buy— NUNCA produce ``no_mo``: su ``production_status`` es
``'na'`` y no genera falla de fabricación. Un terminado sin MO sí es ``no_mo``.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticManufacturable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Manufacturable (DIAG)',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Manufacturable (DIAG)',
            'supplier_rank': 1,
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name, purchasable=False, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
            'purchase_ok': purchasable,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _make_bom(self, finished, component, qty=2.0):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': qty,
            })],
        })

    def _force_order(self, lines):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return so, board

    # ------------------------------------------------------------------
    # Caso
    # ------------------------------------------------------------------
    def test_manufacturable_finished_vs_purchased_component(self):
        # Terminado fabricable por BoM (sin ruta de compra).
        finished = self._make_product('TERMINADO BOM (MANUF)')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        # Insumo con ruta Buy: comprado, NO fabricable.
        component = self._make_product(
            'INSUMO COMPRADO (MANUF)', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        buy_route = self.env.ref(
            'purchase_stock.route_warehouse0_buy', raise_if_not_found=False)
        if buy_route:
            component.product_tmpl_id.route_ids = [(6, 0, buy_route.ids)]
        self._make_bom(finished, component)

        _so, board = self._force_order([(finished, 3.0)])
        # Fuerza el escenario "sin orden de fabricación" del pedido (como el
        # caso real S07301): el terminado no tiene MO.
        board.write({'production_alert': 'no_order'})

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        finished_line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        component_line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == component)
        self.assertEqual(len(finished_line), 1)
        self.assertEqual(len(component_line), 1)

        # El terminado es fabricable y, sin MO, es "sin orden".
        self.assertTrue(finished_line.is_manufacturable)
        self.assertEqual(finished_line.production_status, 'no_mo')

        # El insumo comprado NO es fabricable: producción 'na' y sin falla.
        self.assertFalse(component_line.is_manufacturable)
        self.assertEqual(component_line.production_status, 'na')
        self.assertFalse(
            component_line.failure_ids.filtered(
                lambda f: f.node == 'production'),
            'Un insumo comprado no debe generar falla de fabricación.',
        )
