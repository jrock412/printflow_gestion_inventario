# -*- coding: utf-8 -*-
"""Flujo de CORRECCIÓN del lote equivocado (PrintFlow).

Custodia la ventana de corrección:
  * documento ABIERTO -> se puede corregir (A -> B);
  * documento VALIDADO (``move``/``picking`` ``done``) -> BLOQUEADO por servidor
    (``UserError`` y sin escritura);
  * MO terminada SIN lote -> PERMITIDO (completar el dato); CON lote -> bloqueado;
  * validación en curso (``picked``) -> exige confirmación + motivo;
  * corregir un lote autorizado revoca la autorización anterior SOLO si se marca
    ``revoke_prior_authorization``.

``TransactionCase`` hace rollback; crea sus propios registros.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


@tagged('post_install', '-at_install')
class TestProductFlowLotCorrection(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Corrección Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Picker = cls.env['printflow.flow.lot.picker']
        cls.Health = cls.env['printflow.stock.health']
        cls.Exception = cls.env['printflow.lot.exception']
        # Política 'warn': aísla la corrección de la fricción de excepción.
        cls.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'warn')

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

    def _stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _move_with_lot(self, product, lot, picked=False):
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
            'picked': picked,
        })
        return picking, move

    def _mo(self, product):
        manu_type = self.warehouse.manu_type_id
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id
                or self.stock_location.id),
        })

    def _manager(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('mrp.group_mrp_manager').id,
            ])],
        })

    def _picker_move(self, product, move, current_lot, target_kind='no_stock_lot'):
        picker = self.Picker._pf_populate(
            product, target_kind, 'stock.move', move.id,
            lot_name_actual=current_lot.name if current_lot else '',
            location_id=self.stock_location.id,
            demand_qty=2.0,
            current_lot_id=current_lot,
        )
        return picker.with_user(self._manager('pf_corr_%s' % move.id))

    # ==================================================================
    # Abierto: corrige A -> B
    # ==================================================================
    def test_open_move_allows_correction(self):
        product = self._product('CORR ABIERTO')
        lot_a = self._lot(product, 'CORR-A')
        lot_b = self._lot(product, 'CORR-B')
        self._stock(product, 5.0, lot=lot_a)
        self._stock(product, 5.0, lot=lot_b)
        _picking, move = self._move_with_lot(product, lot_a)

        picker = self._picker_move(product, move, lot_a)
        picker.lot_id = lot_b.id
        self.assertTrue(picker.is_correction)
        self.assertTrue(picker.can_correct)
        result = picker.action_assign_lot()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(lot_b, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # Movimiento validado -> bloqueado por servidor, sin escritura
    # ==================================================================
    def test_done_move_blocks_correction(self):
        product = self._product('CORR MOV DONE')
        lot_a = self._lot(product, 'CORR-DONE-A')
        lot_b = self._lot(product, 'CORR-DONE-B')
        self._stock(product, 5.0, lot=lot_a)
        self._stock(product, 5.0, lot=lot_b)
        _picking, move = self._move_with_lot(product, lot_a)
        move.write({'state': 'done'})

        picker = self._picker_move(product, move, lot_a)
        picker.lot_id = lot_b.id
        self.assertFalse(picker.can_correct)
        self.assertTrue(picker.correction_block_reason)
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        self.assertIn(lot_a, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # Albarán validado -> bloqueado
    # ==================================================================
    def test_done_picking_blocks_correction(self):
        product = self._product('CORR PICK DONE')
        lot_a = self._lot(product, 'CORR-PICK-A')
        lot_b = self._lot(product, 'CORR-PICK-B')
        self._stock(product, 5.0, lot=lot_a)
        self._stock(product, 5.0, lot=lot_b)
        picking, move = self._move_with_lot(product, lot_a)
        picking.write({'state': 'done'})

        picker = self._picker_move(product, move, lot_a)
        picker.lot_id = lot_b.id
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        self.assertIn(lot_a, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # MO terminada SIN lote -> PERMITIDO (completar el dato)
    # ==================================================================
    def test_done_mo_without_lot_allows(self):
        product = self._product('CORR MO SIN LOTE')
        chosen = self._lot(product, 'CORR-MO-ELEGIDO')
        self._stock(product, 5.0, lot=chosen)
        mo = self._mo(product)
        mo.write({'state': 'done'})
        self.assertFalse(mo.lot_producing_id)

        picker = self.Picker._pf_populate(
            product, 'unassigned_mo', 'mrp.production', mo.id,
            lot_name_actual='', demand_qty=1.0)
        picker = picker.with_user(self._manager('pf_corr_mo_ok'))
        picker.lot_id = chosen.id
        picker.action_assign_lot()
        self.assertEqual(mo.lot_producing_id, chosen)

    # ==================================================================
    # MO terminada CON lote -> bloqueado
    # ==================================================================
    def test_done_mo_with_lot_blocks(self):
        product = self._product('CORR MO CON LOTE')
        old = self._lot(product, 'CORR-MO-OLD')
        new = self._lot(product, 'CORR-MO-NEW')
        self._stock(product, 5.0, lot=old)
        self._stock(product, 5.0, lot=new)
        mo = self._mo(product)
        mo.write({'state': 'done', 'lot_producing_id': old.id})

        picker = self.Picker._pf_populate(
            product, 'unassigned_mo', 'mrp.production', mo.id,
            lot_name_actual=old.name, demand_qty=1.0, current_lot_id=old)
        picker = picker.with_user(self._manager('pf_corr_mo_no'))
        picker.lot_id = new.id
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        self.assertEqual(mo.lot_producing_id, old)

    # ==================================================================
    # Validación en curso (picked): confirmación + motivo
    # ==================================================================
    def test_picked_requires_confirmation_and_reason(self):
        product = self._product('CORR PICKED')
        lot_a = self._lot(product, 'CORR-PICKED-A')
        lot_b = self._lot(product, 'CORR-PICKED-B')
        self._stock(product, 5.0, lot=lot_a)
        self._stock(product, 5.0, lot=lot_b)
        _picking, move = self._move_with_lot(product, lot_a, picked=True)

        picker = self._picker_move(product, move, lot_a)
        picker.lot_id = lot_b.id
        self.assertTrue(picker.document_in_progress)
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        picker.confirm_correction = True
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        picker.exception_reason = 'Se corrige el lote en plena validación.'
        result = picker.action_assign_lot()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(lot_b, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # Revocar la autorización del lote anterior (solo si se marca)
    # ==================================================================
    def test_correction_revokes_prior_authorization_only_when_marked(self):
        # Caso 1: NO se marca -> la autorización anterior sigue activa.
        product = self._product('CORR REVOKE OFF')
        lot_a = self._lot(product, 'CORR-REV-A')
        lot_b = self._lot(product, 'CORR-REV-B')
        self._stock(product, 5.0, lot=lot_a)
        self._stock(product, 5.0, lot=lot_b)
        _picking, move = self._move_with_lot(product, lot_a)
        self.Health._pf_authorize_lot_exception(lot_a, reason='Autorizado antes.')

        picker = self._picker_move(product, move, lot_a)
        picker.lot_id = lot_b.id
        self.assertTrue(picker.current_lot_is_authorized)
        self.assertFalse(picker.revoke_prior_authorization)
        picker.action_assign_lot()
        self.assertTrue(self.Exception.search([
            ('lot_id', '=', lot_a.id), ('active', '=', True)]))

        # Caso 2: SÍ se marca -> se revoca la autorización anterior.
        product_2 = self._product('CORR REVOKE ON')
        lot_a2 = self._lot(product_2, 'CORR-REV2-A')
        lot_b2 = self._lot(product_2, 'CORR-REV2-B')
        self._stock(product_2, 5.0, lot=lot_a2)
        self._stock(product_2, 5.0, lot=lot_b2)
        _picking_2, move_2 = self._move_with_lot(product_2, lot_a2)
        self.Health._pf_authorize_lot_exception(lot_a2, reason='Autorizado antes 2.')

        picker_2 = self._picker_move(product_2, move_2, lot_a2)
        picker_2.lot_id = lot_b2.id
        picker_2.revoke_prior_authorization = True
        picker_2.action_assign_lot()
        self.assertFalse(self.Exception.search([
            ('lot_id', '=', lot_a2.id), ('active', '=', True)]))
