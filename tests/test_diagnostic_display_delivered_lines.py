# -*- coding: utf-8 -*-
"""MEJORA A: los productos ya entregados SIEMPRE se muestran (PrintFlow).

Una línea 100% entregada no tiene demanda pendiente y por eso NO debe generar
fallas; pero tampoco debe desaparecer de "Productos del pedido". Se muestra como
una fila de SOLO DISPLAY (``is_display_only``) con todo en 0, sana, al final del
listado y con la nota "Todo en orden (producto entregado)".
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticDisplayDeliveredLines(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Display Entregado (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _deliver_partial(self, so, delivered_by_product):
        picking = so.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking, 'La confirmación debe generar el albarán.')
        picking.action_assign()
        for move in picking.move_ids:
            qty = delivered_by_product.get(move.product_id, 0.0)
            move.quantity = qty
            move.picked = qty > 0.0
        result = picking.button_validate()
        if (isinstance(result, dict)
                and result.get('res_model') == 'stock.backorder.confirmation'):
            confirmation = self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({})
            confirmation.process()
        return picking

    def _build(self):
        """Pedido con un producto entregado y otro pendiente."""
        delivered = self._make_product('ENTREGADO DISPLAY (DIAG)')
        pending = self._make_product('PENDIENTE DISPLAY (DIAG)')
        self.env['stock.quant']._update_available_quantity(
            delivered, self.stock_location, 5.0)
        self.env['stock.quant']._update_available_quantity(
            pending, self.stock_location, 5.0)
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': delivered.id,
                    'product_uom_qty': 1.0,
                    'product_uom': delivered.uom_id.id,
                }),
                (0, 0, {
                    'product_id': pending.id,
                    'product_uom_qty': 1.0,
                    'product_uom': pending.uom_id.id,
                }),
            ],
        })
        so.action_confirm()
        self._deliver_partial(so, {delivered: 1.0})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        board.invalidate_model()
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        return wizard, so, board, delivered, pending

    # ------------------------------------------------------------------
    # Casos
    # ------------------------------------------------------------------
    def test_delivered_product_shows_as_display_only_row(self):
        wizard, so, _board, delivered, _pending = self._build()
        line = so.order_line.filtered(lambda l: l.product_id == delivered)
        self.assertAlmostEqual(line.qty_delivered, line.product_uom_qty, places=3)

        row = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == delivered)
        self.assertTrue(row, 'El producto entregado debe seguir apareciendo.')
        self.assertTrue(row.is_display_only)
        self.assertEqual(row.required_qty, 0.0)
        self.assertEqual(row.deficit_qty, 0.0)
        self.assertEqual(row.contention_qty, 0.0)
        self.assertFalse(row.is_over_reserved)
        self.assertEqual(row.flow_severity, 'ok')
        self.assertEqual(row.flow_failed_node_count, 0)
        self.assertEqual(
            row.status_note, 'Todo en orden (producto entregado)')
        self.assertFalse(
            row.failure_ids,
            'Una fila de solo display no debe generar fallas de nodo.')

    def test_delivered_product_is_not_demand(self):
        wizard, so, board, delivered, _pending = self._build()
        demand = wizard._get_demand_map(board, so)
        self.assertNotIn(
            delivered, demand,
            'Un producto 100% entregado no debe tener demanda pendiente.')

    def test_display_only_rows_go_last(self):
        wizard, _so, _board, delivered, _pending = self._build()
        rows = wizard.product_line_ids
        self.assertTrue(rows)
        self.assertFalse(rows[0].is_display_only)
        self.assertTrue(rows[-1].is_display_only)
        self.assertEqual(rows[-1].product_id, delivered)
