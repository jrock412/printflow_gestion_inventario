# -*- coding: utf-8 -*-
"""Caso c: fabricable, hay material y SIN OF -> remedio ``manufacture``.

El motor unificado clasifica la producción ``no_mo`` como causa ``manufacture``
(crear la Orden de Fabricación) y el remedio físico, cuando hay BOM y material,
también es ``manufacture``.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticManufactureNoMo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Flow = cls.env['printflow.product.flow.diagnostic']
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _product(self, name, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def test_manufacture_when_material_available(self):
        finished = self._product('TERMINADO A FABRICAR')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        component = self._product('COMPONENTE SUFICIENTE')
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        self.env['stock.quant']._update_available_quantity(
            component, self.stock_location, 50.0)

        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(finished, 1.0), 'manufacture')

        verdict = self.Flow._pf_flow_verdict({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_delivery_stage': True,
            'is_stock_covered': False, 'physical_remedy': 'manufacture',
        })
        self.assertEqual(verdict['production_status'], 'no_mo')
        self.assertEqual(verdict['cause'], 'manufacture')
        self.assertEqual(verdict['remedy_key'], 'manufacture')
