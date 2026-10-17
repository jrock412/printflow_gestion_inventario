# -*- coding: utf-8 -*-
"""Fase 7: Ajustes (res.config.settings) de los tableros nuevos (PrintFlow).

Custodia:
  * al guardar Ajustes, los cuatro parámetros ``pf_*`` quedan PERSISTIDOS en
    ``ir.config_parameter`` con la clave EXACTA del código;
  * el tablero "Productos" respeta ``pf_catalog_limit``;
  * el motor de pendientes respeta ``pf_node_pending_nodes``;
  * el motor cae a sus DEFAULT si el parámetro falta (sin romper).

Son de SOLO LECTURA salvo el ``set_values`` de Ajustes (la transacción de
``TransactionCase`` lo revierte). Hacen rollback al terminar.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_MODULE = 'x_product_dimensional_pricing'

# Claves EXACTAS (deben coincidir con las constantes de
# ``printflow_flow_pending.py``).
PARAM_NODE_PENDING_ENABLED = _MODULE + '.pf_node_pending_enabled'
PARAM_NODE_PENDING_NODES = _MODULE + '.pf_node_pending_nodes'
PARAM_NODE_PENDING_LIMIT = _MODULE + '.pf_node_pending_limit'
PARAM_CATALOG_LIMIT = _MODULE + '.pf_catalog_limit'
PARAM_SCOPE = _MODULE + '.pf_stock_health_scope'


@tagged('post_install', '-at_install')
class TestPhase7SettingsConfig(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Catalog = cls.env['printflow.inventory.catalog']
        cls.Pending = cls.env['printflow.node.pending.line']
        cls.ICP = cls.env['ir.config_parameter'].sudo()

    def _settings(self, **vals):
        """Crea y guarda Ajustes (equivale a pulsar 'Guardar' en el panel)."""
        settings = self.env['res.config.settings'].create(vals)
        settings.set_values()
        return settings

    def _managed_product(self, name):
        product = self._pf_product(name)
        product.write({'x_is_printflow_managed': True})
        return product

    # ------------------------------------------------------------------
    # 1) Persistencia de los parámetros al guardar Ajustes
    # ------------------------------------------------------------------
    def test_settings_persist_catalog_limit(self):
        self._settings(pf_catalog_limit=2)
        self.assertEqual(self.ICP.get_param(PARAM_CATALOG_LIMIT), '2')

    def test_settings_persist_node_pending(self):
        self._settings(
            pf_node_pending_enabled=True,
            pf_node_pending_nodes='delivery',
            pf_node_pending_limit=3,
        )
        self.assertEqual(
            self.ICP.get_param(PARAM_NODE_PENDING_ENABLED), 'True')
        self.assertEqual(
            self.ICP.get_param(PARAM_NODE_PENDING_NODES), 'delivery')
        self.assertEqual(
            self.ICP.get_param(PARAM_NODE_PENDING_LIMIT), '3')

    # ------------------------------------------------------------------
    # 2) El tablero respeta el valor configurado
    # ------------------------------------------------------------------
    def test_board_respects_catalog_limit(self):
        # 3 productos gestionados (para que el tope sea determinista).
        for index in range(3):
            self._managed_product('FASE7 CATALOGO %s' % index)
        self._settings(pf_catalog_limit=2)  # fija el param vía Ajustes
        self.ICP.set_param(PARAM_SCOPE, 'managed')
        rows = self.Catalog._pf_populate(only_alerts=False)
        self.assertEqual(len(rows), 2)

    def test_engine_respects_node_pending_nodes(self):
        self._settings(
            pf_node_pending_enabled=True, pf_node_pending_nodes='delivery')
        pending = self.env['printflow.flow.pending']
        self.assertEqual(pending._pf_node_pending_nodes(), ['delivery'])

    # ------------------------------------------------------------------
    # 3) Default del código si el parámetro falta (degradación segura)
    # ------------------------------------------------------------------
    def test_engine_falls_back_to_defaults_when_missing(self):
        self.ICP.search([('key', '=', PARAM_CATALOG_LIMIT)]).unlink()
        pending = self.env['printflow.flow.pending']
        self.assertEqual(pending._pf_catalog_limit(), 0)
