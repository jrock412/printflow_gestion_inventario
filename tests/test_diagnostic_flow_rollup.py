# -*- coding: utf-8 -*-
"""Roll-up del subárbol en el diagnóstico de pedido (PrintFlow).

El terminado debe mostrar el PEOR caso de su subárbol:
  * un componente en sobrepedido (contención) sube su ``stock='over'``;
  * el terminado sin MO aporta ``production='no_mo'``;
  * el resumen de fallas y el ``flow_failure_ids`` incluyen AMBOS.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticFlowRollup(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Flow Rollup (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

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
    def test_rollup_combines_component_over_and_finished_no_mo(self):
        finished = self._make_product('TERMINADO ROLLUP')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        component = self._make_product('COMPONENTE ROLLUP')
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
            })],
        })

        # El componente tiene stock, pero OTRO pedido lo reserva TODO: el pedido
        # no puede tomarlo -> contención -> stock 'over'.
        self._add_stock(component, 10.0)
        other = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': component.id,
                'product_uom_qty': 10.0,
                'product_uom': component.uom_id.id,
            })],
        })
        other.action_confirm()
        # El terminado ya tiene su existencia: así su propio nodo de inventario
        # queda en 'ok' y el 'over' solo puede venir del componente.
        self._add_stock(finished, 3.0)

        _so, board = self._force_order([(finished, 3.0)])
        board.write({'production_alert': 'no_order'})

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        finished_line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        self.assertEqual(len(finished_line), 1)

        # El roll-up hereda el 'over' del componente…
        self.assertEqual(finished_line.flow_stock_status, 'over')
        # …y conserva el estado propio roto del terminado.
        self.assertEqual(finished_line.flow_production_status, 'no_mo')
        self.assertEqual(finished_line.flow_severity, 'danger')

        summary = finished_line.flow_failure_summary
        self.assertIn('Sin orden de fabricación', summary)
        self.assertIn('Sobrepedido', summary)

        nodes = set(finished_line.flow_failure_ids.mapped('node'))
        self.assertIn('stock', nodes)
        self.assertIn('production', nodes)
        # La falla de stock viene del componente; la de fabricación, del terminado.
        stock_failure = finished_line.flow_failure_ids.filtered(
            lambda f: f.node == 'stock')
        self.assertEqual(stock_failure.origin_product_id, component)
        production_failure = finished_line.flow_failure_ids.filtered(
            lambda f: f.node == 'production')
        self.assertEqual(production_failure.origin_product_id, finished)
