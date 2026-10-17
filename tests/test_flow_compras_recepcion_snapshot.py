# -*- coding: utf-8 -*-
"""Fotografía REAL del diagrama en COMPRAS y RECEPCIÓN (PrintFlow).

Custodia el contrato de la tarea "fotografía real" (Sección 3 del CONTEXT.md):

  * **CA-1** — el nodo Compras reporta como pendiente SOLO las OC SIN CONFIRMAR:
    una OC confirmada y YA RECIBIDA (flujo nativo ``button_confirm`` + validar
    albarán) NO cuenta.
  * **CA-2** — el nodo Recepción deriva de los albaranes de entrada REALES: con
    uno abierto reporta "por recibir"; con todo recibido, deja de contar.
  * **CA-3** — si el producto es fabricable, la recepción de un COMPONENTE
    (insumo de su BOM) también se refleja en el nodo Recepción (producto y pedido).
  * **CA-4** — los badges son EXPLÍCITOS por nodo (``pending_label`` presente y
    diferenciado: "OC sin confirmar" en Compras, "por recibir" en Recepción).
  * **CA-6** — SOLO LECTURA: todo corre en ``TransactionCase`` (rollback) y el
    motor de pendientes NO usa SQL crudo ni ``cr.commit``.

Los datos de prueba se crean por el FLUJO NATIVO de Odoo (crear OC, confirmar,
validar albarán): no se fuerza ningún estado. Nada se persiste (rollback).
"""

import os

from odoo import fields
from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFlowComprasRecepcionSnapshot(TransactionCase):
    """CA-1..CA-6 de la fotografía real de Compras/Recepción."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flow = cls.env['printflow.product.flow']
        cls.Canvas = cls.env['printflow.flow.canvas']
        cls.Pending = cls.env['printflow.flow.pending']
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Snapshot Compras/Recepción'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Snapshot Compras/Recepción', 'supplier_rank': 1})
        # Nodos deterministas (transitorio: rollback al terminar la clase).
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_enabled', '1')
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_nodes',
            'purchase,receipt,production,delivery,sale')
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_limit', '0')

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

    def _manufacturable(self, name, component):
        """Terminado FABRICABLE con BOM a un componente (una sola línea)."""
        finished = self._product(name)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        return finished

    def _purchase_order(self, product):
        """OC en BORRADOR (sin confirmar) del producto."""
        return self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'price_unit': 1.0,
                'name': product.name,
                'product_uom': product.uom_id.id,
                'date_planned': fields.Datetime.now(),
            })],
        })

    def _receive_po(self, po):
        """Recibe por completo la OC por el FLUJO NATIVO (valida el albarán)."""
        picking = po.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(
            picking, 'La confirmación de la OC debe generar el albarán.')
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.button_validate()
        if (isinstance(result, dict)
                and result.get('res_model') == 'stock.backorder.confirmation'):
            self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({}).process()
        return picking

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    def _product_payload(self, product):
        return self.Canvas._pf_build_payload(self._wizard(product), 'product')

    def _order_payload(self, product):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
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
        wizard.write({'focus_line_id': line.id})
        return self.Canvas._pf_build_payload(wizard, 'order')

    @staticmethod
    def _by_key(payload):
        return {node['key']: node for node in payload['nodes']}

    # ==================================================================
    # CA-1 — Compras cuenta SOLO las OC sin confirmar (la recibida NO cuenta)
    # ==================================================================
    def test_ca1_purchase_pending_only_unconfirmed(self):
        product = self._purchasable('SNAPSHOT CA1')
        # OC confirmada y YA RECIBIDA (flujo nativo): no debe contar.
        received_po = self._purchase_order(product)
        received_po.button_confirm()
        self._receive_po(received_po)
        received_po.invalidate_recordset(['state'])
        self.assertEqual(received_po.state, 'purchase')
        # OC en borrador (sin confirmar): SÍ debe contar.
        self._purchase_order(product)

        pending = self.Pending._pf_node_pending_map(product).get(product.id, {})
        self.assertEqual(
            pending.get('purchase'), 1,
            'Compras debe contar SOLO la OC sin confirmar (la recibida no).')

    # ==================================================================
    # CA-2 — Recepción deriva de albaranes de entrada REALES
    # ==================================================================
    def test_ca2_receipt_pending_open_then_received(self):
        product = self._purchasable('SNAPSHOT CA2')
        po = self._purchase_order(product)
        po.button_confirm()

        opened = self._by_key(self._product_payload(product))
        self.assertGreaterEqual(opened['receipt']['pending'], 1)
        self.assertEqual(opened['receipt']['status'], 'pending')

        # Todo recibido -> deja de contar como pendiente.
        self._receive_po(po)
        closed = self._by_key(self._product_payload(product))
        self.assertEqual(closed['receipt']['pending'], 0)
        self.assertEqual(closed['receipt']['status'], 'na')

    # ==================================================================
    # CA-3 — Recepción de un INSUMO (BOM) se refleja (producto y pedido)
    # ==================================================================
    def test_ca3_receipt_counts_component(self):
        component = self._purchasable('SNAPSHOT CA3 COMPONENTE')
        po = self._purchase_order(component)
        po.button_confirm()
        finished = self._manufacturable('SNAPSHOT CA3 TERMINADO', component)

        by_key = self._by_key(self._product_payload(finished))
        self.assertGreaterEqual(
            by_key['receipt']['pending'], 1,
            'La recepción del insumo debe reflejarse en el diagrama del producto.')
        self.assertEqual(by_key['receipt']['status'], 'pending')

        order = self._by_key(self._order_payload(finished))
        self.assertGreaterEqual(
            order['receipt']['pending'], 1,
            'La recepción del insumo debe reflejarse también en el pedido.')
        self.assertEqual(order['receipt']['status'], 'pending')

    # ==================================================================
    # CA-4 — Badges EXPLÍCITOS por nodo (pending_label diferenciado)
    # ==================================================================
    def test_ca4_pending_labels_are_explicit(self):
        product = self._purchasable('SNAPSHOT CA4')
        self._purchase_order(product)  # OC en borrador -> Compras pendiente
        payload = self._product_payload(product)
        by_key = self._by_key(payload)

        # El contrato del nodo SIEMPRE trae la etiqueta (aunque pending sea 0).
        for node in payload['nodes']:
            self.assertIn('pending_label', node)

        self.assertEqual(
            by_key['purchase']['pending_label'], 'OC sin confirmar')
        self.assertEqual(by_key['receipt']['pending_label'], 'por recibir')
        self.assertNotEqual(
            by_key['purchase']['pending_label'],
            by_key['receipt']['pending_label'],
            'El badge de Compras y Recepción NO deben compartir texto genérico.')

    # ==================================================================
    # CA-6 — SOLO LECTURA (rollback + motor sin SQL crudo/commit)
    # ==================================================================
    def test_ca6_snapshot_is_read_only(self):
        product = self._purchasable('SNAPSHOT CA6')
        po = self._purchase_order(product)
        before_state = po.state
        before_qty = product.qty_available

        self.Pending._pf_node_pending_map(product)
        self.Pending._pf_receipt_pending_distinct([product.id])
        self._product_payload(product)

        po.invalidate_recordset(['state'])
        self.assertEqual(po.state, before_state)
        self.assertEqual(product.qty_available, before_qty)

    def test_ca6_engine_has_no_raw_sql(self):
        module_path = get_module_path('printflow_gestion_inventario')
        target = os.path.join(
            module_path, 'models', 'printflow_flow_pending.py')
        with open(target, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('cr.execute(', source)
        self.assertNotIn('cr.commit(', source)
