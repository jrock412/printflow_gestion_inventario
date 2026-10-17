# -*- coding: utf-8 -*-
"""Autorización PERSISTENTE desde el selector de lote (PrintFlow).

Cuando el operador marca el check "Autorizar este lote como excepción
documentada" (con su motivo), el selector crea una ``printflow.lot.exception``:
el detector de mezcla del motor deja de reportar el lote y el estado cae a
``lot_ok``. SIN el check NO se crea nada (retrocomportamiento). La política
``warn`` sin marca tampoco autoriza. Un usuario sin permiso (jefe de taller/admin)
recibe ``UserError`` en la guardia.

Crea sus propios registros; ``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


@tagged('post_install', '-at_install')
class TestPickerAuthorizeSharedLot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Autoriza Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Picker = cls.env['printflow.flow.lot.picker']
        cls.Health = cls.env['printflow.stock.health']
        cls.Exception = cls.env['printflow.lot.exception']
        cls.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'confirm_reason')

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

    def _sale_line(self, product):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        return order, order.order_line.filtered(
            lambda line: line.product_id == product)[:1]

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _outgoing_with_sale_line(self, product, sale_line, qty=2.0, lot=None):
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
            'lot_id': lot.id if lot else False,
        })
        move.sale_line_id = sale_line.id
        return picking, move

    def _manager(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('mrp.group_mrp_manager').id,
            ])],
        })

    def _regular_user(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('stock.group_stock_user').id,
            ])],
        })

    def _picker_for_no_stock(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan('lot_no_stock', 'solution')
        row = self.Tray.search([
            ('product_id', '=', product.id),
            ('kind', '=', 'no_stock_lot'),
        ])[:1]
        self.assertTrue(row)
        action = row.action_open_lot_picker()
        return self.Picker.browse(action['res_id'])

    def _scenario(self, name):
        """Producto con lote propio, lote ajeno (usado por 2 pedidos) y 1 movimiento
        con lote fantasma (para que la bandeja ofrezca el "no_stock_lot").

        El lote ajeno lleva sufijo exclusivo (``-L<n>``) para NO caer en
        "genérico" (que tiene mayor precedencia que "mezclado").
        """
        product = self._product(name)
        _order, line = self._sale_line(product)
        own_name = line._get_exclusive_lot_name()
        own_lot = self._lot(product, own_name)
        self._stock(product, 5.0, lot=own_lot)
        other_lot = self._lot(product, '%s-L7' % name)
        self._stock(product, 4.0, lot=other_lot)
        ghost = self._lot(product, '%s-FANTASMA' % name)
        _picking, move = self._outgoing_with_sale_line(product, line, 2.0, ghost)
        # Segundo pedido que usará el lote ajeno: habilita la mezcla observable.
        _order_b, line_b = self._sale_line(product)
        self._outgoing_with_sale_line(product, line_b, 2.0, other_lot)
        picker = self._picker_for_no_stock(product)
        return product, other_lot, move, picker

    # ==================================================================
    # Con el check: crea la excepción y el motor cae a lot_ok
    # ==================================================================
    def test_check_authorizes_and_clears_mixed(self):
        product, other_lot, move, picker = self._scenario('AUTORIZA')
        manager = self._manager('pf_autoriza_lote')
        picker = picker.with_user(manager)
        picker.lot_id = other_lot.id
        self.assertTrue(picker.is_exception)
        picker.confirm_exception = True
        picker.exception_reason = 'Se autoriza reusar el sobrante real.'
        picker.authorize_shared_lot = True
        result = picker.action_assign_lot()
        self.assertEqual(result['tag'], 'display_notification')

        exception = self.Exception.search([('lot_id', '=', other_lot.id)])
        self.assertEqual(len(exception), 1)
        self.assertEqual(
            exception.reason, 'Se autoriza reusar el sobrante real.')
        self.assertEqual(exception.authorized_by_id, manager)
        self.assertEqual(exception.source_model, 'stock.move')
        self.assertEqual(exception.source_id, move.id)

        self.assertEqual(self.Health._pf_lot_state(product)['state'], 'lot_ok')
        # Revocar demuestra que era la excepción la que despejaba la mezcla.
        self.Health._pf_revoke_lot_exception(other_lot)
        self.assertEqual(
            self.Health._pf_lot_state(product)['state'], 'lot_mixed')

    # ==================================================================
    # Sin el check: NO crea registro (retrocomportamiento)
    # ==================================================================
    def test_without_check_does_not_authorize(self):
        product, other_lot, _move, picker = self._scenario('SIN-CHECK')
        picker = picker.with_user(self._manager('pf_sin_check'))
        picker.lot_id = other_lot.id
        picker.confirm_exception = True
        picker.exception_reason = 'Motivo presente pero sin autorizar.'
        self.assertFalse(picker.authorize_shared_lot)
        picker.action_assign_lot()
        self.assertFalse(self.Exception.search([('lot_id', '=', other_lot.id)]))
        self.assertEqual(
            self.Health._pf_lot_state(product)['state'], 'lot_mixed')

    # ==================================================================
    # Política 'warn' sin marca: tampoco autoriza
    # ==================================================================
    def test_warn_policy_without_check_does_not_authorize(self):
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'warn')
        _product, other_lot, _move, picker = self._scenario('WARN')
        picker = picker.with_user(self._manager('pf_warn'))
        picker.lot_id = other_lot.id
        self.assertTrue(picker.is_exception)
        picker.action_assign_lot()
        self.assertFalse(self.Exception.search([('lot_id', '=', other_lot.id)]))

    # ==================================================================
    # El check exige motivo (una autorización no auditable no se guarda).
    # Política 'confirm' NO pide motivo: el motivo lo exige el propio check.
    # ==================================================================
    def test_check_requires_reason(self):
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'confirm')
        _product, other_lot, _move, picker = self._scenario('SIN-MOTIVO')
        self.assertEqual(picker.exception_policy, 'confirm')
        picker = picker.with_user(self._manager('pf_sin_motivo'))
        picker.lot_id = other_lot.id
        picker.confirm_exception = True
        picker.authorize_shared_lot = True
        picker.exception_reason = False
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        self.assertFalse(self.Exception.search([('lot_id', '=', other_lot.id)]))

    # ==================================================================
    # Usuario sin permiso: la guardia bloquea antes de autorizar
    # ==================================================================
    def test_user_without_permission_cannot_authorize(self):
        _product, other_lot, _move, picker = self._scenario('SIN-PERMISO')
        picker = picker.with_user(self._regular_user('pf_sin_permiso'))
        picker.lot_id = other_lot.id
        picker.confirm_exception = True
        picker.exception_reason = 'No debería llegar a guardarse.'
        picker.authorize_shared_lot = True
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        self.assertFalse(self.Exception.search([('lot_id', '=', other_lot.id)]))
