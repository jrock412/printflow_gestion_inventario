# -*- coding: utf-8 -*-
"""G7 — Permisos de la salud de inventario (saneamiento global y por producto).

Un usuario sin `mrp.group_mrp_manager` no puede sanear por ninguna vía.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCleanupPermissionsGeneric(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Health = cls.env['printflow.stock.health']

    def _user(self):
        return self.env.ref('base.public_user', raise_if_not_found=False)

    def test_global_cleanup_is_guarded(self):
        user = self._user()
        if not user:
            self.skipTest('base.public_user no está disponible.')
        with self.assertRaises(UserError):
            self.Health.with_user(user)._pf_cleanup_all()
        # El administrador sí puede.
        self.Health._pf_cleanup_all()

    def test_surface_cleanup_all_is_guarded(self):
        user = self._user()
        if not user:
            self.skipTest('base.public_user no está disponible.')
        surface = self.env['printflow.inventory.health'].with_user(user)
        with self.assertRaises(UserError):
            surface.action_cleanup_all()
