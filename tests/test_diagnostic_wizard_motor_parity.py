# -*- coding: utf-8 -*-
"""Paridad Tablero <-> Wizard Nivel 1 vía el MOTOR de salud (regresión S07301).

El Tablero de Pedidos y el Wizard de Diagnóstico deben contar la MISMA historia
para el mismo pedido. La única fuente de verdad del estado por producto es
``printflow.order.health.engine``; el wizard ya no reimplementa reglas.

Patrón del caso real (tarjeta 3669 / S07301):
  * Una línea tiene su Orden de Fabricación TERMINADA (``state='done'``): NO debe
    aparecer "Sin orden de fabricación" (el wizard viejo solo miraba MOs activas).
  * Un producto tiene un quant con libre < 0 COMPENSADO por otro quant con libre
    positivo (reserva colgada / anomalía). Decisión 1: el tablero ya NO marca el
    falso "sobre pedido" (usa el libre AGREGADO), pero el diagnóstico SÍ detecta
    la reserva colgada y recomienda sanearla (nunca comprar/fabricar).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticWizardMotorParity(TransactionCase):
    """El estado por producto del wizard se calcula llamando al motor."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Motor Parity (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.manu_type = cls.warehouse.manu_type_id
        # Segunda ubicación interna: permite tener DOS quants del mismo producto
        # (uno sobre-reservado y otro con existencia libre), como en el caso real.
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'REGRESION PARITY EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_finished(self, name):
        """Terminado PrintFlow de FABRICACIÓN (sin ruta de compra)."""
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _make_sale(self, lines):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        # Pedido confirmado a la fuerza, sin disparar la procura: el escenario
        # controlado que ya usan los tests del diagnóstico.
        so.write({'state': 'sale'})
        return so

    def _make_done_mo(self, so, product):
        """MO en estado ``done`` vinculada al pedido (patrón S07301)."""
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
        """Un quant sobre-reservado (libre < 0) + otro con libre > 0.

        Así el AGREGADO del producto sigue teniendo libre para el pedido
        (``contention_qty == 0``) y la única señal de sobrepedido es la
        sobre-reserva GLOBAL por quant, justo como en S07301.
        """
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, quantity=1.0, reserved_quantity=5.0)
        self.env['stock.quant']._update_available_quantity(
            product, self.extra_location, quantity=10.0)

    def _recompute(self, board):
        board.invalidate_model([
            'mrp_production_ids', 'has_production', 'pf_has_done_mo',
            'pf_any_pending_mo', 'is_stock_missing', 'production_alert',
            'procurement_type', 'state', 'health_stock', 'health_production',
            'health_severity',
        ])
        board._compute_mrp_production_ids()
        board._compute_production_status()
        board._compute_purchase_status()
        board._compute_is_stock_missing()
        board._compute_state()
        board._compute_health_flags()
        return board

    # ------------------------------------------------------------------
    # Regresión
    # ------------------------------------------------------------------
    def test_done_mo_and_global_over_reservation_match_board(self):
        finished = self._make_finished('FONDO NEGRO (PARITY REGRESION)')
        other = self._make_finished('PLASTIFICACION (PARITY REGRESION)')

        so = self._make_sale([(finished, 1.0), (other, 1.0)])
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})

        # (i) MO TERMINADA del producto principal.
        self._make_done_mo(so, finished)
        # (ii) Sobre-reserva GLOBAL sobre ese mismo producto.
        self._over_reserve_with_free_stock(finished)
        self._recompute(board)

        # Precondiciones del caso real.
        self.assertTrue(board.pf_has_done_mo, 'La MO hecha debe contar.')
        self.assertEqual(board.mrp_production_ids.product_id, finished)
        self.assertIn(board.state, ('ready', 'partial_delivered'))
        # Decisión 1: el libre AGREGADO del producto alcanza (1 + 10 - 5 = 6),
        # así que el tablero YA NO marca un falso "sobre pedido".
        self.assertEqual(
            board.health_stock, 'ok',
            'El libre agregado alcanza: no debe haber falso sobrepedido.')

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        self.assertEqual(len(line), 1)

        # (i) Con la MO TERMINADA, producción NO es 'no_mo' (falso "Sin orden").
        self.assertNotEqual(
            line.production_status, 'no_mo',
            'Una MO terminada no debe leerse como "sin orden de fabricación".')
        self.assertFalse(
            line.failure_ids.filtered(lambda f: f.node == 'production'),
            'La MO hecha no debe generar falla de fabricación.',
        )

        # (ii) El diagnóstico SÍ detecta la reserva colgada (anomalía) y ofrece
        # el saneamiento; NUNCA comprar/fabricar.
        # Bloque III §27: el libre AGREGADO no es negativo, así que la línea NO
        # se marca "Sobrepedido" (stock_status='ok'); la anomalía se expone como
        # una falla `data_anomaly` ("Reserva colgada").
        self.assertEqual(line.stock_status, 'ok')
        stock_failure = line.failure_ids.filtered(lambda f: f.node == 'stock')
        self.assertTrue(stock_failure)
        self.assertEqual(stock_failure.pf_cause, 'data_anomaly')
        self.assertIn('reserva colgada', stock_failure.summary.lower())
        self.assertNotIn('sobrepedido', stock_failure.summary.lower())
        # La sobre-reserva global NO es contención propia del pedido: no debe
        # mostrarse una cifra engañosa "0.00".
        self.assertAlmostEqual(line.contention_qty, 0.0, places=3)
        self.assertNotIn('0.00', stock_failure.summary)
        # Bloque II: naturaleza anomalía + remedio de re-reserva (no compra).
        self.assertEqual(stock_failure.pf_reservation_nature, 'anomaly')
        self.assertEqual(stock_failure.pf_remedy_kind, 'run_action')
        self.assertEqual(
            stock_failure.pf_remedy_target, 'fix_over_reservation')
        self.assertEqual(
            stock_failure.pf_solution_kind, 'run_action')
        self.assertEqual(
            stock_failure.pf_solution_target, 'fix_over_reservation')
