# -*- coding: utf-8 -*-
"""Nodo ENTREGA del diagnóstico de pedido (paridad tablero <-> wizard).

El wizard antes solo diagnosticaba 4 nodos (venta, inventario, compras,
fabricación) y se saltaba la entrega: un pedido "listo pero sin entregar"
salía como "todo en orden" aunque el tablero lo marcara en Entrega Parcial.
Este test blinda el nodo canónico 'delivery':

  (1) Paridad en entrega parcial: ``board.is_partial_delivery is True`` y
      ``wizard.delivery_status == 'partial'``; la línea entregada -> 'ok' y la
      pendiente -> 'pending' con falla ``node='delivery'`` /
      ``pf_cause='order_delivery_pending'``.
  (2) "Listo pero sin entregar" y sin problema de flujo: el wizard NO dice
      "todo en orden"; muestra "Pendiente por entrega" y ofrece
      "Ir a la entrega de este producto".
  (3) Entregado: ``delivery_status='ok'`` y sin falla de entrega.
  (4) Navegación: ``_pf_nav_action('line_delivery')`` y
      ``action_open_line_delivery`` abren ``stock.picking`` con el albarán del
      PROPIO producto y excluyen el de otros pedidos.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticDeliveryNode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Nodo Entrega (DIAG)',
        })
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Cliente Nodo Entrega Otro (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.manu_type = cls.warehouse.manu_type_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        """Producto almacenable PrintFlow SIN ruta (genera albarán al confirmar)."""
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

    def _confirm_order(self, partner, lines):
        """Confirma un pedido con ``[(product, qty), ...]``."""
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.action_confirm()
        return so

    def _board(self, so):
        # El puente nativo sale.order.mrp_production_ids se cachea al confirmar:
        # se invalida para que el tablero vea las MO recién creadas.
        so.invalidate_model(['mrp_production_ids'])
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        board.recompute_states(domain=[('id', '=', board.id)])
        return board

    def _make_done_mo(self, so, product):
        """MO ``done`` vinculada al pedido (producción ya ejecutada).

        Simula el caso "listo pero sin entregar": no queda nada que fabricar,
        solo validar el albarán de salida.
        """
        group = so.procurement_group_id
        if not group:
            group = self.env['procurement.group'].create({
                'name': f'{so.name} - Inmediata',
                'sale_id': so.id,
                'partner_id': so.partner_id.id,
            })
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'origin': group.name or so.name,
            'picking_type_id': self.manu_type.id,
            'location_src_id': (
                self.manu_type.default_location_src_id.id
                or self.stock_location.id
            ),
            'location_dest_id': (
                self.manu_type.default_location_dest_id.id
                or self.stock_location.id
            ),
            'source_procurement_group_id': group.id,
            'procurement_group_id': group.id,
        })
        self.assertEqual(mo.sale_id, so)
        mo.write({'state': 'done'})
        return mo

    def _wizard(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    def _deliver(self, so, qty_by_product=None):
        """Valida el albarán entregando solo las cantidades indicadas.

        Lo que no se entrega queda en un albarán de reserva (backorder), de modo
        que el pedido puede quedar parcialmente entregado.
        """
        qty_by_product = qty_by_product or {}
        picking = so.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking, 'La confirmación debe generar el albarán.')
        picking.action_assign()
        for move in picking.move_ids:
            qty = qty_by_product.get(move.product_id, move.product_uom_qty)
            move.quantity = qty
            move.picked = qty > 0.0
        result = picking.button_validate()
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            confirmation = self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({})
            confirmation.process()
        return picking

    # ------------------------------------------------------------------
    # (1) Paridad en entrega parcial
    # ------------------------------------------------------------------
    def test_partial_delivery_matches_board_and_wizard(self):
        delivered = self._make_product('ENTREGADO PARCIAL (DIAG DELIVERY)')
        pending = self._make_product('PENDIENTE PARCIAL (DIAG DELIVERY)')
        self._add_stock(delivered, 10.0)
        self._add_stock(pending, 10.0)

        so = self._confirm_order(
            self.customer, [(delivered, 1.0), (pending, 1.0)])
        # Entrega SOLO ``delivered``: ``pending`` queda en backorder.
        self._deliver(so, {delivered: 1.0, pending: 0.0})

        board = self._board(so)
        self.assertTrue(
            board.is_partial_delivery,
            'El tablero debe marcar entrega parcial.')
        self.assertFalse(board.pf_all_delivered)

        wizard = self._wizard(board)
        self.assertEqual(
            wizard.delivery_status, 'partial',
            'El wizard debe mostrar la MISMA entrega parcial que el tablero.')

        line_delivered = wizard.product_line_ids.filtered(
            lambda l: l.product_id == delivered)
        line_pending = wizard.product_line_ids.filtered(
            lambda l: l.product_id == pending)
        self.assertTrue(line_delivered)
        self.assertTrue(line_pending)

        # La línea ya entregada no genera demanda: fila de display, entrega OK.
        self.assertTrue(line_delivered.is_display_only)
        self.assertEqual(line_delivered.delivery_status, 'ok')
        self.assertFalse(line_delivered.failure_ids.filtered(
            lambda f: f.node == 'delivery'))

        # La línea pendiente aporta la falla de entrega del nodo canónico.
        self.assertEqual(line_pending.delivery_status, 'pending')
        delivery_failure = line_pending.failure_ids.filtered(
            lambda f: f.node == 'delivery')
        self.assertTrue(delivery_failure)
        self.assertEqual(delivery_failure.pf_cause, 'order_delivery_pending')

    def test_partial_line_reports_partial_delivery(self):
        """Una sola línea entregada a medias -> 'partial' con su microcopy."""
        product = self._make_product('PARCIAL LINEA (DIAG DELIVERY)')
        self._add_stock(product, 10.0)
        so = self._confirm_order(self.customer, [(product, 3.0)])
        self._make_done_mo(so, product)
        self._deliver(so, {product: 1.0})

        board = self._board(so)
        self.assertTrue(board.is_partial_delivery)
        self.assertEqual(board.state, 'partial_delivered')

        wizard = self._wizard(board)
        self.assertEqual(wizard.delivery_status, 'partial')
        self.assertEqual(wizard.recommended_route, 'deliver')

        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertEqual(line.delivery_status, 'partial')
        delivery_failure = line.failure_ids.filtered(
            lambda f: f.node == 'delivery')
        self.assertTrue(delivery_failure)
        self.assertIn('Entrega parcial', delivery_failure.summary)

    # ------------------------------------------------------------------
    # (2) Listo pero sin entregar, sin problema de flujo
    # ------------------------------------------------------------------
    def test_ready_without_delivery_is_not_all_ok(self):
        product = self._make_product('LISTO SIN ENTREGAR (DIAG DELIVERY)')
        self._add_stock(product, 5.0)
        so = self._confirm_order(self.customer, [(product, 1.0)])
        # Producción YA ejecutada: no queda nada que fabricar (flujo sano).
        self._make_done_mo(so, product)

        board = self._board(so)
        self.assertEqual(
            board.state, 'ready',
            'El pedido está listo y aún sin entregar (etapa de entrega).')
        self.assertEqual(
            board.health_production, 'ok',
            'La fabricación ya se ejecutó: no es un quiebre de flujo.')

        wizard = self._wizard(board)
        self.assertEqual(wizard.delivery_status, 'pending')
        self.assertEqual(
            wizard.recommended_route, 'deliver',
            'La única acción pendiente es entregar el pedido.')
        self.assertEqual(wizard.root_cause_node, 'delivery')

        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        self.assertEqual(line.delivery_status, 'pending')
        self.assertEqual(line.root_cause_node, 'delivery')

        delivery_failure = line.failure_ids.filtered(
            lambda f: f.node == 'delivery')
        self.assertTrue(delivery_failure)
        self.assertEqual(
            delivery_failure.pf_cause, 'order_delivery_pending')
        self.assertEqual(
            delivery_failure.summary, 'Pendiente por entrega')
        self.assertTrue(delivery_failure.pf_solution_available)
        self.assertFalse(
            delivery_failure.pf_problem_available,
            'Síntoma y raíz coinciden (mismo albarán): un solo botón.')
        self.assertEqual(
            delivery_failure.pf_solution_label,
            'Ir a la entrega de este producto')

        # El wizard YA NO dice "todo en orden" para este producto.
        self.assertIn('Pendiente por entrega', line.status_note)
        self.assertNotIn('Todo en orden', line.status_note)
        self.assertNotIn(
            'no muestra quiebres', wizard.root_cause_detail or '')

    # ------------------------------------------------------------------
    # (3) Entregado
    # ------------------------------------------------------------------
    def test_delivered_order_has_ok_status_and_no_failure(self):
        product = self._make_product('ENTREGADO TOTAL (DIAG DELIVERY)')
        self._add_stock(product, 5.0)
        so = self._confirm_order(self.customer, [(product, 1.0)])
        self._deliver(so, {product: 1.0})

        board = self._board(so)
        self.assertTrue(board.pf_all_delivered)

        wizard = self._wizard(board)
        self.assertEqual(wizard.delivery_status, 'ok')
        self.assertNotEqual(wizard.recommended_route, 'deliver')
        self.assertFalse(
            wizard.deficit_line_ids.failure_ids.filtered(
                lambda f: f.node == 'delivery'),
            'Un pedido entregado no debe tener falla de entrega.')

    # ------------------------------------------------------------------
    # (4) Navegación a la entrega del PROPIO producto
    # ------------------------------------------------------------------
    def test_nav_line_delivery_opens_own_product_picking(self):
        product = self._make_product('PRODUCTO NAV ENTREGA (DIAG DELIVERY)')
        self._add_stock(product, 10.0)
        own_so = self._confirm_order(self.customer, [(product, 1.0)])
        other_so = self._confirm_order(self.other_customer, [(product, 1.0)])
        own_picking = own_so.picking_ids
        other_picking = other_so.picking_ids
        self.assertTrue(own_picking)
        self.assertTrue(other_picking)

        board = self._board(own_so)
        wizard = self._wizard(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        failure = line.failure_ids.filtered(lambda f: f.node == 'delivery')[:1]
        self.assertTrue(failure)

        # Acción directa del tablero: albarán del propio pedido, no el ajeno.
        action = board.action_open_product_delivery(product)
        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['res_id'], own_picking.id)
        self.assertNotEqual(action['res_id'], other_picking.id)

        # La falla navega por el MISMO destino (target 'line_delivery').
        nav = failure._pf_nav_action('line_delivery')
        self.assertEqual(nav['res_model'], 'stock.picking')
        self.assertEqual(nav['res_id'], own_picking.id)

        # El botón de fila usa la MISMA acción del tablero.
        nav_button = line.action_open_line_delivery()
        self.assertEqual(nav_button['res_model'], 'stock.picking')
        self.assertEqual(nav_button['res_id'], own_picking.id)

    def test_nav_falls_back_to_order_delivery_without_error(self):
        product_in = self._make_product('EN PEDIDO ENTREGA (DIAG DELIVERY)')
        product_out = self._make_product('FUERA PEDIDO ENTREGA (DIAG DELIVERY)')
        self._add_stock(product_in, 10.0)
        so = self._confirm_order(self.customer, [(product_in, 1.0)])
        own_picking = so.picking_ids
        board = self._board(so)

        # El producto no está en ningún albarán del pedido: se cae a la entrega
        # del pedido (nunca a la bandeja de albaranes ajenos) y NO lanza error.
        action = board.action_open_product_delivery(product_out)
        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['res_id'], own_picking.id)

    def test_nav_closes_without_error_when_no_delivery(self):
        product = self._make_product('SIN ALBARAN ENTREGA (DIAG DELIVERY)')
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        action = board.action_open_product_delivery(product)
        self.assertEqual(action['type'], 'ir.actions.act_window_close')
