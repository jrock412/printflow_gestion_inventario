# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticBomEstimate(TransactionCase):
    """B1.2: el Diagnóstico estima insumos vía BoM cuando el pedido es de
    fabricación pero NO existe Orden de Fabricación (caso "SIN ORDEN").

    También blinda el refactor B1.1: ``_raw_consumption_qty`` (MO real) debe
    devolver exactamente el mismo valor que la fórmula pura extraída
    ``_raw_consumption_qty_from_dims``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente BOM Diagnostico',
        })
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1
        )
        cls.manu_type = cls.warehouse.manu_type_id

    # ──────────────────────────────────────────────────────────────────────
    # Utilidades
    # ──────────────────────────────────────────────────────────────────────
    def _make_finished(self, name):
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        # Sin ruta de compra: el producto debe ser de FABRICACIÓN para que el
        # tablero marque procurement_type='manufacture' y se dispare la estimación.
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _make_component(self, name):
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'purchase_ok': True,
        })

    def _make_bom(self, finished, component, qty=1.0):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id,
                'product_qty': qty,
            })],
        })

    def _make_board(self, finished, qty):
        """Pedido de fabricación confirmado a la FUERZA (sin procurement/MO)."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': finished.id,
                'product_uom_qty': qty,
                'product_uom': finished.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return self.env['printflow.order.board'].create({'sale_order_id': so.id})

    def _make_mo(self, finished, bom, product_qty, dim_area=0.0, dim_height=0.0):
        return self.env['mrp.production'].create({
            'product_id': finished.id,
            'product_qty': product_qty,
            'product_uom_id': finished.uom_id.id,
            'bom_id': bom.id,
            'dim_area': dim_area,
            'dim_height': dim_height,
            'picking_type_id': self.manu_type.id,
            'location_src_id': (
                self.manu_type.default_location_src_id.id
                or self.warehouse.lot_stock_id.id
            ),
            'location_dest_id': (
                self.manu_type.default_location_dest_id.id
                or self.warehouse.lot_stock_id.id
            ),
        })

    # ──────────────────────────────────────────────────────────────────────
    # B1.2 — Estimación vía BoM
    # ──────────────────────────────────────────────────────────────────────
    def test_estimated_component_when_no_mo(self):
        """Pedido de fabricación sin MO: el insumo de la BoM se estima."""
        finished = self._make_finished('TERMINADO ESTIMADO (DIAG)')
        component = self._make_component('INSUMO ESTIMADO (DIAG)')
        self._make_bom(finished, component, qty=2.0)

        board = self._make_board(finished, qty=3.0)
        self.assertEqual(
            board.procurement_type, 'manufacture',
            'El escenario debe ser de fabricación para disparar la estimación.',
        )
        self.assertFalse(board.mrp_production_ids)

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        comp_lines = wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == component)
        self.assertEqual(
            len(comp_lines), 1,
            'La BoM debe aportar el insumo estimado al desglose.',
        )
        self.assertEqual(
            comp_lines.line_kind, 'estimated',
            'Sin MO, el insumo debe marcarse como estimado.',
        )
        # (2 insumos / 1 terminado) * 3 terminados = 6.
        self.assertAlmostEqual(comp_lines.required_qty, 6.0, places=3)
        self.assertGreater(comp_lines.deficit_qty, 0.0)

    def test_no_bom_does_not_invent_components(self):
        """Sin BoM ni MO: no se inventan insumos y se deja constancia."""
        finished = self._make_finished('TERMINADO SIN BOM (DIAG)')
        board = self._make_board(finished, qty=1.0)

        wizard = self.env['printflow.order.diagnostic.wizard'].create({
            'board_id': board.id,
        })
        self.assertFalse(
            wizard.deficit_line_ids.filtered(lambda l: l.line_kind == 'estimated'),
            'Sin BoM no debe aparecer ningún insumo estimado.',
        )
        self.assertIn(
            'sin bom', (wizard.root_cause_detail or '').lower(),
            'El diagnóstico debe explicar que no se pudo estimar por falta de BoM.',
        )

    # ──────────────────────────────────────────────────────────────────────
    # B1.1 — Paridad del refactor
    # ──────────────────────────────────────────────────────────────────────
    def test_raw_consumption_parity_with_area_rule(self):
        """MO real con regla de consumo por ÁREA: 50 cm² * 2 unidades = 100."""
        finished = self._make_finished('TERMINADO AREA (DIAG)')
        component = self._make_component('INSUMO AREA (DIAG)')
        bom = self._make_bom(finished, component, qty=1.0)
        self.env['product.consumption.rule'].create({
            'material_tmpl_id': component.product_tmpl_id.id,
            'consumption_basis': 'area',
            'applied_on_product_ids': [(6, 0, [finished.product_tmpl_id.id])],
        })
        mo = self._make_mo(finished, bom, product_qty=2.0, dim_area=50.0)
        move = mo.move_raw_ids.filtered(lambda m: m.product_id == component)
        self.assertTrue(move, 'La MO debe generar el movimiento del componente.')
        self.assertAlmostEqual(
            mo._raw_consumption_qty(mo, move), 100.0, places=3,
            msg='El refactor no debe alterar el resultado de una regla por área.',
        )

    def test_raw_consumption_parity_without_rule(self):
        """MO real SIN regla: respeta la cantidad de la BoM (3)."""
        finished = self._make_finished('TERMINADO SIN REGLA (DIAG)')
        component = self._make_component('INSUMO SIN REGLA (DIAG)')
        bom = self._make_bom(finished, component, qty=3.0)
        # Dimensiones altas: sin regla NO deben influir en el resultado.
        mo = self._make_mo(finished, bom, product_qty=1.0, dim_area=999.0)
        move = mo.move_raw_ids.filtered(lambda m: m.product_id == component)
        self.assertTrue(move)
        self.assertAlmostEqual(
            mo._raw_consumption_qty(mo, move), 3.0, places=3,
            msg='Sin regla, el consumo debe ser la cantidad original de la BoM.',
        )
