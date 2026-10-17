# -*- coding: utf-8 -*-
"""Resumen corto del problema en la TARJETA del nodo (PrintFlow).

El payload del canvas deja de pintar el genérico "N problema(s)": cada nodo
lleva ``summary`` (el mismo texto que el ``detail`` del panel, fuente única) y
``summary_more`` (cuántas fallas ADICIONALES cobija el hito, para el sufijo
" +N").

Estos tests custodian:
  * el nodo roto expone un ``summary`` legible y su ``summary_more`` cuadra con
    ``issues - 1``;
  * un nodo sano (sin fallas hospedadas) NO inventa texto (``summary == ''``);
  * el helper ``_pf_node_summary`` es puro y tolera ``owner_failure=None``;
  * sin foco el payload es SEGURO (summary vacío en todos los nodos).

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticNodeSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Node Summary'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Node Summary', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _force_order(self, lines, partner=None):
        so = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        return so, board

    def _wizard(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})

    def _payload(self, wizard):
        return json.loads(wizard.focus_timeline_json)

    def _purchase_root_wizard(self):
        product = self._product(
            'SUMARIO COMPRA RAIZ', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 4.0)])
        wizard = self._wizard(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})
        return wizard

    # ------------------------------------------------------------------
    # 1) El helper es puro y tolera owner None
    # ------------------------------------------------------------------
    def test_helper_without_owner_returns_empty(self):
        wizard = self._purchase_root_wizard()
        self.assertEqual(wizard._pf_node_summary(None, 5), ('', 0))
        self.assertEqual(wizard._pf_node_summary(None, 0), ('', 0))

    def test_helper_with_owner_uses_summary_and_more(self):
        wizard = self._purchase_root_wizard()
        line = wizard.focus_line_id
        owner = line.failure_ids.filtered(
            lambda f: f.node == 'purchase')[:1]
        self.assertTrue(owner)
        self.assertEqual(
            wizard._pf_node_summary(owner, 3), (owner.summary or '', 2))
        self.assertEqual(
            wizard._pf_node_summary(owner, 1), (owner.summary or '', 0))
        # Nunca negativo aunque ``issues`` sea 0.
        self.assertEqual(
            wizard._pf_node_summary(owner, 0), (owner.summary or '', 0))

    # ------------------------------------------------------------------
    # 2) El nodo roto expone un resumen legible (no "N problema(s)")
    # ------------------------------------------------------------------
    def test_broken_node_carries_summary(self):
        wizard = self._purchase_root_wizard()
        line = wizard.focus_line_id
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}

        purchase = by_key['purchase']
        self.assertEqual(purchase['role'], 'root')
        self.assertTrue(purchase['summary'])
        purchase_failure = line.failure_ids.filtered(
            lambda f: f.node == 'purchase')[:1]
        self.assertEqual(purchase['summary'], purchase_failure.summary)
        # " +N" = cuántas fallas ADICIONALES cobija el hito.
        self.assertEqual(
            purchase['summary_more'], max(0, purchase['issues'] - 1))

    # ------------------------------------------------------------------
    # 3) La consecuencia también resume su problema
    # ------------------------------------------------------------------
    def test_consequence_node_carries_summary(self):
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        stock = by_key['stock']
        self.assertEqual(stock['role'], 'consequence')
        self.assertTrue(stock['summary'])

    # ------------------------------------------------------------------
    # 4) Nodo sano: sin fallas -> sin texto inventado
    # ------------------------------------------------------------------
    def test_healthy_node_has_no_summary(self):
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        customer = by_key['customer']
        self.assertEqual(customer['summary'], '')
        self.assertEqual(customer['summary_more'], 0)

    # ------------------------------------------------------------------
    # 5) Sin foco: payload SEGURO
    # ------------------------------------------------------------------
    def test_summary_safe_without_focus(self):
        product = self._product('SUMARIO SIN FOCO')
        _so, board = self._force_order([(product, 1.0)])
        wizard = self._wizard(board)
        self.assertFalse(wizard.focus_line_id)
        for node in self._payload(wizard)['nodes']:
            self.assertEqual(node['summary'], '')
            self.assertEqual(node['summary_more'], 0)
            # Sin foco tampoco hay etiqueta de estado (payload seguro).
            self.assertEqual(node.get('status_label', ''), '')

    # ------------------------------------------------------------------
    # 6) El label de estado es ESPECÍFICO del hito (nodos sanos dicen su estado)
    # ------------------------------------------------------------------
    def test_node_status_label_is_hito_specific(self):
        wizard = self._purchase_root_wizard()
        # Entrega en orden -> "Entregado" (no "Sano").
        self.assertEqual(wizard._pf_node_status_label('delivery', 'ok'), 'Entregado')
        self.assertEqual(wizard._pf_node_status_label('receipt', 'ok'), 'Recibido')
        self.assertEqual(
            wizard._pf_node_status_label('stock', 'ok'), 'Disponible')
        # `over` unificado con la cabecera ("Stock en contención").
        self.assertEqual(
            wizard._pf_node_status_label('stock', 'over'), 'Stock en contención')
        # Fabricación en proceso.
        self.assertEqual(
            wizard._pf_node_status_label('production', 'in_progress'),
            'OF en proceso')
        # Sin estado -> cadena vacía.
        self.assertEqual(wizard._pf_node_status_label('delivery', None), '')

    def test_healthy_node_carries_status_label(self):
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        customer = by_key['customer']
        self.assertEqual(customer['summary'], '')
        self.assertEqual(customer['status_label'], 'Entregado')
