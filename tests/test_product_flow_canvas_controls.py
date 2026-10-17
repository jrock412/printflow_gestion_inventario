# -*- coding: utf-8 -*-
"""Controles del canvas de PRODUCTO (PrintFlow · Fase 5).

Custodia los controles de presentación que ahora comparte con el pedido:
  * roles de cadena (root/consequence/independent) y su padre;
  * ``root_link`` en la consecuencia ("Se rompió porque falló X");
  * arista de ERROR raíz -> consecuencia con su píldora;
  * ``tray`` en la raíz, ``summary``/``summary_more`` y ``extra_count``;
  * un producto SANO conserva el flujo secuencial (sin aristas de error).

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

import json

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_LABELS


@tagged('post_install', '-at_install')
class TestProductFlowCanvasControls(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Controles Producto', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']

    def _purchasable(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True, 'purchase_ok': True,
            'seller_ids': [(0, 0, {'partner_id': self.supplier.id})],
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    def _payload(self, wizard):
        return json.loads(wizard.timeline_json)

    def _broken(self, name):
        product = self._purchasable(name)
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        return product

    # ------------------------------------------------------------------
    # 1) Raíz, consecuencia, arista de error y root_link
    # ------------------------------------------------------------------
    def test_root_consequence_and_error_edge(self):
        wizard = self._wizard(self._broken('CONTROLES CADENA'))
        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}

        self.assertEqual(payload['global']['root'], 'purchase')
        self.assertEqual(by_key['purchase']['role'], 'root')
        self.assertIsNone(by_key['purchase']['parent'])
        self.assertIn('tray', by_key['purchase'])

        consequence = by_key['stock']
        self.assertEqual(consequence['role'], 'consequence')
        self.assertEqual(consequence['parent'], 'purchase')
        self.assertIn('root_link', consequence)
        self.assertEqual(consequence['root_link']['target_key'], 'purchase')
        self.assertIn(
            PF_CHAIN_LABELS['purchase'], consequence['root_link']['label'])
        self.assertNotIn(
            'solution', [a['key'] for a in consequence['actions']])

        error_edges = [e for e in payload['edges'] if e['type'] == 'error']
        self.assertIn(('purchase', 'stock'),
                      {(e['from'], e['to']) for e in error_edges})

    # ------------------------------------------------------------------
    # 2) summary / summary_more / extra_count en el nodo roto
    # ------------------------------------------------------------------
    def test_node_summary_and_extra_count(self):
        wizard = self._wizard(self._broken('CONTROLES RESUMEN'))
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        purchase = by_key['purchase']
        self.assertTrue(purchase['summary'])
        self.assertEqual(purchase['issues'], len(purchase['panel']))
        self.assertEqual(
            purchase['summary_more'], max(0, purchase['issues'] - 1))
        self.assertEqual(purchase['extra_count'], 0)

    # ------------------------------------------------------------------
    # 3) El producto SANO solo trae flujo secuencial (sin errores)
    # ------------------------------------------------------------------
    def test_healthy_product_has_only_flow_edges(self):
        wizard = self._wizard(self._purchasable('CONTROLES SANO'))
        payload = self._payload(wizard)
        self.assertIsNone(payload['global']['root'])
        self.assertTrue(payload['edges'])
        self.assertTrue(
            all(edge['type'] == 'flow' for edge in payload['edges']))
        for node in payload['nodes']:
            self.assertEqual(node['role'], 'none')
            self.assertEqual(node['panel'], [])
            self.assertNotIn('tray', node)
