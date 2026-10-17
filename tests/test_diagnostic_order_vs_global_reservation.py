# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticOrderVsGlobalReservation(TransactionCase):
    """B2: el Wizard de Diagnóstico debe distinguir dos causas distintas.

    * **Falta física**: no hay mercancía suficiente ni en camino -> comprar o
      fabricar (``deficit_qty`` / ``stock_status == 'deficit'``).
    * **Contención**: el stock existe, pero lo tienen reservado OTROS pedidos
      -> reasignar (``is_contention`` / ``stock_status == 'over'``), NUNCA
      comprar.

    Antes el wizard le atribuía a este pedido toda la sobre-reserva global del
    almacén, por lo que un pedido sin material propio aparecía con "sobre-reserva"
    aunque la causa real fuera que otro pedido se llevó el stock.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Contencion Diagnostico',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        """Producto almacenable PrintFlow SIN ruta de compra.

        Sin ruta de compra, ``action_confirm`` crea el albarán de entrega (que es
        el que reserva), que es justo lo que este test necesita medir.
        """
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _confirm_order(self, product, qty):
        """Pedido confirmado de verdad: genera y reserva su albarán de entrega."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return self.env['printflow.order.board'].create({'sale_order_id': so.id})

    def _diagnose(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

    # ------------------------------------------------------------------
    # 1. Stock suficiente, pero reservado por OTRO pedido -> contención
    # ------------------------------------------------------------------
    def test_contention_when_stock_reserved_by_other_order(self):
        product = self._make_product('PRODUCTO CONTENCION (DIAG)')
        self._add_stock(product, 5.0)

        # OTRO pedido se lleva todo el stock primero.
        self._confirm_order(product, 5.0)
        # El pedido diagnosticado necesita 3 y ya no queda stock libre.
        board = self._confirm_order(product, 3.0)

        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(lambda l: l.product_id == product)

        self.assertTrue(line, 'El producto debe aparecer en el desglose.')
        # No hay falta física: el stock existe (5 >= 3).
        self.assertAlmostEqual(wizard.deficit_total, 0.0, places=3)
        self.assertAlmostEqual(line.deficit_qty, 0.0, places=3)
        # Pero sí hay contención: lo tienen otros.
        self.assertEqual(wizard.stock_status, 'over')
        self.assertTrue(line.is_contention)
        self.assertAlmostEqual(line.contention_qty, 3.0, places=3)
        # La ruta correcta es reasignar, jamás comprar.
        self.assertEqual(wizard.recommended_route, 'reassign')
        self.assertNotEqual(wizard.recommended_route, 'purchase')

    # ------------------------------------------------------------------
    # 2. Stock insuficiente (aunque no haya otros pedidos) -> falta física
    # ------------------------------------------------------------------
    def test_physical_shortfall_routes_to_purchase_or_produce(self):
        product = self._make_product('PRODUCTO SIN STOCK (DIAG)')
        # Sin stock y sin otros pedidos.
        board = self._confirm_order(product, 5.0)

        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(lambda l: l.product_id == product)

        self.assertTrue(line)
        self.assertGreater(wizard.deficit_total, 0.0)
        self.assertAlmostEqual(line.deficit_qty, 5.0, places=3)
        self.assertEqual(wizard.stock_status, 'deficit')
        self.assertFalse(line.is_contention)
        self.assertIn(wizard.recommended_route, ('purchase', 'produce'))

    # ------------------------------------------------------------------
    # 3. La propia reserva del pedido NO es contención
    # ------------------------------------------------------------------
    def test_own_reservation_is_not_contention(self):
        product = self._make_product('PRODUCTO RESERVA PROPIA (DIAG)')
        self._add_stock(product, 10.0)

        board = self._confirm_order(product, 5.0)
        wizard = self._diagnose(board)
        line = wizard.deficit_line_ids.filtered(lambda l: l.product_id == product)

        self.assertTrue(line)
        # El pedido reservó lo suyo: ni falta física ni contención.
        self.assertAlmostEqual(line.order_reserved_qty, 5.0, places=3)
        self.assertAlmostEqual(line.contention_qty, 0.0, places=3)
        self.assertFalse(line.is_contention)
        self.assertAlmostEqual(wizard.deficit_total, 0.0, places=3)
        self.assertNotEqual(wizard.stock_status, 'over')
