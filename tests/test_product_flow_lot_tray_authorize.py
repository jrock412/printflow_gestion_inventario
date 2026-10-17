# -*- coding: utf-8 -*-
"""Autorizar la asignación ACTUAL desde la bandeja de lote (PrintFlow).

El "Solucionar" del hallazgo "lotes mezclados" abre la bandeja de lote; su botón
de fila "Autorizar excepción" abre el wizard
``printflow.flow.lot.exception.authorize`` que pide el MOTIVO y autoriza el lote
de ESA fila como excepción documentada. NO reasigna: el lote ya estaba en el
documento. Tras autorizar, el estado del producto cae a ``lot_ok`` y el lote sale
de ``mixed_lots``.

Cubre también el selector: marcar "Autorizar…" con el lote ACTUAL ya no bloquea.

``TransactionCase`` hace rollback; solo toca sus propios registros.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTrayAuthorizeCurrentLot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Autoriza Bandeja'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Picker = cls.env['printflow.flow.lot.picker']
        cls.Authorize = cls.env['printflow.flow.lot.exception.authorize']
        cls.Health = cls.env['printflow.stock.health']
        cls.Exception = cls.env['printflow.lot.exception']

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

    def _mixed(self, name):
        """Producto con UN lote (nombre exclusivo ``-L1``) usado por 2 pedidos."""
        product = self._product(name)
        lot = self._lot(product, '%s-L1' % name)
        self._stock(product, 10.0, lot=lot)
        _o1, line_1 = self._sale_line(product)
        self._outgoing_with_sale_line(product, line_1, 2.0, lot)
        _o2, line_2 = self._sale_line(product)
        self._outgoing_with_sale_line(product, line_2, 2.0, lot)
        return product, lot

    def _tray(self, product, lot_state):
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        tray = self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])
        self.assertTrue(tray, 'La bandeja debe traer filas.')
        return tray

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    # ==================================================================
    # (a) Autorizar el lote actual desde la bandeja -> lot_ok, fuera de mixed
    # ==================================================================
    def test_authorize_current_lot_from_tray(self):
        product, lot = self._mixed('AUTORIZA-TRAY')
        self.assertEqual(
            self.Health._pf_lot_state(product)['state'], 'lot_mixed')

        tray = self._tray(product, 'lot_mixed')
        row = tray.filtered(
            lambda r: r.kind == 'mixed_lot' and r.can_authorize)[:1]
        self.assertTrue(row, 'Debe haber una fila autorizable.')
        self.assertEqual(row.lot_id, lot)

        action = row.action_authorize_lot()
        self.assertEqual(
            action['res_model'], 'printflow.flow.lot.exception.authorize')
        wizard = self.Authorize.browse(action['res_id'])
        self.assertEqual(wizard.lot_id, lot)

        wizard.reason = 'Reuso intencional del sobrante entre pedidos.'
        result = wizard.action_authorize()
        self.assertEqual(result['tag'], 'display_notification')

        exception = self.Exception.search([('lot_id', '=', lot.id)])
        self.assertTrue(exception.active)
        self.assertEqual(exception.reason, wizard.reason)

        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_ok')
        self.assertNotIn(lot.name, state['mixed_lots'])
        self.assertIn(lot.name, state['authorized_lots'])

    # ==================================================================
    # (b) El motivo es obligatorio
    # ==================================================================
    def test_reason_is_mandatory(self):
        _product, lot = self._mixed('AUTORIZA-MOTIVO')
        wizard = self.Authorize.create({'lot_id': lot.id})
        self.assertFalse(wizard.reason)
        with self.assertRaises(UserError):
            wizard.action_authorize()
        self.assertFalse(self.Exception.search([('lot_id', '=', lot.id)]))

    # ==================================================================
    # (c) Usuario sin permiso -> UserError
    # ==================================================================
    def test_authorize_without_permission_raises(self):
        _product, lot = self._mixed('AUTORIZA-PERMISO')
        user = self._user('pf_authorize_no_perm', [
            self.env.ref('base.group_user'),
            self.env.ref('stock.group_stock_user')])
        wizard = self.Authorize.create({
            'lot_id': lot.id, 'reason': 'No debería autorizarse.'})
        with self.assertRaises(UserError):
            wizard.with_user(user).action_authorize()
        self.assertFalse(self.Exception.search([('lot_id', '=', lot.id)]))

    # ==================================================================
    # (d) El selector: autorizar el lote ACTUAL ya no bloquea
    # ==================================================================
    def test_selector_authorizes_current_lot_without_reassign(self):
        product, lot = self._mixed('AUTORIZA-PICKER')
        tray = self._tray(product, 'lot_mixed')
        row = tray.filtered(
            lambda r: r.kind == 'mixed_lot' and r.can_choose_lot)[:1]
        action = row.action_open_lot_picker()
        picker = self.Picker.browse(action['res_id'])
        self.assertEqual(picker.lot_name_actual, lot.name)

        # Se elige el MISMO lote que el documento ya tiene + chek de autorizar.
        picker.lot_id = lot.id
        self.assertTrue(picker.is_current_selection)
        picker.authorize_shared_lot = True
        picker.exception_reason = 'La asignación actual es intencional.'
        result = picker.action_assign_lot()
        self.assertEqual(result['tag'], 'display_notification')

        self.assertTrue(self.Exception.search([('lot_id', '=', lot.id)]))
        self.assertEqual(
            self.Health._pf_lot_state(product)['state'], 'lot_ok')

    # ==================================================================
    # (retrocomportamiento) Sin el chek, el lote actual sigue bloqueado
    # ==================================================================
    def test_selector_blocks_current_lot_without_check(self):
        product, lot = self._mixed('AUTORIZA-BLOQUEO')
        tray = self._tray(product, 'lot_mixed')
        row = tray.filtered(
            lambda r: r.kind == 'mixed_lot' and r.can_choose_lot)[:1]
        action = row.action_open_lot_picker()
        picker = self.Picker.browse(action['res_id'])
        picker.lot_id = lot.id
        self.assertFalse(picker.authorize_shared_lot)
        with self.assertRaises(UserError):
            picker.action_assign_lot()
