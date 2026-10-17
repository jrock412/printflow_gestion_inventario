# -*- coding: utf-8 -*-
"""P13 — Permiso de saneamiento/re-reserva (jefe de taller o administrador).

Un usuario no privilegiado no puede sanear ni re-reservar: ``UserError``.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCleanupPermissions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Remedy = cls.env['printflow.stock.remedy']

    def _restricted_user(self):
        return self.env.ref('base.public_user', raise_if_not_found=False)

    def test_superuser_can_clean(self):
        self.assertTrue(self.Remedy._pf_user_can_clean_reservations())

    def test_restricted_user_cannot_clean(self):
        user = self._restricted_user()
        if not user:
            self.skipTest('base.public_user no está disponible.')
        restricted = self.Remedy.with_user(user)
        self.assertFalse(restricted._pf_user_can_clean_reservations())
        with self.assertRaises(UserError):
            restricted._pf_assert_can_clean()

    def test_health_surface_cleanup_is_guarded(self):
        user = self._restricted_user()
        if not user:
            self.skipTest('base.public_user no está disponible.')
        # Un producto cualquiera con alerta; el permiso se valida ANTES de tocar.
        product = self.env['product.product'].create({
            'name': 'PERMISO SANEAMIENTO', 'type': 'product'})
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.env['stock.quant']._update_available_quantity(
            product, warehouse.lot_stock_id, 1.0, reserved_quantity=5.0)
        row = self.env['printflow.inventory.health'].create({
            'product_id': product.id, 'state': 'over_reserved'})
        with self.assertRaises(UserError):
            row.with_user(user).action_cleanup_reservations()
