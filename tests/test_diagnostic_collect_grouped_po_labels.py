# -*- coding: utf-8 -*-
"""FASE 5 — Etiquetado de la PORCIÓN POR PEDIDO en la OC agrupada (PrintFlow)."""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticCollectGroupedPoLabels(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Bandeja Grupal'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Bandeja Grupal', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _so(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return so

    def test_grouped_portion_label(self):
        product = self.env['product.product'].create({
            'name': 'PERSONALIZADO BANDEJA (DIAG)',
            'type': 'consu',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
            'pf_purchase_on_order': True,
        })
        so_a = self._so(product, 5.0)
        so_b = self._so(product, 5.0)
        po = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': '%s, %s' % (so_a.name, so_b.name),
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 10.0,
                'product_uom': product.uom_id.id,
            })],
        })
        po.order_line.qty_received = 10.0
        po.write({'state': 'purchase'})

        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so_a.id})
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        self.assertTrue(line)
        failure = self.env['printflow.order.diagnostic.failure'].create({
            'line_id': line.id,
            'node': 'stock',
            'pf_cause': 'personalized_supply_stolen',
        })
        failure.action_open_collect_tray()

        evidences = self.env['printflow.order.diagnostic.evidence'].search(
            [('failure_id', '=', failure.id)])
        portion = evidences.filtered(
            lambda e: e.causante_type == 'order_portion')
        self.assertTrue(portion, 'La OC agrupada debe aportar la porción.')
        portion = portion[:1]
        self.assertEqual(portion.ref_name, po.name)
        self.assertEqual(portion.state_label, so_a.name)
        self.assertAlmostEqual(portion.qty, 5.0, places=3)
        # La etiqueta de grupo incluye a AMBOS pedidos.
        self.assertIn(so_a.name, portion.origin_group)
        self.assertIn(so_b.name, portion.origin_group)
