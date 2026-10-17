# -*- coding: utf-8 -*-
"""Bloque II: anomalía, contención, lista de bloqueantes y remedios (PrintFlow).

Cubre P1/P2/P5/P7/P8 y las decisiones 5, 6, 7, 8, 12 y 13:
  * Anomalía (quant con libre < 0 compensado) -> re-reservar, NUNCA comprar.
  * Contención -> lista "quién me bloquea" por entrega/albarán, ordenada por
    fecha comprometida y, en su defecto, antigüedad; excluye entregadas.
  * Doble botón cuando hay descuadre Y falta física.
  * Bloqueo de OF sin BOM (decisión 7) y propuesta de cantidad al ajustar (8).
  * Permiso de re-reserva/saneamiento (jefe de taller o administrador).
  * Prohibido despojar la reserva ajena (P7).
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticRemedyBlocking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente Remedy Blq'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Remedy Blq', 'supplier_rank': 1,
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        # Segunda ubicación interna: permite tener un quant con libre negativo
        # (reserva colgada) compensado por otro quant con existencia libre.
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'REMEDY BLQ EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.Failure = cls.env['printflow.order.diagnostic.failure']
        cls.Blocking = cls.env['printflow.order.blocking.reservation']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product', 'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty, reserved=0.0, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty,
            reserved_quantity=reserved)

    def _force_board(self, product, qty):
        """Pedido forzado a 'sale' (sin procurement) + su tarjeta."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return self.env['printflow.order.board'].create({'sale_order_id': so.id})

    def _diagnose(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})

    def _line(self, wizard, product):
        return wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]

    def _failure(self, line, cause='free_exhausted', node='stock',
                 severity='warning'):
        return self.Failure.create({
            'line_id': line.id, 'pf_cause': cause, 'node': node,
            'severity': severity,
        })

    def _confirm_order(self, product, qty, commitment=None):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        if commitment:
            so.commitment_date = commitment
        return so

    # ------------------------------------------------------------------
    # P1 — Anomalía: re-reservar, no comprar/fabricar
    # ------------------------------------------------------------------
    def test_anomaly_recommends_reserve_not_buy(self):
        product = self._product('ANOMALIA RESERVA')
        # Quant con libre negativo compensado por otro con libre positivo.
        self._add_stock(product, 1.0, reserved=5.0, location=self.extra_location)
        self._add_stock(product, 10.0)
        board = self._force_board(product, 1.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        self.assertTrue(line)

        failure = self._failure(line)
        self.assertEqual(failure.pf_reservation_nature, 'anomaly')
        self.assertEqual(failure.pf_remedy_kind, 'run_action')
        self.assertEqual(failure.pf_remedy_target, 'fix_over_reservation')
        # El plan materializado también apunta al saneamiento.
        self.assertEqual(failure.pf_solution_kind, 'run_action')
        self.assertEqual(failure.pf_solution_target, 'fix_over_reservation')
        # NUNCA sugiere comprar/fabricar.
        for target in (failure.pf_remedy_target, failure.pf_solution_target):
            self.assertNotIn(target, ('buy_product', 'buy_components',
                                      'create_production'))
        # Anti-duplicación: el remedio primario (re-reservar) coincide con la
        # SOLUCIÓN del plan, así que el botón "Recomendación" se OCULTA (el
        # botón "Solucionar" ya ofrece lo mismo). El header primario queda
        # vacío; no hay alternativa porque no hay falta física.
        self.assertFalse(failure.pf_remedy_available)
        self.assertFalse(wizard.remedy_available)
        self.assertFalse(wizard.remedy_secondary_available)
        # Sin remedio primario, el botón de cabecera no navega a ningún lado.
        self.assertEqual(
            wizard.action_apply_remedy()['type'], 'ir.actions.act_window_close')

    # ------------------------------------------------------------------
    # P2/P8 — Contención: lista por entrega, ordenada
    # ------------------------------------------------------------------
    def test_contention_lists_blocking_delivery(self):
        product = self._product('CONTENCION LISTA')
        self._add_stock(product, 5.0)
        other = self._confirm_order(product, 5.0)
        board = self._force_board(product, 3.0)
        line = self._line(self._diagnose(board), product)
        self.assertTrue(line)
        self.assertGreater(line.contention_qty, 0.0)

        failure = self._failure(line)
        self.assertEqual(failure.pf_reservation_nature, 'contention')
        self.assertEqual(failure.pf_remedy_target, 'blocking_reservations')

        action = failure._pf_open_blocking_reservations()
        self.assertEqual(action['res_model'], 'printflow.order.blocking.reservation')
        records = self.Blocking.search(action['domain'])
        self.assertTrue(
            records.filtered(lambda r: r.sale_order_id == other),
            'La entrega del pedido bloqueante debe aparecer en la lista.')
        # Decisión 5: no se listan entregas terminadas/canceladas.
        self.assertTrue(all(
            r.picking_state not in ('done', 'cancel') for r in records))

    def test_blocking_order_priority_by_commitment(self):
        product = self._product('ORDEN BLOQUEANTES')
        self._add_stock(product, 20.0)
        now = fields.Datetime.now()
        later = self._confirm_order(
            product, 3.0, commitment=now + timedelta(days=5))
        earlier = self._confirm_order(
            product, 3.0, commitment=now + timedelta(days=1))
        # Demanda alta -> contención real, para que la falla exista.
        board = self._force_board(product, 15.0)
        line = self._line(self._diagnose(board), product)
        failure = self._failure(line)
        action = failure._pf_open_blocking_reservations()
        records = self.Blocking.search(action['domain'])
        self.assertGreaterEqual(len(records), 2)
        # La fecha comprometida manda: la más urgente (earlier) va primero.
        self.assertEqual(records[0].sale_order_id, earlier)
        self.assertNotEqual(records[0].sale_order_id, later)

    # ------------------------------------------------------------------
    # Decisión 12 — Doble botón: descuadre + falta física
    # ------------------------------------------------------------------
    def test_double_remedy_when_anomaly_and_physical(self):
        product = self._product(
            'DOBLE BOTON', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        # Quant con libre negativo compensado + agregado insuficiente.
        self._add_stock(product, 1.0, reserved=4.0, location=self.extra_location)
        self._add_stock(product, 10.0)
        board = self._force_board(product, 20.0)
        wizard = self._diagnose(board)
        line = self._line(wizard, product)
        self.assertGreater(line.deficit_qty, 0.0)

        # Falta física COMPRABLE: la causa real ahora es 'buy_product' (el motor
        # la clasifica por su remedio físico). Su plan YA ofrece comprar, así que
        # el primario se oculta (anti-duplicación); el saneamiento queda como
        # segundo botón/alternativa.
        failure = self._failure(line, cause='buy_product', node='stock',
                                severity='danger')
        self.assertEqual(failure.pf_reservation_nature, 'physical')
        self.assertFalse(failure.pf_remedy_available)
        self.assertEqual(failure.pf_remedy_target, 'buy_product')
        self.assertTrue(failure.pf_second_remedy_available)
        self.assertEqual(
            failure.pf_second_remedy_target, 'fix_over_reservation')
        # La cabecera conserva la ALTERNATIVA aunque el primario esté oculto.
        self.assertTrue(wizard.remedy_secondary_available)

    # ------------------------------------------------------------------
    # Decisión 7 — Bloquear OF sin BOM
    # ------------------------------------------------------------------
    def test_create_production_without_bom_is_blocked(self):
        product = self._product('SIN BOM BLOQUEO')
        board = self._force_board(product, 2.0)
        line = self._line(self._diagnose(board), product)
        failure = self._failure(line, cause='order_shortfall')
        with self.assertRaises(UserError):
            failure._pf_open_create_production()

    def test_create_production_with_bom_opens_without_creating(self):
        component = self._product('COMPONENTE BOM OK')
        self._add_stock(component, 50.0)
        product = self._product('CON BOM OK')
        self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        board = self._force_board(product, 2.0)
        line = self._line(self._diagnose(board), product)
        failure = self._failure(line, cause='order_shortfall')
        mos_before = self.env['mrp.production'].search_count([])
        action = failure._pf_open_create_production()
        self.assertEqual(action['res_model'], 'mrp.production')
        self.assertFalse(action.get('res_id'))
        self.assertEqual(
            self.env['mrp.production'].search_count([]), mos_before,
            'Abrir el botón NO debe crear la OF (abrir ≠ ejecutar).')

    # ------------------------------------------------------------------
    # Decisión 8 — Ajuste propone la cantidad
    # ------------------------------------------------------------------
    def test_adjust_proposes_suggested_qty(self):
        product = self._product('AJUSTE SUGERIDO')
        board = self._force_board(product, 4.0)
        line = self._line(self._diagnose(board), product)
        failure = self._failure(line, cause='order_shortfall')
        action = failure._pf_open_quants_adjust()
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertTrue(action['context']['inventory_mode'])
        self.assertAlmostEqual(
            action['context']['pf_suggested_qty'], 4.0, places=3)

    # ------------------------------------------------------------------
    # P5 — Comprar producto no crea OC al abrir; decisión 10 sin venta
    # ------------------------------------------------------------------
    def test_buy_product_opens_wizard_without_creating_po(self):
        product = self._product(
            'COMPRAR SIN CREAR', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        board = self._force_board(product, 3.0)
        line = self._line(self._diagnose(board), product)
        failure = self._failure(line, cause='order_shortfall')
        po_before = self.env['purchase.order'].search_count([])
        action = failure._pf_open_buy_product()
        self.assertEqual(action['res_model'], 'mrp.quick.purchase.wizard')
        self.assertEqual(
            self.env['purchase.order'].search_count([]), po_before,
            'Abrir la compra NO debe crear la OC (abrir ≠ ejecutar).')

    # ------------------------------------------------------------------
    # P7 — La re-reserva no despoja la reserva de otro pedido
    # ------------------------------------------------------------------
    def test_fix_over_reservation_does_not_steal_other_order(self):
        product = self._product('NO DESPOJO')
        self._add_stock(product, 5.0)
        first = self._confirm_order(product, 5.0)
        first_picking = first.picking_ids.filtered(
            lambda p: p.state not in ('done', 'cancel'))
        self.assertTrue(first_picking)
        reserved_before = sum(first_picking.move_line_ids.mapped('quantity'))

        second = self._confirm_order(product, 3.0)
        board = self.env['printflow.order.board'].create(
            {'sale_order_id': second.id})
        line = self._line(self._diagnose(board), product)
        failure = self._failure(line)

        failure._pf_run_fix_over_reservation()

        first_picking.invalidate_recordset()
        reserved_after = sum(first_picking.move_line_ids.mapped('quantity'))
        self.assertAlmostEqual(
            reserved_before, reserved_after, places=3,
            msg='La re-reserva del pedido en foco no debe tocar la reserva ajena.')
        self.assertEqual(first_picking.state, 'assigned')

    # ------------------------------------------------------------------
    # Decisiones 6/13 — Permiso de re-reserva y saneamiento
    # ------------------------------------------------------------------
    def test_reservation_permission_is_restricted(self):
        Remedy = self.env['printflow.stock.remedy']
        # El superusuario del entorno de test puede limpiar/re-reservar.
        self.assertTrue(Remedy._pf_user_can_clean_reservations())
        # Un usuario no privilegiado no puede (no se crean usuarios: el
        # entorno de test no tiene filestore escribible).
        restricted_user = self.env.ref(
            'base.public_user', raise_if_not_found=False)
        if not restricted_user:
            self.skipTest('base.public_user no está disponible.')
        restricted = Remedy.with_user(restricted_user)
        self.assertFalse(restricted._pf_user_can_clean_reservations())
        with self.assertRaises(UserError):
            restricted._pf_assert_can_clean()

    def test_board_global_cleanup_restricted(self):
        restricted_user = self.env.ref(
            'base.public_user', raise_if_not_found=False)
        if not restricted_user:
            self.skipTest('base.public_user no está disponible.')
        product = self._product('SANEAMIENTO RESTRICCION')
        self._add_stock(product, 1.0, reserved=5.0)
        board = self._force_board(product, 1.0)
        with self.assertRaises(UserError):
            board.with_user(restricted_user).action_cleanup_over_reservations()
