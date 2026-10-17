# -*- coding: utf-8 -*-
"""Excepción CONSCIENTE y auditable del selector de lote (PrintFlow).

Cuando el operador elige un lote que NO es el lote PROPIO del documento, el
selector marca ``is_exception`` y aplica la política configurable (cero
hardcodeo): con ``confirm_reason`` exige confirmación + motivo; con el lote
propio, la excepción NO se marca. La asignación deja registro (``message_post``)
en el chatter del albarán. El operador SIEMPRE puede elegir; la política solo
agrega fricción y registro.

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


@tagged('post_install', '-at_install')
class TestProductFlowLotPickerException(TransactionCase):
    """La excepción de lote propio exige fricción y deja bitácora."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Excepción Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Picker = cls.env['printflow.flow.lot.picker']
        # Política por defecto (DEFAULT): exige confirmación + motivo.
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
        # El pedido se vincula DESPUÉS de crear la reserva manual (evita que el
        # override de reserva exclusiva interfiera con el escenario del test).
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

    def _picker_for_no_stock(self, product, lot_state='lot_no_stock'):
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        row = self.Tray.search([
            ('product_id', '=', product.id),
            ('kind', '=', 'no_stock_lot'),
        ])[:1]
        self.assertTrue(row)
        action = row.action_open_lot_picker()
        return self.Picker.browse(action['res_id'])

    # ==================================================================
    # Excepción: lote distinto al propio
    # ==================================================================
    def test_exception_requires_confirmation_and_reason(self):
        product = self._product('EXCEPCION LOTE')
        _order, line = self._sale_line(product)
        own_name = line._get_exclusive_lot_name()
        self.assertTrue(own_name)
        own_lot = self._lot(product, own_name)
        self._stock(product, 5.0, lot=own_lot)
        other_lot = self._lot(product, 'EXCEPCION-OTRO')
        self._stock(product, 4.0, lot=other_lot)
        ghost = self._lot(product, 'EXCEPCION-FANTASMA')
        picking, move = self._outgoing_with_sale_line(
            product, line, 2.0, ghost)

        picker = self._picker_for_no_stock(product)
        self.assertEqual(picker.own_lot_name, own_name)
        # Lote PROPIO => NO es excepción.
        picker.lot_id = own_lot.id
        self.assertFalse(picker.is_exception)
        # Lote DISTINTO => es excepción.
        picker.lot_id = other_lot.id
        self.assertTrue(picker.is_exception)

        picker = picker.with_user(self._manager('pf_exc_lote'))
        # (a) Sin confirmación => error.
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        # (b) Confirmado SIN motivo => error (política confirm_reason).
        picker.confirm_exception = True
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        # (c) Confirmado + motivo => asigna y deja bitácora en el albarán.
        picker.exception_reason = (
            'El cliente rechazó el trabajo; se reusa el sobrante.')
        result = picker.action_assign_lot()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(other_lot, move.move_line_ids.mapped('lot_id'))
        self.assertNotIn(ghost, move.move_line_ids.mapped('lot_id'))
        self.assertTrue(any(
            'EXCEPCION-OTRO' in (message.body or '')
            for message in picking.message_ids))

    # ==================================================================
    # Política silenciosa: 'warn' deja elegir sin fricción
    # ==================================================================
    def test_warn_policy_allows_without_friction(self):
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'warn')
        product = self._product('EXCEPCION WARN')
        _order, line = self._sale_line(product)
        own_name = line._get_exclusive_lot_name()
        own_lot = self._lot(product, own_name)
        self._stock(product, 5.0, lot=own_lot)
        other_lot = self._lot(product, 'EXCEPCION-WARN-OTRO')
        self._stock(product, 4.0, lot=other_lot)
        ghost = self._lot(product, 'EXCEPCION-WARN-FANTASMA')
        _picking, move = self._outgoing_with_sale_line(
            product, line, 2.0, ghost)

        picker = self._picker_for_no_stock(product)
        picker = picker.with_user(self._manager('pf_exc_warn'))
        picker.lot_id = other_lot.id
        self.assertTrue(picker.is_exception)
        # Sin confirmación ni motivo: la política 'warn' NO bloquea.
        result = picker.action_assign_lot()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(other_lot, move.move_line_ids.mapped('lot_id'))
