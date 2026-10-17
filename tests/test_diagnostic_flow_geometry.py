# -*- coding: utf-8 -*-
"""Canvas secuencial del diagrama de flujo del diagnóstico de pedido.

El payload de ``focus_timeline_json`` expone el CANVAS del producto enfocado:

  * ``order``: la espina CAUSAL (``PF_CHAIN_ORDER``), intacta;
  * ``flow_type``: ``'purchase'`` o ``'manufacture'`` (lo detecta el motor);
  * ``axis``: recorrido FÍSICO secuencial según el tipo, termina en ``customer``;
  * ``nodes``: nodos de canvas (geometría + estado + acciones);
  * ``layout``: solo ``grid``/``cell`` (sin ``decision``/``branches``);
  * ``edges``: flujo secuencial + errores raíz -> consecuencia.

Estos tests custodian:
  * el esqueleto COMPLETO por tipo (comprar y fabricar);
  * la ausencia TOTAL del rombo y las ramas paralelas;
  * que la venta NO viaja al canvas (es solo lógica);
  * la integridad referencial de las aristas contra los nodos;
  * el caso seguro sin foco.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_ORDER

# Ejes esperados por tipo de flujo.
AXIS_PURCHASE = [
    'purchase', 'receipt', 'stock', 'delivery', 'customer']
AXIS_MANUFACTURE = [
    'purchase', 'receipt', 'stock_supply', 'production', 'stock_finished',
    'delivery', 'customer']


@tagged('post_install', '-at_install')
class TestDiagnosticFlowGeometry(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Flow Geometry',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Flow Geometry',
            'supplier_rank': 1,
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _bom(self, finished, component, qty=1.0):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': qty,
            })],
        })

    def _force_order(self, product, qty, partner=None):
        so = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
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
        return wizard

    def _payload(self, wizard):
        return json.loads(wizard.focus_timeline_json)

    @staticmethod
    def _node_keys(payload):
        return [node['key'] for node in payload['nodes']]

    @staticmethod
    def _edge_pairs(payload):
        return {(e['from'], e['to']) for e in payload['edges']}

    # ------------------------------------------------------------------
    # Escenarios
    # ------------------------------------------------------------------
    def _purchase_only(self):
        """Comprable SIN stock ni PO: recorrido de COMPRA."""
        product = self._product(
            'FLOW COMPRADO', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return self._wizard_for(product, 4.0)

    def _manufactured(self):
        """Fabricable con BOM: recorrido de FABRICACIÓN."""
        component = self._product('FLOW FAB COMPONENTE', purchase_ok=False)
        self._add_stock(component, 100.0)
        finished = self._product('FLOW FABRICADO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._bom(finished, component, 1.0)
        return self._wizard_for(finished, 3.0)

    def _manufactured_comprable(self):
        """Fabricable cuyo COMPONENTE comprable falta."""
        component = self._product(
            'FLOW MIXTO COMPONENTE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        finished = self._product('FLOW MIXTO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._bom(finished, component, 2.0)
        return self._wizard_for(finished, 3.0)

    # ------------------------------------------------------------------
    # 1) Claves del canvas (sin rombo ni ramas)
    # ------------------------------------------------------------------
    def test_payload_has_canvas_keys(self):
        payload = self._payload(self._manufactured_comprable())
        for key in ('order', 'flow_type', 'axis', 'global', 'nodes', 'layout',
                    'edges'):
            self.assertIn(key, payload)
        # El rombo y las ramas paralelas quedaron ELIMINADOS.
        self.assertNotIn('decision', payload)
        self.assertNotIn('branches', payload)
        self.assertNotIn('preparation', payload)
        self.assertIn('grid', payload['layout'])
        self.assertIn('cell', payload['layout'])
        self.assertNotIn('shapes', payload['layout'])
        self.assertTrue(payload['nodes'])
        self.assertTrue(payload['edges'])

    # ------------------------------------------------------------------
    # 2) Espina causal intacta + eje secuencial por tipo
    # ------------------------------------------------------------------
    def test_order_and_axis_unchanged(self):
        purchased = self._payload(self._purchase_only())
        manufactured = self._payload(self._manufactured_comprable())
        for payload in (purchased, manufactured):
            self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
            self.assertEqual(len(payload['nodes']), len(payload['axis']))
            self.assertEqual(payload['axis'][-1], 'customer')
        self.assertEqual(purchased['flow_type'], 'purchase')
        self.assertEqual(purchased['axis'], AXIS_PURCHASE)
        self.assertEqual(manufactured['flow_type'], 'manufacture')
        self.assertEqual(manufactured['axis'], AXIS_MANUFACTURE)

    # ------------------------------------------------------------------
    # 3) Recorrido de COMPRA
    # ------------------------------------------------------------------
    def test_bought_case(self):
        payload = self._payload(self._purchase_only())
        self.assertEqual(self._node_keys(payload), AXIS_PURCHASE)
        by_key = {n['key']: n for n in payload['nodes']}
        # Compra faltante -> recepción N/A (derivada de purchase).
        self.assertEqual(by_key['purchase']['status'], 'missing')
        self.assertEqual(by_key['receipt']['status'], 'na')
        self.assertEqual(by_key['purchase']['owner'], 'purchase')
        self.assertEqual(by_key['receipt']['owner'], 'purchase')
        # El flujo es secuencial de punta a punta.
        pairs = self._edge_pairs(payload)
        for src, dst in zip(AXIS_PURCHASE, AXIS_PURCHASE[1:]):
            self.assertIn((src, dst), pairs)

    # ------------------------------------------------------------------
    # 4) Recorrido de FABRICACIÓN (insumos/terminado)
    # ------------------------------------------------------------------
    def test_manufactured_case(self):
        payload = self._payload(self._manufactured_comprable())
        self.assertEqual(self._node_keys(payload), AXIS_MANUFACTURE)
        by_key = {n['key']: n for n in payload['nodes']}
        self.assertEqual(by_key['stock_supply']['owner'], 'stock')
        self.assertEqual(by_key['stock_finished']['owner'], 'stock')
        self.assertEqual(by_key['production']['owner'], 'production')
        pairs = self._edge_pairs(payload)
        self.assertIn(('stock_supply', 'production'), pairs)
        self.assertIn(('production', 'stock_finished'), pairs)

    # ------------------------------------------------------------------
    # 5) Errores raíz -> consecuencia
    # ------------------------------------------------------------------
    def test_error_edges_root_to_consequence(self):
        payload = self._payload(self._purchase_only())
        errors = [e for e in payload['edges'] if e['type'] == 'error']
        self.assertTrue(errors)
        target = next(
            (e for e in errors
             if e['from'] == 'purchase' and e['to'] == 'stock'), None)
        self.assertIsNotNone(target)
        self.assertTrue(target['chain'])
        self.assertEqual(target['label'], 'Causa → Consecuencia')
        stock = next(n for n in payload['nodes'] if n['key'] == 'stock')
        self.assertEqual(target['tone'], 'danger')
        self.assertEqual(stock['role'], 'consequence')

    # ------------------------------------------------------------------
    # 6) Integridad: cada extremo de arista existe como nodo
    # ------------------------------------------------------------------
    def test_edges_reference_existing_nodes(self):
        for wizard in (self._purchase_only(), self._manufactured(),
                       self._manufactured_comprable()):
            payload = self._payload(wizard)
            node_keys = set(self._node_keys(payload))
            for edge in payload['edges']:
                self.assertIn(edge['from'], node_keys,
                              'origen huérfano: %s' % edge['from'])
                self.assertIn(edge['to'], node_keys,
                              'destino huérfano: %s' % edge['to'])

    # ------------------------------------------------------------------
    # 7) El cliente es terminal y la venta NO está en el canvas
    # ------------------------------------------------------------------
    def test_customer_terminal_and_no_sale(self):
        payload = self._payload(self._manufactured())
        by_key = {n['key']: n for n in payload['nodes']}
        self.assertEqual(by_key['customer']['kind'], 'terminal')
        self.assertEqual(by_key['customer']['tone'], 'ok')
        self.assertNotIn('sale', self._node_keys(payload))
        self.assertNotIn('sale', payload['axis'])

    # ------------------------------------------------------------------
    # 8) Sin foco: payload seguro
    # ------------------------------------------------------------------
    def test_geometry_without_focus_is_safe(self):
        product = self._product('FLOW SIN FOCO')
        _so, board = self._force_order(product, 1.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        self.assertFalse(wizard.focus_line_id)
        payload = self._payload(wizard)
        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        self.assertEqual(payload['axis'], AXIS_PURCHASE)
        for node in payload['nodes']:
            self.assertIsNone(node['status'])
            self.assertEqual(node['actions'], [])
        node_keys = set(self._node_keys(payload))
        for edge in payload['edges']:
            self.assertIn(edge['from'], node_keys)
            self.assertIn(edge['to'], node_keys)

    # ------------------------------------------------------------------
    # 9) 2 FILAS de LECTURA NORMAL (izq->der en AMBAS): col/row por tipo
    # ------------------------------------------------------------------
    def _assert_left_to_right_layout(self, payload, per_row):
        """Contrato del reparto en 2 filas de lectura L->R.

        * ``rows == 2`` (el eje tiene más de 4 hitos) y ``cols == per_row``;
        * fila 0: ``col = index`` (izquierda a derecha);
        * fila 1: ``col = index - per_row`` (TAMBIÉN izquierda a derecha; el
          nodo ``per_row`` —el "5"— cae en ``col = 0``, bajo el nodo 1);
        * un MÁXIMO de un nodo por celda ``(col, row)``;
        * existe la arista de BAJADA ``axis[per_row-1] -> axis[per_row]`` (el
          retorno del último de la fila 0 al primero de la fila 1).
        """
        grid = payload['layout']['grid']
        self.assertEqual(grid, {'cols': per_row, 'rows': 2})
        axis = payload['axis']
        by_key = {n['key']: n for n in payload['nodes']}
        seen = set()
        for index, key in enumerate(axis):
            expected = (index - per_row, 1) if index >= per_row else (index, 0)
            node = by_key[key]
            self.assertEqual(
                (node['col'], node['row']), expected,
                'Geometría inesperada en %s' % key)
            cell = (node['col'], node['row'])
            self.assertNotIn(
                cell, seen, 'Dos nodos en la celda %s' % (cell,))
            seen.add(cell)
        # La arista de bajada entre filas une el último de la fila 0 con el
        # primero de la fila 1.
        self.assertIn((axis[per_row - 1], axis[per_row]),
                      self._edge_pairs(payload))

    def test_two_row_reading_layout_purchase(self):
        """5 hitos -> 2 filas (ambas izq->der): el "4" cae bajo el nodo 1."""
        payload = self._payload(self._purchase_only())
        self._assert_left_to_right_layout(payload, per_row=3)
        by_key = {n['key']: n for n in payload['nodes']}
        expected = {
            'purchase': (0, 0), 'receipt': (1, 0), 'stock': (2, 0),
            'delivery': (0, 1), 'customer': (1, 1),
        }
        for key, (col, row) in expected.items():
            self.assertEqual(
                (by_key[key]['col'], by_key[key]['row']), (col, row),
                'Geometría inesperada en %s' % key)

    def test_two_row_reading_layout_manufacture(self):
        """7 hitos -> 2 filas de 4; ambas filas se leen izq->der."""
        payload = self._payload(self._manufactured_comprable())
        self._assert_left_to_right_layout(payload, per_row=4)
        by_key = {n['key']: n for n in payload['nodes']}
        expected = {
            'purchase': (0, 0), 'receipt': (1, 0), 'stock_supply': (2, 0),
            'production': (3, 0), 'stock_finished': (0, 1),
            'delivery': (1, 1), 'customer': (2, 1),
        }
        for key, (col, row) in expected.items():
            self.assertEqual(
                (by_key[key]['col'], by_key[key]['row']), (col, row),
                'Geometría inesperada en %s' % key)
        # `nodes` SIGUE en orden de eje (contrato) y `seq` sigue 1..N.
        self.assertEqual(
            [n['key'] for n in payload['nodes']], payload['axis'])
        self.assertEqual(
            [n['seq'] for n in payload['nodes']],
            list(range(1, len(payload['axis']) + 1)))

    # ------------------------------------------------------------------
    # 10) Geometría de la celda: el JS la LEE del payload (fuente única)
    # ------------------------------------------------------------------
    def test_layout_cell_is_present(self):
        payload = self._payload(self._purchase_only())
        cell = payload['layout']['cell']
        for key in ('w', 'h', 'gap_x', 'gap_y', 'pad_top'):
            self.assertIn(key, cell)
        self.assertEqual(cell['h'], 132)

    def test_widget_reads_geometry_from_payload(self):
        """El JS NO duplica las constantes: lee ``layout.cell``/``layout.grid``."""
        module_path = get_module_path('printflow_gestion_inventario')
        js_path = os.path.join(
            module_path, 'static', 'src', 'js', 'printflow_order_timeline.js')
        with open(js_path, encoding='utf-8') as handle:
            js = handle.read()
        self.assertIn('payload.layout.cell', js)
        self.assertIn('payload.layout.grid', js)
