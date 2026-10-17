# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticIncomingMap(TransactionCase):
    """C4: cobertura de ``_get_incoming_map`` del Wizard de Diagnóstico.

    Verifica que lo "en camino" salga de la diferencia
    ``product_qty - qty_received`` de cada línea de compra del pedido, que
    agrupe compras/líneas distintas (compras agrupadas) y que respete la UdM
    de la línea. Se usan productos ``consu`` porque su ``qty_received_method``
    es 'manual' y permite fijar la cantidad recibida sin generar albaranes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Incoming Diagnostico',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Incoming Diagnostico',
            'supplier_rank': 1,
        })
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        # type='consu' → qty_received_method='manual' (se puede fijar qty_received).
        cls.product_a = cls.env['product.product'].create({
            'name': 'INSUMO INCOMING A (DIAG)',
            'type': 'consu',
            'purchase_ok': True,
            'uom_id': cls.uom_unit.id,
        })
        cls.product_b = cls.env['product.product'].create({
            'name': 'INSUMO INCOMING B (DIAG)',
            'type': 'consu',
            'purchase_ok': True,
            'uom_id': cls.uom_unit.id,
        })
        cls.other = cls.env['product.product'].create({
            'name': 'INSUMO INCOMING OTRO (DIAG)',
            'type': 'consu',
            'purchase_ok': True,
            'uom_id': cls.uom_unit.id,
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_po(self, lines, state='purchase'):
        """Crea una PO. ``lines`` = [(product, qty, uom, received), ...]."""
        po = self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': qty,
                'product_uom': uom.id,
            }) for product, qty, uom, _received in lines],
        })
        for line, (_p, _q, _u, received) in zip(po.order_line, lines):
            if received:
                line.qty_received = received
        if state:
            po.write({'state': state})
        return po

    def _wizard(self):
        """Wizard mínimo: ``_get_incoming_map`` no depende del tablero."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.product_a.id,
                'product_uom_qty': 1.0,
                'product_uom': self.uom_unit.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    # ------------------------------------------------------------------
    # Casos
    # ------------------------------------------------------------------
    def test_partial_and_full_receipt(self):
        """La recibida se descuenta; la no recibida cuenta completa."""
        po = self._make_po([
            (self.product_a, 10.0, self.uom_unit, 4.0),   # parcial: quedan 6
            (self.product_b, 5.0, self.uom_unit, 0.0),    # sin recibir: 5
        ])
        wizard = self._wizard()
        products = self.product_a | self.product_b
        incoming = wizard._get_incoming_map(products, po)

        self.assertEqual(incoming[self.product_a.id], [(6.0, self.uom_unit)])
        self.assertEqual(incoming[self.product_b.id], [(5.0, self.uom_unit)])

    def test_grouped_orders_and_lines_are_accumulated(self):
        """Varias PO del mismo pedido acumulan sus remanentes."""
        po1 = self._make_po([(self.product_a, 3.0, self.uom_unit, 0.0)])
        po2 = self._make_po([(self.product_a, 4.0, self.uom_unit, 1.0)])
        wizard = self._wizard()
        incoming = wizard._get_incoming_map([self.product_a], po1 | po2)

        entries = incoming[self.product_a.id]
        self.assertEqual(len(entries), 2, 'Cada PO aporta su propio remanente.')
        self.assertAlmostEqual(sum(qty for qty, _uom in entries), 6.0, places=3)

    def test_fully_received_line_is_not_incoming(self):
        """Una línea ya recibida no aporta nada 'en camino'."""
        po = self._make_po([(self.product_a, 5.0, self.uom_unit, 5.0)])
        wizard = self._wizard()
        incoming = wizard._get_incoming_map([self.product_a], po)
        self.assertNotIn(self.product_a.id, incoming)

    def test_different_uom_keeps_line_uom(self):
        """El remanente conserva la UdM de la línea (la conversión es luego)."""
        po = self._make_po([(self.product_a, 2.0, self.uom_dozen, 0.0)])
        wizard = self._wizard()
        incoming = wizard._get_incoming_map([self.product_a], po)
        self.assertEqual(incoming[self.product_a.id], [(2.0, self.uom_dozen)])

    def test_draft_and_cancelled_orders_are_ignored(self):
        """Ni borrador ni cancelada cuentan como material en camino."""
        draft = self._make_po(
            [(self.product_a, 5.0, self.uom_unit, 0.0)], state='draft')
        confirmed = self._make_po(
            [(self.product_a, 5.0, self.uom_unit, 0.0)], state='purchase')
        confirmed.button_cancel()
        wizard = self._wizard()

        self.assertEqual(wizard._get_incoming_map([self.product_a], draft), {})
        self.assertEqual(wizard._get_incoming_map([self.product_a], confirmed), {})

    def test_products_outside_the_filter_are_ignored(self):
        """Solo se consideran los productos pedidos por el llamador."""
        po = self._make_po([
            (self.product_a, 5.0, self.uom_unit, 0.0),
            (self.other, 7.0, self.uom_unit, 0.0),
        ])
        wizard = self._wizard()
        incoming = wizard._get_incoming_map([self.product_a], po)
        self.assertIn(self.product_a.id, incoming)
        self.assertNotIn(self.other.id, incoming)

    def test_empty_inputs_return_empty_map(self):
        po = self._make_po([(self.product_a, 5.0, self.uom_unit, 0.0)])
        wizard = self._wizard()
        self.assertEqual(wizard._get_incoming_map([], po), {})
        self.assertEqual(
            wizard._get_incoming_map([self.product_a], self.env['purchase.order']),
            {},
        )

    # ------------------------------------------------------------------
    # FASE 3: ``sale_name`` devuelve la PORCIÓN propia (OC agrupada 1:N).
    # ------------------------------------------------------------------
    def test_sale_name_returns_own_portion_only(self):
        wizard = self._wizard()
        so_a = wizard.board_id.sale_order_id  # product_a qty 1
        so_b = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.product_a.id,
                'product_uom_qty': 3.0,
                'product_uom': self.uom_unit.id,
            })],
        })
        so_b.write({'state': 'sale'})
        po = self._make_po([(self.product_a, 8.0, self.uom_unit, 0.0)])
        po.origin = '%s, %s' % (so_a.name, so_b.name)

        own = wizard._get_incoming_map(
            [self.product_a], po, sale_name=so_a.name)
        # Demanda A=1, B=3 -> total 4 -> porción A = 8 * 1/4 = 2.
        self.assertEqual(own[self.product_a.id], [(2.0, self.uom_unit)])

        # Sin ``sale_name``: comportamiento histórico (remanente completo).
        legacy = wizard._get_incoming_map([self.product_a], po)
        self.assertEqual(legacy[self.product_a.id], [(8.0, self.uom_unit)])
