# -*- coding: utf-8 -*-
"""Rendimiento — el catálogo "Productos" no crece con N (sin N+1).

Custodia que ``printflow.inventory.catalog._pf_populate`` haga un número de
consultas CONSTANTE respecto al número de productos, tanto en el alcance
completo como en el flujo "Solo alertas" (que ejercita el barrido real
``_pf_products_in_alert`` / ``_pf_lot_alert_product_ids``).

No fija números exactos (frágiles): compara el conteo con 10 y con 40 productos
y exige que la diferencia sea mínima (un N+1 crecería ~N).
"""

from contextlib import ExitStack
from unittest import mock

from odoo.tests.common import TransactionCase, tagged

# Delta tolerado entre poblados con distinto N.
_QUERY_DELTA = 10


@tagged('post_install', '-at_install')
class TestInventoryCatalogQueryBudget(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Catalog = cls.env['printflow.inventory.catalog']
        cls._set_param_cls('pf_catalog_limit', '0')
        cls._set_param_cls('pf_stock_health_scope', 'managed')
        cls._set_param_cls('pf_node_pending_enabled', '1')
        cls._set_param_cls(
            'pf_node_pending_nodes', 'purchase,receipt,production,delivery,sale')
        cls._set_param_cls('pf_reservation_cleanup_limit', '0')

    @classmethod
    def _set_param_cls(cls, key, value):
        cls.env['ir.config_parameter'].sudo().set_param(
            'x_product_dimensional_pricing.%s' % key, value)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _managed_products(self, n, prefix, alert=False, tracking='none'):
        products = self.env['product.product']
        for i in range(n):
            product = self.env['product.product'].create({
                'name': '%s %02d' % (prefix, i),
                'type': 'product',
                'tracking': tracking,
                'x_is_printflow_managed': True,
            })
            if alert:
                # Reserva huérfana: cuant reservado sin movimiento que lo
                # respalde -> producto en alerta de lote/cantidad.
                self.env['stock.quant']._update_available_quantity(
                    product, self.stock_location, 1.0, reserved_quantity=5.0)
            else:
                self.env['stock.quant']._update_available_quantity(
                    product, self.stock_location, 5.0)
            products |= product
        return products

    def _measure_populate(self, products, only_alerts):
        Catalog = self.env['printflow.inventory.catalog']

        def _scope(model_self, only_alerts=False, limit=0):
            return products

        with mock.patch.object(type(Catalog), '_pf_scope_products', _scope), \
                self._isolate_transient(Catalog):
            # Warm-up: carga cachés (config/rutas/BOM) fuera del conteo.
            Catalog._pf_populate(only_alerts=only_alerts)
            self.env.flush_all()
            self.env.cr.flush()
            start = self.cr.sql_log_count
            Catalog._pf_populate(only_alerts=only_alerts)
            self.env.flush_all()
            self.env.cr.flush()
            return self.cr.sql_log_count - start

    def _measure_populate_alerts(self):
        # Sin parche de alcance: se ejercita el barrido real
        # ``_pf_products_in_alert`` / ``_pf_lot_alert_product_ids``.
        Catalog = self.env['printflow.inventory.catalog']
        with self._isolate_transient(Catalog):
            # Warm-up: carga cachés fuera del conteo (evita el sesgo frío/caliente).
            self.Catalog._pf_populate(only_alerts=True)
            self.env.flush_all()
            self.env.cr.flush()
            start = self.cr.sql_log_count
            self.Catalog._pf_populate(only_alerts=True)
            self.env.flush_all()
            self.env.cr.flush()
            return self.cr.sql_log_count - start

    def _isolate_transient(self, Catalog):
        """Aísla el alta/baja de filas transitorias del conteo de LECTURA.

        ``_pf_reset``/``create`` escriben las filas del catálogo y su costo crece
        con el tamaño del conjunto en alerta de la BD (ruido ajeno al N+1 que se
        quiere blindar). El N+1 era de LECTURA; se mide todo lo demás intacto.
        """
        def _no_reset(model_self):
            return None

        def _no_create(model_self, vals, *args, **kwargs):
            return model_self.browse()

        stack = ExitStack()
        stack.enter_context(
            mock.patch.object(type(Catalog), '_pf_reset', _no_reset))
        stack.enter_context(
            mock.patch.object(type(Catalog), 'create', _no_create))
        return stack

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def test_populate_all_query_count_is_constant(self):
        small = self._managed_products(10, 'CAT-Q10')
        big = self._managed_products(40, 'CAT-Q40')
        q_small = self._measure_populate(small, only_alerts=False)
        q_big = self._measure_populate(big, only_alerts=False)
        self.assertLessEqual(
            abs(q_big - q_small), _QUERY_DELTA,
            '_pf_populate no debe crecer con N (10->%d, 40->%d)'
            % (q_small, q_big))

    def test_populate_only_alerts_query_count_is_constant(self):
        # Productos por LOTE en alerta: obligan a pasar por
        # ``_pf_lot_alert_product_ids`` (la ruta que tenía el N+1 por candidato).
        self._managed_products(10, 'CAT-AL10', alert=True, tracking='lot')
        q_small = self._measure_populate_alerts()
        self._managed_products(40, 'CAT-AL40', alert=True, tracking='lot')
        q_big = self._measure_populate_alerts()
        self.assertLessEqual(
            abs(q_big - q_small), _QUERY_DELTA,
            '_pf_populate(only_alerts=True) no debe crecer con N (10->%d, 40->%d)'
            % (q_small, q_big))
