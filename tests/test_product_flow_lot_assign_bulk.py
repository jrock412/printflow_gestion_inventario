# -*- coding: utf-8 -*-
"""Asignación de UN lote EN BLOQUE desde la bandeja (PrintFlow · H-021).

Custodia los criterios CA-2/CA-3/CA-4/CA-5/CA-6/CA-7/CA-9 del plan de
"ASIGNACIÓN DE LOTE EN BLOQUE desde la bandeja":

* **CA-2** — con N filas de entrega sin lote seleccionadas, el botón de cabecera
  abre UN solo wizard (``printflow.flow.lot.assign.bulk``) que muestra producto,
  demanda SUMADA, la tabla de candidatos (Lote · Existencia · Reservado ·
  Disponible · Rol) y la lista de destinos; al ejecutar con UN motivo, TODOS los
  destinos asignables quedan reservados con el lote elegido.
* **CA-3** — las filas NO asignables (otros tipos) se OMITEN y su conteo se
  reporta: no abortan el resto.
* **CA-4** — si ``libre < total_demand`` y NO se marcó "Confirmo la asignación
  parcial" se bloquea con mensaje guía y NO se escribe; con el check se asigna lo
  disponible y se reporta.
* **CA-5** — sin jefe de taller/administrador, ABRIR y EJECUTAR lanzan
  ``UserError`` (``_pf_assert_can_clean``).
* **CA-6** — sin ``reason`` ejecutar lanza ``UserError``; con política ≠ ``warn``,
  sin ``confirm_exception`` también.
* **CA-7** — la notificación informa "N asignadas · P parciales · K omitidas ·
  E con error"; al REABRIR la bandeja las órdenes resueltas YA NO se listan.
* **CA-9** — dos filas de la MISMA entrega (``missing_move`` + ``pending_order``)
  producen UNA sola asignación y el duplicado se reporta como omitido.

Es de SOLO LECTURA sobre datos ajenos salvo la ÚNICA escritura del flujo (la
reasignación NATIVA de reserva que dispara el wizard con su guardia y su motivo):
crea sus propios productos/albaranes y ``TransactionCase`` hace rollback.
"""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

# Configuración de nodos de pendientes (0 = sin tope): hace DETERMINISTA el
# número de filas ``pending_order`` que la bandeja produce.
PARAM_NODE_PENDING_LIMIT = (
    'x_product_dimensional_pricing.pf_node_pending_limit')
PARAM_NODE_PENDING_ENABLED = (
    'x_product_dimensional_pricing.pf_node_pending_enabled')
PARAM_NODE_PENDING_NODES = (
    'x_product_dimensional_pricing.pf_node_pending_nodes')
# Política de asignación por excepción (cero hardcodeo): se fija en ``warn``
# para que la única fricción de los casos base sea la que cada test monta.
PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


@tagged('post_install', '-at_install')
class TestProductFlowLotAssignBulk(TransactionCase):
    """El wizard en bloque asigna UN lote a la SELECCIÓN (con guardia y motivo)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Asignacion Bloque'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Bulk = cls.env['printflow.flow.lot.assign.bulk']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        # Determinismo de la bandeja (transitorio: vive en la transacción).
        cls.ICP.set_param(PARAM_NODE_PENDING_ENABLED, '1')
        cls.ICP.set_param(PARAM_NODE_PENDING_NODES,
                          'purchase,receipt,production,delivery,sale')
        cls.ICP.set_param(PARAM_NODE_PENDING_LIMIT, '0')
        cls.ICP.set_param(PARAM_EXCEPTION_POLICY, 'warn')

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

    def _outgoing(self, product, qty=2.0, lot=None, with_line=False):
        """Albarán de salida confirmado (con o sin ``move_line``).

        Se confirma ANTES de que exista existencia (Odoo no reserva por su
        cuenta) y con ``with_line=False`` el movimiento queda SIN reserva ⇒ la
        bandeja produce la fila ``pending_order`` de la ORDEN.
        """
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
        if with_line:
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

    def _open_tray(self, product, lot_state='lot_missing'):
        """Abre la bandeja por el dispatcher (misma ruta que el operador)."""
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        return self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])

    def _wizard_for(self, selection):
        """Abre el wizard en bloque desde la acción sobre la SELECCIÓN."""
        action = selection.action_assign_lot_bulk()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.assign.bulk')
        self.assertEqual(action['target'], 'new')
        return self.Bulk.browse(action['res_id'])

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    def _manager(self, login):
        return self._user(login, [
            self.env.ref('base.group_user'),
            self.env.ref('mrp.group_mrp_manager'),
        ])

    # ==================================================================
    # CA-2 — el wizard asigna UN lote a TODA la selección
    # ==================================================================
    def test_ca2_bulk_assigns_lot_to_all_destinations(self):
        product = self._product('BULK CA2')
        lot = self._lot(product, 'BULK-CA2-LOTE')
        pick_a, move_a = self._outgoing(product, 2.0)
        pick_b, move_b = self._outgoing(product, 4.0)
        self._stock(product, 10.0, lot=lot)

        tray = self._open_tray(product)
        pending = tray.filtered(lambda r: r.kind == 'pending_order')
        self.assertEqual(set(pending.mapped('res_id')), {pick_a.id, pick_b.id})

        bulk = self._wizard_for(pending)

        # (a) el wizard muestra producto, demanda SUMADA y los destinos.
        self.assertEqual(bulk.product_id, product)
        self.assertAlmostEqual(bulk.total_demand, 6.0)
        self.assertEqual(bulk.assignable_count, 2)
        self.assertEqual(len(bulk.line_ids), 2)
        self.assertEqual(
            set(bulk.line_ids.mapped('move_id')), {move_a, move_b})

        # (b) la tabla de candidatos trae el lote con su info de disponibilidad.
        candidate = bulk.candidate_ids.filtered(lambda c: c.lot_id == lot)
        self.assertTrue(candidate, 'El lote con existencia debe ser candidato.')
        self.assertAlmostEqual(candidate.available, 10.0)
        self.assertAlmostEqual(candidate.reserved, 0.0)
        self.assertTrue(candidate.is_elective, 'Con libre > 0 es elegible.')
        self.assertIn(lot, bulk.candidate_lot_ids)

        # (c) ejecutar con UN motivo reserva el lote en TODOS los destinos.
        bulk.lot_id = lot.id
        bulk.reason = 'Asignación masiva de prueba.'
        result = bulk.action_assign_lot_bulk()

        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('2 asignadas', result['params']['message'])
        self.assertEqual(set(bulk.line_ids.mapped('result')), {'assigned'})
        self.assertIn(lot, move_a.move_line_ids.mapped('lot_id'))
        self.assertIn(lot, move_b.move_line_ids.mapped('lot_id'))
        self.assertAlmostEqual(
            sum(move_a.move_line_ids.mapped('quantity')), 2.0)
        self.assertAlmostEqual(
            sum(move_b.move_line_ids.mapped('quantity')), 4.0)

    def test_ca2_without_assignable_rows_notifies_without_wizard(self):
        """Sin filas asignables no se abre un wizard vacío."""
        product = self._product('BULK CA2 VACIO')
        lot = self._lot(product, 'BULK-CA2-VACIO-LOTE')
        self._stock(product, 5.0, lot=lot)
        row = self.Tray.create({
            'product_id': product.id,
            'lot_state': 'lot_missing',
            'kind': 'orphan_quant',
            'res_model': 'stock.quant',
            'res_id': 0,
            'can_choose_lot': False,
            'lot_id': lot.id,
        })

        action = row.action_assign_lot_bulk()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')

    # ==================================================================
    # CA-3 — las filas NO asignables se OMITEN y se reportan
    # ==================================================================
    def test_ca3_non_assignable_rows_are_omitted(self):
        product = self._product('BULK CA3')
        lot = self._lot(product, 'BULK-CA3-LOTE')
        _pick, move = self._outgoing(product, 3.0)
        self._stock(product, 10.0, lot=lot)

        tray = self._open_tray(product)
        pending = tray.filtered(lambda r: r.kind == 'pending_order')
        self.assertTrue(pending)
        # Fila NO asignable (tipo fuera de la lista blanca) en la MISMA selección.
        # Se crea DESPUÉS de poblar la bandeja: ``_pf_populate`` limpia las filas
        # previas del producto+estado, así que una fila previa sería eliminada.
        extra = self.Tray.create({
            'product_id': product.id,
            'lot_state': 'lot_missing',
            'kind': 'unassigned_mo',
            'res_model': 'mrp.production',
            'res_id': 0,
            'can_choose_lot': True,
        })

        bulk = self._wizard_for(pending | extra)

        # Solo el destino asignable entra; el resto se OMITE y se cuenta.
        self.assertEqual(bulk.assignable_count, 1)
        self.assertEqual(len(bulk.line_ids), 1)
        self.assertEqual(bulk.omitted_count, 1)
        # La fila es la dimensión OPERATIVA (la ORDEN): su ``res_id`` es el
        # albarán; el movimiento resuelto viaja en ``move_id``.
        self.assertEqual(set(bulk.line_ids.mapped('res_id')), {_pick.id})
        self.assertEqual(set(bulk.line_ids.mapped('move_id')), {move})

    # ==================================================================
    # CA-4 — la asignación PARCIAL exige confirmación explícita
    # ==================================================================
    def test_ca4_partial_requires_confirmation(self):
        product = self._product('BULK CA4')
        lot = self._lot(product, 'BULK-CA4-LOTE')
        _pick, move = self._outgoing(product, 5.0)
        self._stock(product, 2.0, lot=lot)

        tray = self._open_tray(product)
        bulk = self._wizard_for(
            tray.filtered(lambda r: r.kind == 'pending_order'))
        self.assertAlmostEqual(bulk.total_demand, 5.0)
        bulk.lot_id = lot.id
        bulk.reason = 'Reparto de lo disponible.'

        # libre (2) < demanda (5) y sin el check -> bloquea y NO escribe.
        with self.assertRaises(UserError):
            bulk.action_assign_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))

        # Con el check -> asigna lo disponible y lo reporta como parcial.
        bulk.confirm_partial = True
        result = bulk.action_assign_lot_bulk()
        self.assertIn('1 parciales', result['params']['message'])
        self.assertEqual(set(bulk.line_ids.mapped('result')), {'partial'})
        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 2.0)

    def test_ca4_scarce_lot_reports_error_on_starved_destination(self):
        """Un lote que se agota tras el primer destino se REPORTA (no revienta)."""
        product = self._product('BULK CA4 ESCASO')
        lot = self._lot(product, 'BULK-CA4-ESCASO-LOTE')
        pick_a, move_a = self._outgoing(product, 3.0)
        pick_b, move_b = self._outgoing(product, 3.0)
        self._stock(product, 2.0, lot=lot)

        tray = self._open_tray(product)
        pending = tray.filtered(lambda r: r.kind == 'pending_order')
        self.assertEqual(set(pending.mapped('res_id')), {pick_a.id, pick_b.id})
        bulk = self._wizard_for(pending)
        bulk.lot_id = lot.id
        bulk.reason = 'Reparto FIFO del sobrante.'
        bulk.confirm_partial = True

        result = bulk.action_assign_lot_bulk()

        self.assertEqual(result['type'], 'ir.actions.client')
        results = set(bulk.line_ids.mapped('result'))
        self.assertIn('partial', results)
        self.assertIn('error', results)
        # El primer destino (FIFO) se queda con lo disponible; el otro se reporta.
        self.assertAlmostEqual(
            sum(move_a.move_line_ids.mapped('quantity')), 2.0)
        self.assertFalse(move_b.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # CA-5 — permisos: abrir y ejecutar exigen jefe de taller/admin
    # ==================================================================
    def test_ca5_permission_denied_on_open_and_execute(self):
        product = self._product('BULK CA5')
        lot = self._lot(product, 'BULK-CA5-LOTE')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 10.0, lot=lot)
        user = self._user('pf_bulk_assign_inv', [self.env.ref('base.group_user')])

        rows = self._open_tray(product).filtered(
            lambda r: r.kind == 'pending_order')
        self.assertTrue(rows)
        # ABRIR: la acción de la bandeja exige la guardia de permisos.
        with self.assertRaises(UserError):
            rows.with_user(user).action_assign_lot_bulk()

        # EJECUTAR: el wizard vuelve a exigir la misma guardia.
        bulk = self._wizard_for(rows)
        bulk.lot_id = lot.id
        bulk.reason = 'Intento sin permiso.'
        with self.assertRaises(UserError):
            bulk.with_user(user).action_assign_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))
        self.assertEqual(self.Bulk.search_count([]), 1)

    # ==================================================================
    # CA-6 — motivo obligatorio y política de excepción
    # ==================================================================
    def test_ca6_reason_is_mandatory(self):
        product = self._product('BULK CA6 MOTIVO')
        lot = self._lot(product, 'BULK-CA6-MOTIVO-LOTE')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 10.0, lot=lot)

        rows = self._open_tray(product).filtered(
            lambda r: r.kind == 'pending_order')
        bulk = self._wizard_for(rows)
        bulk.lot_id = lot.id
        self.assertFalse(bulk.reason)
        with self.assertRaises(UserError):
            bulk.action_assign_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))

        bulk.reason = 'Motivo válido.'
        bulk.action_assign_lot_bulk()
        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))

    def test_ca6_policy_requires_exception_check(self):
        product = self._product('BULK CA6 POLITICA')
        lot = self._lot(product, 'BULK-CA6-POLITICA-LOTE')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 10.0, lot=lot)
        self.ICP.set_param(PARAM_EXCEPTION_POLICY, 'confirm_reason')

        rows = self._open_tray(product).filtered(
            lambda r: r.kind == 'pending_order')
        bulk = self._wizard_for(rows)
        bulk.lot_id = lot.id
        bulk.reason = 'Motivo con política estricta.'
        # Política ≠ ``warn`` sin el check -> bloquea.
        with self.assertRaises(UserError):
            bulk.action_assign_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))

        bulk.confirm_exception = True
        bulk.action_assign_lot_bulk()
        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # CA-7 — la notificación reporta y la bandeja ya no lista lo resuelto
    # ==================================================================
    def test_ca7_results_and_resolved_orders_disappear(self):
        product = self._product('BULK CA7')
        lot = self._lot(product, 'BULK-CA7-LOTE')
        pick_a, move_a = self._outgoing(product, 2.0)
        pick_b, move_b = self._outgoing(product, 3.0)
        self._stock(product, 10.0, lot=lot)

        rows = self._open_tray(product).filtered(
            lambda r: r.kind == 'pending_order')
        self.assertEqual(set(rows.mapped('res_id')), {pick_a.id, pick_b.id})
        bulk = self._wizard_for(rows)
        bulk.lot_id = lot.id
        bulk.reason = 'Cierre de la asignación.'
        result = bulk.action_assign_lot_bulk()

        message = result['params']['message']
        self.assertIn('2 asignadas', message)
        self.assertIn('0 parciales', message)
        self.assertIn('0 omitidas', message)
        self.assertIn('0 con error', message)

        # Al REABRIR la bandeja, las órdenes resueltas YA NO se listan.
        self.Tray._pf_populate(product, 'lot_missing')
        pending = self.Tray.search([
            ('product_id', '=', product.id),
            ('kind', '=', 'pending_order'),
        ])
        self.assertNotIn(pick_a.id, pending.mapped('res_id'))
        self.assertNotIn(pick_b.id, pending.mapped('res_id'))
        self.assertIn(lot, move_a.move_line_ids.mapped('lot_id'))
        self.assertIn(lot, move_b.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # CA-9 — dos filas de la MISMA entrega producen UNA sola asignación
    # ==================================================================
    def test_ca9_duplicate_destination_is_reported_as_omitted(self):
        product = self._product('BULK CA9')
        lot = self._lot(product, 'BULK-CA9-LOTE')
        # Movimiento sin lote CON move line sin lote ⇒ la bandeja produce DOS
        # filas para la MISMA entrega: ``missing_move`` (evidencia técnica) y
        # ``pending_order`` (dimensión operativa).
        pick, move = self._outgoing(product, 3.0, with_line=True)
        self._stock(product, 10.0, lot=lot)

        tray = self._open_tray(product)
        missing = tray.filtered(
            lambda r: r.kind == 'missing_move' and r.res_id == move.id)
        pending = tray.filtered(
            lambda r: r.kind == 'pending_order' and r.res_id == pick.id)
        self.assertTrue(missing)
        self.assertTrue(pending)

        bulk = self._wizard_for(missing | pending)

        # Una sola asignación (el duplicado se OMITE y se reporta).
        self.assertEqual(len(bulk.line_ids), 1)
        self.assertEqual(bulk.line_ids.move_id, move)
        self.assertGreaterEqual(bulk.omitted_count, 1)

        bulk.lot_id = lot.id
        bulk.reason = 'Dedupe por movimiento.'
        result = bulk.action_assign_lot_bulk()
        self.assertIn('1 asignadas', result['params']['message'])
        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))
