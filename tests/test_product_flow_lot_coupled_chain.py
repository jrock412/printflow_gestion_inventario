# -*- coding: utf-8 -*-
"""P1 · Las DOS fallas de lote del diagrama de PRODUCTO son UNA sola (CA-1).

Custodia que, cuando la ENTREGA de un producto por lote reserva SIN lote
(``lot_missing``) y deja el inventario con una reserva COLGADA (``data_anomaly``),
el diagrama del producto presente ambos nodos como UNA MISMA falla:

  * la raíz de la cadena pasa a ser la ENTREGA y el INVENTARIO su CONSECUENCIA
    (cadena INVERTIDA respecto al orden natural compras→…→entrega), en vez de
    quedar los dos marcados "Independiente";
  * la franja ``chain_summary`` nombra ambos nodos, con la Entrega PRIMERO;
  * el nodo Entrega nombra el LOTE EXCLUSIVO esperado del pedido (causa raíz
    explícita, ``SXXXXX-Lyyyy``) cuando es determinable.

El caso NO acoplado (solo ``lot_missing``, sin la reserva colgada) queda
EXACTAMENTE como hoy: NO se inventa cadena (candado de no-regresión).

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar (sin ``cr.execute``/``cr.commit``).
"""
import json

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestProductFlowLotCoupledChain(
        PrintflowStockHealthTestMixin, TransactionCase):
    """Entrega sin lote + reserva colgada = UNA falla encadenada (raíz→consec.)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Cadena Lote'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _real_stock(self, product, qty=10.0):
        """Stock REAL en un lote propio: evita el déficit de stock (así el
        inventario no se repinta por falta de existencia y la única falla de lote
        es la entrega sin lote)."""
        lot = self.env['stock.lot'].create(
            {'name': '%s-REAL' % product.name, 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)
        return lot

    def _outgoing_without_lot(self, product, qty=3.0, sale_line=None):
        """Albarán de salida cuyo movimiento RESERVA SIN lote (``lot_missing``).

        La línea de movimiento se crea con ``lot_id=False`` y cantidad > 0 hacia
        una ubicación de cliente ⇒ el motor la cuenta en ``missing_move_ids``.

        IMPORTANTE: se confirma el movimiento ANTES de añadir stock, porque
        ``stock.move._action_confirm()`` llama internamente a ``_action_assign()``
        (Odoo 17): si ya hubiera existencia, Odoo reservaría por su cuenta (con el
        lote real) y crearía una move line extra, desvirtuando el escenario. Por
        eso este helper se invoca ANTES de ``_real_stock``/``_hanging_quant``.
        """
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        move = self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
        })
        move._action_confirm()
        if sale_line is not None:
            # Vínculo al pedido (para derivar el lote EXCLUSIVO esperado). Se
            # escribe por ORM (el campo es readonly en UI, no en ORM).
            move.write({'sale_line_id': sale_line.id})
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'quantity': qty,
            'lot_id': False,
        })
        return picking, move

    def _backing_quant(self, product, qty=5.0):
        """Existencia SIN lote que RESPALDA la reserva (neutraliza la anomalía).

        La línea sin lote ya reserva por su cuenta (Odoo crea el quant sin lote
        con ``reserved > quantity`` ⇒ reserva colgada). Añadiendo físico sin lote
        en la MISMA ubicación la reserva queda RESPALDADA ⇒ el estado de lote
        sigue siendo ``lot_missing`` pero YA no hay ``data_anomaly``: sirve para
        el escenario NO acoplado (candado de no-regresión).
        """
        self._pf_add_stock(product, qty, location=self.stock_location)

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _payload(self, product):
        return json.loads(self._wizard(product).timeline_json)

    def _by_key(self, payload):
        return {node['key']: node for node in payload['nodes']}

    def _sale_line(self, product, qty=3.0):
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        return sale.order_line[:1]

    # ==================================================================
    # CA-1a · Caso ACOPLADO: Entrega = raíz, Inventario = consecuencia
    # ==================================================================
    def test_coupled_delivery_is_root_inventory_consequence(self):
        product = self._product('CADENA LOTE ACOPLADA')
        self._outgoing_without_lot(product, 3.0)
        self._real_stock(product, 10.0)

        payload = self._payload(product)
        by_key = self._by_key(payload)

        # La RAÍZ es la Entrega (reservó sin lote) y el Inventario su consecuencia
        # (reserva colgada): ya NO salen los dos "independientes".
        self.assertEqual(by_key['delivery']['role'], 'root')
        self.assertEqual(by_key['stock']['role'], 'consequence')
        self.assertEqual(by_key['stock']['parent'], 'delivery')
        self.assertIn('root_link', by_key['stock'])
        self.assertEqual(by_key['stock']['root_link']['target_key'], 'delivery')

        # La franja de cadena nombra AMBOS nodos, con la raíz (Entrega) primero.
        summary = payload['global']['chain_summary']
        self.assertIn('Entrega', summary)
        self.assertIn('Inventario', summary)
        self.assertLess(
            summary.index('Entrega'), summary.index('Inventario'),
            'La raíz (Entrega) debe ir ANTES de su consecuencia (Inventario).')

    # ==================================================================
    # CA-1b · Caso NO acoplado: sin reserva colgada NO se inventa cadena
    # ==================================================================
    def test_uncoupled_delivery_alone_does_not_invent_chain(self):
        product = self._product('CADENA LOTE NO ACOPLADA')
        self._outgoing_without_lot(product, 3.0)
        self._real_stock(product, 10.0)
        # Respalda la reserva sin lote ⇒ no hay ``data_anomaly``: queda SOLO el
        # ``lot_missing`` de la entrega (el caso que NO debe acoplarse).
        self._backing_quant(product, 5.0)

        payload = self._payload(product)
        by_key = self._by_key(payload)

        # Sin la reserva colgada el ACOPLAMIENTO no dispara: la entrega es la
        # raíz (comportamiento EXISTENTE y correcto, es el único nodo roto) pero
        # el inventario NO se promueve a su consecuencia ni se inventa cadena.
        self.assertNotEqual(by_key['stock']['role'], 'consequence')
        self.assertNotIn('root_link', by_key['stock'])
        self.assertEqual(payload['global']['chain_summary'], '')

    # ==================================================================
    # CA-1c · Causa raíz explícita: el nodo Entrega nombra el lote esperado
    # ==================================================================
    def test_coupled_delivery_names_expected_exclusive_lot(self):
        product = self._product('CADENA LOTE ESPERADO')
        line = self._sale_line(product, 3.0)
        self._outgoing_without_lot(product, 3.0, sale_line=line)
        self._real_stock(product, 10.0)

        expected = line._get_exclusive_lot_name()
        self.assertTrue(
            expected, 'El pedido debe exponer un lote exclusivo determinable.')

        payload = self._payload(product)
        by_key = self._by_key(payload)

        # El resumen del nodo Entrega (raíz) nombra el lote EXCLUSIVO esperado.
        self.assertIn(expected, by_key['delivery']['summary'])
