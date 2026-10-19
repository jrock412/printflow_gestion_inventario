# -*- coding: utf-8 -*-
"""Detalle del resultado y rótulos del wizard de asignación en bloque (H-029/H-031).

Custodia los criterios CA-3/CA-4 del plan de las incidencias del wizard de
asignación en bloque, ya con el grano NUEVO (§3.O · H-039/H-040): cada fila del
contenedor es un MOVIMIENTO (una unidad / línea de pedido) y los conteos del
detalle se llevan POR UNIDAD.

* **CA-3 (H-029)** — tras una asignación en bloque con errores/omisiones, el
  operador LEE el motivo por destino: la acción sigue devolviendo la
  ``display_notification`` con el MISMO texto de los 4 conteos y AHORA encadena
  (``params['next']``) el detalle ``printflow.flow.lot.assign.bulk.result``, con
  UNA fila por MOVIMIENTO (una unidad) y ``result_note`` NO vacío en las filas
  ``error``/``skipped``. Los 4 conteos (asignadas/parciales/omitidas/error) son
  por UNIDAD: una fila = un movimiento.
* **CA-1 (H-032)** — la acción ANIDADA en ``params['next']`` declara
  ``views == [(False, 'form')]``: Odoo solo normaliza ``views`` en la acción de
  PRIMER nivel, así que sin ella el cliente revienta en
  ``action_service.js::_preprocessAction`` (``action.views.map``).
* **CA-4 (H-031 / H-047)** — la ranura "Selección" declara su unidad: "Unidades
  por asignar" / "Unidades a entregar" / "Filas omitidas" + el texto aclaratorio
  VISIBLE ``selection_note``, que declara qué ES cada fila (una UNIDAD = un
  movimiento de la entrega = una línea de pedido) SIN repetir los conteos ya
  rotulados al lado (D-8 de §3.P); ``total_demand`` CONSERVA su ``digits``.

Es de SOLO LECTURA sobre datos ajenos salvo la ÚNICA escritura del flujo (la
reasignación NATIVA de reserva que dispara el wizard con su guardia y su motivo):
crea sus propios productos/albaranes y ``TransactionCase`` hace rollback.
"""

import os

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
# Política de asignación por excepción (cero hardcodeo): se fija en ``warn``.
PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')

_MODULE = 'printflow_gestion_inventario'

# Archivos tocados por la tarea (se audita que no usen SQL crudo).
_TOUCHED_FILES = (
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk.py'),
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk_result.py'),
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk_result_line.py'),
)


@tagged('post_install', '-at_install')
class TestProductFlowLotAssignBulkResult(TransactionCase):
    """El detalle por destino y los rótulos de la ranura "Selección"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Detalle Bloque'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Bulk = cls.env['printflow.flow.lot.assign.bulk']
        cls.Result = cls.env['printflow.flow.lot.assign.bulk.result']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
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

    def _outgoing(self, product, qty=2.0):
        """Albarán de salida confirmado SIN reserva (fila ``pending_order``)."""
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
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        return self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])

    def _wizard_for(self, selection):
        action = selection.action_assign_lot_bulk()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.assign.bulk')
        return self.Bulk.browse(action['res_id'])

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

    # ==================================================================
    # CA-3 — la notificación encadena el detalle con el motivo por destino
    # ==================================================================
    def test_ca3_notification_chains_detail_with_reasons(self):
        product = self._product('RESULT CA3')
        lot = self._lot(product, 'RESULT-CA3-LOTE')
        pick_a, move_a = self._outgoing(product, 3.0)
        pick_b, move_b = self._outgoing(product, 3.0)
        self._stock(product, 2.0, lot)          # lote ESCASO (2 para 6)

        tray = self._open_tray(product)
        pending = tray.filtered(lambda row: row.kind == 'pending_order')
        self.assertEqual(set(pending.mapped('res_id')), {pick_a.id, pick_b.id})

        bulk = self._wizard_for(pending)
        # Decisión POR UNIDAD (H-039/H-040): el MISMO lote (2 u) se elige en
        # CADA fila; la parcial ya no se bloquea en bloque (CA-7).
        for line in bulk.line_ids:
            line.lot_id = lot.id
        bulk.reason = 'Detalle por destino.'
        result = bulk.action_assign_lot_bulk()

        # (a) la notificación conserva el MISMO texto de los 4 conteos (CA-7),
        # ahora POR UNIDAD: una entrega con N unidades produce N filas.
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(
            result['params']['message'],
            '0 asignadas · 1 parciales · 0 omitidas · 1 con error.')

        # (b) AHORA encadena el detalle (H-029).
        nxt = result['params']['next']
        self.assertEqual(nxt['type'], 'ir.actions.act_window')
        self.assertEqual(
            nxt['res_model'], 'printflow.flow.lot.assign.bulk.result')
        self.assertEqual(nxt['target'], 'new')
        # CA-1 (H-032): la acción ANIDADA en `params['next']` declara `views`
        # (Odoo NO lo normaliza en el segundo nivel) ⇒ sin ella el cliente
        # revienta en `_preprocessAction` (`action.views.map`).
        self.assertEqual(nxt['views'], [(False, 'form')])
        detail = self.Result.browse(nxt['res_id'])

        # (c) UNA fila por destino, con el resultado y su motivo completo.
        self.assertEqual(len(detail.line_ids), len(bulk.line_ids))
        self.assertEqual(detail.partial_count, 1)
        self.assertEqual(detail.error_count, 1)
        for line in detail.line_ids:
            self.assertEqual(line.result, bulk.line_ids.filtered(
                lambda src: src.seq == line.seq).result)
        error_lines = detail.line_ids.filtered(
            lambda line: line.result == 'error')
        self.assertTrue(error_lines)
        self.assertTrue(all(line.result_note for line in error_lines))
        self.assertIn(lot, (move_a | move_b).move_line_ids.mapped('lot_id'))

    def test_ca3_omitted_destination_is_listed_in_detail(self):
        """El detalle muestra TAMBIÉN las filas omitidas (con su motivo)."""
        product = self._product('RESULT CA3 OMITIDA')
        lot = self._lot(product, 'RESULT-CA3-OMITIDA-LOTE')
        pick_a, move_a = self._outgoing(product, 3.0)
        pick_b, move_b = self._outgoing(product, 3.0)
        pick_c, move_c = self._outgoing(product, 1.0)
        self._stock(product, 2.0, lot)

        rows = [
            self._raw_row(pick_a, move_a, 3.0),
            self._raw_row(pick_b, move_b, 3.0),
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
        bulk = self.Bulk._pf_populate(product, rows)
        self.assertEqual(bulk.assignable_count, 2)
        self.assertEqual(bulk.omitted_count, 1)
        self.assertEqual(len(bulk.line_ids), 3)
        for line in bulk.line_ids:
            line.lot_id = lot.id
        bulk.reason = 'Detalle con omitidas.'
        result = bulk.action_assign_lot_bulk()

        self.assertEqual(
            result['params']['message'],
            '0 asignadas · 1 parciales · 1 omitidas · 1 con error.')
        # La acción encadenada SIEMPRE declara `views` (CA-1/H-032).
        self.assertEqual(
            result['params']['next']['views'], [(False, 'form')])
        detail = self.Result.browse(result['params']['next']['res_id'])
        self.assertEqual(len(detail.line_ids), 3)
        skipped = detail.line_ids.filtered(lambda line: line.result == 'skipped')
        self.assertEqual(len(skipped), 1)
        self.assertTrue(skipped.result_note)
        self.assertEqual(detail.error_count, 1)
        self.assertTrue(
            all(line.result_note for line in detail.line_ids.filtered(
                lambda line: line.result in ('error', 'skipped'))))

    # ==================================================================
    # CA-4 — rótulos y texto aclaratorio VISIBLE
    # ==================================================================
    def test_ca4_selection_labels_and_note(self):
        fields = self.env['printflow.flow.lot.assign.bulk'].fields_get(
            ['total_demand', 'assignable_count', 'omitted_count',
             'selection_note'])
        self.assertEqual(fields['total_demand']['string'], 'Unidades a entregar')
        self.assertEqual(
            fields['assignable_count']['string'], 'Unidades por asignar')
        self.assertEqual(fields['omitted_count']['string'], 'Filas omitidas')
        # ``total_demand`` CONSERVA su ``digits`` (D3): sin sufijos inventados.
        field = self.env['printflow.flow.lot.assign.bulk']._fields['total_demand']
        self.assertEqual(field._digits, 'Product Unit of Measure')

        product = self._product('RESULT CA4')
        lot = self._lot(product, 'RESULT-CA4-LOTE')
        pick_a, move_a = self._outgoing(product, 3.0)
        pick_b, move_b = self._outgoing(product, 3.0)
        self._stock(product, 10.0, lot)
        bulk = self.Bulk._pf_populate(product, [
            self._raw_row(pick_a, move_a, 3.0),
            self._raw_row(pick_b, move_b, 3.0),
        ])
        self.assertAlmostEqual(bulk.total_demand, 6.0)
        self.assertEqual(bulk.assignable_count, 2)
        self.assertEqual(
            bulk.selection_note,
            'Cada fila es una unidad: un movimiento de la entrega = una línea '
            'de pedido.')

    # ==================================================================
    # Candado — sin SQL crudo
    # ==================================================================
    def test_touched_files_have_no_raw_sql(self):
        module_path = get_module_path(_MODULE)
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)
