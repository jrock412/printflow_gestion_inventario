# -*- coding: utf-8 -*-
"""Botón unificado "Solucionar" del diagnóstico de pedido (PrintFlow).

Desde que se retiró el botón "Recomendación", el botón "Solucionar"
(``action_open_solution``) ejecuta el REMEDIO estructural (``pf_remedy_*``)
cuando ``pf_remedy_available`` es True y, en cualquier otro caso, la SOLUCIÓN
del playbook (``pf_solution_*``). ``pf_remedy_available`` es el GATE de la
unificación: ya significa "el remedio apunta a un destino distinto al del plan".

Estos tests custodian, en solo lectura y sin ejecutar nada:

  1. ``order_supply_missing``: la SOLUCIÓN del plan guía a comprar lo que falta
     (``buy_product``) y abre la Compra Rápida (no la lista de compras) sin crear
     ninguna OC; el remedio estructural queda redundante y se apaga.
  2. Redundancia: cuando el remedio coincide con la solución, se apaga y el
     botón sigue abriendo una sola acción (la solución).
  3. Remedio ``none``: el botón cae a la solución del plan (albarán / OF).
  4. Alternativa intacta: anomalía + falta física comprable conserva el 2º
     remedio (sin ejecutarlo).
  5. Nodo consecuencia: la VISTA lo oculta, pero el MODELO no se muta.
  6. Vista: ambos botones "Solucionar" gatean con las dos banderas.
"""
from odoo.tests.common import TransactionCase, tagged

import json


@tagged('post_install', '-at_install')
class TestDiagnosticUnifiedSolution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Solución Unificada'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Solución Unificada', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        # Segunda ubicación interna: permite la reserva colgada (quant con libre
        # negativo compensado) que dispara el doble remedio.
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'SOLUCION UNIFICADA EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, purchasable=False, remove_routes=False, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
            'purchase_ok': purchasable,
        }
        vals.update(extra)
        product = self.env['product.product'].create(vals)
        if remove_routes:
            product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _add_stock(self, product, qty, reserved=0.0, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty,
            reserved_quantity=reserved)

    def _force_board(self, product, qty):
        """Pedido forzado a 'sale' (sin procurement) + su tarjeta."""
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

    def _line(self, wizard, product):
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line, 'El producto del pedido debe estar en el wizard.')
        return line

    def _failure(self, line, node):
        failure = line.failure_ids.filtered(lambda f: f.node == node)[:1]
        self.assertTrue(failure, 'Debe existir la falla del nodo %s.' % node)
        return failure

    # ------------------------------------------------------------------
    # 1) order_supply_missing -> la solución del plan guía a comprar (buy_product)
    # ------------------------------------------------------------------
    def test_supply_missing_opens_quick_purchase_via_remedy(self):
        """El botón unificado abre la Compra Rápida (por la solución del plan)."""
        product = self._product(
            'UNIF COMPRABLE SIN OC', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        purchase = self._failure(line, 'purchase')

        self.assertEqual(purchase.pf_cause, 'order_supply_missing')
        # La SOLUCIÓN del plan ahora guía a COMPRAR lo que falta (buy_product) e
        # iguala el destino del remedio estructural -> el remedio queda
        # REDUNDANTE y se apaga (anti-duplicación). El botón sigue abriendo la
        # Compra Rápida, ahora por la vía de la solución.
        self.assertEqual(purchase.pf_solution_target, 'buy_product')
        self.assertFalse(purchase.pf_remedy_available)
        self.assertEqual(purchase.pf_remedy_target, 'buy_product')

        po_before = self.env['purchase.order'].search_count([])
        action = purchase.action_open_solution()
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(
            self.env['purchase.order'].search_count([]), po_before,
            'Abrir la solución NO debe crear la OC (abrir ≠ ejecutar).')

    # ------------------------------------------------------------------
    # 2) Redundancia: el remedio se apaga y queda una sola acción
    # ------------------------------------------------------------------
    def test_redundant_remedy_falls_back_to_single_solution(self):
        """Sin remedio propio (redundante) el botón usa la solución única."""
        product = self._product(
            'UNIF REDUNDANTE', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        stock = self._failure(line, 'stock')

        self.assertEqual(stock.pf_cause, 'buy_product')
        # El remedio coincide con la solución del plan -> se apaga (una acción).
        self.assertFalse(stock.pf_remedy_available)
        self.assertTrue(stock.pf_solution_available)
        self.assertEqual(stock.pf_solution_target, 'buy_product')
        # El botón sigue abriendo la Compra Rápida (ahora por la solución).
        action = stock.action_open_solution()
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')

    # ------------------------------------------------------------------
    # 3) Remedio `none`: cae a la solución del playbook
    # ------------------------------------------------------------------
    def test_remedy_none_falls_back_to_plan_solution(self):
        """Causas sin remedio estructural: manda la solución del playbook."""
        product = self._product('UNIF REMEDIO NONE')
        _so, board = self._force_board(product, 2.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        Failure = self.env['printflow.order.diagnostic.failure']

        # Compra por recibir -> abrir el albarán de entrada.
        receive = Failure.create({
            'line_id': line.id, 'pf_cause': 'order_receive_pending',
            'node': 'purchase', 'severity': 'warning',
        })
        self.assertFalse(receive.pf_remedy_available)
        self.assertEqual(
            receive.action_open_solution()['res_model'], 'stock.picking')

        # Fabricación trabada -> abrir la Orden de Fabricación.
        production = Failure.create({
            'line_id': line.id, 'pf_cause': 'order_production_blocked',
            'node': 'production', 'severity': 'danger',
        })
        self.assertFalse(production.pf_remedy_available)
        self.assertEqual(
            production.action_open_solution()['res_model'], 'mrp.production')

    # ------------------------------------------------------------------
    # 4) Alternativa intacta (anomalía + falta física comprable)
    # ------------------------------------------------------------------
    def test_alternative_remedy_kept_without_executing(self):
        """Conserva el 2º remedio y NO ejecuta nada (abrir ≠ ejecutar)."""
        product = self._product(
            'UNIF DOBLE REMEDIO', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})],
            remove_routes=True)
        # Quant con libre negativo compensado + agregado insuficiente.
        self._add_stock(product, 1.0, reserved=4.0, location=self.extra_location)
        self._add_stock(product, 10.0)
        _so, board = self._force_board(product, 20.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        stock = self._failure(line, 'stock')

        self.assertGreater(line.deficit_qty, 0.0)
        self.assertTrue(stock.pf_second_remedy_available)
        self.assertEqual(
            stock.pf_second_remedy_target, 'fix_over_reservation')

        # "Abrir ≠ ejecutar": solo se inspecciona; el inventario no se toca.
        reserved_before = sum(self.env['stock.quant'].search([
            ('product_id', '=', product.id),
        ]).mapped('reserved_quantity'))
        reserved_after = sum(self.env['stock.quant'].search([
            ('product_id', '=', product.id),
        ]).mapped('reserved_quantity'))
        self.assertAlmostEqual(reserved_before, reserved_after, places=3)

    # ------------------------------------------------------------------
    # 5) Nodo consecuencia: la vista lo oculta, el MODELO no se muta
    # ------------------------------------------------------------------
    def test_consequence_keeps_model_solution_untouched(self):
        """La consecuencia no muta el modelo: la solución sigue disponible."""
        product = self._product(
            'UNIF CONSECUENCIA', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})],
            remove_routes=True)
        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        stock = self._failure(line, 'stock')

        self.assertEqual(stock.pf_chain_role, 'consequence')
        self.assertTrue(stock.pf_chain_is_consequence)
        # Paridad: el playbook (fuente única) no se muta.
        self.assertTrue(stock.pf_solution_available)

    # ------------------------------------------------------------------
    # 6) Panel: el botón "Solucionar" por fila usa el mismo gate
    # ------------------------------------------------------------------
    def test_panel_solution_gates_on_both_flags(self):
        """El "Solucionar" POR FILA del panel se rige por el mismo gate que la
        tabla (``pf_solution_available`` / ``pf_remedy_available``) y se oculta
        en las consecuencias. La tabla de fallas ya no existe en la vista."""
        product = self._product(
            'UNIF VISTA COMPRABLE', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        purchase = self._failure(line, 'purchase')
        wizard.write({'focus_line_id': line.id})

        payload = json.loads(wizard.focus_timeline_json)
        by_key = {node['key']: node for node in payload['nodes']}
        rows = by_key['purchase']['panel']
        sol_actions = [
            action
            for row in rows for action in row['actions']
            if action['key'] == 'solution']
        self.assertTrue(
            sol_actions, 'La raíz debe ofrecer "Solucionar" en su fila.')
        self.assertTrue(sol_actions[0]['enabled'])
        self.assertEqual(sol_actions[0]['failure_id'], purchase.id)

        # La tabla de fallas se eliminó: sus botones ya no están en la vista.
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form').arch_db or ''
        self.assertNotIn('focus_flow_failure_ids', arch)
        self.assertNotIn('action_open_solution', arch)
        self.assertNotIn('action_apply_second_remedy', arch)
