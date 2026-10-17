# -*- coding: utf-8 -*-
"""Bandeja gestionable de INSUMOS del diagrama de PRODUCTO (PrintFlow).

Custodia el hito ALMACÉN DE INSUMOS (``stock_supply``):
  * el token CRUDO del motor (``over_reserved``) se traduce a idioma de operador
    y el nodo se pinta en ROJO (``danger``), sin repintar el tone (paridad del
    canvas: ``node.tone == _pf_node_tone(key, status)``);
  * la explicación (``explain``) ya NO imprime el token técnico;
  * el "Solucionar" ABRE la bandeja ``printflow.flow.supply.tray`` con una fila
    por insumo/almacén (evidencia);
  * las TRES vías (traslado/compra/ajuste) devuelven el ``ir.actions`` correcto;
  * la "Corrección automática" pasa por el guardia de permisos (jefe de taller);
  * no regresión: la bandeja de LOTE sigue abriendo.

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
import json

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowSupplyTray(TransactionCase):
    """El insumo reservado de más enciende el nodo y abre su bandeja."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Bandeja Insumos'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.supply.tray']
        cls.Presentation = cls.env['printflow.flow.presentation']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product', 'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _over_reserved_component(self, name, qty=1.0, reserved=5.0):
        """Insumo con libre AGREGADO negativo (reservado > existencia)."""
        component = self._product(name)
        self.env['stock.quant']._update_available_quantity(
            component, self.stock_location, qty, reserved_quantity=reserved)
        return component

    def _manufacturable_with(self, name, component):
        finished = self._product(name)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        return finished

    def _supply_product(self, name):
        """Terminado fabricable cuyo insumo está reservado de más."""
        component = self._over_reserved_component('%s INSUMO' % name)
        return self._manufacturable_with(name, component), component

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _payload(self, wizard):
        return json.loads(wizard.timeline_json)

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    def _outgoing_no_stock_lot(self, product, lot, qty=2.0):
        """Albarán de salida que reserva un lote SIN existencia."""
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        move = self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
        })
        move._action_confirm()
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'quantity': qty,
            'lot_id': lot.id,
        })
        return picking, move

    # ==================================================================
    # (a) Token traducido + semáforo ROJO
    # ==================================================================
    def test_over_reserved_token_is_human_and_danger(self):
        self.assertEqual(
            self.Presentation._pf_node_status_label(
                'stock_supply', 'over_reserved'),
            'Reservado de más')
        self.assertEqual(
            self.Presentation._pf_node_tone('stock_supply', 'over_reserved'),
            'danger')
        # Los otros tokens del snapshot también se traducen y pintan rojo.
        for token, label in (
                ('physical', 'No hay existencia'),
                ('contention', 'Apartado por otros pedidos'),
                ('no_route', 'Sin forma de reponer')):
            self.assertEqual(
                self.Presentation._pf_node_status_label('stock_supply', token),
                label)
            self.assertEqual(
                self.Presentation._pf_node_tone('stock_supply', token),
                'danger')

    def test_canvas_supply_node_is_danger_and_parity(self):
        finished, _component = self._supply_product('INSUMOS ROJO')
        payload = self._payload(self._wizard(finished))
        # Paridad: el tone de TODOS los nodos sale del status.
        for node in payload['nodes']:
            self.assertEqual(
                node['tone'],
                self.Presentation._pf_node_tone(node['key'], node['status']))
        by_key = {node['key']: node for node in payload['nodes']}
        supply = by_key['stock_supply']
        self.assertEqual(supply['status'], 'over_reserved')
        self.assertEqual(supply['tone'], 'danger')
        self.assertEqual(supply['status_label'], 'Reservado de más')

    # ==================================================================
    # (b) Explain humano (sin token crudo)
    # ==================================================================
    def test_explain_is_human(self):
        finished, _component = self._supply_product('INSUMOS EXPLAIN')
        payload = self._payload(self._wizard(finished))
        by_key = {node['key']: node for node in payload['nodes']}
        explain = by_key['stock_supply']['explain']
        blob = ' '.join(
            [explain['headline'], explain['what']] + explain['why']
            + explain['how'])
        self.assertNotIn('over_reserved', blob)
        self.assertIn('Reservado de más', explain['what'])

    # ==================================================================
    # (c) La bandeja lista el insumo/almacén con la evidencia
    # ==================================================================
    def test_tray_lists_component_evidence(self):
        finished, component = self._supply_product('INSUMOS BANDEJA')
        action = self._wizard(finished).action_run_pf_plan(
            'supply_issue', 'solution')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.supply.tray')
        self.assertEqual(action['target'], 'current')
        tray = self.Tray.search([('product_id', '=', finished.id)])
        self.assertTrue(tray, 'La bandeja debe traer al menos una fila.')
        self.assertEqual(set(tray.mapped('component_id')), {component})
        row = tray[:1]
        self.assertEqual(row.component_name, component.display_name)
        self.assertEqual(row.location_id, self.stock_location)
        self.assertAlmostEqual(row.on_hand, 1.0)
        self.assertAlmostEqual(row.reserved, 5.0)
        self.assertAlmostEqual(row.free, -4.0)
        self.assertAlmostEqual(row.need, 1.0)
        self.assertEqual(row.state, 'over_reserved')
        self.assertEqual(row.state_label, 'Reservado de más')
        self.assertEqual(row.res_model, 'stock.quant')
        self.assertEqual(row.action_open()['res_model'], 'stock.quant')

    # ==================================================================
    # (d) Las tres acciones devuelven el ir.actions correcto
    # ==================================================================
    def test_action_transfer_creates_draft_internal_picking(self):
        finished, component = self._supply_product('INSUMOS TRASLADO')
        tray = self.Tray._pf_populate(finished)
        action = tray[:1].action_transfer()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.picking')
        picking = self.env['stock.picking'].browse(action['res_id'])
        self.assertEqual(picking.state, 'draft')
        self.assertEqual(picking.picking_type_id, self.warehouse.int_type_id)
        self.assertEqual(picking.move_ids.product_id, component)
        self.assertGreater(picking.move_ids.product_uom_qty, 0.0)

    def test_action_buy_opens_quick_purchase(self):
        finished, component = self._supply_product('INSUMOS COMPRA')
        tray = self.Tray._pf_populate(finished)
        action = tray[:1].action_buy()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        wizard = self.env['mrp.quick.purchase.wizard'].browse(action['res_id'])
        self.assertEqual(wizard.purchase_line_ids.product_id, component)

    def test_action_adjust_opens_quants_inventory_mode(self):
        finished, _component = self._supply_product('INSUMOS AJUSTE')
        tray = self.Tray._pf_populate(finished)
        action = tray[:1].action_adjust()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertTrue(action['context'].get('inventory_mode'))

    # ==================================================================
    # (e) Corrección automática: guardia de permisos
    # ==================================================================
    def test_apply_correction_without_permission_raises(self):
        finished, _component = self._supply_product('INSUMOS PERMISO SIN')
        tray = self.Tray._pf_populate(finished)
        user = self._user(
            'pf_supply_no_perm', [self.env.ref('base.group_user')])
        with self.assertRaises(UserError):
            tray.with_user(user).action_apply_correction()

    def test_apply_correction_with_permission_notifies(self):
        finished, _component = self._supply_product('INSUMOS PERMISO CON')
        tray = self.Tray._pf_populate(finished)
        user = self._user('pf_supply_perm', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        action = tray.with_user(user).action_apply_correction()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertTrue(action['params']['message'])

    # ==================================================================
    # (f) No regresión (lote) + fila/nodo de insumos cableados
    # ==================================================================
    def test_lot_tray_still_opens(self):
        product = self._product(
            'INSUMOS LOTE REGRESION', tracking='lot')
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        real_lot = self.env['stock.lot'].create(
            {'name': 'INSUMOS-REAL', 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, 10.0, lot_id=real_lot)
        ghost = self.env['stock.lot'].create(
            {'name': 'INSUMOS-FANTASMA', 'product_id': product.id})
        self._outgoing_no_stock_lot(product, ghost, 2.0)
        action = self._wizard(product).action_run_pf_plan(
            'lot_no_stock', 'solution')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')

    def test_supply_panel_row_and_node_action(self):
        finished, _component = self._supply_product('INSUMOS PANEL')
        payload = self._payload(self._wizard(finished))
        by_key = {node['key']: node for node in payload['nodes']}
        supply = by_key['stock_supply']
        solutions = [
            action
            for row in supply['panel'] for action in row['actions']
            if action['key'] == 'solution'
            and action.get('args') == ['supply_issue', 'solution']
        ]
        self.assertTrue(
            solutions, 'La fila del insumo debe ofrecer "Solucionar".')
        self.assertEqual(solutions[0]['method'], 'action_run_pf_plan')
        self.assertEqual(solutions[0]['res_model'], 'printflow.product.flow')
        # El nodo con problema ofrece la entrada "Solucionar los insumos".
        self.assertIn('fix_supply', {a['key'] for a in supply['actions']})
