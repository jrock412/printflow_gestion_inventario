# -*- coding: utf-8 -*-
"""Contrato de la vista del diagnóstico: selector limpio y sin alertas de cabecera.

Custodia el arch de la vista base `printflow_order_diagnostic_wizard_view_form`:
  * el selector conserva `product_id` con `widget="printflow_open_timeline"` y
    las columnas ancladas por la vista hija del plan (`contention_qty`,
    `deficit_qty`, `warehouse_free_qty`) -> si faltaran, el módulo no cargaría;
  * el selector YA NO trae el badge `flow_severity` ni el botón
    `action_open_line_delivery`;
  * la alerta de déficit total YA NO vive en la CABECERA (se retiró del sheet);
  * el botón "Volver a productos" se oculta con `finished_product_count <= 1`.
Son de SOLO LECTURA.
"""
from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticSelectorView(TransactionCase):

    def _arch_root(self):
        view = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form')
        arch = view.arch_db
        if not isinstance(arch, (bytes, str)):
            arch = str(arch)
        if isinstance(arch, str):
            arch = arch.encode('utf-8')
        return etree.fromstring(arch)

    def test_selector_keeps_timeline_widget_and_anchored_columns(self):
        root = self._arch_root()
        self.assertTrue(root.xpath("//field[@name='product_line_ids']"))
        self.assertTrue(root.xpath(
            "//field[@name='product_line_ids']//field[@name='product_id']"
            "[@widget='printflow_open_timeline']"),
            'El selector debe mantener el widget printflow_open_timeline.')
        for col in ('contention_qty', 'deficit_qty', 'warehouse_free_qty'):
            self.assertTrue(
                root.xpath(
                    "//field[@name='product_line_ids']//field[@name='%s']" % col),
                'La columna %s es ancla de la vista hija del plan.' % col)

    def test_selector_drops_flow_severity_and_delivery_button(self):
        root = self._arch_root()
        self.assertFalse(
            root.xpath("//field[@name='flow_severity']"),
            'El badge flow_severity ya no debe estar en el selector.')
        self.assertFalse(
            root.xpath("//button[@name='action_open_line_delivery']"),
            'El botón action_open_line_delivery ya no debe estar en el selector.')

    def test_deficit_alert_removed_from_header(self):
        root = self._arch_root()
        alerts = [
            alert
            for alert in root.xpath("//div[contains(@class, 'alert-danger')]")
            if alert.xpath(".//field[@name='deficit_total']")
        ]
        self.assertFalse(
            alerts,
            'La alerta de déficit total YA NO debe vivir en la cabecera.')

    def test_back_button_guarded_by_finished_product_count(self):
        root = self._arch_root()
        buttons = root.xpath("//button[@name='action_back_to_products']")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(
            buttons[0].get('invisible'), 'finished_product_count <= 1')
