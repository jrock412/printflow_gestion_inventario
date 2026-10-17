# -*- coding: utf-8 -*-
"""Cadena de fallas por niveles del diagnóstico de pedido (FEATURE A).

Caso S09337 sintético: un comprable SIN stock y SIN Orden de Compra rompe DOS
nodos —Compras ("falta comprar") e Inventario ("sin stock")— que son LA MISMA
causa encadenada. El motor de salud ya calcula la raíz (``root_cause_node``):
aquí se verifica que la falla de Compras es la RAÍZ y la de Inventario su
CONSECUENCIA, con padre y orden correctos.

Caso S09336 (fabricado): una OF en BORRADOR (``to_launch``) sobre un producto con
BoM y stock en déficit. Fabricar CREA las existencias, así que Fabricación es la
RAÍZ y el Inventario su CONSECUENCIA (no una falla independiente).
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticFailureChain(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Cadena Fallas',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Cadena Fallas',
            'supplier_rank': 1,
        })
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

    def _force_board(self, product, qty):
        """Pedido forzado a 'sale' (sin procura) + su tarjeta de tablero."""
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

    # ------------------------------------------------------------------
    # S09337: Compras (raíz) -> Inventario (consecuencia)
    # ------------------------------------------------------------------
    def test_s09337_purchase_root_stock_consequence(self):
        product = self._product(
            'CADENA BANNER COMPRABLE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]

        _so, board = self._force_board(product, 4.0)
        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        self.assertEqual(line.root_cause_node, 'purchase')

        by_node = {f.node: f for f in line.failure_ids}
        self.assertIn('purchase', by_node)
        self.assertIn('stock', by_node)
        purchase = by_node['purchase']
        stock = by_node['stock']

        # La raíz es una sola y no cuelga de nadie.
        self.assertEqual(purchase.pf_chain_role, 'root')
        self.assertFalse(purchase.pf_chain_parent_node)
        self.assertEqual(purchase.pf_chain_rank, 0)
        # Inventario es CONSECUENCIA de Compras (misma causa encadenada).
        self.assertEqual(stock.pf_chain_role, 'consequence')
        self.assertEqual(stock.pf_chain_parent_node, 'purchase')
        self.assertTrue(stock.pf_chain_is_consequence)
        self.assertEqual(stock.pf_chain_depth, 1)
        self.assertIn('consecuencia', stock.pf_chain_label)
        self.assertIn('Compras', stock.pf_chain_label)
        # El rank ordena la raíz antes que su consecuencia.
        self.assertLess(purchase.pf_chain_rank, stock.pf_chain_rank)

    # ------------------------------------------------------------------
    # FABRICADO: Fabricación (raíz) -> Inventario (consecuencia)
    # ------------------------------------------------------------------
    def _make_draft_mo(self, so, product, qty):
        """MO en BORRADOR vinculada al pedido (misma procura que S09336)."""
        group = self.env['procurement.group'].create({
            'name': '%s - Inmediata' % so.name,
            'sale_id': so.id,
            'partner_id': so.partner_id.id,
        })
        manu_type = self.warehouse.manu_type_id
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': product.uom_id.id,
            'origin': '%s - Inmediata' % so.name,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
            'source_procurement_group_id': group.id,
            'procurement_group_id': group.id,
        })

    def test_manufactured_production_root_stock_consequence(self):
        """BOM + MO en borrador (``to_launch``) + déficit de stock.

        Fabricar CREA las existencias, así que ``production`` precede a
        ``stock`` en la cadena causal. El Inventario NO es una falla
        independiente: es CONSECUENCIA de Fabricación (y por eso su botón
        "Solucionar" queda oculto, mientras la raíz sí lo expone).
        """
        component = self._product('CADENA FABRICADO COMPONENTE')
        self.env['stock.quant']._update_available_quantity(
            component, self.stock_location, 50.0)
        finished = self._product('CADENA FABRICADO CORTES', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': 1.0,
            })],
        })

        so, board = self._force_board(finished, 3.0)
        mo = self._make_draft_mo(so, finished, qty=3.0)
        self.assertEqual(mo.state, 'draft')
        board._sync_mrp_productions_from_sales(so)

        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == finished)[:1]
        self.assertTrue(line)
        # La raíz es FABRICACIÓN: la OF existe pero no se lanzó.
        self.assertEqual(line.root_cause_node, 'production')

        by_node = {f.node: f for f in line.failure_ids}
        self.assertIn('production', by_node)
        self.assertIn('stock', by_node)
        production = by_node['production']
        stock = by_node['stock']

        # Fabricación es la única raíz y no cuelga de nadie.
        self.assertEqual(production.pf_chain_role, 'root')
        self.assertFalse(production.pf_chain_parent_node)
        self.assertEqual(production.pf_chain_rank, 0)
        self.assertFalse(production.pf_chain_is_consequence)
        # Inventario es CONSECUENCIA de Fabricación (el stock lo crea la OF).
        self.assertEqual(stock.pf_chain_role, 'consequence')
        self.assertEqual(stock.pf_chain_parent_node, 'production')
        self.assertTrue(stock.pf_chain_is_consequence)
        self.assertEqual(stock.pf_chain_depth, 1)
        self.assertIn('consecuencia', stock.pf_chain_label)
        self.assertIn('Fabricación', stock.pf_chain_label)
        self.assertLess(production.pf_chain_rank, stock.pf_chain_rank)
        # La solución del MODELO sigue en la consecuencia (la VISTA la oculta).
        self.assertTrue(stock.pf_solution_available)
