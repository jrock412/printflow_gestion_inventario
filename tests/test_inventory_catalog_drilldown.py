# -*- coding: utf-8 -*-
"""Drill-down del tablero Productos (PrintFlow · Fase 5/6).

Custodia:
  * ``action_open_flow()`` delega en el HOOK ``_pf_product_flow_action``;
  * con el override de ``diagnostic/`` devuelve el ``act_window`` del diagrama
    (``printflow.product.flow``);
  * ``action_open_alerts()`` reutiliza ``_pf_open_health`` filtrado al producto;
  * el HOOK responde con una notificación cuando no hay producto.

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestInventoryCatalogDrilldown(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Catalog = cls.env['printflow.inventory.catalog']

    def _catalog_row(self, product):
        return self.Catalog.create({'product_id': product.id})

    def test_action_open_flow_opens_product_diagram(self):
        product = self._pf_product('DRILL FLUJO')
        row = self._catalog_row(product)
        action = row.action_open_flow()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        self.assertTrue(action.get('res_id'))

    def test_hook_without_product_returns_notification(self):
        action = self.Catalog._pf_product_flow_action(
            self.env['product.product'])
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')

    def test_action_open_alerts_filters_product(self):
        product = self._pf_product('DRILL ALERTA')
        self._pf_add_stock(product, 1.0, reserved=5.0)
        row = self._catalog_row(product)
        action = row.action_open_alerts()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.inventory.health')
        self.assertEqual(
            action.get('domain'), [('product_id', 'in', [product.id])])
