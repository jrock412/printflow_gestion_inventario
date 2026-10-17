# -*- coding: utf-8 -*-
"""Asignación de lote en una fila ``pending_order`` (PrintFlow · H-026).

Custodia el criterio **CA-1** del plan "ASIGNACIÓN DE LOTE EN BLOQUE desde la
bandeja": la vía POR FILA de una entrega en ORDEN pendiente.

Contexto (H-026): la bandeja produce, para el estado ``lot_missing``, UNA fila
por cada ORDEN de entrega pendiente sin lote (``kind='pending_order'``,
``res_model='stock.picking'``). El botón "Elegir lote" abría el selector, pero
"Asignar lote" lanzaba
``UserError('Este ítem no permite elegir un lote (tipo: pending_order)')`` porque
el mapa ``handlers`` de ``_pf_assign_lot_to_document`` no conocía ese tipo.

Con el handler ``_pf_assign_lot_on_pending_order_doc`` (D4) la vía por fila:

* resuelve el MOVIMIENTO activo del producto dentro del albarán y delega en el
  MISMO escritor NATIVO ``_pf_reassign_move_lot`` (protocolo de reserva nativo);
* **asigna SIN ``UserError``** y deja el movimiento reservado con el lote elegido.

Es de SOLO LECTURA sobre datos ajenos salvo la ÚNICA escritura del flujo (la
reserva NATIVA que dispara el selector con su guardia): crea sus propios
productos/albaranes y ``TransactionCase`` hace rollback al terminar.
"""

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
# porque el caso de CA-1 es NEUTRO (no hay lote previo ⇒ no es excepción).
PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')


@tagged('post_install', '-at_install')
class TestProductFlowLotPendingOrderAssign(TransactionCase):
    """CA-1: "Elegir lote" de una fila ``pending_order`` asigna SIN ``UserError``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Pending Order'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Picker = cls.env['printflow.flow.lot.picker']
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

    def _outgoing(self, product, qty=2.0):
        """Albarán de salida confirmado SIN reserva (fila ``pending_order``).

        Se confirma ANTES de que exista existencia: así Odoo no reserva nada por
        su cuenta y el movimiento queda SIN ``move_line`` (la bandeja produce la
        fila ``pending_order`` de la ORDEN).
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

    def _pending_row(self, tray, picking):
        """Fila ``pending_order`` de la ORDEN indicada."""
        row = tray.filtered(
            lambda r: r.kind == 'pending_order' and r.res_id == picking.id)[:1]
        self.assertTrue(row, 'Debe existir la fila pending_order de la orden.')
        return row

    def _picker_for(self, row):
        """Abre el selector de lote de la fila (ruta del operador)."""
        action = row.action_open_lot_picker()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.picker')
        self.assertEqual(action['target'], 'new')
        return self.Picker.browse(action['res_id'])

    # ==================================================================
    # CA-1 — la vía POR FILA asigna SIN ``UserError``
    # ==================================================================
    def test_ca1_pending_order_row_assigns_without_user_error(self):
        """Una fila ``pending_order`` reserva el lote elegido (H-026 resuelto)."""
        product = self._product('PENDING CA1')
        lot = self._lot(product, 'PENDING-CA1-LOTE')
        pick, move = self._outgoing(product, 2.0)
        # La existencia se crea DESPUÉS de confirmar: el movimiento está sin
        # reserva y la bandeja lo lista como ORDEN pendiente sin lote.
        self._stock(product, 10.0, lot=lot)

        tray = self._open_tray(product)
        row = self._pending_row(tray, pick)
        # (a) la fila es la dimensión OPERATIVA: apunta al albarán y admite lote.
        self.assertEqual(row.res_model, 'stock.picking')
        self.assertEqual(row.lot_action_mode, 'assign')
        self.assertTrue(row.can_choose_lot)

        picker = self._picker_for(row)
        # (b) el selector viaja con el tipo de ítem y el modelo de la fila.
        self.assertEqual(picker.target_kind, 'pending_order')
        self.assertEqual(picker.res_model, 'stock.picking')
        self.assertEqual(picker.res_id, pick.id)
        # (c) NEUTRO: la orden no tenía lote ⇒ asignar NO es excepción.
        self.assertFalse(picker.own_lot_name)
        self.assertFalse(picker.lot_name_actual)
        self.assertFalse(picker.is_exception)
        # (d) el lote con existencia en la ubicación del documento es candidato.
        self.assertIn(lot, picker.candidate_lot_ids)

        # (e) ejecutar "Asignar lote" ASIGNA sin ``UserError`` (antes reventaba).
        picker.lot_id = lot.id
        result = picker.action_assign_lot()

        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        # (f) la escritura es la reserva NATIVA del movimiento de la orden.
        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 2.0)
        self.assertIn(move.state, ('assigned', 'partially_available'))

    def test_ca1_pending_order_assignment_is_idempotent(self):
        """Reasignar el MISMO lote a la orden ya reservada no duplica líneas."""
        product = self._product('PENDING CA1 IDEMP')
        lot = self._lot(product, 'PENDING-CA1-IDEMP-LOTE')
        pick, move = self._outgoing(product, 3.0)
        self._stock(product, 10.0, lot=lot)

        tray = self._open_tray(product)
        row = self._pending_row(tray, pick)
        picker = self._picker_for(row)
        picker.lot_id = lot.id
        picker.action_assign_lot()

        # Segunda pasada por la MISMA ruta: la idempotencia del escritor NATIVO
        # deja el movimiento reservado con el lote elegido y sin líneas extra.
        picker2 = self._picker_for(self._pending_row(tray, pick))
        picker2.lot_id = lot.id
        picker2.action_assign_lot()

        self.assertIn(lot, move.move_line_ids.mapped('lot_id'))
        self.assertAlmostEqual(
            sum(move.move_line_ids.mapped('quantity')), 3.0)
        self.assertEqual(len(move.move_line_ids), 1)
