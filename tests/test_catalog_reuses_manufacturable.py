# -*- coding: utf-8 -*-
"""Rendimiento — ``_pf_populate`` reutiliza el mapa de fabricables (sin recálculo).

Custodia que ``_pf_manufacturable_products`` se calcule UNA sola vez por
poblado: el catálogo debe reutilizar el mapa de BOM (sin volver a llamar
``_bom_find``) y reenviar el conjunto de fabricables al snapshot de inventario.
"""

from unittest import mock

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCatalogReusesManufacturable(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Catalog = cls.env['printflow.inventory.catalog']
        cls._set_param_cls('pf_catalog_limit', '0')
        cls._set_param_cls('pf_stock_health_scope', 'managed')
        cls._set_param_cls('pf_node_pending_enabled', '1')
        cls._set_param_cls(
            'pf_node_pending_nodes', 'purchase,receipt,production,delivery,sale')

    @classmethod
    def _set_param_cls(cls, key, value):
        cls.env['ir.config_parameter'].sudo().set_param(
            'x_product_dimensional_pricing.%s' % key, value)

    def test_manufacturable_computed_once_and_bom_reused(self):
        # Al menos 2 productos para que ``_bom_find`` no tome el atajo de 1.
        for i in range(3):
            product = self.env['product.product'].create({
                'name': 'REUSE FABRICABLE %02d' % i,
                'type': 'product',
                'x_is_printflow_managed': True,
            })
            self.env['stock.quant']._update_available_quantity(
                product, self.stock_location, 5.0)

        Engine = self.env['printflow.order.health.engine']
        original = type(Engine)._pf_manufacturable_products
        calls = []

        def _spy(model_self, products, bom_by_product=None):
            calls.append(bom_by_product is not None)
            return original(model_self, products, bom_by_product=bom_by_product)

        with mock.patch.object(
                type(Engine), '_pf_manufacturable_products', _spy):
            self.Catalog._pf_populate(only_alerts=False)

        self.assertEqual(
            len(calls), 1,
            '_pf_manufacturable_products debe llamarse UNA sola vez en el poblado.')
        self.assertTrue(
            calls[0], 'El poblado debe reutilizar el mapa de BOM (bom_by_product).')
