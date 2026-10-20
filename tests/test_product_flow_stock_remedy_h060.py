# -*- coding: utf-8 -*-
"""Cura H-060 en el saneo ACOTADO de la reserva colgada (§3.S · Lote 1 · T1).

La ventana "Solucionar" de la reserva colgada sana también por OF (movimientos
``raw_material_production_id`` sin albarán). Hoy ``_pf_release_hanging_lot_
reservation`` llama ``pickings.action_assign()`` a secas ⇒ el core lanza
``UserError`` *"Nothing to check the availability for."*
(``stock_picking.py`` L942-943) y el botón re-vienta (H-060). Además una línea
colgada marcada ``picked`` NUNCA se libera (el ``_pf_unreserve_reservation`` del
motor se la salta: core ``stock_move.py`` L804/L816 · ``stock_move_line.py``
L109-113 ⇒ CT-02 escudo): hay que destildar la LÍNEA concreta antes (CT-01).

El lote candaea:

* (a) guardia ``if pickings:`` + **fallback OF**: los moves sin albarán se
  re-reservan con ``stock.move._action_assign()`` (primitiva NATIVA);
* (b) liberación válida de la línea ``picked`` (escritura EXPLÍCITA a nivel de
  LÍNEA, aviso + bitácora en el documento y en el producto);
* (c) parámetro nuevo ``lines``: acota el saneo al DOCUMENTO de la fila (nunca
  suelta más); con ``None`` se comporta byte-a-byte como antes;
* (d) MISMO contrato de retorno ``{'cleaned_pickings', 'still_negative'}``.

Escenario OF ( Herramientas del plan §3.S.8: "move de insumo con
``raw_material_production_id``, ``picking_id=False``, quant colgado con línea
``picked=True``"). Transaccional: ``TransactionCase`` hace rollback; NUNCA toca
datos reales (código sí, datos no).

Reutiliza los helpers de escenario del candado CA-4v (``test_product_flow_
over_reservation_scoped``) copiando las piezas mínimas: la clase ajena no se
subclasea para no re-correr sus tests.
"""
import io
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

_EPS = 1e-6


@tagged('post_install', '-at_install')
class TestProductFlowStockRemedyH060(TransactionCase):
    """H-060: el saneo acotado sana OF sin albarán + línea tachada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente H060'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Remedy = cls.env['printflow.stock.remedy']

    # ------------------------------------------------------------------
    # Utilidades (patrón del candado CA-4v · test_product_flow_over_
    # reservation_scoped.py)
    # ------------------------------------------------------------------
    def _product(self):
        product = self.env['product.product'].create({
            'name': 'H060 COLGADA',
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _outgoing(self, product, qty):
        """Albarán de salida confirmado, SIN lote y SIN existencia disponible."""
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

    def _of_setup(self, picked=False, qty=1.0, line_qty=None):
        """(mo, move, línea, quant colgado) de INSUMO sin albarán.

        El move es materia prima de la OF (``raw_material_production_id``),
        ``picking_id=False`` y su línea (opcionalmente ``picked``) es la que
        SOSTIENE la reserva colgada del quant sin lote.
        """
        product = self._product()
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
            'product_uom_qty': qty,
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
            'quantity': line_qty if line_qty is not None else qty,
            'picked': picked,
        })
        quant = self._hanging_quant(product, line.quantity_product_uom)
        return mo, move, line, quant

    # ------------------------------------------------------------------
    # (a) Guardia del recordset vacío + fallback OF: sin UserError
    # ------------------------------------------------------------------
    def test_h060_of_without_picking_no_usererror(self):
        """Una reserva colgada de INSUMO (sin albarán) se sana sin impeachment."""
        _mo, _move, _line, quant = self._of_setup()

        # El saneo corre completo sin UserError ante la OF sin albarán.
        result = self.Remedy._pf_release_hanging_lot_reservation(
            _move.product_id)

        self.assertEqual(result['cleaned_pickings'], [])
        self.assertIsInstance(result['still_negative'], bool)
        quant.invalidate_recordset()
        # El colgado queda saneado: nada reservado sobre nada físico (delta 0).
        self.assertLessEqual(
            quant.reserved_quantity, quant.quantity + _EPS)

    def test_h060_empty_picking_guard_contract(self):
        """Sin colgado (ni con ``lines`` vacío): contrato EXACTO y sin excepción."""
        product = self._product()
        empty_lines = self.env['stock.move.line']
        self.assertEqual(
            self.Remedy._pf_release_hanging_lot_reservation(
                product, lines=empty_lines),
            {'cleaned_pickings': [], 'still_negative': False})
        self.assertEqual(
            self.Remedy._pf_release_hanging_lot_reservation(product),
            {'cleaned_pickings': [], 'still_negative': False})

    # ------------------------------------------------------------------
    # (b) Liberación válida de la línea colgada marcada ``picked``
    # ------------------------------------------------------------------
    def test_h060_picked_hanging_line_is_released(self):
        """El tachón de la LÍNEA baja (CT-01) y la colgada se soltó (H-060)."""
        mo, _move, line, quant = self._of_setup(picked=True)
        move = line.move_id
        product = line.product_id
        self.assertTrue(line.picked)
        self.assertTrue(move.picked)

        result = self.Remedy._pf_release_hanging_lot_reservation(
            line.product_id)

        self.assertEqual(result['cleaned_pickings'], [])
        quant.invalidate_recordset()
        # CT-03/native: ``_do_unreserve`` DES-ENLAZA las líneas no tachadas
        # ⇒ la línea colgada tildada quedó ELIMINADA (nunca se debe leer).
        self.assertFalse(line.exists())
        # El escudo del motor syncroniza el move (escritura EXPLÍCITA).
        move.invalidate_recordset(['picked'])
        self.assertFalse(move.picked)
        # El colgado quedo sano (nada reservado sobre nada físico).
        self.assertLessEqual(
            quant.reserved_quantity, quant.quantity + _EPS)
        # Aviso + bitácora: la OF y el producto MENCIONAN el tachón soltado.
        production_bodies = '\n'.join(
            msg.body or '' for msg in mo.message_ids)
        product_bodies = '\n'.join(
            msg.body or '' for msg in product.message_ids)
        self.assertIn('en marcha', production_bodies)
        self.assertIn('en marcha', product_bodies)

    # ------------------------------------------------------------------
    # (c) Acotado POR DOCUMENTO: ``lines`` NO suelta más
    # ------------------------------------------------------------------
    def test_h060_scope_lines_touches_only_that_document(self):
        """Con ``lines=<línea A>``, la reserva del documento B queda intacta."""
        product = self._product()
        picking_a, move_a = self._outgoing(product, 1.0)
        picking_b, _move_b = self._outgoing(product, 1.0)
        # Ambas líneas SOSTIENEN el mismo quant colgado: fecha 0 / reserva 2.
        quant = self._hanging_quant(product, 2.0)
        line_a = move_a.move_line_ids
        line_b = picking_b.move_ids.move_line_ids
        self.assertEqual(len(line_a), 1)
        self.assertEqual(len(line_b), 1)

        result = self.Remedy._pf_release_hanging_lot_reservation(
            product, lines=line_a)

        # Solo se saneó el documento A (su albarán entra en el contrato).
        self.assertEqual(result['cleaned_pickings'], [picking_a.id])
        line_a.invalidate_recordset()
        line_b.invalidate_recordset()
        quant.invalidate_recordset()
        # CT-03/native: la línea A quedó ELIMINADA por ``_do_unreserve`` al
        # soltar SU reserva; la B sigue viva y conserva SU reserva intacta.
        self.assertFalse(line_a.exists())
        self.assertAlmostEqual(line_b.quantity_product_uom, 1.0)
        self.assertAlmostEqual(quant.reserved_quantity, 1.0)

    # ------------------------------------------------------------------
    # (d) Candado: NO SQL crudo ni validación por detrás
    # ------------------------------------------------------------------
    def test_h060_remedy_source_has_no_raw_sql(self):
        """El saneo NO usa SQL crudo ni ``cr.commit`` (código sí, datos no)."""
        path = os.path.join(
            get_module_path('printflow_gestion_inventario'),
            'models', 'printflow_stock_remedy.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('cr.execute(', source)
        self.assertNotIn('cr.commit(', source)
        self.assertNotIn('button_validate', source)
