# -*- coding: utf-8 -*-
"""Bandeja de Resolución (v1, solo lectura) del escáner de producto.

Cubre:
  (a) los causantes de ``bom_archive_blocked`` salen recolectables
      (``collectible=True`` / ``causante_type='sale_order'``) y con datos;
  (b) ``finding.action_open_resolution_tray`` y
      ``wizard.action_open_resolution_tray`` devuelven un dominio correcto;
  (c) ``evidence.action_open_selected`` navega (un solo modelo) o avisa
      (modelos mixtos), SIN modificar datos;
  (d) ``evidence.action_back_to_scanner`` reabre el escáner.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticResolutionTray(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Bandeja Resolucion',
        })
        cls.Scanner = cls.env['printflow.product.diagnostic.wizard']
        cls.Evidence = cls.env['printflow.product.diagnostic.evidence']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
        })

    def _make_phantom_bom(self, product):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'type': 'phantom',
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
        })

    def _make_sale_line(self, product, qty=1.0):
        """Pedido forzado a 'sale' con una línea del producto (patrón FASE 1).

        Se crea un movimiento en borrador vinculado a la línea porque una venta
        real siempre lo tiene y el core (``_ensure_bom_is_free``) exige uno NO
        cancelado para considerar la línea bloqueante.
        """
        sale_order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        sale_order.write({'state': 'sale'})
        line = sale_order.order_line[:1]
        self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'sale_line_id': line.id,
            'location_id': self.env['stock.location'].search(
                [('usage', '=', 'internal')], limit=1).id,
            'location_dest_id': self.env['stock.location'].search(
                [('usage', '=', 'customer')], limit=1).id,
        })
        return line

    def _blocked_scanner(self):
        """Escáner con una BOM kit bloqueada por DOS pedidos pendientes."""
        product = self._make_product('KIT BANDEJA (DIAG)')
        bom = self._make_phantom_bom(product)
        line_a = self._make_sale_line(product, qty=3.0)
        line_b = self._make_sale_line(product, qty=5.0)
        wizard = self.Scanner.create({'product_id': product.id})
        finding = wizard.finding_ids.filtered(
            lambda f: f.check_code == 'bom_archive_blocked')[:1]
        return wizard, finding, bom, line_a, line_b

    # ------------------------------------------------------------------
    # (a) Causantes recolectables del bloqueo de archivado
    # ------------------------------------------------------------------
    def test_bom_archive_blocked_causantes_are_collectible_sale_orders(self):
        _wizard, finding, _bom, line_a, line_b = self._blocked_scanner()
        self.assertTrue(finding, 'Debe existir el hallazgo de archivado bloqueado.')

        collectible = finding.evidence_ids.filtered('collectible')
        self.assertEqual(
            len(collectible), 2,
            'Los dos pedidos bloqueantes deben ser causantes recolectables.',
        )
        for evidence in collectible:
            self.assertEqual(evidence.causante_type, 'sale_order')
            self.assertEqual(evidence.action_kind, 'none')
            self.assertTrue(evidence.ref_name)
            self.assertEqual(evidence.partner_name, self.customer.display_name)
            self.assertTrue(evidence.state_label.startswith('Facturación:'))
        self.assertEqual(
            set(collectible.mapped('sale_order_id')),
            {line_a.order_id, line_b.order_id},
            'Ambos pedidos bloqueantes deben figurar como causantes.',
        )

        # La BOM kit es evidencia secundaria: NO entra en la bandeja.
        bom_evidences = finding.evidence_ids.filtered(
            lambda e: e.causante_type == 'bom')
        self.assertTrue(bom_evidences)
        self.assertFalse(
            any(bom_evidences.mapped('collectible')),
            'La BOM a archivar no debe mezclarse como causante recolectable.',
        )

    # ------------------------------------------------------------------
    # (b) Dominio de la bandeja desde hallazgo y desde escáner
    # ------------------------------------------------------------------
    def test_finding_action_domain_filters_by_finding(self):
        wizard, finding, _bom, _a, _b = self._blocked_scanner()
        action = finding.action_open_resolution_tray()

        self.assertEqual(
            action['res_model'], 'printflow.product.diagnostic.evidence')
        self.assertEqual(action['target'], 'current')
        self.assertIn(('collectible', '=', True), action['domain'])
        self.assertIn(('finding_id', '=', finding.id), action['domain'])
        self.assertEqual(action['context'].get('pf_scanner_id'), wizard.id)

        # El dominio devuelve exactamente los causantes de ese hallazgo.
        found = self.Evidence.search(action['domain'])
        self.assertEqual(found, finding.evidence_ids.filtered('collectible'))

    def test_wizard_action_domain_filters_by_scanner(self):
        wizard, _finding, _bom, _a, _b = self._blocked_scanner()
        action = wizard.action_open_resolution_tray()

        self.assertEqual(
            action['res_model'], 'printflow.product.diagnostic.evidence')
        self.assertEqual(action['target'], 'current')
        self.assertIn(('collectible', '=', True), action['domain'])
        self.assertIn(('scanner_id', '=', wizard.id), action['domain'])
        self.assertEqual(action['context'].get('pf_scanner_id'), wizard.id)

    # ------------------------------------------------------------------
    # (c) Abrir seleccionados: navega o avisa, nunca modifica
    # ------------------------------------------------------------------
    def test_open_selected_single_model_opens_filtered_list(self):
        _wizard, finding, _bom, line_a, line_b = self._blocked_scanner()
        evidences = finding.evidence_ids.filtered('collectible')

        action = evidences.action_open_selected()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(action['target'], 'current')
        self.assertEqual(list(action['domain'][0][:2]), ['id', 'in'])
        self.assertEqual(
            set(action['domain'][0][2]),
            {line_a.order_id.id, line_b.order_id.id},
        )
        self.assertEqual(
            self.env['sale.order'].search_count(action['domain']), 2)

    def test_open_selected_mixed_models_shows_notification(self):
        _wizard, finding, bom, _a, _b = self._blocked_scanner()
        self.Evidence.create({
            'finding_id': finding.id,
            'label': 'BOM mixta (DIAG)',
            'causante_type': 'bom',
            'collectible': True,
            'res_model': 'mrp.bom',
            'res_id': bom.id,
        })
        evidences = finding.evidence_ids.filtered('collectible')

        action = evidences.action_open_selected()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertNotIn(
            'res_model', action,
            'La selección mixta NO debe abrir una acción de ventana.',
        )

    def test_open_selected_without_targets_shows_notification(self):
        _wizard, finding, _bom, _a, _b = self._blocked_scanner()
        no_target = self.Evidence.create({
            'finding_id': finding.id,
            'label': 'Sin destino (DIAG)',
            'causante_type': 'other',
            'collectible': True,
        })
        action = no_target.action_open_selected()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')

    # ------------------------------------------------------------------
    # (d) Volver al diagnóstico
    # ------------------------------------------------------------------
    def test_back_to_scanner_reopens_wizard_from_context(self):
        wizard, finding, _bom, _a, _b = self._blocked_scanner()
        evidences = finding.evidence_ids.filtered('collectible')

        action = evidences.with_context(
            pf_scanner_id=wizard.id).action_back_to_scanner()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(
            action['res_model'], 'printflow.product.diagnostic.wizard')
        self.assertEqual(action['res_id'], wizard.id)
        self.assertEqual(action['target'], 'current')

    def test_back_to_scanner_falls_back_to_evidence_scanner(self):
        wizard, finding, _bom, _a, _b = self._blocked_scanner()
        evidences = finding.evidence_ids.filtered('collectible')

        action = evidences.action_back_to_scanner()

        self.assertEqual(action['res_model'],
                         'printflow.product.diagnostic.wizard')
        self.assertEqual(action['res_id'], wizard.id)

    # ------------------------------------------------------------------
    # (e) Contrato extendido de 3 acciones sobre el hallazgo real
    # ------------------------------------------------------------------
    def test_blocked_finding_exposes_three_actions(self):
        """Archivado bloqueado: síntoma (BOM), raíz (guiar) y recopilar."""
        _wizard, finding, _bom, _a, _b = self._blocked_scanner()
        self.assertTrue(finding.pf_problem_available)
        self.assertTrue(finding.pf_solution_available)
        self.assertTrue(finding.pf_collect_available)

        self.assertEqual(finding.pf_problem_target, 'bom')
        self.assertEqual(finding.pf_action_kind, 'navigate')
        self.assertEqual(finding.pf_solution_target, 'sale_orders')
        self.assertEqual(finding.pf_collect_target, 'collect_tray')
        self.assertEqual(
            finding.pf_action_target, finding.pf_solution_target)
        # Etiquetas distintas por botón.
        labels = {
            finding.pf_problem_label,
            finding.pf_solution_label,
            finding.pf_collect_label,
        }
        self.assertEqual(len(labels), 3)

    def test_finding_collect_opens_resolution_tray(self):
        """Recopilar en un hallazgo con raíz agregada abre la Bandeja."""
        _wizard, finding, _bom, _a, _b = self._blocked_scanner()
        action = finding.action_open_collect()

        self.assertEqual(
            action['res_model'], 'printflow.product.diagnostic.evidence')
        self.assertIn(('collectible', '=', True), action['domain'])
        self.assertIn(('finding_id', '=', finding.id), action['domain'])
        self.assertEqual(
            self.Evidence.search_count(action['domain']), 2)

    # ------------------------------------------------------------------
    # (g) FASE 5: la bandeja del PEDIDO comparte el esquema del mixin.
    # ------------------------------------------------------------------
    def test_order_evidence_shares_causante_schema(self):
        order_evidence = self.env['printflow.order.diagnostic.evidence']
        for field_name in (
            'label', 'detail', 'nav_kind', 'causante_type', 'collectible',
            'ref_name', 'partner_name', 'qty', 'qty_secondary', 'state_label',
            'date_ref', 'action_kind', 'origin_group', 'purchase_order_id',
            'picking_id',
        ):
            self.assertIn(field_name, order_evidence._fields)
        self.assertEqual(
            order_evidence._fields['causante_type'].selection,
            self.Evidence._fields['causante_type'].selection,
        )

    # ------------------------------------------------------------------
    # (f) Regresión de layout: ningún campo Text como columna del árbol
    # ------------------------------------------------------------------
    def test_trees_have_no_text_column(self):
        for xmlid in (
            'printflow_gestion_inventario'
            '.printflow_product_diagnostic_wizard_view_form',
            'printflow_gestion_inventario'
            '.printflow_product_resolution_tray_view_tree',
        ):
            view = self.env.ref(xmlid)
            combined = view._get_combined_arch()
            self.assertFalse(
                combined.xpath("//field[@name='pf_plan_steps']"),
                '%s no debe tener pf_plan_steps como columna.' % xmlid)
