# -*- coding: utf-8 -*-
"""Semáforo del diagrama de PRODUCTO con problema de LOTE (PrintFlow).

El lote NO repinta el ``tone``: su severidad se expresa A TRAVÉS del ``status``
del nodo. Este candado verifica que, con un lote reservado sin existencia
(``lot_no_stock``), TODOS los nodos siguen cumpliendo
``node['tone'] == presentation._pf_node_tone(key, node['status'])`` y que el hito
que porta el lote deja de estar en ``'na'`` (el semáforo se enciende).

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotSemaphore(TransactionCase):
    """El estado de lote enciende el semáforo por ``status`` (no por ``tone``)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Semáforo Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Presentation = cls.env['printflow.flow.presentation']

    def _product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _real_stock(self, product, qty=10.0):
        """Stock REAL en un lote propio: evita el déficit del escenario."""
        lot = self.env['stock.lot'].create(
            {'name': '%s-REAL' % product.name, 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)
        return lot

    def _outgoing_no_stock_lot(self, product, lot, qty=2.0):
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

    def test_lot_status_drives_tone_without_repainting(self):
        product = self._product('SEMAFORO LOTE FONDO NEGRO')
        self._real_stock(product, 10.0)
        lot = self.env['stock.lot'].create(
            {'name': 'SEMAFORO-LOTE-FANTASMA', 'product_id': product.id})
        self._outgoing_no_stock_lot(product, lot, 2.0)

        wizard = self.Flow.browse(
            self.Flow.action_open_product_flow(product.id)['res_id'])
        payload = json.loads(wizard.timeline_json)

        # Paridad del semáforo en TODOS los nodos: el tone sale del status.
        for node in payload['nodes']:
            self.assertEqual(
                node['tone'],
                self.Presentation._pf_node_tone(node['key'], node['status']),
                'El tono del nodo %r no debe repintarse desde el lote.'
                % node['key'])

        # El hito que porta el lote deja de estar en 'na'.
        by_key = {node['key']: node for node in payload['nodes']}
        delivery = by_key['delivery']
        self.assertEqual(delivery['status'], 'lot_no_stock')
        self.assertNotEqual(delivery['tone'], 'na')
        self.assertEqual(delivery['tone'], 'danger')
