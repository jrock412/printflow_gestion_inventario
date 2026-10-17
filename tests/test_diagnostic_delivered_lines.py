# -*- coding: utf-8 -*-
"""Regresión S07301: una línea YA ENTREGADA no debe generar falso positivo.

Antes el diagnóstico trataba como demanda la cantidad TOTAL pedida, sin restar
lo entregado. Como el producto FONDO NEGRO (id 13058) tenía un quant global
sobre-reservado por otros pedidos POS, la compuerta de sobre-reserva marcaba su
línea 100% entregada con la falla "Sobrepedido" (``free_exhausted``) y el semáforo
del tablero la señalaba como ``is_stock_missing``.

La corrección usa la demanda PENDIENTE (``product_uom_qty - qty_delivered``):
  * Línea 100% entregada -> demanda 0 -> sin falla de inventario.
  * Línea parcialmente entregada -> solo la parte pendiente cuenta.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticDeliveredLines(TransactionCase):
    """El diagnóstico solo debe mirar la demanda pendiente de cada línea."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Entregas Diagnóstico (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.manu_type = cls.warehouse.manu_type_id
        # Segunda ubicación interna: permite un quant sobre-reservado (libre < 0)
        # y otro con existencia libre, como en el caso real S07301.
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'REGRESION ENTREGA EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

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

    def _make_done_mo(self, so, product):
        """MO en ``done`` vinculada al pedido (activa la compuerta del tablero).

        Se usa el ``procurement_group`` NATIVO del pedido confirmado para que el
        vínculo ``mrp.production.sale_id`` (y por ende ``sale.order.mrp_production_ids``)
        quede bien resuelto.
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

    def _over_reserve_with_free_stock(self, product):
        """Un quant con libre < 0 + otro con libre > 0 (patrón S07301).

        El agregado del producto conserva libre para el pedido
        (``contention_qty == 0``); la única señal es la sobre-reserva GLOBAL.
        """
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, quantity=1.0, reserved_quantity=5.0)
        self.env['stock.quant']._update_available_quantity(
            product, self.extra_location, quantity=10.0)

    def _confirm_order(self, lines):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.action_confirm()
        return so

    def _deliver_partial(self, so, delivered_by_product):
        """Valida el albarán entregando SOLO las cantidades indicadas.

        Lo que no se entrega queda en un albarán de reserva (backorder), de modo
        que el pedido queda parcialmente entregado.
        """
        picking = so.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking, 'La confirmación debe generar el albarán de entrega.')
        picking.action_assign()
        for move in picking.move_ids:
            qty = delivered_by_product.get(move.product_id, 0.0)
            move.quantity = qty
            move.picked = qty > 0.0
        result = picking.button_validate()
        if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
            # En Odoo 17 el wizard de backorder se inicializa por contexto
            # (``default_pick_ids``), no por ``res_id``.
            confirmation = self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({})
            confirmation.process()
        return picking

    def _recompute(self, board):
        # El vínculo nativo sale.order.mrp_production_ids se cachea al confirmar;
        # se invalida para que el puente board→MO vea la MO recién creada.
        board.mapped('sale_order_id').invalidate_model(['mrp_production_ids'])
        board.invalidate_model([
            'mrp_production_ids', 'has_production', 'pf_has_done_mo',
            'pf_any_pending_mo', 'is_stock_missing', 'production_alert',
            'procurement_type', 'state', 'health_stock', 'health_production',
            'health_severity', 'pf_all_delivered', 'is_partial_delivery',
        ])
        board._compute_mrp_production_ids()
        board._compute_production_status()
        board._compute_purchase_status()
        board._compute_delivery_status()
        board._compute_is_stock_missing()
        board._compute_state()
        board._compute_health_flags()
        return board

    # ------------------------------------------------------------------
    # 1. Línea 100% entregada + quant sobre-reservado global -> sin falla
    # ------------------------------------------------------------------
    def test_delivered_line_with_global_over_reservation_has_no_stock_failure(self):
        finished = self._make_product('FONDO NEGRO (REGRESION S07301)')
        pending = self._make_product('PLASTIFICACION (REGRESION S07301)')
        # Ambos con stock: el primero se entrega y el segundo queda pendiente,
        # de modo que la única señal posible para FONDO NEGRO sea la sobre-reserva
        # global (no un déficit físico del otro producto).
        self._add_stock(finished, 10.0)
        self._add_stock(pending, 1.0)

        so = self._confirm_order([(finished, 1.0), (pending, 1.0)])
        # MO terminada del producto pendiente -> compuerta de sobre-reserva activa.
        self._make_done_mo(so, pending)
        # Entrega SOLO FONDO NEGRO; PLASTIFICACION queda en backorder.
        self._deliver_partial(so, {finished: 1.0})
        # Sobre-reserva GLOBAL del producto ya entregado (patrón S07301).
        self._over_reserve_with_free_stock(finished)

        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        self._recompute(board)

        line = so.order_line.filtered(lambda l: l.product_id == finished)
        self.assertAlmostEqual(
            line.qty_delivered, line.product_uom_qty, places=3,
            msg='La línea de FONDO NEGRO debe quedar 100% entregada.')
        self.assertEqual(board.state, 'partial_delivered')
        self.assertTrue(board.pf_has_done_mo)
        # Punto 3: el semáforo del tablero ya no marca stock faltante por una
        # línea entregada (la sobre-reserva global no es de ESTE pedido).
        self.assertFalse(
            board.is_stock_missing,
            'Una línea entregada no debe marcar is_stock_missing en el tablero.')

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        # MEJORA A: la línea entregada SÍ se muestra, pero como fila de solo
        # display: sana y sin fallas de inventario.
        delivered_line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        self.assertTrue(
            delivered_line,
            'Una línea 100% entregada SÍ debe aparecer en "Productos del pedido".')
        self.assertTrue(
            delivered_line.is_display_only,
            'La línea entregada debe marcarse como producto entregado.')
        self.assertEqual(delivered_line.flow_severity, 'ok')
        self.assertEqual(delivered_line.flow_failed_node_count, 0)
        self.assertEqual(
            delivered_line.status_note, 'Todo en orden (producto entregado)')
        free_exhausted = wizard.deficit_line_ids.failure_ids.filtered(
            lambda f: f.pf_cause == 'free_exhausted')
        self.assertFalse(
            free_exhausted,
            'No debe quedar falla de inventario "Sobrepedido" para una línea entregada.')

    # ------------------------------------------------------------------
    # 2. Línea parcialmente entregada -> solo cuenta la parte pendiente
    # ------------------------------------------------------------------
    def test_partially_delivered_line_only_counts_pending_qty(self):
        product = self._make_product('PARCIAL (REGRESION S07301)')
        self._add_stock(product, 10.0)

        so = self._confirm_order([(product, 3.0)])
        self._deliver_partial(so, {product: 1.0})

        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        self._recompute(board)

        line = so.order_line.filtered(lambda l: l.product_id == product)
        self.assertAlmostEqual(line.qty_delivered, 1.0, places=3)

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        # La demanda del mapa descuenta lo entregado: 3 - 1 = 2.
        demand = wizard._get_demand_map(board, so)
        self.assertIn(product, demand)
        self.assertAlmostEqual(
            demand[product]['qty'], 2.0, places=3,
            msg='Solo la parte pendiente (3 - 1) debe contar como demanda.')
        line_val = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line_val)
        self.assertAlmostEqual(line_val.required_qty, 2.0, places=3)
