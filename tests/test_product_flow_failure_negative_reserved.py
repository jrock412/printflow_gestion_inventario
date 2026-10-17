# -*- coding: utf-8 -*-
"""Falla huérfana: reserva NEGATIVA sube al respaldo (PrintFlow · Fase 1).

Un quant con ``reserved_quantity`` negativa es inventario fantasma. El motor ya
lo PLIEGA en ``lot_orphan_reservation`` y expone ``negative_reserved_quant_ids``
(sin crear estados nuevos). Este candado verifica que la falla guiada:
  * lo DETECTA (estado huérfano) y lo describe con su respaldo real;
  * ``_pf_fault_execute('reconcile')`` SUBE el reservado hasta el respaldo real
    (la primitiva NATIVA ``_update_reserved_quantity``), SIN borrar el quant ni
    tocar el FÍSICO y sin crear movimientos de ajuste.

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowFailureNegativeReserved(TransactionCase):
    """La reserva negativa se detecta y se sube al respaldo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Falla Negativa'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Registry = cls.env['printflow.flow.failure.registry']
        cls.Health = cls.env['printflow.stock.health']

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

    def _backing_move_line(self, product, lot, qty=2.0):
        """Línea de un movimiento de salida ACTIVO que RESPALDA reservado."""
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
            'lot_id': lot.id,
        })
        return picking, move

    def _ctx(self, product):
        failure = self.Registry._pf_failure_for('lot_orphan_reservation')
        ctx = {'host': None, 'product': product,
               'code': 'lot_orphan_reservation'}
        ctx['observation'] = failure._pf_fault_detect(None, ctx)
        return failure, ctx

    # ==================================================================
    # La reserva negativa sube al respaldo; físico y quant intactos
    # ==================================================================
    def test_negative_reserved_rises_to_support(self):
        product = self._product('FALLA NEGATIVA')
        lot = self.env['stock.lot'].create(
            {'name': 'FALLA-NEGATIVA-LOTE', 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, 10.0, lot_id=lot)
        # Movimiento activo que RESPALDA 2 unidades del lote.
        self._backing_move_line(product, lot, 2.0)
        # Reserva NEGATIVA (fantasma): queda en -3 aunque el respaldo sea 2.
        self.env['stock.quant']._update_reserved_quantity(
            product, self.stock_location, -3.0, lot_id=lot)

        failure, ctx = self._ctx(product)
        self.assertTrue(ctx['observation'])
        self.assertTrue(
            ctx['observation']['lot_info']['negative_reserved_quant_ids'])
        rows = failure._pf_fault_evidences(ctx)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]['reserved_qty'], -3.0, places=6)
        self.assertAlmostEqual(rows[0]['support_qty'], 2.0, places=6)
        self.assertAlmostEqual(rows[0]['delta_qty'], 5.0, places=6)

        failure._pf_fault_execute('reconcile', ctx)

        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', lot.id)])
        self.assertEqual(len(quant), 1, 'El quant NO se borra.')
        self.assertAlmostEqual(quant.reserved_quantity, 2.0, places=6)
        self.assertAlmostEqual(quant.quantity, 10.0, places=6)
