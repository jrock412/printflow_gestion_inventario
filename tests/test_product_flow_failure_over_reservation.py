# -*- coding: utf-8 -*-
"""Reserva colgada REAL vs existencia negativa + bandeja guiada (PrintFlow).

Cubre el defecto de la tarjeta FONDO NEGRO (product.product 13058, quant 15197):

  (a) un quant NEGATIVO SIN reserva (``quantity < 0`` y ``reserved <= 0``) NO es
      una "reserva colgada": cae a la causa ``negative`` (ajuste de inventario) y
      NO dispara la anomalía ``data_anomaly``;
  (b) un quant con RESERVA REAL (``reserved > 0`` y ``quantity < reserved``) SÍ
      se marca como reserva colgada (anomalía);
  (c) el "Solucionar" de ``data_anomaly`` ABRE la bandeja guiada
      (``printflow.flow.failure.tray``) con una fila por quant afectado y la
      acción explícita de saneo/re-reserva (ya no es un one-click ciego).

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestProductFlowFailureOverReservation(
        PrintflowStockHealthTestMixin, TransactionCase):
    """Criterio único de reserva colgada + bandeja guiada de saneo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Reserva Colgada'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        # Segunda ubicación interna: permite la reserva colgada (quant con
        # reservado > físico) compensada por otro quant con existencia libre.
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'RESERVA COLGADA EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.Engine = cls.env['printflow.order.health.engine']
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Health = cls.env['printflow.stock.health']
        cls.Tray = cls.env['printflow.flow.failure.tray']
        cls.Flow = cls.env['printflow.product.flow']
        cls.Failure = cls.env['printflow.order.diagnostic.failure']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _finished(self, name):
        product = self._pf_product(name, x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _negative_without_reservation(self, name):
        """Quant NEGATIVO puro: ``quantity < 0`` y ``reserved == 0``."""
        product = self._finished(name)
        self._pf_add_stock(product, -5.0)
        return product

    def _hanging_reservation(self, name):
        """Quant con RESERVA REAL: ``reserved > 0`` y ``quantity < reserved``."""
        product = self._finished(name)
        self._pf_add_stock(product, 1.0, reserved=5.0,
                           location=self.extra_location)
        self._pf_add_stock(product, 10.0)
        return product

    # ------------------------------------------------------------------
    # (a) Existencia negativa SIN reserva NO es reserva colgada
    # ------------------------------------------------------------------
    def test_negative_quant_without_reservation_is_not_hanging(self):
        product = self._negative_without_reservation('FALLA NEGATIVO PURO')

        state = self.Remedy._pf_product_reservation_state(product)
        self.assertFalse(
            state['has_negative_quant'],
            'Un quant negativo sin reserva NO es una reserva colgada.')
        self.assertNotIn(
            product.id,
            self.Engine._pf_reservation_anomaly_products([product.id]))
        self.assertNotIn(
            product.id,
            self.Remedy._pf_negative_quant_product_ids([product.id]))

    def test_compensated_negative_quant_is_not_anomaly(self):
        """Caso real FONDO NEGRO: quant negativo (reserved=0) con total positivo.

        Un quant con existencia negativa sin reserva, compensado por otro con
        existencia, NO es reserva colgada (antes se reportaba como tal).
        """
        product = self._finished('FALLA FONDO NEGRO')
        self._pf_add_stock(product, -229.0, location=self.extra_location)
        self._pf_add_stock(product, 882.76)

        state = self.Remedy._pf_product_reservation_state(product)
        self.assertFalse(state['has_negative_quant'])
        self.assertNotIn(
            product.id,
            self.Engine._pf_reservation_anomaly_products([product.id]))
        self.assertNotIn(
            product.id,
            self.Remedy._pf_negative_quant_product_ids([product.id]))
        self.assertNotIn(product, self.Health._pf_products_in_alert())

    def test_negative_quant_falls_to_negative_cause_and_adjust(self):
        """La existencia negativa pura cae a la causa ``negative`` (ajuste)."""
        product = self._negative_without_reservation('FALLA NEGATIVO AJUSTE')
        wizard = self.env['printflow.product.diagnostic.wizard'].create({
            'product_ids': [(6, 0, [product.id])],
        })
        findings = wizard.finding_ids.filtered(
            lambda f: f.product_id == product)
        negative = findings.filtered(
            lambda f: f.check_code == 'stock_negative')
        self.assertTrue(negative, 'Debe emitirse la existencia negativa.')
        self.assertEqual(negative[:1].pf_cause, 'negative')
        self.assertEqual(negative[:1].pf_remedy_target, 'quants_adjust')
        # NO se reporta como anomalía de reserva colgada.
        self.assertFalse(
            findings.filtered(
                lambda f: f.pf_cause == 'data_anomaly'),
            'Una existencia negativa sin reserva no puede ser data_anomaly.')

    # ------------------------------------------------------------------
    # (b) Reserva REAL SÍ se marca como colgada
    # ------------------------------------------------------------------
    def test_hanging_reservation_is_marked(self):
        product = self._hanging_reservation('FALLA RESERVA REAL')

        state = self.Remedy._pf_product_reservation_state(product)
        self.assertTrue(state['has_negative_quant'])
        self.assertIn(
            product.id,
            self.Engine._pf_reservation_anomaly_products([product.id]))
        self.assertIn(
            product.id,
            self.Remedy._pf_negative_quant_product_ids([product.id]))
        self.assertEqual(
            self.Remedy._pf_classify_reservation(product), 'anomaly')

    # ------------------------------------------------------------------
    # (c) Bandeja guiada de la reserva colgada
    # ------------------------------------------------------------------
    def test_tray_populates_with_hanging_quant_and_actions(self):
        product = self._hanging_reservation('FALLA BANDEJA COLGADA')
        tray = self.Tray._pf_populate(None, 'data_anomaly', product)

        self.assertTrue(tray)
        self.assertEqual(tray.code, 'data_anomaly')
        self.assertEqual(tray.product_id, product)
        self.assertEqual(len(tray.line_ids), 1)
        line = tray.line_ids[:1]
        self.assertEqual(line.res_model, 'stock.quant')
        keys = set(line.action_ids.mapped('key'))
        self.assertEqual(
            keys, {'release_reservation', 'view_quant', 'leave'})

        # Lista blanca: una clave desconocida NO ejecuta nada (cierra).
        action = tray.action_run(line.id, 'clave_desconocida')
        self.assertEqual(action['type'], 'ir.actions.act_window_close')
        # Navegar: abre el quant afectado (solo lectura).
        action = tray.action_run(line.id, 'view_quant')
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertEqual(action['res_id'], line.res_id)

    def test_flow_solution_opens_guided_tray(self):
        """El "Solucionar" de ``data_anomaly`` abre la bandeja guiada."""
        product = self._hanging_reservation('FALLA FLUJO COLGADA')
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])

        guided = wizard.action_run_pf_plan(
            'data_anomaly', 'solution', product.id)
        self.assertEqual(guided['res_model'], 'printflow.flow.failure.tray')

    def test_order_solution_opens_guided_tray(self):
        """El "Solucionar" de la falla de pedido también abre la bandeja."""
        product = self._hanging_reservation('FALLA PEDIDO COLGADA')
        board = self._pf_force_board(product, 1.0)
        wizard = self._pf_diagnose(board)
        line = self._pf_line(wizard, product)
        self.assertTrue(line, 'Debe existir la línea de producto.')
        failure = self.Failure.create({
            'line_id': line.id, 'pf_cause': 'data_anomaly',
            'node': 'stock', 'severity': 'warning',
        })
        action = failure.action_open_solution()
        self.assertEqual(action['res_model'], 'printflow.flow.failure.tray')
        tray = self.Tray.browse(action['res_id'])
        self.assertTrue(tray.line_ids)

    def test_tray_execute_saneo_reassigns_by_rules(self):
        """Ejecutar el saneo re-asigna según Odoo, sin one-click ciego."""
        # Reserva REAL respaldada por un albarán: físco bajado a 1 sin reconciliar
        # (patrón del bug), de modo que el saneo tenga una reserva que corregir.
        product = self._finished('FALLA SANEO EJECUTA')
        self._pf_add_stock(product, 5.0)
        self._pf_confirm_order(product, 5.0)
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.stock_location.id)], limit=1)
        quant.sudo().write({'quantity': 1.0})
        self.assertTrue(
            self.Remedy._pf_product_reservation_state(
                product)['has_negative_quant'])

        tray = self.Tray._pf_populate(None, 'data_anomaly', product)
        line = tray.line_ids[:1]
        action = tray.action_run(line.id, 'release_reservation')
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        # Tras re-asignar, la reserva no puede superar el físico real (1).
        quant.invalidate_recordset()
        self.assertLessEqual(quant.reserved_quantity, 1.0 + 1e-6)
