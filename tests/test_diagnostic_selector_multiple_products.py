# -*- coding: utf-8 -*-
"""Selector del Nivel 1 cuando el pedido tiene VARIOS productos.

Con más de un producto terminado con demanda pendiente, el tablero NO
auto-enfoca: el formulario muestra el selector (``show_product_selector``) y
habilita el cambio de producto (``can_switch_product``). Desde una fila se entra
a la línea de tiempo (``line.action_open_product``) y el botón
``action_back_to_products`` devuelve al selector limpiando el foco.

Son de SOLO LECTURA: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticSelectorMultipleProducts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Selector Multiple (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests de diagnóstico)
    # ------------------------------------------------------------------
    def _make_product(self, name, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        product = self.env['product.product'].create(vals)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _force_order(self, lines, partner=None):
        so = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        return so, board

    def _open_wizard(self, board):
        action = board.action_open_diagnostic_wizard()
        self.assertEqual(
            action.get('res_model'), 'printflow.order.diagnostic.wizard')
        return self.env[
            'printflow.order.diagnostic.wizard'].browse(action['res_id'])

    # ------------------------------------------------------------------
    # Caso
    # ------------------------------------------------------------------
    def test_selector_then_drill_and_back(self):
        product_a = self._make_product('SELECTOR PRODUCTO A (DIAG)')
        product_b = self._make_product('SELECTOR PRODUCTO B (DIAG)')
        self._add_stock(product_a, 5.0)
        self._add_stock(product_b, 5.0)
        _so, board = self._force_order([(product_a, 1.0), (product_b, 1.0)])

        wizard = self._open_wizard(board)

        # Sin foco y con dos productos: se muestra el selector.
        self.assertFalse(wizard.focus_line_id)
        self.assertEqual(wizard.finished_product_count, 2)
        self.assertTrue(wizard.show_product_selector)
        self.assertTrue(wizard.can_switch_product)
        self.assertFalse(wizard.is_timeline)

        # Drill: entrar a la línea de tiempo del producto A.
        line_a = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product_a)
        self.assertEqual(len(line_a), 1)
        line_a.action_open_product()
        self.assertEqual(wizard.focus_line_id, line_a)
        self.assertTrue(wizard.is_timeline)

        # Volver a productos limpia el foco y regresa al selector.
        wizard.action_back_to_products()
        self.assertFalse(wizard.focus_line_id)
        self.assertFalse(wizard.is_timeline)
        self.assertTrue(wizard.show_product_selector)
