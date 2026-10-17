# -*- coding: utf-8 -*-
"""FALTANTE REAL y PEDIDOS POR COMPRAR en el nodo COMPRAS (PrintFlow).

Custodia el contrato de la tarea de la Sección 3 del CONTEXT.md:

  * **CA-1** — el nodo Compras descuenta del déficit las OC SIN CONFIRMAR ligadas
    a pedidos con entrega pendiente: ``faltante_real = déficit − OC_a_confirmar``.
  * **CA-2** — el nodo explicita que hay OC sin confirmar (badge ``pending`` con
    ``pending_label == 'OC sin confirmar'``) junto a la magnitud.
  * **CA-3** — la resolución abre la Compra Rápida con cantidad = faltante real,
    CONGELADA (``pf_freeze_qty``): al "Traer pedidos" NO se recalcula.
  * **CA-4** — el botón "Traer pedidos" importa SOLO los pedidos que requieren
    compra: EXCLUYE el de OC en trámite (draft) e INCLUYE el de OC cancelada y el
    de OC ya recibida.
  * **CA-5** — el selector de "Agrupar pedidos" lee "número − cliente"
    (``display_name`` de ``sale.order`` en contexto) sin efecto colateral.
  * **CA-6** — paridad del pedido + compra rápida normal intactas; SOLO LECTURA:
    ``TransactionCase`` (rollback), sin ``cr.execute`` / ``cr.commit``.

Los datos de prueba se crean por el FLUJO NATIVO de Odoo (confirmar OC, validar
albarán): no se fuerza ningún estado. Nada se persiste (rollback).
"""

import json
import os

from odoo import fields
from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Archivos de PRODUCCIÓN de la tarea (solo lectura: sin SQL crudo ni commit).
_TOUCHED_FILES = (
    os.path.join('models', 'printflow_flow_pending.py'),
    os.path.join('models', 'printflow_flow_strategy_product.py'),
    os.path.join('models', 'printflow_flow_strategy_order.py'),
    os.path.join('models', 'printflow_quick_purchase_bridge.py'),
    os.path.join('models', 'printflow_sale_order_display.py'),
    os.path.join('wizard', 'printflow_product_flow.py'),
    os.path.join('wizard', 'printflow_order_diagnostic_failure.py'),
)


@tagged('post_install', '-at_install')
class TestFlowComprasPorComprar(TransactionCase):
    """CA-1..CA-6 del faltante real y los pedidos por comprar."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flow = cls.env['printflow.product.flow']
        cls.Canvas = cls.env['printflow.flow.canvas']
        cls.Pending = cls.env['printflow.flow.pending']
        cls.Quick = cls.env['mrp.quick.purchase.wizard']
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Por Comprar'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Por Comprar', 'supplier_rank': 1})
        # Nodos de pendientes deterministas (transitorio: rollback al terminar).
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_enabled', '1')
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_nodes',
            'purchase,receipt,production,delivery,sale')
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_limit', '0')

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests del flujo)
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _purchasable(self, name):
        product = self._product(
            name, purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _deficit_purchasable(self, name, qty):
        """Comprable con déficit físico (existencia negativa de ``qty``)."""
        product = self._purchasable(name)
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -abs(qty))
        return product

    def _sale_order(self, product, qty):
        """Pedido con ENTREGA PENDIENTE del producto (sin entregar).

        Se deja en estado de venta como el resto de la suite (sin generar
        albaranes): el motor de pendientes lee la LÍNEA de venta
        (``product_uom_qty − qty_delivered``).
        """
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return so

    def _purchase_order(self, product, qty=1.0, origin=None):
        """OC en BORRADOR (sin confirmar) del producto, opcionalmente ligada."""
        return self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'origin': origin or False,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': qty,
                'price_unit': 1.0,
                'name': product.name,
                'product_uom': product.uom_id.id,
                'date_planned': fields.Datetime.now(),
            })],
        })

    def _receive_po(self, po):
        """Recibe por completo la OC por el FLUJO NATIVO (valida el albarán)."""
        picking = po.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(
            picking, 'La confirmación de la OC debe generar el albarán.')
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.button_validate()
        if (isinstance(result, dict)
                and result.get('res_model') == 'stock.backorder.confirmation'):
            self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({}).process()
        return picking

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        return self.Flow.browse(action['res_id'])

    def _product_payload(self, product):
        return self.Canvas._pf_build_payload(self._wizard(product), 'product')

    def _order(self, so, product):
        """Wizard de diagnóstico del PEDIDO con la línea del producto enfocada."""
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        wizard.write({'focus_line_id': line.id})
        return wizard, line

    @staticmethod
    def _by_key(payload):
        return {node['key']: node for node in payload['nodes']}

    @staticmethod
    def _deficit_of(product):
        """Déficit físico real (MISMA fórmula del motor/wizard)."""
        return max(
            0.0,
            (product.outgoing_qty or 0.0)
            - (product.qty_available or 0.0)
            - (product.incoming_qty or 0.0))

    # ==================================================================
    # CA-1 — El nodo Compras DESCUENTA las OC sin confirmar del pedido
    # ==================================================================
    def test_ca1_purchase_shortfall_discounts_unconfirmed_cover(self):
        product = self._deficit_purchasable('POR COMPRAR CA1', 5.0)
        so = self._sale_order(product, 8.0)
        deficit = self._deficit_of(product)
        self.assertGreater(deficit, 0.0)

        before = self._by_key(self._product_payload(product))
        self.assertEqual(before['purchase']['shortfall_qty'], deficit)

        # OC en borrador ligada (por ``origin``) al pedido que espera entrega.
        oc_qty = 2.0
        self._purchase_order(product, qty=oc_qty, origin=so.name)

        after = self._by_key(self._product_payload(product))
        self.assertEqual(
            after['purchase']['shortfall_qty'],
            self._deficit_of(product) - oc_qty,
            'El faltante real debe descontar lo ya pedido sin confirmar.')
        self.assertLess(
            after['purchase']['shortfall_qty'],
            before['purchase']['shortfall_qty'])

    # ==================================================================
    # CA-2 — Señal EXPLÍCITA "OC sin confirmar" junto a la magnitud
    # ==================================================================
    def test_ca2_purchase_badge_unconfirmed_signal(self):
        product = self._deficit_purchasable('POR COMPRAR CA2', 6.0)
        so = self._sale_order(product, 6.0)
        self._purchase_order(product, qty=1.0, origin=so.name)
        self._purchase_order(product, qty=1.0)  # otra OC sin confirmar

        by_key = self._by_key(self._product_payload(product))
        self.assertEqual(
            by_key['purchase']['pending'], 2,
            'El badge cuenta los DOCUMENTOS de OC sin confirmar.')
        self.assertEqual(
            by_key['purchase']['pending_label'], 'OC sin confirmar')
        self.assertGreater(by_key['purchase']['shortfall_qty'], 0.0)

    # ==================================================================
    # CA-3 — La resolución abre la Compra Rápida CONGELADA con el faltante
    # ==================================================================
    def test_ca3_resolution_freezes_shortfall_qty(self):
        product = self._deficit_purchasable('POR COMPRAR CA3', 9.0)
        so = self._sale_order(product, 9.0)
        oc_qty = 4.0
        self._purchase_order(product, qty=oc_qty, origin=so.name)
        expected = self._deficit_of(product) - oc_qty
        self.assertGreater(expected, 0.0)
        wizard = self._wizard(product)

        action = wizard.action_run_pf_plan('order_supply_missing', 'solution')

        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        quick = self.Quick.browse(action['res_id'])
        self.assertTrue(
            quick.pf_freeze_qty,
            'La cantidad del faltante real debe viajar CONGELADA.')
        line = quick.purchase_line_ids[:1]
        self.assertEqual(line.product_id, product)
        self.assertEqual(line.product_qty, expected)

        # "Traer pedidos" NO debe recalcular la cantidad congelada.
        quick.action_pf_import_requiring_orders()
        self.assertEqual(quick.purchase_line_ids[:1].product_qty, expected)
        self.assertTrue(quick.pf_freeze_qty)

    # ==================================================================
    # CA-4 — "Traer pedidos" importa SOLO los que requieren compra
    # ==================================================================
    def test_ca4_import_only_requiring_orders(self):
        product = self._purchasable('POR COMPRAR CA4')
        so_draft = self._sale_order(product, 1.0)
        so_cancelled = self._sale_order(product, 1.0)
        so_received = self._sale_order(product, 1.0)
        # (a) OC en trámite (draft): ya hay compra que se confirmará -> EXCLUIR.
        self._purchase_order(product, qty=1.0, origin=so_draft.name)
        # (b) OC CANCELADA: su mercancía no entra -> requiere compra nueva.
        cancelled = self._purchase_order(
            product, qty=1.0, origin=so_cancelled.name)
        cancelled.button_cancel()
        # (c) OC YA RECIBIDA (sin recepción abierta) -> requiere compra nueva.
        received = self._purchase_order(
            product, qty=1.0, origin=so_received.name)
        received.button_confirm()
        self._receive_po(received)

        wizard = self._wizard(product)
        action = wizard.action_run_pf_plan('order_supply_missing', 'solution')
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        quick = self.Quick.browse(action['res_id'])
        quick.action_pf_import_requiring_orders()

        imported = quick.order_line_ids.mapped('sale_order_id')
        self.assertNotIn(
            so_draft, imported,
            'Un pedido con OC en trámite NO requiere compra.')
        self.assertIn(so_cancelled, imported)
        self.assertIn(so_received, imported)
        self.assertEqual(imported, so_cancelled | so_received)

    # ==================================================================
    # CA-5 — Selector: "número − cliente" SOLO en el contexto del selector
    # ==================================================================
    def test_ca5_selector_shows_partner_in_context(self):
        product = self._purchasable('POR COMPRAR CA5')
        so = self._sale_order(product, 1.0)
        partner_name = so.partner_id.name

        # El caché de un campo computed NO es sensible al contexto: se invalida
        # entre lecturas (mismo cuidado que exige el ``sale_show_partner_name``
        # nativo para el selector).
        so.invalidate_recordset()
        labeled = so.with_context(
            pf_purchase_partner_label=True).display_name
        self.assertEqual(labeled, '%s − %s' % (so.name, partner_name))

        so.invalidate_recordset()
        self.assertEqual(so.display_name, so.name)
        self.assertNotEqual(labeled, so.name)

    # ==================================================================
    # CA-6 — Paridad del pedido + compra normal intacta + SOLO LECTURA
    # ==================================================================
    def test_ca6_order_parity_and_normal_quick_purchase(self):
        product = self._purchasable('POR COMPRAR CA6')
        so = self._sale_order(product, 7.0)
        oc_qty = 2.0
        self._purchase_order(product, qty=oc_qty, origin=so.name)

        wizard, line = self._order(so, product)
        payload = json.loads(wizard.focus_timeline_json)
        by_key = self._by_key(payload)
        self.assertEqual(
            by_key['purchase']['shortfall_qty'],
            max(0.0, line.deficit_qty - oc_qty),
            'El diagrama del PEDIDO debe llevar la misma magnitud que el producto.')

        # La Compra Rápida NORMAL (sin la marca) NO está congelada.
        normal = self.Quick.create({
            'product_id': product.id,
            'purchase_line_ids': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'product_uom_id': product.uom_id.id,
                'material_received': False,
            })],
        })
        self.assertFalse(normal.pf_freeze_qty)

    def test_ca6_is_read_only(self):
        product = self._deficit_purchasable('POR COMPRAR CA6 RO', 3.0)
        so = self._sale_order(product, 3.0)
        self._purchase_order(product, qty=1.0, origin=so.name)
        qty_before = product.qty_available
        po_before = self.env['purchase.order'].search_count([])

        wizard = self._wizard(product)
        self._product_payload(product)
        action = wizard.action_run_pf_plan('order_supply_missing', 'solution')
        self.Quick.browse(action['res_id']).action_pf_import_requiring_orders()

        self.assertEqual(product.qty_available, qty_before)
        self.assertEqual(
            self.env['purchase.order'].search_count([]), po_before)

    def test_ca6_touched_files_have_no_raw_sql(self):
        module_path = get_module_path('printflow_gestion_inventario')
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)
