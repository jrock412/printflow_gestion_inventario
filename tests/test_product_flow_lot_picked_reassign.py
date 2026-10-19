# -*- coding: utf-8 -*-
"""El cambio de lote de una unidad TACHADA (§3.R · H-055 · H-056 · H-057).

Custodia el contrato de §3.R:

* **CA-1/CA-2 (T1)** — una unidad ``picked`` de una entrega abierta cambia de
  lote: queda reservada **solo** en el lote elegido, el lote viejo recupera su
  libre y el tachón **vuelve** (en el movimiento **y** en sus líneas · C-2).
* **CA-3 (T1)** — las entregas ``done``/``cancel`` devuelven ``0.0`` sin tocar
  nada (D-2).
* **CA-4 (T1)** — una unidad **corta** no recupera el tachón (queda ``partial``).
* **CA-4/CA-5 (T2)** — el veredicto de la fila usa la **tolerancia de la UdM**
  (``_pf_unit_is_covered``), no un ``_EPS`` mágico: el caso del DTF
  (demanda 0,018182 / reservado 0,018, UdM ``m`` con rounding 0,001) es
  ``assigned``; una falta real es ``partial``; sin nada reservado es ``error``
  con el motivo real; demanda cero es ``skipped``.
* **CA-6 (T3)** — el camino **por documento** (``_pf_assign_lot_to_document``)
  hace el MISMO baile: sobre una unidad tachada **no suma** la reserva (H-056).
* **CA-7 (T4)** — **atomicidad**: si el baile falla a mitad, el savepoint
  revierte TODO y la unidad queda con su tachón y su lote de antes.
* **CA-10 (T5)** — elegir un lote **VACÍO** no le quita nada a la unidad: queda
  intacta (tachón + reserva vieja) y la fila lo reporta con el motivo real.

El escenario se monta con las utilidades del test de ``per_move`` (producto por
lote, albarán de salida confirmado y reservado por el flujo NATIVO).
``TransactionCase`` hace rollback: la BD de PRUEBA se lee, no se sanea.
"""

from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

# Política de asignación por excepción (cero hardcodeo): ``warn`` para que los
# casos no tengan fricción extra.
PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


class _LotReassignBase(TransactionCase):
    """Utilidades compartidas (sin tests propios)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente 3R Reasignacion Tachada'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Quant = cls.env['stock.quant']
        cls.Bulk = cls.env['printflow.flow.lot.assign.bulk']
        cls.BulkLine = cls.env['printflow.flow.lot.assign.bulk.line']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        cls.ICP.set_param(PARAM_EXCEPTION_POLICY, 'warn')

    # ------------------------------------------------------------------
    # Utilidades (mismas del test de ``per_move``)
    # ------------------------------------------------------------------
    def _product(self, name, uom=None):
        vals = {
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        }
        product = self.env['product.product'].create(vals)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        if uom is not None:
            # Se fija en la PLANTILLA (``_inherits``) y se comprueba de vuelta.
            product.product_tmpl_id.write(
                {'uom_id': uom.id, 'uom_po_id': uom.id})
            self.assertEqual(product.uom_id, uom)
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _outgoing(self, product, qtys=(1.0,)):
        """Albarán de salida confirmado con UN movimiento por cantidad.

        ``description_picking`` entra en la clave de fusión del core: así las
        unidades NO se fusionan en un solo movimiento.
        """
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        moves = self.env['stock.move']
        for index, qty in enumerate(qtys):
            moves |= self.env['stock.move'].create({
                'name': product.display_name,
                'description_picking': '%s u%d' % (product.display_name, index),
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'picking_id': picking.id,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
            })
        moves._action_confirm()
        return picking, moves

    def _reserved_move(self, product, lot, qty=1.0, picked=True):
        """Movimiento abierto con su reserva puesta en ``lot`` (y tachón)."""
        self._stock(product, qty + 4.0, lot=lot)
        picking, move = self._outgoing(product, qtys=(qty,))
        picking.action_assign()
        self.assertEqual(
            move.move_line_ids.mapped('lot_id'), lot,
            'El flujo NATIVO debe reservar el lote con existencia.')
        if picked:
            move.picked = True
        return picking, move

    def _bulk(self, product, move, lot, demand=None):
        """Contenedor con UNA fila (una unidad) y el lote elegido."""
        bulk = self.Bulk.create({
            'product_id': product.id,
            'reason': 'Cambio de lote sobre una unidad tachada (prueba).',
        })
        self.BulkLine.create({
            'bulk_id': bulk.id,
            'kind': 'missing_move',
            'res_model': 'stock.move',
            'res_id': move.id,
            'move_id': move.id,
            'demand_qty': demand if demand is not None else move.product_uom_qty,
            'assignable': True,
            'lot_id': lot.id,
        })
        return bulk

    def _free(self, product, lot):
        return self.Quant._get_available_quantity(
            product, self.stock_location, lot_id=lot, strict=True)

    def _reserved(self, product, lot):
        quants = self.Quant._gather(
            product, self.stock_location, lot_id=lot, strict=True)
        return sum(quants.mapped('reserved_quantity'))


@tagged('post_install', '-at_install')
class TestProductFlowLotPickedReassign(_LotReassignBase):
    """T1 — el baile del tachón (D-3) y la vara de la UdM (D-4)."""

    # ==================================================================
    # CA-1 — la unidad tachada cambia de lote y el tachón vuelve
    # ==================================================================
    def test_ca1_picked_unit_changes_lot(self):
        product = self._product('3R CA1 TACHADA')
        lot_old = self._lot(product, '3R-CA1-VIEJO')
        lot_new = self._lot(product, '3R-CA1-NUEVO')
        _picking, move = self._reserved_move(product, lot_old)
        self._stock(product, 5.0, lot=lot_new)

        bulk = self._bulk(product, move, lot_new)
        bulk.action_assign_lot_bulk()

        move.invalidate_recordset()
        line = bulk.line_ids[:1]
        self.assertEqual(line.result, 'assigned', line.result_note)
        # La reserva quedó SOLO en el lote elegido.
        self.assertEqual(move.move_line_ids.mapped('lot_id'), lot_new)
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 1.0)
        # Tachón devuelto: en el MOVIMIENTO y en sus LÍNEAS (C-2).
        self.assertTrue(move.picked, 'El tachón debe volver al movimiento.')
        self.assertTrue(
            all(move.move_line_ids.mapped('picked')),
            'El tachón debe volver a TODAS las líneas del movimiento.')
        self.assertEqual(move.state, 'assigned')
        # El lote viejo recupera su libre.
        self.assertAlmostEqual(self._free(product, lot_old), 5.0)
        self.assertAlmostEqual(self._free(product, lot_new), 4.0)

    # ==================================================================
    # CA-2 — sin reserva apilada (ni fantasma ni negativa)
    # ==================================================================
    def test_ca2_no_stacked_reservation(self):
        product = self._product('3R CA2 SIN APILAR')
        lot_old = self._lot(product, '3R-CA2-VIEJO')
        lot_new = self._lot(product, '3R-CA2-NUEVO')
        _picking, move = self._reserved_move(product, lot_old)
        self._stock(product, 5.0, lot=lot_new)

        self._bulk(product, move, lot_new).action_assign_lot_bulk()

        move.invalidate_recordset()
        self.assertEqual(move.move_line_ids.mapped('lot_id'), lot_new)
        self.assertAlmostEqual(self._reserved(product, lot_old), 0.0)
        self.assertAlmostEqual(self._reserved(product, lot_new), 1.0)
        # Cero cantidades negativas en los quants del producto.
        quants = self.Quant.search([('product_id', '=', product.id)])
        self.assertFalse(
            [q.id for q in quants if q.reserved_quantity < 0],
            'El baile no debe dejar reservas negativas.')
        self.assertFalse(
            [q.id for q in quants if q.quantity < 0],
            'El baile no debe dejar físico negativo.')

    # ==================================================================
    # CA-3 — done / cancel NO se tocan (D-2)
    # ==================================================================
    def test_ca3_done_or_cancel_untouched(self):
        product = self._product('3R CA3 NO-GO')
        lot_old = self._lot(product, '3R-CA3-VIEJO')
        lot_new = self._lot(product, '3R-CA3-NUEVO')
        self._stock(product, 10.0, lot=lot_old)

        done_picking, done_move = self._reserved_move(product, lot_old)
        done_move._action_done()
        self.assertEqual(done_move.state, 'done')
        done_lines = done_move.move_line_ids
        self.assertEqual(
            done_move._pf_reassign_lots([lot_new]), 0.0,
            'Una entrega done no se toca (D-2).')
        self.assertEqual(done_move.state, 'done')
        self.assertEqual(done_move.move_line_ids, done_lines)

        cancel_picking, cancel_move = self._reserved_move(product, lot_old)
        cancel_move._action_cancel()
        self.assertEqual(cancel_move.state, 'cancel')
        self.assertEqual(
            cancel_move._pf_reassign_lots([lot_new]), 0.0,
            'Una entrega cancel no se toca (D-2).')
        self.assertEqual(cancel_move.state, 'cancel')
        self.assertFalse(cancel_move.picked)

    # ==================================================================
    # CA-4 — la unidad corta NO recupera el tachón
    # ==================================================================
    def test_ca4_short_unit_loses_pick(self):
        product = self._product('3R CA4 CORTA')
        lot_old = self._lot(product, '3R-CA4-VIEJO')
        lot_new = self._lot(product, '3R-CA4-NUEVO')
        _picking, move = self._reserved_move(product, lot_old)
        self._stock(product, 0.5, lot=lot_new)

        bulk = self._bulk(product, move, lot_new)
        bulk.action_assign_lot_bulk()

        move.invalidate_recordset()
        line = bulk.line_ids[:1]
        self.assertEqual(line.result, 'partial', line.result_note)
        # La parcial NO se tranca (R1): se reserva lo disponible.
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 0.5)
        self.assertAlmostEqual(self._reserved(product, lot_new), 0.5)
        # El tachón NO vuelve (CA-4).
        self.assertFalse(move.picked)
        self.assertFalse(any(move.move_line_ids.mapped('picked')))
        # Y el lote viejo recupera su libre (no quedó apilado).
        self.assertAlmostEqual(self._free(product, lot_old), 5.0)


@tagged('post_install', '-at_install')
class TestProductFlowLotAssignBulkVerdict(_LotReassignBase):
    """T2 — el veredicto honesto de la fila (D-4 · CA-4/CA-5)."""

    def _meter_product(self, name):
        """Producto en una UdM con ``rounding`` 0.001 (el caso del DTF).

        Se crea una categoría/UdM PROPIAS (no se toca ``decimal.precision`` ni
        la UdM ``m`` de la BD, que es DATO): lo que CA-5 exige es la tolerancia
        del redondeo de la UdM, no un registro concreto.
        """
        category = self.env['uom.category'].create(
            {'name': '3R Longitud (prueba)'})
        uom = self.env['uom.uom'].create({
            'name': 'Metro 3R (rounding 0.001)',
            'category_id': category.id,
            'uom_type': 'reference',
            'factor': 1.0,
            'rounding': 0.001,
        })
        self.assertEqual(uom.rounding, 0.001)
        return self._product(name, uom=uom)

    # ==================================================================
    # CA-5 — la tolerancia de la UdM (caso literal del DTF)
    # ==================================================================
    def test_ca5_uom_rounding_is_covered(self):
        product = self._meter_product('3R CA5 DTF')
        lot = self._lot(product, '3R-CA5-DTF-LOTE')
        self._stock(product, 0.018, lot=lot)
        _picking, move = self._outgoing(product, qtys=(0.018182,))

        # El helper es la ÚNICA vara (sin ``_EPS``): 0,018 cubre 0,018182
        # porque el redondeo de la UdM (0,001) los iguala.
        self.assertTrue(move._pf_unit_is_covered(0.018, 0.018182))
        self.assertFalse(move._pf_unit_is_covered(0.0, 1.0))

        bulk = self._bulk(product, move, lot, demand=0.018182)
        bulk.action_assign_lot_bulk()

        self.assertEqual(
            bulk.line_ids[:1].result, 'assigned',
            bulk.line_ids[:1].result_note)
        # El reservado EXACTO depende del ``decimal.precision`` de la BD (DATO,
        # H-053); lo que CA-5 fija es el VEREDICTO con la vara de la UdM.
        reserved = self._reserved(product, lot)
        self.assertGreater(reserved, 0.0)
        self.assertTrue(move._pf_unit_is_covered(reserved, 0.018182))

    # ==================================================================
    # CA-4 — una falta REAL es ``partial``
    # ==================================================================
    def test_ca4_short_unit_is_partial(self):
        product = self._product('3R CA4 VEREDICTO PARCIAL')
        lot = self._lot(product, '3R-CA4V-LOTE')
        self._stock(product, 1.0, lot=lot)
        _picking, move = self._outgoing(product, qtys=(2.0,))

        bulk = self._bulk(product, move, lot, demand=2.0)
        bulk.action_assign_lot_bulk()

        self.assertEqual(bulk.line_ids[:1].result, 'partial')
        self.assertAlmostEqual(self._reserved(product, lot), 1.0)

    # ==================================================================
    # CA-5 — sin reserva: ``error`` con el motivo REAL (nombra el lote)
    # ==================================================================
    def test_ca5_zero_reservation_is_error_with_reason(self):
        product = self._product('3R CA5 ERROR REAL')
        lot_empty = self._lot(product, '3R-CA5-VACIO')
        _picking, move = self._outgoing(product, qtys=(1.0,))

        bulk = self._bulk(product, move, lot_empty, demand=1.0)
        bulk.action_assign_lot_bulk()

        line = bulk.line_ids[:1]
        self.assertEqual(line.result, 'error')
        self.assertIn(lot_empty.name, line.result_note)
        self.assertIn('no tiene existencia disponible', line.result_note)

    # ==================================================================
    # CA-5 — demanda cero: ``skipped`` (nada que asignar)
    # ==================================================================
    def test_ca5_zero_demand_is_skipped(self):
        product = self._product('3R CA5 DEMANDA CERO')
        lot = self._lot(product, '3R-CA5-CERO-LOTE')
        self._stock(product, 1.0, lot=lot)
        _picking, move = self._outgoing(product, qtys=(1.0,))

        bulk = self._bulk(product, move, lot, demand=0.0)
        bulk.action_assign_lot_bulk()

        line = bulk.line_ids[:1]
        self.assertEqual(line.result, 'skipped')
        self.assertIn('no tiene demanda', line.result_note)


@tagged('post_install', '-at_install')
class TestProductFlowLotDocumentPath(_LotReassignBase):
    """T3 — el camino por documento usa el MISMO mecanismo (H-056 · CA-6)."""

    # ==================================================================
    # CA-6 — el camino por documento NO suma la reserva en silencio
    # ==================================================================
    def test_ca6_document_path_does_not_stack(self):
        product = self._product('3R CA6 DOCUMENTO')
        lot_old = self._lot(product, '3R-CA6-VIEJO')
        lot_new = self._lot(product, '3R-CA6-NUEVO')
        _picking, move = self._reserved_move(product, lot_old)
        self._stock(product, 5.0, lot=lot_new)

        Flow = self.env['printflow.product.flow']
        Flow._pf_assign_lot_to_document(
            'missing_move', 'stock.move', move.id, lot_new)

        move.invalidate_recordset()
        move.move_line_ids.invalidate_recordset()
        # La unidad quedó reservada SOLO en el lote elegido (no A + B).
        self.assertEqual(move.move_line_ids.mapped('lot_id'), lot_new)
        self.assertAlmostEqual(self._reserved(product, lot_old), 0.0)
        self.assertAlmostEqual(self._reserved(product, lot_new), 1.0)
        # El lote viejo recupera su libre original (5.0 físicas, 0 reservadas).
        self.assertAlmostEqual(self._free(product, lot_old), 5.0)
        # El tachón vuelve: en el MOVIMIENTO y en sus LÍNEAS (C-2).
        self.assertTrue(move.picked)
        self.assertTrue(all(move.move_line_ids.mapped('picked')))


@tagged('post_install', '-at_install')
class TestProductFlowLotBulkAtomicity(_LotReassignBase):
    """T4 — un solo aliento por fila (CA-7)."""

    # ==================================================================
    # CA-7 — un fallo a mitad del baile deja la unidad EXACTAMENTE igual
    # ==================================================================
    def test_ca7_failure_leaves_unit_untouched(self):
        product = self._product('3R CA7 ATOMICO')
        lot_old = self._lot(product, '3R-CA7-VIEJO')
        lot_new = self._lot(product, '3R-CA7-NUEVO')
        _picking, move = self._reserved_move(product, lot_old)
        self._stock(product, 5.0, lot=lot_new)
        bulk = self._bulk(product, move, lot_new)

        # La primitiva de reserva revienta DESPUÉS del destildado y de la
        # liberación: es el punto medio exacto del baile.
        boom = RuntimeError('fallo simulado a mitad del baile')
        with patch.object(type(self.env['stock.move']), '_pf_reserve_lot',
                          side_effect=boom):
            bulk.action_assign_lot_bulk()

        move.invalidate_recordset()
        move.move_line_ids.invalidate_recordset()
        self.Quant.invalidate_model()
        line = bulk.line_ids[:1]
        self.assertEqual(line.result, 'error')
        self.assertEqual(
            line.result_note, 'No se pudo asignar el lote a la unidad.')
        # La unidad quedó como estaba: tachón y lote viejos, sin destildar.
        self.assertTrue(move.picked, 'El savepoint debe restaurar el tachón.')
        self.assertTrue(
            all(move.move_line_ids.mapped('picked')),
            'El savepoint debe restaurar el tachón en TODAS las líneas.')
        self.assertEqual(move.move_line_ids.mapped('lot_id'), lot_old)
        self.assertAlmostEqual(self._reserved(product, lot_old), 1.0)
        self.assertAlmostEqual(self._free(product, lot_new), 5.0)


@tagged('post_install', '-at_install')
class TestProductFlowLotEmptyLotGuard(_LotReassignBase):
    """T5 — el lote VACÍO no se toma (H-058 · D-10 · CA-10)."""

    # ==================================================================
    # CA-10 — el lote vacío no le quita nada a la unidad
    # ==================================================================
    def test_ca10_empty_lot_does_not_touch_unit(self):
        product = self._product('3R CA10 VACIO')
        lot_old = self._lot(product, '3R-CA10-VIEJO')
        empty = self._lot(product, '3R-CA10-VACIO')
        _picking, move = self._reserved_move(product, lot_old)
        free_old_before = self._free(product, lot_old)

        bulk = self._bulk(product, move, empty)
        bulk.action_assign_lot_bulk()

        move.invalidate_recordset()
        move.move_line_ids.invalidate_recordset()
        line = bulk.line_ids[:1]
        self.assertEqual(line.result, 'error')
        self.assertIn(empty.name, line.result_note)
        self.assertIn('no tiene existencia disponible', line.result_note)
        # La unidad quedó INTACTA: tachón + reserva vieja + libre del lote A.
        self.assertTrue(move.picked)
        self.assertTrue(all(move.move_line_ids.mapped('picked')))
        self.assertEqual(move.move_line_ids.mapped('lot_id'), lot_old)
        self.assertAlmostEqual(self._reserved(product, lot_old), 1.0)
        self.assertAlmostEqual(self._free(product, lot_old), free_old_before)
