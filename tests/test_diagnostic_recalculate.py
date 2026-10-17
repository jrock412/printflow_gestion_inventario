# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticRecalculate(TransactionCase):
    """C1: ``action_recalculate`` debe re-ejecutar el snapshot sobre el MISMO
    wizard (sin recrearlo), reemplazar las líneas de déficit y reflejar de
    inmediato los cambios de stock, sin dejar líneas huérfanas.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Recalcular Diagnostico',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO RECALCULAR (DIAG)',
            'type': 'product',
            'x_is_printflow_managed': True,
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_wizard(self, qty=5.0):
        """Pedido forzado a 'sale' (sin procurement) + su tarjeta y wizard."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    def _add_stock(self, qty):
        self.env['stock.quant']._update_available_quantity(
            self.product, self.stock_location, qty)

    # ------------------------------------------------------------------
    # Casos
    # ------------------------------------------------------------------
    def test_recalculate_refreshes_numbers_without_orphan_lines(self):
        """Entra stock: el déficit desaparece y no quedan líneas viejas."""
        wizard = self._make_wizard(qty=5.0)
        self.assertTrue(wizard.has_deficit)
        self.assertAlmostEqual(wizard.deficit_total, 5.0, places=3)
        old_line_ids = wizard.deficit_line_ids.ids
        self.assertTrue(old_line_ids)

        # Entra justo el stock que faltaba y se recalcula.
        self._add_stock(5.0)
        action = wizard.action_recalculate()

        # La acción recarga el MISMO wizard (target nuevo).
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.order.diagnostic.wizard')
        self.assertEqual(action['res_id'], wizard.id)
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'new')

        self.assertFalse(wizard.has_deficit)
        self.assertAlmostEqual(wizard.deficit_total, 0.0, places=3)

        # Las líneas anteriores se borraron: no hay huérfanas.
        self.assertFalse(
            self.env['printflow.order.diagnostic.wizard.line'].search(
                [('id', 'in', old_line_ids)]),
            'El recálculo no debe dejar líneas huérfanas.',
        )
        # Y la nueva línea ya ve el stock recién cargado.
        new_line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == self.product)
        self.assertEqual(len(new_line), 1)
        self.assertAlmostEqual(new_line.on_hand_qty, 5.0, places=3)
        self.assertAlmostEqual(new_line.deficit_qty, 0.0, places=3)

    def test_recalculate_updates_deficit_upwards(self):
        """Si el stock desaparece, el recálculo vuelve a mostrar el déficit."""
        wizard = self._make_wizard(qty=2.0)
        self._add_stock(2.0)
        wizard.action_recalculate()
        self.assertAlmostEqual(wizard.deficit_total, 0.0, places=3)
        self.assertFalse(wizard.has_deficit)

        # Se retira el stock y se vuelve a recalcular.
        self._add_stock(-2.0)
        wizard.action_recalculate()
        self.assertAlmostEqual(wizard.deficit_total, 2.0, places=3)
        self.assertTrue(wizard.has_deficit)

    def test_recalculate_preserves_chosen_route(self):
        """El recálculo no pisa la ruta que el operador ya eligió."""
        wizard = self._make_wizard(qty=1.0)
        wizard.resolution_route = 'none'
        wizard.action_recalculate()
        self.assertEqual(
            wizard.resolution_route, 'none',
            'El recálculo debe conservar la decisión del operador.',
        )
