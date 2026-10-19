# -*- coding: utf-8 -*-
"""Asignación de lote POR UNIDAD (movimiento) en bloque desde la bandeja (PrintFlow).

Custodia los criterios CA-1…CA-7/CA-10 del plan de la asignación de lote
**POR ORDEN** (§3.O · H-039/H-040 · cierra **H-034**): el contenedor
``printflow.flow.lot.assign.bulk`` tiene **UNA sola acción** ("Asignar lote"),
**cada fila es un MOVIMIENTO** (una unidad = una línea de pedido) y cada fila
lleva **SU** selector de lote; el operador decide el par caja ↔ unidad.

* **CA-1** — la bandeja tiene UNA acción de lote en bloque: ``split`` no existe
  (ni método, ni campo ``mode``, ni ``split_note``).
* **CA-2** — un albarán con **2 movimientos** del producto produce **2 filas**
  (2 ``move_id`` distintos, ``demanda = 1`` cada una) ⇒ **H-034 cerrado**.
* **CA-3/CA-4** — cada fila muestra **pedido · línea · lote propio con su
  existencia**; **ninguna** fila llega pre-llenada (``lot_id`` **vacío**) aunque
  su lote propio tenga existencia, y el **sin** existencia se informa en
  ``0.00`` con su nombre visible.
* **CA-5** — dos lotes elegidos **uno por fila** cubren las 2 unidades: cada
  movimiento queda con SU ``move_line`` y SU lote (2/2).
* **CA-6** — motivo obligatorio, política de excepción (cero hardcodeo) y
  guardia de permisos (jefe de taller/administrador).
* **CA-7** — la fila parcial/error **no revienta** a las demás (captura por
  fila) y la fila **sin lote** queda ``skipped`` sin escribirse.
* **CA-10** — abrir/poblar el contenedor **no escribe** nada.

Es de SOLO LECTURA sobre datos ajenos salvo la ÚNICA escritura del flujo (la
reserva NATIVA que dispara el contenedor con su guardia y su motivo): crea sus
propios productos/albaranes y ``TransactionCase`` hace rollback al terminar.
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

# Candado (§0.2): el candado mira el CÓDIGO del módulo, NUNCA a este propio
# archivo de test (auditarse a sí mismo lo delataría por las agujas literales).
_MODULE = 'printflow_gestion_inventario'
_TOUCHED_FILES = (
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk.py'),
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk_line.py'),
    os.path.join('wizard', 'printflow_flow_lot_candidate.py'),
    os.path.join('wizard', 'printflow_flow_lot_tray.py'),
)


@tagged('post_install', '-at_install')
class TestProductFlowLotAssignBulkPerMove(TransactionCase):
    """El contenedor asigna a CADA unidad (movimiento) su lote (fila por fila)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Asignacion Por Unidad'})
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

    def _sale_lines(self, product, count=1):
        """Líneas de pedido (SIN confirmar) para darle lote propio a la unidad.

        El nombre del lote propio sale de la MISMA primitiva del motor que usa la
        bandeja (``sale.order.line._get_exclusive_lot_name``): el test lo lee de
        allí, no lo re-calcula.
        """
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {'product_id': product.id, 'product_uom_qty': 1.0})
                for _index in range(count)],
        })
        return order, order.order_line[:count]

    def _outgoing(self, product, qtys=(1.0,), sale_lines=None):
        """Albarán de salida confirmado con UN movimiento por cantidad.

        Se confirma ANTES de que exista existencia (Odoo no reserva por su
        cuenta) y SIN ``move_line``: los movimientos quedan SIN reserva ⇒ la
        bandeja produce la fila ``pending_order`` de la ORDEN (que se EXPANDE a
        una fila por movimiento en el contenedor).
        """
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        moves = self.env['stock.move']
        for index, qty in enumerate(qtys):
            sale_line = (sale_lines or [])[index] if sale_lines else None
            moves |= self.env['stock.move'].create({
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'picking_id': picking.id,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
                'sale_line_id': sale_line.id if sale_line else False,
            })
        moves._action_confirm()
        return picking, moves

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
        """Abre el contenedor desde la acción sobre la SELECCIÓN."""
        action = selection.action_assign_lot_bulk()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.assign.bulk')
        self.assertEqual(action['target'], 'new')
        return self.Bulk.browse(action['res_id'])

    def _pending_row(self, tray):
        """Fila ``pending_order`` de la bandeja (la dimensión OPERATIVA)."""
        rows = tray.filtered(lambda rec: rec.kind == 'pending_order')
        self.assertTrue(rows, 'La bandeja debe listar la entrega sin lote.')
        return rows

    def _line_for(self, bulk, move):
        """Fila del contenedor que corresponde a UN movimiento."""
        line = bulk.line_ids.filtered(lambda rec: rec.move_id == move)[:1]
        self.assertTrue(
            line, 'Cada movimiento debe tener SU fila en el contenedor.')
        return line

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
    # CA-1 — una sola acción en bloque: el modo ``split`` no existe
    # ==================================================================
    def test_ca1_only_one_bulk_action_exists(self):
        self.assertFalse(
            hasattr(self.Tray, 'action_split_lot_bulk'),
            'La bandeja no debe exponer el reparto (superficie retirada).')
        self.assertFalse(
            hasattr(self.Bulk, 'action_split_lot_bulk'),
            'El contenedor no debe exponer el reparto (superficie retirada).')
        self.assertNotIn('mode', self.Bulk._fields)
        self.assertNotIn('split_note', self.Bulk._fields)
        self.assertNotIn('lot_id', self.Bulk._fields)
        self.assertNotIn('confirm_partial', self.Bulk._fields)
        self.assertNotIn('is_in_split', self.env['printflow.flow.lot.candidate']._fields)

    # ==================================================================
    # CA-2 — una entrega con 2 unidades son 2 filas (cierra H-034)
    # ==================================================================
    def test_ca2_two_moves_of_one_delivery_are_two_rows(self):
        product = self._product('BULK POR UNIDAD CA2')
        _order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(1.0, 1.0), sale_lines=sale_lines)
        self.assertEqual(len(moves), 2)

        tray = self._open_tray(product)
        bulk = self._wizard_for(self._pending_row(tray))

        # Dos filas, dos movimientos distintos y la demanda POR MOVIMIENTO.
        self.assertEqual(len(bulk.line_ids), 2)
        self.assertEqual(set(bulk.line_ids.mapped('move_id')), set(moves))
        for line in bulk.line_ids:
            self.assertAlmostEqual(line.demand_qty, 1.0)
        self.assertAlmostEqual(bulk.total_demand, 2.0)
        self.assertEqual(bulk.assignable_count, 2)

    # ==================================================================
    # CA-3/CA-4 — lote propio por fila (informativo) + selector por fila
    # ==================================================================
    def test_ca3_each_row_shows_own_lot_and_selector(self):
        product = self._product('BULK POR UNIDAD CA3')
        order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(1.0, 1.0), sale_lines=sale_lines)
        move_a, move_b = moves[0], moves[1]
        own_name_a = sale_lines[0]._get_exclusive_lot_name()
        own_name_b = sale_lines[1]._get_exclusive_lot_name()
        self.assertNotEqual(own_name_a, own_name_b)
        # El lote propio de la PRIMERA unidad EXISTE con existencia; el de la
        # segunda existe pero está VACÍO (D4: elección consciente, ``0.00``).
        lot_a = self._lot(product, own_name_a)
        self._lot(product, own_name_b)
        self._stock(product, 1.0, lot=lot_a)

        tray = self._open_tray(product)
        bulk = self._wizard_for(self._pending_row(tray))

        line_a = self._line_for(bulk, move_a)
        line_b = self._line_for(bulk, move_b)

        # (a) trazabilidad del par caja ↔ pedido, unidad por unidad.
        self.assertEqual(line_a.sale_line_id, sale_lines[0])
        self.assertEqual(line_b.sale_line_id, sale_lines[1])
        self.assertEqual(line_a.sale_order_name, order.name)
        self.assertEqual(line_b.sale_order_name, order.name)
        self.assertEqual(line_a.own_lot_name, own_name_a)
        self.assertEqual(line_b.own_lot_name, own_name_b)

        # (b) NINGUNA fila llega pre-llenada (CA-1): el lote propio solo
        # INFORMA su existencia (CA-2), aunque la tenga.
        self.assertAlmostEqual(line_a.own_lot_qty, 1.0)
        self.assertFalse(
            line_a.lot_id,
            'El lote propio con existencia NO se pre-llena (D-1).')
        self.assertAlmostEqual(line_b.own_lot_qty, 0.0)
        self.assertFalse(line_b.lot_id, 'El lote propio vacío llega SIN lote.')
        self.assertTrue(
            line_b.own_lot_name, 'El nombre del lote propio queda visible.')
        self.assertTrue(
            line_a.own_lot_name, 'El nombre del lote propio queda visible.')

        # (c) el selector por fila ofrece SOLO lotes con existencia.
        self.assertIn(lot_a, bulk.candidate_lot_ids)

    # ==================================================================
    # CA-5 — un lote por fila cubre las 2 unidades (entrega completa 2/2)
    # ==================================================================
    def test_ca5_per_row_lots_cover_both_moves(self):
        product = self._product('BULK POR UNIDAD CA5')
        lot_a = self._lot(product, 'BULK-PORUNIDAD-CA5-A')
        lot_b = self._lot(product, 'BULK-PORUNIDAD-CA5-B')
        _order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(1.0, 1.0), sale_lines=sale_lines)
        move_a, move_b = moves[0], moves[1]
        self._stock(product, 1.0, lot=lot_a)
        self._stock(product, 1.0, lot=lot_b)

        tray = self._open_tray(product)
        bulk = self._wizard_for(self._pending_row(tray))
        self.assertEqual(len(bulk.line_ids), 2)

        self._line_for(bulk, move_a).lot_id = lot_a.id
        self._line_for(bulk, move_b).lot_id = lot_b.id
        bulk.reason = 'Una caja por unidad (decision por fila).'

        result = bulk.action_assign_lot_bulk()

        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn('2 asignadas', result['params']['message'])
        self.assertEqual(set(bulk.line_ids.mapped('result')), {'assigned'})
        # Cada movimiento se queda con SU lote (2/2 de la entrega cubiertos).
        self.assertEqual(move_a.move_line_ids.mapped('lot_id'), lot_a)
        self.assertEqual(move_b.move_line_ids.mapped('lot_id'), lot_b)
        self.assertAlmostEqual(
            sum(move_a.move_line_ids.mapped('quantity')), 1.0)
        self.assertAlmostEqual(
            sum(move_b.move_line_ids.mapped('quantity')), 1.0)

    # ==================================================================
    # CA-6 — motivo obligatorio, política de excepción y permisos
    # ==================================================================
    def test_ca6_reason_policy_and_permissions(self):
        product = self._product('BULK POR UNIDAD CA6')
        lot = self._lot(product, 'BULK-PORUNIDAD-CA6-LOTE')
        _pick, moves = self._outgoing(product, qtys=(1.0,))
        self._stock(product, 5.0, lot=lot)
        user = self._user(
            'pf_per_move_inv', [self.env.ref('base.group_user')])
        manager = self._manager('pf_per_move_manager')

        tray = self._open_tray(product)
        rows = self._pending_row(tray)

        # (a) ABRIR exige jefe de taller/administrador.
        with self.assertRaises(UserError):
            rows.with_user(user).action_assign_lot_bulk()

        bulk = self._wizard_for(rows)
        self._line_for(bulk, moves[0]).lot_id = lot.id

        # (b) EJECUTAR vuelve a exigir la guardia de permisos.
        with self.assertRaises(UserError):
            bulk.with_user(user).action_assign_lot_bulk()

        # (c) el motivo es obligatorio.
        bulk = bulk.with_user(manager)
        with self.assertRaises(UserError):
            bulk.action_assign_lot_bulk()
        self.assertFalse(moves.move_line_ids.mapped('lot_id'))

        # (d) política ≠ ``warn`` sin ``confirm_exception`` -> bloquea.
        self.ICP.set_param(PARAM_EXCEPTION_POLICY, 'confirm_reason')
        bulk.reason = 'Motivo con politica estricta.'
        with self.assertRaises(UserError):
            bulk.action_assign_lot_bulk()
        self.assertFalse(moves.move_line_ids.mapped('lot_id'))

        # (e) con la confirmación de excepción, asigna.
        bulk.confirm_exception = True
        bulk.action_assign_lot_bulk()
        self.assertIn(lot, moves.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # CA-7 — captura POR FILA: la parcial no revienta a las demás
    # ==================================================================
    def test_ca7_partial_row_does_not_break_the_rest(self):
        product = self._product('BULK POR UNIDAD CA7')
        lot_small = self._lot(product, 'BULK-PORUNIDAD-CA7-SMALL')
        lot_full = self._lot(product, 'BULK-PORUNIDAD-CA7-FULL')
        _order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(2.0, 1.0), sale_lines=sale_lines)
        move_partial, move_full = moves[0], moves[1]
        self._stock(product, 1.0, lot=lot_small)
        self._stock(product, 1.0, lot=lot_full)

        tray = self._open_tray(product)
        bulk = self._wizard_for(self._pending_row(tray))

        self._line_for(bulk, move_partial).lot_id = lot_small.id
        self._line_for(bulk, move_full).lot_id = lot_full.id
        bulk.reason = 'Lote escaso: la parcial no debe frenar a la otra fila.'

        result = bulk.action_assign_lot_bulk()

        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(self._line_for(bulk, move_partial).result, 'partial')
        self.assertEqual(self._line_for(bulk, move_full).result, 'assigned')
        self.assertIn(
            '1 parciales', result['params']['message'])
        self.assertIn('1 asignadas', result['params']['message'])
        self.assertIn(lot_small, move_partial.move_line_ids.mapped('lot_id'))
        self.assertIn(lot_full, move_full.move_line_ids.mapped('lot_id'))

    def test_ca7_row_without_lot_is_skipped(self):
        product = self._product('BULK POR UNIDAD CA7 SKIP')
        lot = self._lot(product, 'BULK-PORUNIDAD-CA7-SKIP-LOTE')
        _order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(1.0, 1.0), sale_lines=sale_lines)
        move_touched, move_untouched = moves[0], moves[1]
        self._stock(product, 1.0, lot=lot)

        tray = self._open_tray(product)
        bulk = self._wizard_for(self._pending_row(tray))
        # Solo UNA fila trae lote: la otra queda SIN decisión.
        self._line_for(bulk, move_touched).lot_id = lot.id
        bulk.reason = 'Solo una unidad tiene lote elegido.'

        result = bulk.action_assign_lot_bulk()

        skipped = self._line_for(bulk, move_untouched)
        self.assertEqual(skipped.result, 'skipped')
        self.assertTrue(skipped.result_note)
        self.assertFalse(
            move_untouched.move_line_ids.mapped('lot_id'),
            'La unidad sin lote elegido no se toca.')
        self.assertEqual(self._line_for(bulk, move_touched).result, 'assigned')
        self.assertIn(lot, move_touched.move_line_ids.mapped('lot_id'))
        self.assertIn('1 asignadas', result['params']['message'])

    # ==================================================================
    # CA-10 — abrir/poblar el contenedor NO escribe nada
    # ==================================================================
    def test_ca10_opening_writes_nothing(self):
        product = self._product('BULK POR UNIDAD CA10')
        lot = self._lot(product, 'BULK-PORUNIDAD-CA10-LOTE')
        _order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(1.0, 1.0), sale_lines=sale_lines)
        self._stock(product, 5.0, lot=lot)
        Quant = self.env['stock.quant']
        Lot = self.env['stock.lot']

        def snapshot():
            return (
                Quant.search_read(
                    [('product_id', '=', product.id)],
                    ['quantity', 'reserved_quantity', 'lot_id']),
                Lot.search_read(
                    [('product_id', '=', product.id)], ['name']),
                moves.read(['state', 'quantity', 'product_uom_qty']),
            )

        before = snapshot()
        bulk = self._wizard_for(self._pending_row(self._open_tray(product)))
        self.assertTrue(bulk.line_ids)
        self.assertEqual(
            bulk.line_ids.mapped('result'), ['pending', 'pending'])
        self.assertEqual(before, snapshot())

    # ==================================================================
    # Candado — el código tocado no usa SQL crudo (§0.2)
    # ==================================================================
    def test_touched_files_have_no_raw_sql(self):
        module_path = get_module_path(_MODULE)
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)
