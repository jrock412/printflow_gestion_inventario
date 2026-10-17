# -*- coding: utf-8 -*-
"""Bloque V — Manejo de lotes / trazabilidad (V1–V8 + decisiones 1–8).

Escenarios GENÉRICOS (productos y lotes propios del test), sin tocar datos
reales. Cubre:
  * V1 detección de estados de lote.
  * V2 reconciliación de reserva huérfana sin tocar reservas reales.
  * V3 reasignación por lote con existencia (nunca un lote vacío).
  * V4 lote exclusivo por pedido.
  * V5 movimiento sin lote: bloquear o auto-asignar según configuración.
  * V6 nunca mezclar lotes entre clientes.
  * V7 reparación de MO terminada sin lote.
  * V8 no trasvase: nunca se asigna a un pedido el lote de otro.
  * Decisiones §54.1–§54.8 por defecto.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

# Claves de configuración (ir.config_parameter).
PARAM_LOT_CRITERION = 'x_product_dimensional_pricing.pf_lot_exclusive_criterion'
PARAM_LOT_MISSING_ACTION = 'x_product_dimensional_pricing.pf_lot_missing_action'
PARAM_LOT_ORPHAN_AUTO = 'x_product_dimensional_pricing.pf_lot_orphan_auto_reconcile'
PARAM_LOT_ALLOW_GENERIC = (
    'x_product_dimensional_pricing.pf_lot_allow_generic_nonpersonalized')
PARAM_LOT_GENERIC_PREFIX = 'x_product_dimensional_pricing.pf_lot_generic_prefix'


@tagged('post_install', '-at_install')
class TestLotManagement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente Lote A'})
        cls.other_customer = cls.env['res.partner'].create(
            {'name': 'Cliente Lote B'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Health = cls.env['printflow.stock.health']
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Surface = cls.env['printflow.inventory.health']
        cls.Production = cls.env['mrp.production']

    # ------------------------------------------------------------------
    # Utilidades (genéricas, sin productos concretos)
    # ------------------------------------------------------------------
    def _set_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(key, value)

    def _prod(self, name, managed=True, tracking='lot'):
        return self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': tracking,
            'x_is_printflow_managed': managed,
        })

    def _lot(self, product, name, parent=None):
        vals = {'name': name, 'product_id': product.id}
        if parent:
            vals['parent_lot_id'] = parent.id
        return self.env['stock.lot'].create(vals)

    def _stock(self, product, qty, lot=None, reserved=0.0, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty, lot_id=lot,
            reserved_quantity=reserved)

    def _outgoing(self, product, qty, lot=None, sale_line=None, with_line=True):
        """Albarán de salida con un movimiento y (opcional) su move_line."""
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
            'sale_line_id': sale_line.id if sale_line else False,
        })
        move._action_confirm()
        if with_line:
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

    def _confirm_order(self, partner, product, qty=1.0):
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _exclusive_lot(self, sale_order, product, qty=5.0):
        """Crea el lote exclusivo del pedido con existencia y lo devuelve."""
        line = sale_order.order_line.filtered(lambda l: l.product_id == product)[:1]
        lot = self._lot(product, line._get_exclusive_lot_name())
        self._stock(product, qty, lot=lot)
        return lot

    # ==================================================================
    # V1 — Detección de estados de lote
    # ==================================================================
    def test_v1_lot_missing(self):
        product = self._prod('PF LOTE SIN LOTE')
        self._outgoing(product, 2.0, lot=None)
        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_missing')
        self.assertEqual(state['remedy_key'], 'assign_lot')

    def test_v1_lot_orphan_reservation(self):
        product = self._prod('PF LOTE HUERFANA')
        # Quant sin lote con reservado y SIN move_line que lo respalde.
        self._stock(product, 0.0, lot=None, reserved=5.0)
        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_orphan_reservation')
        self.assertEqual(state['remedy_key'], 'reconcile_lot_reservation')

    def test_v1_lot_no_stock(self):
        product = self._prod('PF LOTE SIN STOCK')
        ghost = self._lot(product, 'PF-LOTE-FANTASMA-1')
        self._outgoing(product, 2.0, lot=ghost)
        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_no_stock')

    def test_v1_lot_generic(self):
        product = self._prod('PF LOTE GENERICO')
        generic = self._lot(product, 'LOTE-GENERICO-PF-TEST')
        self._stock(product, 10.0, lot=generic)
        self._outgoing(product, 2.0, lot=generic)
        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_generic')
        self.assertEqual(state['remedy_key'], 'replace_generic_lot')

    def test_v1_lot_ok(self):
        product = self._prod('PF LOTE OK')
        lot = self._lot(product, 'PF-LOTE-OK-1')
        self._stock(product, 10.0, lot=lot)
        self._outgoing(product, 2.0, lot=lot)
        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_ok')

    # ==================================================================
    # V2 — Reconciliar reserva huérfana sin tocar reservas reales
    # ==================================================================
    def test_v2_reconcile_orphan_keeps_real(self):
        product = self._prod('PF LOTE RECONCILE')
        real_lot = self._lot(product, 'PF-LOTE-REAL-1')
        self._stock(product, 10.0, lot=real_lot)
        # Reserva REAL: la crea y respalda Odoo al asignar el movimiento.
        picking, _move = self._outgoing(product, 2.0, with_line=False)
        picking.action_assign()
        self.assertTrue(picking.move_line_ids, 'Debe haber reserva real.')
        backed_real = sum(picking.move_line_ids.mapped('quantity'))
        self.assertGreater(backed_real, 0.0)

        # Reserva HUÉRFANA: quant sin lote reservado sin movimiento.
        self._stock(product, 0.0, lot=None, reserved=5.0)
        state = self.Health._pf_lot_state(product)
        self.assertEqual(state['state'], 'lot_orphan_reservation')

        result = self.Health._pf_reconcile_lot_reservation(product)
        self.assertGreaterEqual(result['reconciled'], 1)

        orphan = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', False)])
        orphan_reserved = sum(orphan.mapped('reserved_quantity'))
        self.assertAlmostEqual(orphan_reserved, 0.0, places=6)
        # La reserva REAL se conserva (lo respaldado por el movimiento).
        real = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', real_lot.id)])
        self.assertAlmostEqual(
            sum(real.mapped('reserved_quantity')), backed_real, places=6)

    # ==================================================================
    # V3 — Reasignar por lote con existencia (nunca un lote vacío)
    # ==================================================================
    def test_v3_reassign_by_stock(self):
        product = self._prod('PF LOTE REASIGNA', managed=False)
        with_stock = self._lot(product, 'PF-LOTE-CON-STOCK')
        self._stock(product, 10.0, lot=with_stock)
        ghost = self._lot(product, 'PF-LOTE-VACIO')
        picking, move = self._outgoing(product, 3.0, lot=ghost)

        self.Health._pf_reassign_by_lot(product)

        lots = picking.move_line_ids.mapped('lot_id')
        self.assertIn(with_stock, lots)
        self.assertNotIn(ghost, lots)

    # ==================================================================
    # V4 — Lote exclusivo por pedido
    # ==================================================================
    def test_v4_exclusive_per_order(self):
        product = self._prod('PF LOTE EXCLUSIVO')
        so1 = self._confirm_order(self.customer, product, 1.0)
        so2 = self._confirm_order(self.other_customer, product, 1.0)
        lot1 = self._exclusive_lot(so1, product)
        lot2 = self._exclusive_lot(so2, product)

        (so1.picking_ids | so2.picking_ids).action_assign()

        self.assertEqual(so1.picking_ids.move_line_ids.mapped('lot_id'), lot1)
        self.assertEqual(so2.picking_ids.move_line_ids.mapped('lot_id'), lot2)
        self.assertNotEqual(lot1, lot2)

    # ==================================================================
    # V5 — Movimiento sin lote: bloquear o auto-asignar (configurable)
    # ==================================================================
    def test_v5_missing_blocks(self):
        self._set_param(PARAM_LOT_MISSING_ACTION, 'block')
        product = self._prod('PF LOTE BLOQUEA')
        picking, _move = self._outgoing(product, 2.0, lot=None)
        with self.assertRaises(UserError):
            picking.button_validate()

    def test_v5_missing_assigns_exclusive(self):
        self._set_param(PARAM_LOT_MISSING_ACTION, 'assign')
        product = self._prod('PF LOTE AUTOASIGNA')
        so = self._confirm_order(self.customer, product, 1.0)
        lot = self._exclusive_lot(so, product)
        picking = so.picking_ids

        picking._pf_prepare_lots_for_validation()

        self.assertEqual(picking.move_line_ids.mapped('lot_id'), lot)

    def test_v5_missing_warn_default_does_not_assign(self):
        product = self._prod('PF LOTE AVISA')
        so = self._confirm_order(self.customer, product, 1.0)
        picking = so.picking_ids
        # Nivel por defecto = warn: no asigna ni bloquea.
        picking._pf_prepare_lots_for_validation()
        self.assertFalse(picking.move_line_ids.mapped('lot_id'))

    # ==================================================================
    # V6 — Nunca mezclar lotes entre clientes
    # ==================================================================
    def test_v6_no_mix_clients(self):
        product = self._prod('PF LOTE SIN MEZCLA')
        so1 = self._confirm_order(self.customer, product, 1.0)
        so2 = self._confirm_order(self.other_customer, product, 1.0)
        lot1 = self._exclusive_lot(so1, product)
        lot2 = self._exclusive_lot(so2, product)
        (so1.picking_ids | so2.picking_ids).action_assign()

        # Saneamiento/reasignación: cada pedido conserva SU lote.
        self.Health._pf_reassign_by_lot(product)

        self.assertEqual(so1.picking_ids.move_line_ids.mapped('lot_id'), lot1)
        self.assertEqual(so2.picking_ids.move_line_ids.mapped('lot_id'), lot2)

    # ==================================================================
    # V7 — Reparar MO terminada sin lote
    # ==================================================================
    def test_v7_finished_repair(self):
        product = self._prod('PF LOTE TERMINADO')
        # Pedido SIN confirmar (solo aporta la línea para el lote exclusivo).
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        manu_type = self.warehouse.manu_type_id
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'origin': so.name,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
        })
        mo.write({'state': 'done'})
        self.assertFalse(mo.lot_producing_id)

        repaired = self.Health._pf_repair_finished_lot(product)

        self.assertGreaterEqual(repaired, 1)
        self.assertTrue(mo.lot_producing_id)

    # ==================================================================
    # V8 — No trasvase: nunca se asigna a un pedido el lote de otro
    # ==================================================================
    def test_v8_no_cross_order_steal(self):
        product = self._prod('PF LOTE NO TRASVASE')
        so1 = self._confirm_order(self.customer, product, 1.0)
        so2 = self._confirm_order(self.other_customer, product, 1.0)
        lot1 = self._exclusive_lot(so1, product)
        lot2 = self._exclusive_lot(so2, product)
        (so1.picking_ids | so2.picking_ids).action_assign()

        self.Health._pf_reassign_by_lot(product)
        self.Health._pf_reconcile_lot_reservation(product)

        self.assertNotEqual(lot1, lot2)
        self.assertNotIn(
            lot2.id, so1.picking_ids.move_line_ids.mapped('lot_id').ids)
        self.assertNotIn(
            lot1.id, so2.picking_ids.move_line_ids.mapped('lot_id').ids)

    # ==================================================================
    # Decisiones §54 (valores por defecto configurables)
    # ==================================================================
    def test_d1_dimension_lives_in_generic_service(self):
        self.assertTrue(hasattr(self.Health, '_pf_lot_state'))
        self.assertTrue(hasattr(self.Remedy, '_pf_lot_remedy_key'))
        self.assertEqual(
            self.Remedy._pf_lot_remedy_key('lot_missing'), 'assign_lot')

    def test_d2_exclusive_criterion_managed_by_default(self):
        managed = self._prod('PF CRITERIO GESTIONADO', managed=True)
        plain = self._prod('PF CRITERIO NORMAL', managed=False)
        self.assertTrue(self.Health._pf_lot_exclusive_required(managed))
        self.assertFalse(self.Health._pf_lot_exclusive_required(plain))
        self._set_param(PARAM_LOT_CRITERION, 'all_lot')
        self.assertTrue(self.Health._pf_lot_exclusive_required(plain))

    def test_d3_missing_action_default_warn(self):
        self.assertEqual(self.Health._pf_lot_missing_action(), 'warn')
        self._set_param(PARAM_LOT_MISSING_ACTION, 'block')
        self.assertEqual(self.Health._pf_lot_missing_action(), 'block')

    def test_d4_orphan_auto_default_false(self):
        self.assertFalse(self.Health._pf_lot_orphan_auto())
        self._set_param(PARAM_LOT_ORPHAN_AUTO, 'True')
        self.assertTrue(self.Health._pf_lot_orphan_auto())

    def test_d5_generic_allowed_nonpersonalized(self):
        plain = self._prod('PF GENERICO NO GESTIONADO', managed=False)
        generic = self._lot(plain, 'LOTE-GENERICO-PF-TEST')
        self._stock(plain, 10.0, lot=generic)
        self._outgoing(plain, 1.0, lot=generic)
        # En un producto NO gestionado el lote genérico no se marca.
        self.assertEqual(self.Health._pf_lot_state(plain)['state'], 'lot_ok')

    def test_d6_exclusive_granularity_per_line(self):
        product = self._prod('PF GRANULARIDAD')
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        line = so.order_line
        self.assertEqual(
            line._get_exclusive_lot_name(), '%s-L%s' % (so.name, line.id))

    def test_d7_parent_shared_child_exclusive(self):
        product = self._prod('PF PADRE HIJO')
        parent = self._lot(product, 'PF-ROLLO-COMPRA')
        child = self.Production._get_or_create_lot(
            product, 'PF-HIJO-EXCLUSIVO', parent_lot=parent)
        self.assertEqual(child.parent_lot_id, parent)

    def test_d8_prevention_at_validation_not_on_write(self):
        # Escribir un move_line sin lote NO dispara auto-asignación (no hay hook
        # en `stock.move.line.write`).
        product = self._prod('PF PREVENCION')
        _picking, move = self._outgoing(product, 2.0, lot=None)
        self.assertFalse(move._pf_has_lot_assigned())
        # El punto de enganche es la validación (método presente en picking).
        self.assertTrue(hasattr(
            self.env['stock.picking'], '_pf_prepare_lots_for_validation'))
