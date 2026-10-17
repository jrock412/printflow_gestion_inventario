# -*- coding: utf-8 -*-
"""Drill-down del tablero Productos por clic en `product_id` (PrintFlow · F7).

Custodia el wiring de la vista LISTA `printflow_inventory_catalog_view_list`:
  * `product_id` usa el widget `printflow_open_timeline` con
    `options.action = action_open_flow` (abre el DIAGRAMA DE FLUJO);
  * el botón dedicado "Ver diagrama" (`action_open_flow`) NO existe en la lista
    (se eliminó en F7 y su reemplazo es el clic en `product_id`);
  * el botón "Producto" (`action_open_product`) SIGUE presente (ficha);
  * el KANBAN conserva su botón "Ver diagrama" (`action_open_flow`).

Son de SOLO LECTURA: se inspecciona `view.arch_db`; `TransactionCase` hace
rollback al terminar, así que NO se escribe ningún dato persistente.
"""
import ast

from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCatalogListDrilldownWidget(TransactionCase):

    def _arch_root(self, xml_id):
        view = self.env.ref('printflow_gestion_inventario.' + xml_id)
        arch = view.arch_db
        if not isinstance(arch, (bytes, str)):
            arch = str(arch)
        if isinstance(arch, str):
            arch = arch.encode('utf-8')
        return etree.fromstring(arch)

    def _product_id_options(self, root):
        """Options del field `product_id` de la lista, ya evaluados a dict."""
        fields = root.xpath(
            "//field[@name='product_id']"
            "[@widget='printflow_open_timeline']")
        self.assertEqual(
            len(fields), 1,
            'La lista debe declarar product_id con el widget '
            'printflow_open_timeline (F7: clic = drill-down).')
        raw = fields[0].get('options')
        self.assertTrue(
            raw, 'product_id debe declarar options con action_open_flow.')
        return ast.literal_eval(raw)

    def test_list_product_id_wires_flow_action(self):
        root = self._arch_root('printflow_inventory_catalog_view_list')
        options = self._product_id_options(root)
        self.assertEqual(
            options.get('action'), 'action_open_flow',
            'El clic en product_id debe disparar action_open_flow (diagrama).')

    def test_list_removes_dedicated_flow_button(self):
        root = self._arch_root('printflow_inventory_catalog_view_list')
        self.assertFalse(
            root.xpath("//button[@name='action_open_flow']"),
            'El botón "Ver diagrama" ya no debe estar en la lista (F7).')

    def test_list_keeps_product_button(self):
        root = self._arch_root('printflow_inventory_catalog_view_list')
        self.assertTrue(
            root.xpath("//button[@name='action_open_product']"),
            'El botón "Producto" (abrir ficha) debe seguir en la lista.')

    def test_kanban_keeps_dedicated_flow_button(self):
        root = self._arch_root('printflow_inventory_catalog_view_kanban')
        self.assertTrue(
            root.xpath("//button[@name='action_open_flow']"),
            'El kanban conserva su botón "Ver diagrama" (action_open_flow).')
