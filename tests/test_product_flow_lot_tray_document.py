# -*- coding: utf-8 -*-
"""Bandeja de lote: columna "Documento" agnóstica + modo de acción (PrintFlow).

Custodia las tres piezas añadidas a ``printflow.flow.lot.tray`` (SIN tocar el
contrato existente):

  * ``document_ref`` (``fields.Reference`` computado): EMPAQUETA el par
    ``(res_model, res_id)`` como un único valor navegable, agnóstico al modelo
    de la fila (lista blanca: ``stock.move``, ``stock.picking``,
    ``mrp.production``, ``purchase.order``, ``sale.order``, ``stock.quant``,
    ``stock.lot``). NO sustituye a ``res_model``/``res_id`` (se conservan).
  * ``lot_action_mode`` (``Selection`` computado): ``create`` (OF con lote
    sugerido), ``assign`` (el resto) o ``reconcile`` (reserva huérfana).
  * ``action_open()`` intacto: navega al registro o cierra si no hay documento.

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar. Los helpers replican el mínimo
del patrón de ``test_product_flow_lot_tray.py`` / ``..._ux.py`` (mismos
constructores de albarán/MO/quant), sin acoplarse a sus métodos de instancia.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotTrayDocument(TransactionCase):
    """La bandeja expone un Documento navegable y un modo por fila."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Tray Documento'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']

    # ------------------------------------------------------------------
    # Utilidades (mismo andamiaje que test_product_flow_lot_tray.py)
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

    def _orphan_reservation(self, product, reserved=5.0):
        """Reserva SIN movimiento que la respalde -> quant huérfano."""
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, 1.0, reserved_quantity=reserved)

    def _outgoing(self, product, qty=2.0, lot=None, sale_line=None):
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
        if sale_line:
            move.sale_line_id = sale_line.id
        return picking, move

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

    def _sale_line(self, product, qty=2.0):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        return order.order_line.filtered(
            lambda line: line.product_id == product)[:1]

    def _open_tray(self, product, lot_state):
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        action = wizard.action_run_pf_plan(lot_state, 'solution')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')
        tray = self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])
        self.assertTrue(tray, 'La bandeja debe traer al menos una fila.')
        return tray

    def _row_for(self, tray, res_model, res_id):
        return tray.filtered(
            lambda r: r.res_model == res_model and r.res_id == res_id)[:1]

    # ==================================================================
    # 1) document_ref empaqueta (res_model, res_id) para cada caso
    # ==================================================================
    def test_document_ref_packs_model_and_id_per_kind(self):
        # no_stock_lot y generic_lot apuntan a un stock.move (documento).
        no_stock = self._product('DOC NO STOCK')
        ghost = self._lot(no_stock, 'DOC-FANTASMA')
        _p, move_ns = self._outgoing(no_stock, 2.0, lot=ghost)
        row = self._row_for(
            self._open_tray(no_stock, 'lot_no_stock'), 'stock.move', move_ns.id)
        self.assertTrue(row)
        self.assertEqual(row.kind, 'no_stock_lot')
        self._assert_document_ref(row, 'stock.move', move_ns.id)

        generic = self._product('DOC GENERICO')
        gen_lot = self._lot(generic, 'LOTE-GENERICO-DOC')
        self._stock(generic, 10.0, lot=gen_lot)
        _p, move_gen = self._outgoing(generic, 2.0, lot=gen_lot)
        row = self._row_for(
            self._open_tray(generic, 'lot_generic'), 'stock.move', move_gen.id)
        self.assertTrue(row)
        self._assert_document_ref(row, 'stock.move', move_gen.id)

        # missing_move: movimiento de salida sin lote -> stock.move.
        missing = self._product('DOC MISSING')
        _p, move_missing = self._outgoing(missing, 2.0, lot=None)
        row = self._row_for(
            self._open_tray(missing, 'lot_missing'), 'stock.move',
            move_missing.id)
        self.assertTrue(row)
        self._assert_document_ref(row, 'stock.move', move_missing.id)

        # unassigned_mo: OF terminada sin lote -> mrp.production.
        mo_product = self._product('DOC MO SIN LOTE')
        mo = self._mo_done_without_lot(mo_product)
        row = self._row_for(
            self._open_tray(mo_product, 'lot_unassigned_finished'),
            'mrp.production', mo.id)
        self.assertTrue(row)
        self._assert_document_ref(row, 'mrp.production', mo.id)

        # orphan_quant: reserva huérfana -> stock.quant.
        orphan = self._product('DOC HUERFANO')
        self._orphan_reservation(orphan)
        tray = self._open_tray(orphan, 'lot_orphan_reservation')
        row = tray.filtered(lambda r: r.res_model == 'stock.quant')[:1]
        self.assertTrue(row)
        quant = self.env['stock.quant'].browse(row.res_id)
        self._assert_document_ref(row, 'stock.quant', quant.id)

    def _assert_document_ref(self, row, model, res_id):
        """El Reference resuelve el MISMO par (modelo, id) que res_model/res_id."""
        self.assertEqual(row.res_model, model)
        self.assertEqual(row.res_id, res_id)
        self.assertEqual(row.document_ref._name, model)
        self.assertEqual(row.document_ref.id, res_id)
        raw = row.read(['document_ref'])[0]['document_ref']
        self.assertEqual(raw, '%s,%s' % (model, res_id))

    # ==================================================================
    # 2) Leer document_ref de varias filas resuelve display_name
    # ==================================================================
    def test_document_ref_resolves_display_name_for_many_rows(self):
        product = self._product('DOC DISPLAY NAME')
        ghost = self._lot(product, 'DOC-DISPLAY-FANTASMA')
        moves = [self._outgoing(product, 1.0, lot=ghost)[1] for _ in range(3)]
        tray = self._open_tray(product, 'lot_no_stock')
        rows = tray.filtered(lambda r: r.res_id in [m.id for m in moves])
        self.assertEqual(len(rows), 3, 'Deben existir las TRES filas.')
        for row in rows:
            self.assertEqual(row.document_ref._name, 'stock.move')
            self.assertTrue(
                row.document_ref.display_name,
                'El documento debe resolver un display_name legible.')

    # ==================================================================
    # 3) El cómputo de document_ref NO consulta la BD por fila (sin N+1)
    # ==================================================================
    def test_document_ref_compute_has_no_n_plus_one(self):
        product = self._product('DOC PRESUPUESTO')
        ghost = self._lot(product, 'DOC-PRESUPUESTO-FANTASMA')
        for _ in range(6):
            self._outgoing(product, 1.0, lot=ghost)
        tray = self._open_tray(product, 'lot_no_stock')
        self.assertGreaterEqual(len(tray), 6, 'Se esperaban >=6 filas.')

        # Warm-up + medida: solo el CÓMPUTO de document_ref (no la resolución
        # del display_name, que es una lectura del registro destino por diseño).
        self.env.flush_all()
        self.env.cr.flush()
        start = self.cr.sql_log_count
        for row in tray:
            _ = row.document_ref
        self.env.flush_all()
        self.env.cr.flush()
        delta = self.cr.sql_log_count - start
        self.assertLessEqual(
            delta, 3,
            'El cómputo de document_ref no debe crecer con las filas '
            '(N+1 detectado: %s consultas para %s filas).' % (delta, len(tray)))

    # ==================================================================
    # 4) lot_action_mode: mapa explícito por caso
    # ==================================================================
    def test_lot_action_mode_create_for_mo_with_suggested_lot(self):
        product = self._product('MODO MO CON SUGERIDO')
        line = self._sale_line(product)
        mo = self._mo_done_without_lot(product, origin=line.order_id.name)
        row = self._row_for(
            self._open_tray(product, 'lot_unassigned_finished'),
            'mrp.production', mo.id)
        self.assertTrue(row)
        self.assertTrue(row.own_lot_name)
        self.assertEqual(row.lot_action_mode, 'create')

    def test_lot_action_mode_assign_for_mo_without_suggested_lot(self):
        product = self._product('MODO MO SIN SUGERIDO')
        mo = self._mo_done_without_lot(product)  # sin pedido -> sin sugerido
        row = self._row_for(
            self._open_tray(product, 'lot_unassigned_finished'),
            'mrp.production', mo.id)
        self.assertTrue(row)
        self.assertFalse(row.own_lot_name)
        self.assertEqual(row.lot_action_mode, 'assign')

    def test_lot_action_mode_reconcile_for_orphan_quant(self):
        product = self._product('MODO HUERFANO')
        self._orphan_reservation(product)
        tray = self._open_tray(product, 'lot_orphan_reservation')
        self.assertTrue(tray)
        self.assertEqual(set(tray.mapped('lot_action_mode')), {'reconcile'})

    def test_lot_action_mode_assign_for_lot_kinds(self):
        # missing_move -> assign
        missing = self._product('MODO MISSING')
        self._outgoing(missing, 2.0, lot=None)
        tray = self._open_tray(missing, 'lot_missing')
        self.assertTrue(tray)
        self.assertEqual(set(tray.mapped('lot_action_mode')), {'assign'})

        # no_stock_lot -> assign
        no_stock = self._product('MODO NO STOCK')
        ghost = self._lot(no_stock, 'MODO-NO-STOCK-L')
        self._outgoing(no_stock, 2.0, lot=ghost)
        tray = self._open_tray(no_stock, 'lot_no_stock')
        self.assertTrue(tray)
        self.assertEqual(set(tray.mapped('lot_action_mode')), {'assign'})

        # generic_lot -> assign
        generic = self._product('MODO GENERICO')
        gen_lot = self._lot(generic, 'LOTE-GENERICO-MODO')
        self._stock(generic, 10.0, lot=gen_lot)
        self._outgoing(generic, 2.0, lot=gen_lot)
        tray = self._open_tray(generic, 'lot_generic')
        self.assertTrue(tray)
        self.assertEqual(set(tray.mapped('lot_action_mode')), {'assign'})

    def test_lot_action_mode_assign_for_mixed_lot(self):
        product = self._product('MODO MEZCLADO')
        lot = self._lot(product, 'MODO-MEZCLADO-L1')
        self._stock(product, 10.0, lot=lot)
        self._outgoing(product, 2.0, lot=lot, sale_line=self._sale_line(product))
        self._outgoing(product, 2.0, lot=lot, sale_line=self._sale_line(product))
        tray = self._open_tray(product, 'lot_mixed')
        self.assertTrue(tray)
        self.assertEqual(set(tray.mapped('lot_action_mode')), {'assign'})

    # ==================================================================
    # 5) action_open() intacto: navega o cierra si no hay documento
    # ==================================================================
    def test_action_open_navigates_to_document(self):
        product = self._product('DOC ACTION OPEN')
        ghost = self._lot(product, 'DOC-ACTION-OPEN-L')
        _p, move = self._outgoing(product, 2.0, lot=ghost)
        row = self._row_for(
            self._open_tray(product, 'lot_no_stock'), 'stock.move', move.id)
        self.assertTrue(row)
        nav = row.action_open()
        self.assertEqual(nav['type'], 'ir.actions.act_window')
        self.assertEqual(nav['res_model'], 'stock.move')
        self.assertEqual(nav['res_id'], move.id)

    def test_action_open_closes_without_document(self):
        product = self._product('DOC ACTION CLOSE')
        row = self.Tray.create({'product_id': product.id})
        self.assertFalse(row.res_model)
        self.assertFalse(row.res_id)
        self.assertEqual(
            row.action_open(), {'type': 'ir.actions.act_window_close'})

    # ==================================================================
    # 6) Búsqueda del modo: el search method traduce a campos almacenados
    # ==================================================================
    def test_search_lot_action_mode_translates_to_stored_fields(self):
        self.assertEqual(
            self.Tray._pf_search_lot_action_mode('=', 'reconcile'),
            [('kind', '=', 'orphan_quant')])
        self.assertEqual(
            self.Tray._pf_search_lot_action_mode('=', 'create'),
            [('kind', '=', 'unassigned_mo'), ('own_lot_name', '!=', False)])
        assign = self.Tray._pf_search_lot_action_mode('=', 'assign')
        self.assertIn(('kind', 'in', (
            'missing_move', 'no_stock_lot', 'generic_lot', 'mixed_lot')), assign)
        # Operador no soportado: no rompe (no acota).
        self.assertEqual(
            self.Tray._pf_search_lot_action_mode('<>', 'create'), [])

    def test_search_document_ref_translates_to_model_and_id(self):
        self.assertEqual(
            self.Tray._pf_search_document_ref('=', 'stock.move,7'),
            [('res_model', '=', 'stock.move'), ('res_id', '=', 7)])
        # Sin id: solo por modelo.
        self.assertEqual(
            self.Tray._pf_search_document_ref('=', 'stock.move'),
            [('res_model', '=', 'stock.move')])
        # Texto: por nombre de modelo.
        self.assertEqual(
            self.Tray._pf_search_document_ref('ilike', 'stock'),
            [('res_model', 'ilike', 'stock')])
