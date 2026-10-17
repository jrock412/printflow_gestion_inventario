# -*- coding: utf-8 -*-
"""F1 — El NODO detecta la reserva colgada por su cuenta (sin falla).

El diagrama de línea de tiempo migra el aviso amarillo "Reserva colgada" al NODO
de stock: aunque el tablero esté 'ok' y NO exista una falla/raíz, el hito de
stock se marca ``anomaly=True`` y ofrece la acción ``cleanup_reservations``
(saneamiento de todo el pedido). La detección usa
``printflow.stock.remedy._pf_negative_quant_product_ids``, NO la cadena de fallas.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticNodeAnomalyAction(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Anomalía Nodo',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'ANOMALIA NODO EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

    def _anomaly_finished(self, name):
        """Terminado comprado con un quant de libre negativo (reserva colgada)."""
        product = self._pf_product(name, x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._pf_add_stock(
            product, 1.0, reserved=5.0, location=self.extra_location)
        self._pf_add_stock(product, 10.0)
        return product

    # ------------------------------------------------------------------
    # 1) Nodo de stock con anomalía y SIN falla (tablero 'ok')
    # ------------------------------------------------------------------
    def test_stock_node_detects_anomaly_without_failure(self):
        product = self._anomaly_finished('NODO ANOMALIA SIN FALLA')
        board = self._pf_force_board(product, 1.0)
        self._pf_recompute_board(board)
        self.assertEqual(board.health_stock, 'ok')

        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})

        payload = json.loads(wizard.focus_timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        stock = by_key['stock']

        self.assertTrue(stock['anomaly'])
        self.assertNotEqual(stock['role'], 'consequence')
        keys = [action['key'] for action in stock['actions']]
        self.assertIn('cleanup_reservations', keys)
        cleanup = next(
            action for action in stock['actions']
            if action['key'] == 'cleanup_reservations')
        self.assertEqual(cleanup['kind'], 'run_action')
        self.assertEqual(cleanup['method'], 'action_cleanup_over_reservations')
        self.assertEqual(cleanup['res_model'], 'printflow.order.board')

    # ------------------------------------------------------------------
    # 2) La detección USA los quants negativos, no la cadena de fallas
    # ------------------------------------------------------------------
    def test_anomaly_detected_by_own_negative_quant_helper(self):
        product = self._anomaly_finished('NODO ANOMALIA SIN CADENA')
        board = self._pf_force_board(product, 1.0)
        self._pf_recompute_board(board)
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)

        # El helper parte de los quants negativos del subárbol (independiente de
        # `flow_failure_ids` / `root_cause_node`).
        product_ids = [
            member['product_id']
            for member in wizard._pf_collect_subtree(line)
        ]
        negative = self.env[
            'printflow.stock.remedy']._pf_negative_quant_product_ids(
                product_ids)
        self.assertIn(product.id, negative)
        self.assertEqual(wizard._pf_anomaly_node_keys(line), {'stock'})

    # ------------------------------------------------------------------
    # 3) El guard de consecuencia bloquea la acción con efecto
    # ------------------------------------------------------------------
    def test_cleanup_action_absent_in_consequence(self):
        product = self._anomaly_finished('NODO ANOMALIA CONSECUENCIA')
        board = self._pf_force_board(product, 1.0)
        self._pf_recompute_board(board)
        wizard = self._pf_diagnose(board)

        blocked = wizard._pf_node_actions(
            'stock', None, 'consequence', 'deficit', False, None, True)
        self.assertNotIn(
            'cleanup_reservations', [action['key'] for action in blocked])

    # ------------------------------------------------------------------
    # 4) Sin anomalía no se ofrece el saneo
    # ------------------------------------------------------------------
    def test_no_anomaly_no_cleanup_action(self):
        product = self._anomaly_finished('NODO ANOMALIA SIN ANOMALIA')
        board = self._pf_force_board(product, 1.0)
        self._pf_recompute_board(board)
        wizard = self._pf_diagnose(board)

        actions = wizard._pf_node_actions(
            'stock', None, 'none', 'ok', False, None, False)
        self.assertNotIn(
            'cleanup_reservations', [action['key'] for action in actions])
