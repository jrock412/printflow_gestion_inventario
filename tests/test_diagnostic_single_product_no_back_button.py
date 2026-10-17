# -*- coding: utf-8 -*-
"""Un solo producto pendiente -> sin cambio de producto ni selector.

Con EXACTAMENTE un producto terminado con demanda pendiente el wizard nace
enfocado al diagrama: ``finished_product_count == 1``, ``can_switch_product``
Falso y, por tanto, el botón "Volver a productos" queda oculto
(``finished_product_count <= 1``). Son de SOLO LECTURA.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticSingleProductNoBackButton(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Single No Back (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

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

    def test_single_product_hides_switch_and_back(self):
        product = self._make_product('UNICO SIN VOLVER (DIAG)')
        self._add_stock(product, 5.0)
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})

        action = board.action_open_diagnostic_wizard()
        wizard = self.env[
            'printflow.order.diagnostic.wizard'].browse(action['res_id'])

        self.assertEqual(wizard.finished_product_count, 1)
        self.assertFalse(wizard.can_switch_product)
        self.assertFalse(wizard.show_product_selector)
