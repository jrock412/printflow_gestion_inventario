# -*- coding: utf-8 -*-
"""Porción propia PRORRATEADA por demanda del grupo (PrintFlow)."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticOwnSupplyProrated(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Porción Prorrateo'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Porción Prorrateo', 'supplier_rank': 1})
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO PORCION PRORRATEO',
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

    def test_prorated_by_demand(self):
        so_a = self._so(3.0)
        so_b = self._so(1.0)
        po = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': '%s, %s' % (so_a.name, so_b.name),
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 8.0,
                'product_uom': self.product.uom_id.id,
            })],
        })
        po.write({'state': 'purchase'})

        own_a = self.Remedy._pf_own_portion(self.product, so_a)
        own_b = self.Remedy._pf_own_portion(self.product, so_b)
        # 8 * 3/4 = 6 ; 8 * 1/4 = 2
        self.assertAlmostEqual(own_a['own_supply_qty'], 6.0, places=3)
        self.assertAlmostEqual(own_b['own_supply_qty'], 2.0, places=3)
        self.assertEqual(own_a['own_portion_kind'], 'prorated')
        self.assertEqual(own_b['own_portion_kind'], 'prorated')

    def test_zero_denominator_gives_zero_portion(self):
        """Sin demanda visible en el grupo, la porción es 0 (no se inventa)."""
        so_a = self._so(0.0)
        so_b = self._so(0.0)
        po = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': '%s, %s' % (so_a.name, so_b.name),
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 8.0,
                'product_uom': self.product.uom_id.id,
            })],
        })
        po.write({'state': 'purchase'})
        own_a = self.Remedy._pf_own_portion(self.product, so_a)
        self.assertAlmostEqual(own_a['own_supply_qty'], 0.0, places=3)
        self.assertEqual(own_a['own_portion_kind'], 'none')
