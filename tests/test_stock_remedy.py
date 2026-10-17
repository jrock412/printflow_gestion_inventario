# -*- coding: utf-8 -*-
"""Clasificador estructural de remedios y ramas del playbook (PrintFlow).

Cubre T1/T2/P4 del plan:
  * ``printflow.stock.remedy`` clasifica las tres naturalezas (falta física,
    contención, anomalía) y el caso ``ok``.
  * El discriminador de anomalía exige ``has_negative_quant AND free_global>=0``
    (P4: con libre agregado negativo NO es anomalía).
  * El árbol de falta física devuelve fabricar / comprar componentes / sin BOM /
    comprar producto / ajustar.
  * El playbook conserva su comportamiento SIN ``ctx`` y ramifica CON ``ctx``.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestStockRemedyClassify(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente Remedy'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Remedy', 'supplier_rank': 1,
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.extra_location = cls.env['stock.location'].create({
            'name': 'REMEDY EXTRA',
            'location_id': cls.stock_location.id,
            'usage': 'internal',
        })
        cls.Remedy = cls.env['printflow.stock.remedy']
        cls.Playbook = cls.env['printflow.resolution.playbook']

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

    def _make_bom(self, product, components):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [
                (0, 0, {'product_id': comp.id, 'product_qty': qty})
                for comp, qty in components
            ],
        })

    # ------------------------------------------------------------------
    # T1 — Naturaleza de la traba
    # ------------------------------------------------------------------
    def test_classify_physical(self):
        product = self._product('REMEDY PHYSICAL')
        self.assertEqual(
            self.Remedy._pf_classify_reservation(product, deficit_qty=5.0),
            'physical')

    def test_classify_contention(self):
        product = self._product('REMEDY CONTENTION')
        self.assertEqual(
            self.Remedy._pf_classify_reservation(product, contention_qty=3.0),
            'contention')

    def test_classify_anomaly(self):
        product = self._product('REMEDY ANOMALY')
        # Quant con libre negativo compensado por otro con libre positivo.
        self._add_stock(product, 1.0, reserved=5.0, location=self.extra_location)
        self._add_stock(product, 10.0)
        state = self.Remedy._pf_product_reservation_state(product)
        self.assertTrue(state['has_negative_quant'])
        self.assertGreaterEqual(state['free_global'], 0.0)
        self.assertEqual(
            self.Remedy._pf_classify_reservation(product), 'anomaly')

    def test_no_anomaly_when_free_global_negative(self):
        """P4: con libre agregado negativo NO es anomalía (es falta/contención)."""
        product = self._product('REMEDY GLOBAL NEG')
        self._add_stock(product, 1.0, reserved=5.0)
        state = self.Remedy._pf_product_reservation_state(product)
        self.assertLess(state['free_global'], 0.0)
        self.assertNotEqual(
            self.Remedy._pf_classify_reservation(product), 'anomaly')

    # ------------------------------------------------------------------
    # T1 — Remedio del caso de falta física
    # ------------------------------------------------------------------
    def test_physical_manufacture(self):
        component = self._product('REMEDY COMPONENTE OK')
        self._add_stock(component, 100.0)
        product = self._product('REMEDY FABRICABLE')
        self._make_bom(product, [(component, 1.0)])
        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(product, 2.0), 'manufacture')

    def test_physical_buy_components(self):
        component = self._product('REMEDY COMPONENTE FALTA')
        # Sin stock del componente: la BOM no se puede cubrir.
        product = self._product('REMEDY FABRICABLE SIN INSUMO')
        self._make_bom(product, [(component, 1.0)])
        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(product, 2.0),
            'buy_components')

    def test_physical_no_bom(self):
        manu_rule = self.env['stock.rule'].search(
            [('action', '=', 'manufacture')], limit=1)
        self.assertTrue(manu_rule, 'El entorno debe tener una regla de fabricación.')
        product = self._product('REMEDY FABRICABLE SIN BOM')
        product.product_tmpl_id.route_ids = [(6, 0, [manu_rule.route_id.id])]
        self.assertTrue(self.Remedy._pf_is_manufacturable(product))
        self.assertFalse(self.Remedy._pf_has_bom(product))
        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(product, 1.0), 'no_bom')

    def test_physical_buy_product(self):
        product = self._product(
            'REMEDY COMPRABLE', purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        self.assertTrue(self.Remedy._pf_is_purchasable(product))
        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(product, 1.0), 'buy_product')

    def test_physical_adjust(self):
        product = self._product('REMEDY SIN RUTA')
        self.assertEqual(
            self.Remedy._pf_physical_remedy_key(product, 1.0), 'adjust')

    # ------------------------------------------------------------------
    # T2 — Playbook: sin ctx conserva; con ctx ramifica
    # ------------------------------------------------------------------
    def test_playbook_free_exhausted_without_ctx_is_unchanged(self):
        plan = self.Playbook._pf_get_plan('free_exhausted')
        self.assertEqual(
            plan['actions']['solution']['target'], 'reserving_sale_orders')
        self.assertEqual(plan['actions']['solution']['kind'], 'navigate')

    def test_playbook_free_exhausted_anomaly_branches_to_reserve(self):
        plan = self.Playbook._pf_get_plan(
            'free_exhausted', ctx={'reservation_nature': 'anomaly'})
        action = plan['actions']['solution']
        self.assertEqual(action['kind'], 'run_action')
        self.assertEqual(action['target'], 'fix_over_reservation')

    def test_playbook_free_exhausted_contention_branches_to_blocking(self):
        plan = self.Playbook._pf_get_plan(
            'free_exhausted', ctx={'reservation_nature': 'contention'})
        action = plan['actions']['solution']
        self.assertEqual(action['kind'], 'navigate')
        self.assertEqual(action['target'], 'blocking_reservations')

    def test_new_causes_contract(self):
        expected = {
            'data_anomaly': ('run_action', 'fix_over_reservation'),
            'adjust_inventory': ('navigate', 'quants_adjust'),
            'manufacture': ('open_wizard', 'create_production'),
            'manufacture_components': ('open_wizard', 'buy_components'),
            'buy_product': ('open_wizard', 'buy_product'),
            'no_bom': ('navigate', 'bom_list'),
        }
        for cause, (kind, target) in expected.items():
            plan = self.Playbook._pf_get_plan(cause)
            action = plan['actions']['solution']
            self.assertEqual(action['kind'], kind, cause)
            self.assertEqual(action['target'], target, cause)
            self.assertTrue(plan['summary'], cause)
            self.assertEqual(len(plan['steps']), 3, cause)
