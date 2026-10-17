# -*- coding: utf-8 -*-
"""Regresión BUG 1: el recálculo del wizard debe refrescar el ``health_stock``
VIEJO del tablero antes de reconstruir el snapshot.

El nodo INVENTARIO del wizard usa el semáforo del tablero como RESPALDO cuando
el desglose numérico por producto no detecta déficit ni contención. Si ese
semáforo quedó obsoleto (la tarjeta no se recalculó tras corregir la reserva),
el wizard seguía mostrando 'over' (SOBREPEDIDO fantasma), como en S07301.

Este test reproduce el escenario: se crea una tarjeta con sobre-reserva REAL
(el semáforo queda 'over'), se crea el wizard y DESPUÉS se corrige la reserva
física sin tocar el tablero (el campo almacenado queda viejo). ``action_recalculate``
debe refrescar la tarjeta y el wizard debe dejar de reportar 'over'.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticRecalculateHealthRefresh(TransactionCase):
    """El recálculo del wizard refresca el semáforo de stock acotado al pedido."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Recalc Health (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.manu_type = cls.warehouse.manu_type_id
        # Segunda ubicación interna: permite que el AGREGADO del producto tenga
        # libre aunque un quant puntual esté sobre-reservado (patrón S07301).
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'RECALC HEALTH EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_finished(self, name):
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _make_sale(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        # Confirmado a la fuerza, sin disparar la procura (escenario controlado).
        so.write({'state': 'sale'})
        return so

    def _make_done_mo(self, so, product):
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

    def _over_reserve_with_free_stock(self, product):
        """Sobre-reserva REAL: el libre AGREGADO del producto queda negativo.

        Decisión 1: el tablero decide con el libre agregado, así que para que
        marque 'over' no basta un quant suelto compensado por otro; el total del
        producto debe quedar en negativo.
        """
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, quantity=1.0, reserved_quantity=5.0)

    def _clear_over_reservation(self, product):
        """Quita la sobre-reserva del quant (queda libre >= 0)."""
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.stock_location.id),
        ], limit=1)
        self.assertTrue(quant)
        quant.write({'reserved_quantity': 0.0})

    # ------------------------------------------------------------------
    # Caso
    # ------------------------------------------------------------------
    def test_recalculate_refreshes_stale_health_stock(self):
        finished = self._make_finished('TERMINADO STALE HEALTH (DIAG)')
        so = self._make_sale(finished, 1.0)
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        self._make_done_mo(so, finished)
        self._over_reserve_with_free_stock(finished)

        # Semáforo REAL en 'over' (libre agregado negativo por reserva colgada).
        board.recompute_states(domain=[('id', '=', board.id)])
        self.assertTrue(board.is_stock_missing)
        self.assertEqual(board.health_stock, 'over')

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        self.assertEqual(wizard.stock_status, 'over')

        # Se corrige la reserva física PERO nadie recalcula la tarjeta: el
        # semáforo almacenado queda VIEJO (los quants no son dependencia de
        # ``health_stock``), reproduciendo la causa del BUG 1.
        self._clear_over_reservation(finished)
        wizard.invalidate_recordset(['stock_status'])
        self.assertEqual(
            board.health_stock, 'over',
            'El semáforo debe seguir viejo para reproducir el fallback.')
        # El snapshot directo cae al respaldo del tablero y muestra 'over'.
        stale_snapshot, _lines = wizard._build_snapshot(board)
        self.assertEqual(
            stale_snapshot['stock_status'], 'over',
            'Sin recálculo, el wizard hereda el semáforo obsoleto del tablero.')

        # Con el recálculo, la tarjeta se refresca y el wizard deja de mentir.
        wizard.action_recalculate()
        self.assertFalse(board.is_stock_missing)
        self.assertEqual(
            board.health_stock, 'ok',
            'El recálculo acotado debe limpiar el SOBREPEDIDO viejo.')
        self.assertEqual(
            wizard.stock_status, 'ok',
            'El wizard debe dejar de reportar SOBREPEDIDO tras refrescar.')
        finished_line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == finished)
        self.assertTrue(finished_line)
        self.assertEqual(finished_line.stock_status, 'ok')
