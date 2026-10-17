# -*- coding: utf-8 -*-
"""Candado de PARIDAD del canvas (PrintFlow).

El payload del pedido producido por el wizard (``_pf_timeline_payload``) debe
ser EXACTAMENTE el que produce el servicio compartido
``printflow.flow.canvas._pf_build_payload(wizard, 'order')``. Es la red de
seguridad de la extracción del canvas (Fase 5): cualquier divergencia rompe
``test_diagnostic_timeline_payload`` y este test.
"""

import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFlowCanvasParity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Canvas Parity'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Canvas Parity', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Canvas = cls.env['printflow.flow.canvas']

    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _force_order(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return self.env['printflow.order.board'].create({'sale_order_id': so.id})

    def _purchase_root_wizard(self):
        product = self._product(
            'PARITY COMPRA RAIZ', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        board = self._force_order(product, 4.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        wizard.write({'focus_line_id': line.id})
        return wizard

    def test_order_payload_is_deep_equal(self):
        wizard = self._purchase_root_wizard()
        self.assertEqual(
            self.Canvas._pf_build_payload(wizard, 'order'),
            wizard._pf_timeline_payload())

    def test_serialized_payload_matches_canvas(self):
        wizard = self._purchase_root_wizard()
        self.assertEqual(
            json.loads(wizard.focus_timeline_json),
            self.Canvas._pf_build_payload(wizard, 'order'))

    def test_without_focus_payload_is_deep_equal(self):
        product = self._product('PARITY SIN FOCO')
        board = self._force_order(product, 1.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        self.assertFalse(wizard.focus_line_id)
        self.assertEqual(
            self.Canvas._pf_build_payload(wizard, 'order'),
            wizard._pf_timeline_payload())
