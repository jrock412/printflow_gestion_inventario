# -*- coding: utf-8 -*-
"""E1 — Atribución de componentes en el chequeo de kits (PrintFlow).

El chequeo ``kit_no_own_stock`` (``diagnostic/models/checks/check_kit.py``) debe
señalar al COMPONENTE faltante, NUNCA al kit. La confusión clásica viene de
``mrp.bom.explode``: allí ``data['product']`` es el producto PADRE (el kit o el
sub-kit), no el componente; el componente SIEMPRE es ``bom_line.product_id``.
El chequeo delega en ``printflow.stock.remedy._pf_missing_components`` (fuente
única del desglose de BOM), que aplica esa regla.

Cubre:
  (a) kit con 2 componentes y uno sin libre suficiente -> ``warning`` cuyas
      evidencias apuntan al COMPONENTE (``product_id`` = id del componente) y
      NUNCA al kit;
  (b) kit con quants propios Y un componente faltante -> igual emite el warning
      del componente (no se salta la evaluación por tener quants);
  (c) kit con quants propios y componentes suficientes -> sin faltantes (``ok``);
  (d) kit anidado (sub-kit ``phantom``) -> ``explode`` reporta la hoja y la
      evidencia NO apunta ni al kit padre ni al sub-kit intermedio.

Solo lectura: el escáner no modifica datos de negocio.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestDiagnosticKitComponents(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Diagnóstico Kit'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Scanner = cls.env['printflow.product.diagnostic.wizard']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_phantom_bom(self, product, components):
        """BOM ``phantom`` (kit) del producto con sus componentes.

        :param components: lista de ``(product.product, qty)``.
        """
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'type': 'phantom',
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'bom_line_ids': [
                (0, 0, {'product_id': comp.id, 'product_qty': qty})
                for comp, qty in components
            ],
        })

    def _kit_finding(self, kit):
        """Escanea el kit y devuelve su hallazgo ``kit_no_own_stock``."""
        wizard = self.Scanner.create({'product_id': kit.id})
        return wizard.finding_ids.filtered(
            lambda f: f.check_code == 'kit_no_own_stock')[:1]

    def _evidence_products(self, finding):
        """Productos referenciados por las evidencias del hallazgo."""
        return finding.evidence_ids.mapped('product_id')

    # ------------------------------------------------------------------
    # (a) El componente faltante es la evidencia; el kit NO
    # ------------------------------------------------------------------
    def test_component_shortage_points_to_component_not_kit(self):
        kit = self._pf_product('KIT E1 DOS COMPONENTES')
        comp_ok = self._pf_product('KIT E1 COMPONENTE OK')
        comp_bad = self._pf_product('KIT E1 COMPONENTE FALTA')
        self._pf_add_stock(comp_ok, 10.0)
        # comp_bad sin stock: su libre (0) no cubre lo requerido (2).
        self._make_phantom_bom(kit, [(comp_ok, 1.0), (comp_bad, 2.0)])

        finding = self._kit_finding(kit)
        self.assertTrue(finding, 'Debe emitirse el hallazgo del kit.')
        self.assertEqual(finding.severity, 'warning')
        self.assertEqual(finding.record_count, 1)

        evidence_products = self._evidence_products(finding)
        self.assertIn(
            comp_bad, evidence_products,
            'La evidencia debe apuntar al componente sin disponibilidad.')
        self.assertNotIn(
            kit, evidence_products,
            'La evidencia NUNCA debe apuntar al kit (data["product"] es el padre).')

        # La evidencia del faltante es un componente recolectable y navegable.
        component_evidence = finding.evidence_ids.filtered(
            lambda e: e.product_id == comp_bad)[:1]
        self.assertEqual(component_evidence.causante_type, 'component')
        self.assertTrue(component_evidence.collectible)
        self.assertEqual(component_evidence.res_model, 'product.product')
        self.assertEqual(component_evidence.res_id, comp_bad.id)
        self.assertEqual(component_evidence.nav_kind, 'product')

    # ------------------------------------------------------------------
    # (b) Tener quants propios NO oculta el faltante del componente
    # ------------------------------------------------------------------
    def test_kit_with_own_quants_still_reports_missing_component(self):
        kit = self._pf_product('KIT E1 CON QUANTS PROPIOS')
        comp_ok = self._pf_product('KIT E1 QUANTS COMPONENTE OK')
        comp_bad = self._pf_product('KIT E1 QUANTS COMPONENTE FALTA')
        self._pf_add_stock(kit, 5.0)  # el kit tiene quants propios
        self._pf_add_stock(comp_ok, 10.0)
        self._make_phantom_bom(kit, [(comp_ok, 1.0), (comp_bad, 2.0)])

        finding = self._kit_finding(kit)
        self.assertEqual(
            finding.severity, 'warning',
            'Tener quants propios no debe saltarse la evaluación de componentes.')
        self.assertEqual(finding.record_count, 1)
        self.assertIn(comp_bad, self._evidence_products(finding))
        self.assertNotIn(kit, self._evidence_products(finding))

    # ------------------------------------------------------------------
    # (c) Kit con quants propios y componentes suficientes -> ok
    # ------------------------------------------------------------------
    def test_kit_with_own_quants_and_enough_components_is_ok(self):
        kit = self._pf_product('KIT E1 SUFICIENTE')
        comp_a = self._pf_product('KIT E1 SUFICIENTE A')
        comp_b = self._pf_product('KIT E1 SUFICIENTE B')
        self._pf_add_stock(kit, 3.0)
        self._pf_add_stock(comp_a, 10.0)
        self._pf_add_stock(comp_b, 10.0)
        self._make_phantom_bom(kit, [(comp_a, 1.0), (comp_b, 1.0)])

        finding = self._kit_finding(kit)
        self.assertEqual(finding.severity, 'ok')
        self.assertEqual(finding.record_count, 0)
        self.assertFalse(
            finding.evidence_ids.filtered(
                lambda e: e.causante_type == 'component'),
            'Sin faltantes no debe haber evidencias de componente.')

    # ------------------------------------------------------------------
    # (c bis) Kit SIN quants propios y componentes suficientes -> info
    # ------------------------------------------------------------------
    def test_kit_without_own_quants_and_enough_components_is_info(self):
        kit = self._pf_product('KIT E1 SIN QUANTS SUFICIENTE')
        comp_a = self._pf_product('KIT E1 SIN QUANTS A')
        comp_b = self._pf_product('KIT E1 SIN QUANTS B')
        self._pf_add_stock(comp_a, 10.0)
        self._pf_add_stock(comp_b, 10.0)
        self._make_phantom_bom(kit, [(comp_a, 1.0), (comp_b, 1.0)])

        finding = self._kit_finding(kit)
        self.assertEqual(finding.severity, 'info')
        self.assertEqual(finding.record_count, 0)

    # ------------------------------------------------------------------
    # (d) Kit anidado: explode reporta la HOJA, no el sub-kit
    # ------------------------------------------------------------------
    def test_nested_kit_reports_leaf_component(self):
        leaf_bad = self._pf_product('KIT E1 HOJA FALTA')
        sub_kit = self._pf_product('SUB-KIT E1')
        self._make_phantom_bom(sub_kit, [(leaf_bad, 1.0)])

        parent = self._pf_product('KIT E1 ANIDADO')
        comp_ok = self._pf_product('KIT E1 ANIDADO COMPONENTE OK')
        self._pf_add_stock(comp_ok, 10.0)
        self._make_phantom_bom(parent, [(comp_ok, 1.0), (sub_kit, 1.0)])

        finding = self._kit_finding(parent)
        self.assertEqual(finding.severity, 'warning')

        evidence_products = self._evidence_products(finding)
        self.assertIn(
            leaf_bad, evidence_products,
            'El explode debe reportar el componente hoja del sub-kit.')
        self.assertNotIn(
            parent, evidence_products,
            'La evidencia nunca apunta al kit padre.')
        self.assertNotIn(
            sub_kit, evidence_products,
            'La evidencia apunta a la hoja, no al sub-kit intermedio.')
