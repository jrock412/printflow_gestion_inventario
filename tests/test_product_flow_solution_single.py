# -*- coding: utf-8 -*-
"""Acción "Solucionar" ÚNICA: vive SOLO en la fila del panel (PrintFlow · Bloque V).

Regla de la opción A: el botón "Solucionar" NO se duplica. El NODO ya no trae la
acción ``solution`` y el PEDIDO no se toca; la fila del panel trae EXACTAMENTE
UNA ``solution`` primaria. En las filas de LOTE, además, los ``args`` incluyen el
producto del lote como 3er elemento ADITIVO:
``[cause, 'solution', origin_product_id]``.

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowSolutionSingle(TransactionCase):
    """El botón "Solucionar" aparece UNA sola vez: en la fila del panel."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Solución Única', 'supplier_rank': 1})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Solución Única'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _purchasable(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True, 'purchase_ok': True,
            'seller_ids': [(0, 0, {'partner_id': self.supplier.id})],
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot_product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

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

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _payload(self, wizard):
        return json.loads(wizard.timeline_json)

    # ==================================================================
    # 1) Producto roto (compra con déficit): nodo sin 'solution', fila con UNA
    # ==================================================================
    def test_broken_node_has_no_solution_and_row_has_exactly_one(self):
        product = self._purchasable('SOLUCION UNICA COMPRA')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        payload = self._payload(self._wizard(product))

        # (1) NINGÚN nodo trae la acción 'solution'.
        for node in payload['nodes']:
            self.assertNotIn(
                'solution', [a['key'] for a in node['actions']],
                'El nodo %r NO debe duplicar "Solucionar".' % node['key'])

        # (2) La fila del panel de Compras trae EXACTAMENTE UNA 'solution' por
        #     fila, marcada como HERO (``primary``).
        by_key = {n['key']: n for n in payload['nodes']}
        purchase = by_key['purchase']
        self.assertEqual(purchase['role'], 'root')
        rows_with_solution = [
            row for row in purchase['panel'] if row['solution_available']]
        self.assertTrue(rows_with_solution)
        for row in rows_with_solution:
            solutions = [
                a for a in row['actions'] if a['key'] == 'solution']
            self.assertEqual(len(solutions), 1)
            self.assertTrue(solutions[0].get('primary'))
        solution = next(
            a for row in rows_with_solution for a in row['actions']
            if a['key'] == 'solution')
        self.assertEqual(solution['method'], 'action_run_pf_node')
        self.assertEqual(solution['res_model'], 'printflow.product.flow')

    # ==================================================================
    # 2) Fila de LOTE: los args incluyen origin_product_id (3er elemento)
    # ==================================================================
    def test_lot_row_args_include_origin_product_id(self):
        product = self._lot_product('SOLUCION UNICA LOTE')
        ghost = self.env['stock.lot'].create(
            {'name': 'SOLUCION-UNICA-FANTASMA', 'product_id': product.id})
        self._outgoing_no_stock_lot(product, ghost, 2.0)
        wizard = self._wizard(product)
        payload = self._payload(wizard)

        by_key = {n['key']: n for n in payload['nodes']}
        delivery = by_key['delivery']
        lot_row = next(
            row for row in delivery['panel'] if row['solution_available'])
        solution = next(
            a for a in lot_row['actions'] if a['key'] == 'solution')
        self.assertEqual(
            solution['args'], ['lot_no_stock', 'solution', product.id])
        # El nodo de lote tampoco duplica "Solucionar".
        self.assertNotIn(
            'solution', [a['key'] for a in delivery['actions']])
