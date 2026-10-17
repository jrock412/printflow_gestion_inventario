# -*- coding: utf-8 -*-
"""Aviso informativo: órdenes de entrega pendientes del producto (PrintFlow).

El aviso NO es una falla: cuenta los albaranes de entrega (``outgoing``, no
``done``/``cancel``) de OTROS orígenes que contienen el producto y los expone
en la línea del wizard. Debe funcionar incluso cuando el motor de salud NO
marca ninguna falla de entrega (caso "ya saneado").

Estos tests son de SOLO LECTURA sobre los datos reales: crean sus propios
registros y ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPendingDeliveryOrders(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Pending Entrega (DIAG)',
        })
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Cliente Pending Entrega Otro (DIAG)',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        """Producto almacenable PrintFlow SIN ruta (genera albarán al confirmar)."""
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _confirm_order(self, partner, product, qty=1.0):
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _deliver(self, so):
        """Valida por completo el albarán del pedido (lo deja ``done``)."""
        picking = so.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))[:1]
        self.assertTrue(picking, 'La confirmación debe generar el albarán.')
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.button_validate()
        if (isinstance(result, dict)
                and result.get('res_model') == 'stock.backorder.confirmation'):
            confirmation = self.env['stock.backorder.confirmation'].with_context(
                result.get('context') or {}).create({})
            confirmation.process()
        return picking

    # ------------------------------------------------------------------
    # Conteo del aviso
    # ------------------------------------------------------------------
    def test_pending_delivery_count_excludes_own_and_has_no_delivery_failure(self):
        product = self._make_product('PENDIENTES ENTREGA (DIAG)')
        self._add_stock(product, 1.0)

        # Pedido PROPIO, ya entregado: su albarán NO debe contarse.
        own_so = self._confirm_order(self.customer, product, 1.0)
        own_picking = self._deliver(own_so)
        self.assertEqual(own_picking.state, 'done')

        # N pedidos AJENOS con albarán de entrega pendiente del mismo producto.
        other_pickings = self.env['stock.picking']
        for _i in range(3):
            other_so = self._confirm_order(self.other_customer, product, 1.0)
            other_pickings |= other_so.picking_ids
        self.assertEqual(len(other_pickings), 3)
        self.assertTrue(all(
            p.state not in ('done', 'cancel') for p in other_pickings))
        self.assertTrue(all(
            p.picking_type_id.code == 'outgoing' for p in other_pickings))

        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line, 'El wizard debe tener la línea del producto.')

        # El aviso cuenta SOLO los ajenos: 3 (no incluye el propio, done).
        self.assertEqual(
            line.pending_delivery_order_count, len(other_pickings),
            'El aviso debe contar solo los albaranes ajenos pendientes.')
        self.assertTrue(line.has_pending_delivery_orders)

        # El aviso es informativo: NO materializa falla del nodo 'delivery'.
        self.assertFalse(
            line.failure_ids.filtered(lambda f: f.node == 'delivery'),
            'El aviso informativo NO debe crear fallas de entrega.')
        self.assertFalse(
            line.flow_failure_ids.filtered(lambda f: f.node == 'delivery'),
            'El aviso NO debe aparecer en el roll-up de fallas.')

    # ------------------------------------------------------------------
    # Acción de navegación
    # ------------------------------------------------------------------
    def test_open_pending_delivery_orders_excludes_own(self):
        product = self._make_product('PENDIENTES ACCION (DIAG)')
        own_so = self._confirm_order(self.customer, product, 1.0)
        other_so = self._confirm_order(self.other_customer, product, 1.0)

        board = self.env['printflow.order.board'].create(
            {'sale_order_id': own_so.id})
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        line = wizard.product_line_ids.filtered(
            lambda l: l.product_id == product)
        self.assertTrue(line)
        wizard.write({'focus_line_id': line.id})

        action = wizard.action_open_pending_delivery_orders()

        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['view_mode'], 'tree,form')
        self.assertEqual(action['target'], 'current')
        self.assertEqual(list(action['domain'][0][:2]), ['id', 'in'])
        self.assertIn(other_so.picking_ids.id, action['domain'][0][2])
        self.assertNotIn(
            own_so.picking_ids.id, action['domain'][0][2],
            'La bandeja del aviso NO debe incluir los albaranes del propio pedido.')
