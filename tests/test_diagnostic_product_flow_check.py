# -*- coding: utf-8 -*-
"""FASE 4 — El escáner consume el motor unificado de flujo (PrintFlow).

El chequeo ``check_flow`` vuelca el veredicto de
``printflow.product.flow.diagnostic`` como hallazgos estándar del área ``flow``.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticProductFlowCheck(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Flujo Escáner'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _scan(self, products):
        return self.env['printflow.product.diagnostic.wizard'].create({
            'product_ids': [(6, 0, products.ids)],
        })

    def test_flow_area_is_registered(self):
        mixin = self.env['printflow.product.check.mixin']
        codes = [c['code'] for c in mixin._pf_get_checks()]
        self.assertIn('product_flow', codes)

    def test_flow_check_emits_ok_finding(self):
        product = self._pf_product('FLUJO OK', x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        wizard = self._scan(product)
        flow = wizard.finding_ids.filtered(lambda f: f.area == 'flow')
        self.assertTrue(flow)
        self.assertTrue(any(f.check_code == 'product_flow' for f in flow))

    def test_flow_check_classifies_cause(self):
        product = self._pf_product('FLUJO CON CAUSA', x_is_printflow_managed=True)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        # Existencia negativa -> sobre-reserva agregada -> causa de flujo.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        wizard = self._scan(product)
        flow = wizard.finding_ids.filtered(
            lambda f: f.area == 'flow' and f.severity in ('warning', 'error'))
        self.assertTrue(flow)
        # La causa se resuelve vía el prefijo ``flow_<cause>`` en el playbook.
        self.assertTrue(any(f.pf_cause for f in flow))
        self.assertTrue(any('flow_' in (f.check_code or '') for f in flow))

    def test_flow_check_skips_consumable(self):
        """Un producto que NO gestiona inventario no fabrica una causa de flujo."""
        product = self._pf_product(
            'FLUJO CONSUMIBLE', type='consu', x_is_printflow_managed=True)
        wizard = self._scan(product)
        flow = wizard.finding_ids.filtered(
            lambda f: f.area == 'flow' and f.product_id == product
            and f.severity in ('warning', 'error'))
        self.assertFalse(
            flow, 'Un consumible no debe producir una causa de flujo.')

    # ------------------------------------------------------------------
    # E5: la recomendación NUNCA queda vacía para las causas mapeadas.
    # ------------------------------------------------------------------
    def _finding_with_code(self, product, check_code, severity='warning'):
        wizard = self._scan(product)
        return self.env['printflow.product.diagnostic.finding'].create({
            'wizard_id': wizard.id,
            'check_code': check_code,
            'severity': severity,
            'product_id': product.id,
            'area': 'flow',
        })

    def test_data_anomaly_offers_fix_over_reservation(self):
        """``flow_data_anomaly`` -> botón Recomendación con re-reserva."""
        product = self._pf_product('FLUJO ANOMALIA', x_is_printflow_managed=True)
        finding = self._finding_with_code(product, 'flow_data_anomaly')
        self.assertEqual(finding.pf_cause, 'data_anomaly')
        self.assertTrue(finding.pf_remedy_available)
        self.assertEqual(finding.pf_remedy_target, 'fix_over_reservation')
        self.assertEqual(finding.pf_reservation_nature, 'anomaly')

    def test_physical_causes_offer_remedy(self):
        """Las causas físicas del motor unificado no quedan sin recomendación."""
        expected = {
            'flow_manufacture': 'create_production',
            'flow_manufacture_components': 'buy_components',
            'flow_buy_product': 'buy_product',
            'flow_no_bom': 'bom_list',
        }
        product = self._pf_product('FLUJO FISICO', x_is_printflow_managed=True)
        for check_code, target in expected.items():
            with self.subTest(check_code=check_code):
                finding = self._finding_with_code(product, check_code)
                self.assertTrue(
                    finding.pf_remedy_available,
                    'La recomendación no puede quedar vacía para %s.'
                    % check_code)
                self.assertEqual(
                    finding.pf_remedy_target, target,
                    'Destino de recomendación inesperado para %s.' % check_code)
