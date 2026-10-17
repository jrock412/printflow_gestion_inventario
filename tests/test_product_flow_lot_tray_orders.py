# -*- coding: utf-8 -*-
"""Bandeja de lote: P2 (lista TODAS las órdenes) + P3 (botón honesto).

Custodia los criterios CA-2 y CA-3 del plan de "Gestión del error de lote en el
diagrama de producto":

* **CA-2 (P2)** — el "Solucionar" del nodo Entrega (``lot_missing``) lista, además
  de la fila del MOVIMIENTO ya creado sin lote (``missing_move``), **UNA fila por
  cada ORDEN de entrega pendiente del producto que aún NO tiene lote**
  (``kind='pending_order'``, ``res_model='stock.picking'``). La entrega SANA (con
  lote asignado) NO aparece y todas las filas resuelven al modo ``assign``. Las dos
  lecturas se SUMAN a propósito (O-5): no se deduplican.
* **CA-3 (P3)** — el "problem" del plan ``lot_missing`` se rotula
  "Ver existencias por lote" y su destino sigue siendo ``quants`` (el botón dice
  la verdad sobre a dónde lleva).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios productos/albaranes y
``TransactionCase`` hace rollback al terminar. NO escribe ni valida por detrás.
"""

from odoo.tests.common import TransactionCase, tagged

# Tope de filas por nodo (0 = sin tope). Se fija para que el conteo de filas
# ``pending_order`` sea determinista y no dependa de la configuración de la BD.
PARAM_NODE_PENDING_LIMIT = (
    'x_product_dimensional_pricing.pf_node_pending_limit')
PARAM_NODE_PENDING_ENABLED = (
    'x_product_dimensional_pricing.pf_node_pending_enabled')
PARAM_NODE_PENDING_NODES = (
    'x_product_dimensional_pricing.pf_node_pending_nodes')


@tagged('post_install', '-at_install')
class TestProductFlowLotTrayOrders(TransactionCase):
    """P2/P3: la bandeja lista las órdenes pendientes y el botón no miente."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Bandeja Ordenes'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Lots = cls.env['printflow.flow.lots']
        cls.Playbook = cls.env['printflow.resolution.playbook']
        # Determinismo: nodos habilitados y SIN tope de filas (transitorio;
        # vive en la transacción del test y no persiste).
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param(PARAM_NODE_PENDING_ENABLED, '1')
        ICP.set_param(PARAM_NODE_PENDING_NODES,
                      'purchase,receipt,production,delivery,sale')
        ICP.set_param(PARAM_NODE_PENDING_LIMIT, '0')

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self):
        product = self.env['product.product'].create({
            'name': 'BANDEJA ORDENES P2',
            'type': 'product',
            'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _outgoing(self, product, qty=2.0, lot=None, with_line=True):
        """Albarán de salida confirmado; opcionalmente con move line.

        La confirmación ocurre ANTES de que exista existencia: así ``Odoo`` no
        reserva nada por su cuenta y el escenario queda controlado (mismo
        cuidado que ``test_product_flow_lot_coupled_chain``).
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
        if with_line:
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': picking.id,
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
                'quantity': qty,
                'lot_id': lot.id if lot else False,
            })
        return picking, move

    def _open_tray(self, product, lot_state, expect_rows=True):
        """Abre la bandeja por el dispatcher (misma ruta que el operador).

        ``expect_rows=False`` para los casos donde NO debe haber ninguna fila
        (p. ej. todas las entregas ya tienen lote).
        """
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        wizard = self.Flow.browse(action['res_id'])
        action = wizard.action_run_pf_plan(lot_state, 'solution')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.tray')
        tray = self.Tray.search([('product_id', '=', product.id)])
        if expect_rows:
            self.assertTrue(tray, 'La bandeja debe traer al menos una fila.')
            self.assertEqual(set(tray.mapped('lot_state')), {lot_state})
        return tray

    # ------------------------------------------------------------------
    # CA-2 — P2: la bandeja lista TODAS las órdenes pendientes sin lote
    # ------------------------------------------------------------------
    def test_ca2_pending_orders_listed_one_row_per_delivery(self):
        """Una fila por ORDEN sin lote; la SANA no aparece; modo ``assign``."""
        product = self._product()
        real_lot = self._lot(product, 'P2-LOTE-REAL')
        # 3 entregas pendientes SIN lote (2 sin reserva y 1 con move line sin
        # lote ⇒ además produce la fila ``missing_move`` de la evidencia técnica).
        pick_a, _move_a = self._outgoing(product, 2.0, with_line=False)
        pick_b, _move_b = self._outgoing(product, 4.0, with_line=False)
        pick_c, move_c = self._outgoing(product, 3.0, with_line=True)
        # 1 entrega SANA: su movimiento SÍ tiene lote (exclusivo del pedido o uno
        # real) ⇒ NO debe listarse como orden pendiente.
        pick_ok, _move_ok = self._outgoing(product, 3.0, lot=real_lot)
        # Existencia del lote real (deja la entrega sana respaldada de verdad).
        self._stock(product, 10.0, lot=real_lot)

        tray = self._open_tray(product, 'lot_missing')

        pending = tray.filtered(lambda r: r.kind == 'pending_order')
        # (a) una fila por cada orden pendiente SIN lote.
        self.assertEqual(
            set(pending.mapped('res_id')), {pick_a.id, pick_b.id, pick_c.id})
        self.assertEqual(set(pending.mapped('res_model')), {'stock.picking'})
        self.assertTrue(
            all(row.res_model == 'stock.picking' for row in pending))
        # (b) la entrega SANA (con lote) NO aparece.
        self.assertNotIn(pick_ok.id, pending.mapped('res_id'))
        # (c) todas resuelven al modo ``assign`` (nunca en blanco).
        self.assertEqual(set(pending.mapped('lot_action_mode')), {'assign'})
        # (d) cada fila navega a SU documento (doc_ref = par modelo/registro).
        for row in pending:
            self.assertEqual(row.document_ref._name, 'stock.picking')
            self.assertEqual(row.document_ref.id, row.res_id)
        # (e) la demanda viaja por fila (dimensión real de la orden).
        demand = {row.res_id: row.demand_qty for row in pending}
        self.assertAlmostEqual(demand[pick_a.id], 2.0)
        self.assertAlmostEqual(demand[pick_b.id], 4.0)
        self.assertAlmostEqual(demand[pick_c.id], 3.0)
        # (f) no-regresión: la fila del MOVIMIENTO ya creado sin lote sigue ahí
        #     (ambas lecturas conviven; no se deduplican).
        missing = tray.filtered(lambda r: r.kind == 'missing_move')
        self.assertIn(move_c.id, missing.mapped('res_id'))
        # (g) el operador ve la dimensión completa, no una sola fila.
        self.assertGreater(len(tray), 1)

    def test_ca2_pending_orders_exclude_fully_lotted_deliveries(self):
        """Si TODAS las entregas tienen lote, no se inventa ninguna orden."""
        product = self._product()
        lot = self._lot(product, 'P2-LOTE-UNICO')
        pick_ok, _move_ok = self._outgoing(product, 3.0, lot=lot)
        self._stock(product, 5.0, lot=lot)

        tray = self._open_tray(product, 'lot_missing', expect_rows=False)

        pending = tray.filtered(lambda r: r.kind == 'pending_order')
        self.assertFalse(pending)
        self.assertNotIn(pick_ok.id, pending.mapped('res_id'))

    def test_ca2_pending_order_search_mode_keeps_assign(self):
        """El filtro de la vista (``assign``) NO pierde las órdenes nuevas."""
        product = self._product()
        pick, _move = self._outgoing(product, 2.0, with_line=False)

        tray = self._open_tray(product, 'lot_missing')

        found = self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_action_mode', '=', 'assign'),
        ])
        self.assertIn(pick.id, found.filtered(
            lambda r: r.kind == 'pending_order').mapped('res_id'))

    # ------------------------------------------------------------------
    # CA-3 — P3: el rótulo del botón coincide con su destino (``quants``)
    # ------------------------------------------------------------------
    def test_ca3_problem_label_matches_quants_target(self):
        """El "problem" de ``lot_missing`` se llama "Ver existencias por lote"."""
        plan = self.Lots._pf_plan_for_state('lot_missing', 'product')
        problem = plan['actions']['problem']
        self.assertEqual(problem['label'], 'Ver existencias por lote')
        self.assertEqual(problem['kind'], 'navigate')
        self.assertEqual(problem['target'], 'quants')

    def test_ca3_problem_label_in_both_modes(self):
        """El rotulado honesto aplica igual sin pedido y con pedido."""
        for has_order in (False, True):
            plan = self.Playbook._pf_plan_lot_missing(
                {'has_order': has_order})
            problem = plan['actions']['problem']
            self.assertEqual(problem['label'], 'Ver existencias por lote')
            self.assertEqual(problem['target'], 'quants')
