# -*- coding: utf-8 -*-
"""Anti-falso-positivo del caso f: si la porción propia YA está reservada, NO
se marca ``personalized_supply_stolen`` (PrintFlow)."""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticPersonalizedNotStolen(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente No Robo Personalizado'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def test_condition_is_false_when_own_reserved(self):
        Wizard = self.env['printflow.order.diagnostic.wizard']
        # Porción propia (5) reservada al pedido: NO hay robo.
        self.assertFalse(
            Wizard._pf_is_personalized_supply_stolen(5.0, 5.0, 5.0, 0.0))
        # Sin porción recibida: NO hay robo.
        self.assertFalse(
            Wizard._pf_is_personalized_supply_stolen(0.0, 5.0, 0.0, 0.0))
        # Hay libre para el pedido: NO hay robo.
        self.assertFalse(
            Wizard._pf_is_personalized_supply_stolen(5.0, 5.0, 0.0, 5.0))
        # Porción recibida, sin reservar y sin libre: SÍ hay robo.
        self.assertTrue(
            Wizard._pf_is_personalized_supply_stolen(5.0, 5.0, 0.0, 0.0))

    def test_no_stolen_without_own_received(self):
        """Integración: un personalizado SIN compra recibida NO se marca."""
        product = self.env['product.product'].create({
            'name': 'PERSONALIZADO SIN COMPRA (DIAG)',
            'type': 'product',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
            'pf_purchase_on_order': True,
        })
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 5.0,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        self.assertTrue(line)
        self.assertAlmostEqual(line.own_received_qty, 0.0, places=3)
        failure = line.failure_ids.filtered(lambda f: f.node == 'stock')
        if failure:
            self.assertNotEqual(
                failure.pf_cause, 'personalized_supply_stolen')
