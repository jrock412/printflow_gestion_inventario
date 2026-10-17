# -*- coding: utf-8 -*-
"""Contrato de la capa de EXPLICACIÓN del diagrama de flujo (PrintFlow).

La capa ``printflow.flow.explain`` produce, por CADA nodo del canvas, un dict de
cinco claves (``headline``/``what``/``why``/``how``/``severity``). Estos tests
custodian:

  * el nodo SANO -> severidad ``ok`` y ``why``/``how`` VACÍOS;
  * el nodo con PENDIENTES -> al menos ``warn``;
  * ``how`` == los PASOS del playbook de la causa dueña;
  * un problema de LOTE -> severidad ``danger`` y los pasos del plan de ese lote;
  * los candados A/B del frontend: el panel lateral REEMPLAZA al popover.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Contrato congelado de la explicación.
EXPLAIN_KEYS = frozenset({'headline', 'what', 'why', 'how', 'severity'})


@tagged('post_install', '-at_install')
class TestFlowExplain(TransactionCase):
    """Contrato de ``printflow.flow.explain`` y del frontend del panel."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Explain = cls.env['printflow.flow.explain']
        cls.Playbook = cls.env['printflow.resolution.playbook']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _node(self, **extra):
        node = {
            'key': 'purchase', 'label': 'Compras', 'status': 'ok',
            'status_label': 'Comprado', 'summary': '', 'tone': 'ok',
            'panel': [], 'issues': 0,
        }
        node.update(extra)
        return node

    def _empty_prep(self):
        return {'lot_by_pid': {}, 'finished_pids': [], 'component_pids': []}

    # ==================================================================
    # 1) Nodo SANO: ok y vacío
    # ==================================================================
    def test_healthy_node_is_ok_and_empty(self):
        explain = self.Explain._pf_node_explain(
            'purchase', self._node(), {}, self._empty_prep(), node_pending=0)
        self.assertEqual(set(explain), EXPLAIN_KEYS)
        self.assertEqual(explain['severity'], 'ok')
        self.assertEqual(explain['why'], [])
        self.assertEqual(explain['how'], [])
        self.assertTrue(explain['headline'])
        self.assertTrue(explain['what'])

    # ==================================================================
    # 2) Con PENDIENTES: al menos warn
    # ==================================================================
    def test_pending_node_is_at_least_warn(self):
        explain = self.Explain._pf_node_explain(
            'purchase', self._node(), {}, self._empty_prep(), node_pending=2)
        self.assertIn(explain['severity'], ('warn', 'danger'))
        self.assertTrue(explain['why'])

    # ==================================================================
    # 3) how == pasos del playbook de la causa dueña
    # ==================================================================
    def test_how_matches_playbook_steps(self):
        cause = 'buy_product'
        node = self._node(
            status='missing', status_label='Falta comprar',
            summary='Falta comprar', tone='danger')
        explain = self.Explain._pf_node_explain(
            'purchase', node, {}, self._empty_prep(),
            owner_failure={'pf_cause': cause}, node_pending=0)
        self.assertEqual(explain['severity'], 'danger')
        self.assertEqual(
            explain['how'], self.Playbook._pf_get_plan(cause)['steps'])

    # ==================================================================
    # 4) Problema de LOTE: danger + plan del estado de lote
    # ==================================================================
    def test_lot_problem_uses_lot_plan(self):
        lot_info = {'state': 'lot_no_stock', 'no_stock_lot_ids': [1]}
        prep = {
            'lot_by_pid': {7: lot_info},
            'finished_pids': [7], 'component_pids': [],
        }
        node = self._node(
            key='delivery', label='Entrega', tone='na',
            status_label='Sin dato / N/A')
        explain = self.Explain._pf_node_explain('delivery', node, {}, prep)
        self.assertEqual(explain['severity'], 'danger')
        self.assertTrue(
            any('lote' in reason.lower() for reason in explain['why']))
        lot_plan = self.Playbook._pf_get_plan('lot_no_stock')
        for step in lot_plan['steps']:
            self.assertIn(step, explain['how'])

    # ==================================================================
    # 5) Candado A: la plantilla tiene el panel y YA NO el popover
    # ==================================================================
    def test_timeline_template_has_explain_panel(self):
        module_path = get_module_path('printflow_gestion_inventario')
        template_path = os.path.join(
            module_path, 'static', 'src', 'xml', 'printflow_order_timeline.xml')
        with open(template_path, encoding='utf-8') as handle:
            xml = handle.read()
        self.assertIn(
            'o_pf_flow_explain_panel', xml,
            'La plantilla debe traer el panel lateral de explicación.')
        self.assertNotIn(
            'o_pf_flow_popover', xml,
            'El popover flotante debe haber sido REEMPLAZADO por el panel.')

    # ==================================================================
    # 6) Candado B: el JS ya no posiciona popover y sí lee la geometría
    # ==================================================================
    def test_widget_js_has_no_popover_position(self):
        module_path = get_module_path('printflow_gestion_inventario')
        js_path = os.path.join(
            module_path, 'static', 'src', 'js', 'printflow_order_timeline.js')
        with open(js_path, encoding='utf-8') as handle:
            js = handle.read()
        self.assertNotIn('_popoverPosition', js)
        self.assertNotIn('POPOVER_WIDTH', js)
        self.assertIn('payload.layout.cell', js)
