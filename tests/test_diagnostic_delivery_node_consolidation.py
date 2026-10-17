# -*- coding: utf-8 -*-
"""Unificación del nodo ENTREGA del canvas (Opción A) — PrintFlow.

El antiguo nodo ``preparation`` ("Preparación / Despacho", ``kind='derived'``) era
un espejo 1:1 del estado de ``delivery`` y no aportaba señal propia: el contador
de entregas pendientes vivía en ``delivery`` pero el botón "Ver órdenes
pendientes" había quedado en ``preparation``. Este test blinda la
consolidación:

  * NO existe ningún nodo ``preparation`` en el payload (ni en el eje);
  * el nodo ``delivery`` concentra estado + contador (``info``) + acciones:
    expone ``pending_deliveries`` con el método público
    ``action_open_pending_delivery_orders``;
  * el ``info`` del nodo coincide EXACTAMENTE con
    ``line.pending_delivery_order_count`` (una sola fuente de verdad).

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticDeliveryNodeConsolidation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Consolida Entrega (DIAG)',
        })
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Cliente Consolida Entrega Otro (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        """Producto almacenable PrintFlow SIN ruta (genera albarán al confirmar)."""
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _confirm_order(self, partner, product, qty=1.0):
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

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

    def _wizard_for(self, own_so, product):
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line, 'El wizard debe tener la línea del producto.')
        wizard.write({'focus_line_id': line.id})
        return wizard, line

    def _delivery_wizard(self):
        """Pedido propio entregado + 3 pedidos ajenos con salida pendiente."""
        product = self._make_product('CONSOLIDA ENTREGA (DIAG)')
        self._add_stock(product, 1.0)

        own_so = self._confirm_order(self.customer, product, 1.0)
        self._deliver(own_so)

        other_pickings = self.env['stock.picking']
        for _i in range(3):
            other_so = self._confirm_order(self.other_customer, product, 1.0)
            other_pickings |= other_so.picking_ids
        self.assertEqual(len(other_pickings), 3)
        return self._wizard_for(own_so, product)

    # ------------------------------------------------------------------
    # 1) El nodo 'preparation' ya NO existe en el canvas
    # ------------------------------------------------------------------
    def test_no_preparation_node_in_payload(self):
        wizard, _line = self._delivery_wizard()
        payload = json.loads(wizard.focus_timeline_json)
        node_keys = [node['key'] for node in payload['nodes']]
        self.assertNotIn('preparation', node_keys)
        self.assertNotIn('preparation', payload['axis'])
        # No quedan nodos derivados (kind 'derived') en el canvas.
        self.assertFalse(
            [n for n in payload['nodes'] if n.get('kind') == 'derived'])

    # ------------------------------------------------------------------
    # 2) El nodo 'delivery' concentra el contador (info)
    # ------------------------------------------------------------------
    def test_delivery_node_carries_pending_count(self):
        wizard, line = self._delivery_wizard()
        payload = json.loads(wizard.focus_timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        self.assertIn('delivery', by_key)
        self.assertEqual(by_key['delivery']['info'], 3)
        # El contador del nodo es EXACTAMENTE el de la línea (fuente única).
        self.assertEqual(
            by_key['delivery']['info'], line.pending_delivery_order_count)

    # ------------------------------------------------------------------
    # 3) El nodo 'delivery' expone la acción "Ver órdenes pendientes"
    # ------------------------------------------------------------------
    def test_delivery_node_exposes_pending_action(self):
        wizard, _line = self._delivery_wizard()
        payload = json.loads(wizard.focus_timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        action = next(
            (a for a in by_key['delivery']['actions']
             if a['key'] == 'pending_deliveries'),
            None)
        self.assertIsNotNone(action, 'El nodo Entrega debe ofrecer el aviso.')
        self.assertEqual(action['method'], 'action_open_pending_delivery_orders')
        self.assertEqual(
            action['res_model'], 'printflow.order.diagnostic.wizard')
        self.assertTrue(action['enabled'])
