# -*- coding: utf-8 -*-
"""Guardia de reserva NEGATIVA en el selector de lote (PrintFlow).

Custodia que el selector por documento:
  * NO infle la disponibilidad por una reserva negativa (una anomalía no es
    stock);
  * EXCLUYA los quants fantasma (físico <= 0 y reservado < 0);
  * BLOQUEE con ``UserError`` un lote con algún quant de reserva negativa.

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFlowLotPickerNegativeReserved(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Lots = cls.env['printflow.flow.lots']
        cls.Picker = cls.env['printflow.flow.lot.picker']

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

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _negative_reserved(self, product, lot, qty):
        self.env['stock.quant']._update_reserved_quantity(
            product, self.stock_location, -qty, lot_id=lot)

    # ==================================================================
    # 1) No infla la disponibilidad por una reserva negativa
    # ==================================================================
    def test_available_lots_does_not_inflate_on_negative(self):
        product = self._product('NEG CANDIDATO')
        lot = self._lot(product, 'NEG-CANDIDATO-LOTE')
        self._stock(product, 5.0, lot)
        self._negative_reserved(product, lot, 3.0)

        result = self.Lots._pf_available_lots(product)
        entry = next(c for c in result if c['lot_id'] == lot.id)
        self.assertAlmostEqual(entry['available'], 5.0)
        self.assertAlmostEqual(entry['reserved'], 0.0)

    # ==================================================================
    # 2) Un quant fantasma NO se ofrece como lote
    # ==================================================================
    def test_phantom_quant_is_not_offered(self):
        product = self._product('NEG FANTASMA')
        phantom = self._lot(product, 'NEG-FANTASMA-LOTE')
        # Sin físico y con reserva negativa: inventario fantasma puro.
        self._negative_reserved(product, phantom, 5.0)

        result = self.Lots._pf_available_lots(product)
        self.assertNotIn(phantom.id, [c['lot_id'] for c in result])

    # ==================================================================
    # 3) El selector BLOQUEA un lote con reserva negativa
    # ==================================================================
    def test_picker_blocks_lot_with_negative_reserved(self):
        product = self._product('NEG PICKER')
        lot = self._lot(product, 'NEG-PICKER-LOTE')
        self._stock(product, 5.0, lot)
        self._negative_reserved(product, lot, 3.0)

        picker = self.Picker._pf_populate(
            product, 'no_stock_lot', 'stock.lot', lot.id,
            lot_name_actual='OTRO-LOTE')
        picker.lot_id = lot.id
        with self.assertRaises(UserError):
            picker.action_assign_lot()
