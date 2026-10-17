# -*- coding: utf-8 -*-
"""Paridad del motor unificado de flujo con el motor de salud (PrintFlow).

El orquestador ``printflow.product.flow.diagnostic._pf_flow_verdict`` es PURO y
debe reproducir EXACTAMENTE los semáforos, la severidad, las fallas y el nodo de
quiebre que produce hoy el motor ``printflow.order.health.engine``. Este test es
la red de seguridad de la Fase 0: si el orquestador divergiera, aquí se rompe.
"""

from odoo.tests.common import TransactionCase, tagged


class _FakeMove:
    """Movimiento de consumo mínimo que consume ``_pf_mo_waiting_material``."""

    def __init__(self, state, quantity, demand):
        self.state = state
        self.quantity = quantity
        self.product_uom_qty = demand


class _FakeMO:
    """MO mínima (solo ``move_raw_ids``) para los contextos planos del test."""

    def __init__(self, moves):
        self.move_raw_ids = moves


@tagged('post_install', '-at_install')
class TestDiagnosticFlowEngineParity(TransactionCase):
    """El orquestador puro == motor de salud, para contextos planos."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flow = cls.env['printflow.product.flow.diagnostic']
        cls.Engine = cls.env['printflow.order.health.engine']

    # ------------------------------------------------------------------
    # Reconstrucción canónica (el MISMO mapeo que usa el wizard)
    # ------------------------------------------------------------------
    def _engine_verdict(self, ctx):
        engine = self.Engine
        prod_data = {
            'active_mos': ctx.get('active_mos') or [],
            'done_mos': ctx.get('done_mos') or [],
            'has_draft_mo': ctx.get('has_draft_mo'),
            'in_production_stage': ctx.get('in_production_stage'),
            'procurement_type': ctx.get('procurement_type'),
            'design_pending': ctx.get('design_pending'),
            'production_alert': ctx.get('production_alert'),
            'in_delivery_stage': ctx.get('in_delivery_stage'),
            'is_stock_covered': ctx.get('is_stock_covered'),
            'is_late_material': ctx.get('is_late_material'),
        }
        # Solo se agrega la clave si el llamador la resolvió (fallback histórico).
        if 'is_manufacturable' in ctx:
            prod_data['is_manufacturable'] = ctx.get('is_manufacturable')
        sale = ctx.get('sale_status') or (
            'ok' if ctx.get('is_finished', True) else 'na')
        delivery = ctx.get('delivery_status') or 'na'
        deficit = ctx.get('deficit_qty') or 0.0
        contention = ctx.get('contention_qty') or 0.0
        stock = engine._pf_product_stock({
            'deficit_qty': deficit,
            'contention_qty': contention,
            'in_over_reserved': bool(ctx.get('in_over_reserved')),
            'is_stock_tracked': ctx.get('is_stock_tracked'),
        })
        purchase = engine._pf_product_supply({
            'purchase_ok': ctx.get('purchase_ok'),
            'incoming_qty': ctx.get('incoming_qty') or 0.0,
            'deficit_qty': deficit,
            'pending_product_ids': ctx.get('pending_product_ids') or set(),
            'order_health_supply': ctx.get('order_health_supply'),
            'product_id': ctx.get('product_id'),
            'is_stock_tracked': ctx.get('is_stock_tracked'),
        })
        production = engine._pf_product_production(prod_data)
        if ctx.get('unconfirmed'):
            stock = purchase = production = 'na'
        anomaly = bool(ctx.get('reservation_anomaly'))
        severity = engine._pf_product_severity({
            'sale_status': sale, 'stock_status': stock,
            'purchase_status': purchase, 'production_status': production,
            'delivery_status': delivery, 'reservation_anomaly': anomaly,
        })
        failures = engine._pf_product_failures({
            'sale_status': sale, 'stock_status': stock,
            'purchase_status': purchase, 'production_status': production,
            'delivery_status': delivery,
            'delivery_delivered': ctx.get('delivery_delivered'),
            'delivery_required': ctx.get('delivery_required'),
            'deficit_qty': deficit, 'contention_qty': contention,
            'reservation_anomaly': anomaly,
            # Paridad: el mismo remedio físico que recibe el motor de flujo.
            'physical_remedy': ctx.get('physical_remedy'),
            # Paridad: productos que NO gestionan inventario no emiten fallas
            # de stock/compra.
            'is_stock_tracked': ctx.get('is_stock_tracked'),
            # Arte pendiente: señal ADICIONAL (misma entrada que el motor real).
            'design_pending': ctx.get('design_pending'),
        })
        return {
            'sale_status': sale, 'stock_status': stock,
            'purchase_status': purchase, 'production_status': production,
            'delivery_status': delivery, 'severity': severity,
            'failures': failures,
        }

    def _assert_parity(self, ctx):
        verdict = self.Flow._pf_flow_verdict(ctx)
        expected = self._engine_verdict(ctx)
        for key in ('sale_status', 'stock_status', 'purchase_status',
                    'production_status', 'delivery_status', 'severity'):
            self.assertEqual(
                verdict[key], expected[key],
                'Divergencia en %s para ctx=%s' % (key, ctx))
        self.assertEqual(verdict['failures'], expected['failures'])
        return verdict

    # ------------------------------------------------------------------
    # Escenarios
    # ------------------------------------------------------------------
    def test_ok_flow(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
        })
        self.assertEqual(verdict['stock_status'], 'ok')
        self.assertFalse(verdict['root_cause_node'])

    def test_physical_deficit_purchasable(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'deficit_qty': 5.0, 'physical_remedy': 'buy_product',
        })
        self.assertEqual(verdict['stock_status'], 'deficit')
        self.assertEqual(verdict['purchase_status'], 'missing')
        self.assertEqual(verdict['root_cause_node'], 'purchase')
        # Un déficit físico se clasifica por su remedio físico (comprar), no
        # por la causa genérica de compra faltante: el remedio manda.
        self.assertEqual(verdict['cause'], 'buy_product')
        self.assertEqual(verdict['remedy_key'], 'buy_product')

    def test_contention_keeps_free_exhausted(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'contention_qty': 3.0,
        })
        self.assertEqual(verdict['stock_status'], 'over')
        self.assertEqual(verdict['root_cause_node'], 'stock')

    def test_reservation_anomaly(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'reservation_anomaly': True,
        })
        # La anomalía no cambia el semáforo de stock (libre agregado >= 0)…
        self.assertEqual(verdict['stock_status'], 'ok')
        # …pero sí aparece como falla data_anomaly en el motor.
        self.assertTrue(
            any(f['pf_cause'] == 'data_anomaly' for f in verdict['failures']))

    def test_no_mo_production(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_delivery_stage': True,
            'is_stock_covered': False,
        })
        self.assertEqual(verdict['production_status'], 'no_mo')
        self.assertEqual(verdict['root_cause_node'], 'production')
        self.assertEqual(verdict['cause'], 'manufacture')

    def test_mo_stuck_production(self):
        stuck_mo = _FakeMO([_FakeMove('confirmed', 0.0, 5.0)])
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_delivery_stage': True,
            'active_mos': [stuck_mo], 'is_late_material': False,
            # El flag lo define el llamador (default False desde E6).
            'mo_stuck': True,
        })
        self.assertEqual(verdict['production_status'], 'material')
        self.assertEqual(verdict['cause'], 'mo_stuck')
        self.assertEqual(verdict['remedy_key'], 'prioritize_mo')

    def test_mo_stuck_requires_explicit_flag(self):
        """Sin ``mo_stuck`` explícito el motor NO fabrica la causa ``mo_stuck``."""
        stuck_mo = _FakeMO([_FakeMove('confirmed', 0.0, 5.0)])
        verdict = self.Flow._pf_flow_verdict({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_delivery_stage': True,
            'active_mos': [stuck_mo], 'is_late_material': False,
        })
        self.assertEqual(verdict['production_status'], 'material')
        self.assertNotEqual(verdict['cause'], 'mo_stuck')

    def test_to_launch_draft_mo(self):
        """MO en BORRADOR -> ``to_launch`` (bloqueo duro) y causa ``mo_stuck``."""
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_production_stage': True,
            'has_draft_mo': True, 'is_stock_covered': False,
            'active_mos': [], 'done_mos': [],
            'mo_stuck': True,
        })
        self.assertEqual(verdict['production_status'], 'to_launch')
        self.assertEqual(verdict['root_cause_node'], 'production')
        self.assertEqual(verdict['cause'], 'mo_stuck')
        self.assertEqual(verdict['remedy_key'], 'prioritize_mo')

    def test_delivery_pending(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'delivery_status': 'pending',
        })
        self.assertEqual(verdict['root_cause_node'], 'delivery')
        self.assertEqual(verdict['cause'], 'order_delivery_pending')

    def test_unconfirmed_forces_na(self):
        verdict = self._assert_parity({
            'is_finished': True, 'sale_status': 'pending', 'purchase_ok': True,
            'unconfirmed': True, 'deficit_qty': 2.0,
        })
        self.assertEqual(verdict['stock_status'], 'na')
        self.assertEqual(verdict['purchase_status'], 'na')
        self.assertEqual(verdict['production_status'], 'na')

    def test_consumable_not_stock_skips_deficit(self):
        """Un producto que NO gestiona inventario no produce déficit ni compra."""
        verdict = self._assert_parity({
            'is_finished': False, 'sale_status': 'na', 'purchase_ok': True,
            'deficit_qty': 5.0, 'is_stock_tracked': False,
        })
        self.assertEqual(verdict['stock_status'], 'ok')
        self.assertEqual(verdict['purchase_status'], 'na')
        self.assertFalse(verdict['failures'])
        self.assertFalse(verdict['root_cause_node'])

    def test_stock_tracked_keeps_deficit(self):
        """Contra-prueba: con inventario, el déficit sigue mandando."""
        verdict = self._assert_parity({
            'is_finished': False, 'sale_status': 'na', 'purchase_ok': True,
            'deficit_qty': 5.0, 'is_stock_tracked': True,
        })
        self.assertEqual(verdict['stock_status'], 'deficit')
        self.assertEqual(verdict['purchase_status'], 'missing')
