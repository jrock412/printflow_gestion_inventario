# -*- coding: utf-8 -*-
"""Bandeja GENÉRICA de fallas guiadas (PrintFlow · Fase 1).

Candado de la superficie ``printflow.flow.failure.tray``:
  * se puebla con UNA línea por evidencia que declara la falla;
  * cada línea trae sus ACCIONES guiadas (lista blanca de la falla);
  * ``action_run`` SOLO despacha claves de la lista blanca: una clave
    desconocida NO ejecuta nada (cierra);
  * ``navigate`` abre el registro/lista señalada; ``execute`` corre la falla;
  * el CABLEADO del diagrama abre la bandeja guiada para la falla huérfana
    cuando la fila trae el producto explícito, y CONSERVA la bandeja de lote
    clásica para el resto (y para las llamadas sin contexto).

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowFailureTrayGeneric(TransactionCase):
    """La bandeja genérica pinta la falla y despacha por lista blanca."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.failure.tray']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _orphan_product(self, name, physical=10.0, reserved=4.0):
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

    def _populate(self, product):
        return self.Tray._pf_populate(None, 'lot_orphan_reservation', product)

    # ==================================================================
    # 1) Poblado por evidencia + acciones por fila
    # ==================================================================
    def test_populate_from_evidence(self):
        product, lot = self._orphan_product('TRAP GENERICA')
        tray = self._populate(product)

        self.assertTrue(tray)
        self.assertEqual(tray.code, 'lot_orphan_reservation')
        self.assertEqual(tray.product_id, product)
        self.assertEqual(tray.severity, 'danger')
        self.assertTrue(tray.summary)
        self.assertTrue(tray.steps)
        self.assertEqual(len(tray.line_ids), 1)
        line = tray.line_ids[:1]
        self.assertEqual(line.lot_name, lot.name)
        self.assertEqual(line.res_model, 'stock.quant')
        keys = set(line.action_ids.mapped('key'))
        self.assertEqual(
            keys,
            {'reconcile', 'view_supporting_moves', 'view_quant', 'leave'})

    # ==================================================================
    # 2) action_run SOLO despacha la lista blanca
    # ==================================================================
    def test_action_run_whitelist(self):
        product, lot = self._orphan_product('TRAP LISTA BLANCA')
        tray = self._populate(product)
        line = tray.line_ids[:1]

        # Clave desconocida: NO despacha (cierra).
        action = tray.action_run(line.id, 'clave_desconocida')
        self.assertEqual(action['type'], 'ir.actions.act_window_close')

        # Navegar: abre el quant (solo lectura).
        action = tray.action_run(line.id, 'view_quant')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertEqual(action['res_id'], line.res_id)

        # La fila de acción delega en la bandeja (método público).
        action_row = line.action_ids.filtered(lambda a: a.key == 'view_quant')[:1]
        self.assertEqual(action_row.action_run()['res_model'], 'stock.quant')

    # ==================================================================
    # 3) execute corre la falla (reconciliar)
    # ==================================================================
    def test_action_run_execute_reconciles(self):
        product, lot = self._orphan_product('TRAP EJECUTA')
        tray = self._populate(product)
        line = tray.line_ids[:1]

        action = tray.action_run(line.id, 'reconcile')
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')

        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', lot.id)])
        self.assertAlmostEqual(quant.reserved_quantity, 0.0, places=6)

    # ==================================================================
    # 4) CABLEADO del diagrama: guiada con producto, clásica sin él
    # ==================================================================
    def test_wiring_prefers_guided_tray_with_product(self):
        product, lot = self._orphan_product('TRAP CABLEADO')
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])

        # Con el producto explícito (fila del panel): bandeja GENÉRICA.
        guided = wizard.action_run_pf_plan(
            'lot_orphan_reservation', 'solution', product.id)
        self.assertEqual(guided['res_model'], 'printflow.flow.failure.tray')

        # Sin contexto (llamada clásica): bandeja de LOTE (fallback intacto).
        legacy = wizard.action_run_pf_plan('lot_orphan_reservation', 'solution')
        self.assertEqual(legacy['res_model'], 'printflow.flow.lot.tray')
