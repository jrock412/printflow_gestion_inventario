# -*- coding: utf-8 -*-
"""Un componente que NO gestiona inventario (consumible) no produce déficit.

Caso real S14026: la OF de IMPRESION GLASSE consume PAPEL GLASE 300 GR, un
producto ``consu`` (sin quants). El tablero lo da por satisfecho
(``has_material_ready=True``, ``health_supply='ok'``), pero el diagnóstico lo
marcaba como "Falta comprar" / "Sin stock" porque medía existencia por
``stock.quant``. Este test fija la coherencia:

  * un producto que NO gestiona inventario (``detailed_type != 'product'``) se
    trata como satisfecho: sin déficit, sin contención, sin fallas de
    stock/compra y con "No aplica" en Compras;
  * un producto ALMACENABLE sin existencia SIGUE produciendo déficit (no
    regresión);
  * los helpers unitarios y la bandera ``is_stock_tracked`` del motor.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


class _FakeMove:
    """Movimiento de consumo mínimo para ``_pf_mo_waiting_material``.

    ``product`` opcional: si NO se pasa, el doble carece de ``product_id`` y debe
    conservar el comportamiento histórico del motor.
    """

    def __init__(self, state, quantity, demand, product=None):
        self.state = state
        self.quantity = quantity
        self.product_uom_qty = demand
        if product is not None:
            self.product_id = product


class _FakeMO:
    """MO mínima (solo ``move_raw_ids``) para el test unitario."""

    def __init__(self, moves):
        self.move_raw_ids = moves


@tagged('post_install', '-at_install')
class TestDiagnosticConsumableNotStock(TransactionCase):
    """Coherencia tablero <-> diagnóstico para productos sin inventario."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env['printflow.order.health.engine']
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Consumible No Stock'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, ptype='product', **extra):
        vals = {'name': name, 'type': ptype, 'x_is_printflow_managed': True}
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

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
        """MO en BORRADOR vinculada al pedido (misma procura que S14026)."""
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

    def _build_case(self, component_type):
        """Terminado (cubierto por stock) con OF que consume un componente.

        El terminado arranca con existencia suficiente para que el ÚNICO aporte
        posible al déficit sea el componente (aísla el caso).
        """
        component = self._product(
            'CONSUMIBLE COMP %s' % component_type, ptype=component_type,
            purchase_ok=True)
        finished = self._product('TERMINADO COMP', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._add_stock(finished, 1.0)
        # BoM ANTES de la MO: la OF SÍ genera sus movimientos de consumo.
        self._make_bom(finished, [(component, 5.0)])
        so, board = self._force_board(finished, 1.0)
        self._make_mo(so, finished, qty=1.0)
        board._sync_mrp_productions_from_sales(so)
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        return component, finished, wizard

    def _line(self, wizard, product):
        return wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]

    def _focus_payload(self, wizard, product):
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertTrue(line, 'La línea del terminado debe existir.')
        wizard.write({'focus_line_id': line.id})
        return line, json.loads(wizard.focus_timeline_json)

    # ------------------------------------------------------------------
    # (i) Consumible: satisfecho, sin déficit ni fallas stock/compra
    # ------------------------------------------------------------------
    def test_consumable_component_is_treated_as_satisfied(self):
        component, finished, wizard = self._build_case('consu')
        line = self._line(wizard, component)
        self.assertTrue(line, 'El componente consumible debe estar en la demanda.')
        self.assertEqual(line.stock_status, 'ok')
        self.assertEqual(line.purchase_status, 'na')
        self.assertFalse(line.deficit_qty > 0.0)
        self.assertFalse(line.contention_qty > 0.0)
        self.assertFalse(
            line.failure_ids.filtered(
                lambda f: f.node in ('stock', 'purchase')),
            'Un consumible no puede emitir fallas de stock ni de compra.')
        self.assertFalse(line.root_cause_node in ('stock', 'purchase'))

        # El déficit del PEDIDO queda en 0: el terminado está cubierto y el
        # consumible no aporta.
        self.assertFalse(wizard.deficit_total > 0.0)
        self.assertFalse(wizard.root_cause_node in ('stock', 'purchase'))

        # El terminado hereda el "no aplica" de Compras y el insumo disponible.
        finished_line = self._line(wizard, finished)
        self.assertEqual(finished_line.flow_purchase_status, 'na')
        self.assertEqual(finished_line.flow_supply_status, 'ok')
        self.assertFalse(finished_line.root_cause_node in ('stock', 'purchase'))

        # Canvas: el nodo COMPRAS queda "No aplica" y NO en rojo.
        _focus, payload = self._focus_payload(wizard, finished)
        by_key = {n['key']: n for n in payload['nodes']}
        self.assertIn('purchase', by_key)
        self.assertEqual(by_key['purchase']['status'], 'na')
        self.assertNotEqual(by_key['purchase']['tone'], 'danger')

    # ------------------------------------------------------------------
    # (ii) Almacenable sin stock: SIGUE en déficit (no regresión)
    # ------------------------------------------------------------------
    def test_storable_component_still_deficits(self):
        component, finished, wizard = self._build_case('product')
        line = self._line(wizard, component)
        self.assertTrue(line, 'El componente almacenable debe estar en la demanda.')
        self.assertEqual(line.stock_status, 'deficit')
        self.assertEqual(line.purchase_status, 'missing')
        self.assertTrue(line.deficit_qty > 0.0)
        self.assertTrue(
            line.failure_ids.filtered(lambda f: f.node == 'stock'))
        self.assertTrue(
            line.failure_ids.filtered(lambda f: f.node == 'purchase'))
        self.assertIn(line.root_cause_node, ('stock', 'purchase'))

    # ------------------------------------------------------------------
    # (iii) Unitarios: helpers y banderas
    # ------------------------------------------------------------------
    def test_is_stock_tracked_and_skips_inventory(self):
        engine = self.Engine
        consu = self._product('UNIT CONSU', ptype='consu')
        consu_on_order = self._product('UNIT CONSU ON ORDER', ptype='consu')
        consu_on_order.product_tmpl_id.pf_purchase_on_order = True
        storable = self._product('UNIT STORABLE', ptype='product')

        # Consumible sin bandera: NO gestiona inventario y se salta.
        self.assertFalse(engine._pf_is_stock_tracked(consu))
        self.assertTrue(engine._pf_skips_inventory(consu))
        # Consumible con compra por pedido: conserva su lógica (NO se salta).
        self.assertFalse(engine._pf_is_stock_tracked(consu_on_order))
        self.assertFalse(engine._pf_skips_inventory(consu_on_order))
        # Almacenable: gestiona inventario y NUNCA se salta.
        self.assertTrue(engine._pf_is_stock_tracked(storable))
        self.assertFalse(engine._pf_skips_inventory(storable))
        # Producto vacío: no se salta (guarda tolerante).
        self.assertFalse(engine._pf_skips_inventory(False))

    def test_product_rules_with_flag(self):
        engine = self.Engine
        self.assertEqual(
            engine._pf_product_stock(
                {'is_stock_tracked': False, 'deficit_qty': 5.0}),
            'ok')
        self.assertEqual(
            engine._pf_product_supply(
                {'is_stock_tracked': False, 'purchase_ok': True,
                 'deficit_qty': 5.0}),
            'na')

    def test_mo_waiting_material_ignores_consumable(self):
        engine = self.Engine
        consu = self._product('UNIT MO CONSU', ptype='consu')
        # Movimiento de un consumible con material "faltante": NO es espera real.
        mo_consumable = _FakeMO([_FakeMove('confirmed', 0.0, 5.0, consu)])
        self.assertFalse(engine._pf_mo_waiting_material([mo_consumable]))
        # Doble SIN ``product_id``: conserva el comportamiento histórico.
        mo_legacy = _FakeMO([_FakeMove('confirmed', 0.0, 5.0)])
        self.assertTrue(engine._pf_mo_waiting_material([mo_legacy]))
