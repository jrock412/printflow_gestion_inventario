# -*- coding: utf-8 -*-
"""Caso f — Compra propia retenida (personalizado con reparto, PrintFlow).

Reproduce el testigo: un producto ``pf_purchase_on_order`` cuya compra propia ya
se recibió, pero el pedido no la tiene reservada (la retiene otro pedido del
grupo). El diagnóstico detecta ``personalized_supply_stolen`` y ofrece el remedio
``claim_own_purchase``.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticPersonalizedPurchase(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Personalizado Compra'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Personalizado Compra', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _personalized(self):
        # ``consu`` -> qty_received manual (permite simular la recepción).
        product = self.env['product.product'].create({
            'name': 'PERSONALIZADO COMPRA (DIAG)',
            'type': 'consu',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
            'pf_purchase_on_order': True,
        })
        self.assertTrue(product.product_tmpl_id.pf_purchase_on_order)
        return product

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

    def test_stolen_own_purchase_is_detected(self):
        product = self._personalized()
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
        # La porción propia recibida se computa (5 de 10).
        self.assertAlmostEqual(line.own_received_qty, 5.0, places=3)
        self.assertGreater(line.incoming_own + 1.0, 0.0)

        failure = line.failure_ids.filtered(lambda f: f.node == 'stock')
        self.assertTrue(failure)
        self.assertEqual(failure.pf_cause, 'personalized_supply_stolen')
        self.assertEqual(failure.pf_remedy_target, 'claim_own_purchase')
        self.assertEqual(failure.pf_remedy_kind, 'run_action')
