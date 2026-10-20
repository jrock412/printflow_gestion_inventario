# -*- coding: utf-8 -*-
"""Reserva colgada REMONTADA POR DOCUMENTO (§3.S · Lote 1 · T2/T3).

La ventana "Solucionar" del ``data_anomaly`` deja de listar QUANTS y lista
UNA FILA POR DOCUMENTO: una fila por ``stock.move.line`` activa que sostiene
la reserva colgada (albarán u OF, socio, lote actual o "(sin lote)", cantidad
de la línea, "En marcha" y "Reservado por"), con acción ``release_document``
(saneo ACOTADO al documento de la fila), ``view_document`` (navegar) y
``leave`` aunque NO haya línea activa que lo respalde (caso FONDO NEGRO).

Son SOLO LECTURA sobre datos reales: el test crea SUS productos/albaranes/quants
y el ``TransactionCase`` hace rollback. Los T-A (código sí, datos no) se
respetan: ninguna escritura fuera de los propios fixtures.
"""
from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_EPS = 1e-6


@tagged('post_install', '-at_install')
class TestProductFlowFailureByDocument(
        PrintflowStockHealthTestMixin, TransactionCase):
    """La bandeja del colgado respira POR DOCUMENTO (T2) y navega (T3)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Por Documento'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'COLGADA POR DOCUMENTO EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.Tray = cls.env['printflow.flow.failure.tray']
        cls.Remedy = cls.env['printflow.stock.remedy']

    # ------------------------------------------------------------------
    # Utilidades (patrón del candado CA-4v · over_reservation_scoped)
    # ------------------------------------------------------------------
    def _outgoing(self, product, qty, lot=None):
        """Albarán de salida confirmado con su move line (lote opcional)."""
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
        return picking, move

    def _backed_quant(self, product, lot, qty):
        """Quant de un LOTE con existencia que RESPALDA su reserva (legítima)."""
        Quant = self.env['stock.quant'].sudo()
        Quant._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)
        quant = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.stock_location.id),
            ('lot_id', '=', lot.id)], limit=1)
        quant.write({'quantity': qty, 'reserved_quantity': qty})
        return quant

    def _hanging_quant(self, product, reserved, qty=0.0, location=None):
        """Quant SIN lote con reserva colgada (``reserved > quantity``)."""
        Quant = self.env['stock.quant'].sudo()
        Quant._update_available_quantity(
            product, location or self.stock_location, reserved)
        quant = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', '=', (location or self.stock_location).id),
            ('lot_id', '=', False)], limit=1)
        quant.write({'quantity': qty, 'reserved_quantity': reserved})
        return quant

    def _finished(self, name):
        product = self._pf_product(name, x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _duo(self):
        """Hanging cuantia SOSTENIDA por DOS entregas (una fila por documento)."""
        product = self._finished('COLGADA POR DOCUMENTO')
        picking_a, move_a = self._outgoing(product, 1.0)
        picking_b, move_b = self._outgoing(product, 1.0)
        self._hanging_quant(product, 2.0)
        return product, picking_a, move_a, picking_b, move_b

    def _of_fixture(self, picked=True, line_qty=0.2):
        """(mo, move, línea) de INSUMO sin albarán + quant colgado (0/0,2).

        El quant queda SIN existencia física (quantity=0, réservada 0,2): así
        el remontaje nativo NO tiene stock y el mensaje honesto confiesa
        "No había stock para re-reservar".
        """
        product = self._finished('COLGADA OF POR DOCUMENTO')
        manu_type = self.warehouse.manu_type_id
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
        })
        move = self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': 1.0,
            'product_uom': product.uom_id.id,
            'raw_material_production_id': mo.id,
            'location_id': self.stock_location.id,
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
        })
        move._action_confirm()
        line = self.env['stock.move.line'].create({
            'move_id': move.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': move.location_dest_id.id,
            'quantity': line_qty,
            'picked': picked,
        })
        quant = self._hanging_quant(product, line.quantity_product_uom, 0.0)
        return mo, move, line, quant

    # ══════════════════════════════════════════════════════════════════════
    # T2 — Evidencias POR DOCUMENTO
    # ══════════════════════════════════════════════════════════════════════
    def test_rows_per_document_with_fields(self):
        """UNA fila por move.line activa con los datos del documento."""
        product, picking_a, _move_a, picking_b, _move_b = self._duo()
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        rows = tray.line_ids
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.res_model, 'stock.move.line')
            self.assertEqual(row.document_model, 'stock.picking')
            self.assertIn(row.document_res_id, (picking_a.id, picking_b.id))
            self.assertEqual(row.document_kind, 'picking')
            self.assertEqual(row.line_qty, 1.0)
            self.assertFalse(row.picked)
            self.assertTrue(row.reserved_by)
            # Del QUANT compartido (que la fila sigue pintando):
            self.assertAlmostEqual(row.physical_qty, 0.0)
            self.assertAlmostEqual(row.reserved_qty, 2.0)
            self.assertAlmostEqual(row.delta_qty, -2.0)
            self.assertEqual(row.lot_name, '(sin lote)')
        names = {row.document_name for row in rows}
        self.assertEqual(
            names, {picking_a.name, picking_b.name})

    def test_fallback_quant_without_lines(self):
        """Colgado SIN línea activa ⇒ UNA fila de quant (nadie invisible)."""
        product = self._finished('COLGADA SIN LINEA ACTIVA')
        self._pf_add_stock(
            product, 1.0, reserved=2.0, location=self.extra_location)
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        rows = tray.line_ids
        self.assertEqual(len(rows), 1)
        row = rows[:1]
        self.assertEqual(row.res_model, 'stock.quant')
        self.assertEqual(row.document_kind, 'quant')
        self.assertFalse(row.document_model)
        self.assertFalse(row.document_res_id)
        self.assertIn('sin movimiento activo', row.detail)

    def test_actions_whitelist(self):
        """La lista blanca es release_document / view_document / leave."""
        product, _picking_a, _move_a, _picking_b, _move_b = self._duo()
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        keys = set(tray.line_ids.mapped('action_ids.key'))
        self.assertEqual(
            keys, {'release_document', 'view_document', 'leave'})
        primary = tray.line_ids.mapped(
            'action_ids').filtered('primary')[:1]
        self.assertEqual(primary.key, 'release_document')
        # Claves RETIRADAS de ESTA falla: no despachan (cierran).
        line = tray.line_ids[:1]
        for retired in ('release_reservation', 'clave_rara', 'view_quant'):
            action = tray.action_run(line.id, retired)
            self.assertEqual(
                action['type'], 'ir.actions.act_window_close')

    def test_release_document_row_fixture(self):
        """Accionar release_document en la fila OF: sin UserError y quant sano."""
        mo, _move, line, quant = self._of_fixture()
        tray = self.Tray._pf_populate(None, 'data_anomaly', line.product_id)
        rows = tray.line_ids
        self.assertEqual(len(rows), 1)
        row = rows[:1]
        self.assertEqual(row.res_model, 'stock.move.line')
        self.assertEqual(row.document_kind, 'production')
        self.assertEqual(row.document_model, 'mrp.production')
        self.assertEqual(row.document_res_id, mo.id)
        self.assertTrue(row.picked)

        action = tray.action_run(row.id, 'release_document')
        self.assertEqual(action['type'], 'ir.actions.client')
        message = action['params']['message']
        self.assertIn('saneada', message)
        # Sin stock para re-reservar ⇒ mensaje honesto en la misma fila:
        self.assertIn('No había stock para re-reservar', message)
        # CT-03/native: la línea SOSTENEDORA quedó ELIMINADA por
        # ``_do_unreserve`` al soltar la reserva del documento.
        self.assertFalse(line.exists())
        _move.invalidate_recordset(['picked'])
        quant.invalidate_recordset()
        self.assertFalse(_move.picked)
        self.assertLessEqual(
            quant.reserved_quantity, quant.quantity + _EPS)
        bodies = '\n'.join(msg.body or '' for msg in mo.message_ids)
        self.assertIn('en marcha', bodies)

    def test_healthy_delivery_not_listed(self):
        """La entrega SANA de la misma ubicación NO entra a las filas (H-022)."""
        product = self._finished('COLGADA SANA NO LISTADA')
        real_lot = self.env['stock.lot'].create(
            {'name': 'SANA-DOC-LOTE', 'product_id': product.id})
        picking_ok, move_ok = self._outgoing(product, 2.0, lot=real_lot)
        _picking_bad, _move_bad = self._outgoing(product, 3.0)
        self._backed_quant(product, real_lot, 2.0)
        self._hanging_quant(product, 3.0)

        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        rows = tray.line_ids
        self.assertEqual(len(rows), 1)
        row = rows[:1]
        healthy_line = move_ok.move_line_ids
        self.assertNotEqual(row.res_id, healthy_line.id)
        self.assertNotEqual(row.document_name, picking_ok.name)

    # ══════════════════════════════════════════════════════════════════════
    # T3 — Campos del documento en la fila + navegación view_document
    # ══════════════════════════════════════════════════════════════════════
    def test_document_fields_populated_on_row(self):
        """Todas las filas de T2 nacen CON los campos de documento poblados."""
        product, picking_a, _move_a, picking_b, _move_b = self._duo()
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        for row in tray.line_ids:
            self.assertTrue(row.document_name)
            self.assertTrue(row.document_model)
            self.assertTrue(row.document_res_id)
            self.assertTrue(row.partner_name)
        row_a = tray.line_ids.filtered(
            lambda l: l.document_res_id == picking_a.id)[:1]
        self.assertEqual(row_a.document_name, picking_a.name)
        self.assertEqual(row_a.document_kind, 'picking')
        row_b = tray.line_ids.filtered(
            lambda l: l.document_res_id == picking_b.id)[:1]
        self.assertEqual(row_b.document_model, 'stock.picking')

    def test_view_document_opens_picking_form(self):
        """view_document abre el FORM del albarán de la fila (target current)."""
        product, picking_a, _move_a, _picking_b, _move_b = self._duo()
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        row = tray.line_ids.filtered(
            lambda l: l.document_res_id == picking_a.id)[:1]
        action = tray.action_run(row.id, 'view_document')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['res_id'], picking_a.id)
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'current')
        self.assertEqual(action['name'], picking_a.name)

    def test_view_document_opens_production_form(self):
        """view_document abre el FORM de la OF cuando el documento es MO."""
        mo, _move, line, _quant = self._of_fixture()
        tray = self.Tray._pf_populate(None, 'data_anomaly', line.product_id)
        row = tray.line_ids[:1]
        action = tray.action_run(row.id, 'view_document')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'mrp.production')
        self.assertEqual(action['res_id'], mo.id)
        self.assertEqual(action['target'], 'current')
