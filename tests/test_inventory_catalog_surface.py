# -*- coding: utf-8 -*-
"""Tablero "Productos" (catálogo) — superficie y poblado (PrintFlow · Fase 6).

Custodia:
  * ``action_open_catalog`` devuelve un ``act_window`` lista/kanban con búsqueda;
  * ``_pf_populate(only_alerts=False)`` trae los productos del alcance;
  * ``only_alerts=True`` trae SOLO alertas;
  * ``flow_type`` correcto (fabricable vs compra);
  * ``node_pending_total`` / ``pending_by_node`` con el motor de pendientes;
  * el mapa de severidad estado/lote -> semáforo.

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_PARAM = 'x_product_dimensional_pricing.%s'


@tagged('post_install', '-at_install')
class TestInventoryCatalogSurface(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Catálogo (F6)'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Catálogo (F6)', 'supplier_rank': 1})
        cls.Catalog = cls.env['printflow.inventory.catalog']
        cls._set_param_cls('pf_catalog_limit', '0')
        cls._set_param_cls('pf_stock_health_scope', 'managed')
        cls._set_param_cls('pf_node_pending_enabled', '1')
        cls._set_param_cls(
            'pf_node_pending_nodes', 'purchase,receipt,production,delivery,sale')

    @classmethod
    def _set_param_cls(cls, key, value):
        cls.env['ir.config_parameter'].sudo().set_param(
            _PARAM % key, value)

    def _managed_product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    # ------------------------------------------------------------------
    # 1) Superficie
    # ------------------------------------------------------------------
    def test_action_open_catalog_returns_board(self):
        action = self.Catalog.action_open_catalog()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.inventory.catalog')
        self.assertEqual(action['view_mode'], 'list,kanban')
        self.assertTrue(action.get('search_view_id'))

    def test_action_open_catalog_only_alerts_preset(self):
        action = self.Catalog.action_open_catalog(only_alerts=True)
        self.assertEqual(
            action.get('context'), {'search_default_filter_alert': 1})

    # ------------------------------------------------------------------
    # 2) Poblado
    # ------------------------------------------------------------------
    def test_populate_all_includes_managed_product(self):
        product = self._managed_product('CATALOGO TODOS')
        rows = self.Catalog._pf_populate(only_alerts=False)
        self.assertIn(product, rows.mapped('product_id'))

    def test_populate_only_alerts_flags_over_reserved(self):
        product = self._managed_product('CATALOGO ALERTA')
        self._pf_add_stock(product, 1.0, reserved=5.0)
        rows = self.Catalog._pf_populate(only_alerts=True)
        row = rows.filtered(lambda r: r.product_id == product)
        self.assertTrue(row)
        self.assertNotEqual(row.state, 'ok')
        self.assertTrue(row.has_alert)

    def test_flow_type_detects_manufacture(self):
        component = self._managed_product('CATALOGO COMPONENTE')
        self._pf_add_stock(component, 10.0)
        finished = self._managed_product('CATALOGO FABRICADO')
        self._pf_make_bom(finished, [(component, 1.0)])
        rows = self.Catalog._pf_populate(only_alerts=False)
        finished_row = rows.filtered(lambda r: r.product_id == finished)
        self.assertTrue(finished_row)
        self.assertEqual(finished_row.flow_type, 'manufacture')

    def test_pending_total_and_label(self):
        product = self._managed_product('CATALOGO PENDIENTES')
        self._pf_add_stock(product, 10.0)
        self._pf_confirm_order(product, 2.0)  # deja una entrega pendiente
        rows = self.Catalog._pf_populate(only_alerts=False)
        row = rows.filtered(lambda r: r.product_id == product)
        self.assertTrue(row)
        self.assertGreaterEqual(row.node_pending_total, 1)
        self.assertIn('Entrega', row.pending_by_node)
        self.assertTrue(row.has_pending)

    # ------------------------------------------------------------------
    # 3) Mapa de severidad (puro)
    # ------------------------------------------------------------------
    def test_severity_mapping(self):
        base = self.env['printflow.inventory.catalog']
        self.assertEqual(base._pf_severity('physical', 'lot_ok'), ('danger', 0))
        self.assertEqual(base._pf_severity('ok', 'lot_missing'), ('danger', 0))
        self.assertEqual(
            base._pf_severity('over_reserved', 'lot_ok'), ('warning', 1))
        self.assertEqual(
            base._pf_severity('ok', 'lot_generic'), ('warning', 1))
        self.assertEqual(base._pf_severity('ok', 'lot_ok'), ('ok', 3))
