# -*- coding: utf-8 -*-
"""El Centro de Salud v1 (form + notebook) quedó RETIRADO (PrintFlow).

Verifica que:
  * el modelo ``printflow.health.center`` NO existe en el registry;
  * su menú/acción/vistas ya no están;
  * los campos puente ``center_id`` / ``pf_selected`` desaparecieron;
  * los PUNTOS DE ENTRADA HISTÓRICOS siguen intactos.
"""

from odoo.tests.common import TransactionCase, tagged

_MODULE = 'x_product_dimensional_pricing'
# Los PUNTOS DE ENTRADA vivos de la bandeja viven ahora en GI.
_GI_MODULE = 'printflow_gestion_inventario'

_HISTORICAL_XMLIDS = (
    'action_server_printflow_inventory_health',
    'action_server_printflow_cleanup_all_reservations',
    'action_server_printflow_open_orphan_moves',
    'action_server_printflow_purge_orphan_moves',
    'menu_printflow_inventory_health',
    'menu_printflow_maintenance',
)


@tagged('post_install', '-at_install')
class TestHealthCenterRetired(TransactionCase):

    def test_model_is_retired(self):
        self.assertNotIn(
            'printflow.health.center', self.env,
            'El modelo del Centro v1 debe estar eliminado.')

    def test_menu_and_action_are_retired(self):
        for name in ('menu_printflow_health_center',
                     'action_server_printflow_health_center',
                     'printflow_health_center_view_form',
                     'printflow_health_center_view_list'):
            record = self.env.ref(
                '%s.%s' % (_MODULE, name), raise_if_not_found=False)
            self.assertFalse(
                record, 'El registro del Centro v1 %r no debe existir.' % name)

    def test_bridge_fields_removed(self):
        health_fields = self.env['printflow.inventory.health']._fields
        pending_fields = self.env['printflow.node.pending.line']._fields
        self.assertNotIn('center_id', health_fields)
        self.assertNotIn('center_id', pending_fields)
        self.assertNotIn('pf_selected', pending_fields)

    def test_historical_entry_points_intact(self):
        for name in _HISTORICAL_XMLIDS:
            record = self.env.ref(
                '%s.%s' % (_GI_MODULE, name), raise_if_not_found=False)
            self.assertTrue(
                record, 'El punto de entrada histórico %r debe existir.' % name)
        self.assertTrue(hasattr(
            self.env['printflow.inventory.health'], '_pf_open_health'))
        self.assertTrue(hasattr(
            self.env['printflow.inventory.health'], '_pf_populate'))
