# -*- coding: utf-8 -*-
"""Autorización EN BLOQUE de lotes desde la bandeja (PrintFlow).

El botón de ACCIÓN SOBRE LA SELECCIÓN ("Autorizar excepción") abre el wizard
``printflow.flow.lot.exception.authorize.bulk`` para autorizar con UN motivo los
lotes de todas las filas seleccionadas (una vez por lote DISTINTO), omitiendo las
ya autorizadas o no autorizables. Requiere jefe de taller/administrador.

``TransactionCase`` hace rollback; crea sus propios registros.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotTrayAuthorizeBulk(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Bulk = cls.env['printflow.flow.lot.exception.authorize.bulk']
        cls.Health = cls.env['printflow.stock.health']
        cls.Exception = cls.env['printflow.lot.exception']

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

    def _user(self, login, groups):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [group.id for group in groups])],
        })

    def _row(self, product, kind, lot=None):
        return self.Tray.create({
            'product_id': product.id,
            'kind': kind,
            'lot_id': lot.id if lot else False,
        })

    # ==================================================================
    # Selección mixta: autoriza los pendientes (1 vez por lote distinto)
    # ==================================================================
    def test_bulk_authorizes_pending_lots(self):
        product = self._product('BULK TRAY')
        lot_a = self._lot(product, 'BULK-A')
        lot_b = self._lot(product, 'BULK-B')
        lot_c = self._lot(product, 'BULK-C')
        # lot_c ya autorizado -> se OMITE.
        self.Health._pf_authorize_lot_exception(lot_c, reason='Ya autorizado.')

        row_a = self._row(product, 'mixed_lot', lot_a)
        row_b = self._row(product, 'generic_lot', lot_b)
        row_b2 = self._row(product, 'generic_lot', lot_b)  # MISMO lote que row_b
        row_c = self._row(product, 'no_stock_lot', lot_c)  # ya autorizado
        row_d = self._row(product, 'missing_move')         # sin lote
        selection = row_a | row_b | row_b2 | row_c | row_d

        action = selection.action_authorize_selected()
        self.assertEqual(
            action['res_model'], 'printflow.flow.lot.exception.authorize.bulk')
        wizard = self.Bulk.browse(action['res_id'])
        # Lotes DISTINTOS pendientes: a y b (b repetido -> una vez).
        self.assertEqual(set(wizard.lot_ids.ids), {lot_a.id, lot_b.id})
        # Omitidos: lot_c (ya autorizado) y row_d (no autorizable) -> 2 filas.
        self.assertEqual(wizard.skipped, 2)

        wizard.reason = 'Autorización masiva de prueba.'
        result = wizard.action_authorize()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        self.assertIn(
            '2 lote(s) autorizado(s)', result['params']['message'])

        self.assertTrue(self.Exception.search_count(
            [('lot_id', '=', lot_a.id), ('active', '=', True)]))
        self.assertTrue(self.Exception.search_count(
            [('lot_id', '=', lot_b.id), ('active', '=', True)]))
        # El ya autorizado NO se duplica (unique por lot_id + company_id).
        self.assertEqual(self.Exception.search_count(
            [('lot_id', '=', lot_c.id)]), 1)

    # ==================================================================
    # Todas omitidas -> notifica SIN abrir el wizard
    # ==================================================================
    def test_all_skipped_notifies_without_wizard(self):
        product = self._product('BULK SKIP')
        lot_c = self._lot(product, 'BULK-SKIP-C')
        self.Health._pf_authorize_lot_exception(lot_c, reason='Ya autorizado.')

        row_c = self._row(product, 'no_stock_lot', lot_c)
        row_d = self._row(product, 'missing_move')
        action = (row_c | row_d).action_authorize_selected()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(self.Bulk.search_count([]), 0)

    # ==================================================================
    # El motivo es obligatorio
    # ==================================================================
    def test_reason_is_mandatory(self):
        product = self._product('BULK MOTIVO')
        lot_a = self._lot(product, 'BULK-MOTIVO-A')
        row_a = self._row(product, 'mixed_lot', lot_a)

        action = row_a.action_authorize_selected()
        wizard = self.Bulk.browse(action['res_id'])
        self.assertFalse(wizard.reason)
        with self.assertRaises(UserError):
            wizard.action_authorize()
        self.assertFalse(self.Exception.search_count([('lot_id', '=', lot_a.id)]))

    # ==================================================================
    # Usuario sin permiso -> UserError (no autoriza nada)
    # ==================================================================
    def test_permission_denied(self):
        product = self._product('BULK PERMISO')
        lot_a = self._lot(product, 'BULK-PERMISO-A')
        row_a = self._row(product, 'mixed_lot', lot_a)
        user = self._user(
            'pf_bulk_no_perm', [self.env.ref('base.group_user')])

        with self.assertRaises(UserError):
            row_a.with_user(user).action_authorize_selected()
        self.assertFalse(self.Exception.search_count([('lot_id', '=', lot_a.id)]))

    # ==================================================================
    # Guardia de vista: acción de selección + botón de fila conservado
    # ==================================================================
    def test_view_has_selection_action(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree').arch
        self.assertIn('name="action_authorize_selected"', arch)
        self.assertIn('display="selection"', arch)
        self.assertIn('name="action_authorize_lot"', arch)
