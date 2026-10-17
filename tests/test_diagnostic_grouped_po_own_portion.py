# -*- coding: utf-8 -*-
"""Porción propia en OC AGRUPADA (1 OC = N pedidos) y precedencia (PrintFlow)."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticGroupedPoOwnPortion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Grupal Porción'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Grupal Porción', 'supplier_rank': 1})
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO GRUPAL PORCION',
            'type': 'product',
            'purchase_ok': True,
        })

    def _so(self, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return so

    def test_sale_line_precedence_over_proration(self):
        so_a = self._so(6.0)
        so_b = self._so(4.0)
        origin = '%s, %s' % (so_a.name, so_b.name)
        # PO agrupada prorrateada: 10 unidades.
        po1 = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': origin,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 10.0,
                'product_uom': self.product.uom_id.id,
            })],
        })
        po1.write({'state': 'purchase'})
        # Segunda PO con vínculo EXACTO a la línea de A: 5 unidades.
        po2 = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': origin,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 5.0,
                'product_uom': self.product.uom_id.id,
                'sale_line_id': so_a.order_line.id,
            })],
        })
        po2.write({'state': 'purchase'})

        own_a = self.Remedy._pf_own_portion(self.product, so_a)
        own_b = self.Remedy._pf_own_portion(self.product, so_b)
        # A: 6 (prorrateo) + 5 (exacto) = 11; la porción es 'sale_line' (manda).
        self.assertAlmostEqual(own_a['own_supply_qty'], 11.0, places=3)
        self.assertEqual(own_a['own_portion_kind'], 'sale_line')
        # B: 4 (prorrateo), sin exacto.
        self.assertAlmostEqual(own_b['own_supply_qty'], 4.0, places=3)
        self.assertEqual(own_b['own_portion_kind'], 'prorated')
        # El grupo de origen es el mismo para ambos.
        self.assertEqual(own_a['origin_group'], own_b['origin_group'])
