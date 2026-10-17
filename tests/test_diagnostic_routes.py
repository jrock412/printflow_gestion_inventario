# -*- coding: utf-8 -*-
from types import SimpleNamespace

from odoo.tests.common import TransactionCase, tagged

from ..wizard.printflow_order_diagnostic_wizard import ROUTE_SELECTION, _EPS


@tagged('post_install', '-at_install')
class TestDiagnosticRoutes(TransactionCase):
    """Blinda los cambios del wizard de Diagnóstico:

    * A2: ``_route_purchase`` arma UNA compra rápida con TODAS las líneas con
      déficit (no solo la primera).
    * A3: ``_route_reassign`` delega en el helper del tablero y produce el mismo
      efecto que ``action_fix_over_reservation``.
    * A4: ``resolution_route`` y ``recommended_route`` comparten la selección.
    * A6: ``create()`` construye el snapshot (líneas y valores) en un solo paso.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Rutas Diagnostico',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Rutas Diagnostico',
            'supplier_rank': 1,
        })
        cls.product_a = cls.env['product.product'].create({
            'name': 'INSUMO A (DIAGNOSTICO)',
            'type': 'product',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
            'seller_ids': [(0, 0, {'partner_id': cls.supplier.id})],
        })
        cls.product_b = cls.env['product.product'].create({
            'name': 'INSUMO B (DIAGNOSTICO)',
            'type': 'product',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
            'seller_ids': [(0, 0, {'partner_id': cls.supplier.id})],
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_order(self, lines):
        """Pedido forzado a 'sale' (sin confirmar) + su tarjeta de tablero."""
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            }) for product, qty in lines],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return so, board

    def _make_confirmed_order(self, product, qty=1.0):
        """Pedido confirmado de verdad: genera albarán de entrega."""
        so = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return so, board

    # ------------------------------------------------------------------
    # A2 — Compra de TODAS las líneas con déficit
    # ------------------------------------------------------------------
    def test_purchase_route_preloads_all_deficit_lines(self):
        """Pedido con 2 insumos sin stock ni PO: la compra lleva 2 líneas."""
        _so, board = self._make_order([
            (self.product_a, 3.0),
            (self.product_b, 4.0),
        ])
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        deficit = wizard.deficit_line_ids.filtered(
            lambda l: l.deficit_qty > _EPS)
        self.assertEqual(len(deficit), 2)

        action = wizard._route_purchase()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        self.assertTrue(action.get('res_id'))

        po_wizard = self.env['mrp.quick.purchase.wizard'].browse(action['res_id'])
        self.assertTrue(po_wizard.exists())
        self.assertEqual(len(po_wizard.purchase_line_ids), 2)
        qty_by_product = {
            line.product_id: line.product_qty
            for line in po_wizard.purchase_line_ids
        }
        self.assertAlmostEqual(qty_by_product[self.product_a], 3.0, places=3)
        self.assertAlmostEqual(qty_by_product[self.product_b], 4.0, places=3)
        self.assertTrue(
            all(not line.material_received for line in po_wizard.purchase_line_ids),
            'No se debe forzar la recepción del material.',
        )

    def test_purchase_route_with_component_deficit_lines(self):
        """Dos líneas de INSUMO (component) con déficit se cargan ambas."""
        _so, board = self._make_order([(self.product_a, 1.0)])
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        wizard.write({'deficit_line_ids': [
            (5, 0, 0),
            (0, 0, {
                'product_id': self.product_a.id,
                'line_kind': 'component',
                'required_qty': 3.0,
                'deficit_qty': 3.0,
                'uom_id': self.product_a.uom_id.id,
            }),
            (0, 0, {
                'product_id': self.product_b.id,
                'line_kind': 'component',
                'required_qty': 4.0,
                'deficit_qty': 4.0,
                'uom_id': self.product_b.uom_id.id,
            }),
        ]})
        action = wizard._route_purchase()
        po_wizard = self.env['mrp.quick.purchase.wizard'].browse(action['res_id'])
        self.assertEqual(len(po_wizard.purchase_line_ids), 2)
        qty_by_product = {
            line.product_id: line.product_qty
            for line in po_wizard.purchase_line_ids
        }
        self.assertAlmostEqual(qty_by_product[self.product_a], 3.0, places=3)
        self.assertAlmostEqual(qty_by_product[self.product_b], 4.0, places=3)

    # ------------------------------------------------------------------
    # A3 — _route_reassign == action_fix_over_reservation
    # ------------------------------------------------------------------
    def test_route_reassign_matches_board_action(self):
        product = self.env['product.product'].create({
            'name': 'PRODUCTO REASIGNACION (DIAGNOSTICO)',
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        _so_a, board_a = self._make_confirmed_order(product)
        _so_b, board_b = self._make_confirmed_order(product)
        self.assertTrue(
            board_a._get_delivery_pickings(),
            'El pedido confirmado debe tener albarán de entrega.',
        )

        res_board = board_a.action_fix_over_reservation()

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board_b.id,
        })
        wizard.resolution_route = 'reassign'
        res_wizard = wizard._route_reassign()

        self.assertEqual(
            board_a.is_stock_missing, board_b.is_stock_missing,
            'El wizard debe dejar la salud igual que la acción de la tarjeta.',
        )
        self.assertEqual(
            res_board['params']['type'], res_wizard['params']['type'],
            'El tipo de notificación debe coincidir.',
        )
        self.assertEqual(
            res_wizard['params']['next'],
            {'type': 'ir.actions.act_window_close'},
            'El wizard debe cerrarse al terminar.',
        )

    # ------------------------------------------------------------------
    # A4 — Selección compartida
    # ------------------------------------------------------------------
    def test_route_selections_are_shared(self):
        Wizard = self.env['printflow.order.diagnostic.wizard']
        selection = list(Wizard._fields['resolution_route'].selection)
        self.assertEqual(selection, list(ROUTE_SELECTION))
        self.assertEqual(
            selection,
            list(Wizard._fields['recommended_route'].selection),
            'Ambos campos deben exponer exactamente las mismas opciones.',
        )

    # ------------------------------------------------------------------
    # A6 — create() en un solo write
    # ------------------------------------------------------------------
    def test_create_builds_snapshot_and_lines(self):
        _so, board = self._make_order([(self.product_a, 5.0)])
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        self.assertTrue(wizard.has_deficit)
        self.assertAlmostEqual(wizard.deficit_total, 5.0, places=3)
        self.assertEqual(len(wizard.deficit_line_ids), 1)
        line = wizard.deficit_line_ids
        self.assertEqual(line.product_id, self.product_a)
        self.assertEqual(line.uom_id, self.product_a.uom_id)
        self.assertAlmostEqual(line.required_qty, 5.0, places=3)
        self.assertAlmostEqual(line.deficit_qty, 5.0, places=3)
        self.assertEqual(wizard.resolution_route, wizard.recommended_route)

    # ------------------------------------------------------------------
    # C4 — Matriz de decisión (_recommend_route / _root_cause)
    # ------------------------------------------------------------------
    @staticmethod
    def _decision_vals(**overrides):
        """Vals mínimos que consumen ``_recommend_route`` y ``_root_cause``."""
        base = {
            'sale_status': 'ok', 'stock_status': 'ok',
            'purchase_status': 'ok', 'production_status': 'ok',
            'deficit_total': 0.0,
        }
        base.update(overrides)
        return base

    def _wizard_for(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    def test_recommend_route_matrix(self):
        """Falta física → comprar/fabricar; contención → reasignar.

        ``_recommend_route`` solo consulta ``board.procurement_type``, así que
        se le pasa un stub: la matriz se prueba como función pura y no depende
        de la configuración de rutas del entorno de pruebas.
        """
        _so, board = self._make_order([(self.product_a, 1.0)])
        wizard = self._wizard_for(board)
        # _recommend_route solo usa board.procurement_type; con un stub la
        # matriz queda como función pura y no depende de la config del entorno.
        buy = SimpleNamespace(procurement_type='purchase')
        mo = SimpleNamespace(procurement_type='manufacture')

        # Fabricación con déficit y sin PO: hay que comprar el insumo.
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(deficit_total=5.0), 5.0),
            'purchase')
        # Con PO pendiente: recibir (antes que fabricar).
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(
                deficit_total=5.0, purchase_status='pending'), 5.0),
            'receive')
        # Con insumo cubierto pero sin MO: producir.
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(
                deficit_total=5.0, production_status='no_mo'), 5.0),
            'produce')
        # Compra con déficit: comprar (aunque no falte la PO).
        self.assertEqual(
            wizard._recommend_route(buy, self._decision_vals(
                deficit_total=5.0, purchase_status='missing'), 5.0),
            'purchase')

        # Contención: NUNCA comprar, siempre reasignar.
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(stock_status='over'), 0.0),
            'reassign')

        # Sin déficit: recibir, aprobar arte o fabricar.
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(purchase_status='pending'), 0.0),
            'receive')
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(production_status='design'), 0.0),
            'design')
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(production_status='material'), 0.0),
            'produce')

        # Flujo sano: solo diagnóstico.
        self.assertEqual(
            wizard._recommend_route(mo, self._decision_vals(), 0.0), 'none')

    def test_root_cause_matrix(self):
        """Cada combinación de nodo roto apunta al nodo correcto."""
        _so, board = self._make_order([(self.product_a, 1.0)])
        wizard = self._wizard_for(board)

        root, _detail = wizard._root_cause(
            board, self._decision_vals(sale_status='pending'), [])
        self.assertEqual(root, 'sale')

        root, _detail = wizard._root_cause(
            board, self._decision_vals(stock_status='over'), [])
        self.assertEqual(root, 'stock')

        root, _detail = wizard._root_cause(
            board, self._decision_vals(
                stock_status='deficit', purchase_status='missing',
                deficit_total=3.0), [])
        self.assertEqual(root, 'purchase')

        root, _detail = wizard._root_cause(
            board, self._decision_vals(
                stock_status='deficit', purchase_status='ok'), [])
        self.assertEqual(root, 'stock')

        root, _detail = wizard._root_cause(
            board, self._decision_vals(purchase_status='pending'), [])
        self.assertEqual(root, 'purchase')

        root, _detail = wizard._root_cause(
            board, self._decision_vals(production_status='no_mo'), [])
        self.assertEqual(root, 'production')

        root, detail = wizard._root_cause(board, self._decision_vals(), [])
        self.assertFalse(root)
        self.assertTrue(detail)
