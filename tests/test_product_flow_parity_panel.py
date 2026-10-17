# -*- coding: utf-8 -*-
"""Paridad de la fila del panel: PRODUCTO vs PEDIDO (PrintFlow · Fase 5).

Para el MISMO ``pf_cause`` (déficit físico de un producto comprable), la fila del
panel del diagrama de PRODUCTO debe mostrar el MISMO plan que la falla del
diagnóstico de PEDIDO: mismo ``plan_summary`` (playbook) y misma etiqueta de
solución. Ambos consumen la ÚNICA fuente de verdad
(``printflow.resolution.playbook``).

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowParityPanel(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Paridad Panel'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Paridad Panel', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']

    def _purchasable(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True, 'purchase_ok': True,
            'seller_ids': [(0, 0, {'partner_id': self.supplier.id})],
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _product_wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    def _order_failure(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
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
        self.assertTrue(line)
        return line.failure_ids

    def test_panel_row_matches_order_failure_plan(self):
        product = self._purchasable('PARIDAD PANEL PRODUCTO')
        # El diagrama del PRODUCTO (sin venta) se lee ANTES de crear el pedido.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        pwizard = self._product_wizard(product)
        prows = [
            row
            for node in json.loads(pwizard.timeline_json)['nodes']
            for row in node.get('panel', [])
        ]
        # La fila de COMPRAS es la RAÍZ: ofrece "Solucionar" con su plan.
        purchase_row = next(
            row for row in prows if row['label'] == 'Compras')
        psolution = next(
            action
            for action in purchase_row['actions']
            if action['key'] == 'solution')

        # La falla del PEDIDO para el mismo producto/causa.
        failure = self._order_failure(product, 3.0).filtered(
            lambda f: f.node == 'purchase')
        self.assertTrue(failure)

        self.assertEqual(
            purchase_row['plan_summary'], failure.pf_plan_summary)
        self.assertEqual(psolution['sublabel'], failure.pf_solution_label)
