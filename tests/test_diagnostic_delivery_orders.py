# -*- coding: utf-8 -*-
"""MEJORA C: bandeja de albaranes de entrega + validación masiva (PrintFlow).

El ancla de la bandeja es ``stock.move.line`` (RESERVAS), no ``sale.order``:
los albaranes del POS que apartan el insumo tienen ``sale_id`` False. La acción
masiva de validar es la ÚNICA escritura; el resto del diagnóstico es lectura.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticDeliveryOrders(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Delivery Orders (DIAG)',
        })
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Cliente Delivery Orders Otro (DIAG)',
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

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _confirm_order(self, partner, product, qty=1.0):
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _failure_for(self, board):
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        line = wizard.deficit_line_ids[:1] or wizard.product_line_ids[:1]
        self.assertTrue(line, 'El wizard debe tener al menos una línea.')
        return self.env['printflow.order.diagnostic.failure'].create({
            'line_id': line.id,
        })

    # ------------------------------------------------------------------
    # Bandeja anclada en reservas (move lines)
    # ------------------------------------------------------------------
    def test_delivery_pickings_anchor_on_move_lines_and_exclude_own(self):
        product = self._make_product('RESERVA ENTREGA (DIAG)')
        self._add_stock(product, 5.0)
        own_so = self._confirm_order(self.customer, product, 1.0)
        other_so = self._confirm_order(self.other_customer, product, 1.0)
        own_picking = own_so.picking_ids
        other_picking = other_so.picking_ids
        (own_picking | other_picking).action_assign()

        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})
        failure = self._failure_for(board)
        pickings = failure._pf_delivery_pickings()

        self.assertIn(
            other_picking, pickings,
            'La bandeja debe incluir los albaranes que reservan el producto.')
        self.assertNotIn(
            own_picking, pickings,
            'La bandeja NO debe repetir los albaranes del propio pedido.')

    def test_open_delivery_orders_freezes_the_set(self):
        product = self._make_product('CONGELA ENTREGA (DIAG)')
        self._add_stock(product, 5.0)
        own_so = self._confirm_order(self.customer, product, 1.0)
        other_so = self._confirm_order(self.other_customer, product, 1.0)
        own_so.picking_ids.action_assign()
        other_so.picking_ids.action_assign()

        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})
        failure = self._failure_for(board)
        action = failure._pf_open_delivery_orders()

        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['view_mode'], 'tree,form')
        self.assertEqual(action['target'], 'current')
        self.assertEqual(list(action['domain'][0][:2]), ['id', 'in'])
        self.assertEqual(
            set(action['domain'][0][2]), set(failure._pf_delivery_pickings().ids))

    # ------------------------------------------------------------------
    # Validación masiva
    # ------------------------------------------------------------------
    def _result_line(self, wizard, picking):
        """Devuelve la fila del resultado correspondiente a un albarán."""
        return wizard.line_ids.filtered(
            lambda line: line.picking_id == picking)

    def test_bulk_validate_requires_explicit_target(self):
        result = self.env['stock.picking'].action_pf_bulk_validate_deliveries()

        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'warning')

    def test_bulk_validate_processes_assigned_and_skips_unassigned(self):
        ready = self._make_product('LISTO ENTREGA (DIAG)')
        self._add_stock(ready, 5.0)
        ready_so = self._confirm_order(self.customer, ready, 1.0)
        ready_picking = ready_so.picking_ids
        ready_picking.action_assign()

        nostock = self._make_product('SIN STOCK ENTREGA (DIAG)')
        nostock_so = self._confirm_order(self.customer, nostock, 1.0)
        nostock_picking = nostock_so.picking_ids
        self.assertNotEqual(nostock_picking.state, 'assigned')

        result = self.env['stock.picking'].with_context(
            active_ids=[ready_picking.id, nostock_picking.id],
        ).action_pf_bulk_validate_deliveries()

        self.assertEqual(ready_picking.state, 'done')
        self.assertNotEqual(nostock_picking.state, 'done')
        # La acción devuelve la ventana de detalle (no una notificación).
        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'printflow.delivery.bulk.result')
        wizard = self.env['printflow.delivery.bulk.result'].browse(
            result['res_id'])
        self.assertEqual(wizard.done_count, 1)
        self.assertEqual(wizard.skipped_count, 1)
        self.assertEqual(wizard.failed_count, 0)
        self.assertEqual(self._result_line(wizard, ready_picking).result, 'done')
        skip_line = self._result_line(wizard, nostock_picking)
        self.assertEqual(skip_line.result, 'skipped')
        self.assertTrue(skip_line.reason)

    def test_bulk_validate_mixed_success_and_failure(self):
        """Un albarán válido queda ``done`` y uno que falla no tumba el lote."""
        # Albarán VÁLIDO: producto reservado de sobra.
        valid = self._make_product('VALIDO MIXTO (DIAG)')
        self._add_stock(valid, 5.0)
        valid_picking = self._confirm_order(self.customer, valid, 1.0).picking_ids
        valid_picking.action_assign()

        # Albarán que FALLA: un producto reservado + otro sin stock forzado,
        # que al validar dejaría la existencia en negativo.
        reservable = self._make_product('RESERVABLE MIXTO (DIAG)')
        self._add_stock(reservable, 5.0)
        bad = self._make_product('SIN STOCK MIXTO (DIAG)')
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': reservable.id,
                    'product_uom_qty': 1.0,
                    'product_uom': reservable.uom_id.id,
                }),
                (0, 0, {
                    'product_id': bad.id,
                    'product_uom_qty': 1.0,
                    'product_uom': bad.uom_id.id,
                }),
            ],
        })
        so.action_confirm()
        bad_picking = so.picking_ids
        bad_picking.action_assign()
        self.assertEqual(
            bad_picking.state, 'assigned',
            'El albarán mixto debe quedar elegible (assigned) para probar el fallo.')
        bad_move = bad_picking.move_ids.filtered(
            lambda move: move.product_id == bad)
        bad_move.quantity = 1.0
        bad_move.picked = True

        result = self.env['stock.picking'].with_context(
            active_ids=[valid_picking.id, bad_picking.id],
            test_stock_no_negative=True,
        ).action_pf_bulk_validate_deliveries()

        self.assertEqual(valid_picking.state, 'done')
        self.assertNotEqual(bad_picking.state, 'done')
        wizard = self.env['printflow.delivery.bulk.result'].browse(
            result['res_id'])
        self.assertEqual(self._result_line(wizard, valid_picking).result, 'done')
        failed_line = self._result_line(wizard, bad_picking)
        self.assertEqual(failed_line.result, 'failed')
        self.assertTrue(failed_line.reason)
        self.assertIn(bad.display_name, failed_line.reason)

    def test_bulk_validate_keeps_done_when_validate_returns_print_action(self):
        """Un dict de impresión posterior a ``_action_done`` NO revierte el albarán."""
        product = self._make_product('IMPRIME ENTREGA (DIAG)')
        self._add_stock(product, 5.0)
        picking = self._confirm_order(self.customer, product, 1.0).picking_ids
        picking.action_assign()
        # Con la impresión automática activa, ``button_validate`` devuelve
        # ``do_multi_print`` DESPUÉS de validar: el albarán ya quedó ``done``.
        picking.picking_type_id.auto_print_delivery_slip = True

        result = self.env['stock.picking'].with_context(
            active_ids=[picking.id],
        ).action_pf_bulk_validate_deliveries()

        self.assertEqual(picking.state, 'done')
        wizard = self.env['printflow.delivery.bulk.result'].browse(
            result['res_id'])
        line = self._result_line(wizard, picking)
        self.assertEqual(line.result, 'done')
        self.assertEqual(wizard.done_count, 1)
