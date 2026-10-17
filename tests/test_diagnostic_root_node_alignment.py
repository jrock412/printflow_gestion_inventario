# -*- coding: utf-8 -*-
"""Alineación del nodo RAÍZ con el nodo que CORRIGE la falla (PrintFlow).

Bug real: el nodo RAÍZ (anillo/badge/tray/"Solucionar") se derivaba de
``line.root_cause_node``, pero la falla RAÍZ puede RESOLVERSE en otro hito. Caso
típico: déficit de COMPONENTE -> la falla se hospeda en ``stock_supply``, pero
``root_cause_node == 'stock'`` apuntaba el anillo a ``stock_finished``.

Regla nueva (§2): si existe una falla con ``pf_chain_role == 'root'``, el slot
del nodo de corrección es ``_pf_failure_slot(root_failure)`` (respeta el remap
component->supply) y con ESE slot se calculan los roles. Así el anillo RAÍZ y
"Solucionar" caen SIEMPRE en el mismo nodo donde se corrige.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticRootNodeAlignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Root Alignment'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Root Alignment', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _force_order(self, product, qty):
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
        return so, board

    def _wizard_for(self, product, qty):
        _so, board = self._force_order(product, qty)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line, 'El wizard debe tener la línea del terminado.')
        wizard.write({'focus_line_id': line.id})
        return wizard, line

    def _purchase_root(self):
        product = self._product(
            'ALIGN COMPRA RAIZ', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return self._wizard_for(product, 4.0)

    def _manufactured_comprable(self):
        component = self._product(
            'ALIGN MIXTO COMPONENTE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        finished = self._product('ALIGN MIXTO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 2.0})],
        })
        return self._wizard_for(finished, 3.0)

    def _component_contention(self):
        """Terminado fabricable + COMPONENTE retenido por otro pedido.

        Genera una falla de STOCK sobre el COMPONENTE (``origin_kind ==
        component``): su slot de canvas es ``supply``, aunque su nodo causal sea
        ``stock`` (el remap component->supply).
        """
        component = self._product('ALIGN CHIP COMPONENTE')
        finished = self._product('ALIGN CHIP TERMINADO')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 2.0})],
        })
        self._add_stock(component, 10.0)
        other = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': component.id,
                'product_uom_qty': 10.0,
                'product_uom': component.uom_id.id,
            })],
        })
        other.action_confirm()
        self._add_stock(finished, 3.0)
        _so, board = self._force_order(finished, 3.0)
        board.write({'production_alert': 'no_order'})
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        wizard.write({'focus_line_id': line.id})
        return wizard, line

    # ------------------------------------------------------------------
    # 1) El remap component->supply existe (base del arreglo)
    # ------------------------------------------------------------------
    def test_component_stock_failure_maps_to_supply(self):
        wizard, line = self._component_contention()
        component_failures = line.flow_failure_ids.filtered(
            lambda f: f.node == 'stock'
            and f.origin_kind in ('component', 'estimated'))
        self.assertTrue(
            component_failures, 'Debe existir una falla del COMPONENTE.')
        failure = component_failures[:1]
        self.assertEqual(wizard._pf_failure_slot(failure), 'supply')
        payload = json.loads(wizard.focus_timeline_json)
        by_key = {n['key']: n for n in payload['nodes']}
        panel_ids = [
            row['failure_id'] for row in by_key['stock_supply']['panel']]
        self.assertIn(failure.id, panel_ids)

    # ------------------------------------------------------------------
    # 2) Invariante: el nodo RAÍZ es el que HOSPEDA la falla raíz
    # ------------------------------------------------------------------
    def _assert_root_alignment(self, wizard, line):
        payload = json.loads(wizard.focus_timeline_json)
        by_key = {n['key']: n for n in payload['nodes']}
        root_failure = line.flow_failure_ids.filtered(
            lambda f: f.pf_chain_role == 'root')[:1]
        self.assertTrue(root_failure, 'Debe haber una falla RAÍZ.')
        slot = wizard._pf_failure_slot(root_failure)
        key_by_slot = wizard._pf_key_by_slot(payload['axis'])
        expected_key = key_by_slot.get(slot)
        self.assertIsNotNone(expected_key)
        node = by_key[expected_key]
        # El anillo RAÍZ y el hito que corrige son el MISMO nodo.
        self.assertEqual(node['role'], 'root')
        self.assertEqual(node['chain'], slot)
        panel_ids = [row['failure_id'] for row in node['panel']]
        self.assertIn(root_failure.id, panel_ids)

    def test_purchase_root_alignment(self):
        wizard, line = self._purchase_root()
        self._assert_root_alignment(wizard, line)

    def test_manufactured_root_alignment(self):
        wizard, line = self._manufactured_comprable()
        self._assert_root_alignment(wizard, line)

    def test_component_contention_root_alignment(self):
        wizard, line = self._component_contention()
        self._assert_root_alignment(wizard, line)

    # ------------------------------------------------------------------
    # 3) Regresión directa: el root ROW apunta al slot de la falla raíz
    #    (no al slot derivado de `root_cause_node`)
    # ------------------------------------------------------------------
    def test_payload_uses_root_failure_slot(self):
        wizard, line = self._manufactured_comprable()
        payload = json.loads(wizard.focus_timeline_json)
        root_failure = line.flow_failure_ids.filtered(
            lambda f: f.pf_chain_role == 'root')[:1]
        self.assertTrue(root_failure)
        slot = wizard._pf_failure_slot(root_failure)
        key_by_slot = wizard._pf_key_by_slot(payload['axis'])
        root_nodes = [n for n in payload['nodes'] if n['role'] == 'root']
        self.assertTrue(root_nodes)
        self.assertIn(key_by_slot.get(slot), [n['key'] for n in root_nodes])
