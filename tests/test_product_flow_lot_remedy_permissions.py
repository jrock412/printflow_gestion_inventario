# -*- coding: utf-8 -*-
"""Permisos de los remedios de LOTE del diagrama de PRODUCTO (PrintFlow).

El "Solucionar" de un hallazgo de lote ABRE la bandeja gestionable
(``printflow.flow.lot.tray``), NO ejecuta el remedio: VER la bandeja no exige
permisos especiales (cualquier ``base.group_user``). La EJECUCIÓN del remedio
vive en ``action_apply_correction``, que pasa por el guardia
``printflow.stock.remedy._pf_assert_can_clean()`` (jefe de taller/admin):
  * SIN permiso -> la bandeja se VE, pero ``action_apply_correction`` lanza
    ``UserError`` (no se toca el inventario);
  * CON permiso -> notificación de resultado (acción ejecutada).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotRemedyPermissions(TransactionCase):
    """El remedio de lote respeta el guardia de permisos del principal."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Permiso Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']

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

    def _outgoing(self, product, qty=2.0, lot=None):
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
        return picking, move

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    def _tray(self, product):
        """Filas de la bandeja creadas para el producto (por el wizard)."""
        return self.env['printflow.flow.lot.tray'].search(
            [('product_id', '=', product.id)])

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    def _orphan_product(self, name):
        product = self._product(name)
        # Quant con reservado SIN movimiento que lo respalde (huérfana).
        self._stock(product, 0.0, lot=None, reserved=5.0)
        return product

    # ==================================================================
    # 1) Reserva huérfana
    # ==================================================================
    def test_orphan_view_tray_without_permission_then_apply_raises(self):
        product = self._orphan_product('PERMISO HUERFANA SIN')
        wizard = self._wizard(product)
        user = self._user(
            'pf_lot_orphan_no_perm', [self.env.ref('base.group_user')])
        # VER la bandeja NO exige el permiso de saneamiento.
        action = wizard.with_user(user).action_run_pf_plan(
            'lot_orphan_reservation', 'solution')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')
        tray = self._tray(product)
        self.assertTrue(tray)
        # APLICAR la corrección SÍ pasa por el guardia -> UserError.
        with self.assertRaises(UserError):
            tray.with_user(user).action_apply_correction()

    def test_orphan_with_permission_notifies(self):
        product = self._orphan_product('PERMISO HUERFANA CON')
        wizard = self._wizard(product)
        user = self._user('pf_lot_orphan_perm', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        wizard.with_user(user).action_run_pf_plan(
            'lot_orphan_reservation', 'solution')
        tray = self._tray(product)
        self.assertTrue(tray)
        action = tray.with_user(user).action_apply_correction()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')

    # ==================================================================
    # 2) Movimiento sin lote
    # ==================================================================
    def test_missing_view_tray_without_permission_then_apply_raises(self):
        product = self._product('PERMISO SIN LOTE')
        self._outgoing(product, 2.0, lot=None)
        wizard = self._wizard(product)
        user = self._user(
            'pf_lot_missing_no_perm', [self.env.ref('base.group_user')])
        action = wizard.with_user(user).action_run_pf_plan(
            'lot_missing', 'solution')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')
        tray = self._tray(product)
        self.assertTrue(tray)
        with self.assertRaises(UserError):
            tray.with_user(user).action_apply_correction()

    def test_missing_with_permission_notifies(self):
        product = self._product('PERMISO SIN LOTE OK')
        self._outgoing(product, 2.0, lot=None)
        wizard = self._wizard(product)
        user = self._user('pf_lot_missing_perm', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        wizard.with_user(user).action_run_pf_plan('lot_missing', 'solution')
        tray = self._tray(product)
        self.assertTrue(tray)
        action = tray.with_user(user).action_apply_correction()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
