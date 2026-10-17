# -*- coding: utf-8 -*-
"""Contrato del payload JSON del diagrama de línea de tiempo (PrintFlow).

El widget OWL ``printflow_order_timeline`` consume ``focus_timeline_json`` del
wizard de diagnóstico. Estos tests custodian el CONTRATO del payload:

  * ``order`` sigue el orden CAUSAL del motor (``PF_CHAIN_ORDER``);
  * los roles de la cadena (raíz / consecuencia / independiente) y el padre de
    la consecuencia son correctos;
  * la info informativa de entrega se expone en su nodo;
  * sin foco el payload es SEGURO (5 nodos, sin estados ni roles);
  * las plantillas OWL usan expresiones JAVASCRIPT (no Python).

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import glob
import json
import os
import re

from lxml import etree

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_LABELS, PF_CHAIN_ORDER

# Palabras de PYTHON prohibidas dentro de expresiones QWeb de OWL (JS).
# OWL 2 (Odoo 17) compila `t-*` como JavaScript: `not/and/or` deben ser
# `!/&&/||`, y `True/False/None` deben ser `true/false/null|undefined`.
_PYTHON_EXPRESSION_TOKENS = re.compile(r'\b(not|and|or|True|False|None)\b')


@tagged('post_install', '-at_install')
class TestDiagnosticTimelinePayload(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Timeline Payload',
        })
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Cliente Timeline Payload Otro',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Timeline Payload',
            'supplier_rank': 1,
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests de diagnóstico)
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

    def _force_order(self, lines, partner=None):
        """Pedido forzado a 'sale' (sin procurement) + su tarjeta de tablero."""
        so = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        return so, board

    def _wizard(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})

    def _payload(self, wizard):
        return json.loads(wizard.focus_timeline_json)

    def _focus(self, wizard, product):
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line, 'El wizard debe tener la línea del producto.')
        wizard.write({'focus_line_id': line.id})
        return line

    def _deliver(self, so):
        """Valida por completo el albarán del pedido (lo deja ``done``)."""
        picking = so.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking, 'La confirmación debe generar el albarán.')
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.button_validate()
        if (isinstance(result, dict)
                and result.get('res_model') == 'stock.backorder.confirmation'):
            confirmation = self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({})
            confirmation.process()
        return picking

    # ------------------------------------------------------------------
    # 1) Orden causal de los nodos
    # ------------------------------------------------------------------
    def test_payload_order_follows_chain(self):
        product = self._product('TIMELINE ORDEN (PAYLOAD)')
        _so, board = self._force_order([(product, 1.0)])
        wizard = self._wizard(board)
        self._focus(wizard, product)

        payload = self._payload(wizard)

        # La espina CAUSAL sigue intacta en `order`; los NODOS son el recorrido
        # FÍSICO SECUENCIAL (`axis`), no los 5 nodos causales.
        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        self.assertEqual(payload['flow_type'], 'purchase')
        self.assertEqual(payload['axis'][-1], 'customer')
        self.assertEqual(
            [node['key'] for node in payload['nodes']], payload['axis'])
        # `seq` es el PASO del recorrido físico (1..N); la venta no está.
        self.assertEqual(
            [node['seq'] for node in payload['nodes']],
            list(range(1, len(payload['axis']) + 1)))
        self.assertNotIn('sale', payload['axis'])
        labels = {node['key']: node['label'] for node in payload['nodes']}
        self.assertEqual(labels['purchase'], PF_CHAIN_LABELS['purchase'])

    # ------------------------------------------------------------------
    # 2) Raíz y padre de la consecuencia (Compras -> Inventario)
    # ------------------------------------------------------------------
    def test_payload_root_and_consequence_parent(self):
        product = self._product(
            'TIMELINE COMPRA RAIZ (PAYLOAD)', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 4.0)])
        wizard = self._wizard(board)
        self._focus(wizard, product)

        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}

        self.assertEqual(by_key['purchase']['role'], 'root')
        self.assertIsNone(by_key['purchase']['parent'])
        self.assertEqual(by_key['stock']['role'], 'consequence')
        self.assertEqual(by_key['stock']['parent'], 'purchase')
        self.assertEqual(payload['global']['root'], 'purchase')
        # La consecuencia enlaza a la raíz (no ofrece solución).
        self.assertEqual(by_key['stock']['root_link']['target_key'], 'purchase')
        self.assertNotIn(
            'solution', [a['key'] for a in by_key['stock']['actions']])

    # ------------------------------------------------------------------
    # 3) Nodo INDEPENDIENTE (traba aguas arriba de la raíz)
    # ------------------------------------------------------------------
    def test_payload_independent_node(self):
        """Raíz Inventario (contención sobre el TERMINADO) + Fabricación trabada
        aguas arriba: Fabricación queda INDEPENDIENTE (traba paralela) y la raíz
        es el ALMACÉN TERMINADO (no el de insumos, que está sano)."""
        component = self._product('TIMELINE INDEP COMPONENTE (PAYLOAD)')
        self._add_stock(component, 100.0)
        finished = self._product('TIMELINE INDEP FABRICADO (PAYLOAD)')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 1.0,
            })],
        })
        self._add_stock(finished, 5.0)
        # Otro pedido reserva TODO el terminado -> contención (stock 'over').
        other = self.env['sale.order'].create({
            'partner_id': self.other_customer.id,
            'order_line': [(0, 0, {
                'product_id': finished.id,
                'product_uom_qty': 5.0,
                'product_uom': finished.uom_id.id,
            })],
        })
        other.action_confirm()

        _so, board = self._force_order([(finished, 3.0)])
        board.write({'production_alert': 'no_order'})
        wizard = self._wizard(board)
        self._focus(wizard, finished)

        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}

        # La contención del TERMINADO manda como raíz; Fabricación, aguas arriba,
        # es una traba PARALELA: independiente y sin padre. El ALMACÉN INSUMOS
        # (que está sano) NO recibe el problema del terminado.
        self.assertEqual(by_key['stock_finished']['role'], 'root')
        self.assertEqual(by_key['stock_supply']['role'], 'none')
        self.assertEqual(by_key['production']['role'], 'independent')
        self.assertIsNone(by_key['production']['parent'])
        # Nunca una flecha hacia atrás: no hay arista de error que apunte de la
        # raíz (terminado) hacia un hito aguas arriba (fabricación).
        error_pairs = {
            (e['from'], e['to'])
            for e in payload['edges'] if e['type'] == 'error'}
        self.assertNotIn(('stock_finished', 'production'), error_pairs)
        self.assertNotIn(('stock_finished', 'stock_supply'), error_pairs)

    # ------------------------------------------------------------------
    # 4) Info informativa de entrega
    # ------------------------------------------------------------------
    def test_payload_delivery_info(self):
        product = self._product('TIMELINE ENTREGA (PAYLOAD)')
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._add_stock(product, 1.0)

        # Pedido PROPIO ya entregado: su albarán NO se cuenta.
        own_so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        own_so.action_confirm()
        self._deliver(own_so)
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})

        # Tres pedidos AJENOS con albarán pendiente del mismo producto.
        other_pickings = self.env['stock.picking']
        for _i in range(3):
            other_so = self.env['sale.order'].create({
                'partner_id': self.other_customer.id,
                'order_line': [(0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': 1.0,
                    'product_uom': product.uom_id.id,
                })],
            })
            other_so.action_confirm()
            other_pickings |= other_so.picking_ids

        wizard = self._wizard(board)
        self._focus(wizard, product)
        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}

        self.assertEqual(by_key['delivery']['info'], len(other_pickings))

    # ------------------------------------------------------------------
    # 4b) Fase 3: aviso de PENDIENTES por nodo + acción de navegación
    # ------------------------------------------------------------------
    def test_payload_node_pending_badge_and_action(self):
        """Cada nodo expone ``pending`` + ``pending_action`` accionable.

        Con foco y entregas AJENAS pendientes, el nodo Entrega:
          * ``pending`` == ``info`` (MISMA fuente: entregas ajenas pendientes);
          * ``pending_action`` apunta al dispatcher PÚBLICO
            ``action_open_node_pending`` del wizard (nunca un ``_pf_*``).
        """
        product = self._product('TIMELINE PENDING NODO (PAYLOAD)')
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._add_stock(product, 1.0)

        # Pedido PROPIO ya entregado (no se cuenta).
        own_so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        own_so.action_confirm()
        self._deliver(own_so)
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})

        # Dos pedidos AJENOS con albarán de entrega pendiente.
        for _i in range(2):
            other_so = self.env['sale.order'].create({
                'partner_id': self.other_customer.id,
                'order_line': [(0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': 1.0,
                    'product_uom': product.uom_id.id,
                })],
            })
            other_so.action_confirm()

        wizard = self._wizard(board)
        self._focus(wizard, product)
        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}
        delivery = by_key['delivery']

        self.assertGreater(delivery['pending'], 0)
        self.assertEqual(delivery['pending'], delivery['info'])
        action = delivery['pending_action']
        self.assertIsNotNone(action)
        self.assertEqual(action['method'], 'action_open_node_pending')
        self.assertFalse(action['method'].startswith('_pf'))
        self.assertEqual(
            action['res_model'], 'printflow.order.diagnostic.wizard')
        self.assertEqual(action['res_id'], wizard.id)
        self.assertEqual(action['args'], ['delivery'])
        self.assertEqual(action['kind'], 'navigate')
        self.assertTrue(action['enabled'])

        # El dispatcher PÚBLICO devuelve una ventana navegable (no escribe).
        opened = wizard.action_open_node_pending('delivery')
        self.assertEqual(opened['type'], 'ir.actions.act_window')
        self.assertEqual(opened['res_model'], 'stock.picking')

        # Fase 3.3: en el POPOVER, `delivery` NO duplica: conserva su acción
        # `pending_deliveries` y NO recibe la `pending` genérica.
        delivery_keys = [a['key'] for a in delivery['actions']]
        self.assertIn('pending_deliveries', delivery_keys)
        self.assertNotIn('pending', delivery_keys)

    # ------------------------------------------------------------------
    # 4c) Fase 3.1: el dispatcher devuelve un `act_window` por TIPO de nodo
    # ------------------------------------------------------------------
    def test_action_open_node_pending_returns_window_per_node(self):
        """`action_open_node_pending` navega bien para CADA tipo de hito.

        Los nodos de stock delegan en la bandeja de Salud de Inventario; el
        resto abre listas nativas. Todo es navegación (no escribe).
        """
        product = self._product('TIMELINE DISPATCHER NODO (PAYLOAD)')
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 1.0)])
        wizard = self._wizard(board)
        self._focus(wizard, product)

        expected = {
            'purchase': 'purchase.order',
            'receipt': 'stock.picking',
            'production': 'mrp.production',
            'delivery': 'stock.picking',
            'stock': 'printflow.inventory.health',
            'stock_supply': 'printflow.inventory.health',
            'stock_finished': 'printflow.inventory.health',
        }
        for node_key, res_model in expected.items():
            action = wizard.action_open_node_pending(node_key)
            self.assertEqual(
                action.get('type'), 'ir.actions.act_window',
                'El nodo %r debe devolver un act_window.' % node_key)
            self.assertEqual(
                action.get('res_model'), res_model,
                'El nodo %r debe abrir %r.' % (node_key, res_model))

        # Sin foco o sin clave: cierre seguro (no navega).
        wizard.write({'focus_line_id': False})
        self.assertEqual(
            wizard.action_open_node_pending('delivery').get('type'),
            'ir.actions.act_window_close')

    # ------------------------------------------------------------------
    # 4d) Fase 3.3: el aviso de la TARJETA es un badge informativo
    # ------------------------------------------------------------------
    def test_timeline_pending_notice_is_informational_badge(self):
        """La tarjeta muestra el conteo como BADGE informativo (sin acción).

        La ACCIÓN de ver pendientes vive en el POPOVER (ver 4f). Aquí se blinda
        que la tarjeta NO vuelva a cablear un botón clicable de pendientes.
        """
        module_path = get_module_path('printflow_gestion_inventario')
        template_path = os.path.join(
            module_path, 'static', 'src', 'xml', 'printflow_order_timeline.xml')
        tree = etree.parse(template_path)

        # Ya NO hay botón de pendientes en la tarjeta.
        self.assertFalse(
            [el for el in tree.iter('button')
             if 'o_pf_node_pending_btn' in (el.get('class') or '')],
            'La tarjeta ya no debe tener botón de pendientes.')

        # Sí hay un badge informativo que muestra `shape.pending`, sin clic.
        badges = [
            el for el in tree.iter('span')
            if 'text-bg-info' in (el.get('class') or '')
            and any(c.get('t-esc') == 'shape.pending' for c in el.iter())
        ]
        self.assertTrue(
            badges, 'La tarjeta debe mostrar el conteo en un badge info.')
        for badge in badges:
            self.assertIsNone(badge.get('t-on-click'))

    # ------------------------------------------------------------------
    # 4e) Fase 3.3: el tooltip NO intercepta clics (fix conservado)
    # ------------------------------------------------------------------
    def test_tooltip_does_not_intercept_clicks(self):
        """El tooltip que cubre la tarjeta al hover es puramente visual.

        Conserva el fix de la Fase 3.1: si no fuera ``pointer-events: none``
        robaría los clics de la tarjeta (que abre el popover del nodo).
        """
        module_path = get_module_path('printflow_gestion_inventario')
        scss_path = os.path.join(
            module_path, 'static', 'src', 'scss', 'printflow_diagnostic.scss')
        with open(scss_path, encoding='utf-8') as handle:
            scss = handle.read()

        tip_blocks = re.findall(r'\.o_pf_node_tip\s*\{([^}]*)\}', scss)
        self.assertTrue(tip_blocks, 'Debe existir la regla .o_pf_node_tip.')
        self.assertTrue(
            any('pointer-events: none' in body for body in tip_blocks),
            'El tooltip .o_pf_node_tip debe ser puramente visual '
            '(pointer-events: none).')
        self.assertFalse(
            any('pointer-events: auto' in body for body in tip_blocks),
            'Ningún .o_pf_node_tip debe reactivar pointer-events.')

    # ------------------------------------------------------------------
    # 4f) Fase 3.3: el POPOVER ofrece "Ver pendientes (N)" (método público)
    # ------------------------------------------------------------------
    def test_popover_offers_pending_action(self):
        """Con pendientes, el nodo agrega la acción `pending` al popover.

        Se usa un nodo de COMPRA: un pedido de compra en borrador del producto
        deja 1 pendiente en `purchase`. La acción NAVEGA (no escribe) con método
        PÚBLICO y sin exponer `_pf_*`.
        """
        product = self._product('TIMELINE POPOVER PENDING (PAYLOAD)')
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 1.0)])

        # Pedido de COMPRA en borrador del producto -> 1 pendiente de compra.
        self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })

        wizard = self._wizard(board)
        self._focus(wizard, product)
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        purchase = by_key['purchase']

        action = next(
            (a for a in purchase['actions'] if a['key'] == 'pending'), None)
        self.assertIsNotNone(
            action, 'El popover debe ofrecer la acción `pending`.')
        self.assertEqual(action['method'], 'action_open_node_pending')
        self.assertFalse(action['method'].startswith('_'))
        self.assertEqual(action['kind'], 'navigate')
        self.assertEqual(
            action['res_model'], 'printflow.order.diagnostic.wizard')
        self.assertEqual(action['res_id'], wizard.id)
        self.assertEqual(action['args'], ['purchase'])
        self.assertTrue(action['enabled'])
        self.assertIn('1', action['label'])

    # ------------------------------------------------------------------
    # 5) Payload seguro SIN foco
    # ------------------------------------------------------------------
    def test_payload_without_focus_is_safe(self):
        product = self._product('TIMELINE SIN FOCO (PAYLOAD)')
        _so, board = self._force_order([(product, 1.0)])
        wizard = self._wizard(board)
        self.assertFalse(wizard.focus_line_id)

        payload = self._payload(wizard)

        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        # Sin foco: recorrido de compra por defecto, sin estados ni acciones.
        self.assertEqual(payload['axis'][-1], 'customer')
        self.assertNotIn('sale', payload['axis'])
        for node in payload['nodes']:
            self.assertIsNone(node['status'])
            self.assertEqual(node['role'], 'none')
            self.assertIsNone(node['parent'])
            self.assertEqual(node['issues'], 0)
            self.assertEqual(node['info'], 0)
            self.assertEqual(node['summary'], '')
            self.assertEqual(node['summary_more'], 0)
            self.assertEqual(node['actions'], [])
            # F1: `anomaly` está SIEMPRE presente; sin foco es False.
            self.assertFalse(node['anomaly'])
            # Fase 3: sin foco el aviso de pendientes es SEGURO (0 y sin acción).
            self.assertEqual(node['pending'], 0)
            self.assertIsNone(node['pending_action'])

    # ------------------------------------------------------------------
    # 5b) Resumen corto del nodo (summary / summary_more) en el payload
    # ------------------------------------------------------------------
    def test_payload_nodes_carry_short_summary(self):
        """Cada nodo expone ``summary`` (texto corto) y ``summary_more`` (extra).

        El nodo roto lleva el resumen de su falla ANFITRIONA (misma fuente que
        el ``detail`` del panel); el nodo sano no inventa texto.
        """
        product = self._product(
            'TIMELINE RESUMEN (PAYLOAD)', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 4.0)])
        wizard = self._wizard(board)
        line = self._focus(wizard, product)

        payload = self._payload(wizard)
        by_key = {node['key']: node for node in payload['nodes']}

        purchase = by_key['purchase']
        self.assertEqual(purchase['role'], 'root')
        self.assertTrue(purchase['summary'])
        purchase_failure = line.failure_ids.filtered(
            lambda f: f.node == 'purchase')[:1]
        self.assertEqual(purchase['summary'], purchase_failure.summary)
        self.assertEqual(
            purchase['summary_more'], max(0, purchase['issues'] - 1))

        # El terminal sano no arrastra resumen.
        self.assertEqual(by_key['customer']['summary'], '')
        self.assertEqual(by_key['customer']['summary_more'], 0)

    # ------------------------------------------------------------------
    # 5c) Capa de EXPLICACIÓN: cada nodo trae la explicación de 5 claves
    # ------------------------------------------------------------------
    def test_payload_nodes_carry_explain(self):
        """Todo nodo del payload (pedido) trae ``explain`` con las 5 claves."""
        product = self._product(
            'TIMELINE EXPLAIN (PAYLOAD)', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 4.0)])
        wizard = self._wizard(board)
        self._focus(wizard, product)

        nodes = self._payload(wizard)['nodes']
        self.assertTrue(nodes, 'El payload debe traer nodos.')
        for node in nodes:
            explain = node['explain']
            self.assertEqual(
                set(explain),
                {'headline', 'what', 'why', 'how', 'severity'},
                'Nodo %r sin contrato de explain.' % node['key'])
            self.assertIn(
                explain['severity'], ('ok', 'info', 'warn', 'danger'))
            self.assertIsInstance(explain['why'], list)
            self.assertIsInstance(explain['how'], list)

    # ------------------------------------------------------------------
    # 6) La vista cablea el widget
    # ------------------------------------------------------------------
    def test_timeline_view_wires_widget(self):
        view = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form')
        self.assertIn('printflow_order_timeline', view.arch_db or '')
        self.assertIn('focus_timeline_json', view.arch_db or '')

    # ------------------------------------------------------------------
    # 7) Las plantillas OWL usan expresiones JavaScript (no Python)
    # ------------------------------------------------------------------
    def test_timeline_template_uses_js_expressions(self):
        """Guarda contra el error de runtime `missing ) after argument list`.

        OWL 2 (Odoo 17) compila los atributos ``t-*`` como JAVASCRIPT: un ``not``
        (Python) genera ``ctx['not']ctx[...]`` y revienta la compilación en el
        navegador. Este test recorre TODAS las plantillas OWL del módulo y falla
        si algún atributo ``t-*`` trae operadores/valores de Python.
        """
        module_path = get_module_path('printflow_gestion_inventario')
        # Odoo 17 exige que TODO asset viva bajo <módulo>/static/ (ir_asset._get_paths),
        # así que las plantillas OWL del módulo —incluidas las del timeline del
        # diagnóstico— están todas en static/src/xml de la raíz.
        xml_dirs = [
            os.path.join(module_path, 'static', 'src', 'xml'),
        ]
        templates = []
        for xml_dir in xml_dirs:
            templates.extend(glob.glob(os.path.join(xml_dir, '*.xml')))
        self.assertTrue(
            templates, 'Deben existir plantillas OWL en static/src/xml.')

        offenders = []
        for path in templates:
            tree = etree.parse(path)
            for element in tree.iter():
                for name, value in element.attrib.items():
                    if not name.startswith('t-'):
                        continue
                    found = _PYTHON_EXPRESSION_TOKENS.search(value)
                    if found:
                        offenders.append(
                            '%s :: %s="%s" (token Python: %s)' % (
                                os.path.basename(path), name, value,
                                found.group(1)))
        self.assertFalse(
            offenders,
            'Plantillas OWL con sintaxis Python (debe ser JavaScript):\n'
            + '\n'.join(offenders))
