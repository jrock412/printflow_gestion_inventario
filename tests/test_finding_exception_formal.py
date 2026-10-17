# -*- coding: utf-8 -*-
"""Excepciones FORMALES genéricas (PrintFlow · GI · F1–F5).

Custodia los criterios de aceptación del plan rev.2:

* CA-1/CA-2: autorizar una MO terminada sin lote crea UN registro
  ``printflow.finding.exception`` (modelo de GI).
* CA-3/CA-4: la autorización NO altera la MO ni toca el inventario
  (``stock.quant``/``stock.move``/``stock.lot`` idénticos antes/después).
* CA-5/CA-6: el adaptador SILENCIA el hallazgo en las superficies de GI (tray),
  y REVOCAR lo hace reaparecer.
* CA-7: idempotencia (reusa el registro, no duplica).
* CA-8: permisos (usuario sin rol de jefe de taller/admin -> ``UserError``).
* CA-9: bitácora (autorizador, fecha, motivo, origen + ``message_post``).
* CA-10: genericidad (otro ``res_model``+``res_id`` sin código nuevo).
* CA-11: extensibilidad (el registry lista el hallazgo).
* CA-12: paridad (con supresiones VACÍAS el adaptador devuelve lo del motor).
* F5: la vista de la bandeja trae el botón formal y ya NO "Abrir documento".

``TransactionCase`` hace rollback; solo toca sus propios registros.
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin


@tagged('post_install', '-at_install')
class TestFindingExceptionFormal(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Excepción Formal'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Exception = cls.env['printflow.finding.exception']
        cls.Filter = cls.env['printflow.finding.exception.filter']
        cls.Registry = cls.env['printflow.finding.exception.registry']
        cls.Health = cls.env['printflow.stock.health']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Authorize = cls.env['printflow.finding.exception.authorize']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        return self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })

    def _mo_done_without_lot(self, product):
        manu_type = self.warehouse.manu_type_id
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id
                or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id
                or self.stock_location.id),
        })
        mo.write({'state': 'done'})
        return mo

    def _stock_snapshot(self):
        """Conteos + sumas de quants/moves/lots (para CA-4)."""
        Quant = self.env['stock.quant']
        quants = Quant.search([])
        Quant.search([]).mapped('quantity')
        return {
            'quant_count': len(quants),
            'quant_qty': round(sum(quants.mapped('quantity')), 6),
            'quant_reserved': round(sum(quants.mapped('reserved_quantity')), 6),
            'move_count': self.env['stock.move'].search_count([]),
            'move_line_count': self.env['stock.move.line'].search_count([]),
            'lot_count': self.env['stock.lot'].search_count([]),
        }

    def _authorize_mo(self, mo, reason='Excepción formal del test'):
        return self.Exception._pf_authorize(
            'lot_unassigned_finished', 'mrp.production', mo.id,
            reason=reason, target_label=mo.name)

    # ==================================================================
    # CA-1/CA-2/CA-3: crea UN registro en GI y NO altera la MO
    # ==================================================================
    def test_ca1_authorize_mo_creates_single_gi_record(self):
        product = self._product('EXC CA1')
        mo = self._mo_done_without_lot(product)
        self.assertFalse(mo.lot_producing_id)

        record = self._authorize_mo(mo)

        self.assertTrue(record)
        self.assertEqual(record._name, 'printflow.finding.exception')
        found = self.Exception.search([
            ('finding_code', '=', 'lot_unassigned_finished'),
            ('target_model', '=', 'mrp.production'),
            ('target_id', '=', mo.id),
        ])
        self.assertEqual(len(found), 1)
        self.assertTrue(found.active)
        # CA-3: la MO no cambia.
        self.assertFalse(mo.lot_producing_id)

    # ==================================================================
    # CA-4: la autorización NO toca el inventario (idéntico antes/después)
    # ==================================================================
    def test_ca4_inventory_untouched_by_authorize(self):
        product = self._product('EXC CA4')
        self._pf_add_stock(product, 7.0)
        mo = self._mo_done_without_lot(product)

        before = self._stock_snapshot()
        self._authorize_mo(mo)
        after = self._stock_snapshot()
        self.assertEqual(before, after, 'Autorizar NO debe tocar el inventario.')

        # Revocar tampoco toca el inventario.
        self.Exception.search([
            ('target_id', '=', mo.id)]).action_pf_revoke()
        self.assertEqual(self._stock_snapshot(), before)

    # ==================================================================
    # CA-5/CA-6: el adaptador silencia el hallazgo; revocar lo devuelve
    # ==================================================================
    def test_ca5_ca6_filter_silences_and_revoke_restores(self):
        product = self._product('EXC CA5')
        mo = self._mo_done_without_lot(product)
        raw = self.Health._pf_lot_state(product)
        self.assertEqual(raw['state'], 'lot_unassigned_finished')

        record = self._authorize_mo(mo)
        filtered = self.Filter._pf_apply_to_lot_info(
            product, self.Health._pf_lot_state(product))
        # El MOTOR no cambia (no se toca x); el GI sí silencia.
        self.assertEqual(
            self.Health._pf_lot_state(product)['state'],
            'lot_unassigned_finished')
        self.assertEqual(filtered['state'], 'lot_ok')
        self.assertNotIn(mo.id, filtered['unassigned_mo_ids'])

        # La bandeja de GI ya NO lista la fila.
        tray = self.Tray._pf_populate(product, 'lot_unassigned_finished')
        self.assertFalse(tray, 'El hallazgo autorizado no debe generar fila.')

        # CA-6: revocar hace reaparecer el hallazgo.
        record.action_pf_revoke()
        again = self.Filter._pf_apply_to_lot_info(
            product, self.Health._pf_lot_state(product))
        self.assertEqual(again['state'], 'lot_unassigned_finished')
        tray2 = self.Tray._pf_populate(product, 'lot_unassigned_finished')
        self.assertTrue(tray2)

    # ==================================================================
    # CA-7: idempotencia (re-autorizar REUSA el registro)
    # ==================================================================
    def test_ca7_authorize_is_idempotent(self):
        product = self._product('EXC CA7')
        mo = self._mo_done_without_lot(product)
        first = self._authorize_mo(mo, reason='Primera')
        second = self._authorize_mo(mo, reason='Segunda')
        self.assertEqual(first, second)
        count = self.Exception.search_count([
            ('finding_code', '=', 'lot_unassigned_finished'),
            ('target_model', '=', 'mrp.production'),
            ('target_id', '=', mo.id)])
        self.assertEqual(count, 1)
        self.assertEqual(second.reason, 'Segunda')

    # ==================================================================
    # CA-8: permisos (usuario sin jefe de taller/admin)
    # ==================================================================
    def test_ca8_authorize_without_permission_raises(self):
        product = self._product('EXC CA8')
        mo = self._mo_done_without_lot(product)
        user = self.env['res.users'].create({
            'name': 'pf_exc_no_perm', 'login': 'pf_exc_no_perm',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('stock.group_stock_user').id])],
        })
        with self.assertRaises(UserError):
            self.Exception.with_user(user)._pf_authorize(
                'lot_unassigned_finished', 'mrp.production', mo.id,
                reason='No debería autorizarse.')
        self.assertFalse(self.Exception.search([('target_id', '=', mo.id)]))

    # ==================================================================
    # CA-9: bitácora (registro + message_post en el documento)
    # ==================================================================
    def test_ca9_audit_trail(self):
        product = self._product('EXC CA9')
        mo = self._mo_done_without_lot(product)
        record = self.Exception._pf_authorize(
            'lot_unassigned_finished', 'mrp.production', mo.id,
            reason='Motivo auditado', target_label=mo.name,
            source_model='printflow.flow.lot.tray', source_id=42,
            source_label='Origen bandeja')
        self.assertTrue(record.authorized_by_id)
        self.assertTrue(record.authorized_date)
        self.assertEqual(record.reason, 'Motivo auditado')
        self.assertEqual(record.source_model, 'printflow.flow.lot.tray')
        self.assertEqual(record.source_id, 42)
        self.assertEqual(record.source_label, 'Origen bandeja')
        # message_post (nota) en la MO.
        self.assertTrue(mo.message_ids, 'Debe dejar una nota en el documento.')

    # ==================================================================
    # CA-10: genericidad (otro res_model + res_id sin código nuevo)
    # ==================================================================
    def test_ca10_generic_other_model(self):
        product = self._product('EXC CA10')
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.env.ref(
                'stock.stock_location_customers').id,
            'partner_id': self.customer.id,
        })
        move = self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': 2.0,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.env.ref(
                'stock.stock_location_customers').id,
        })
        record = self.Exception._pf_authorize(
            'lot_missing', 'stock.move', move.id, reason='Sin lote, autorizado.')
        self.assertTrue(record)
        self.assertIn(move.id, self.Exception._pf_suppressed_targets(
            'lot_missing'))
        # El adaptador lo resta del lot_info.
        info = {
            'state': 'lot_missing', 'missing_move_ids': [move.id],
            'orphan_quant_ids': [], 'no_stock_lot_ids': [],
            'generic_lot_ids': [], 'mixed_lots': [], 'unassigned_mo_ids': [],
            'authorized_lots': [], 'shared_lots': [],
        }
        filtered = self.Filter._pf_filter_info(
            info, {'lot_missing': {move.id}})
        self.assertEqual(filtered['state'], 'lot_ok')
        self.assertNotIn(move.id, filtered['missing_move_ids'])

    # ==================================================================
    # CA-11: extensibilidad (registry lista los 5 formalismos)
    # ==================================================================
    def test_ca11_registry_lists_formalisms(self):
        supported = self.Registry._pf_supported()
        for code in ('lot_unassigned_finished', 'lot_missing', 'lot_no_stock',
                     'lot_generic', 'lot_mixed'):
            self.assertIn(code, supported)
        self.assertEqual(
            self.Registry._pf_shape('lot_unassigned_finished')['target_model'],
            'mrp.production')
        # Un código fuera de lista blanca NO admite autorización.
        self.assertFalse(self.Registry._pf_is_supported('lot_orphan_reservation'))
        with self.assertRaises(ValidationError):
            self.Exception.create({
                'finding_code': 'lot_orphan_reservation',
                'target_model': 'stock.quant', 'target_id': 1,
            })

    # ==================================================================
    # CA-12: paridad (sin supresiones, el adaptador no altera el motor)
    # ==================================================================
    def test_ca12_parity_without_suppressions(self):
        product = self._product('EXC CA12')
        self._mo_done_without_lot(product)
        raw = self.Health._pf_lot_state(product)
        filtered = self.Filter._pf_apply_to_lot_info(product, raw)
        # El estado y las listas del motor quedan EXACTOS.
        self.assertEqual(filtered, raw)
        # El mapa en lote también.
        lot_map = self.Health._pf_lot_states_map(product)
        filtered_map = self.Filter._pf_apply_to_lot_map(product, lot_map)
        self.assertEqual(filtered_map, lot_map)

    # ==================================================================
    # F5: la vista de la bandeja trae el botón formal y NO "Abrir documento"
    # ==================================================================
    def test_f5_tray_view_has_formal_authorize(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree').arch
        self.assertIn('name="action_authorize_finding"', arch)
        self.assertIn('name="action_authorize_selected_findings"', arch)
        self.assertIn('name="action_confirm_apply_correction"', arch)
        self.assertIn('name="action_confirm_create_suggested_lots"', arch)
        self.assertNotIn('string="Abrir documento"', arch)
        self.assertIn('name="document_ref"', arch)

    # ==================================================================
    # F4: el wizard genérico autoriza (y exige motivo)
    # ==================================================================
    def test_f4_authorize_wizard(self):
        product = self._product('EXC F4')
        mo = self._mo_done_without_lot(product)
        action = self.Exception._pf_authorize_action(
            'lot_unassigned_finished', 'mrp.production', mo.id,
            target_label=mo.name)
        self.assertEqual(
            action['res_model'], 'printflow.finding.exception.authorize')
        wizard = self.Authorize.browse(action['res_id'])
        self.assertEqual(wizard.finding_code, 'lot_unassigned_finished')
        with self.assertRaises(UserError):
            wizard.action_authorize()  # sin motivo
        wizard.reason = 'Motivo del wizard genérico.'
        result = wizard.action_authorize()
        self.assertEqual(result['tag'], 'display_notification')
        self.assertTrue(self.Exception.search([('target_id', '=', mo.id)]))
