# -*- coding: utf-8 -*-
"""§3.V · Lote 1 (T1–T3): la autorización de LOTE apunta al LOTE (H-065/H-066).

Custodia los criterios de aceptación del plan §3.V (el caso real del DTF: un
producto gestionado con DOS lotes genéricos reservados en DOS movimientos):

* CA-1: autorizar UN lote deja el estado en ``lot_generic``.
* CA-2: autorizar los DOS lotes deja el estado en ``lot_ok`` (el nodo se apaga).
* CA-3: confirmar el wizard "Autorizar lote" crea UNA excepción
  ``lot_generic`` con ``target_model='stock.lot'`` y ``target_id=<lote>`` **y
  conserva** la escritura en ``printflow.lot.exception`` (la que apaga la MEZCLA
  en el motor).
* CA-4: una excepción ``lot_generic`` creada con ``target_model='stock.move'``
  (las históricas del DTF) NO apaga el hallazgo ni aparece en
  ``_pf_suppressed_targets('lot_generic')``.
* CA-5: la fila de la bandeja resuelve su destino FORMAL por el registry (el
  lote, aunque la fila pinte el ``stock.move``) y la vía formal de bloque apunta
  al MISMO destino.
* CA-6: ``lot_missing`` (``stock.move``) y ``lot_unassigned_finished``
  (``mrp.production``) siguen igual, sin regresión.
* CA-7 (H-067): la excepción formal de un hallazgo de LOTE se etiqueta con el
  NOMBRE DEL LOTE, nunca con el documento de la fila.

SOLO LECTURA sobre datos ajenos: crea sus propios registros y ``TransactionCase``
hace rollback. NO se acciona ningún botón con efecto sobre datos reales.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotExceptionLotTarget(TransactionCase):
    """El destino de la excepción de lote lo manda el registry, no la fila."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente §3.V Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.uom = (
            cls.env.ref('uom.product_uom_meter', raise_if_not_found=False)
            or cls.env.ref('uom.product_uom_unit'))
        cls.Exception = cls.env['printflow.finding.exception']
        cls.Filter = cls.env['printflow.finding.exception.filter']
        cls.Registry = cls.env['printflow.finding.exception.registry']
        cls.Health = cls.env['printflow.stock.health']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Authorize = cls.env['printflow.flow.lot.exception.authorize']
        cls.AuthorizeBulk = cls.env[
            'printflow.flow.lot.exception.authorize.bulk']
        cls.LotException = cls.env['printflow.lot.exception']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        """Producto gestionado y por lote (el caso del DTF: UdM ``m``)."""
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'uom_id': self.uom.id,
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _outgoing(self, product, qty, lot):
        """Albarán de salida con una línea por lote (una unidad por movimiento)."""
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
        line = self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'quantity': qty,
            'lot_id': lot.id if lot else False,
        })
        # Al confirmar, Odoo puede reservar por FIFO y añadir su propia línea:
        # se quita la que no es la del lote pedido para que la fila de la
        # bandeja sea DETERMINISTA (una línea por movimiento).
        (move.move_line_ids - line).unlink()
        return picking, move

    def _two_generic_lots(self, name):
        """El caso del DTF: 2 lotes genéricos con existencia, en 2 movimientos."""
        product = self._product(name)
        lot_a = self._lot(product, '%s-GENERICO-A' % name)
        lot_b = self._lot(product, '%s-GENERICO-B' % name)
        self._stock(product, 10.0, lot_a)
        self._stock(product, 10.0, lot_b)
        _picking_a, move_a = self._outgoing(product, 1.0, lot_a)
        _picking_b, move_b = self._outgoing(product, 1.0, lot_b)
        return product, lot_a, lot_b, move_a, move_b

    def _tray_row(self, product, lot):
        rows = self.Tray._pf_populate(product, 'lot_generic')
        row = rows.filtered(lambda rec: rec.lot_id.id == lot.id)[:1]
        self.assertTrue(row, 'La bandeja debe listar el lote genérico.')
        return row

    def _formal_exceptions(self, finding_code, target_model):
        return self.Exception.search([
            ('finding_code', '=', finding_code),
            ('target_model', '=', target_model),
        ])

    # ==================================================================
    # CA-1: autorizar UN lote deja el estado en `lot_generic`
    # ==================================================================
    def test_ca1_one_lot_authorized_keeps_lot_generic(self):
        product, lot_a, lot_b, _move_a, _move_b = self._two_generic_lots(
            'SEGV CA1')
        raw = self.Health._pf_lot_state(product)
        self.assertEqual(raw['state'], 'lot_generic')
        self.assertEqual(set(raw['generic_lot_ids']), {lot_a.id, lot_b.id})

        self.Exception._pf_authorize(
            'lot_generic', 'stock.lot', lot_a.id, reason='Autorizado uno solo.')

        filtered = self.Filter._pf_apply_to_lot_info(
            product, self.Health._pf_lot_state(product))
        self.assertEqual(filtered['state'], 'lot_generic')
        self.assertEqual(set(filtered['generic_lot_ids']), {lot_b.id})

    # ==================================================================
    # CA-2: autorizar los DOS lotes deja el estado en `lot_ok`
    # ==================================================================
    def test_ca2_both_lots_authorized_reaches_lot_ok(self):
        product, lot_a, lot_b, _move_a, _move_b = self._two_generic_lots(
            'SEGV CA2')
        raw = self.Health._pf_lot_state(product)
        filtered = self.Filter._pf_apply_to_lot_info(product, raw)
        self.assertEqual(raw['state'], 'lot_generic')
        self.assertEqual(set(raw['generic_lot_ids']), {lot_a.id, lot_b.id})
        self.assertEqual(set(filtered['generic_lot_ids']),
                         {lot_a.id, lot_b.id})
        rows = self.Tray._pf_populate(product, 'lot_generic')
        self.assertEqual(len(rows), 2, 'Una fila por movimiento (2 lotes).')
        self.assertEqual(set(rows.mapped('lot_id').ids), {lot_a.id, lot_b.id})

        action = rows.action_authorize_selected()
        wizard = self.AuthorizeBulk.browse(action['res_id'])
        self.assertEqual(len(wizard.lot_ids), 2)
        self.assertEqual(wizard.finding_code, 'lot_generic')
        wizard.reason = 'Los dos lotes del DTF son intencionales.'
        wizard.action_authorize()

        filtered = self.Filter._pf_apply_to_lot_info(
            product, self.Health._pf_lot_state(product))
        self.assertEqual(filtered['state'], 'lot_ok')
        self.assertFalse(filtered['generic_lot_ids'])
        # El nodo deja de pintarse: la bandeja queda vacía.
        self.assertFalse(self.Tray._pf_populate(product, 'lot_generic'))
        for lot in (lot_a, lot_b):
            self.assertTrue(self.Exception.search([
                ('finding_code', '=', 'lot_generic'),
                ('target_model', '=', 'stock.lot'),
                ('target_id', '=', lot.id)]))

    # ==================================================================
    # CA-3: el wizard crea la excepción sobre el LOTE y conserva la de mezcla
    # ==================================================================
    def test_ca3_lot_wizard_creates_formal_exception_on_lot(self):
        product, lot_a, _lot_b, _move_a, _move_b = self._two_generic_lots(
            'SEGV CA3')
        row = self._tray_row(product, lot_a)
        # La fila pinta el DOCUMENTO (stock.move)…
        self.assertEqual(row.res_model, 'stock.move')
        self.assertEqual(row.finding_code, 'lot_generic')

        action = row.action_authorize_lot()
        self.assertEqual(
            action['res_model'], 'printflow.flow.lot.exception.authorize')
        wizard = self.Authorize.browse(action['res_id'])
        self.assertEqual(wizard.finding_code, 'lot_generic')
        wizard.reason = 'Lote genérico intencional (caso DTF).'
        result = wizard.action_authorize()
        self.assertEqual(result['tag'], 'display_notification')

        # …pero la excepción FORMAL vive sobre el LOTE.
        formal = self._formal_exceptions('lot_generic', 'stock.lot')
        self.assertEqual(set(formal.mapped('target_id')), {lot_a.id})
        self.assertEqual(formal.lot_id, lot_a)
        # Y la de MEZCLA (motor) se conserva intacta.
        self.assertTrue(self.LotException.search([('lot_id', '=', lot_a.id)]))

    # ==================================================================
    # CA-4: una excepción con target `stock.move` NO apaga el lote (H-066)
    # ==================================================================
    def test_ca4_move_targeted_exception_does_not_suppress_lot(self):
        product, lot_a, lot_b, move_a, _move_b = self._two_generic_lots(
            'SEGV CA4')
        # Espejo de las 4 excepciones históricas del DTF.
        self.Exception._pf_authorize(
            'lot_generic', 'stock.move', move_a.id, reason='Histórica.')

        suppressed = self.Exception._pf_suppressed_targets('lot_generic')
        self.assertNotIn(move_a.id, suppressed)
        self.assertEqual(suppressed, set())

        filtered = self.Filter._pf_apply_to_lot_info(
            product, self.Health._pf_lot_state(product))
        self.assertEqual(filtered['state'], 'lot_generic')
        self.assertEqual(set(filtered['generic_lot_ids']), {lot_a.id, lot_b.id})

    # ==================================================================
    # CA-5: la fila y la vía formal de bloque apuntan al LOTE
    # ==================================================================
    def test_ca5_tray_and_formal_path_point_to_lot(self):
        product, lot_a, _lot_b, _move_a, _move_b = self._two_generic_lots(
            'SEGV CA5')
        row = self._tray_row(product, lot_a)

        target_model, target_id = row._pf_formal_target()
        self.assertEqual((target_model, target_id), ('stock.lot', lot_a.id))
        self.assertTrue(row.can_authorize_finding)

        # Vía formal POR FILA: el wizard apunta al lote.
        action = row.action_authorize_finding()
        wizard = self.env['printflow.finding.exception.authorize'].browse(
            action['res_id'])
        self.assertEqual(wizard.target_model, 'stock.lot')
        self.assertEqual(wizard.target_id, lot_a.id)

        # Vía formal EN BLOQUE: la línea del wizard también apunta al lote.
        action_bulk = row.action_authorize_selected_findings()
        bulk = self.env[
            'printflow.finding.exception.authorize.bulk'].browse(
                action_bulk['res_id'])
        self.assertEqual(set(bulk.line_ids.mapped('target_model')),
                         {'stock.lot'})
        self.assertEqual(bulk.line_ids.target_id, lot_a.id)

    # ==================================================================
    # CA-6: `lot_missing` y `lot_unassigned_finished` siguen igual
    # ==================================================================
    def test_ca6_other_findings_untouched(self):
        # (a) lot_missing: destino `stock.move`, la fila NO tiene lote y AUN ASÍ
        #     se puede autorizar (sin regresión).
        product = self._product('SEGV CA6 ENTREGA')
        self._outgoing(product, 1.0, lot=None)
        rows = self.Tray._pf_populate(product, 'lot_missing')
        row = rows[:1]
        self.assertTrue(row, 'La bandeja debe listar la entrega sin lote.')
        self.assertFalse(row.lot_id)
        self.assertEqual(row._pf_formal_target(), ('stock.move', row.res_id))
        self.assertTrue(row.can_authorize_finding)
        self.Exception._pf_authorize(
            'lot_missing', 'stock.move', row.res_id, reason='Sin lote, aceptado.')
        self.assertIn(row.res_id,
                      self.Exception._pf_suppressed_targets('lot_missing'))

        # (b) lot_unassigned_finished: destino `mrp.production` (MO sin lote).
        product_mo = self._product('SEGV CA6 MO')
        manu_type = self.warehouse.manu_type_id
        mo = self.env['mrp.production'].create({
            'product_id': product_mo.id,
            'product_qty': 1.0,
            'product_uom_id': product_mo.uom_id.id,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
        })
        mo.write({'state': 'done'})
        mo_rows = self.Tray._pf_populate(product_mo, 'lot_unassigned_finished')
        mo_row = mo_rows[:1]
        self.assertTrue(mo_row, 'La bandeja debe listar la MO sin lote.')
        self.assertEqual(mo_row._pf_formal_target(), ('mrp.production', mo.id))
        self.assertTrue(mo_row.can_authorize_finding)

    # ==================================================================
    # CA-7 (H-067): la etiqueta de la excepción dice el LOTE, no el documento
    # ==================================================================
    def test_ca7_lot_exception_label_is_the_lot_name(self):
        product, lot_a, lot_b, _move_a, _move_b = self._two_generic_lots(
            'SEGV CA7')
        row = self._tray_row(product, lot_a)
        # La fila pinta el DOCUMENTO que usa el lote…
        self.assertTrue(row.label.startswith('Movimiento '),
                        'La fila de lote pinta el documento (no el lote).')
        # …pero la ETIQUETA de la excepción es el nombre del lote.
        self.assertEqual(row._pf_formal_label(), lot_a.name)

        # (a) Vía formal POR FILA: el wizard y el registro guardan el lote.
        action = row.action_authorize_finding()
        wizard = self.env['printflow.finding.exception.authorize'].browse(
            action['res_id'])
        self.assertEqual(wizard.target_model, 'stock.lot')
        self.assertEqual(wizard.target_label, lot_a.name)
        wizard.reason = 'Lote genérico intencional (H-067).'
        wizard.action_authorize()
        formal = self._formal_exceptions('lot_generic', 'stock.lot')
        self.assertEqual(formal.target_label, lot_a.name)

        # (b) Vía formal EN BLOQUE: la línea del wizard también dice el lote.
        row_b = self._tray_row(product, lot_b)
        action_bulk = row_b.action_authorize_selected_findings()
        bulk = self.env[
            'printflow.finding.exception.authorize.bulk'].browse(
                action_bulk['res_id'])
        self.assertEqual(bulk.line_ids.target_label, lot_b.name)
        self.assertEqual(bulk.line_ids.target_id, lot_b.id)

        # (c) Sin regresión: un hallazgo de MOVIMIENTO conserva su rótulo.
        product_move = self._product('SEGV CA7 ENTREGA')
        self._outgoing(product_move, 1.0, lot=None)
        move_row = self.Tray._pf_populate(product_move, 'lot_missing')[:1]
        self.assertEqual(move_row._pf_formal_target(),
                         ('stock.move', move_row.res_id))
        self.assertEqual(move_row._pf_formal_label(), move_row.label)
        self.assertTrue(move_row.label.startswith('Movimiento '))
