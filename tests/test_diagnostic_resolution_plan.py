# -*- coding: utf-8 -*-
"""FASE 3 — Experiencia de resolución de los diagnósticos.

Cubre:
  (a) el playbook devuelve un plan y un FALLBACK genérico;
  (b) el contrato extendido de TRES acciones (problema / solución / recopilar)
      con sus ALIAS deprecados apuntando a la solución;
  (c) ``pf_cause`` del hallazgo se deriva de ``check_code`` + ``severity``;
  (d) la navegación del problema (síntoma), de la solución (raíz) y de la raíz
      en conjunto (recopilar), resueltas bajo demanda;
  (e) la regla "síntoma = raíz -> un solo botón";
  (f) el wizard de pedido traduce contención/déficit a lenguaje llano.
"""
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.printflow_gestion_inventario.models \
    .printflow_finding_resolution import pf_reserving_sale_order_ids

# Mapa esperado causa -> tres acciones (kind, target) para ``has_bom=False``.
EXPECTED_ACTION_MAP = {
    'negative': {
        'problem': ('navigate', 'quants'),
        'solution': ('navigate', 'quants_adjust'),
        'collect': ('none', ''),
    },
    'free_exhausted': {
        'problem': ('navigate', 'quants'),
        'solution': ('navigate', 'reserving_sale_orders'),
        'collect': ('navigate', 'reserving_sale_orders'),
    },
    'kit_no_own_stock': {
        'problem': ('navigate', 'quants'),
        'solution': ('navigate', 'bom'),
        'collect': ('navigate', 'collect_tray'),
    },
    'bom_duplicated': {
        'problem': ('navigate', 'bom_list'),
        'solution': ('navigate', 'bom_duplicates'),
        'collect': ('navigate', 'collect_tray'),
    },
    'bom_archive_blocked': {
        'problem': ('navigate', 'bom'),
        'solution': ('navigate', 'sale_orders'),
        'collect': ('navigate', 'collect_tray'),
    },
    'orderpoint_kit': {
        'problem': ('navigate', 'product'),
        'solution': ('navigate', 'orderpoint'),
        'collect': ('navigate', 'collect_tray'),
    },
    'no_route': {
        'problem': ('none', ''),
        'solution': ('navigate', 'product'),
        'collect': ('none', ''),
    },
    'pending_sale_lines': {
        'problem': ('navigate', 'sale_lines'),
        'solution': ('navigate', 'sale_orders'),
        'collect': ('navigate', 'collect_tray'),
    },
    'active_mo': {
        'problem': ('navigate', 'mo_list'),
        'solution': ('navigate', 'mo'),
        'collect': ('navigate', 'collect_tray'),
    },
    'record_archived': {
        'problem': ('none', ''),
        'solution': ('navigate', 'product'),
        'collect': ('none', ''),
    },
    'record_no_supplier': {
        'problem': ('none', ''),
        'solution': ('navigate', 'product'),
        'collect': ('none', ''),
    },
}


@tagged('post_install', '-at_install')
class TestDiagnosticResolutionPlan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Plan Resolucion',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Scanner = cls.env['printflow.product.diagnostic.wizard']
        cls.Playbook = cls.env['printflow.resolution.playbook']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _confirm_order(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _force_negative_free(self, product):
        """Deja el libre AGREGADO del producto en negativo (sobre-reserva).

        Escribe ``reserved_quantity`` del quant interno por encima de su
        cantidad: así ``free_global < 0`` y el motor unificado de flujo clasifica
        la disponibilidad como ``free_exhausted`` (antes lo avisaba
        ``stock_negative`` como warning; ahora es propiedad de ``check_flow``).
        """
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ], limit=1)
        if quant:
            quant.sudo().write({
                'reserved_quantity': (quant.quantity or 0.0) + 1.0,
            })

    def _finding(self, wizard, code):
        return wizard.finding_ids.filtered(lambda f: f.check_code == code)

    # ------------------------------------------------------------------
    # (a) Playbook: plan y fallback
    # ------------------------------------------------------------------
    def test_playbook_fallback_for_unknown_cause(self):
        plan = self.Playbook._pf_get_plan('causa_que_no_existe')
        self.assertTrue(plan['summary'])
        self.assertEqual(plan['action_kind'], 'none')
        self.assertEqual(len(plan['steps']), 3)
        self.assertIn('Revisa', plan['summary'])
        # El fallback también trae las tres acciones (todas desactivadas).
        for key in ('problem', 'solution', 'collect'):
            self.assertFalse(plan['actions'][key]['available'])

    def test_playbook_free_exhausted_plan(self):
        plan = self.Playbook._pf_get_plan('free_exhausted')
        self.assertEqual(plan['action_kind'], 'navigate')
        self.assertEqual(plan['target'], 'reserving_sale_orders')
        self.assertEqual(len(plan['steps']), 3)
        self.assertIn('otros pedidos', plan['summary'])

    # ------------------------------------------------------------------
    # (b) Contrato extendido: mapa de las tres acciones
    # ------------------------------------------------------------------
    def test_playbook_action_map(self):
        """El playbook expone las tres acciones con kind/target/available."""
        for cause, expected in EXPECTED_ACTION_MAP.items():
            plan = self.Playbook._pf_get_plan(cause)
            actions = plan['actions']
            for key in ('problem', 'solution', 'collect'):
                kind, target = expected[key]
                action = actions[key]
                self.assertEqual(
                    action['kind'], kind,
                    'Causa %s/%s: kind inesperado.' % (cause, key))
                self.assertEqual(
                    action['target'], target,
                    'Causa %s/%s: target inesperado.' % (cause, key))
                self.assertEqual(
                    action['available'], kind != 'none',
                    'Causa %s/%s: available incoherente.' % (cause, key))
            # Los ALIAS deprecados SIEMPRE apuntan a la solución (raíz).
            self.assertEqual(
                plan['action_kind'], actions['solution']['kind'])
            self.assertEqual(
                plan['action_label'], actions['solution']['label'])
            self.assertEqual(
                plan['target'], actions['solution']['target'])

    def test_available_labels_are_distinct(self):
        """Cada botón disponible tiene etiqueta propia (destinos distintos)."""
        for cause in EXPECTED_ACTION_MAP:
            plan = self.Playbook._pf_get_plan(cause)
            labels = [
                action['label']
                for action in plan['actions'].values()
                if action['available']
            ]
            self.assertTrue(
                all(labels), 'Causa %s: hay acción disponible sin etiqueta.' % cause)
            self.assertEqual(
                len(labels), len(set(labels)),
                'Causa %s: etiquetas repetidas entre botones.' % cause)

    def test_playbook_uom_mismatch_solution_follows_bom(self):
        with_bom = self.Playbook._pf_get_plan(
            'uom_mismatch', ctx={'has_bom': True})
        self.assertEqual(
            with_bom['actions']['solution']['target'], 'bom')
        without_bom = self.Playbook._pf_get_plan('uom_mismatch')
        self.assertEqual(
            without_bom['actions']['solution']['target'], 'product')
        # Sin BOM, síntoma y raíz coinciden: un solo botón.
        self.assertFalse(without_bom['actions']['problem']['available'])

    # ------------------------------------------------------------------
    # (c) pf_cause del hallazgo
    # ------------------------------------------------------------------
    def test_free_exhausted_finding_exposes_plan(self):
        product = self._make_product('PRODUCTO RESERVA TOTAL (DIAG)')
        self._add_stock(product, 5.0)
        self._confirm_order(product, 5.0)  # otro pedido se lleva todo.
        # Sobre-reserva agregada -> la disponibilidad es del motor de flujo.
        self._force_negative_free(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'flow_free_exhausted')[:1]

        self.assertTrue(finding, 'Debe existir el hallazgo de libre agotada.')
        self.assertEqual(finding.pf_cause, 'free_exhausted')
        self.assertTrue(finding.pf_plan_summary)
        self.assertTrue(finding.pf_plan_steps.startswith('1.'))
        # Tres acciones con destinos distintos para el caso central.
        self.assertEqual(finding.pf_problem_target, 'quants')
        self.assertEqual(
            finding.pf_solution_target, 'reserving_sale_orders')
        self.assertEqual(
            finding.pf_collect_target, 'reserving_sale_orders')
        self.assertTrue(finding.pf_problem_available)
        self.assertTrue(finding.pf_solution_available)
        self.assertTrue(finding.pf_collect_available)
        # Alias deprecados == solución.
        self.assertEqual(
            finding.pf_action_target, finding.pf_solution_target)
        self.assertTrue(finding.pf_action_available)

    def test_negative_finding_cause_is_negative(self):
        product = self._make_product('PRODUCTO NEGATIVO (DIAG)')
        # Existencia negativa directa: dispara el error de stock.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -2.0)

        wizard = self.Scanner.create({'product_id': product.id})
        errors = self._finding(wizard, 'stock_negative').filtered(
            lambda f: f.severity == 'error')
        self.assertTrue(errors, 'La existencia negativa debe ser un error.')
        finding = errors[:1]
        self.assertEqual(finding.pf_cause, 'negative')
        self.assertEqual(finding.pf_problem_target, 'quants')
        self.assertEqual(finding.pf_solution_target, 'quants_adjust')
        self.assertFalse(
            finding.pf_collect_available, 'La negativa no tiene raíz agregada.')

    def test_record_state_causes(self):
        product = self._make_product('PRODUCTO SIN PROVEEDOR (DIAG)')
        wizard = self.Scanner.create({'product_id': product.id})
        findings = self._finding(wizard, 'record_state')
        no_supplier = findings.filtered(
            lambda f: f.pf_cause == 'record_no_supplier')
        self.assertTrue(no_supplier)

        archived = self._make_product('PRODUCTO ARCHIVADO (DIAG)')
        archived.write({'active': False})
        wizard = self.Scanner.create({'product_id': archived.id})
        findings = self._finding(wizard, 'record_state')
        self.assertTrue(findings.filtered(lambda f: f.pf_cause == 'record_archived'))

    def test_single_button_when_root_equals_symptom(self):
        """Archivado: síntoma y raíz son la ficha -> un solo botón (solución)."""
        archived = self._make_product('PRODUCTO UN SOLO BOTON (DIAG)')
        archived.write({'active': False})
        wizard = self.Scanner.create({'product_id': archived.id})
        finding = self._finding(wizard, 'record_state').filtered(
            lambda f: f.pf_cause == 'record_archived')[:1]
        self.assertTrue(finding)
        self.assertFalse(finding.pf_problem_available)
        self.assertTrue(finding.pf_solution_available)
        self.assertFalse(finding.pf_collect_available)

    # ------------------------------------------------------------------
    # (d) Navegación: problema (síntoma), solución (raíz) y recopilar
    # ------------------------------------------------------------------
    def test_action_open_problem_goes_to_quants(self):
        product = self._make_product('PRODUCTO SINTOMA QUANTS (DIAG)')
        self._add_stock(product, 4.0)
        self._confirm_order(product, 4.0)
        self._force_negative_free(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'flow_free_exhausted')[:1]

        action = finding.action_open_problem()
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertEqual(action['target'], 'current')
        self.assertIn(
            ('product_id', '=', product.id), action['domain'])

    def test_action_open_solution_lists_reserving_orders(self):
        product = self._make_product('PRODUCTO QUIEN RESERVA (DIAG)')
        self._add_stock(product, 4.0)
        order = self._confirm_order(product, 4.0)
        self._force_negative_free(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'flow_free_exhausted')[:1]
        self.assertTrue(finding)

        action = finding.action_open_solution()
        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(action['target'], 'current')
        self.assertEqual(list(action['domain'][0][:2]), ['id', 'in'])
        self.assertIn(
            order.id, action['domain'][0][2],
            'El pedido que reserva el producto debe aparecer en la lista.',
        )
        self.assertEqual(
            self.env['sale.order'].search_count(action['domain']), 1)
        # El alias deprecado ``action_open`` navega al SÍNTOMA (quants).
        self.assertEqual(finding.action_open()['res_model'], 'stock.quant')

    def test_action_open_collect_lists_reserving_orders(self):
        """Recopilar la raíz (free_exhausted) = lista de pedidos que reservan."""
        product = self._make_product('PRODUCTO RECOPILAR RAIZ (DIAG)')
        self._add_stock(product, 3.0)
        order = self._confirm_order(product, 3.0)
        self._force_negative_free(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'flow_free_exhausted')[:1]
        self.assertTrue(finding)
        self.assertTrue(finding.pf_collect_available)

        action = finding.action_open_collect()
        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(list(action['domain'][0][:2]), ['id', 'in'])
        self.assertIn(order.id, action['domain'][0][2])
        self.assertEqual(
            self.env['sale.order'].search_count(action['domain']), 1)

        # El helper de lectura resuelve los pedidos que reservan.
        helper_ids = pf_reserving_sale_order_ids(self.env, product)
        self.assertIn(order.id, helper_ids)

    def test_action_open_solution_quants_adjust_for_negative(self):
        product = self._make_product('PRODUCTO AJUSTE (DIAG)')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -2.0)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'stock_negative').filtered(
            lambda f: f.severity == 'error')[:1]
        self.assertTrue(finding)

        action = finding.action_open_solution()
        self.assertEqual(action['res_model'], 'stock.quant')
        self.assertTrue(action.get('context', {}).get('inventory_mode'))
        self.assertIn(
            ('product_id', '=', product.id), action['domain'])

    def test_action_open_plan_detail_opens_dialog(self):
        product = self._make_product('PRODUCTO DETALLE PLAN (DIAG)')
        self._add_stock(product, 2.0)
        self._confirm_order(product, 2.0)
        self._force_negative_free(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'flow_free_exhausted')[:1]
        action = finding.action_open_plan_detail()

        self.assertEqual(
            action['res_model'], 'printflow.product.diagnostic.finding')
        self.assertEqual(action['res_id'], finding.id)
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['view_mode'], 'form')

    def test_evidence_inherits_cause_and_labels(self):
        product = self._make_product('PRODUCTO EVIDENCIA PLAN (DIAG)')
        self._add_stock(product, 2.0)
        self._confirm_order(product, 2.0)
        self._force_negative_free(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'flow_free_exhausted')[:1]
        self.assertTrue(finding.evidence_ids)

        evidence = finding.evidence_ids[0]
        self.assertEqual(evidence.pf_cause, finding.pf_cause)
        self.assertEqual(evidence.pf_action_label, finding.pf_action_label)
        self.assertEqual(
            evidence.pf_solution_label, finding.pf_solution_label)
        self.assertEqual(
            evidence.pf_problem_label, finding.pf_problem_label)
        self.assertEqual(
            evidence.pf_collect_label, finding.pf_collect_label)
        self.assertEqual(evidence.action_open()['res_model'], 'sale.order')

    # ------------------------------------------------------------------
    # (e) Plan de acción del pedido
    # ------------------------------------------------------------------
    def test_order_plan_contention_is_plain_and_reassigns(self):
        product = self._make_product('PRODUCTO CONTENCION PLAN (DIAG)')
        self._add_stock(product, 5.0)
        self._confirm_order(product, 5.0)  # otro pedido se lleva todo.
        board = self.env['printflow.order.board'].create({
            'sale_order_id': self._confirm_order(product, 3.0).id,
        })
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

        self.assertIn('otr', wizard.root_cause_plain.lower())
        self.assertEqual(wizard.resolution_plan_button_label,
                         'Liberar y re-reservar')
        self.assertTrue(wizard.resolution_plan_steps.startswith('1.'))

    def test_order_plan_deficit_is_plain_and_buys(self):
        product = self._make_product('PRODUCTO DEFICIT PLAN (DIAG)')
        board = self.env['printflow.order.board'].create({
            'sale_order_id': self._confirm_order(product, 5.0).id,
        })
        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })

        self.assertIn('comprar o fabricar', wizard.root_cause_plain.lower())
        self.assertIn(
            wizard.resolution_plan_button_label,
            ('Generar solicitud de compra', 'Lanzar/priorizar fabricación'),
        )
