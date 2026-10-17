# -*- coding: utf-8 -*-
"""Almacén de insumos: lote elegido a un componente de MO (PrintFlow).

Custodia que el selector de lote por documento, para el hito "Almacén insumos",
reutilice el helper EXISTENTE del motor ``mrp.production._assign_lot_to_move``
(que acepta el lote ELEGIDO y solo reescribe si cambia), a través del
orquestador ``printflow.product.flow._pf_assign_lot_to_document`` (target_kind
``component_move``).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotPickerComponent(TransactionCase):
    """El lote elegido se asigna al componente vía ``_assign_lot_to_move``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
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

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _mo(self, product):
        manu_type = self.warehouse.manu_type_id
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id
                or self.stock_location.id),
        })

    # ==================================================================
    # Componente de MO: lote elegido vía ``_assign_lot_to_move``
    # ==================================================================
    def test_component_move_assigns_chosen_lot(self):
        finished = self._product('COMP TERMINADO')
        component = self._product('COMP INSUMO')
        chosen = self._lot(component, 'COMP-LOTE-ELEGIDO')
        self.env['stock.quant']._update_available_quantity(
            component, self.stock_location, 8.0, lot_id=chosen)
        mo = self._mo(finished)
        move = self.env['stock.move'].create({
            'name': component.display_name,
            'product_id': component.id,
            'product_uom_qty': 3.0,
            'product_uom': component.uom_id.id,
            'location_id': mo.location_src_id.id,
            'location_dest_id': mo.location_dest_id.id,
            'raw_material_production_id': mo.id,
        })
        move._action_confirm()

        message = self.Flow._pf_assign_lot_to_document(
            'component_move', 'stock.move', move.id, chosen,
            product=component)

        self.assertTrue(message)
        self.assertIn(chosen, move.move_line_ids.mapped('lot_id'))
        # ``_assign_lot_to_move`` marca 'picked' (consumo tomado).
        self.assertTrue(all(line.picked for line in move.move_line_ids))

    # ==================================================================
    # Lista blanca: un tipo desconocido NO se escribe
    # ==================================================================
    def test_unknown_target_kind_is_rejected(self):
        product = self._product('COMP DESCONOCIDO')
        chosen = self._lot(product, 'COMP-DESCONOCIDO-LOTE')
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.Flow._pf_assign_lot_to_document(
                'no_existe', 'stock.lot', chosen.id, chosen, product=product)
