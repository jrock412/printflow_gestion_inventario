# -*- coding: utf-8 -*-
"""Consistencia Tablero <-> Wizard para el caso real S07301 (regresión).

Escenario (mismo patrón que ``test_diagnostic_recalculate_health_refresh``):
  * Un pedido de fabricación con una Orden de Fabricación TERMINADA (``done``):
    el tablero queda sano y ``health_stock='ok'``.
  * Un segundo producto PENDIENTE, CUBIERTO por existencia (2 en mano para 1 de
    demanda) y con una BoM cuyo insumo está 100% reservado por OTRO pedido.

Antes, el wizard explotaba la BoM del pendiente aunque ya tuviera stock, y la
contención del insumo se colaba como "SOBREPEDIDO" en el roll-up del terminado,
contradiciendo al tablero (que solo evalúa la sobre-reserva de los productos de
venta). Además marcaba "SIN ORDEN" a un producto que no necesita fabricarse.

La corrección NO toca las fórmulas de déficit/contención: solo deja de
ESPECULAR los insumos (y el "sin orden") de un terminado ya cubierto por
existencia cuando la producción ya se ejecutó (``pf_has_done_mo``).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticWizardBoardConsistency(TransactionCase):
    """El wizard no debe inventar SOBREPEDIDO/SIN ORDEN para un terminado cubierto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Consistencia Tablero (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.manu_type = cls.warehouse.manu_type_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        """Producto almacenable PrintFlow; sin ruta de compra (fabricación)."""
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

    def _reserve_all(self, product, qty):
        """Otro pedido confirmado se lleva TODO el stock del producto."""
        other = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        other.action_confirm()
        return other

    def _make_sale(self, lines):
        """Pedido forzado a 'sale' (sin procurement) para un escenario controlado."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        return so

    def _make_done_mo(self, so, product):
        """MO ``done`` vinculada al pedido (activa ``pf_has_done_mo``)."""
        group = self.env['procurement.group'].create({
            'name': f'{so.name} - Inmediata',
            'sale_id': so.id,
            'partner_id': so.partner_id.id,
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'origin': f'{so.name} - Inmediata',
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

    def _recompute(self, board):
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

    def _build(self):
        delivered = self._make_product('ENTREGADO CONSISTENCIA (DIAG)')
        pending = self._make_product('PENDIENTE CONSISTENCIA (DIAG)')
        component = self._make_product('INSUMO CONSISTENCIA (DIAG)')
        # El pendiente tiene BoM; su insumo está 100% reservado por otro pedido.
        self.env['mrp.bom'].create({
            'product_tmpl_id': pending.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 1.0,
            })],
        })
        self._add_stock(delivered, 10.0)
        # El pendiente YA está cubierto: 2 en mano para 1 de demanda.
        self._add_stock(pending, 2.0)
        self._add_stock(component, 10.0)
        # Otro pedido se queda con TODO el insumo (libre = 0, no < 0).
        self._reserve_all(component, 10.0)

        so = self._make_sale([(delivered, 1.0), (pending, 1.0)])
        # MO terminada -> el pedido ya pasó por fabricación (caso S07301).
        self._make_done_mo(so, delivered)

        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        self._recompute(board)
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        return board, wizard, delivered, pending, component

    # ------------------------------------------------------------------
    # Caso
    # ------------------------------------------------------------------
    def test_wizard_matches_board_when_finished_is_covered(self):
        board, wizard, _delivered, pending, component = self._build()

        # Precondiciones del caso real.
        self.assertTrue(board.pf_has_done_mo)
        self.assertFalse(board.production_alert)
        self.assertEqual(board.health_stock, 'ok')
        self.assertEqual(
            board.health_severity, 'ok',
            'El tablero debe quedar sano para que la comparación tenga sentido.')

        # El wizard NO debe contradecir al tablero: ni SOBREPEDIDO ni SIN ORDEN.
        self.assertEqual(wizard.stock_status, 'ok')
        self.assertAlmostEqual(wizard.over_reserved_total, 0.0, places=3)
        self.assertEqual(wizard.production_status, 'ok')
        # NUEVO REQUISITO (nodo Entrega): este pedido está en etapa de entrega y
        # no se ha entregado nada, así que la ruta recomendada es entregar (ya no
        # es 'none': la entrega dejó de ser invisible para el diagnóstico).
        self.assertEqual(wizard.recommended_route, 'deliver')
        self.assertEqual(wizard.delivery_status, 'pending')

        pending_line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == pending)
        self.assertEqual(len(pending_line), 1)
        self.assertEqual(pending_line.stock_status, 'ok')
        self.assertEqual(pending_line.flow_stock_status, 'ok')
        self.assertEqual(pending_line.production_status, 'na')
        self.assertEqual(pending_line.flow_production_status, 'ok')
        # La entrega pendiente sube el semáforo a 'warning' (no es quiebre de
        # flujo: stock y fabricación siguen sanos, como en el tablero).
        self.assertEqual(pending_line.delivery_status, 'pending')
        self.assertEqual(pending_line.flow_delivery_status, 'pending')
        self.assertEqual(pending_line.flow_severity, 'warning')

        # El insumo del terminado cubierto NO debe haberse estimado.
        self.assertFalse(
            wizard.deficit_line_ids.filtered(
                lambda l: l.product_id == component),
            'Un terminado cubierto no debe explotar su BoM (insumo 14445).')
        self.assertFalse(
            wizard.deficit_line_ids.failure_ids.filtered(
                lambda f: f.pf_cause == 'free_exhausted'),
            'No debe aparecer la falla "Sobrepedido" fantasma.')
