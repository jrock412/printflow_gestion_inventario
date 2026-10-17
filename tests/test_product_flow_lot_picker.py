# -*- coding: utf-8 -*-
"""Selector de lote por DOCUMENTO de la bandeja gestionable (PrintFlow).

Custodia el flujo de DECISIÓN CONSCIENTE: desde una fila de la bandeja de lote
(p. ej. ``lot_no_stock`` de Entrega) el operador ABRE el selector, VE los lotes
con existencia (el lote sin stock NO aparece) y ASIGNA el elegido; el movimiento
queda con ese lote. Sin permiso (jefe de taller/administrador) -> ``UserError``.
La reserva huérfana NO admite elección de lote.

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotPicker(TransactionCase):
    """El selector lista candidatos y asigna el lote elegido al documento."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Picker Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Picker = cls.env['printflow.flow.lot.picker']

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
        # Odoo 17 reserva al confirmar por defecto (reservation_method
        # 'at_confirm'): la reserva nativa tomaría el lote REAL (el único con
        # existencia) y contaminaría el escenario. La soltamos para dejar SOLO
        # la línea con el lote fantasma que el test necesita.
        move.move_line_ids.unlink()
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

    def _mo_done_without_lot(self, product):
        manu_type = self.warehouse.manu_type_id
        mo = self.env['mrp.production'].create({
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
        mo.write({'state': 'done'})
        return mo

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    def _open_tray(self, product, lot_state):
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        tray = self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])
        self.assertTrue(tray, 'La bandeja debe traer al menos una fila.')
        return tray

    def _picker_from_row(self, row):
        action = row.action_open_lot_picker()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.picker')
        return self.Picker.browse(action['res_id'])

    def _manager(self, login):
        return self._user(login, [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager')])

    # ==================================================================
    # 1) El selector lista candidatos y asigna el lote elegido (Entrega)
    # ==================================================================
    def test_picker_lists_candidates_and_assigns_chosen_lot(self):
        product = self._product('PICKER NO STOCK')
        real_lot = self._lot(product, 'PICKER-REAL')
        self._stock(product, 10.0, lot=real_lot)
        ghost = self._lot(product, 'PICKER-FANTASMA')
        _picking, move = self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        self.assertTrue(row)
        picker = self._picker_from_row(row)

        # Candidatos: el lote con existencia SÍ; el lote ACTUAL (fantasma) ahora
        # se FUERZA en la tabla (con 0, para que el operador lo vea), pero NO es
        # elegible.
        cand_ids = picker.candidate_ids.mapped('lot_id')
        self.assertIn(real_lot, cand_ids)
        self.assertIn(ghost, cand_ids)
        ghost_cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == ghost)[:1]
        self.assertFalse(ghost_cand.is_elective)
        cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == real_lot)[:1]
        self.assertAlmostEqual(cand.available, 10.0)
        self.assertTrue(cand.location_names)

        user = self._manager('pf_picker_ok')
        picker = picker.with_user(user)
        cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == real_lot)[:1]
        cand.is_selected = True
        self.assertEqual(picker.lot_id, real_lot)
        # El documento tenía el lote fantasma (actual): elegir otro es excepción.
        self.assertTrue(picker.is_exception)
        picker.confirm_exception = True
        picker.exception_reason = 'Reasignación autorizada (prueba).'
        result = picker.action_assign_lot()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        # El movimiento queda con el lote ELEGIDO.
        self.assertIn(real_lot, move.move_line_ids.mapped('lot_id'))
        self.assertNotIn(ghost, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # 2) Sin permiso -> UserError (no se toca el inventario)
    # ==================================================================
    def test_picker_without_permission_raises(self):
        product = self._product('PICKER SIN PERMISO')
        real_lot = self._lot(product, 'PICKER-SP-REAL')
        self._stock(product, 10.0, lot=real_lot)
        ghost = self._lot(product, 'PICKER-SP-FANTASMA')
        self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        picker = self._picker_from_row(row)

        user = self._user(
            'pf_picker_no_perm', [self.env.ref('base.group_user')])
        picker = picker.with_user(user)
        picker.lot_id = real_lot.id
        with self.assertRaises(UserError):
            picker.action_assign_lot()

    # ==================================================================
    # 3) Fabricación: el lote ELEGIDO se asigna al terminado de la MO
    # ==================================================================
    def test_mo_picker_assigns_chosen_lot(self):
        product = self._product('PICKER MO')
        chosen = self._lot(product, 'PICKER-MO-ELEGIDO')
        self._stock(product, 5.0, lot=chosen)
        mo = self._mo_done_without_lot(product)
        self.assertFalse(mo.lot_producing_id)

        tray = self._open_tray(product, 'lot_unassigned_finished')
        row = tray.filtered(lambda r: r.res_model == 'mrp.production')[:1]
        self.assertTrue(row)
        picker = self._picker_from_row(row)

        picker = picker.with_user(self._manager('pf_picker_mo'))
        picker.lot_id = chosen.id
        picker.action_assign_lot()
        self.assertEqual(mo.lot_producing_id, chosen)

    # ==================================================================
    # 4) La reserva huérfana NO admite elección de lote
    # ==================================================================
    def test_orphan_row_has_no_picker(self):
        product = self._product('PICKER HUERFANA')
        self._stock(product, 0.0, lot=None, reserved=5.0)

        tray = self._open_tray(product, 'lot_orphan_reservation')
        row = tray.filtered(lambda r: r.kind == 'orphan_quant')[:1]
        self.assertTrue(row)
        with self.assertRaises(UserError):
            row.action_open_lot_picker()
        # El botón está OCULTO para la reserva huérfana (defensa también en XML).
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree').arch
        self.assertIn("kind == 'orphan_quant'", arch)

    # ==================================================================
    # 5) Causa raíz: sin elegir candidato el selector NO tiene lote
    #    (la tabla era solo evidencia, desconectada del campo de decisión).
    # ==================================================================
    def test_assign_without_choosing_lot_raises(self):
        product = self._product('PICKER SIN ELECCION')
        real_lot = self._lot(product, 'PICKER-SE-REAL')
        self._stock(product, 10.0, lot=real_lot)
        ghost = self._lot(product, 'PICKER-SE-FANTASMA')
        self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        picker = self._picker_from_row(row)
        picker = picker.with_user(self._manager('pf_picker_sin_eleccion'))

        # Sin elegir nada: `lot_id` vacío -> asignar es imposible (UserError).
        self.assertFalse(picker.lot_id)
        with self.assertRaises(UserError):
            picker.action_assign_lot()

    # ==================================================================
    # 6) El CHECK de la fila cierra la brecha evidencia -> decisión:
    #    marca `is_selected`, espeja `lot_id` y luego se puede asignar.
    # ==================================================================
    def test_candidate_check_selects_and_assigns_lot(self):
        product = self._product('PICKER CHECK')
        real_lot = self._lot(product, 'PICKER-CHECK-REAL')
        self._stock(product, 10.0, lot=real_lot)
        ghost = self._lot(product, 'PICKER-CHECK-FANTASMA')
        _picking, move = self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        picker = self._picker_from_row(row)

        picker = picker.with_user(self._manager('pf_picker_check'))
        cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == real_lot)[:1]
        self.assertTrue(cand)
        self.assertFalse(cand.is_selected)
        self.assertFalse(cand.is_picked)

        # Marcar el check elige la fila y espeja el lote en el selector.
        cand.is_selected = True
        self.assertTrue(cand.is_selected)
        self.assertTrue(cand.is_picked)
        self.assertEqual(picker.lot_id, real_lot)

        # El documento tenía el lote fantasma: elegir otro es excepción.
        picker.confirm_exception = True
        picker.exception_reason = 'Reasignación autorizada (prueba).'
        # Y ahora la asignación (con permiso) funciona de punta a punta.
        result = picker.action_assign_lot()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(real_lot, move.move_line_ids.mapped('lot_id'))
        self.assertNotIn(ghost, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # 7) La selección es ÚNICA: marcar dos filas deja solo la última.
    # ==================================================================
    def test_candidate_selection_is_single(self):
        product = self._product('PICKER UNICA SELECCION')
        lot_a = self._lot(product, 'PICKER-US-A')
        lot_b = self._lot(product, 'PICKER-US-B')
        self._stock(product, 10.0, lot=lot_a)
        self._stock(product, 6.0, lot=lot_b)
        ghost = self._lot(product, 'PICKER-US-FANTASMA')
        self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        picker = self._picker_from_row(row)

        cand_a = picker.candidate_ids.filtered(
            lambda c: c.lot_id == lot_a)[:1]
        cand_b = picker.candidate_ids.filtered(
            lambda c: c.lot_id == lot_b)[:1]
        self.assertTrue(cand_a)
        self.assertTrue(cand_b)

        cand_a.is_selected = True
        self.assertTrue(cand_a.is_selected)
        self.assertEqual(picker.lot_id, lot_a)

        # Marcar la segunda desmarca la primera y espeja el nuevo lote.
        cand_b.is_selected = True
        self.assertTrue(cand_b.is_selected)
        self.assertFalse(cand_a.is_selected)
        self.assertEqual(picker.lot_id, lot_b)
        self.assertEqual(picker.candidate_ids.filtered('is_selected'), cand_b)

    # ==================================================================
    # 8) Más de una fila marcada (dato forzado fuera del write) -> UserError.
    #    Defensa del selector: la tabla debe tener UNA sola marca.
    # ==================================================================
    def test_more_than_one_selected_raises(self):
        product = self._product('PICKER DOBLE MARCA')
        lot_a = self._lot(product, 'PICKER-DM-A')
        lot_b = self._lot(product, 'PICKER-DM-B')
        self._stock(product, 10.0, lot=lot_a)
        self._stock(product, 6.0, lot=lot_b)
        ghost = self._lot(product, 'PICKER-DM-FANTASMA')
        self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        picker = self._picker_from_row(row)
        picker = picker.with_user(self._manager('pf_picker_doble'))

        # ``create`` no pasa por el write que desmarca hermanas: fuerza DOS marcas.
        cand_model = self.env['printflow.flow.lot.candidate']
        for lot in (lot_a, lot_b):
            cand_model.create({
                'picker_id': picker.id, 'lot_id': lot.id,
                'lot_name': lot.name, 'is_selected': True,
            })
        self.assertEqual(
            len(picker.candidate_ids.filtered('is_selected')), 2)
        with self.assertRaises(UserError):
            picker.action_assign_lot()

    # ==================================================================
    # 9) Elegir con el check NO evade el guardia: sin permiso -> UserError
    # ==================================================================
    def test_candidate_check_without_permission_raises(self):
        product = self._product('PICKER CHECK SIN PERMISO')
        real_lot = self._lot(product, 'PICKER-CHECK-SP-REAL')
        self._stock(product, 10.0, lot=real_lot)
        ghost = self._lot(product, 'PICKER-CHECK-SP-FANTASMA')
        self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        picker = self._picker_from_row(row)

        user = self._user(
            'pf_picker_check_no_perm', [self.env.ref('base.group_user')])
        picker = picker.with_user(user)
        cand = picker.candidate_ids.filtered(
            lambda c: c.lot_id == real_lot)[:1]
        cand.is_selected = True  # elegir SÍ se puede (no toca inventario)
        self.assertEqual(picker.lot_id, real_lot)
        with self.assertRaises(UserError):
            picker.action_assign_lot()  # asignar exige jefe de taller/admin

    # ==================================================================
    # 10) Guardia de vista: la tabla ofrece el CHECK de selección y es
    #     editable (un booleano solo se marca en una lista editable).
    # ==================================================================
    def test_candidate_tree_has_selection_check(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_candidate_view_tree').arch
        self.assertIn('name="is_selected"', arch)
        self.assertIn('editable="bottom"', arch)
        self.assertNotIn('action_pick_lot', arch)

    # ==================================================================
    # 11) Guardia de vista: el selector DEBE ser editable
    #    (con edit="false" Odoo 17 abre el registro en readonly y el
    #    desplegable/la confirmación de excepción quedan inservibles).
    # ==================================================================
    def test_picker_form_is_editable(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_picker_view_form').arch
        self.assertNotIn('edit="false"', arch)
        self.assertNotIn("edit='false'", arch)
        self.assertIn('name="lot_id"', arch)
