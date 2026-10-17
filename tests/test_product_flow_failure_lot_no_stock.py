# -*- coding: utf-8 -*-
"""Falla guiada de LOTE SIN EXISTENCIA (``lot_no_stock``) + bandeja (PrintFlow).

Candado de CA-1..CA-4 de la tarea "la bandeja guiada de fallas no cubre
``lot_no_stock``": el "Solucionar" del estado de lote ``lot_no_stock`` (entrega
que retiene un lote sin existencia) deja de caer a la bandeja CLÁSICA y abre la
bandeja GENÉRICA de fallas, con UNA fila por lote y el saneo EXISTENTE; los dos
casos previos (``lot_orphan_reservation`` y ``data_anomaly``) y el fallback
clásico quedan INTACTOS.

  * CA-1: con el PRODUCTO explícito (la fila del panel, 3er argumento ADITIVO)
    ``action_run_pf_plan('lot_no_stock', 'solution', <product>)`` ABRE la bandeja
    ``printflow.flow.failure.tray``; la MISMA llamada SIN contexto (2 argumentos)
    conserva la bandeja CLÁSICA de lote (fallback intacto).
  * CA-2: ``printflow.flow.failure.tray._pf_populate(None, 'lot_no_stock', p)``
    trae UNA fila por lote sin existencia con ``res_model='stock.lot'`` y las
    acciones ``reassign`` (execute, principal), ``view_supporting_moves``
    (navigate) y ``leave`` (close); ``reassign`` ejecuta el saneo EXISTENTE
    (notificación) y una clave desconocida cierra.
  * CA-3: los dos casos previos siguen INTACTOS (``lot_orphan_reservation`` ->
    ``...lot.orphan``, ``data_anomaly`` -> ``...over.reservation``);
    ``_pf_supported()`` contiene los TRES códigos y la guiada de la huérfana
    sigue abriendo con el producto explícito.
  * CA-4: solo LECTURA sobre datos ajenos; el archivo nuevo no tiene
    ``cr.execute(``/``cr.commit(``; el motor externo queda intacto (la falla solo
    REUTILIZA ``printflow.stock.health._pf_reassign_by_lot`` y el guardia
    ``printflow.stock.remedy._pf_assert_can_clean``).

Transaccional: ``TransactionCase`` hace rollback al terminar. El escenario del
lote sin existencia sigue el patrón de ``test_product_flow_lot_actions.py``: un
lote REAL con stock (evita el déficit) + un albarán de salida que retiene un lote
FANTASMA sin existencia.
"""
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowFailureLotNoStock(TransactionCase):
    """La falla guiada de lote sin existencia se registra y se resuelve."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Lote Sin Existencia'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.failure.tray']
        cls.Registry = cls.env['printflow.flow.failure.registry']

    # ------------------------------------------------------------------
    # Utilidades (patrón de ``test_product_flow_lot_actions.py``)
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

    def _real_stock(self, product, qty=10.0):
        """Stock REAL en un lote propio: evita el déficit (así el lote sin
        existencia es la ÚNICA falla)."""
        lot = self._lot(product, '%s-REAL' % product.name)
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)
        return lot

    def _outgoing_no_stock_lot(self, product, lot, qty=2.0):
        """Albarán de salida que reserva un lote SIN existencia (``lot_no_stock``)."""
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

    def _no_stock_product(self, name):
        """Producto con un lote REAL con stock + un lote FANTASMA retenido."""
        product = self._product(name)
        self._real_stock(product, 10.0)
        ghost = self._lot(product, '%s-FANTASMA' % name)
        self._outgoing_no_stock_lot(product, ghost, 2.0)
        return product

    def _orphan_product(self, name, physical=10.0, reserved=4.0):
        """Producto con una reserva HUÉRFANA (reservado > respaldo)."""
        product = self._product(name)
        lot = self._lot(product, '%s-HUERFANO' % name)
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, physical, lot_id=lot)
        self.env['stock.quant']._update_reserved_quantity(
            product, self.stock_location, reserved, lot_id=lot)
        return product

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    # ==================================================================
    # CA-1: el "Solucionar" abre la guiada con producto; clásica sin él
    # ==================================================================
    def test_ca1_solution_with_product_opens_guided_tray(self):
        product = self._no_stock_product('FALLA NOSTOCK GUIADA')
        wizard = self._wizard(product)

        guided = wizard.action_run_pf_plan(
            'lot_no_stock', 'solution', product.id)
        self.assertEqual(guided['type'], 'ir.actions.act_window')
        self.assertEqual(guided['res_model'], 'printflow.flow.failure.tray')
        self.assertEqual(guided['target'], 'current')

    def test_ca1_solution_without_product_keeps_classic_tray(self):
        """La MISMA llamada sin contexto (2 argumentos) NO cambia: clásica."""
        product = self._no_stock_product('FALLA NOSTOCK CLASICA')
        wizard = self._wizard(product)

        legacy = wizard.action_run_pf_plan('lot_no_stock', 'solution')
        self.assertEqual(legacy['type'], 'ir.actions.act_window')
        self.assertEqual(legacy['res_model'], 'printflow.flow.lot.tray')

    # ==================================================================
    # CA-2: evidencias por lote + acciones guiadas de la falla
    # ==================================================================
    def test_ca2_guided_tray_has_lot_rows_and_actions(self):
        product = self._no_stock_product('FALLA NOSTOCK TRAY')
        tray = self.Tray._pf_populate(None, 'lot_no_stock', product)

        self.assertTrue(tray)
        self.assertEqual(tray.code, 'lot_no_stock')
        self.assertEqual(tray.product_id, product)
        self.assertEqual(tray.severity, 'danger')
        self.assertTrue(tray.line_ids, 'Debe traer al menos una fila.')
        line = tray.line_ids[:1]
        self.assertEqual(line.res_model, 'stock.lot')
        keys = set(line.action_ids.mapped('key'))
        self.assertIn('reassign', keys)
        self.assertIn('view_supporting_moves', keys)
        reassign = line.action_ids.filtered(
            lambda act: act.key == 'reassign')[:1]
        self.assertEqual(reassign.kind, 'execute')
        self.assertTrue(reassign.primary)
        supporting = line.action_ids.filtered(
            lambda act: act.key == 'view_supporting_moves')[:1]
        self.assertEqual(supporting.kind, 'navigate')
        # Navegar (solo lectura): abre las move lines que retienen el lote.
        nav = tray.action_run(line.id, 'view_supporting_moves')
        self.assertEqual(nav['type'], 'ir.actions.act_window')
        self.assertEqual(nav['res_model'], 'stock.move.line')

    def test_ca2_action_run_reassign_executes_existing_saneo(self):
        """``reassign`` (execute) corre el saneo EXISTENTE sin excepción."""
        product = self._no_stock_product('FALLA NOSTOCK SANEO')
        tray = self.Tray._pf_populate(None, 'lot_no_stock', product)
        line = tray.line_ids[:1]

        action = tray.action_run(line.id, 'reassign')
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertTrue(action['params']['message'])

    def test_ca2_action_run_unknown_key_closes(self):
        """La lista blanca: una clave desconocida NO ejecuta (cierra)."""
        product = self._no_stock_product('FALLA NOSTOCK CLAVE')
        tray = self.Tray._pf_populate(None, 'lot_no_stock', product)
        line = tray.line_ids[:1]

        action = tray.action_run(line.id, 'clave_desconocida')
        self.assertEqual(action['type'], 'ir.actions.act_window_close')

    # ==================================================================
    # CA-3: los casos previos siguen INTACTOS
    # ==================================================================
    def test_ca3_registry_keeps_previous_cases(self):
        self.assertEqual(
            self.Registry._pf_failure_for('lot_orphan_reservation')._name,
            'printflow.flow.failure.lot.orphan')
        self.assertEqual(
            self.Registry._pf_failure_for('data_anomaly')._name,
            'printflow.flow.failure.over.reservation')
        supported = self.Registry._pf_supported()
        self.assertIn('lot_orphan_reservation', supported)
        self.assertIn('data_anomaly', supported)
        self.assertIn('lot_no_stock', supported)

    def test_ca3_orphan_guided_tray_still_opens(self):
        """La guiada de la falla HUÉRFANA sigue abriendo (3 args, paridad)."""
        product = self._orphan_product('FALLA HUERFANA SIGUE')
        wizard = self._wizard(product)

        guided = wizard.action_run_pf_plan(
            'lot_orphan_reservation', 'solution', product.id)
        self.assertEqual(guided['res_model'], 'printflow.flow.failure.tray')

    # ==================================================================
    # CA-4: solo lectura + motor externo intacto
    # ==================================================================
    def test_ca4_new_file_has_no_raw_sql(self):
        path = get_module_path('printflow_gestion_inventario')
        self.assertTrue(path, 'El módulo debe estar instalado en disco.')
        file_path = os.path.join(
            path, 'models', 'printflow_flow_failure_lot_no_stock.py')
        with open(file_path, 'r', encoding='utf-8') as handler:
            source = handler.read()
        self.assertNotIn('cr.execute(', source)
        self.assertNotIn('cr.commit(', source)

    def test_ca4_external_motor_reused_untouched(self):
        """La falla REUTILIZA primitivas EXISTENTES del motor (no las reinventa)."""
        self.assertTrue(hasattr(
            self.env['printflow.stock.health'], '_pf_reassign_by_lot'))
        self.assertTrue(hasattr(
            self.env['printflow.stock.remedy'], '_pf_assert_can_clean'))
        failure = self.Registry._pf_failure_for('lot_no_stock')
        self.assertEqual(failure._name, 'printflow.flow.failure.lot.no.stock')
        self.assertEqual(failure._pf_fault_code(), 'lot_no_stock')
