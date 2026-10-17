# -*- coding: utf-8 -*-
"""Explicación del nodo ENTREGA con un lote reservado SIN existencia.

Escenario tipo "FONDO NEGRO": producto gestionado con ``tracking='lot'`` cuyo
albarán de salida reserva un lote que NO tiene existencia interna (``lot_no_stock``
del Bloque V). El nodo de ENTREGA del diagrama de PRODUCTO debe explicarlo:

  * ``explain.severity == 'danger'`` (el lote manda sobre el tono neutro 'na');
  * la palabra "lote" aparece en ``why``;
  * ``how`` incluye los pasos del plan ``lot_no_stock`` del playbook;
  * **el semáforo del nodo (``node.tone``) NO cambia** (paridad intacta).

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFlowExplainDelivery(TransactionCase):
    """El lote reservado sin existencia se explica en el nodo Entrega."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Explain Entrega'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Presentation = cls.env['printflow.flow.presentation']
        cls.Playbook = cls.env['printflow.resolution.playbook']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _ghost_lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _outgoing_no_stock_lot(self, product, lot, qty=2.0):
        """Albarán de salida que reserva un lote SIN existencia (``lot_no_stock``)."""
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
    # El nodo Entrega explica el lote sin existencia (sin repintar el tono)
    # ==================================================================
    def test_delivery_explains_lot_no_stock_without_repainting(self):
        product = self._product('FLOW EXPLAIN FONDO NEGRO')
        ghost = self._ghost_lot(product, 'FLOW-EXPLAIN-FANTASMA-1')
        self._outgoing_no_stock_lot(product, ghost, 2.0)

        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        payload = json.loads(wizard.timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        delivery = by_key['delivery']
        explain = delivery['explain']

        # El lote sin existencia manda: severidad danger y motivo con "lote".
        self.assertEqual(explain['severity'], 'danger')
        self.assertTrue(
            any('lote' in reason.lower() for reason in explain['why']),
            'El motivo del nodo Entrega debe mencionar el lote.')
        # El "cómo" trae los pasos del plan del estado de lote.
        lot_plan = self.Playbook._pf_get_plan('lot_no_stock')
        for step in lot_plan['steps']:
            self.assertIn(step, explain['how'])

        # La capa de explicación NO repinta el nodo: el tono sale SOLO del estado.
        self.assertEqual(
            delivery['tone'],
            self.Presentation._pf_node_tone('delivery', delivery['status']),
            'El tono del nodo no debe cambiar por el estado de lote.')
