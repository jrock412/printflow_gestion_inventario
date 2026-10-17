# -*- coding: utf-8 -*-
"""P4 — el saneo de la reserva colgada es ACOTADO (CA-4).

Custodia el criterio **CA-4** del plan de "Gestión del error de lote en el
diagrama de producto":

* **CA-4 (P4)** — "Liberar y re-reservar" del nodo Inventario (falla
  ``data_anomaly`` / reserva colgada) **NO** debe des-asignar una entrega
  **SANA** que comparte ubicación con el quant colgado.

El problema original (H-022): el saneo del MOTOR
(``x_product_dimensional_pricing::printflow.stock.remedy.
_pf_cleanup_product_reservations``) localiza la **ubicación** con reserva colgada
y suelta **TODAS** las ``stock.move.line`` que reservan allí; como el producto es
de entrega **exclusiva por lote**, una entrega SANA de esa misma ubicación
termina re-asignada contra su lote exclusivo (vacío) ⇒ pierde su excepción.

La solución (D4, 100 % PrintFlow): el método **ACOTADO**
``printflow.stock.remedy._pf_release_hanging_lot_reservation`` suelta SOLO las
líneas que apuntan al quant colgado (misma ubicación **y** mismo lote) y aplica
una guardia **anti-entrega-sana**: una línea respaldada por un lote con
existencia **NUNCA** se suelta. Luego re-reserva con ``picking.action_assign()``
(reglas NATIVAS de Odoo).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios productos/albaranes/quants
y ``TransactionCase`` hace rollback al terminar. NO escribe/crea/borra quants ni
movimientos en código de producción.
"""

import io
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowOverReservationScoped(TransactionCase):
    """CA-4: el saneo acotado preserva la entrega sana de la misma ubicación."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Saneo Acotado'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Engine = cls.env['printflow.order.health.engine']
        cls.Tray = cls.env['printflow.flow.failure.tray']

    # ------------------------------------------------------------------
    # Utilidades (patrón de test_product_flow_lot_tray_orders.py)
    # ------------------------------------------------------------------
    def _product(self):
        product = self.env['product.product'].create({
            'name': 'CA4 SANEO ACOTADO',
            'type': 'product',
            'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _outgoing(self, product, qty, lot=None):
        """Albarán de salida confirmado con su move line (lote opcional).

        La confirmación ocurre ANTES de que exista existencia, así Odoo no
        reserva por su cuenta y el escenario queda controlado (mismo cuidado que
        ``test_product_flow_lot_tray_orders`` / ``..._coupled_chain``).
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
        """Quant de un LOTE con existencia física que RESPALDA su reserva.

        ``quantity == reserved_quantity`` (libre 0) ⇒ reserva LEGÍTIMA, no
        colgada. Es el patrón del setup de ``test_product_flow_failure_over_
        reservation`` (fabricación de quants SOLO en test; rollback al terminar).
        """
        Quant = self.env['stock.quant'].sudo()
        Quant._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)
        quant = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.stock_location.id),
            ('lot_id', '=', lot.id)], limit=1)
        quant.write({'quantity': qty, 'reserved_quantity': qty})
        return quant

    def _hanging_quant(self, product, reserved):
        """Quant SIN lote con reserva colgada (``reserved > quantity``)."""
        Quant = self.env['stock.quant'].sudo()
        Quant._update_available_quantity(product, self.stock_location, reserved)
        quant = Quant.search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.stock_location.id),
            ('lot_id', '=', False)], limit=1)
        quant.write({'quantity': 0.0, 'reserved_quantity': reserved})
        return quant

    def _scenario(self, lot_name='CA4-LOTE-SANO'):
        """(producto, lote real, entrega SANA + move, entrega COLGADA) con reservas.

        La misma ubicación (``WH/Stock``) hospeda las DOS entregas: el quant sin
        lote colgado y el quant del lote real respaldado. Es el caso de H-022.
        """
        product = self._product()
        real_lot = self._lot(product, lot_name)
        picking_ok, move_ok = self._outgoing(product, 2.0, lot=real_lot)
        picking_bad, move_bad = self._outgoing(product, 3.0)
        quant_ok = self._backed_quant(product, real_lot, 2.0)
        self._hanging_quant(product, 3.0)
        return (product, real_lot, picking_ok, move_ok,
                picking_bad, move_bad, quant_ok)

    # ------------------------------------------------------------------
    # CA-4 — el saneo acotado NO toca la entrega sana
    # ------------------------------------------------------------------
    def test_ca4_scoped_saneo_preserves_healthy_delivery(self):
        """El contrato de saneo incluye SOLO la colgada; la SANA queda intacta."""
        (product, real_lot, picking_ok, move_ok,
         picking_bad, _move_bad, quant_ok) = self._scenario()
        # Precondición real: la reserva colgada SÍ existe.
        self.assertTrue(
            self.Remedy._pf_product_reservation_state(
                product)['has_negative_quant'])

        result = self.Remedy._pf_release_hanging_lot_reservation(product)

        # Solo se sanea la COLGADA; la SANA NO entra en la bitácora de saneo.
        self.assertIn(picking_bad.id, result['cleaned_pickings'])
        self.assertNotIn(picking_ok.id, result['cleaned_pickings'])
        self.assertIsInstance(result['still_negative'], bool)

        # Y la entrega SANA conserva su LOTE y su reserva (CA-4).
        move_ok.invalidate_recordset()
        self.assertEqual(move_ok.move_line_ids.lot_id, real_lot)
        quant_ok.invalidate_recordset()
        self.assertAlmostEqual(quant_ok.reserved_quantity, 2.0)

    def test_ca4_scoped_saneo_through_tray_action(self):
        """Ejecutar la acción de la bandeja no des-asigna la entrega SANA."""
        (product, _real_lot, _picking_ok, move_ok,
         _picking_bad, _move_bad, _quant_ok) = self._scenario('CA4-LOTE-TRAY')

        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        self.assertTrue(tray.line_ids)
        line = tray.line_ids[:1]
        action = tray.action_run(line.id, 'release_reservation')
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')

        move_ok.invalidate_recordset()
        self.assertEqual(move_ok.move_line_ids.lot_id.name, 'CA4-LOTE-TRAY')

    def test_ca4_scoped_method_returns_engine_contract(self):
        """Sin reserva colgada: contrato vacío y sin excepción (mismo contrato)."""
        product = self._product()
        result = self.Remedy._pf_release_hanging_lot_reservation(product)
        self.assertEqual(
            result, {'cleaned_pickings': [], 'still_negative': False})

    # ------------------------------------------------------------------
    # Candados (motor intacto / sin SQL crudo)
    # ------------------------------------------------------------------
    def test_ca4_engine_method_still_exists_and_intact(self):
        """El motor NO se reemplazó: solo se heredó un método nuevo."""
        Remedy = self.env['printflow.stock.remedy']
        self.assertTrue(hasattr(Remedy, '_pf_cleanup_product_reservations'))
        self.assertTrue(hasattr(Remedy, '_pf_release_hanging_lot_reservation'))
        engine_module = (
            Remedy._pf_cleanup_product_reservations.__func__.__module__)
        self.assertIn('x_product_dimensional_pricing', engine_module)
        scoped_module = (
            Remedy._pf_release_hanging_lot_reservation.__func__.__module__)
        self.assertIn('printflow_gestion_inventario', scoped_module)

    def test_ca4_scoped_source_has_no_raw_sql(self):
        """El archivo nuevo NO usa SQL crudo ni valida albaranes por detrás."""
        path = os.path.join(
            get_module_path('printflow_gestion_inventario'),
            'models', 'printflow_stock_remedy.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('cr.execute(', source)
        self.assertNotIn('cr.commit(', source)
        self.assertNotIn('button_validate', source)
