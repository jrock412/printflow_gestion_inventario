# -*- coding: utf-8 -*-
"""Caso b: fabricable con BOM pero falta material -> IDENTIFICA el componente.

``_pf_missing_components`` debe devolver EXACTAMENTE los componentes cuyo libre
no cubre la cantidad a producir, y el remedio físico resultante es
``buy_components``.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticBuyComponentsIdentifies(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Remedy = cls.env['printflow.stock.remedy']
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

    def test_missing_component_is_identified(self):
        finished = self._product('TERMINADO COMPONENTES')
        # Producto de FABRICACIÓN: sin rutas de compra, con BOM.
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        scarce = self._product('COMPONENTE ESCASO')
        available = self._product('COMPONENTE DISPONIBLE')
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [
                (0, 0, {'product_id': scarce.id, 'product_qty': 2.0}),
                (0, 0, {'product_id': available.id, 'product_qty': 3.0}),
            ],
        })
        # Solo el 'disponible' tiene existencia de sobra.
        self.env['stock.quant']._update_available_quantity(
            available, self.stock_location, 100.0)

        missing = self.Remedy._pf_missing_components(finished, 1.0)
        missing_products = {m['product'] for m in missing}
        self.assertIn(scarce, missing_products)
        self.assertNotIn(available, missing_products)
        # El remedio físico es comprar los componentes, no fabricar.
        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(finished, 1.0),
            'buy_components')
