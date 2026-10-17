# -*- coding: utf-8 -*-
"""Umbral configurable del backlog (FEATURE B) — cero hardcodeo.

El umbral de entregas pendientes que convierte una falla en "acumulada" vive en
``ir.config_parameter``. Cambiarlo DEBE cambiar el ruteo a Salud de inventario
sin tocar código.
"""
from odoo.tests.common import TransactionCase, tagged

THRESHOLD_PARAM = (
    'x_product_dimensional_pricing.pf_backlog_blocking_threshold')


@tagged('post_install', '-at_install')
class TestDiagnosticBacklogThreshold(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Backlog Umbral'})
        cls.other_customer = cls.env['res.partner'].create(
            {'name': 'Cliente Backlog Umbral Otro'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Backlog Umbral', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _force_board(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return so, self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})

    def _confirm_pending_delivery(self, product, qty=1.0):
        """Pedido AJENO confirmado: genera un albarán de entrega pendiente."""
        so = self.env['sale.order'].create({
            'partner_id': self.other_customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _diagnose(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})

    def _root_failure(self, wizard, product):
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertTrue(line)
        root = line.failure_ids.filtered(
            lambda f: f.pf_chain_role == 'root')[:1]
        self.assertTrue(root)
        return root

    def test_threshold_change_toggles_backlog_routing(self):
        # Escenario de CONTENCIÓN: stock completo pero OTRO pedido lo reserva
        # todo. Así ``free_global`` y ``virtual_available`` quedan en 0 y el
        # ÚNICO disparador posible es el CONTEO de entregas pendientes.
        product = self._product('BACKLOG UMBRAL CONTENCION')
        self._add_stock(product, 5.0)

        # Pedido PROPIO forzado (sin procura -> sin albarán propio): demanda 3.
        _so, board = self._force_board(product, 3.0)
        # Pedido AJENO confirmado: reserva las 5 y deja 1 albarán pendiente.
        self._confirm_pending_delivery(product, 5.0)

        # Umbral por defecto (5): 1 entrega pendiente NO alcanza -> sin backlog.
        self.env['ir.config_parameter'].sudo().set_param(THRESHOLD_PARAM, '5')
        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertEqual(line.pending_delivery_order_count, 1)
        root = self._root_failure(wizard, product)
        self.assertEqual(root.node, 'stock')
        self.assertFalse(root.pf_is_backlog)
        self.assertFalse(root.pf_backlog_available)

        # Baja el umbral a 1: la MISMA situación ahora es backlog.
        self.env['ir.config_parameter'].sudo().set_param(THRESHOLD_PARAM, '1')
        wizard2 = self._diagnose(board)
        root2 = self._root_failure(wizard2, product)
        self.assertTrue(root2.pf_is_backlog)
        self.assertTrue(root2.pf_backlog_available)
        self.assertIn('entregas', root2.pf_backlog_reasons)
