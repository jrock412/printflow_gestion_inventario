# -*- coding: utf-8 -*-
"""P10 — El saneamiento está disponible aunque el tablero esté 'ok'.

Con un quant con libre negativo compensado, el tablero dice 'ok' pero el wizard
de diagnóstico y el escáner de producto ofrecen el saneamiento (Bloque III §28).

F1: además, el NODO de stock del diagrama detecta la anomalía POR SU CUENTA (sin
falla) y expone la acción `cleanup_reservations` en su popover.
"""
import json

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestCleanupSurfaceWhenBoardOk(PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente Superficie'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'SUPERFICIE EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

    def _anomaly_product(self, name='TERMINADO SUPERFICIE'):
        product = self._pf_product(name, x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._pf_add_stock(product, 1.0, reserved=5.0, location=self.extra_location)
        self._pf_add_stock(product, 10.0)
        return product

    def test_wizard_offers_cleanup_when_board_is_ok(self):
        product = self._anomaly_product()
        board = self._pf_force_board(product, 1.0)
        self._pf_recompute_board(board)
        self.assertEqual(board.health_stock, 'ok')

        wizard = self._pf_diagnose(board)
        self.assertTrue(wizard.pf_has_stuck_reservations)

        # F1: el NODO de stock detecta la anomalía SIN falla (el tablero está
        # 'ok') y expone "Sanear reservas colgadas" en su popover.
        line = self._pf_line(wizard, product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})
        payload = json.loads(wizard.focus_timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        stock = by_key['stock']
        self.assertTrue(stock['anomaly'])
        self.assertNotEqual(
            stock['role'], 'consequence',
            'Sin fallas el nodo de stock no puede ser una consecuencia.')
        cleanup = next(
            (action for action in stock['actions']
             if action['key'] == 'cleanup_reservations'), None)
        self.assertIsNotNone(cleanup)
        self.assertEqual(cleanup['kind'], 'run_action')
        self.assertEqual(cleanup['method'], 'action_cleanup_over_reservations')

        # El botón delega en el tablero y responde (aunque no haya albaranes).
        self.assertEqual(
            wizard.action_cleanup_order_reservations()['type'],
            'ir.actions.client')

    def test_scanner_offers_cleanup_when_board_is_ok(self):
        product = self._anomaly_product('TERMINADO SUPERFICIE ESCANER')
        scanner = self.env['printflow.product.diagnostic.wizard'].create(
            {'product_id': product.id})
        finding = scanner.finding_ids.filtered(
            lambda f: f.product_id == product)[:1]
        self.assertTrue(finding)
        self.assertTrue(finding.pf_has_stuck_reservations)
        action = finding.action_cleanup_reservations()
        self.assertEqual(action['type'], 'ir.actions.client')
