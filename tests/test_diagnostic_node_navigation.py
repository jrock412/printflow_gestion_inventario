# -*- coding: utf-8 -*-
"""Navegación del diagnóstico de pedido (PrintFlow).

El rediseño eliminó el Nivel 3 y su ``focus_node``: el único estado de
navegación es ``focus_line_id``. Esto tests custodia:
  * ``action_open_product`` enfoca el producto y muestra el canvas;
  * ``action_back_to_products`` limpia el foco;
  * ``action_recalculate`` preserva el foco en el MISMO producto.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticNodeNavigation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Node Navigation (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _build_wizard_with_stock_and_production_failures(self):
        """Terminado con BOM sin MO + componente en contención: dos nodos rotos."""
        finished = self._make_product('TERMINADO NAV')
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        component = self._make_product('COMPONENTE NAV')
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
            })],
        })
        self._add_stock(component, 10.0)
        other = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': component.id,
                'product_uom_qty': 10.0,
                'product_uom': component.uom_id.id,
            })],
        })
        other.action_confirm()
        # Existencia del terminado: su propio inventario queda en 'ok' y el
        # 'over' de la línea de tiempo solo puede venir del componente.
        self._add_stock(finished, 3.0)

        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': finished.id,
                'product_uom_qty': 3.0,
                'product_uom': finished.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        board.write({'production_alert': 'no_order'})
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == finished)
        return wizard, line

    # ------------------------------------------------------------------
    # Casos
    # ------------------------------------------------------------------
    def test_open_product_focuses_timeline(self):
        wizard, line = self._build_wizard_with_stock_and_production_failures()
        self.assertFalse(wizard.focus_line_id)
        self.assertFalse(wizard.is_timeline)

        line.action_open_product()

        self.assertEqual(wizard.focus_line_id, line)
        self.assertTrue(wizard.is_timeline)
        payload = json.loads(wizard.focus_timeline_json)
        # El producto es fabricable: el canvas trae insumos + fabricación.
        keys = [node['key'] for node in payload['nodes']]
        self.assertIn('stock_supply', keys)
        self.assertIn('production', keys)
        # La falla del flujo se reparte por nodo causal en el panel del nodo.
        by_key = {node['key']: node for node in payload['nodes']}
        self.assertGreater(by_key['stock_supply']['issues'], 0)
        self.assertGreater(by_key['production']['issues'], 0)

    def test_back_to_products_and_recalculate_preserve_focus(self):
        wizard, line = self._build_wizard_with_stock_and_production_failures()
        product = line.product_id  # el recálculo borra la línea vieja
        line.action_open_product()
        self.assertTrue(wizard.focus_line_id)

        # Volver a productos limpia el foco y sale del canvas.
        wizard.action_back_to_products()
        self.assertFalse(wizard.focus_line_id)
        self.assertFalse(wizard.is_timeline)

        # Recalcular preserva el foco en el MISMO producto.
        line.action_open_product()
        wizard.action_recalculate()
        self.assertTrue(wizard.focus_line_id)
        self.assertEqual(wizard.focus_line_id.product_id, product)
