# -*- coding: utf-8 -*-
"""Ruteo a "Salud de inventario" para fallas acumuladas / backlog (FEATURE B).

Cuando la falla es sistémica (sobre-reserva agregada, quant negativo, virtual
negativo o N entregas pendientes >= umbral), la raíz de la cadena expone el
botón que abre la bandeja ``printflow.inventory.health`` POBLADA y FILTRADA al
producto. Un déficit puro (sin sobre-reserva y con pocas entregas pendientes) NO
se enruta: la compra rápida sigue disponible.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticBacklogRouting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Backlog'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Backlog', 'supplier_rank': 1})
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

    def _add_stock(self, product, qty, reserved=0.0):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, reserved_quantity=reserved)

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

    def _diagnose(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})

    def _root_failure(self, wizard, product):
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertTrue(line, 'La línea del producto debe existir.')
        root = line.failure_ids.filtered(
            lambda f: f.pf_chain_role == 'root')[:1]
        self.assertTrue(root, 'Debe existir una raíz de la cadena.')
        return root

    # ------------------------------------------------------------------
    # Sobre-reserva agregada -> backlog con ruteo a la bandeja
    # ------------------------------------------------------------------
    def test_over_reservation_routes_to_inventory_health(self):
        product = self._product('BACKLOG SOBRE-RESERVA')
        # Libre agregado NEGATIVO (sobrepedido real): 1 en almacén, 5 reservados.
        self._add_stock(product, 1.0, reserved=5.0)

        _so, board = self._force_board(product, 1.0)
        wizard = self._diagnose(board)
        root = self._root_failure(wizard, product)
        self.assertEqual(root.node, 'stock')

        self.assertTrue(root.pf_is_backlog)
        self.assertTrue(root.pf_backlog_reasons)
        self.assertTrue(root.pf_backlog_available)

        action = root.action_open_inventory_health()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.inventory.health')
        self.assertEqual(
            action['domain'], [('product_id', 'in', [product.id])])
        # La bandeja quedó POBLADA solo con el producto de la falla.
        rows = self.env['printflow.inventory.health'].search([])
        self.assertEqual(rows.mapped('product_id'), product)

    # ------------------------------------------------------------------
    # Déficit puro (sin sobre-reserva, sin backlog) -> NO se enruta
    # ------------------------------------------------------------------
    def test_pure_deficit_does_not_route_to_backlog(self):
        product = self._product(
            'BACKLOG DEFICIT PURO', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]

        _so, board = self._force_board(product, 3.0)
        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        by_node = {f.node: f for f in line.failure_ids}
        purchase = by_node['purchase']
        stock = by_node['stock']

        # No es backlog y NO se expone el ruteo.
        self.assertFalse(purchase.pf_is_backlog)
        self.assertFalse(purchase.pf_backlog_available)
        self.assertFalse(stock.pf_is_backlog)

        # La vía de solución física (compra rápida) sigue disponible.
        self.assertTrue(stock.pf_solution_available)
        action = stock.action_open_solution()
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')

    # ------------------------------------------------------------------
    # Cabecera del pedido: acción a la bandeja con los productos backlog
    # ------------------------------------------------------------------
    def test_header_action_collects_order_backlog_products(self):
        product = self._product('BACKLOG CABECERA')
        self._add_stock(product, 1.0, reserved=5.0)
        _so, board = self._force_board(product, 1.0)
        wizard = self._diagnose(board)

        self.assertTrue(wizard.pf_has_backlog)
        action = wizard.action_open_inventory_health()
        self.assertEqual(action['res_model'], 'printflow.inventory.health')
        self.assertEqual(
            action['domain'], [('product_id', 'in', [product.id])])
