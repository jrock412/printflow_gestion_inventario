# -*- coding: utf-8 -*-
"""Acciones de LOTE del diagrama de PRODUCTO (PrintFlow · Bloque V).

Custodia que el hito de ENTREGA de un producto por lote con un lote reservado
SIN existencia (``lot_no_stock``):
  * trae una FILA de panel con la acción ``solution`` cableada al MISMO wizard
    ``printflow.product.flow`` vía ``action_run_pf_plan`` (con el producto del
    lote como 3er argumento ADITIVO);
  * el NODO ya NO trae el botón ``solution``: la corrección vive SOLO en la fila
    del panel, sin duplicar;
  * ``explain['how'][0]`` == el ``sublabel`` de la fila del panel (el texto guía
    la acción);
  * ``action_run_pf_plan('lot_no_stock', 'solution')`` ABRE la bandeja
    gestionable ``printflow.flow.lot.tray`` (no ejecuta el remedio directo).

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotActions(TransactionCase):
    """El lote sin existencia del nodo Entrega guía a la acción."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Lote Acciones'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']

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

    def _real_stock(self, product, qty=10.0):
        """Stock REAL en un lote propio: evita el déficit (así el lote sin
        existencia es la ÚNICA falla y el hito Entrega no es una consecuencia)."""
        lot = self.env['stock.lot'].create(
            {'name': '%s-REAL' % product.name, 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)
        return lot

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

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    # ==================================================================
    # El lote manda: fila de panel + acción + explain + fallback navegable
    # ==================================================================
    def test_delivery_lot_no_stock_offers_solution(self):
        product = self._product('LOTE ACCIONES FONDO NEGRO')
        self._real_stock(product, 10.0)
        ghost = self._ghost_lot(product, 'LOTE-ACCIONES-FANTASMA')
        self._outgoing_no_stock_lot(product, ghost, 2.0)

        wizard = self._wizard(product)
        payload = json.loads(wizard.timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        delivery = by_key['delivery']

        # (1) Fila de panel con la acción de solución cableada al wizard.
        lot_rows = [row for row in delivery['panel'] if row['solution_available']]
        self.assertTrue(
            lot_rows, 'El nodo Entrega debe traer la fila del lote.')
        solution = next(
            action for action in lot_rows[0]['actions']
            if action['key'] == 'solution')
        self.assertEqual(solution['res_model'], 'printflow.product.flow')
        self.assertEqual(solution['res_id'], wizard.id)
        self.assertEqual(solution['method'], 'action_run_pf_plan')
        self.assertEqual(
            solution['args'], ['lot_no_stock', 'solution', product.id])

        # (2) El NODO ya NO trae el botón 'solution' (sin duplicar).
        self.assertNotIn(
            'solution', [action['key'] for action in delivery['actions']])

        # (3) explain['how'][0] == sublabel de la FILA (guía a la acción).
        self.assertEqual(
            delivery['explain']['how'][0], solution['sublabel'])

        # (4) El dispatcher ABRE la BANDEJA gestionable de lote (no escribe aquí).
        action = wizard.action_run_pf_plan('lot_no_stock', 'solution')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')
