# -*- coding: utf-8 -*-
"""Bandeja gestionable de LOTE del diagrama de PRODUCTO (PrintFlow · Bloque V).

El "Solucionar" de un hallazgo de lote YA NO ejecuta el remedio directo: ABRE la
bandeja ``printflow.flow.lot.tray``, que lista UNA fila por ítem afectado y deja
la corrección en el botón de cabecera ``action_apply_correction``. Este candado
custodia, para los estados SIN venta (``lot_no_stock``, ``lot_generic``,
``lot_unassigned_finished``):
  * ``action_run_pf_plan(state, 'solution')`` abre la bandeja con >=1 fila;
  * las filas listan ítems concretos y ``action_open`` NAVEGA al registro real;
  * ``action_apply_correction`` sin permiso -> ``UserError``; con
    ``mrp.group_mrp_manager`` -> notificación (remedio real del motor).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
import json

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotTray(TransactionCase):
    """La bandeja de lote abre, lista lo afectado y aplica con permisos."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Bandeja Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Health = cls.env['printflow.stock.health']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, managed=True):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': managed,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

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
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _open_tray(self, product, lot_state):
        """Abre la bandeja por el dispatcher y devuelve las filas pobladas."""
        action = self._wizard(product).action_run_pf_plan(lot_state, 'solution')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')
        self.assertEqual(action['target'], 'current')
        tray = self.Tray.search([('product_id', '=', product.id)])
        self.assertTrue(tray, 'La bandeja debe traer al menos una fila.')
        self.assertEqual(set(tray.mapped('lot_state')), {lot_state})
        return tray

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    def _mo_done_without_lot(self, product, origin=None):
        manu_type = self.warehouse.manu_type_id
        vals = {
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id
                or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id
                or self.stock_location.id),
        }
        if origin:
            vals['origin'] = origin
        mo = self.env['mrp.production'].create(vals)
        mo.write({'state': 'done'})
        return mo

    def _sale(self, product, qty=1.0):
        """Pedido SIN confirmar: solo aporta la línea para el lote exclusivo."""
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })

    def _sale_line(self, product, qty=1.0):
        """Pedido SIN confirmar: devuelve (orden, línea del producto)."""
        order = self._sale(product, qty)
        return order, order.order_line.filtered(
            lambda line: line.product_id == product)[:1]

    def _mixed(self, name):
        """Producto con UN lote (``<name>-L1``) usado por DOS pedidos."""
        product = self._product(name)
        lot = self._lot(product, '%s-L1' % name)
        self._stock(product, 10.0, lot=lot)
        _o1, line_1 = self._sale_line(product)
        _p1, move_1 = self._outgoing(product, 2.0, lot=lot)
        move_1.sale_line_id = line_1.id
        _o2, line_2 = self._sale_line(product)
        _p2, move_2 = self._outgoing(product, 2.0, lot=lot)
        move_2.sale_line_id = line_2.id
        return product, lot

    # ==================================================================
    # 1) lot_no_stock: la bandeja lista el DOCUMENTO (movimiento) y navega
    # ==================================================================
    def test_no_stock_tray_lists_move_and_navigates(self):
        product = self._product('BANDEJA NO STOCK')
        ghost = self._lot(product, 'BANDEJA-FANTASMA')
        picking, move = self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.res_id == move.id)[:1]
        self.assertTrue(row, 'Debe existir UNA fila por documento.')
        self.assertEqual(row.res_model, 'stock.move')
        self.assertEqual(row.kind, 'no_stock_lot')
        self.assertEqual(row.lot_name, ghost.name)
        self.assertEqual(row.picking_id, picking)
        self.assertEqual(row.partner_id, self.customer)
        self.assertTrue(row.remedy_target)
        # El tipo de LOTE (no OF sin lote) conserva "Elegir lote".
        self.assertTrue(row.can_choose_lot)

        nav = row.action_open()
        self.assertEqual(nav['type'], 'ir.actions.act_window')
        self.assertEqual(nav['res_model'], 'stock.move')
        self.assertEqual(nav['res_id'], move.id)

    # ==================================================================
    # 2) lot_generic: la bandeja lista el DOCUMENTO con el lote genérico
    # ==================================================================
    def test_generic_tray_lists_move_with_generic_lot(self):
        product = self._product('BANDEJA GENERICO')
        generic = self._lot(product, 'LOTE-GENERICO-BANDEJA')
        self._stock(product, 10.0, lot=generic)
        picking, move = self._outgoing(product, 2.0, lot=generic)

        tray = self._open_tray(product, 'lot_generic')
        row = tray.filtered(lambda r: r.res_id == move.id)[:1]
        self.assertTrue(row)
        self.assertEqual(row.res_model, 'stock.move')
        self.assertEqual(row.kind, 'generic_lot')
        self.assertEqual(row.lot_name, generic.name)
        self.assertEqual(row.picking_id, picking)
        # El tipo de LOTE (no OF sin lote) conserva "Elegir lote".
        self.assertTrue(row.can_choose_lot)

    # ==================================================================
    # 3) lot_unassigned_finished: la bandeja lista la MO sin lote
    # ==================================================================
    def test_unassigned_finished_tray_lists_mos(self):
        product = self._product('BANDEJA MO SIN LOTE')
        mo = self._mo_done_without_lot(product)
        self.assertFalse(mo.lot_producing_id)

        tray = self._open_tray(product, 'lot_unassigned_finished')
        self.assertIn(mo.id, tray.mapped('res_id'))
        row = tray.filtered(lambda r: r.res_id == mo.id)[:1]
        self.assertEqual(row.res_model, 'mrp.production')
        self.assertEqual(row.kind, 'unassigned_mo')

    # ==================================================================
    # 4) Aplicar corrección: guardia de permisos
    # ==================================================================
    def test_apply_without_permission_raises(self):
        product = self._product('BANDEJA PERMISO SIN')
        ghost = self._lot(product, 'BANDEJA-PERMISO-SIN')
        self._outgoing(product, 2.0, lot=ghost)
        tray = self._open_tray(product, 'lot_no_stock')

        user = self._user('pf_tray_no_perm', [self.env.ref('base.group_user')])
        with self.assertRaises(UserError):
            tray.with_user(user).action_apply_correction()

    def test_apply_with_permission_notifies(self):
        product = self._product('BANDEJA PERMISO CON')
        ghost = self._lot(product, 'BANDEJA-PERMISO-CON')
        self._outgoing(product, 2.0, lot=ghost)
        tray = self._open_tray(product, 'lot_no_stock')

        user = self._user('pf_tray_perm', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        action = tray.with_user(user).action_apply_correction()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertTrue(action['params']['message'])

    # ==================================================================
    # 5) PARIDAD producto<->pedido del remedio del terminado sin lote
    # ==================================================================
    def test_unassigned_finished_remedy_parity_product_vs_order(self):
        flow_lots = self.env['printflow.flow.lots']
        product_plan = flow_lots._pf_plan_for_state(
            'lot_unassigned_finished', 'product')
        order_plan = flow_lots._pf_plan_for_state(
            'lot_unassigned_finished', 'order')
        product_solution = product_plan['actions']['solution']
        order_solution = order_plan['actions']['solution']
        self.assertEqual(product_solution['target'], 'repair_finished_lot')
        self.assertEqual(product_solution['target'], order_solution['target'])
        self.assertEqual(product_solution['label'], order_solution['label'])

    # ==================================================================
    # 6) La bandeja del terminado sin lote apunta a repair_finished_lot
    # ==================================================================
    def test_unassigned_finished_tray_targets_repair(self):
        product = self._product('BANDEJA MO TARGET')
        self._mo_done_without_lot(product)
        tray = self._open_tray(product, 'lot_unassigned_finished')
        self.assertTrue(tray)
        self.assertEqual(
            set(tray.mapped('remedy_target')), {'repair_finished_lot'})

    # ==================================================================
    # 7) Efecto REAL: aplicar la corrección asigna el lote del terminado
    # ==================================================================
    def test_unassigned_finished_apply_repairs_lot(self):
        product = self._product('BANDEJA MO REPARA')
        order = self._sale(product)
        mo = self._mo_done_without_lot(product, origin=order.name)
        self.assertFalse(mo.lot_producing_id)
        tray = self._open_tray(product, 'lot_unassigned_finished')
        self.assertIn(mo.id, tray.mapped('res_id'))

        user = self._user('pf_tray_perm_repair', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        action = tray.with_user(user).action_apply_correction()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'success')

        mo.invalidate_recordset(['lot_producing_id'])
        self.assertTrue(
            mo.lot_producing_id,
            'La MO terminada sin lote debe quedar con lote tras reparar.')

    # ==================================================================
    # 8) OF terminada CON lote sugerido: el caso se resuelve con el
    #    remedio de cabecera (crear el sugerido); NO con "Elegir lote".
    # ==================================================================
    def test_unassigned_mo_with_suggested_lot_uses_header_remedy(self):
        product = self._product('BANDEJA MO SUGERIDO')
        order = self._sale(product)
        mo = self._mo_done_without_lot(product, origin=order.name)
        tray = self._open_tray(product, 'lot_unassigned_finished')
        row = tray.filtered(lambda r: r.res_id == mo.id)[:1]
        self.assertTrue(row)
        # Hay lote sugerido determinable: la vista OCULTA "Elegir lote".
        self.assertTrue(
            row.own_lot_name,
            'La OF con pedido debe tener un lote sugerido determinable.')
        # Y el remedio de cabecera del caso es crear/reparar el lote.
        self.assertEqual(row.remedy_target, 'repair_finished_lot')

    # ==================================================================
    # 9) OF terminada SIN lote sugerido: "Elegir lote" queda de emergencia
    # ==================================================================
    def test_unassigned_mo_without_suggested_lot_keeps_choose_lot(self):
        product = self._product('BANDEJA MO SIN SUGERIDO')
        mo = self._mo_done_without_lot(product)  # sin pedido -> sin sugerido
        tray = self._open_tray(product, 'lot_unassigned_finished')
        row = tray.filtered(lambda r: r.res_id == mo.id)[:1]
        self.assertTrue(row)
        self.assertFalse(
            row.own_lot_name,
            'Una OF sin pedido no tiene lote sugerido determinable.')
        # Sin lote sugerido, "Elegir lote" sigue disponible (emergencia).
        self.assertTrue(row.can_choose_lot)

    # ==================================================================
    # 10) Los demás tipos de la bandeja CONSERVAN "Elegir lote"
    #     (el paquete de soluciones por caso queda intacto)
    # ==================================================================
    def test_other_kinds_keep_choose_lot(self):
        missing_product = self._product('BANDEJA MANTIENE MISSING')
        self._outgoing(missing_product, 2.0, lot=None)
        missing = self._open_tray(missing_product, 'lot_missing')
        self.assertTrue(missing)
        self.assertTrue(all(row.can_choose_lot for row in missing))

        mixed_product, _lot = self._mixed('BANDEJA MANTIENE MIXED')
        mixed = self._open_tray(mixed_product, 'lot_mixed')
        self.assertTrue(mixed)
        self.assertTrue(all(row.can_choose_lot for row in mixed))

    # ==================================================================
    # 11) "Crear lote sugerido": crea por SELECCIÓN (varias filas marcadas)
    # ==================================================================
    def test_create_suggested_lots_on_selection(self):
        product = self._product('BANDEJA CREAR SELECCION')
        order_a = self._sale(product)
        order_b = self._sale(product)
        mo_a = self._mo_done_without_lot(product, origin=order_a.name)
        mo_b = self._mo_done_without_lot(product, origin=order_b.name)
        self.assertFalse(mo_a.lot_producing_id)
        self.assertFalse(mo_b.lot_producing_id)

        tray = self._open_tray(product, 'lot_unassigned_finished')
        rows = tray.filtered(lambda r: r.res_id in (mo_a.id, mo_b.id))
        self.assertEqual(len(rows), 2, 'Deben existir las DOS filas.')
        self.assertTrue(
            all(row.own_lot_name for row in rows),
            'Ambas OF con pedido deben tener lote sugerido determinable.')

        user = self._user('pf_tray_create_sel', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        action = rows.with_user(user).action_create_suggested_lots()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'success')

        mo_a.invalidate_recordset(['lot_producing_id'])
        mo_b.invalidate_recordset(['lot_producing_id'])
        self.assertTrue(
            mo_a.lot_producing_id,
            'La primera OF seleccionada debe quedar con lote sugerido.')
        self.assertTrue(
            mo_b.lot_producing_id,
            'La segunda OF seleccionada debe quedar con lote sugerido.')

    # ==================================================================
    # 12) "Crear lote sugerido": RESPETA la selección (candado clave)
    # ==================================================================
    def test_create_suggested_lots_respects_selection(self):
        product = self._product('BANDEJA CREAR SOLO UNA')
        orders = [self._sale(product) for _ in range(3)]
        mos = [self._mo_done_without_lot(product, origin=order.name)
               for order in orders]
        tray = self._open_tray(product, 'lot_unassigned_finished')
        rows = tray.filtered(lambda r: r.res_id in [mo.id for mo in mos])
        self.assertEqual(len(rows), 3, 'Deben existir las TRES filas.')

        user = self._user('pf_tray_create_one', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        chosen = rows[:1]
        action = chosen.with_user(user).action_create_suggested_lots()
        self.assertEqual(action['params']['type'], 'success')

        chosen_mo = next(mo for mo in mos if mo.id == chosen.res_id)
        chosen_mo.invalidate_recordset(['lot_producing_id'])
        self.assertTrue(
            chosen_mo.lot_producing_id,
            'La fila marcada debe quedar con lote sugerido.')
        for mo in mos:
            if mo.id == chosen.res_id:
                continue
            mo.invalidate_recordset(['lot_producing_id'])
            self.assertFalse(
                mo.lot_producing_id,
                'La acción NO debe tocar las filas no seleccionadas.')

    # ==================================================================
    # 13) "Crear lote sugerido": OMITE las filas no elegibles (sin sugerido)
    # ==================================================================
    def test_create_suggested_lots_omits_non_eligible(self):
        product = self._product('BANDEJA CREAR OMITE')
        mo = self._mo_done_without_lot(product)  # sin pedido -> sin sugerido
        tray = self._open_tray(product, 'lot_unassigned_finished')
        row = tray.filtered(lambda r: r.res_id == mo.id)[:1]
        self.assertTrue(row)
        self.assertFalse(row.own_lot_name)

        user = self._user('pf_tray_create_omit', [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])
        action = row.with_user(user).action_create_suggested_lots()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'warning')

        mo.invalidate_recordset(['lot_producing_id'])
        self.assertFalse(
            mo.lot_producing_id,
            'Una OF sin lote sugerido no debe recibir lote.')

    # ==================================================================
    # 14) "Crear lote sugerido": guardia de permisos
    # ==================================================================
    def test_create_suggested_lots_without_permission_raises(self):
        product = self._product('BANDEJA CREAR PERMISO')
        order = self._sale(product)
        mo = self._mo_done_without_lot(product, origin=order.name)
        tray = self._open_tray(product, 'lot_unassigned_finished')
        row = tray.filtered(lambda r: r.res_id == mo.id)[:1]
        self.assertTrue(row)

        user = self._user('pf_tray_create_noperm', [
            self.env.ref('base.group_user')])
        with self.assertRaises(UserError):
            row.with_user(user).action_create_suggested_lots()
        mo.invalidate_recordset(['lot_producing_id'])
        self.assertFalse(
            mo.lot_producing_id,
            'Sin permiso no se debe escribir el lote sugerido.')
