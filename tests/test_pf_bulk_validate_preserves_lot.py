# -*- coding: utf-8 -*-
"""Preservación de la reserva de lote EXCEPTUADA al validar entregas en lote (H-030).

Custodia los criterios CA-1/CA-2/CA-5 del plan de las incidencias del wizard de
asignación en bloque y del "validar entregas en lote":

* **CA-1** — un albarán de entrega con reserva de lote EXCEPTUADA por el
  operador, procesado por "validar entregas en lote", NO pierde su lote: ningún
  ``action_assign()`` intermedio lo des-reserva.
* **CA-2** — ese albarán se valida (``done``) y YA NO reporta *"Sin stock
  reservado."* habiendo reserva; un albarán SIN reserva ni existencia SÍ se omite
  con *"Sin stock reservado."* (motivo HONESTO).
* **CA-5** — las entregas SIN excepción conservan el flujo NATIVO: con el lote
  exclusivo CON existencia, ``action_assign()`` reserva el lote exclusivo (el
  motor ``x_product_dimensional_pricing`` queda INTACTO: solo se hereda).

Es de SOLO LECTURA sobre datos ajenos salvo las escrituras NATIVAS del flujo
(reserva/validación que ``TransactionCase`` revierte): crea sus propios
productos/pedidos/albaranes y hace rollback al terminar.
"""

import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

# Comportamiento ante movimiento sin lote: se fija en ``warn`` para que la
# validación no se bloquee ni auto-asigne por configuración de la BD.
PARAM_LOT_MISSING_ACTION = (
    'x_product_dimensional_pricing.pf_lot_missing_action')

# Archivo NUEVO del arreglo (se audita que no use SQL crudo).
_TOUCHED_FILES = (os.path.join('models', 'stock_move.py'),)

# Etiqueta de clase del motor: sirve para probar que el motor NO se editó.
_MOTOR_GUARDIAN = '_pf_keep_current_lot_reservation'


@tagged('post_install', '-at_install')
class TestPfBulkValidatePreservesLot(
        PrintflowStockHealthTestMixin, TransactionCase):
    """El "validar entregas en lote" preserva la reserva de lote del operador."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Preserva Lote'})
        cls.env['ir.config_parameter'].sudo().set_param(
            PARAM_LOT_MISSING_ACTION, 'warn')

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        """Producto por lote gestionado (entrega EXCLUSIVA por pedido)."""
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True, 'pf_purchase_on_order': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _delivery(self, product, qty=2.0):
        """SO confirmado + su albarán de salida + su movimiento.

        El lote EXCLUSIVO del pedido se crea DESPUÉS (en el test) para que la
        re-asignación automática del confirmado no reserve nada.
        """
        so = self._pf_confirm_order(product, qty)
        picking = so.picking_ids.filtered(
            lambda pick: pick.picking_type_id.code == 'outgoing')[:1]
        return so, picking, picking.move_ids[:1]

    def _exclusive_lot(self, product, so):
        """Crea (VACÍO o con existencia) el lote exclusivo ``<SO>-L<line>``."""
        name = so.order_line[:1]._get_exclusive_lot_name()
        return self._lot(product, name)

    def _bulk_validate(self, pickings):
        return self.env['stock.picking'].with_context(
            active_ids=pickings.ids,
            active_domain=[]).action_pf_bulk_validate_deliveries()

    def _detail_row(self, action, picking):
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.delivery.bulk.result')
        detail = self.env['printflow.delivery.bulk.result'].browse(
            action['res_id'])
        return detail, detail.line_ids.filtered(
            lambda line: line.picking_id == picking)

    # ==================================================================
    # CA-1 / CA-2 — la excepción SOBREVIVE y el albarán se valida
    # ==================================================================
    def test_ca1_ca2_exception_survives_and_validates(self):
        product = self._product('PF BULK PRESERVA')
        so, picking, move = self._delivery(product, 2.0)
        generic = self._lot(product, 'PF-BULK-GENERICO')
        self._exclusive_lot(product, so)          # existe pero VACÍO
        self._stock(product, 2.0, generic)
        # La EXCEPCIÓN del operador: reserva manual del lote genérico.
        move._pf_reassign_lot(generic, move.product_uom_qty)
        picking.invalidate_recordset(['state'])
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual(move.move_line_ids.mapped('lot_id'), generic)

        # (CA-1/CA-2a) el ``action_assign`` del bulk NO la des-reserva.
        picking.action_assign()
        picking.invalidate_recordset(['state'])
        move.invalidate_recordset(['state', 'move_line_ids'])
        self.assertEqual(
            picking.state, 'assigned',
            'La entrega con la excepción debe seguir lista para transferir.')
        self.assertEqual(
            move.move_line_ids.mapped('lot_id'), generic,
            'El lote EXCEPTUADO por el operador NO debe perderse.')
        self.assertEqual(move.state, 'assigned')

        # (CA-2b) el bulk la valida (done) y NO reporta "Sin stock reservado.".
        detail, row = self._detail_row(
            self._bulk_validate(picking), picking)
        self.assertEqual(len(row), 1)
        self.assertEqual(row.result, 'done')
        self.assertFalse(row.reason)
        picking.invalidate_recordset(['state'])
        self.assertEqual(picking.state, 'done')
        self.assertNotIn(
            'Sin stock reservado.', detail.line_ids.mapped('reason'),
            'Un albarán CON reserva no debe reportar "Sin stock reservado.".')

    # ==================================================================
    # CA-2c — sin reserva ni existencia ⇒ omitida con motivo HONESTO
    # ==================================================================
    def test_ca2c_starved_delivery_is_skipped_honestly(self):
        product = self._product('PF BULK SIN STOCK')
        so_a, pick_a, move_a = self._delivery(product, 2.0)
        generic = self._lot(product, 'PF-BULK-SIN-STOCK-GENERICO')
        self._exclusive_lot(product, so_a)
        self._stock(product, 2.0, generic)
        move_a._pf_reassign_lot(generic, move_a.product_uom_qty)
        # SEGUNDA entrega del MISMO producto: sin reserva y sin existencia.
        so_b, pick_b, _move_b = self._delivery(product, 2.0)
        self._exclusive_lot(product, so_b)

        detail = self.env['printflow.delivery.bulk.result'].browse(
            self._bulk_validate(pick_a | pick_b)['res_id'])
        row_a = detail.line_ids.filtered(
            lambda line: line.picking_id == pick_a)
        row_b = detail.line_ids.filtered(
            lambda line: line.picking_id == pick_b)
        self.assertEqual(row_a.result, 'done')
        self.assertEqual(
            row_b.result, 'skipped',
            'Sin reserva ni existencia el albarán se omite.')
        self.assertEqual(
            row_b.reason, 'Sin stock reservado.',
            'El motivo del omitido debe ser el HONESTO del motor.')

    # ==================================================================
    # CA-5 — sin excepción, el motor sigue alineando al lote EXCLUSIVO
    # ==================================================================
    def test_ca5_exclusive_lot_with_stock_is_reserved(self):
        product = self._product('PF BULK EXCLUSIVO')
        so, picking, move = self._delivery(product, 2.0)
        own = self._exclusive_lot(product, so)
        self._stock(product, 5.0, own)            # el exclusivo SÍ tiene stock

        picking.action_assign()                   # sin reserva previa
        picking.invalidate_recordset(['state'])
        move.invalidate_recordset(['state', 'move_line_ids'])
        self.assertEqual(picking.state, 'assigned')
        self.assertEqual(
            move.move_line_ids.mapped('lot_id'), own,
            'El motor debe seguir reservando el lote EXCLUSIVO del pedido.')

    # ==================================================================
    # Candado — sin SQL crudo y motor SIN CAMBIOS
    # ==================================================================
    def test_touched_files_have_no_raw_sql_and_motor_untouched(self):
        module_path = get_module_path('printflow_gestion_inventario')
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)

        # El override vive SOLO en PrintFlow; el motor solo se HEREDA.
        from odoo.addons.printflow_gestion_inventario.models.stock_move import (
            StockMove as PrintflowStockMove)
        self.assertIn(
            PrintflowStockMove, type(self.env['stock.move']).mro(),
            'La clase de PrintFlow debe estar en el MRO de ``stock.move``.')
        motor_path = get_module_path('x_product_dimensional_pricing')
        with open(
                os.path.join(motor_path, 'models', 'stock_move.py'),
                encoding='utf-8') as handle:
            motor_source = handle.read()
        self.assertIn('_assign_exclusive_lot', motor_source)
        self.assertNotIn(
            _MOTOR_GUARDIAN, motor_source,
            'El motor x_product_dimensional_pricing NO debe conocer el guardián.')
