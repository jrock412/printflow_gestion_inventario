# -*- coding: utf-8 -*-
"""Falla huérfana: reconciliar cuadra el reservado (PrintFlow · Fase 1).

Candado de la PRIMERA falla guiada (``printflow.flow.failure.lot.orphan``):
  * detecta el estado ``lot_orphan_reservation`` delegando en el motor;
  * describe UNA evidencia por quant afectado (con respaldo real y delta);
  * ``_pf_fault_execute('reconcile')`` llama la primitiva NATIVA de
    reconciliación del motor y deja el reservado igual al respaldo real,
    SIN tocar el FÍSICO.

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowFailureOrphanReconcile(TransactionCase):
    """La falla huérfana detecta, describe y reconcilia."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Registry = cls.env['printflow.flow.failure.registry']
        cls.Health = cls.env['printflow.stock.health']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _orphan_product(self, name, physical=10.0, reserved=4.0):
        """Producto por lote con reserva SIN movimiento que la respalde."""
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        lot = self.env['stock.lot'].create(
            {'name': '%s-LOTE' % name, 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, physical, lot_id=lot)
        self.env['stock.quant']._update_reserved_quantity(
            product, self.stock_location, reserved, lot_id=lot)
        return product, lot

    def _ctx(self, product):
        failure = self.Registry._pf_failure_for('lot_orphan_reservation')
        ctx = {'host': None, 'product': product,
               'code': 'lot_orphan_reservation'}
        ctx['observation'] = failure._pf_fault_detect(None, ctx)
        return failure, ctx

    # ==================================================================
    # 1) Detecta y describe UNA evidencia
    # ==================================================================
    def test_detect_and_evidence(self):
        product, lot = self._orphan_product('FALLA HUERFANA DETECTA')
        failure, ctx = self._ctx(product)

        self.assertTrue(ctx['observation'])
        self.assertEqual(ctx['observation']['lot_info']['state'],
                         'lot_orphan_reservation')
        rows = failure._pf_fault_evidences(ctx)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['lot_name'], lot.name)
        self.assertAlmostEqual(row['reserved_qty'], 4.0, places=6)
        self.assertAlmostEqual(row['physical_qty'], 10.0, places=6)
        self.assertAlmostEqual(row['support_qty'], 0.0, places=6)
        self.assertAlmostEqual(row['delta_qty'], -4.0, places=6)
        self.assertTrue(row['support_label'])

    # ==================================================================
    # 2) Reconciliar: reservado == respaldo, físico intacto
    # ==================================================================
    def test_reconcile_squares_reserved_keeps_physical(self):
        product, lot = self._orphan_product('FALLA HUERFANA RECONCILIA')
        failure, ctx = self._ctx(product)

        message = failure._pf_fault_execute('reconcile', ctx)
        self.assertTrue(message)

        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', lot.id)])
        self.assertEqual(len(quant), 1)
        self.assertAlmostEqual(quant.reserved_quantity, 0.0, places=6)
        self.assertAlmostEqual(quant.quantity, 10.0, places=6)
        self.assertEqual(self.Health._pf_lot_state(product)['state'], 'lot_ok')

    # ==================================================================
    # 3) Idempotencia: la segunda reconciliación no escribe
    # ==================================================================
    def test_reconcile_is_idempotent(self):
        product, lot = self._orphan_product('FALLA HUERFANA IDEMPOTENTE')
        failure, ctx = self._ctx(product)
        failure._pf_fault_execute('reconcile', ctx)

        second = self.Health._pf_reconcile_reserved_quant(product)
        self.assertEqual(second['reconciled'], 0)
