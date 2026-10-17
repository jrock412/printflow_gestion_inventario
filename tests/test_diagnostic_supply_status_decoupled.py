# -*- coding: utf-8 -*-
"""El ALMACÉN INSUMOS se decide solo (desacoplado de FABRICACIÓN).

Regresión S09336 (CORTES (LILA)): la Orden de Fabricación existe pero NO tiene
insumos cargados (``move_raw_ids`` vacío y BoM sin líneas). El hito ALMACÉN
INSUMOS debe quedar ROJO y RAÍZ, y Fabricación / Almacén terminado como
CONSECUENCIA. Antes el hito de insumos se derivaba del estado de Fabricación
(``focus_production_status == 'no_supply'``), lo que acoplaba una consecuencia a
su causa.

La fuente única es ``printflow.order.health.engine._pf_supply_node_status``:
  1. OF sin insumos -> ``'no_supply'``;
  2. si no, el peor stock de los componentes.

Estos tests custodian:
  * la bandera ``has_mo_without_materials`` del terminado;
  * el veredicto ``flow_supply_status`` (línea) y ``focus_supply_status`` (foco);
  * el DESACOPLE: forzar Fabricación a ``to_launch`` NO cambia el veredicto de
    insumos (que sigue ``no_supply`` / danger);
  * la contra-prueba: con BOM e insumos cargados, insumos NO es rojo.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticSupplyStatusDecoupled(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env['printflow.order.health.engine']
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Supply Decoupled'})
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

    def _focus_wizard(self, board, product):
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertTrue(line, 'La línea del terminado debe existir.')
        wizard.write({'focus_line_id': line.id})
        return wizard, line

    def _payload(self, wizard):
        return json.loads(wizard.focus_timeline_json)

    # ------------------------------------------------------------------
    # 1) Unidad: la función pura manda sobre el stock cuando faltan insumos
    # ------------------------------------------------------------------
    def test_unit_supply_node_status_prefers_no_supply(self):
        self.assertEqual(
            self.Engine._pf_supply_node_status('deficit', True), 'no_supply')
        self.assertEqual(
            self.Engine._pf_supply_node_status('over', False), 'over')
        self.assertEqual(
            self.Engine._pf_supply_node_status(None, False), 'ok')

    # ------------------------------------------------------------------
    # 2) S09336 sintético: insumos rojo/raíz y desacoplado de Fabricación
    # ------------------------------------------------------------------
    def test_supply_status_is_root_and_decoupled(self):
        component = self._product('DECOUPLED COMPONENTE')
        self._add_stock(component, 100.0)
        finished = self._product('DECOUPLED CORTES LILA', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]

        # La MO nace SIN BoM (``move_raw_ids`` vacío) y la BoM se define DESPUÉS:
        # como en S09336, la OF no tiene insumos cargados.
        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        self.assertEqual(mo.state, 'draft')
        self.assertFalse(mo.move_raw_ids)
        self._make_bom(finished, [(component, 1.0)])
        board._sync_mrp_productions_from_sales(so)

        wizard, line = self._focus_wizard(board, finished)
        self.assertTrue(line.has_mo_without_materials)
        self.assertEqual(line.flow_supply_status, 'no_supply')
        self.assertEqual(wizard.focus_supply_status, 'no_supply')

        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        self.assertEqual(by_key['stock_supply']['status'], 'no_supply')
        self.assertEqual(by_key['stock_supply']['tone'], 'danger')
        self.assertEqual(by_key['stock_supply']['role'], 'root')
        # Fabricación y terminado son CONSECUENCIA del almacén de insumos.
        self.assertEqual(by_key['production']['role'], 'consequence')
        self.assertEqual(by_key['production']['parent'], 'stock_supply')
        self.assertEqual(by_key['stock_finished']['role'], 'consequence')
        self.assertEqual(by_key['stock_finished']['parent'], 'production')

        # ── DESACOPLE: forzar Fabricación a 'to_launch' NO mueve insumos ──
        # El hito de insumos lee su propio veredicto (``flow_supply_status``), no
        # el de Fabricación. Al invalidar, el canvas sigue con insumos rojo.
        line.write({'flow_production_status': 'to_launch'})
        wizard.invalidate_recordset([
            'focus_timeline_json', 'focus_production_status',
            'focus_supply_status',
        ])
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        self.assertEqual(by_key['production']['status'], 'to_launch')
        self.assertEqual(by_key['stock_supply']['status'], 'no_supply')
        self.assertEqual(by_key['stock_supply']['tone'], 'danger')
        self.assertEqual(by_key['stock_supply']['role'], 'root')

    # ------------------------------------------------------------------
    # 3) Contra-prueba: con BOM e insumos cargados, insumos NO es rojo
    # ------------------------------------------------------------------
    def test_supply_is_not_danger_when_materials_are_loaded(self):
        component = self._product('DECOUPLED OK COMPONENTE')
        self._add_stock(component, 100.0)
        finished = self._product('DECOUPLED OK CORTES', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        # BoM ANTES de la MO: la OF SÍ genera sus movimientos de consumo.
        self._make_bom(finished, [(component, 1.0)])

        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        self.assertTrue(mo.move_raw_ids, 'La OF debe tener insumos cargados.')
        board._sync_mrp_productions_from_sales(so)

        wizard, line = self._focus_wizard(board, finished)
        self.assertFalse(line.has_mo_without_materials)
        self.assertNotEqual(line.flow_supply_status, 'no_supply')
        by_key = {n['key']: n for n in self._payload(wizard)['nodes']}
        self.assertNotEqual(by_key['stock_supply']['tone'], 'danger')
