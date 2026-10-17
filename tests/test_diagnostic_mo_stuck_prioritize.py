# -*- coding: utf-8 -*-
"""Caso d: OF existente trabada -> remedio ``prioritize_mo`` (solo navegar).

El diagnóstico es de SOLO LECTURA: el botón de la OF únicamente NAVEGA; nunca
ejecuta ``action_confirm`` ni planificación. El motor unificado clasifica la OF
trabada como causa ``mo_stuck``.
"""

from odoo.tests.common import TransactionCase, tagged

from ..models.printflow_resolution_playbook import PF_CAUSE_SELECTION


class _FakeMove:
    def __init__(self, state, quantity, demand):
        self.state = state
        self.quantity = quantity
        self.product_uom_qty = demand


class _FakeMO:
    def __init__(self, moves):
        self.move_raw_ids = moves


@tagged('post_install', '-at_install')
class TestDiagnosticMoStuckPrioritize(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Playbook = cls.env['printflow.resolution.playbook']
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Flow = cls.env['printflow.product.flow.diagnostic']

    def test_cause_is_registered(self):
        self.assertIn('mo_stuck', dict(PF_CAUSE_SELECTION))

    def test_playbook_navigates_to_mo(self):
        plan = self.Playbook._pf_get_plan('mo_stuck')
        solution = plan['actions']['solution']
        self.assertEqual(solution['kind'], 'navigate')
        self.assertEqual(solution['target'], 'mo')
        self.assertTrue(solution['available'])
        self.assertTrue(plan['steps'])
        # Síntoma y raíz coinciden: se ofrece un solo botón.
        self.assertFalse(plan['actions']['problem']['available'])

    def test_remedy_meta_navigates_to_mo(self):
        label, kind, target = self.Remedy._pf_remedy_meta('prioritize_mo')
        self.assertTrue(label)
        self.assertEqual(kind, 'navigate')
        self.assertEqual(target, 'mo')

    def test_orchestrator_classifies_stuck_mo(self):
        stuck = _FakeMO([_FakeMove('confirmed', 0.0, 5.0)])
        # El flag ``mo_stuck`` lo define el llamador (default False desde E6).
        verdict = self.Flow._pf_flow_verdict({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_delivery_stage': True,
            'active_mos': [stuck], 'is_late_material': False,
            'mo_stuck': True,
        })
        self.assertEqual(verdict['production_status'], 'material')
        self.assertEqual(verdict['cause'], 'mo_stuck')
        self.assertEqual(verdict['remedy_key'], 'prioritize_mo')
