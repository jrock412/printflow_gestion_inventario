# -*- coding: utf-8 -*-
"""FASE 5 — Bandeja de Resolución del PEDIDO (PrintFlow).

La falla del diagnóstico de pedido abre su bandeja de causantes recolectables
(esquema compartido con el escáner) y cada causante navega a su registro real.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticOrderCollectTray(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Bandeja Pedido'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _failure(self, cause, node='stock'):
        product = self._pf_product('BANDEJA PEDIDO', x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        board = self._pf_force_board(product, 3.0)
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        self.assertTrue(line)
        failure = self.env['printflow.order.diagnostic.failure'].create({
            'line_id': line.id,
            'node': node,
            'pf_cause': cause,
        })
        return failure, product

    def test_collect_tray_opens_and_lists_causantes(self):
        failure, product = self._failure('free_exhausted')
        action = failure.action_open_collect_tray()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(
            action['res_model'], 'printflow.order.diagnostic.evidence')
        self.assertEqual(action['target'], 'current')

        evidences = self.env['printflow.order.diagnostic.evidence'].search(
            [('failure_id', '=', failure.id)])
        self.assertTrue(evidences)
        self.assertTrue(evidences.filtered(lambda e: e.collectible))
        # El producto siempre entra como causante navegable.
        product_ev = evidences.filtered(
            lambda e: e.causante_type == 'product')
        self.assertTrue(product_ev)
        self.assertEqual(product_ev.product_id, product)

    def test_collect_tray_is_read_only_navigation(self):
        failure, _product = self._failure('free_exhausted')
        failure.action_open_collect_tray()
        evidences = self.env['printflow.order.diagnostic.evidence'].search(
            [('failure_id', '=', failure.id)])
        # action_open devuelve una acción, nunca ejecuta cambios.
        action = evidences[:1].action_open()
        self.assertIn(action['type'], ('ir.actions.act_window',))
