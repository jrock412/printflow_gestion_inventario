# -*- coding: utf-8 -*-
"""Raíz en ALMACÉN INSUMOS cuando la OF no tiene insumos (regresión S09336).

El cliente define la línea de tiempo SIEMPRE hacia adelante:

    Compras -> Recepción -> Almacén insumos -> Fabricación -> Almacén terminado
    -> Entrega

En S09336 (CORTES (LILA)) la Orden de Fabricación existe pero NO tiene insumos
cargados (``move_raw_ids`` vacío y BoM sin líneas). La lectura correcta es:

  * ALMACÉN INSUMOS  🔴 RAÍZ        (la OF no tiene insumos)
  * FABRICACIÓN      🔴 consecuencia
  * ALMACÉN TERMINADO 🔴 consecuencia

Estos tests custodian, además:
  * las flechas "Causa → Consecuencia" van SIEMPRE hacia adelante (nunca de
    fabricación hacia atrás a insumos);
  * el badge/rol/panel se atribuye POR HITO: un déficit del terminado NO se le
    pega a insumos;
  * un producto con insumos correctos NO dispara la causa ni pinta insumos.

Son de SOLO LECTURA: crean sus propios registros y ``TransactionCase`` hace
rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_CHAIN_ORDER


@tagged('post_install', '-at_install')
class TestDiagnosticSupplyRoot(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Supply Root'})
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

    def _focus_payload(self, board, product):
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)[:1]
        self.assertTrue(line, 'La línea del terminado debe existir.')
        wizard.write({'focus_line_id': line.id})
        return line, json.loads(wizard.focus_timeline_json)

    @staticmethod
    def _error_pairs(payload):
        return {
            (e['from'], e['to'])
            for e in payload['edges'] if e['type'] == 'error'}

    # ------------------------------------------------------------------
    # (1) OF sin insumos -> RAÍZ en ALMACÉN INSUMOS y consecuencias adelante
    # ------------------------------------------------------------------
    def test_mo_without_materials_roots_at_supply(self):
        component = self._product('SUPPLY COMPONENTE')
        self._add_stock(component, 100.0)
        finished = self._product('SUPPLY CORTES LILA', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]

        # La MO nace SIN BoM (queda sin ``move_raw_ids``) y la BoM se define
        # DESPUÉS: como en S09336, la OF no tiene insumos cargados.
        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        self.assertEqual(mo.state, 'draft')
        self.assertFalse(mo.move_raw_ids)
        self._make_bom(finished, [(component, 1.0)])
        board._sync_mrp_productions_from_sales(so)
        self.assertIn(mo, board.mrp_production_ids)

        line, payload = self._focus_payload(board, finished)
        by_key = {n['key']: n for n in payload['nodes']}

        # La raíz es el ALMACÉN INSUMOS (la OF no tiene insumos).
        self.assertEqual(line.root_cause_node, 'supply')
        self.assertEqual(by_key['stock_supply']['role'], 'root')
        self.assertEqual(by_key['stock_supply']['tone'], 'danger')
        self.assertGreaterEqual(by_key['stock_supply']['issues'], 1)
        supply_detail = ' '.join(
            row['detail'] for row in by_key['stock_supply']['panel'])
        self.assertIn('insumos', supply_detail.lower())

        # Fabricación y Almacén terminado son CONSECUENCIAS hacia adelante.
        self.assertEqual(by_key['production']['role'], 'consequence')
        self.assertEqual(by_key['production']['tone'], 'danger')
        self.assertEqual(by_key['production']['parent'], 'stock_supply')
        self.assertEqual(by_key['stock_finished']['role'], 'consequence')
        self.assertEqual(
            by_key['stock_finished']['parent'], 'production')

        # Las flechas de error van SIEMPRE hacia adelante (nunca hacia atrás).
        errors = self._error_pairs(payload)
        self.assertIn(('stock_supply', 'production'), errors)
        self.assertIn(('stock_supply', 'stock_finished'), errors)
        order = {key: index for index, key in enumerate(payload['axis'])}
        for src, dst in errors:
            self.assertLess(
                order[src], order[dst],
                'Flecha hacia atrás prohibida: %s -> %s' % (src, dst))
        # El widget conserva la espina causal de 5 nodos.
        self.assertEqual(payload['order'], list(PF_CHAIN_ORDER))
        self.assertEqual(payload['global']['root'], 'supply')

        # ── Veredicto de INSUMOS desacoplado (fuente única del motor) ────
        # La línea terminada guarda la bandera y el veredicto del hito; el foco
        # del wizard lo espeja vía el related ``focus_supply_status``.
        self.assertTrue(line.has_mo_without_materials)
        self.assertEqual(line.flow_supply_status, 'no_supply')
        self.assertEqual(line.wizard_id.focus_supply_status, 'no_supply')

        # El nodo INSUMOS ofrece "Ir a la Orden de Fabricación": reutiliza el
        # dispatcher público ``action_run_pf_node`` y resuelve a la OF real.
        fabricate = next(
            (a for a in by_key['stock_supply']['actions']
             if a['key'] == 'fabricate'), None)
        self.assertIsNotNone(
            fabricate, 'El nodo insumos debe ofrecer ir a la OF.')
        self.assertEqual(fabricate['method'], 'action_run_pf_node')
        failure = self.env[
            'printflow.order.diagnostic.failure'].browse(fabricate['failure_id'])
        fabricate_action = failure.action_run_pf_node('fabricate')
        self.assertEqual(fabricate_action['res_model'], 'mrp.production')
        self.assertEqual(fabricate_action['res_id'], mo.id)

    # ------------------------------------------------------------------
    # (2) El déficit del TERMINADO NO se le pega a INSUMOS
    # ------------------------------------------------------------------
    def test_finished_deficit_does_not_badge_supply(self):
        component = self._product('SUPPLY BADGE COMPONENTE')
        self._add_stock(component, 100.0)
        finished = self._product('SUPPLY BADGE TERMINADO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        # BoM ANTES de la MO: la OF sí tiene insumos (no dispara la causa).
        self._make_bom(finished, [(component, 1.0)])

        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        self.assertTrue(mo.move_raw_ids, 'La OF debe tener insumos cargados.')
        board._sync_mrp_productions_from_sales(so)

        line, payload = self._focus_payload(board, finished)
        by_key = {n['key']: n for n in payload['nodes']}

        # No hay causa de insumos: INSUMOS queda sano.
        self.assertFalse(
            line.failure_ids.filtered(lambda f: f.node == 'supply'),
            'Un terminado con déficit no debe crear falla de insumos.')
        self.assertEqual(by_key['stock_supply']['issues'], 0)
        self.assertEqual(by_key['stock_supply']['role'], 'none')
        self.assertNotEqual(by_key['stock_supply']['tone'], 'danger')

        # El problema del TERMINADO está en SU propio hito.
        self.assertGreaterEqual(by_key['stock_finished']['issues'], 1)
        finished_detail = ' '.join(
            row['detail'] for row in by_key['stock_finished']['panel'])
        self.assertIn('stock', finished_detail.lower())

    # ------------------------------------------------------------------
    # (3) FONDO NEGRO: insumos correctos -> no dispara la causa ni pinta insumos
    # ------------------------------------------------------------------
    def test_proper_materials_not_flagged_as_no_supply(self):
        component = self._product('SUPPLY OK COMPONENTE')
        self._add_stock(component, 100.0)
        finished = self._product('SUPPLY FONDO NEGRO', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._make_bom(finished, [(component, 1.0)])

        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        board._sync_mrp_productions_from_sales(so)
        self.assertTrue(mo.move_raw_ids)

        line, payload = self._focus_payload(board, finished)
        by_key = {n['key']: n for n in payload['nodes']}

        self.assertNotEqual(line.production_status, 'no_supply')
        self.assertFalse(
            line.failure_ids.filtered(lambda f: f.node == 'supply'))
        # El almacén de insumos tiene material: nunca rojo.
        self.assertNotEqual(by_key['stock_supply']['tone'], 'danger')

    # ------------------------------------------------------------------
    # (4) AUDITORÍA de selections: ningún campo stored que pueda recibir
    #     ``no_supply``/``supply`` debe quedar sin la opción declarada.
    # ------------------------------------------------------------------
    def test_all_relevant_selections_declare_new_options(self):
        cases = [
            ('printflow.order.diagnostic.wizard', 'production_status', 'no_supply'),
            ('printflow.order.diagnostic.wizard', 'root_cause_node', 'supply'),
            ('printflow.order.diagnostic.wizard', 'focus_production_status', 'no_supply'),
            ('printflow.order.diagnostic.wizard', 'focus_supply_status', 'no_supply'),
            ('printflow.order.diagnostic.wizard', 'focus_root_cause_node', 'supply'),
            ('printflow.order.diagnostic.wizard.line', 'production_status', 'no_supply'),
            ('printflow.order.diagnostic.wizard.line', 'flow_production_status', 'no_supply'),
            ('printflow.order.diagnostic.wizard.line', 'flow_supply_status', 'no_supply'),
            ('printflow.order.diagnostic.wizard.line', 'root_cause_node', 'supply'),
            ('printflow.order.diagnostic.failure', 'node', 'supply'),
            ('printflow.order.diagnostic.failure', 'pf_chain_parent_node', 'supply'),
        ]
        for model_name, field_name, option in cases:
            model = self.env[model_name]
            info = model.fields_get([field_name]).get(field_name) or {}
            selection = dict(info.get('selection') or [])
            self.assertIn(
                option, selection,
                '%s.%s no declara la opción %r' % (
                    model_name, field_name, option))

