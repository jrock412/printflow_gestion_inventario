# -*- coding: utf-8 -*-
"""§3.U · Lote 1 (T3) — el "después" de la reserva colgada.

Candadea las tres piezas del lote:
  * **T1** ``document_ref``: la fila expone el documento como **referencia
    nativa** (``stock.picking,<id>`` / ``mrp.production,<id>``), de modo que la
    lista lo pinta como enlace que abre el albarán o la OF; las filas de
    respaldo (``document_kind='quant'``) quedan SIN enlace;
  * **T2 · refresco (H-062)**: accionar una fila deja la bandeja **reabierta y
    repoblada** (``next`` = ``act_window``), nunca ``reload``: el operador ve el
    después sin rearmar el camino diagrama → Solucionar;
  * **T2 · SANEAR TODAS**: ``action_cleanup_all`` reusa el saneo que ya existe
    (``printflow.stock.health._pf_cleanup_products``) detrás del guardia
    ``_pf_assert_can_clean``, devuelve el **resumen en palabras** y revalida el
    código de la falla (la vista lo esconde; el método no se fía).

Son SOLO LECTURA sobre datos reales: el test crea SUS productos/albaranes/
quants y el ``TransactionCase`` hace rollback. Cero escrituras fuera del fixture
(código sí, datos no).
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_EPS = 1e-6


@tagged('post_install', '-at_install')
class TestProductFlowFailureTrayFeedback(
        PrintflowStockHealthTestMixin, TransactionCase):
    """El documento clickeable, el refresco en el sitio y el saneo de TODAS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Feedback Tray'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'COLGADA FEEDBACK EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.Tray = cls.env['printflow.flow.failure.tray']
        cls.Flow = cls.env['printflow.product.flow']

    # ------------------------------------------------------------------
    # Utilidades (mismo andamiaje del candado §3.S por documento)
    # ------------------------------------------------------------------
    def _finished(self, name):
        product = self._pf_product(name, x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _outgoing(self, product, qty):
        """Albarán de salida confirmado con su move line (sin lote)."""
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
        })
        return picking, move

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

    def _duo(self):
        """Colgado SOSTENIDO por DOS entregas ⇒ 2 documentos, 2 filas."""
        product = self._finished('COLGADA FEEDBACK')
        picking_a, _move_a = self._outgoing(product, 1.0)
        picking_b, _move_b = self._outgoing(product, 1.0)
        quant = self._hanging_quant(product, 2.0)
        return product, quant, picking_a, picking_b

    def _hanging_without_lines(self, name):
        """Colgado SIN línea activa (fila de respaldo ``document_kind='quant'``)."""
        product = self._finished(name)
        self._pf_add_stock(
            product, 1.0, reserved=2.0, location=self.extra_location)
        return product

    def _host(self, product):
        """Host del diagrama: la bandeja solo REABRE con un origen real."""
        return self.Flow.create({'product_id': product.id})

    # ==================================================================
    # T1 — document_ref: el documento como referencia NATIVA
    # ==================================================================
    def test_document_ref_points_to_the_document(self):
        """La fila expone ``stock.picking,<id>``; la de quant, sin enlace."""
        product, _quant, picking_a, picking_b = self._duo()
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)

        for row in tray.line_ids:
            self.assertEqual(row.document_kind, 'picking')
            self.assertEqual(row.document_ref._name, 'stock.picking')
            self.assertIn(
                row.document_ref.id, (picking_a.id, picking_b.id))
            # Formato de alambre de una Reference (lo que lee el cliente).
            self.assertEqual(
                row.read(['document_ref'])[0]['document_ref'],
                'stock.picking,%s' % row.document_res_id)

        # Las filas de respaldo (sin movimiento activo) NO tienen documento.
        orphan = self._hanging_without_lines('COLGADA FEEDBACK SIN LINEA')
        orphan_tray = self.Tray._pf_populate(None, 'data_anomaly', orphan)
        fallback = orphan_tray.line_ids[:1]
        self.assertEqual(fallback.document_kind, 'quant')
        self.assertFalse(fallback.document_ref)

    # ==================================================================
    # T2 — SANEAR TODAS: reusa el saneo, repuebla y resume en palabras
    # ==================================================================
    def test_cleanup_all_reopens_the_tray_clean(self):
        """Sanea todo, borra la bandeja vieja y reabre una VACÍA con resumen."""
        product, quant, _picking_a, _picking_b = self._duo()
        tray = self.Tray._pf_populate(
            self._host(product), 'data_anomaly', product)
        old_id = tray.id
        self.assertEqual(len(tray.line_ids), 2)

        action = tray.action_cleanup_all()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('0 documentos colgados', action['params']['message'])
        next_action = action['params']['next']
        self.assertEqual(next_action['type'], 'ir.actions.act_window')
        self.assertEqual(
            next_action['res_model'], 'printflow.flow.failure.tray')
        self.assertEqual(next_action['target'], 'new')
        self.assertNotEqual(next_action['res_id'], old_id)
        # La bandeja vieja se retiró (el poblado es idempotente por origen).
        self.assertFalse(tray.exists())
        new_tray = self.Tray.browse(next_action['res_id'])
        self.assertTrue(new_tray.exists())
        self.assertEqual(len(new_tray.line_ids), 0)
        # CT-03: la caché del ORM no revierte sola ⇒ invalidar antes de leer.
        quant.invalidate_recordset()
        self.assertLessEqual(
            quant.reserved_quantity, quant.quantity + _EPS)

    def test_cleanup_all_warns_when_nothing_could_be_released(self):
        """Producto SANO: no revienta; avisa con tono de atención."""
        product = self._finished('SANA SIN COLGADOS')
        tray = self.Tray._pf_populate(
            self._host(product), 'data_anomaly', product)
        self.assertFalse(tray.line_ids)

        action = tray.action_cleanup_all()

        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'success')
        self.assertIn('0 documentos colgados', action['params']['message'])

    # ==================================================================
    # T2 — Refresco en el sitio (H-062): la bandeja NO se cierra
    # ==================================================================
    def test_row_action_keeps_the_tray_open(self):
        """``release_document`` devuelve la bandeja repoblada, no un reload."""
        product, _quant, _picking_a, _picking_b = self._duo()
        tray = self.Tray._pf_populate(
            self._host(product), 'data_anomaly', product)
        old_id = tray.id
        row = tray.line_ids[:1]

        action = tray.action_run(row.id, 'release_document')

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertTrue(action['params']['message'])
        next_action = action['params']['next']
        self.assertEqual(next_action['type'], 'ir.actions.act_window')
        self.assertEqual(
            next_action['res_model'], 'printflow.flow.failure.tray')
        # El "después": la fila accionada ya no está (o queda la de otro
        # documento), y NO se cierra la ventana.
        self.assertNotEqual(next_action['res_id'], old_id)
        self.assertFalse(tray.exists())
        new_tray = self.Tray.browse(next_action['res_id'])
        self.assertTrue(new_tray.exists())
        self.assertLess(len(new_tray.line_ids), 2)

    def test_row_action_without_host_keeps_the_old_backup(self):
        """Sin origen que repoblar, se conserva el aviso + recarga de hoy."""
        product, _quant, _picking_a, _picking_b = self._duo()
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        row = tray.line_ids[:1]

        action = tray.action_run(row.id, 'release_document')

        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(
            action['params']['next']['tag'], 'reload')

    # ==================================================================
    # T2 — Guardia del código (la vista lo esconde; el método no se fía)
    # ==================================================================
    def test_cleanup_all_guard_only_for_reservation_fault(self):
        """Otra falla comparte la pantalla ⇒ ``UserError``, no saneo mudo."""
        product = self._finished('GUARDIA SANEO MASIVO')
        tray = self.Tray.create({
            'code': 'lot_orphan_reservation',
            'product_id': product.id,
        })
        with self.assertRaises(UserError):
            tray.action_cleanup_all()
