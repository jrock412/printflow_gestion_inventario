# -*- coding: utf-8 -*-
"""G6 — Superficie "Salud de inventario" (bandeja poblada bajo demanda).

Lista los productos en alerta con su estado, sus números y su botón de remedio;
la acción de menú devuelve la ventana poblada.
"""
from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestInventoryHealthSurface(PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # BD real con más alertas que el tope de saneamiento (50): sin límite
        # para que los productos creados por el test no queden fuera de
        # `_pf_products_in_alert` (transacción con rollback: no persiste).
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'SURFACE EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.Health = cls.env['printflow.stock.health']
        cls.Surface = cls.env['printflow.inventory.health']

    def test_populate_lists_alerts_with_buttons(self):
        exhausted = self._pf_product('SURFACE AGOTADO')
        self._pf_add_stock(exhausted, 1.0, reserved=5.0)
        anomaly = self._pf_product('SURFACE ANOMALIA')
        self._pf_add_stock(anomaly, 1.0, reserved=5.0, location=self.extra_location)
        self._pf_add_stock(anomaly, 10.0)

        rows = self.Surface._pf_populate()
        products = rows.mapped('product_id')
        self.assertIn(exhausted, products)
        self.assertIn(anomaly, products)

        exhausted_row = rows.filtered(lambda r: r.product_id == exhausted)
        anomaly_row = rows.filtered(lambda r: r.product_id == anomaly)
        # Sobrepedido AGREGADO (no anomalía): se ve quién bloquea.
        self.assertEqual(exhausted_row.state, 'over_reserved')
        self.assertTrue(exhausted_row.has_negative_quant)
        self.assertEqual(exhausted_row.nature, 'ok')
        self.assertEqual(exhausted_row.remedy_kind, 'navigate')
        self.assertEqual(
            exhausted_row.remedy_target, 'blocking_reservations')
        # Reserva colgada (anomalía): se sane por re-asignación.
        self.assertEqual(anomaly_row.nature, 'anomaly')
        self.assertEqual(anomaly_row.remedy_kind, 'run_action')
        self.assertEqual(anomaly_row.remedy_target, 'fix_over_reservation')

    def test_open_health_returns_action_window(self):
        product = self._pf_product('SURFACE OPEN')
        self._pf_add_stock(product, 1.0, reserved=5.0)
        action = self.Surface._pf_open_health()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.inventory.health')
        self.assertTrue(
            self.Surface.search([('product_id', '=', product.id)]))

    def test_open_health_without_products_is_backward_compatible(self):
        """Sin ``products`` ni ``domain`` el comportamiento es el histórico."""
        action = self.Surface._pf_open_health()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertNotIn('domain', action)
        self.assertEqual(
            action.get('context'), {'search_default_filter_alert': 1})

    def test_open_health_with_products_populates_and_filters(self):
        """El ruteo contextual puebla SOLO esos productos y filtra la ventana."""
        wants = self._pf_product('SURFACE FILTRO INCLUIDO')
        other = self._pf_product('SURFACE FILTRO EXCLUIDO')
        self._pf_add_stock(wants, 1.0, reserved=5.0)
        self._pf_add_stock(other, 1.0, reserved=5.0)

        action = self.Surface._pf_open_health(
            products=wants, title='Solo filtrado')

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.inventory.health')
        self.assertEqual(action['name'], 'Solo filtrado')
        self.assertEqual(
            action['domain'], [('product_id', 'in', [wants.id])])
        rows = self.Surface.search([])
        self.assertEqual(rows.mapped('product_id'), wants)

    def test_action_open_all_alerts_reopens_general_tray(self):
        """El botón público "Ver todas las alertas" delega en el caso general."""
        product = self._pf_product('SURFACE VER TODAS')
        self._pf_add_stock(product, 1.0, reserved=5.0)
        action = self.Surface.action_open_all_alerts()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertNotIn('domain', action)
