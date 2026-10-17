# -*- coding: utf-8 -*-
"""Diagnóstico de pedido POR PRODUCTO Y POR NIVELES (PrintFlow).

Cubre la reestructuración "Nivel 1 -> línea de tiempo -> (popover)":
  (a) Nivel 1 lista SOLO productos terminados (sin componentes);
  (b) cada producto tiene su propio semáforo/nodos en un pedido multi-producto;
  (c) cada nodo roto genera su fila de falla con causa del playbook;
  (d) la navegación se gobierna SOLO por `focus_line_id` (sin `level` ni
      `focus_node`: el Nivel 3 se fusionó en el popover del nodo);
  (e) las vistas ya NO exponen el radio de rutas ni los botones de aplicar;
  (f) el recálculo preserva `focus_line_id`;
  (g) el fallo del componente aparece en el `flow_failure_ids` del terminado.
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticLevels(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Niveles Diagnostico',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Niveles Diagnostico',
            'supplier_rank': 1,
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name, purchasable=False, **extra):
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
            'purchase_ok': purchasable,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _force_order(self, lines, partner=None):
        """Pedido forzado a 'sale' (sin procurement) + su tarjeta de tablero."""
        so = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return so, board

    def _diagnose(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    # ------------------------------------------------------------------
    # (a) Nivel 1: solo terminados
    # ------------------------------------------------------------------
    def test_level_products_lists_only_finished(self):
        """El Nivel 1 no mezcla componentes: `product_line_ids` filtra finished."""
        finished_a = self._make_product('TERMINADO A (NIVELES)', purchasable=True)
        finished_b = self._make_product('TERMINADO B (NIVELES)', purchasable=True)
        _so, board = self._force_order([(finished_a, 2.0), (finished_b, 1.0)])
        wizard = self._diagnose(board)

        self.assertTrue(wizard.product_line_ids)
        self.assertTrue(all(
            l.line_kind == 'finished' for l in wizard.product_line_ids))
        self.assertEqual(len(wizard.product_line_ids), 2)

    # ------------------------------------------------------------------
    # (b) Estado por producto en pedido multi-producto
    # ------------------------------------------------------------------
    def test_per_product_status_in_multi_product_order(self):
        """Dos productos que fallan en nodos DISTINTOS exponen su propio nodo."""
        # A: comprable, sin stock ni PO -> falta comprar (déficit físico).
        product_a = self._make_product(
            'PRODUCTO A COMPRAR (NIVELES)', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        # B: stock disponible pero reservado por OTRO pedido -> contención.
        product_b = self._make_product('PRODUCTO B CONTENCION (NIVELES)')
        self._add_stock(product_b, 5.0)
        # Otro pedido se lleva todo el stock (confirmado, reserva de verdad).
        other = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product_b.id,
                'product_uom_qty': 5.0,
                'product_uom': product_b.uom_id.id,
            })],
        })
        other.action_confirm()

        _so, board = self._force_order([(product_a, 3.0), (product_b, 3.0)])
        wizard = self._diagnose(board)

        line_a = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product_a)
        line_b = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product_b)
        self.assertEqual(len(line_a), 1)
        self.assertEqual(len(line_b), 1)

        self.assertEqual(line_a.root_cause_node, 'purchase')
        self.assertEqual(line_a.severity, 'danger')
        self.assertEqual(line_b.root_cause_node, 'stock')
        self.assertEqual(line_b.severity, 'warning')
        # El foco de la línea de tiempo refleja el nodo del producto ENFOCADO.
        wizard.write({'focus_line_id': line_b.id})
        self.assertEqual(wizard.focus_stock_status, 'over')
        self.assertTrue(wizard.is_timeline)
        wizard.write({'focus_line_id': line_a.id})
        self.assertEqual(wizard.focus_purchase_status, 'missing')

    # ------------------------------------------------------------------
    # (c) Fallas por nodo
    # ------------------------------------------------------------------
    def test_failures_per_broken_node(self):
        """Cada nodo roto deja su fila con la causa del playbook."""
        product_a = self._make_product(
            'PRODUCTO FALLAS (NIVELES)', purchasable=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        _so, board = self._force_order([(product_a, 4.0)])
        wizard = self._diagnose(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product_a)

        self.assertTrue(line.failure_ids)
        by_node = {f.node: f for f in line.failure_ids}
        self.assertIn('stock', by_node)
        self.assertIn('purchase', by_node)
        # La fila de stock ahora se clasifica por el REMEDIO FÍSICO (producto
        # comprable con proveedor -> buy_product), no por el genérico
        # 'order_shortfall'. La fila de compras conserva su causa.
        self.assertEqual(by_node['stock'].pf_cause, 'buy_product')
        self.assertEqual(by_node['purchase'].pf_cause, 'order_supply_missing')
        self.assertTrue(line.failure_summary)
        self.assertEqual(line.failed_node_count, len(line.failure_ids))
        # Las tres acciones del playbook quedan materializadas.
        purchase_failure = by_node['purchase']
        self.assertTrue(purchase_failure.pf_solution_label)
        # La SOLUCIÓN del plan guía a COMPRAR lo que falta (destino buy_product):
        # coincide con el remedio estructural, así que el remedio queda
        # REDUNDANTE y se apaga (regla anti-duplicación).
        self.assertEqual(
            purchase_failure.pf_solution_target, 'buy_product')
        self.assertFalse(purchase_failure.pf_remedy_available)
        self.assertEqual(purchase_failure.pf_remedy_target, 'buy_product')
        # El botón "Solucionar" sigue abriendo la Compra Rápida (por la solución).
        self.assertEqual(
            purchase_failure.action_open_solution()['res_model'],
            'mrp.quick.purchase.wizard')

    # ------------------------------------------------------------------
    # (d) Drill y Volver (focus_line_id)
    # ------------------------------------------------------------------
    def test_drill_navigation_between_levels(self):
        product = self._make_product('PRODUCTO DRILL (NIVELES)', purchasable=True)
        _so, board = self._force_order([(product, 1.0)])
        wizard = self._diagnose(board)
        self.assertFalse(wizard.focus_line_id)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)

        # Nivel 1 -> línea de tiempo (método de la LÍNEA, botón de fila).
        line.action_open_product()
        self.assertEqual(wizard.focus_line_id, line)
        self.assertTrue(wizard.is_timeline)

        # Volver a productos limpia el foco.
        wizard.action_back_to_products()
        self.assertFalse(wizard.focus_line_id)
        self.assertFalse(wizard.is_timeline)

    # ------------------------------------------------------------------
    # (e) Sin radio de rutas ni botones de aplicar
    # ------------------------------------------------------------------
    def test_views_do_not_expose_route_ui(self):
        base = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form')
        arch = base.arch_db or ''
        self.assertNotIn('resolution_route', arch)
        self.assertNotIn('action_apply_route', arch)
        self.assertNotIn('action_apply_plan', arch)
        self.assertIn('product_line_ids', arch)
        # El rediseño ELIMINA el botón de componentes y el campo `level`.
        self.assertNotIn('action_open_components', arch)
        self.assertNotIn('name="level"', arch)

        resolution = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_order_diagnostic_wizard_view_form_resolution')
        res_arch = resolution.arch_db or ''
        self.assertNotIn('action_apply_plan', res_arch)
        self.assertNotIn('resolution_route', res_arch)

    # ------------------------------------------------------------------
    # (f) Recalcular preserva foco
    # ------------------------------------------------------------------
    def test_recalculate_preserves_focus(self):
        product = self._make_product(
            'PRODUCTO RECALCULO FOCO (NIVELES)', purchasable=True)
        _so, board = self._force_order([(product, 2.0)])
        wizard = self._diagnose(board)
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        wizard.write({'focus_line_id': line.id})

        wizard.action_recalculate()

        self.assertTrue(wizard.focus_line_id)
        self.assertEqual(wizard.focus_line_id.product_id, product)

    # ------------------------------------------------------------------
    # (g) El fallo del componente se ve en el terminado y en su nodo
    # ------------------------------------------------------------------
    def test_component_failure_rolls_up_into_finished_line(self):
        finished = self._make_product('TERMINADO CON BOM (NIVELES)')
        # Sin ruta de compra -> fabricación; así se estima el insumo por BoM.
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        component = self._make_product('INSUMO DE BOM (NIVELES)', purchasable=True)
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 2.0,
            })],
        })

        _so, board = self._force_order([(finished, 3.0)])
        wizard = self._diagnose(board)

        # Nivel 1: solo el terminado.
        self.assertEqual(len(wizard.product_line_ids), 1)
        finished_line = wizard.product_line_ids
        self.assertEqual(finished_line.product_id, finished)

        # El componente cuelga del terminado (producto primario).
        component_line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == component)
        self.assertEqual(len(component_line), 1)
        self.assertEqual(component_line.parent_line_id, finished_line)
        self.assertEqual(finished_line.component_count, 1)
        self.assertTrue(finished_line.has_components)
        self.assertFalse(component_line.has_components)

        # El fallo del componente aparece en el roll-up del terminado, con el
        # origen (producto/componente) y el nodo correctos.
        rolled = finished_line.flow_failure_ids.filtered(
            lambda f: f.origin_product_id == component)
        self.assertTrue(rolled, 'El fallo del componente debe subir al terminado.')
        self.assertTrue(rolled.filtered(lambda f: f.node == 'stock'))
        self.assertEqual(rolled.filtered(
            lambda f: f.node == 'stock').origin_product_id, component)
        # El fallo propio del terminado NO se cuela en los del componente.
        self.assertFalse(component_line.flow_failure_ids.filtered(
            lambda f: f.origin_product_id == finished))
