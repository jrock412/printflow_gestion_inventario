# -*- coding: utf-8 -*-
"""MO en BORRADOR -> estado ``to_launch`` (regresión S09336).

La Orden de Fabricación existe pero está SIN LANZAR (``state='draft'``) y aún no
tiene movimientos de consumo. Antes el motor contaba cualquier MO no-``done``
como "activa", no encontraba material pendiente (``move_raw_ids`` vacío) y
devolvía ``ok``: el wizard señalaba la raíz en INVENTARIO cuando el bloqueo real
está en FABRICACIÓN.

Regla nueva (fuente única en ``printflow.order.health.engine``):
  * ``_pf_product_production`` devuelve ``to_launch`` cuando hay una MO draft, el
    pedido está en etapa de fabricación y el terminado NO está cubierto por
    existencia.
  * ``to_launch`` es ``danger`` y su falla es
    ``order_production_blocked``.
  * La precedencia canónica hace que FABRICACIÓN gane sobre el déficit de stock.
  * El motor de flujo lo clasifica como ``mo_stuck`` -> ``prioritize_mo``.
"""

from odoo.tests.common import TransactionCase, tagged


class _FakeMove:
    """Movimiento de consumo mínimo que consume ``_pf_mo_waiting_material``."""

    def __init__(self, state, quantity, demand):
        self.state = state
        self.quantity = quantity
        self.product_uom_qty = demand


class _FakeMO:
    """MO mínima para los contextos planos (estado + consumos)."""

    def __init__(self, moves=None, state='confirmed'):
        self.move_raw_ids = moves or []
        self.state = state


@tagged('post_install', '-at_install')
class TestDiagnosticMoDraftToLaunch(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env['printflow.order.health.engine']
        cls.Flow = cls.env['printflow.product.flow.diagnostic']
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente MO Draft To Launch'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _make_bom(self, product, components):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [
                (0, 0, {'product_id': comp.id, 'product_qty': qty})
                for comp, qty in components
            ],
        })

    def _force_board(self, product, qty):
        """Pedido forzado a 'sale' (sin procura) + su tarjeta."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return so, self.env['printflow.order.board'].create(
            {'sale_order_id': so.id})

    def _make_mo(self, so, product, qty=1.0):
        """MO en BORRADOR (default) vinculada al pedido, SIN movimientos."""
        group = self.env['procurement.group'].create({
            'name': '%s - Inmediata' % so.name,
            'sale_id': so.id,
            'partner_id': so.partner_id.id,
        })
        manu_type = self.warehouse.manu_type_id
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': product.uom_id.id,
            'origin': '%s - Inmediata' % so.name,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
            'source_procurement_group_id': group.id,
            'procurement_group_id': group.id,
        })

    # ------------------------------------------------------------------
    # Unitarios (funciones puras)
    # ------------------------------------------------------------------
    def test_unit_product_production_to_launch(self):
        status = self.Engine._pf_product_production({
            'active_mos': [], 'done_mos': [], 'has_draft_mo': True,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': False,
        })
        self.assertEqual(status, 'to_launch')

    def test_unit_to_launch_severity_is_danger(self):
        severity = self.Engine._pf_product_severity({
            'production_status': 'to_launch',
        })
        self.assertEqual(severity, 'danger')

    def test_unit_to_launch_failure_cause(self):
        failures = self.Engine._pf_product_failures({
            'production_status': 'to_launch',
        })
        prod = [f for f in failures if f['node'] == 'production']
        self.assertEqual(len(prod), 1)
        self.assertEqual(prod[0]['severity'], 'danger')
        self.assertEqual(prod[0]['pf_cause'], 'order_production_blocked')

    def test_unit_classify_mos_buckets(self):
        draft = _FakeMO([], state='draft')
        confirmed = _FakeMO([], state='confirmed')
        done = _FakeMO([], state='done')
        cancelled = _FakeMO([], state='cancel')
        buckets = self.Engine._pf_classify_mos(
            [draft, confirmed, done, cancelled])
        self.assertEqual(buckets['draft'], [draft])
        self.assertEqual(buckets['done'], [done])
        self.assertEqual(buckets['non_done'], [draft, confirmed])

    # ------------------------------------------------------------------
    # Contrastes: la rama to_launch NO debe dispararse de más
    # ------------------------------------------------------------------
    def test_confirmed_mo_without_material_is_not_to_launch(self):
        stuck = _FakeMO([_FakeMove('confirmed', 0.0, 5.0)])
        status = self.Engine._pf_product_production({
            'active_mos': [stuck], 'done_mos': [], 'has_draft_mo': False,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': False,
        })
        self.assertIn(status, ('material', 'late'))

    def test_confirmed_mo_with_material_is_in_progress(self):
        """MO LANZADA (confirmed) con material completo -> ``in_progress``.

        Antes caía al final en ``'ok'`` (verde "Sano") y el diagrama no sabía
        decir "OF en proceso". Ahora distingue ``to_launch`` (draft),
        ``in_progress`` (confirmed) y ``ok`` (terminada).
        """
        ready = _FakeMO([_FakeMove('assigned', 5.0, 5.0)])
        status = self.Engine._pf_product_production({
            'active_mos': [ready], 'done_mos': [], 'has_draft_mo': False,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': False,
        })
        self.assertEqual(status, 'in_progress')

    def test_unit_in_progress_is_warning_not_danger(self):
        severity = self.Engine._pf_product_severity({
            'production_status': 'in_progress',
        })
        self.assertEqual(severity, 'warning')

    def test_unit_in_progress_failure_label(self):
        failures = self.Engine._pf_product_failures({
            'production_status': 'in_progress',
        })
        prod = [f for f in failures if f['node'] == 'production']
        self.assertEqual(len(prod), 1)
        self.assertEqual(prod[0]['severity'], 'warning')
        self.assertIn('proceso', prod[0]['summary'].lower())

    def test_in_progress_is_not_a_root_cause(self):
        """``in_progress`` es un AVISO: no es nodo de quiebre."""
        root = self.Engine._pf_root_cause_node({
            'sale_status': 'ok', 'stock_status': 'ok',
            'purchase_status': 'ok', 'production_status': 'in_progress',
            'delivery_status': 'ok',
        })
        self.assertFalse(root)

    def test_design_does_not_override_material(self):
        """El ARTE no tapa la traba real de la OF (regresión S09338).

        Una MO confirmed con material pendiente dice ``material`` (no ``design``)
        y, además, el arte pendiente viaja como falla ADICIONAL.
        """
        stuck = _FakeMO([_FakeMove('confirmed', 0.0, 5.0)])
        status = self.Engine._pf_product_production({
            'active_mos': [stuck], 'done_mos': [], 'has_draft_mo': False,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': False, 'design_pending': True,
        })
        self.assertEqual(status, 'material')
        failures = self.Engine._pf_product_failures({
            'production_status': status, 'design_pending': True,
        })
        summaries = [
            f['summary'] for f in failures if f['node'] == 'production']
        self.assertIn('Falta material', summaries)
        self.assertIn('Arte pendiente', summaries)

    def test_design_does_not_override_to_launch(self):
        status = self.Engine._pf_product_production({
            'active_mos': [], 'done_mos': [], 'has_draft_mo': True,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': False, 'design_pending': True,
        })
        self.assertEqual(status, 'to_launch')

    def test_design_is_status_only_when_of_is_clean(self):
        """Sin ninguna traba de OF, el arte sí es el estado (compatibilidad).

        Con la OF TERMINADA y arte pendiente, Fabricación reporta ``design``
        (no ``in_progress``); es el caso heredado que se conserva.
        """
        done = _FakeMO([], state='done')
        status = self.Engine._pf_product_production({
            'active_mos': [], 'done_mos': [done], 'has_draft_mo': False,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': False, 'design_pending': True,
        })
        self.assertEqual(status, 'design')

    def test_launched_mo_helper(self):
        draft = _FakeMO([], state='draft')
        progress = _FakeMO([], state='progress')
        confirmed = _FakeMO([], state='confirmed')
        done = _FakeMO([], state='done')
        self.assertFalse(self.Engine._pf_has_launched_mo([draft]))
        self.assertFalse(self.Engine._pf_has_launched_mo([draft, done]))
        self.assertTrue(self.Engine._pf_has_launched_mo([draft, confirmed]))
        self.assertTrue(self.Engine._pf_has_launched_mo([progress]))

    def test_draft_mo_covered_by_stock_is_not_to_launch(self):
        status = self.Engine._pf_product_production({
            'active_mos': [], 'done_mos': [], 'has_draft_mo': True,
            'in_production_stage': True, 'is_manufacturable': True,
            'is_stock_covered': True,
        })
        self.assertNotEqual(status, 'to_launch')

    def test_draft_mo_outside_production_stage_is_not_to_launch(self):
        status = self.Engine._pf_product_production({
            'active_mos': [], 'done_mos': [], 'has_draft_mo': True,
            'in_production_stage': False, 'is_manufacturable': True,
            'is_stock_covered': False,
        })
        self.assertNotEqual(status, 'to_launch')

    def test_order_waiting_material_is_not_to_launch(self):
        health = self.Engine._pf_order_health({
            'procurement_type': 'manufacture',
            'state': 'waiting_material',
            'has_production': True,
            'has_draft_mo': True,
            'has_waiting_material': True,
        })
        self.assertEqual(health['health_production'], 'material')

    def test_order_in_production_with_draft_mo_is_to_launch(self):
        health = self.Engine._pf_order_health({
            'procurement_type': 'manufacture',
            'state': 'in_production',
            'has_production': True,
            'has_draft_mo': True,
        })
        self.assertEqual(health['health_production'], 'to_launch')
        self.assertEqual(health['health_severity'], 'danger')

    # ------------------------------------------------------------------
    # S09336 sintético: tablero real con MO draft sin movimientos
    # ------------------------------------------------------------------
    def test_s09336_draft_mo_is_root_production(self):
        component = self._product('S09336 COMPONENTE')
        self._add_stock(component, 50.0)
        finished = self._product('S09336 CORTES LILA', purchase_ok=False)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]

        # La MO se crea en BORRADOR y SIN BoM todavía: queda sin movimientos de
        # consumo, como en S09336 (``move_raw_ids = []``).
        so, board = self._force_board(finished, 3.0)
        mo = self._make_mo(so, finished, qty=3.0)
        self.assertEqual(mo.state, 'draft')
        self.assertFalse(mo.move_raw_ids, 'La MO draft no debe tener consumos.')

        # Luego se define la BoM: el producto es fabricable, pero la MO ya existe
        # en borrador y sigue sin consumos (el bloqueo real es "sin lanzar").
        self._make_bom(finished, [(component, 1.0)])

        board._sync_mrp_productions_from_sales(so)
        self.assertIn(mo, board.mrp_production_ids)

        # El tablero sigue marcando el bloqueo duro ('to_launch'); el wizard
        # AFINA la causa: la OF no tiene insumos cargados (raíz ALMACÉN INSUMOS).
        self.assertEqual(board.state, 'in_production')
        self.assertEqual(board.health_production, 'to_launch')
        self.assertEqual(board.health_severity, 'danger')

        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})
        self.assertEqual(wizard.production_status, 'no_supply')
        self.assertEqual(wizard.root_cause_node, 'supply')
        self.assertIn('insumos', (wizard.production_summary or '').lower())

        line = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == finished)[:1]
        self.assertTrue(line, 'La línea del terminado debe existir.')
        self.assertEqual(line.production_status, 'no_supply')
        self.assertEqual(line.root_cause_node, 'supply')
        # Veredicto de INSUMOS desacoplado del de Fabricación (fuente única).
        self.assertTrue(line.has_mo_without_materials)
        self.assertEqual(line.flow_supply_status, 'no_supply')
        wizard.write({'focus_line_id': line.id})
        self.assertEqual(wizard.focus_supply_status, 'no_supply')
        prod_failure = line.failure_ids.filtered(
            lambda f: f.node == 'supply')[:1]
        self.assertTrue(
            prod_failure, 'Debe existir la falla del almacén de insumos.')
        self.assertEqual(prod_failure.severity, 'danger')
        self.assertEqual(prod_failure.pf_cause, 'mo_without_materials')

    def test_s09336_flow_verdict_prioritizes_mo(self):
        verdict = self.Flow._pf_flow_verdict({
            'is_finished': True, 'sale_status': 'ok', 'purchase_ok': True,
            'is_manufacturable': True, 'in_production_stage': True,
            'has_draft_mo': True, 'is_stock_covered': False,
            'active_mos': [], 'done_mos': [],
            # El flag lo define el llamador (default False desde E6).
            'mo_stuck': True,
        })
        self.assertEqual(verdict['production_status'], 'to_launch')
        self.assertEqual(verdict['root_cause_node'], 'production')
        self.assertEqual(verdict['cause'], 'mo_stuck')
        self.assertEqual(verdict['remedy_key'], 'prioritize_mo')
