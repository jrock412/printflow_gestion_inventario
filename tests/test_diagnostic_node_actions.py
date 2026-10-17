# -*- coding: utf-8 -*-
"""Acciones DIRECTAS del popover por nodo del centro de operaciones.

El widget OWL ``printflow_order_timeline`` es una VITRINA: el servidor arma la
lista ``actions`` de cada nodo del canvas a partir del playbook/remedios ya
calculados por la falla y de los métodos EXISTENTES del tablero/falla.

Estos tests custodian el contrato de esa lista:

  * el nodo raíz trae acciones directas (problema, solución, y los atajos de
    compra del tablero) con ``method``/``res_model`` utilizables;
  * el nodo CONSECUENCIA NO expone "solución" ni NINGUNA acción ``run_action``:
    solo informa y enlaza a la raíz;
  * ``open_area`` quedó ELIMINADO;
  * sin foco, ``actions == []`` en todos los nodos;
  * la tabla de fallas se ELIMINÓ del formulario: cada falla vive en el PANEL
    de su nodo (con sus acciones por fila) y el total de fallas del subárbol
    se reparte sin pérdida (``∑ fallas_en_paneles == flow_failure_ids``).

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_ORDER


@tagged('post_install', '-at_install')
class TestDiagnosticNodeActions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Acciones Nodo',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Acciones Nodo',
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

    def _force_order(self, lines, partner=None):
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

    def _purchase_root_wizard(self):
        """Comprable sin stock ni PO -> Compra raíz, Inventario consecuencia."""
        product = self._product(
            'ACCIONES COMPRA RAIZ', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_order([(product, 4.0)])
        wizard = self._wizard(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})
        return wizard

    @staticmethod
    def _action(node, key):
        return next(
            (action for action in node['actions'] if action['key'] == key),
            None)

    # ------------------------------------------------------------------
    # 1) Nodo raíz roto: acciones directas
    # ------------------------------------------------------------------
    def test_actions_present_for_broken_root(self):
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        purchase = by_key['purchase']

        self.assertEqual(purchase['role'], 'root')
        keys = [action['key'] for action in purchase['actions']]
        self.assertIn('problem', keys)
        self.assertIn('solution', keys)
        # Atajos de resolución mudados desde el kanban.
        self.assertIn('quick_purchase', keys)
        self.assertIn('quick_purchase_component', keys)
        # `open_area` quedó ELIMINADO (Nivel 3 fusionado en el panel).
        self.assertNotIn('open_area', keys)

        quick = self._action(purchase, 'quick_purchase')
        self.assertIsNotNone(quick)
        self.assertEqual(quick['res_model'], 'printflow.order.board')
        self.assertEqual(quick['method'], 'action_open_quick_purchase')

        solution = self._action(purchase, 'solution')
        self.assertIsNotNone(solution)
        self.assertTrue(solution['enabled'])
        self.assertIsNotNone(solution['failure_id'])

    def test_solution_is_primary_and_first(self):
        """La acción resolutiva va PRIMERA y marcada como HERO (``primary``)."""
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        purchase = by_key['purchase']
        keys = [action['key'] for action in purchase['actions']]
        self.assertEqual(keys[0], 'solution', 'La solución debe ir PRIMERO.')
        solution = self._action(purchase, 'solution')
        self.assertTrue(solution.get('primary'))
        # El nombre específico del remedio viaja como subtítulo atenuado.
        self.assertTrue(solution.get('sublabel'))
        self.assertEqual(solution['label'], 'Solucionar')

    def test_consequence_has_no_primary_action(self):
        """En una CONSECUENCIA ninguna acción es HERO (solo informa)."""
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        stock = by_key['stock']
        self.assertEqual(stock['role'], 'consequence')
        for action in stock['actions']:
            self.assertFalse(action.get('primary'))

    def test_panel_solution_is_primary(self):
        """La solución POR FILA del panel también es HERO y va primero."""
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        row = by_key['purchase']['panel'][0]
        keys = [action['key'] for action in row['actions']]
        self.assertEqual(keys[0], 'solution')
        solution = next(
            action for action in row['actions'] if action['key'] == 'solution')
        self.assertTrue(solution.get('primary'))
        self.assertEqual(solution['label'], 'Solucionar')
        self.assertTrue(solution.get('sublabel'))

    # ------------------------------------------------------------------
    # 2) Nodo CONSECUENCIA: sin solución ni acciones con efecto
    # ------------------------------------------------------------------
    def test_consequence_only_informs(self):
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        stock = by_key['stock']

        self.assertEqual(stock['role'], 'consequence')
        keys = [action['key'] for action in stock['actions']]
        self.assertNotIn('solution', keys)
        self.assertNotIn('open_area', keys)
        for action in stock['actions']:
            self.assertNotEqual(
                action['kind'], 'run_action',
                'Las consecuencias no exponen acciones con efecto.')
        # En su lugar, la consecuencia enlaza a la raíz.
        self.assertIsNotNone(stock['root_link'])
        self.assertEqual(stock['root_link']['target_key'], 'purchase')

    # ------------------------------------------------------------------
    # 3) run_action solo en nodos NO consecuencia (los del tablero)
    # ------------------------------------------------------------------
    def test_run_action_only_outside_consequence(self):
        wizard = self._purchase_root_wizard()
        payload = self._payload(wizard)
        for node in payload['nodes']:
            for action in node['actions']:
                if action['kind'] == 'run_action':
                    self.assertNotEqual(
                        node['role'], 'consequence',
                        'run_action no debe ofrecerse en una consecuencia.')

    # ------------------------------------------------------------------
    # 3b) F1: nodo de stock ANÓMALO -> "Sanear reservas colgadas"
    # ------------------------------------------------------------------
    def test_stock_anomaly_exposes_cleanup_action(self):
        """Con anomalía y sin ser consecuencia, el nodo de stock ofrece el saneo."""
        wizard = self._purchase_root_wizard()
        actions = wizard._pf_node_actions(
            'stock', None, 'none', 'deficit', False, None, True)
        keys = [action['key'] for action in actions]
        self.assertIn('cleanup_reservations', keys)
        cleanup = next(
            action for action in actions
            if action['key'] == 'cleanup_reservations')
        self.assertEqual(cleanup['kind'], 'run_action')
        self.assertEqual(cleanup['method'], 'action_cleanup_over_reservations')
        self.assertEqual(cleanup['res_model'], 'printflow.order.board')

    def test_stock_anomaly_action_blocked_on_consequence(self):
        """El guard de consecuencia bloquea el saneo aunque haya anomalía."""
        wizard = self._purchase_root_wizard()
        blocked = wizard._pf_node_actions(
            'stock', None, 'consequence', 'deficit', False, None, True)
        self.assertNotIn(
            'cleanup_reservations', [a['key'] for a in blocked])
        # Sin anomalía tampoco aparece (default).
        clean = wizard._pf_node_actions(
            'stock', None, 'none', 'deficit', False, None, False)
        self.assertNotIn(
            'cleanup_reservations', [a['key'] for a in clean])

    # ------------------------------------------------------------------
    # 4) Sin foco: acciones vacías y seguro
    # ------------------------------------------------------------------
    def test_actions_safe_without_focus(self):
        product = self._product('ACCIONES SIN FOCO')
        _so, board = self._force_order([(product, 1.0)])
        wizard = self._wizard(board)
        self.assertFalse(wizard.focus_line_id)

        payload = self._payload(wizard)

        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        for node in payload['nodes']:
            self.assertEqual(node['actions'], [])
            self.assertEqual(node['panel'], [])

    # ------------------------------------------------------------------
    # 5) Retrocompatibilidad: `order`/`global` siguen presentes
    # ------------------------------------------------------------------
    def test_payload_additive_backcompat(self):
        wizard = self._purchase_root_wizard()
        payload = self._payload(wizard)

        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        self.assertIn('global', payload)
        for key in ('severity', 'root', 'chain_summary'):
            self.assertIn(key, payload['global'])
        by_key = {n['key']: n for n in payload['nodes']}
        self.assertEqual(by_key['purchase']['status'], 'missing')
        self.assertEqual(by_key['purchase']['role'], 'root')
        self.assertEqual(payload['global']['root'], 'purchase')

    # ------------------------------------------------------------------
    # 6) La tabla de fallas se ELIMINÓ: sus acciones viven en el panel
    # ------------------------------------------------------------------
    def test_failure_table_removed_from_view(self):
        """El formulario ya NO tiene la tabla "Fallas del producto": sus
        botones y el detalle se movieron al panel del popover de cada nodo."""
        view = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form')
        arch = view.arch_db or ''
        self.assertNotIn('focus_flow_failure_ids', arch)
        self.assertNotIn('focus_node_failure_ids', arch)
        self.assertNotIn('action_open_node', arch)
        self.assertNotIn('action_back_to_timeline', arch)
        # Los botones de la tabla desaparecieron del formulario.
        self.assertNotIn('action_open_solution', arch)
        self.assertNotIn('action_apply_second_remedy', arch)

    def test_panel_rows_carry_row_actions(self):
        """Cada fila del panel trae sus acciones (problema / solución)."""
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        purchase = by_key['purchase']
        self.assertTrue(purchase['panel'])
        row = purchase['panel'][0]
        keys = [action['key'] for action in row['actions']]
        self.assertIn('problem', keys)
        self.assertIn('solution', keys)
        solution = next(
            action for action in row['actions'] if action['key'] == 'solution')
        self.assertTrue(solution['enabled'])
        self.assertIsNotNone(solution['failure_id'])

    def test_consequence_panel_rows_only_problem(self):
        """En una CONSECUENCIA el panel solo ofrece 'Ver el problema'."""
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        stock = by_key['stock']
        self.assertEqual(stock['role'], 'consequence')
        self.assertTrue(stock['panel'])
        for row in stock['panel']:
            keys = [action['key'] for action in row['actions']]
            self.assertNotIn('solution', keys)
            self.assertNotIn('second_remedy', keys)
            for key in keys:
                self.assertEqual(key, 'problem')

    # ------------------------------------------------------------------
    # 6b) CERO pérdida: cada falla del subárbol aparece en UN panel
    # ------------------------------------------------------------------
    def test_zero_loss_failures_in_panels(self):
        """∑ fallas en paneles == total de fallas del subárbol (cero pérdida).

        Reemplaza a la tabla eliminada: ninguna falla del subárbol (incluidas
        las de componentes/venta) se pierde al quitar la tabla.
        """
        wizard = self._purchase_root_wizard()
        line = wizard.focus_line_id
        payload = self._payload(wizard)
        total = len(line.flow_failure_ids)
        self.assertGreater(total, 0)
        in_panels = sum(len(node['panel']) for node in payload['nodes'])
        self.assertEqual(in_panels, total)

    def test_extra_chip_counts_component_failures(self):
        """El chip "+N de componentes/venta" cuenta fallas externas al slot."""
        component = self._product('CHIP COMPONENTE')
        finished = self._product('CHIP TERMINADO')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 2.0})],
        })
        self.env['stock.quant']._update_available_quantity(
            component, self.stock_location, 10.0)
        # Otro pedido reserva TODO el componente -> contención del insumo.
        other = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': component.id,
                'product_uom_qty': 10.0,
                'product_uom': component.uom_id.id,
            })],
        })
        other.action_confirm()
        self.env['stock.quant']._update_available_quantity(
            finished, self.stock_location, 3.0)
        _so, board = self._force_order([(finished, 3.0)])
        board.write({'production_alert': 'no_order'})
        wizard = self._wizard(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        wizard.write({'focus_line_id': line.id})

        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        # La contención del COMPONENTE cae en el almacén de insumos y se marca
        # como externa (chip). Fabricación solo tiene su falla propia.
        self.assertGreaterEqual(by_key['stock_supply']['extra_count'], 1)
        self.assertEqual(by_key['production']['extra_count'], 0)

    # ------------------------------------------------------------------
    # 7) El popover invoca el dispatcher PÚBLICO (no métodos privados)
    #
    # Odoo 17 rechaza los métodos privados (nombre con ``_``) por
    # ``/web/dataset/call_button``. Las acciones resolutivas del hito deben
    # viajar como el dispatcher público ``action_run_pf_node`` + la clave.
    # ------------------------------------------------------------------
    def test_failure_actions_use_public_dispatcher(self):
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        purchase = by_key['purchase']

        buy = self._action(purchase, 'buy_product')
        self.assertIsNotNone(buy)
        self.assertEqual(buy['method'], 'action_run_pf_node')
        self.assertFalse(
            buy['method'].startswith('_'),
            'El popover NO debe exponer un método privado por RPC.')
        self.assertEqual(buy['args'], ['buy_product'])

        # El dispatcher resuelve la clave al método `_pf_*` interno correcto.
        failure = self.env[
            'printflow.order.diagnostic.failure'].browse(buy['failure_id'])
        action = failure.action_run_pf_node('buy_product')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')

    def test_unknown_dispatch_key_is_safe(self):
        """Una clave fuera de la lista blanca no rompe: cierra la ventana."""
        wizard = self._purchase_root_wizard()
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        buy = self._action(by_key['purchase'], 'buy_product')
        failure = self.env[
            'printflow.order.diagnostic.failure'].browse(buy['failure_id'])
        self.assertEqual(
            failure.action_run_pf_node('does_not_exist')['type'],
            'ir.actions.act_window_close')

    def test_no_private_method_in_any_popover_action(self):
        wizard = self._purchase_root_wizard()
        for node in self._payload(wizard)['nodes']:
            for action in node['actions']:
                method = action.get('method')
                if method:
                    self.assertFalse(
                        method.startswith('_'),
                        'Método privado expuesto por RPC: %s' % method)
