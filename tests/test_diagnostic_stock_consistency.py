# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticStockConsistency(TransactionCase):
    """El nodo INVENTARIO del wizard de diagnostico NO debe contradecir la
    matematica por producto.

    Caso reportado: el tablero deja ``health_stock == 'ok'`` (su semaforo no ve
    el faltante), pero el desglose del wizard detecta un deficit real. Antes el
    badge copiaba ciegamente el semaforo y mostraba 'ok' junto a la alerta roja
    de deficit. Con la regla de precedencia nueva, si el desglose detecta
    deficit el badge DEBE mostrar 'deficit'.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Diagnostico Stock',
        })
        # Producto PrintFlow almacenable, SIN stock en el sistema.
        cls.product = cls.env['product.product'].create({
            'name': 'PRODUCTO SIN STOCK (DIAGNOSTICO)',
            'type': 'product',
            'x_is_printflow_managed': True,
        })

    def _make_board_with_deficit_and_ok_health(self, qty=5.0):
        """Pedido confirmado a la fuerza (sin procurement), sin MO ni stock.

        Se escribe ``state = 'sale'`` directamente para reproducir el caso real
        en el que Odoo NO genero la MO (el temido 'SIN ORDEN'): asi el semaforo
        del tablero se queda en 'ok' aunque falte el material.
        """
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'product_uom': self.product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        board = self.env['printflow.order.board'].create({'sale_order_id': so.id})
        # Recalculo acotado a esta tarjeta (mismo patron que los tests existentes).
        board.invalidate_model([
            'has_production', 'has_waiting_material', 'is_stock_missing',
            'production_alert', 'procurement_type', 'health_stock',
        ])
        board._compute_production_status()
        board._compute_purchase_status()
        board._compute_is_stock_missing()
        board._compute_health_flags()
        return board

    def test_badge_shows_deficit_when_health_is_ok(self):
        board = self._make_board_with_deficit_and_ok_health()
        # Precondicion del bug: el semaforo del tablero no ve el faltante.
        self.assertEqual(
            board.health_stock, 'ok',
            'El escenario debe reproducir el semaforo en verde para validar la correccion.',
        )

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

        self.assertGreater(wizard.deficit_total, 0.0)
        self.assertTrue(wizard.has_deficit)
        self.assertNotEqual(wizard.stock_status, 'ok',
                            'El badge no puede decir OK si el desglose detecta deficit.')
        self.assertEqual(wizard.stock_status, 'deficit')
        self.assertIn('déficit', (wizard.stock_summary or '').lower())

    def test_summary_warns_when_semaphore_flags_over_without_gaps(self):
        """El semaforo dice 'over' pero el desglose no ve sobre-reserva:
        se avisa en vez de decir 'Stock suficiente'."""
        summary = self.env['printflow.order.diagnostic.wizard']._stock_summary(
            {
                'stock_status': 'over',
                'over_reserved_total': 0.0,
                'deficit_total': 0.0,
                'incoming_total': 0.0,
            },
            [],
        )
        self.assertIn('sobrepedido', summary.lower())

    def test_summary_warns_when_semaphore_flags_deficit_without_gaps(self):
        """Aviso historico preservado: semaforo 'deficit' sin respaldo numerico."""
        summary = self.env['printflow.order.diagnostic.wizard']._stock_summary(
            {
                'stock_status': 'deficit',
                'over_reserved_total': 0.0,
                'deficit_total': 0.0,
                'incoming_total': 0.0,
            },
            [],
        )
        self.assertIn('no lo refleja', summary.lower())
