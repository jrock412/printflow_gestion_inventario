# -*- coding: utf-8 -*-
"""UX del selector de lote: resumen, señales y sugerencia (PrintFlow).

Custodia que, al poblar el selector:
  * el lote PROPIO y el lote ACTUAL SIEMPRE aparezcan en la tabla (aunque tengan
    0 existencia) para que el operador los vea;
  * el resumen del documento muestre la existencia del propio/actual;
  * las señales (``hint``) y banderas (``is_own_lot``/``is_current_lot``/
    ``is_authorized``/``is_elective``) sean correctas;
  * haya EXACTAMENTE UNA fila sugerida (``is_recommended``);
  * las guardias de vista (check ``is_selected``, editable, sin ``action_pick_lot``,
    form editable con ``name="lot_id"``) se conserven.

``TransactionCase`` hace rollback; crea sus propios registros.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotPickerUx(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente UX Picker'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
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

    def _stock(self, product, qty, lot=None, reserved=0.0):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot,
            reserved_quantity=reserved)

    def _sale_line(self, product):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 2.0,
                'product_uom': product.uom_id.id,
            })],
        })
        return order.order_line.filtered(
            lambda line: line.product_id == product)[:1]

    def _move_with_lot(self, product, lot, sale_line=None):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        move = self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': 2.0,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
        })
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'quantity': 2.0,
            'lot_id': lot.id,
        })
        if sale_line:
            move.sale_line_id = sale_line.id
        return picking, move

    def _picker(self, product, move, own_lot_name='', current_lot=None):
        return self.Picker._pf_populate(
            product, 'no_stock_lot', 'stock.move', move.id,
            own_lot_name=own_lot_name,
            lot_name_actual=current_lot.name if current_lot else '',
            location_id=self.stock_location.id,
            demand_qty=2.0,
            current_lot_id=current_lot,
        )

    # ==================================================================
    # Propio/actual SIEMPRE en la tabla + señales
    # ==================================================================
    def test_own_and_current_lots_are_listed_and_labeled(self):
        product = self._product('UX PICKER')
        line = self._sale_line(product)
        own_name = line._get_exclusive_lot_name()
        own_lot = self._lot(product, own_name)          # sin existencia
        current_lot = self._lot(product, 'UX-PICKER-ACTUAL')
        self._stock(product, 10.0, lot=current_lot, reserved=2.0)
        _picking, move = self._move_with_lot(product, current_lot, line)

        picker = self._picker(
            product, move, own_lot_name=own_name, current_lot=current_lot)
        self.assertEqual(picker.own_lot_id, own_lot)
        self.assertEqual(picker.current_lot_id, current_lot)

        cand_ids = picker.candidate_ids.mapped('lot_id')
        self.assertIn(own_lot, cand_ids, 'El lote propio SIEMPRE se lista.')
        self.assertIn(current_lot, cand_ids, 'El lote actual SIEMPRE se lista.')

        own_cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == own_lot)[:1]
        self.assertTrue(own_cand.is_own_lot)
        self.assertFalse(own_cand.is_elective)
        self.assertEqual(own_cand.hint, 'Tu lote (sin existencia)')
        self.assertEqual(own_cand.role_label, 'Lote original del pedido')
        self.assertAlmostEqual(own_cand.qty_on_hand, 0.0)

        cur_cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == current_lot)[:1]
        self.assertTrue(cur_cand.is_current_lot)
        self.assertTrue(cur_cand.is_elective)
        self.assertEqual(cur_cand.hint, 'Lote actual')
        self.assertEqual(cur_cand.role_label, 'Lote que está usando')
        self.assertAlmostEqual(cur_cand.qty_on_hand, 10.0)
        self.assertAlmostEqual(cur_cand.available, 8.0)

        # Resumen con cifras (existencia · reservado · disponible).
        self.assertIn('Existencia', picker.current_lot_summary)
        self.assertIn('reservado', picker.current_lot_summary)
        self.assertIn('disponible', picker.current_lot_summary)
        self.assertIn('0.00', picker.own_lot_summary)

    # ==================================================================
    # Exactamente UNA fila sugerida
    # ==================================================================
    def test_exactly_one_recommended(self):
        product = self._product('UX PICKER SUGERIDO')
        current_lot = self._lot(product, 'UX-SUG-ACTUAL')
        self._stock(product, 10.0, lot=current_lot)
        bigger = self._lot(product, 'UX-SUG-GRANDE')
        self._stock(product, 50.0, lot=bigger)
        _picking, move = self._move_with_lot(product, current_lot)

        picker = self._picker(product, move, current_lot=current_lot)
        recommended = picker.candidate_ids.filtered('is_recommended')
        self.assertEqual(len(recommended), 1, 'Debe haber UNA sola sugerencia.')
        # Sin lote propio, gana el de mayor libre (bigger).
        self.assertEqual(recommended.lot_id, bigger)

    # ==================================================================
    # Guardias de vista (se conservan)
    # ==================================================================
    def test_view_guards_preserved(self):
        tree = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_candidate_view_tree').arch
        self.assertIn('name="is_selected"', tree)
        self.assertIn('editable="bottom"', tree)
        self.assertNotIn('action_pick_lot', tree)
        # Columnas mínimas para decidir.
        self.assertIn('name="qty_on_hand"', tree)
        self.assertIn('name="reserved"', tree)
        self.assertIn('name="available"', tree)
        self.assertIn('name="role_label"', tree)
        # Secundarios (ocultos por defecto, no borrados).
        self.assertIn('name="hint"', tree)
        self.assertIn('name="is_recommended"', tree)

        form = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_picker_view_form').arch
        self.assertNotIn('edit="false"', form)
        self.assertIn('name="lot_id"', form)
