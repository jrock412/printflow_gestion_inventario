# -*- coding: utf-8 -*-
"""REPARTO MULTI-LOTE en bloque desde la bandeja (PrintFlow · H-037 / H-036).

Custodia los criterios CA-1..CA-8 del plan "REPARTO multi-lote" (Sección 3 del
CONTEXT.md): el modo ``split`` de ``printflow.flow.lot.assign.bulk`` permite
marcar VARIOS lotes con la columna "Incluir" y repartir la demanda de las
entregas sin lote de UNA sola pasada, de forma ADITIVA por la vía NATIVA (UNA
liberación + N reservas), sin perder ningún lote.

* **CA-1** (reparto multi-lote) — con 2+ lotes marcados, UNA corrida deja TODOS
  los lotes reservados: un destino cuya demanda exige 2 lotes queda con 2
  ``stock.move.line`` (una por lote) y con la reserva completa (``assigned``).
* **CA-2** (H-036 · multi-tick) — ``is_in_split`` es INDEPENDIENTE por fila
  (varios ticks conviven); la selección ÚNICA de ``is_selected`` sigue intacta.
* **CA-3** (parcial) — sin el check "Confirmo la asignación parcial" y con
  ``Suma libre < demanda`` lanza ``UserError`` SIN escribir; con el check reparte lo
  disponible y reporta el desglose en ``result_note``.
* **CA-4** (orden declarado) — el reparto consume los lotes en el orden de la
  tabla (``available desc, lot_name asc``): primero el de más disponible, y el
  ``split_note`` VISIBLE coincide con el orden aplicado.
* **CA-5** (reporte intacto) — la acción conserva los 4 conteos, la
  ``display_notification`` y el ``params['next']`` al detalle por destino
  (``printflow.flow.lot.assign.bulk.result``), con una fila por destino.
* **CA-6** (guardia · motivo · política) — sin jefe de taller/administrador,
  ABRIR y EJECUTAR lanzan ``UserError``; sin ``reason`` también; con política ≠
  ``warn`` sin ``confirm_exception`` también.
* **CA-8** (no apilar sobre lo en curso) — un movimiento ``picked`` no recibe
  reservas nuevas: el destino se reporta con ``error`` y motivo honesto.

Es de SOLO LECTURA sobre datos ajenos salvo la ÚNICA escritura del flujo (la
reserva ADITIVA NATIVA que dispara el wizard con su guardia y su motivo): crea sus
propios productos/albaranes y ``TransactionCase`` hace rollback.
"""

import os

from odoo.exceptions import UserError
from odoo.modules.module import get_module_path
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

# Vista del form del MODO reparto: la acción de la bandeja la declara EXPLÍCITA
# para no abrir la del modo ``single`` (superficie distinta del mismo modelo).
SPLIT_VIEW_XMLID = (
    'printflow_gestion_inventario.printflow_flow_lot_assign_bulk_view_form_split')

# Archivos tocados por la tarea (se audita que no usen SQL crudo, REGLA SUPREMA
# §0.2): el candado mira el código del módulo, NUNCA a este propio archivo de
# test (auditarse a sí mismo lo delataría por las agujas literales).
_MODULE = 'printflow_gestion_inventario'
_TOUCHED_FILES = (
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk.py'),
    os.path.join('wizard', 'printflow_flow_lot_tray.py'),
    os.path.join('models', 'stock_move.py'),
)


@tagged('post_install', '-at_install')
class TestProductFlowLotAssignBulkSplit(TransactionCase):
    """El modo reparto cubre la demanda con VARIOS lotes, sin perder ninguno."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Reparto Bloque'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Bulk = cls.env['printflow.flow.lot.assign.bulk']
        cls.Result = cls.env['printflow.flow.lot.assign.bulk.result']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        # Determinismo de la bandeja (transitorio: vive en la transacción).
        cls.ICP.set_param(PARAM_NODE_PENDING_ENABLED, '1')
        cls.ICP.set_param(PARAM_NODE_PENDING_NODES,
                          'purchase,receipt,production,delivery,sale')
        cls.ICP.set_param(PARAM_NODE_PENDING_LIMIT, '0')
        cls.ICP.set_param(PARAM_EXCEPTION_POLICY, 'warn')

    # ------------------------------------------------------------------
    # Utilidades (misma base que el test del modo ``single``)
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

    def _outgoing(self, product, qty=2.0):
        """Albarán de salida confirmado SIN reserva (fila ``pending_order``).

        Se confirma ANTES de que exista existencia (Odoo no reserva por su
        cuenta) ⇒ el movimiento queda SIN ``move_line`` y la bandeja produce la
        fila ``pending_order`` de la ORDEN.
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

    def _pending_rows(self, product):
        """Filas ``pending_order`` de la bandeja del producto."""
        return self._open_tray(product).filtered(
            lambda row: row.kind == 'pending_order')

    def _wizard_for_split(self, selection):
        """Abre el wizard en MODO reparto desde la acción sobre la SELECCIÓN."""
        action = selection.action_split_lot_bulk()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.assign.bulk')
        self.assertEqual(action['target'], 'new')
        # El ``act_window`` declara la vista del MODO reparto (no la del single).
        self.assertEqual(
            [view[0] for view in action.get('views') or []],
            [self.env.ref(SPLIT_VIEW_XMLID).id])
        bulk = self.Bulk.browse(action['res_id'])
        self.assertEqual(bulk.mode, 'split')
        return bulk

    def _raw_row(self, picking, move, demand_qty):
        """Fila CRUDA como la arma la bandeja (contrato de ``_pf_populate``)."""
        return {
            'kind': 'pending_order',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'picking_id': picking.id,
            'move_id': move.id,
            'label': picking.name,
            'demand_qty': demand_qty,
            'location_id': self.stock_location.id,
            'scheduled_date': False,
            'own_lot_name': '',
        }

    def _mark_split(self, bulk, lots):
        """Marca con "Incluir" los candidatos de los lotes indicados."""
        marked = bulk.candidate_ids.filtered(
            lambda cand: cand.lot_id in lots)
        self.assertTrue(marked, 'Los lotes con existencia deben ser candidatos.')
        marked.write({'is_in_split': True})
        return marked

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    # ==================================================================
    # CA-1 — el reparto reserva TODOS los lotes marcados (aditivo)
    # ==================================================================
    def test_ca1_split_reserves_all_marked_lots(self):
        product = self._product('SPLIT CA1')
        lot_a = self._lot(product, 'SPLIT-CA1-A')
        lot_b = self._lot(product, 'SPLIT-CA1-B')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 1.0, lot=lot_a)
        self._stock(product, 1.0, lot=lot_b)

        rows = self._pending_rows(product)
        self.assertTrue(rows)
        bulk = self._wizard_for_split(rows)
        self.assertEqual(self._mark_split(bulk, lot_a | lot_b), bulk.candidate_ids)
        bulk.reason = 'Reparto de dos lotes de una unidad.'

        result = bulk.action_split_lot_bulk()

        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('1 asignadas', result['params']['message'])
        self.assertEqual(set(bulk.line_ids.mapped('result')), {'assigned'})
        # Los DOS lotes quedan reservados en el MISMO movimiento: 2 líneas.
        self.assertEqual(len(move.move_line_ids), 2)
        self.assertEqual(
            set(move.move_line_ids.mapped('lot_id')), set(lot_a | lot_b))
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 2.0)

    # ==================================================================
    # CA-2 — "Incluir" es multi-tick; "Elegir" sigue siendo ÚNICO (H-036)
    # ==================================================================
    def test_ca2_multi_tick_is_independent_and_single_selection_kept(self):
        product = self._product('SPLIT CA2')
        lot_a = self._lot(product, 'SPLIT-CA2-A')
        lot_b = self._lot(product, 'SPLIT-CA2-B')
        _pick, _move = self._outgoing(product, 2.0)
        self._stock(product, 1.0, lot=lot_a)
        self._stock(product, 1.0, lot=lot_b)

        bulk = self._wizard_for_split(self._pending_rows(product))
        cands = bulk.candidate_ids.filtered(
            lambda cand: cand.lot_id in (lot_a | lot_b))
        self.assertEqual(len(cands), 2)

        # Multi-tick: "Incluir" es INDEPENDIENTE por fila (no se desmarcan).
        cands.write({'is_in_split': True})
        self.assertEqual(len(bulk.candidate_ids.filtered('is_in_split')), 2)

        # La selección ÚNICA de ``is_selected`` sigue intacta (contraste H-036).
        cands.write({'is_selected': True})
        self.assertEqual(len(bulk.candidate_ids.filtered('is_selected')), 1)

    # ==================================================================
    # CA-3 — la asignación PARCIAL exige confirmación explícita
    # ==================================================================
    def test_ca3_partial_requires_confirmation(self):
        product = self._product('SPLIT CA3')
        lot_a = self._lot(product, 'SPLIT-CA3-A')
        lot_b = self._lot(product, 'SPLIT-CA3-B')
        _pick, move = self._outgoing(product, 3.0)
        self._stock(product, 1.0, lot=lot_a)
        self._stock(product, 1.0, lot=lot_b)

        bulk = self._wizard_for_split(self._pending_rows(product))
        self._mark_split(bulk, lot_a | lot_b)
        bulk.reason = 'Reparto parcial de lo disponible.'

        # libre (2) < demanda (3) y sin el check -> bloquea y NO escribe.
        with self.assertRaises(UserError):
            bulk.action_split_lot_bulk()
        self.assertFalse(move.move_line_ids)

        # Con el check -> reparte lo disponible y lo reporta como parcial.
        bulk.confirm_partial = True
        result = bulk.action_split_lot_bulk()

        self.assertIn('1 parciales', result['params']['message'])
        self.assertEqual(set(bulk.line_ids.mapped('result')), {'partial'})
        self.assertEqual(len(move.move_line_ids), 2)
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 2.0)
        note = bulk.line_ids.result_note
        self.assertIn(lot_a.name, note)
        self.assertIn(lot_b.name, note)

    # ==================================================================
    # CA-4 — el orden del reparto es el declarado (el de la tabla)
    # ==================================================================
    def test_ca4_declared_order_biggest_lot_first(self):
        product = self._product('SPLIT CA4')
        small = self._lot(product, 'SPLIT-CA4-SMALL')
        big = self._lot(product, 'SPLIT-CA4-BIG')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 1.0, lot=small)
        self._stock(product, 3.0, lot=big)

        bulk = self._wizard_for_split(self._pending_rows(product))
        self._mark_split(bulk, small | big)
        bulk.reason = 'Reparto en el orden declarado.'

        # El plan VISIBLE empieza por el lote de 3 u (el de más disponible).
        self.assertTrue(
            bulk.split_note.startswith('1) %s' % big.name), bulk.split_note)
        self.assertIn(small.name, bulk.split_note)

        bulk.action_split_lot_bulk()

        # Y la reserva consume PRIMERO ese lote (2 u salen del de 3 u).
        self.assertEqual(set(move.move_line_ids.mapped('lot_id')), {big})
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 2.0)

    # ==================================================================
    # CA-5 — reporte y detalle por destino (H-029 sin regresión)
    # ==================================================================
    def test_ca5_report_and_detail_are_kept(self):
        product = self._product('SPLIT CA5')
        lot = self._lot(product, 'SPLIT-CA5-LOTE')
        pick_a, move_a = self._outgoing(product, 2.0)
        pick_b, move_b = self._outgoing(product, 1.0)
        pick_c, move_c = self._outgoing(product, 1.0)
        self._stock(product, 10.0, lot=lot)

        rows = [
            self._raw_row(pick_a, move_a, 2.0),
            self._raw_row(pick_b, move_b, 1.0),
            # Destino NO asignable: resuelve movimiento pero su tipo está fuera
            # de la lista blanca ⇒ ``skipped`` + motivo (D7).
            {
                'kind': 'orphan_quant',
                'res_model': 'stock.quant',
                'res_id': 0,
                'picking_id': 0,
                'move_id': move_c.id,
                'label': 'Reserva huérfana',
                'demand_qty': 0.0,
                'location_id': self.stock_location.id,
                'scheduled_date': False,
                'own_lot_name': '',
            },
        ]
        bulk = self.Bulk._pf_populate(product, rows, mode='split')
        self.assertEqual(bulk.mode, 'split')
        self.assertEqual(bulk.assignable_count, 2)
        self.assertEqual(bulk.omitted_count, 1)
        self.assertEqual(len(bulk.line_ids), 3)
        self._mark_split(bulk, lot)
        bulk.reason = 'Cierre del reparto.'

        result = bulk.action_split_lot_bulk()

        # (a) los MISMOS 4 conteos del modo ``single``.
        self.assertEqual(
            result['params']['message'],
            '2 asignadas · 0 parciales · 1 omitidas · 0 con error.')

        # (b) el detalle se encadena con la MISMA convención de ``views``.
        nxt = result['params']['next']
        self.assertEqual(nxt['type'], 'ir.actions.act_window')
        self.assertEqual(
            nxt['res_model'], 'printflow.flow.lot.assign.bulk.result')
        self.assertEqual(nxt['target'], 'new')
        self.assertEqual(nxt['views'], [(False, 'form')])
        detail = self.Result.browse(nxt['res_id'])

        # (c) UNA fila por destino, incluidas las omitidas, con su motivo.
        self.assertEqual(len(detail.line_ids), len(bulk.line_ids))
        skipped = detail.line_ids.filtered(
            lambda line: line.result == 'skipped')
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped.result_note)
        self.assertTrue(all(
            line.result_note
            for line in detail.line_ids.filtered(
                lambda line: line.result in ('error', 'skipped'))))
        self.assertIn(lot, (move_a | move_b).move_line_ids.mapped('lot_id'))

    # ==================================================================
    # CA-6 — guardia, motivo obligatorio y política de excepción
    # ==================================================================
    def test_ca6_guardian_reason_and_policy(self):
        product = self._product('SPLIT CA6')
        lot = self._lot(product, 'SPLIT-CA6-LOTE')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 10.0, lot=lot)
        user = self._user(
            'pf_split_ca6', [self.env.ref('base.group_user')])
        rows = self._pending_rows(product)
        self.assertTrue(rows)

        # (a) ABRIR sin jefe de taller/administrador -> UserError.
        with self.assertRaises(UserError):
            rows.with_user(user).action_split_lot_bulk()

        # (b) EJECUTAR sin permiso -> UserError (y no escribe).
        bulk = self._wizard_for_split(rows)
        self._mark_split(bulk, lot)
        bulk.reason = 'Intento sin permiso.'
        with self.assertRaises(UserError):
            bulk.with_user(user).action_split_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))

        # (c) sin ``reason`` -> UserError.
        bulk.reason = False
        with self.assertRaises(UserError):
            bulk.action_split_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))

        # (d) política ≠ ``warn`` sin ``confirm_exception`` -> UserError.
        self.ICP.set_param(PARAM_EXCEPTION_POLICY, 'confirm_reason')
        bulk.reason = 'Motivo con política estricta.'
        with self.assertRaises(UserError):
            bulk.action_split_lot_bulk()
        self.assertFalse(move.move_line_ids.mapped('lot_id'))

        bulk.confirm_exception = True
        bulk.action_split_lot_bulk()
        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # CA-8 — no se apilan reservas sobre un movimiento ya en curso
    # ==================================================================
    def test_ca8_does_not_stack_on_picked_move(self):
        product = self._product('SPLIT CA8')
        lot = self._lot(product, 'SPLIT-CA8-LOTE')
        _pick, move = self._outgoing(product, 2.0)
        self._stock(product, 10.0, lot=lot)
        # Movimiento ya EN CURSO (picked): la reserva no se apila sobre él.
        move.picked = True
        row = self.Tray.create({
            'product_id': product.id,
            'lot_state': 'lot_missing',
            'kind': 'missing_move',
            'res_model': 'stock.move',
            'res_id': move.id,
            'can_choose_lot': True,
        })

        bulk = self._wizard_for_split(row)
        self._mark_split(bulk, lot)
        bulk.reason = 'No apilar sobre un movimiento ya en curso.'

        bulk.action_split_lot_bulk()

        line = bulk.line_ids.filtered('assignable')
        self.assertEqual(line.result, 'error')
        self.assertTrue(line.result_note)
        self.assertFalse(move.move_line_ids, 'No se crean reservas nuevas.')

    # ==================================================================
    # Candado — los archivos tocados no usan SQL crudo (§0.2)
    # ==================================================================
    def test_touched_files_have_no_raw_sql(self):
        module_path = get_module_path(_MODULE)
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)
