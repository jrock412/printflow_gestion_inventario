# -*- coding: utf-8 -*-
"""Guardia por RIESGO de la falla huérfana (PrintFlow · Fase 1).

La bandeja guiada deja UNA sola acción con EFECTO, ``reconcile`` (SEGURO: solo
alinea el reservado con lo respaldado), que pasa por
``_pf_assert_can_reconcile`` (grupo configurable; por defecto cualquier
operador) -> un OPERADOR puede reconciliar.

La acción RIESGOSA ``release_and_reassign`` (``_pf_assert_can_clean``: jefe de
taller/administrador) YA NO pertenece a esta superficie: se retiró de la falla,
así que la bandeja no la ofrece y una llamada con esa clave NO ejecuta nada (la
lista blanca la cierra). La primitiva del motor ``_pf_reassign_by_lot`` sigue
disponible para otros flujos.

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowFailurePermissionsSplit(TransactionCase):
    """El operador reconcilia; la superficie ya no ofrece liberar/reasignar."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Tray = cls.env['printflow.flow.failure.tray']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _orphan_product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        lot = self.env['stock.lot'].create(
            {'name': '%s-LOTE' % name, 'product_id': product.id})
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, 10.0, lot_id=lot)
        self.env['stock.quant']._update_reserved_quantity(
            product, self.stock_location, 4.0, lot_id=lot)
        return product, lot

    def _operator(self, login):
        return self.env['res.users'].create({
            'name': login, 'login': login,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })

    # ==================================================================
    # 1) El OPERADOR puede reconciliar (acción segura)
    # ==================================================================
    def test_operator_can_reconcile(self):
        product, lot = self._orphan_product('PERM SPLIT OPERADOR')
        tray = self.Tray._pf_populate(None, 'lot_orphan_reservation', product)
        line = tray.line_ids[:1]
        operator = self._operator('pf_fail_operator')

        action = tray.with_user(operator).action_run(line.id, 'reconcile')
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', lot.id)])
        self.assertAlmostEqual(quant.reserved_quantity, 0.0, places=6)

    # ==================================================================
    # 2) La superficie YA NO ofrece la acción riesgosa de liberar/reasignar
    # ==================================================================
    def test_surface_no_longer_offers_reassign(self):
        product, lot = self._orphan_product('PERM SPLIT SIN REASIGNAR')
        tray = self.Tray._pf_populate(None, 'lot_orphan_reservation', product)
        line = tray.line_ids[:1]

        # La lista blanca de la falla ya no declara la clave riesgosa.
        self.assertNotIn(
            'release_and_reassign', set(line.action_ids.mapped('key')))

        # Aunque llegue la clave, la lista blanca la cierra SIN efecto.
        action = tray.action_run(line.id, 'release_and_reassign')
        self.assertEqual(action['type'], 'ir.actions.act_window_close')
        quant = self.env['stock.quant'].search([
            ('product_id', '=', product.id), ('lot_id', '=', lot.id)])
        self.assertAlmostEqual(quant.reserved_quantity, 4.0, places=6)
