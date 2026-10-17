# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticDemandUom(TransactionCase):
    """A1: ``_get_demand_map`` debe consolidar la demanda del mismo producto en
    UdM distintas usando SIEMPRE la UdM de referencia del producto
    (``product.uom_id``), convirtiendo cada aporte con ``_compute_quantity``.

    Antes se acumulaba ``product_uom_qty`` crudo usando la UdM de la primera
    línea, mezclando magnitudes (5 unidades + 2 docenas = 7 "unidades" en vez de
    29). Este test reproduce ese error y blinda la corrección.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Demanda UdM',
        })
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO UDM MIXTA (DIAGNOSTICO)',
            'type': 'product',
            'uom_id': cls.uom_unit.id,
            'x_is_printflow_managed': True,
        })

    def _make_board(self):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id,
                    'product_uom_qty': 5.0,
                    'product_uom': self.uom_unit.id,
                }),
                (0, 0, {
                    'product_id': self.product.id,
                    'product_uom_qty': 2.0,
                    'product_uom': self.uom_dozen.id,
                }),
            ],
        })
        # Forzamos 'sale' sin confirmar: no dispara OC/MO y no afecta al cálculo.
        so.write({'state': 'sale'})
        return self.env['printflow.order.board'].create({'sale_order_id': so.id})

    def test_same_product_mixed_uom_consolidates_to_reference_uom(self):
        board = self._make_board()
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

        lines = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == self.product)
        self.assertEqual(
            len(lines), 1,
            'El mismo producto en UdM distintas debe consolidar en UNA sola línea.',
        )
        # 5 unidades + 2 docenas (12 c/u) = 29 unidades.
        self.assertAlmostEqual(lines.required_qty, 29.0, places=3)
        self.assertEqual(
            lines.uom_id, self.product.uom_id,
            'La UdM de la línea debe ser la de referencia del producto.',
        )
        self.assertEqual(
            lines.line_kind, 'finished',
            'Al venir de una línea de venta, la clasificación es "producto terminado".',
        )
