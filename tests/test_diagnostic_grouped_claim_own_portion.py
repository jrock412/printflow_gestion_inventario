# -*- coding: utf-8 -*-
"""Reparto de la porción propia en una OC agrupada (caso f, PrintFlow)."""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticGroupedClaimOwnPortion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Reparto Porción'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Reparto Porción', 'supplier_rank': 1})
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Playbook = cls.env['printflow.resolution.playbook']
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO REPARTO PORCION',
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

    def test_claim_meta_and_plan(self):
        label, kind, target = self.Remedy._pf_remedy_meta('claim_own_purchase')
        self.assertTrue(label)
        self.assertEqual(kind, 'run_action')
        self.assertEqual(target, 'claim_own_purchase')
        plan = self.Playbook._pf_get_plan('personalized_supply_stolen')
        self.assertEqual(
            plan['actions']['solution']['target'], 'claim_own_purchase')
        self.assertEqual(plan['actions']['solution']['kind'], 'run_action')

    def test_portion_per_order_in_group(self):
        so_a = self._so(5.0)
        so_b = self._so(5.0)
        po = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': '%s, %s' % (so_a.name, so_b.name),
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_qty': 5.0,
                'product_uom': self.product.uom_id.id,
                'sale_line_id': so_a.order_line.id,
            })],
        })
        po.write({'state': 'purchase'})
        own_a = self.Remedy._pf_own_portion(self.product, so_a)
        own_b = self.Remedy._pf_own_portion(self.product, so_b)
        # La compra pertenece SOLO a A; B no reclama nada.
        self.assertAlmostEqual(own_a['own_supply_qty'], 5.0, places=3)
        self.assertAlmostEqual(own_b['own_supply_qty'], 0.0, places=3)
