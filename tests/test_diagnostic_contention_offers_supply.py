# -*- coding: utf-8 -*-
"""Caso e — CONTENCIÓN con oferta de abastecimiento (PrintFlow).

Cuando el stock lo retienen otros, este pedido NO tiene entrada propia y no le
queda libre (``free_global``/``virtual_available`` negativos), la falla mantiene
1º el remedio ``blocking`` (NUNCA toca la reserva ajena) y ADEMÁS ofrece un 2º
remedio de abastecimiento (comprar/fabricar según ruta).
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticContentionOffersSupply(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Contención Oferta'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Contención Oferta', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _purchasable(self, name):
        product = self._pf_product(
            name, x_is_printflow_managed=True, purchase_ok=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['product.supplierinfo'].create({
            'partner_id': self.supplier.id,
            'product_tmpl_id': product.product_tmpl_id.id,
            'price': 1.0,
        })
        return product

    def test_contention_without_own_incoming_offers_supply(self):
        product = self._purchasable('CONTENCION OFERTA')
        self._pf_add_stock(product, 5.0)
        # Otro pedido reserva TODO el stock.
        self._pf_confirm_order(product, 5.0)
        # Baja el físico por debajo de lo reservado -> free_global<0.
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.stock_location.id)], limit=1)
        quant.sudo().write({'quantity': 3.0})

        board = self._pf_force_board(product, 3.0)
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        self.assertTrue(line)
        self.assertGreater(line.contention_qty, 0.0)
        self.assertEqual(line.stock_status, 'over')

        failure = line.failure_ids.filtered(lambda f: f.node == 'stock')
        self.assertTrue(failure)
        # 1º SIEMPRE el bloqueo (no toca reserva ajena).
        self.assertEqual(failure.pf_remedy_target, 'blocking_reservations')
        # 2º abastecimiento por la porción no cubierta.
        self.assertTrue(failure.pf_second_remedy_available)
        self.assertEqual(failure.pf_second_remedy_target, 'buy_product')

    def test_contention_with_free_slack_has_no_second_remedy(self):
        """Con libre suficiente (free_global>=0) NO se ofrece el 2º botón."""
        product = self._purchasable('CONTENCION CON LIBRE')
        self._pf_add_stock(product, 5.0)
        self._pf_confirm_order(product, 5.0)
        board = self._pf_force_board(product, 3.0)
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        failure = line.failure_ids.filtered(lambda f: f.node == 'stock')
        self.assertTrue(failure)
        self.assertEqual(failure.pf_remedy_target, 'blocking_reservations')
        self.assertFalse(failure.pf_second_remedy_available)
