# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticUxLinksLog(TransactionCase):
    """C2/C3 del Wizard de Diagnóstico:

    * C2: los wrappers ``action_open_*`` delegan en el tablero y las banderas
      de visibilidad (``sale_order_id``, ``has_delivery_picking``,
      ``has_purchase``, ``has_production``) quedan bien expuestas.
    * C3: ``action_apply_route`` deja bitácora en el chatter del pedido, sin
      registrarla para la ruta 'none' ni duplicarla en 'reassign'.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente UX Diagnostico',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor UX Diagnostico',
            'supplier_rank': 1,
        })
        # Producto de fabricación gestionado (sin ruta de compra): al confirmar
        # crea albarán de entrega, no PO, y sirve para los enlaces de inventario.
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO UX (DIAG)',
            'type': 'product',
            'x_is_printflow_managed': True,
            'seller_ids': [(0, 0, {'partner_id': cls.supplier.id})],
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_order(self, qty=3.0):
        """Pedido forzado a 'sale' (sin procurement) + su tarjeta de tablero."""
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return so, board

    def _make_confirmed_order(self, qty=1.0):
        """Pedido confirmado de verdad: genera y reserva su albarán."""
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
            })],
        })
        so.action_confirm()
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return so, board

    def _wizard(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    def _route_logs(self, board):
        """Mensajes del chatter con la bitácora central de C3."""
        messages = self.env['mail.message'].search([
            ('model', '=', 'printflow.order.board'),
            ('res_id', '=', board.id),
        ])
        return messages.filtered(
            lambda m: 'se ejecutó la ruta' in (m.body or ''))

    # ------------------------------------------------------------------
    # C2 — Wrappers y banderas
    # ------------------------------------------------------------------
    def test_sale_and_picking_wrappers_delegate_to_board(self):
        _so, board = self._make_confirmed_order()
        wizard = self._wizard(board)

        self.assertEqual(
            wizard.action_open_sale(), board.action_open_sale_order())
        self.assertEqual(
            wizard.action_open_stock_picking(),
            board.action_open_delivery_picking())

    def test_purchase_wrapper_delegates_to_board(self):
        so, board = self._make_order()
        self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': so.name,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 2.0,
                'product_uom': self.product.uom_id.id,
            })],
        })
        wizard = self._wizard(board)
        self.assertEqual(
            wizard.action_open_purchase(), board.action_open_purchase_order())

    def test_production_wrapper_propagates_board_guard(self):
        """Sin MO, el wrapper deja salir el UserError del tablero."""
        _so, board = self._make_order()
        wizard = self._wizard(board)
        with self.assertRaises(UserError):
            wizard.action_open_production()

    def test_visibility_flags_are_wired_to_board(self):
        so, board = self._make_confirmed_order()
        wizard = self._wizard(board)
        self.assertEqual(wizard.sale_order_id, so)
        self.assertEqual(
            wizard.has_delivery_picking, board.has_delivery_picking)
        self.assertEqual(wizard.has_production, board.has_production)
        self.assertEqual(wizard.has_purchase, board.has_purchase)

    # ------------------------------------------------------------------
    # C3 — Bitácora en el chatter
    # ------------------------------------------------------------------
    def test_apply_route_logs_diagnostic_note(self):
        _so, board = self._make_order(qty=4.0)
        wizard = self._wizard(board)
        wizard.resolution_route = 'purchase'

        wizard.action_apply_route()

        logs = self._route_logs(board)
        self.assertEqual(
            len(logs), 1,
            'La ruta ejecutada debe dejar UNA bitácora en el chatter.')
        self.assertIn('déficit físico', logs.body)

    def test_none_route_does_not_log(self):
        _so, board = self._make_order()
        wizard = self._wizard(board)
        wizard.resolution_route = 'none'

        wizard.action_apply_route()

        self.assertFalse(
            self._route_logs(board),
            'La ruta "Solo diagnóstico" no debe escribir bitácora.',
        )

    def test_reassign_route_does_not_double_log(self):
        """'reassign' ya publica su mensaje: el dispatcher no lo duplica."""
        _so, board = self._make_confirmed_order()
        wizard = self._wizard(board)
        wizard.resolution_route = 'reassign'

        wizard.action_apply_route()

        self.assertFalse(
            self._route_logs(board),
            'La bitácora central no debe duplicar el mensaje de reasignación.',
        )
