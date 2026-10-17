# -*- coding: utf-8 -*-
"""Reasignación de lote POR DOCUMENTO (PrintFlow · Huecos 1-3).

Custodia el diseño aprobado que corrige los huecos de la REASIGNACIÓN DE LOTE:

1. La bandeja lista UNA fila POR DOCUMENTO (``stock.move``) con su contexto de
   entrega (albarán/cliente), no una fila por lote.
2. Reasignar el lote de una entrega cambia SOLO esa entrega: no suelta el
   albarán (``do_unreserve`` global), así otra entrega con el mismo lote y otro
   producto del MISMO albarán conservan su reserva.
3. La excepción (elegir un lote distinto al esperado: propio o actual) exige
   confirmación + motivo y deja bitácora en el chatter.
4. El aviso de disponibilidad usa la libre EN la ubicación del documento: si no
   cubre la demanda exige ``confirm_partial`` (queda ``partially_available``);
   si es 0 en esa ubicación, bloquea.
5. Excepción neutra: si el documento NO tenía lote (ni propio ni actual),
   asignar uno NO es excepción (no pide motivo).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


@tagged('post_install', '-at_install')
class TestProductFlowLotReassignPerDocument(TransactionCase):
    """Una fila por documento; reasignación acotada; excepción y disponibilidad."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Reasigna Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Picker = cls.env['printflow.flow.lot.picker']
        # Política por defecto: exige confirmación + motivo (caso excepción).
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

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty, lot_id=lot)

    def _add_outgoing_move(self, picking, product, qty, lot):
        """Añade a ``picking`` un movimiento de salida con lote fijo (o sin lote)."""
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
        # Reserva nativa fuera: el test fija el lote EXACTO de su escenario.
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
        return move

    def _outgoing(self, product, qty=2.0, lot=None):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        move = self._add_outgoing_move(picking, product, qty, lot)
        return picking, move

    def _manager(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('mrp.group_mrp_manager').id,
            ])],
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

    def _picker_for(self, row):
        action = row.action_open_lot_picker()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.picker')
        return self.Picker.browse(action['res_id'])

    # ==================================================================
    # 1) UNA fila POR DOCUMENTO (stock.move) con su contexto de entrega
    # ==================================================================
    def test_lot_lists_one_row_per_document(self):
        product = self._product('PERDOC UNO')
        ghost = self._lot(product, 'PERDOC-UNO-FANTASMA')
        pick_a, move_a = self._outgoing(product, 2.0, lot=ghost)
        pick_b, move_b = self._outgoing(product, 3.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        rows = tray.filtered(lambda r: r.kind == 'no_stock_lot')
        self.assertEqual(len(rows), 2, 'Debe haber UNA fila por documento.')
        self.assertEqual(set(rows.mapped('res_model')), {'stock.move'})
        self.assertEqual(set(rows.mapped('res_id')), {move_a.id, move_b.id})
        self.assertEqual(set(rows.mapped('picking_id')), {pick_a, pick_b})
        self.assertEqual(set(rows.mapped('partner_id')), {self.customer})
        self.assertEqual(set(rows.mapped('lot_name')), {ghost.name})
        self.assertTrue(all(row.can_choose_lot for row in rows))

    # ==================================================================
    # 2) Reasignar cambia SOLO esa entrega (sin do_unreserve global)
    # ==================================================================
    def test_reassign_changes_only_that_delivery(self):
        product = self._product('PERDOC SOLO UNA')
        other_product = self._product('PERDOC OTRO PRODUCTO')
        ghost = self._lot(product, 'PERDOC-SOLO-FANTASMA')
        real = self._lot(product, 'PERDOC-SOLO-REAL')
        self._stock(product, 10.0, lot=real)
        other_lot = self._lot(other_product, 'PERDOC-OTRO-LOTE')
        self._stock(other_product, 5.0, lot=other_lot)

        # Albarán A: el movimiento del producto (lote fantasma) MÁS otro producto
        # que reserva su propio lote (lo que antes rompía el do_unreserve global).
        pick_a = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        move_a = self._add_outgoing_move(pick_a, product, 2.0, ghost)
        move_q = self._add_outgoing_move(pick_a, other_product, 3.0, other_lot)

        # Entrega B: MISMO producto y MISMO lote fantasma (no debe cambiar).
        _pick_b, move_b = self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.res_id == move_a.id)[:1]
        self.assertTrue(row)

        picker = self._picker_for(row)
        picker = picker.with_user(self._manager('pf_perdoc_una'))
        picker.lot_id = real.id
        picker.confirm_exception = True
        picker.exception_reason = 'Reuso del sobrante real.'
        picker.action_assign_lot()

        # La entrega reasignada cambia...
        self.assertIn(real, move_a.move_line_ids.mapped('lot_id'))
        self.assertNotIn(ghost, move_a.move_line_ids.mapped('lot_id'))
        # ...la OTRA entrega con el mismo lote queda INTACTA...
        self.assertIn(ghost, move_b.move_line_ids.mapped('lot_id'))
        self.assertNotIn(real, move_b.move_line_ids.mapped('lot_id'))
        # ...y el OTRO producto del mismo albarán conserva su reserva.
        self.assertIn(other_lot, move_q.move_line_ids.mapped('lot_id'))
        self.assertAlmostEqual(
            sum(move_q.move_line_ids.mapped('quantity')), 3.0)

    # ==================================================================
    # 3) Excepción: exige motivo y deja bitácora en el chatter
    # ==================================================================
    def test_exception_requires_reason_and_logs(self):
        product = self._product('PERDOC EXCEPCION')
        ghost = self._lot(product, 'PERDOC-EXC-FANTASMA')
        real = self._lot(product, 'PERDOC-EXC-REAL')
        self._stock(product, 10.0, lot=real)
        pick, move = self._outgoing(product, 2.0, lot=ghost)

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.res_id == move.id)[:1]
        picker = self._picker_for(row)
        picker = picker.with_user(self._manager('pf_perdoc_exc'))
        picker.lot_id = real.id
        self.assertTrue(picker.is_exception)
        # Sin confirmar -> error.
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        # Confirmado SIN motivo -> error (política confirm_reason).
        picker.confirm_exception = True
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        # Confirmado + motivo -> asigna y registra.
        picker.exception_reason = 'El cliente rechazó el trabajo.'
        result = picker.action_assign_lot()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(real, move.move_line_ids.mapped('lot_id'))
        self.assertTrue(any(
            'PERDOC-EXC-REAL' in (message.body or '')
            for message in pick.message_ids))

    # ==================================================================
    # 4a) Disponibilidad parcial: exige confirm_partial
    # ==================================================================
    def test_partial_availability_requires_confirm(self):
        product = self._product('PERDOC PARCIAL')
        ghost = self._lot(product, 'PERDOC-PARCIAL-FANTASMA')
        partial = self._lot(product, 'PERDOC-PARCIAL-REAL')
        self._stock(product, 1.0, lot=partial)
        _pick, move = self._outgoing(product, 2.0, lot=ghost)
        # Aísla el aviso de disponibilidad de la fricción de excepción.
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'warn')

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.res_id == move.id)[:1]
        picker = self._picker_for(row)
        self.assertAlmostEqual(picker.demand_qty, 2.0)
        picker = picker.with_user(self._manager('pf_perdoc_parcial'))
        picker.lot_id = partial.id
        # 0 < libre(1) < demanda(2) y sin el check -> error.
        with self.assertRaises(UserError):
            picker.action_assign_lot()
        # Con el check -> asigna lo disponible y la entrega queda parcial.
        picker.confirm_partial = True
        picker.action_assign_lot()
        self.assertEqual(move.state, 'partially_available')
        self.assertIn(partial, move.move_line_ids.mapped('lot_id'))
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 1.0)

    # ==================================================================
    # 4b) Lote con 0 en la ubicación del documento -> bloqueo
    # ==================================================================
    def test_lot_with_zero_here_is_blocked(self):
        product = self._product('PERDOC CERO')
        ghost = self._lot(product, 'PERDOC-CERO-FANTASMA')
        elsewhere = self._lot(product, 'PERDOC-CERO-AJENA')
        # Otra ubicación interna (fuera del stock de la entrega).
        other_location = self.env['stock.location'].create({
            'name': 'PERDOC OTRA UBIC', 'usage': 'internal',
            'location_id': self.warehouse.view_location_id.id,
        })
        self._stock(product, 5.0, lot=elsewhere, location=other_location)
        _pick, move = self._outgoing(product, 2.0, lot=ghost)
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_EXCEPTION_POLICY, 'warn')

        tray = self._open_tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.res_id == move.id)[:1]
        picker = self._picker_for(row)
        picker = picker.with_user(self._manager('pf_perdoc_cero'))
        # El lote tiene existencia, pero NO en la ubicación del documento.
        picker.lot_id = elsewhere.id
        with self.assertRaises(UserError):
            picker.action_assign_lot()

    # ==================================================================
    # 5) Excepción neutra: sin lote previo NO pide motivo
    # ==================================================================
    def test_neutral_assignment_without_previous_lot_does_not_ask_reason(self):
        product = self._product('PERDOC NEUTRO')
        real = self._lot(product, 'PERDOC-NEUTRO-REAL')
        self._stock(product, 10.0, lot=real)
        # Movimiento SIN lote con destino cliente -> ``lot_missing``.
        _pick, move = self._outgoing(product, 2.0, lot=None)

        tray = self._open_tray(product, 'lot_missing')
        row = tray.filtered(lambda r: r.res_id == move.id)[:1]
        self.assertTrue(row)
        picker = self._picker_for(row)
        self.assertFalse(picker.own_lot_name)
        self.assertFalse(picker.lot_name_actual)
        picker = picker.with_user(self._manager('pf_perdoc_neutro'))
        picker.lot_id = real.id
        self.assertFalse(picker.is_exception, 'Sin lote previo NO es excepción.')
        # No debe exigir motivo ni confirmación.
        picker.action_assign_lot()
        self.assertIn(real, move.move_line_ids.mapped('lot_id'))
