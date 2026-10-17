# -*- coding: utf-8 -*-
"""Destinos de navegación del diagnóstico de pedido (PrintFlow).

MEJORA B: ``_pf_nav_action`` ya traduce los destinos del contrato del playbook
``quants``, ``sale_lines`` y ``sale_orders``; además, la Bandeja de Resolución
del escáner (``collect_tray``) queda DESACTIVADA aquí porque no existe en el
diagnóstico de pedido. MEJORA C: ``free_exhausted`` sustituye "recopilar" por la
bandeja de ALBARANES DE ENTREGA.

Todo es de SOLO LECTURA: solo se inspeccionan las acciones devueltas.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticOrderNavTargets(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Nav Targets (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _wizard_with_line(self):
        product = self._make_product('NAV TARGETS (DIAG)')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, 5.0)
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line, 'El producto del pedido debe estar en el wizard.')
        return wizard, product, line

    def _failure(self, line, pf_cause=None):
        return self.env['printflow.order.diagnostic.failure'].create({
            'line_id': line.id,
            'pf_cause': pf_cause or False,
        })

    # ------------------------------------------------------------------
    # MEJORA B: destinos nuevos
    # ------------------------------------------------------------------
    def test_nav_quants_opens_internal_quants_of_product(self):
        _wizard, product, line = self._wizard_with_line()
        action = self._failure(line)._pf_nav_action('quants')

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertEqual(action['view_mode'], 'tree,form')
        self.assertEqual(action['target'], 'current')
        self.assertIn(('product_id', '=', product.id), action['domain'])
        self.assertIn(('location_id.usage', '=', 'internal'), action['domain'])

    def test_nav_sale_lines_filters_by_order(self):
        wizard, _product, line = self._wizard_with_line()
        action = self._failure(line)._pf_nav_action('sale_lines')

        self.assertEqual(action['res_model'], 'sale.order.line')
        self.assertEqual(action['target'], 'current')
        self.assertIn(
            ('order_id', '=', wizard.board_id.sale_order_id.id), action['domain'])

    def test_nav_sale_orders_opens_reserving_orders(self):
        _wizard, _product, line = self._wizard_with_line()
        action = self._failure(line)._pf_nav_action('sale_orders')

        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(action['target'], 'current')
        self.assertEqual(list(action['domain'][0][:2]), ['id', 'in'])

    # ------------------------------------------------------------------
    # MEJORA B: collect_tray desactivado en el diagnóstico de pedido
    # ------------------------------------------------------------------
    def test_collect_tray_is_disabled(self):
        _wizard, _product, line = self._wizard_with_line()
        failure = self._failure(line, pf_cause='bom_duplicated')

        self.assertEqual(failure.pf_collect_target, 'collect_tray')
        self.assertFalse(
            failure.pf_collect_available,
            'La Bandeja del escáner no se ofrece en el diagnóstico de pedido.')

    # ------------------------------------------------------------------
    # MEJORA C: free_exhausted recopila albaranes de entrega
    # ------------------------------------------------------------------
    def test_free_exhausted_collect_opens_delivery_orders(self):
        _wizard, _product, line = self._wizard_with_line()
        failure = self._failure(line, pf_cause='free_exhausted')

        self.assertTrue(failure.pf_collect_available)
        self.assertEqual(failure.pf_collect_kind, 'navigate')
        self.assertEqual(failure.pf_collect_target, 'delivery_orders')
        self.assertEqual(
            failure.pf_collect_label, 'Recopilar albaranes de entrega')

        action = failure.action_open_collect()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['target'], 'current')
