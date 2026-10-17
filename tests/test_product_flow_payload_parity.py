# -*- coding: utf-8 -*-
"""Candado del payload del PRODUCTO (PrintFlow · Fase 0 del refactor OOP).

Gemelo de ``test_flow_canvas_parity.py`` (que custodia el payload del PEDIDO).
Fija el CONTRATO OBSERVABLE del diagrama de un PRODUCTO sin venta, que arma la
fábrica ÚNICA ``printflow.flow.canvas._pf_build_payload(host, 'product')``.

Por qué existe
--------------
El plan de refactor OOP (``docs/plan_fases_orquestador_oop_v2.md``) promete que
la unificación del Builder NO cambia el payload. Hasta hoy solo había candado
del PEDIDO; el del PRODUCTO no existía. Sin un ``deep-equal`` del payload del
producto, mover el armado del canvas es a ciegas: cualquier cambio silencioso
de nodos/aristas/acciones rompería el widget OWL sin que ningún test lo note.

Enfoque (elegido por ser el más robusto sin ser frágil)
-------------------------------------------------------
1. **Paridad**: lo serializado por el wizard (``timeline_json``) es EXACTAMENTE
   lo que devuelve la fábrica ``_pf_build_payload(wizard, 'product')``. Blinda
   que el producto NO tenga un segundo motor de armado (una de las razones del
   refactor) y que el JSON sea un round-trip fiel.
2. **Determinismo**: dos llamadas a la fábrica dan el mismo dict (sin efectos
   colaterales ni orden inestable). Esto es lo que permite comparar contra un
   fixture congelado.
3. **Fixture congelado del ESQUELETO**: para el escenario de compra con déficit
   se compara, ``deep-equal``, una lista literal con la huella ESTABLE de cada
   nodo (``key/label/seq/kind/shape/owner/chain/role/parent/col/row/status/
   tone/status_label``). Se excluyen a propósito los campos volátiles
   (``res_id``, ``failure_id``) y los de texto libre no congelables aquí
   (``summary``).
4. **Contrato estructural**: además del esqueleto, se congelan el conjunto de
   claves de nodo, el vocabulario de ``actions[*].key``, el conjunto de claves
   de arista, los ``id`` de las aristas de flujo, la geometría (``layout``) y
   el esquema de filas de ``panel``/``tray``. Así se bloquea cualquier alta/baja
   o renombre de campo, no solo los valores del escenario.

Por qué NO un fixture del payload COMPLETO
------------------------------------------
Un literal del payload entero incluiría ``res_id`` (id del wizard), ids de BOM/
OC/OF y texto traducido: sería un candado frágil que rompería por datos de
entorno y no por el refactor. El esqueleto + esquema captura el contrato que el
widget consume realmente y tolera esa volatilidad.

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar (cero escritura persistente a la BD).
"""

import json

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_ORDER

# ── Contrato CONGELADO del canvas de producto (no importado de producción) ──
# Estos literales son el "contrato observable": si el refactor los cambia, este
# candado debe ladrar. Se escriben a mano a propósito (no se importan) para que
# un cambio en producción NO se propague solo al test.

AXIS_PURCHASE = ['purchase', 'receipt', 'stock', 'delivery', 'customer']
AXIS_MANUFACTURE = [
    'purchase', 'receipt', 'stock_supply', 'production', 'stock_finished',
    'delivery', 'customer',
]

NODE_META = {
    'purchase': {
        'label': 'Compras', 'kind': 'node', 'shape': 'process',
        'owner': 'purchase', 'chain': 'purchase'},
    'receipt': {
        'label': 'Recepción', 'kind': 'node', 'shape': 'process',
        'owner': 'purchase', 'chain': 'purchase'},
    'stock': {
        'label': 'Inventario', 'kind': 'node', 'shape': 'process',
        'owner': 'stock', 'chain': 'inventory'},
    'stock_supply': {
        'label': 'Almacén insumos', 'kind': 'node', 'shape': 'process',
        'owner': 'stock', 'chain': 'supply'},
    'production': {
        'label': 'Fabricación', 'kind': 'node', 'shape': 'process',
        'owner': 'production', 'chain': 'production'},
    'stock_finished': {
        'label': 'Almacén terminado', 'kind': 'node', 'shape': 'process',
        'owner': 'stock', 'chain': 'inventory'},
    'delivery': {
        'label': 'Entrega', 'kind': 'node', 'shape': 'process',
        'owner': 'delivery', 'chain': 'delivery'},
    'customer': {
        'label': 'Cliente', 'kind': 'terminal', 'shape': 'end',
        'owner': 'delivery', 'chain': 'delivery'},
}

LAYOUT_CELL = {'w': 176, 'h': 132, 'gap_x': 24, 'gap_y': 28, 'pad_top': 72}

TOP_LEVEL_KEYS = frozenset(
    {'order', 'flow_type', 'axis', 'global', 'nodes', 'layout', 'edges'})

# Claves SIEMPRE presentes en un nodo (el orden no importa; se compara el set).
BASE_NODE_KEYS = frozenset({
    'key', 'label', 'seq', 'kind', 'shape', 'col', 'row', 'owner', 'chain',
    'status', 'status_label', 'tone', 'role', 'parent', 'issues', 'anomaly',
    'summary', 'summary_more', 'extra_count', 'info', 'pending',
    # Etiqueta EXPLÍCITA del pendiente por nodo (D5, campo ADITIVO del nodo).
    'pending_label',
    # Magnitud del FALTANTE por nodo (D1, campos ADITIVOS del nodo): Compras
    # expone el déficit real; el resto queda en 0 / cadena vacía.
    'shortfall_qty', 'shortfall_label',
    'pending_action', 'actions', 'panel', 'explain',
})

# Contrato de la capa de EXPLICACIÓN por nodo (plan aprobado).
EXPLAIN_KEYS = frozenset({'headline', 'what', 'why', 'how', 'severity'})
EXPLAIN_SEVERITIES = frozenset({'ok', 'info', 'warn', 'danger'})

# Claves que el nodo agrega CONDICIONALMENTE (raíz / consecuencia).
ROOT_ONLY_NODE_KEYS = frozenset({'tray'})
CONSEQUENCE_ONLY_NODE_KEYS = frozenset({'root_link'})

EDGE_KEYS = frozenset(
    {'id', 'from', 'to', 'type', 'label', 'lane', 'side', 'tone', 'chain',
     'style'})

ACTION_BASE_KEYS = frozenset(
    {'key', 'label', 'enabled', 'kind', 'failure_id', 'res_model', 'res_id',
     'method'})
ACTION_OPTIONAL_KEYS = frozenset(
    {'args', 'target_key', 'primary', 'sublabel'})

# Vocabulario COMPLETO de claves de acción del producto (nodos + filas de panel).
ALLOWED_ACTION_KEYS = frozenset({
    'solution', 'problem', 'open_list', 'buy_product', 'buy_components',
    'view_purchase', 'receive', 'quants', 'adjust', 'fix_reservation',
    'cleanup_reservations', 'blocking', 'fabricate', 'delivery_orders',
    'pending', 'open_product', 'collect', 'inventory_health',
    # Bandeja gestionable de insumos: abre el hito ALMACÉN DE INSUMOS roto.
    'fix_supply',
})

PANEL_ROW_KEYS = frozenset({
    'failure_id', 'label', 'detail', 'origin', 'origin_kind', 'chain_note',
    'plan_summary', 'role', 'tone', 'is_consequence', 'problem_available',
    'solution_available', 'collect_available', 'actions',
})

TRAY_ROW_KEYS = frozenset(
    {'label', 'detail', 'ref_name', 'state_label', 'res_model', 'res_id'})

# Nodo CAUSAL de quiebre (``global.root``) -> SLOT de canvas (contrato congelado).
# El ``tray`` vive SOLO en el hito que representa ese slot (``key_by_slot``), no
# en todo nodo con rol ``root`` (p.ej. 'receipt' comparte slot con 'purchase').
ROOT_CAUSE_TO_SLOT = {
    'sale': 'sale', 'purchase': 'purchase', 'supply': 'supply',
    'production': 'production', 'stock': 'inventory', 'delivery': 'delivery',
}

# Escenario A: producto COMPRABLE con déficit físico -> Compras (raíz) e
# Inventario (consecuencia). El rol de 'receipt' es 'root' porque comparte el
# SLOT 'purchase' con 'purchase' (comportamiento actual congelado a propósito).
FROZEN_SKELETON_PURCHASE_DEFICIT = [
    {'key': 'purchase', 'label': 'Compras', 'seq': 1, 'kind': 'node',
     'shape': 'process', 'owner': 'purchase', 'chain': 'purchase',
     'role': 'root', 'parent': None, 'status': 'missing', 'tone': 'danger',
     'status_label': 'Falta comprar', 'col': 0, 'row': 0},
    {'key': 'receipt', 'label': 'Recepción', 'seq': 2, 'kind': 'node',
     'shape': 'process', 'owner': 'purchase', 'chain': 'purchase',
     'role': 'root', 'parent': None, 'status': 'na', 'tone': 'na',
     'status_label': 'No aplica', 'col': 1, 'row': 0},
    {'key': 'stock', 'label': 'Inventario', 'seq': 3, 'kind': 'node',
     'shape': 'process', 'owner': 'stock', 'chain': 'inventory',
     'role': 'consequence', 'parent': 'purchase', 'status': 'deficit',
     'tone': 'danger', 'status_label': 'Sin stock', 'col': 2, 'row': 0},
    {'key': 'delivery', 'label': 'Entrega', 'seq': 4, 'kind': 'node',
     'shape': 'process', 'owner': 'delivery', 'chain': 'delivery',
     'role': 'none', 'parent': None, 'status': 'na', 'tone': 'na',
     'status_label': 'Sin dato / N/A', 'col': 0, 'row': 1},
    {'key': 'customer', 'label': 'Cliente', 'seq': 5, 'kind': 'terminal',
     'shape': 'end', 'owner': 'delivery', 'chain': 'delivery',
     'role': 'none', 'parent': None, 'status': 'ok', 'tone': 'ok',
     'status_label': 'Entregado', 'col': 1, 'row': 1},
]

_SKELETON_FIELDS = (
    'key', 'label', 'seq', 'kind', 'shape', 'owner', 'chain', 'role',
    'parent', 'status', 'tone', 'status_label', 'col', 'row')


@tagged('post_install', '-at_install')
class TestProductFlowPayloadParity(TransactionCase):
    """Candado del contrato del payload del diagrama de PRODUCTO."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Payload Producto', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']
        cls.Canvas = cls.env['printflow.flow.canvas']

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests del producto)
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

    def _manufacturable(self, name):
        """Terminado fabricable con BOM a un COMPONENTE FALTANTE (sin stock)."""
        component = self._product('%s COMPONENTE' % name)
        finished = self._product(name)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        return finished

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _factory(self, wizard):
        return self.Canvas._pf_build_payload(wizard, 'product')

    def _payload(self, wizard):
        return json.loads(wizard.timeline_json)

    def _deficit_purchasable(self, name):
        product = self._purchasable(name)
        # Existencia negativa -> déficit físico -> Compras raíz + Inventario.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        return product

    # ------------------------------------------------------------------
    # Contrato estructural (aplica a CUALQUIER producto)
    # ------------------------------------------------------------------
    def _assert_node_actions(self, wizard, node):
        for action in node['actions']:
            self.assertTrue(
                set(action) <= ACTION_BASE_KEYS | ACTION_OPTIONAL_KEYS,
                'Acción con claves fuera del contrato: %s' % sorted(action))
            self.assertTrue(ACTION_BASE_KEYS <= set(action))
            self.assertIn(
                action['key'], ALLOWED_ACTION_KEYS,
                'Clave de acción fuera del vocabulario: %r' % action['key'])
            self.assertEqual(action['res_model'], 'printflow.product.flow')
            self.assertEqual(action['res_id'], wizard.id)
            self.assertTrue(action['enabled'])

    def _assert_node_explain(self, node):
        """Congela el contrato de la capa de EXPLICACIÓN de un nodo."""
        explain = node['explain']
        self.assertEqual(
            set(explain), EXPLAIN_KEYS,
            'Esquema de explain cambiado en %r' % node['key'])
        self.assertIsInstance(explain['headline'], str)
        self.assertIsInstance(explain['what'], str)
        self.assertIsInstance(explain['why'], list)
        self.assertIsInstance(explain['how'], list)
        self.assertIn(explain['severity'], EXPLAIN_SEVERITIES)

    def _assert_panel_rows(self, wizard, node):
        for row in node['panel']:
            self.assertEqual(set(row), PANEL_ROW_KEYS)
            self.assertIsInstance(row['failure_id'], int)
            self.assertTrue(row['failure_id'] >= 1)
            self.assertTrue(row['label'])
            for action in row['actions']:
                self.assertTrue(
                    set(action) <= ACTION_BASE_KEYS | ACTION_OPTIONAL_KEYS)
                self.assertTrue(ACTION_BASE_KEYS <= set(action))
                self.assertIn(action['key'], ('solution', 'problem'))
                self.assertEqual(
                    action['res_model'], 'printflow.product.flow')
                self.assertEqual(action['res_id'], wizard.id)

    def _assert_tray_rows(self, node):
        for row in node['tray']:
            self.assertEqual(set(row), TRAY_ROW_KEYS)
            self.assertIn(
                row['res_model'], ('product.product', 'mrp.bom',
                                   'mrp.production', 'purchase.order',
                                   'stock.picking'))

    def _assert_payload_contract(self, payload, wizard, flow_type):
        """Congela el ESQUEMA del payload (claves, vocabulario, geometría)."""
        self.assertEqual(set(payload), TOP_LEVEL_KEYS)
        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        self.assertEqual(payload['flow_type'], flow_type)
        axis = AXIS_MANUFACTURE if flow_type == 'manufacture' else AXIS_PURCHASE
        self.assertEqual(payload['axis'], axis)

        # global
        self.assertEqual(
            set(payload['global']),
            {'severity', 'root', 'chain_summary'})
        self.assertIn(payload['global']['severity'], (None, 'ok', 'warning',
                                                      'danger'))

        # layout
        self.assertEqual(set(payload['layout']), {'grid', 'cell'})
        self.assertEqual(payload['layout']['cell'], LAYOUT_CELL)
        grid = payload['layout']['grid']
        self.assertEqual(set(grid), {'cols', 'rows'})
        self.assertGreaterEqual(grid['cols'] * grid['rows'], len(axis))

        # nodos
        self.assertEqual(
            [node['key'] for node in payload['nodes']], axis)
        self.assertEqual(
            [node['seq'] for node in payload['nodes']],
            list(range(1, len(axis) + 1)))
        # El ``tray`` va SOLO en el hito que representa el slot de la raíz.
        root_slot = ROOT_CAUSE_TO_SLOT.get(payload['global']['root'])
        expected_root_key = next(
            (key for key in axis if NODE_META[key]['chain'] == root_slot), None)
        for node in payload['nodes']:
            meta = NODE_META[node['key']]
            expected_keys = set(BASE_NODE_KEYS)
            if node['key'] == expected_root_key:
                expected_keys |= ROOT_ONLY_NODE_KEYS
            if node['role'] == 'consequence':
                expected_keys |= CONSEQUENCE_ONLY_NODE_KEYS
            self.assertEqual(
                set(node), expected_keys,
                'Esquema de nodo %r cambiado' % node['key'])
            self.assertEqual(node['label'], meta['label'])
            self.assertEqual(node['kind'], meta['kind'])
            self.assertEqual(node['shape'], meta['shape'])
            self.assertEqual(node['owner'], meta['owner'])
            self.assertEqual(node['chain'], meta['chain'])
            self.assertIn(node['role'], ('none', 'root', 'consequence',
                                         'independent'))
            self.assertIn(node['tone'], ('ok', 'warn', 'danger', 'na'))
            self.assertIsInstance(node['anomaly'], bool)
            self.assertIsInstance(node['actions'], list)
            self.assertIsInstance(node['panel'], list)
            self.assertIsInstance(node['summary'], str)
            self.assertEqual(node['summary_more'], max(0, node['issues'] - 1))
            self.assertEqual(node['extra_count'], 0)
            self.assertEqual(node['info'], 0)
            self.assertEqual(node['issues'], len(node['panel']))
            self._assert_node_explain(node)
            if 'root_link' in node:
                self.assertEqual(
                    set(node['root_link']), {'label', 'target_key'})
            self._assert_node_actions(wizard, node)
            self._assert_panel_rows(wizard, node)
            if 'tray' in node:
                self._assert_tray_rows(node)

        # El ``tray`` aparece en EXACTAMENTE un nodo: el raíz del canvas.
        tray_nodes = [
            node['key'] for node in payload['nodes'] if 'tray' in node]
        self.assertEqual(
            tray_nodes, [expected_root_key] if expected_root_key else [])

        # aristas
        for edge in payload['edges']:
            self.assertEqual(set(edge), EDGE_KEYS)
            self.assertIn(edge['type'], ('flow', 'error'))
        for index in range(len(axis) - 1):
            src, dst = axis[index], axis[index + 1]
            flow_edges = [
                e for e in payload['edges']
                if e['id'] == 'flow-%s-%s' % (src, dst)]
            self.assertEqual(len(flow_edges), 1)
            edge = flow_edges[0]
            self.assertEqual((edge['from'], edge['to']), (src, dst))
            self.assertEqual(edge['type'], 'flow')
            self.assertEqual(edge['label'], '')
            self.assertFalse(edge['chain'])
            self.assertEqual(edge['style'], 'solid')

    # ==================================================================
    # 1) PARIDAD: lo serializado == la fábrica (deep-equal)
    # ==================================================================
    def test_purchasable_payload_matches_factory(self):
        wizard = self._wizard(
            self._deficit_purchasable('PAYLOAD PARIDAD COMPRA'))
        self.assertEqual(self._payload(wizard), self._factory(wizard))
        # Además, el texto serializado es EXACTAMENTE el de la fábrica.
        self.assertEqual(
            wizard.timeline_json, json.dumps(self._factory(wizard)))

    def test_manufacturable_payload_matches_factory(self):
        wizard = self._wizard(
            self._manufacturable('PAYLOAD PARIDAD FAB'))
        self.assertEqual(self._payload(wizard), self._factory(wizard))

    def test_healthy_payload_matches_factory(self):
        wizard = self._wizard(
            self._purchasable('PAYLOAD PARIDAD SANO'))
        self.assertEqual(self._payload(wizard), self._factory(wizard))

    # ==================================================================
    # 2) DETERMINISMO: la fábrica es pura (permite congelar el fixture)
    # ==================================================================
    def test_factory_is_deterministic(self):
        wizard = self._wizard(
            self._deficit_purchasable('PAYLOAD DETERMINISMO'))
        self.assertEqual(self._factory(wizard), self._factory(wizard))

    # ==================================================================
    # 3) FIXTURE CONGELADO del esqueleto (escenario compra con déficit)
    # ==================================================================
    def test_purchase_deficit_skeleton_is_frozen(self):
        wizard = self._wizard(
            self._deficit_purchasable('PAYLOAD ESQUELETO COMPRA'))
        payload = self._factory(wizard)
        skeleton = [
            {field: node[field] for field in _SKELETON_FIELDS}
            for node in payload['nodes']
        ]
        self.assertEqual(skeleton, FROZEN_SKELETON_PURCHASE_DEFICIT)
        # Raíz e invariantes de la cadena (raíz Compras -> consecuencia Stock).
        self.assertEqual(payload['global']['root'], 'purchase')
        self.assertEqual(payload['global']['severity'], 'danger')
        by_key = {node['key']: node for node in payload['nodes']}
        self.assertEqual(by_key['purchase']['role'], 'root')
        self.assertEqual(by_key['stock']['role'], 'consequence')
        self.assertEqual(by_key['stock']['parent'], 'purchase')
        self.assertEqual(
            by_key['stock']['root_link']['target_key'], 'purchase')
        # Arista de error raíz -> consecuencia.
        error_pairs = {
            (e['from'], e['to'])
            for e in payload['edges'] if e['type'] == 'error'}
        self.assertEqual(error_pairs, {('purchase', 'stock')})
        # Déficit físico: Compras ofrece su acción de solución/compra.
        purchase_keys = {a['key'] for a in by_key['purchase']['actions']}
        self.assertTrue(
            {'open_list', 'buy_product', 'buy_components', 'view_purchase',
             'open_product', 'collect', 'inventory_health'} <= purchase_keys)

    # ==================================================================
    # 4) CONTRATO ESTRUCTURAL en los 3 escenarios representativos
    # ==================================================================
    def test_purchase_deficit_contract(self):
        wizard = self._wizard(
            self._deficit_purchasable('PAYLOAD CONTRATO COMPRA'))
        self._assert_payload_contract(
            self._factory(wizard), wizard, 'purchase')
        by_key = {n['key']: n for n in self._factory(wizard)['nodes']}
        # Compras (raíz): tray + panel; Inventario: root_link + panel.
        self.assertIn('tray', by_key['purchase'])
        self.assertTrue(by_key['purchase']['panel'])
        self.assertIn('root_link', by_key['stock'])
        self.assertTrue(by_key['stock']['panel'])
        # Sin documentos pendientes del producto nuevo.
        for node in self._factory(wizard)['nodes']:
            self.assertEqual(node['pending'], 0)
            self.assertIsNone(node['pending_action'])

    def test_manufacture_contract(self):
        wizard = self._wizard(
            self._manufacturable('PAYLOAD CONTRATO FAB'))
        payload = self._factory(wizard)
        self._assert_payload_contract(payload, wizard, 'manufacture')
        self.assertEqual(wizard.flow_type, 'manufacture')

    def test_healthy_contract(self):
        wizard = self._wizard(
            self._purchasable('PAYLOAD CONTRATO SANO'))
        payload = self._factory(wizard)
        self._assert_payload_contract(payload, wizard, 'purchase')
        # Sin falla: sin raíz, sin roles, sin panel/tray, solo flujo.
        self.assertIsNone(payload['global']['root'])
        for node in payload['nodes']:
            self.assertEqual(node['role'], 'none')
            self.assertFalse(node['panel'])
            self.assertNotIn('tray', node)
            self.assertNotIn('root_link', node)
        self.assertTrue(
            all(edge['type'] == 'flow' for edge in payload['edges']))
