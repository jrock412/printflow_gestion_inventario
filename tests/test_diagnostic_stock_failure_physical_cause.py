# -*- coding: utf-8 -*-
"""Fila de falla de STOCK del diagnóstico de pedido: causa por REMEDIO FÍSICO.

Regresión del bug S09336/S09338: el nodo Stock (déficit físico) mostraba
``order_shortfall`` y su botón "Solucionar" navegaba a una Orden de Compra aun
cuando el producto era FABRICADO (su MO ya existía). Ahora la fila de stock se
clasifica con ``printflow.stock.remedy`` (fuente única) y su solución abre el
destino correcto:

  1. Fabricable con BOM y componentes disponibles -> ``manufacture`` (abre la MO).
  2. Comprable con proveedor -> ``buy_product`` (compra rápida).
  3. Sin ruta ni proveedor -> ``adjust_inventory`` (ajuste de inventario).
  4. Fabricable con insumo faltante -> ``manufacture_components``.
  5. Anti-duplicación: en el caso físico puro el botón primario se OCULTA
     (el plan ya ofrece lo mismo) y en el doble remedio se conserva la
     "Alternativa".
"""

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticStockFailurePhysicalCause(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Causa Física Stock'})
        cls.supplier = cls.env['res.partner'].create(
            {'name': 'Proveedor Causa Física Stock', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        # Segunda ubicación interna: permite la reserva colgada (quant con libre
        # negativo compensado) que dispara la anomalía (doble remedio).
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'CAUSA FISICA EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })

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

    def _add_stock(self, product, qty, reserved=0.0, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty,
            reserved_quantity=reserved)

    def _make_bom(self, product, components):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [
                (0, 0, {'product_id': comp.id, 'product_qty': qty})
                for comp, qty in components
            ],
        })

    def _force_board(self, product, qty):
        """Pedido forzado a 'sale' (sin procura) + su tarjeta."""
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

    def _make_mo(self, so, product, qty=1.0):
        """MO (draft) vinculada al pedido, como la crea la procura real."""
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

    def _stock_failure(self, wizard, product):
        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertTrue(line, 'La línea de producto debe existir.')
        failure = line.failure_ids.filtered(lambda f: f.node == 'stock')[:1]
        self.assertTrue(failure, 'Debe existir la fila de falla de stock.')
        return failure

    # ------------------------------------------------------------------
    # 1) Fabricable con BOM y componentes disponibles -> manufacture (MO)
    # ------------------------------------------------------------------
    def test_manufacture_deficit_routes_to_existing_mo(self):
        component = self._product('CAUSA COMPONENTE OK')
        self._add_stock(component, 50.0)
        finished = self._product('CAUSA FABRICADO CON MO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._make_bom(finished, [(component, 1.0)])

        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        # La MO nace en un procurement group del pedido: se refleja en el puente.
        board._sync_mrp_productions_from_sales(so)
        self.assertIn(mo, board.mrp_production_ids)

        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        failure = self._stock_failure(wizard, finished)

        self.assertEqual(failure.pf_cause, 'manufacture')
        action = failure.action_open_solution()
        self.assertEqual(action['res_model'], 'mrp.production')
        self.assertEqual(action.get('res_id'), mo.id)

    # ------------------------------------------------------------------
    # 2) Comprable con proveedor -> buy_product (compra rápida)
    # ------------------------------------------------------------------
    def test_purchasable_deficit_routes_to_buy_product(self):
        product = self._product(
            'CAUSA COMPRABLE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]

        _so, board = self._force_board(product, 4.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        failure = self._stock_failure(wizard, product)

        self.assertEqual(failure.pf_cause, 'buy_product')
        action = failure.action_open_solution()
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')

    # ------------------------------------------------------------------
    # 3) Sin ruta ni proveedor -> adjust_inventory (ajuste de inventario)
    # ------------------------------------------------------------------
    def test_no_route_deficit_routes_to_adjust(self):
        product = self._product('CAUSA SIN RUTA', purchase_ok=False)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]

        _so, board = self._force_board(product, 5.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        failure = self._stock_failure(wizard, product)

        self.assertEqual(failure.pf_cause, 'adjust_inventory')
        action = failure.action_open_solution()
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertTrue(action['context']['inventory_mode'])

    # ------------------------------------------------------------------
    # 4) Fabricable con insumo faltante -> manufacture_components
    # ------------------------------------------------------------------
    def test_manufacture_missing_component_routes_to_components(self):
        component = self._product('CAUSA INSUMO FALTANTE')  # sin stock
        finished = self._product('CAUSA FABRICADO SIN INSUMO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._make_bom(finished, [(component, 2.0)])

        _so, board = self._force_board(finished, 3.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        failure = self._stock_failure(wizard, finished)

        self.assertEqual(failure.pf_cause, 'manufacture_components')

    # ------------------------------------------------------------------
    # 5) Anti-duplicación: primario oculto; alternativa conservada
    # ------------------------------------------------------------------
    def test_anti_duplication_primary_hidden_second_kept(self):
        # Caso físico PURO: comprar (la solución del plan ya ofrece comprar, así
        # que el botón primario "Recomendación" se oculta).
        product = self._product(
            'CAUSA FISICA PURA', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        _so, board = self._force_board(product, 4.0)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        failure = self._stock_failure(wizard, product)
        self.assertFalse(failure.pf_remedy_available)
        self.assertFalse(failure.pf_second_remedy_available)

        # Caso DOBLE (déficit + reserva colgada): se conserva la ALTERNATIVA de
        # saneamiento aunque el primario siga oculto.
        product2 = self._product(
            'CAUSA DOBLE REMEDIO', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product2.product_tmpl_id.route_ids = [(5, 0, 0)]
        # Quant con libre negativo compensado + agregado insuficiente.
        self._add_stock(product2, 1.0, reserved=4.0,
                        location=self.extra_location)
        self._add_stock(product2, 10.0)
        _so2, board2 = self._force_board(product2, 20.0)
        wizard2 = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board2.id})
        failure2 = self._stock_failure(wizard2, product2)
        self.assertFalse(failure2.pf_remedy_available)
        self.assertTrue(failure2.pf_second_remedy_available)
        self.assertEqual(
            failure2.pf_second_remedy_target, 'fix_over_reservation')
        # La cabecera eleva la alternativa aunque el primario esté oculto.
        self.assertTrue(wizard2.remedy_secondary_available)
