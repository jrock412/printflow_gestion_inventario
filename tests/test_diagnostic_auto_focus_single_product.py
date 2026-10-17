# -*- coding: utf-8 -*-
"""Auto-foco al diagrama cuando el pedido tiene UN SOLO producto pendiente.

Al abrir el diagnóstico DESDE EL TABLERO (``board.action_open_diagnostic_wizard``)
el tablero invoca ``_pf_auto_focus_single_product``: si hay EXACTAMENTE un
producto terminado con demanda pendiente (``required_qty > 0``) el wizard nace
enfocado (``focus_line_id``) y el formulario salta directo a la línea de tiempo.

Se cubren dos casos:
  * pedido con 1 producto -> auto-foco directo y payload parseable;
  * pedido "1 pendiente + 1 entregado" -> el entregado (demanda 0) NO cuenta,
    así que sigue siendo UNO y el auto-foco apunta al pendiente.

Son de SOLO LECTURA: ``TransactionCase`` hace rollback al terminar.
"""
import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticAutoFocusSingleProduct(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Auto Foco (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests de diagnóstico)
    # ------------------------------------------------------------------
    def _make_product(self, name, **extra):
        """Producto terminado gestionado por PrintFlow y sin ruta fija."""
        vals = {
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        product = self.env['product.product'].create(vals)
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

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
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        return so, board

    def _open_wizard(self, board):
        """Abre el diagnóstico por la MISMA ruta que la UI (vía tablero)."""
        action = board.action_open_diagnostic_wizard()
        self.assertEqual(
            action.get('res_model'), 'printflow.order.diagnostic.wizard')
        return self.env[
            'printflow.order.diagnostic.wizard'].browse(action['res_id'])

    def _deliver_partial(self, so, delivered_by_product):
        """Valida el albarán entregando las cantidades indicadas por producto."""
        picking = so.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking, 'La confirmación debe generar el albarán.')
        picking.action_assign()
        for move in picking.move_ids:
            qty = delivered_by_product.get(move.product_id, 0.0)
            move.quantity = qty
            move.picked = qty > 0.0
        result = picking.button_validate()
        if (isinstance(result, dict)
                and result.get('res_model') == 'stock.backorder.confirmation'):
            confirmation = self.env[
                'stock.backorder.confirmation'].with_context(
                    result.get('context') or {}).create({})
            confirmation.process()
        return picking

    # ------------------------------------------------------------------
    # Casos
    # ------------------------------------------------------------------
    def test_auto_focus_single_product_order(self):
        """Un solo producto con demanda -> foco directo y diagrama con nodos."""
        product = self._make_product('UNICO PRODUCTO AUTO FOCO (DIAG)')
        self._add_stock(product, 5.0)
        _so, board = self._force_order([(product, 2.0)])

        wizard = self._open_wizard(board)

        self.assertTrue(wizard.focus_line_id)
        self.assertEqual(wizard.focus_line_id.product_id, product)
        self.assertTrue(wizard.is_timeline)
        self.assertEqual(wizard.finished_product_count, 1)

        payload = json.loads(wizard.focus_timeline_json)
        self.assertTrue(payload.get('nodes'), 'El diagrama debe traer nodos.')

    def test_auto_focus_single_pending_ignores_delivered(self):
        """Caso '1 pendiente + 1 entregado': cuenta como UNO (auto-foco).

        El producto 100% entregado tiene ``required_qty == 0`` y NO compite por
        el auto-foco: el wizard enfoca directamente el producto pendiente.
        """
        pending = self._make_product('PENDIENTE AUTO FOCO (DIAG)')
        delivered = self._make_product('ENTREGADO AUTO FOCO (DIAG)')
        self._add_stock(pending, 5.0)
        self._add_stock(delivered, 5.0)

        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {
                    'product_id': pending.id,
                    'product_uom_qty': 1.0,
                    'product_uom': pending.uom_id.id,
                }),
                (0, 0, {
                    'product_id': delivered.id,
                    'product_uom_qty': 1.0,
                    'product_uom': delivered.uom_id.id,
                }),
            ],
        })
        so.action_confirm()
        self._deliver_partial(so, {delivered: 1.0})
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})
        board.invalidate_model()

        wizard = self._open_wizard(board)

        self.assertEqual(wizard.finished_product_count, 1)
        self.assertTrue(wizard.focus_line_id)
        self.assertEqual(wizard.focus_line_id.product_id, pending)
        self.assertTrue(wizard.is_timeline)
