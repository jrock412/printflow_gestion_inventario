# -*- coding: utf-8 -*-
"""Panel de fallas del diagrama de PRODUCTO (PrintFlow · Fase 5).

Custodia que cada fila del panel del producto:
  * trae ``label``/``detail`` y su ``plan_summary`` (playbook);
  * cablea sus acciones al MISMO wizard ``printflow.product.flow`` (nunca a la
    falla de un pedido), con los dispatchers públicos ``action_run_pf_node`` /
    ``action_run_pf_plan``.

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowPanel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Panel Producto', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']

    def _purchasable(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True, 'purchase_ok': True,
            'seller_ids': [(0, 0, {'partner_id': self.supplier.id})],
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _broken_purchasable(self, name):
        product = self._purchasable(name)
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        return product

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _rows(self, wizard):
        payload = json.loads(wizard.timeline_json)
        return [
            row for node in payload['nodes'] for row in node.get('panel', [])
        ]

    # ------------------------------------------------------------------
    # 1) Las acciones de cada fila apuntan al wizard del PRODUCTO
    # ------------------------------------------------------------------
    def test_panel_rows_are_wired_to_product_flow(self):
        wizard = self._wizard(self._broken_purchasable('PANEL PRODUCTO'))
        rows = self._rows(wizard)
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row['label'])
            self.assertTrue(row['detail'])
            for action in row['actions']:
                self.assertEqual(
                    action['res_model'], 'printflow.product.flow')
                self.assertEqual(action['res_id'], wizard.id)
                self.assertIn(
                    action['method'],
                    ('action_run_pf_node', 'action_run_pf_plan'))

    # ------------------------------------------------------------------
    # 2) El resumen del plan sale del PLAYBOOK (fuente única)
    # ------------------------------------------------------------------
    def test_panel_plan_summary_matches_playbook(self):
        wizard = self._wizard(self._broken_purchasable('PANEL PLAYBOOK'))
        ctx = wizard._pf_product_canvas_ctx()
        playbook = self.env['printflow.resolution.playbook']
        playbook_ctx = ctx['playbook_ctx']
        expected = {
            playbook._pf_get_plan(failure['pf_cause'], ctx=playbook_ctx)[
                'summary']
            for failure in ctx['failures']
            if failure.get('pf_cause')
        }
        self.assertTrue(expected)
        row_summaries = {row['plan_summary'] for row in self._rows(wizard)}
        self.assertTrue(row_summaries)
        self.assertTrue(row_summaries <= expected)

    # ------------------------------------------------------------------
    # 3) La fila de una CONSECUENCIA no ofrece "Solucionar" (paridad pedido)
    # ------------------------------------------------------------------
    def test_consequence_row_hides_solution(self):
        wizard = self._wizard(self._broken_purchasable('PANEL CONSECUENCIA'))
        payload = json.loads(wizard.timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        consequence_rows = [
            row for row in by_key['stock']['panel'] if row['is_consequence']]
        self.assertTrue(consequence_rows)
        for row in consequence_rows:
            self.assertFalse(row['solution_available'])
            self.assertNotIn(
                'solution', [a['key'] for a in row['actions']])
