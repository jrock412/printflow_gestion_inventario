# -*- coding: utf-8 -*-
"""Anti-redundancia de la cadena: la consecuencia NO expone solución (vista).

Regla de la FEATURE A: la solución de una falla consecuente se oculta SOLO a
nivel de VISTA (``pf_chain_is_consequence``); el MODELO no se muta. Este test
custodia la paridad: ``pf_solution_available`` de la falla consecuente sigue
siendo el del playbook (fuente única), mientras los botones de la vista quedan
gateados.
"""
from odoo.tests.common import TransactionCase, tagged

import json


@tagged('post_install', '-at_install')
class TestDiagnosticChainNoDuplicateSolution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Anti Duplicado Cadena'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Anti Duplicado Cadena', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

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

    def test_model_solution_available_is_unchanged(self):
        """Paridad: la consecuencia SIGUE con su solución en el MODELO."""
        product = self._product(
            'ANTIDUP COMPRABLE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)
        stock = line.failure_ids.filtered(lambda f: f.node == 'stock')
        self.assertTrue(stock)
        # El playbook (fuente única) no se mutó: la solución sigue disponible.
        self.assertEqual(stock.pf_chain_role, 'consequence')
        self.assertTrue(stock.pf_solution_available)

    def test_panel_gates_solution_on_consequence(self):
        """El PANEL del diagrama oculta "Solucionar"/"Alternativa" en las
        consecuencias (gate por ``pf_chain_is_consequence``).

        La tabla de fallas se ELIMINÓ: el gate ya no vive en botones de una
        vista, sino en las ACCIONES POR FILA del panel que arma el backend.
        "Recopilar" y "Salud de inventario" siguen con UNA SOLA entrada en el
        popover del nodo RAÍZ (decisión 14).
        """
        product = self._product(
            'ANTIDUP VISTA COMPRABLE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})

        payload = json.loads(wizard.focus_timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}

        # La CONSECUENCIA solo informa: nada de solución ni alternativa.
        stock = by_key['stock']
        self.assertEqual(stock['role'], 'consequence')
        self.assertTrue(stock['panel'])
        for row in stock['panel']:
            keys = [action['key'] for action in row['actions']]
            self.assertNotIn('solution', keys)
            self.assertNotIn('second_remedy', keys)
            for key in keys:
                self.assertEqual(key, 'problem')

        # La RAÍZ sí ofrece "Solucionar" en su fila.
        purchase = by_key['purchase']
        root_keys = {
            action['key']
            for row in purchase['panel'] for action in row['actions']}
        self.assertIn('solution', root_keys)

        # La solución de la raíz es la acción PRIMARIA (hero) y va primero.
        root_solution = next(
            action
            for row in purchase['panel'] for action in row['actions']
            if action['key'] == 'solution')
        self.assertTrue(root_solution.get('primary'))
        self.assertEqual(root_solution['label'], 'Solucionar')

        # La tabla de fallas ya NO está en la vista (ni sus botones).
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form').arch_db or ''
        self.assertNotIn('focus_flow_failure_ids', arch)
        self.assertNotIn('action_open_collect', arch)
        self.assertNotIn('action_open_inventory_health', arch)
