# -*- coding: utf-8 -*-
"""Paridad de la fila de LOTE entre PRODUCTO y PEDIDO (PrintFlow · Bloque V).

La falla de lote se inyecta SOLO en la estrategia del PRODUCTO. En el PEDIDO la
fila nace del motor de reglas y una segunda fila la DUPLICARÍA. Este candado
verifica que, para el MISMO producto con un lote reservado sin existencia:
  * el diagrama de PRODUCTO sí trae la fila del plan de lote;
  * el diagrama de PEDIDO NO la duplica (no inyecta la falla de lote).

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFlowCanvasLotParity(TransactionCase):
    """El PEDIDO no duplica la fila de lote del PRODUCTO."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Paridad Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.OrderWizard = cls.env['printflow.order.diagnostic.wizard']
        cls.Playbook = cls.env['printflow.resolution.playbook']

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

    def _panel_summaries(self, payload):
        return {
            row['plan_summary']
            for node in payload['nodes']
            for row in node.get('panel', [])
        }

    def test_order_mode_does_not_duplicate_lot_row(self):
        product = self._product('PARIDAD LOTE PRODUCTO')
        self._real_stock(product, 10.0)
        lot = self.env['stock.lot'].create(
            {'name': 'PARIDAD-LOTE-FANTASMA', 'product_id': product.id})
        self._outgoing_no_stock_lot(product, lot, 2.0)
        lot_summary = self.Playbook._pf_get_plan('lot_no_stock')['summary']

        # (1) Diagrama de PRODUCTO: SÍ trae la fila del lote.
        pwizard = self.Flow.browse(
            self.Flow.action_open_product_flow(product.id)['res_id'])
        product_payload = json.loads(pwizard.timeline_json)
        self.assertIn(
            lot_summary, self._panel_summaries(product_payload),
            'El diagrama de PRODUCTO debe inyectar la fila del lote.')

        # (2) Diagrama de PEDIDO: NO la duplica.
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
        wizard = self.OrderWizard.create({'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})

        order_payload = json.loads(wizard.focus_timeline_json)
        self.assertNotIn(
            lot_summary, self._panel_summaries(order_payload),
            'El diagrama de PEDIDO NO debe duplicar la fila de lote.')
