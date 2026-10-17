# -*- coding: utf-8 -*-
"""Validación NATIVA de entregas desde la lista de Pendientes (PrintFlow · F4b).

Custodia:
  * una selección de filas de ENTREGA valida los albaranes y devuelve la ventana
    única ``printflow.delivery.bulk.result``;
  * seleccionar filas NO entregables SOLO avisa (no tumba el lote);
  * sin selección, avisa;
  * la validación corre SIN ``sudo`` de escritura (permisos del usuario).

Son de SOLO LECTURA salvo la validación (que ``TransactionCase`` revierte) y
hacen rollback al terminar.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_BULK_XMLID = (
    'x_product_dimensional_pricing.'
    'action_server_printflow_validate_deliveries')


@tagged('post_install', '-at_install')
class TestPendingNativeValidate(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Validación Nativa'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Validación Nativa', 'supplier_rank': 1})
        cls.Pending = cls.env['printflow.node.pending.line']
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_enabled', '1')
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_nodes',
            'delivery,purchase')
        ICP.set_param(
            'x_product_dimensional_pricing.pf_node_pending_limit', '0')

    def _delivery_product(self, name):
        product = self._pf_product(name)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        self._pf_add_stock(product, 10.0)
        return product

    def _confirm_delivery(self, product, qty=2.0):
        so = self._pf_confirm_order(product, qty)
        return so.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]

    def _draft_purchase(self, product):
        return self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'product_uom': product.uom_id.id,
                'name': product.name,
            })],
        })

    # ------------------------------------------------------------------
    # 1) Selección de entregas -> valida + ventana de resultado
    # ------------------------------------------------------------------
    def test_validate_selected_delivery(self):
        product = self._delivery_product('NATIVA ENTREGA')
        picking = self._confirm_delivery(product)
        lines = self.Pending._pf_populate(
            product_ids=[product.id], node_keys=['delivery'])
        self.assertTrue(lines)
        self.assertTrue(all(line.bulk_action_xmlid for line in lines))

        result = self.Pending.with_context(
            active_ids=lines.ids).action_pf_validate_selected()
        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'printflow.delivery.bulk.result')
        picking.invalidate_recordset(['state'])
        self.assertEqual(picking.state, 'done')

    # ------------------------------------------------------------------
    # 2) Sin selección -> aviso
    # ------------------------------------------------------------------
    def test_validate_without_selection_notifies(self):
        result = self.Pending.action_pf_validate_selected()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertEqual(result['params']['type'], 'warning')

    # ------------------------------------------------------------------
    # 3) Solo filas no entregables -> aviso (no falla)
    # ------------------------------------------------------------------
    def test_validate_only_non_deliverable_notifies(self):
        product = self._delivery_product('NATIVA NO ENTREGABLE')
        self._draft_purchase(product)
        lines = self.Pending._pf_populate(
            product_ids=[product.id], node_keys=['purchase'])
        self.assertTrue(lines)
        result = self.Pending.with_context(
            active_ids=lines.ids).action_pf_validate_selected()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')

    # ------------------------------------------------------------------
    # 4) Selección mixta -> valida entregas + avisa de las omitidas
    # ------------------------------------------------------------------
    def test_validate_mixed_selection(self):
        product = self._delivery_product('NATIVA MIXTA')
        picking = self._confirm_delivery(product)
        self._draft_purchase(product)
        lines = self.Pending._pf_populate(
            product_ids=[product.id], node_keys=['delivery', 'purchase'])
        delivery_lines = lines.filtered(lambda l: l.node_key == 'delivery')
        purchase_lines = lines.filtered(lambda l: l.node_key == 'purchase')
        self.assertTrue(delivery_lines)
        self.assertTrue(purchase_lines)

        result = self.Pending.with_context(
            active_ids=lines.ids).action_pf_validate_selected()
        # Aviso + ventana única del resultado (encadenada).
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertIn('next', result['params'])
        picking.invalidate_recordset(['state'])
        self.assertEqual(picking.state, 'done')

    def test_bulk_xmlid_is_the_existing_motor(self):
        product = self._delivery_product('NATIVA MOTOR')
        self._confirm_delivery(product)
        lines = self.Pending._pf_populate(
            product_ids=[product.id], node_keys=['delivery'])
        self.assertTrue(lines)
        self.assertEqual(lines[0].bulk_action_xmlid, _BULK_XMLID)
