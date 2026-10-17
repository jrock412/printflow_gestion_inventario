# -*- coding: utf-8 -*-
"""Magnitud del DÉFICIT en el nodo COMPRAS y resolución que guía a COMPRARLO.

Custodia el contrato de la tarea "el nodo Compras debe decir CUÁNTO falta
comprar y su resolución debe guiar a comprarlo" (Sección 3 del CONTEXT.md):

  * **CA-1** — con déficit > 0 y producto comprable, el nodo Compras muestra la
    magnitud en el badge ADITIVO ``shortfall_qty`` (== déficit) + su etiqueta; el
    resto de hitos queda en 0 / cadena vacía.
  * **CA-2** — la resolución del nodo Compras guía a COMPRAR lo que falta
    (producto + cantidad = déficit), NO a las compras ya hechas: abre la Compra
    Rápida (``mrp.quick.purchase.wizard``) sin crear OC (``abrir ≠ ejecutar``).
  * **CA-3** — generaliza: un producto FABRICABLE y comprable con déficit también
    expone la magnitud en el eje ``manufacture`` (sin hardcode).
  * **CA-4** — paridad: el diagrama del PEDIDO también lleva ``shortfall_qty`` en
    su nodo Compras.
  * **CA-5** — SOLO LECTURA: ``TransactionCase`` (rollback) y los archivos de
    producción tocados NO usan SQL crudo ni ``cr.commit``.

Solo lectura: nada se persiste (rollback de ``TransactionCase``).
"""

import json
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Archivos de PRODUCCIÓN tocados por la tarea (solo lectura: sin SQL crudo).
_TOUCHED_FILES = (
    os.path.join('models', 'printflow_flow_presentation.py'),
    os.path.join('models', 'printflow_flow_payload_builder.py'),
    os.path.join('models', 'printflow_flow_strategy_product.py'),
    os.path.join('models', 'printflow_flow_strategy_order.py'),
    os.path.join('models', 'printflow_flow_pending.py'),
    os.path.join('models', 'printflow_resolution_playbook.py'),
    os.path.join('wizard', 'printflow_product_flow.py'),
)


@tagged('post_install', '-at_install')
class TestFlowComprasDeficitMagnitude(TransactionCase):
    """CA-1..CA-5 de la magnitud del déficit en el nodo Compras."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flow = cls.env['printflow.product.flow']
        cls.Canvas = cls.env['printflow.flow.canvas']
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Déficit Compras'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Déficit Compras', 'supplier_rank': 1})

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests del flujo)
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _purchasable(self, name):
        product = self._product(
            name, purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _deficit_purchasable(self, name):
        """Comprable con déficit físico (existencia negativa)."""
        product = self._purchasable(name)
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        return product

    def _manufacturable_purchasable_deficit(self, name):
        """FABRICABLE (con BOM) y COMPRABLE, con déficit -> eje manufacture."""
        component = self._product('%s COMPONENTE' % name)
        finished = self._purchasable(name)
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        self.env['stock.quant']._update_available_quantity(
            finished, self.stock_location, -3.0)
        return finished

    @staticmethod
    def _deficit_of(product):
        """Déficit físico real (MISMA fórmula del motor/wizard)."""
        return max(
            0.0,
            (product.outgoing_qty or 0.0)
            - (product.qty_available or 0.0)
            - (product.incoming_qty or 0.0))

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    def _product_payload(self, product):
        return self.Canvas._pf_build_payload(self._wizard(product), 'product')

    @staticmethod
    def _by_key(payload):
        return {node['key']: node for node in payload['nodes']}

    def _order(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        return wizard, line

    # ==================================================================
    # CA-1 — El nodo Compras muestra la MAGNITUD del faltante
    # ==================================================================
    def test_ca1_purchase_node_shows_shortfall_magnitude(self):
        product = self._deficit_purchasable('DEFICIT CA1')
        deficit = self._deficit_of(product)
        self.assertGreater(deficit, 0.0)

        payload = self._product_payload(product)
        by_key = self._by_key(payload)
        purchase = by_key['purchase']

        # La magnitud viaja en el badge ADITIVO (no en status_label/summary).
        self.assertEqual(
            purchase['shortfall_qty'], deficit,
            'El nodo Compras debe reflejar la cantidad del déficit.')
        self.assertTrue(purchase['shortfall_label'])
        # El contrato del nodo SIEMPRE trae las claves; solo Compras la llena.
        for node in payload['nodes']:
            self.assertIn('shortfall_qty', node)
            self.assertIn('shortfall_label', node)
            if node['key'] != 'purchase':
                self.assertEqual(node['shortfall_qty'], 0.0)
                self.assertEqual(node['shortfall_label'], '')

    # ==================================================================
    # CA-2 — La resolución guía a COMPRAR lo que falta (producto y pedido)
    # ==================================================================
    def test_ca2_product_solution_guides_to_quick_purchase(self):
        product = self._deficit_purchasable('DEFICIT CA2 PRODUCTO')
        wizard = self._wizard(product)
        po_before = self.env['purchase.order'].search_count([])

        action = wizard.action_run_pf_plan('order_supply_missing', 'solution')

        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        self.assertEqual(
            self.env['purchase.order'].search_count([]), po_before,
            'Abrir la solución NO debe crear la OC (abrir ≠ ejecutar).')

    def test_ca2_order_solution_guides_to_quick_purchase(self):
        product = self._purchasable('DEFICIT CA2 PEDIDO')
        _wizard, line = self._order(product, 4.0)
        purchase = line.failure_ids.filtered(
            lambda f: f.node == 'purchase')[:1]
        self.assertTrue(purchase)
        # La SOLUCIÓN del plan ya guía a comprar el faltante (buy_product).
        self.assertEqual(purchase.pf_solution_target, 'buy_product')
        po_before = self.env['purchase.order'].search_count([])

        action = purchase.action_open_solution()

        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        self.assertEqual(
            self.env['purchase.order'].search_count([]), po_before,
            'Abrir la solución NO debe crear la OC (abrir ≠ ejecutar).')

    # ==================================================================
    # CA-3 — Generaliza: producto FABRICABLE + comprable con déficit
    # ==================================================================
    def test_ca3_manufacture_axis_also_carries_shortfall(self):
        product = self._manufacturable_purchasable_deficit('DEFICIT CA3')
        wizard = self._wizard(product)
        self.assertEqual(wizard.flow_type, 'manufacture')

        payload = self.Canvas._pf_build_payload(wizard, 'product')
        by_key = self._by_key(payload)
        deficit = self._deficit_of(product)
        self.assertGreater(deficit, 0.0)
        # El eje es fabricación, pero el faltante de Compras sigue visible.
        self.assertIn('production', by_key)
        self.assertEqual(by_key['purchase']['shortfall_qty'], deficit)

    # ==================================================================
    # CA-4 — Paridad: el diagrama del PEDIDO también lleva la magnitud
    # ==================================================================
    def test_ca4_order_diagram_parity(self):
        product = self._purchasable('DEFICIT CA4')
        wizard, line = self._order(product, 5.0)
        wizard.write({'focus_line_id': line.id})

        payload = json.loads(wizard.focus_timeline_json)
        by_key = self._by_key(payload)
        self.assertGreater(line.deficit_qty, 0.0)
        self.assertEqual(
            by_key['purchase']['shortfall_qty'], line.deficit_qty)

    # ==================================================================
    # CA-5 — SOLO LECTURA (rollback + sin SQL crudo)
    # ==================================================================
    def test_ca5_navigation_is_read_only(self):
        product = self._deficit_purchasable('DEFICIT CA5')
        qty_before = product.qty_available
        po_before = self.env['purchase.order'].search_count([])

        self._product_payload(product)
        self._wizard(product).action_run_pf_plan(
            'order_supply_missing', 'solution')

        self.assertEqual(product.qty_available, qty_before)
        self.assertEqual(
            self.env['purchase.order'].search_count([]), po_before)

    def test_ca5_touched_files_have_no_raw_sql(self):
        module_path = get_module_path('printflow_gestion_inventario')
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)
