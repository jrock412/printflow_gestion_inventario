# -*- coding: utf-8 -*-
"""Fase 7: permisos (Q11), aislamiento y smoke de los tableros (PrintFlow).

Custodia:
  * los 3 modelos de tablero tienen ACL ``base.group_user`` (1,1,1,1);
  * un usuario de negocio (``base.group_user`` + inventario + fabricación) puede
    ABRIR/POBLAR los 3 tableros: catálogo, pendientes y diagrama de producto;
  * la validación masiva de entregas corre SIN ``sudo`` (Q11): el método no
    escala privilegios al validar;
  * los TransientModel están AISLADOS por usuario (``create_uid``).

``TransactionCase`` revierte todo al terminar.
"""

from unittest import mock

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_MODULE = 'x_product_dimensional_pricing'

# Modelos de tablero nuevos (Fase 5/6/4b).
BOARD_MODELS = (
    'printflow.inventory.catalog',
    'printflow.node.pending.line',
    'printflow.product.flow',
)


@tagged('post_install', '-at_install')
class TestPhase7BoardPermissions(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Fase 7 Permisos'})
        # Usuario de negocio: base.group_user + los grupos que los tableros
        # necesitan para LEER con permisos del usuario (BoM/inventario).
        cls.operator = cls.env['res.users'].create({
            'name': 'PrintFlow Fase7 Operador',
            'login': 'pf_fase7_operator',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('stock.group_stock_user').id,
                cls.env.ref('mrp.group_mrp_user').id,
            ])],
        })
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param(_MODULE + '.pf_node_pending_enabled', '1')
        ICP.set_param(
            _MODULE + '.pf_node_pending_nodes',
            'purchase,receipt,production,delivery,sale')
        ICP.set_param(_MODULE + '.pf_node_pending_limit', '0')
        ICP.set_param(_MODULE + '.pf_catalog_limit', '5')
        ICP.set_param(_MODULE + '.pf_stock_health_scope', 'managed')

    def _managed_product(self, name):
        product = self._pf_product(name)
        product.write({'x_is_printflow_managed': True})
        self._pf_add_stock(product, 10.0)
        return product

    # ------------------------------------------------------------------
    # 1) ACL de los 3 tableros para base.group_user (Q11)
    # ------------------------------------------------------------------
    def test_board_acl_is_base_group_user(self):
        group = self.env.ref('base.group_user')
        Access = self.env['ir.model.access']
        for model_name in BOARD_MODELS:
            acl = Access.search([
                ('model_id.model', '=', model_name),
                ('group_id', '=', group.id),
            ])
            self.assertTrue(
                acl, 'Falta ACL base.group_user para %s' % model_name)
            self.assertTrue(
                all(acl.mapped('perm_read')), model_name)
            self.assertTrue(
                all(acl.mapped('perm_write')), model_name)
            self.assertTrue(
                all(acl.mapped('perm_create')), model_name)
            self.assertTrue(
                all(acl.mapped('perm_unlink')), model_name)

    # ------------------------------------------------------------------
    # 2) El operador abre/puebla los 3 tableros
    # ------------------------------------------------------------------
    def test_operator_populates_catalog(self):
        self._managed_product('FASE7 OP CATALOGO')
        catalog = self.env['printflow.inventory.catalog'].with_user(
            self.operator)
        rows = catalog._pf_populate(only_alerts=False)
        self.assertTrue(rows)
        action = catalog.action_open_catalog()
        self.assertEqual(action['res_model'], 'printflow.inventory.catalog')

    def test_operator_populates_pending(self):
        pending = self.env['printflow.node.pending.line'].with_user(
            self.operator)
        pending._pf_populate()
        action = pending.action_open_pending()
        self.assertEqual(action['res_model'], 'printflow.node.pending.line')

    def test_operator_opens_product_flow(self):
        product = self._managed_product('FASE7 OP FLUJO')
        action = self.env['printflow.product.flow'].with_user(
            self.operator).action_open_product_flow(product.id)
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.product.flow')

    # ------------------------------------------------------------------
    # 3) Aislamiento por usuario de los TransientModel
    # ------------------------------------------------------------------
    def test_catalog_rows_isolated_by_user(self):
        self._managed_product('FASE7 AISLAMIENTO')
        Catalog = self.env['printflow.inventory.catalog']
        Catalog.with_user(self.operator)._pf_populate(only_alerts=False)
        rows_user = Catalog.search(
            [('create_uid', '=', self.operator.id)])
        self.assertTrue(rows_user)
        rows_admin = Catalog.search(
            [('create_uid', '=', self.env.uid)])
        self.assertFalse(rows_admin & rows_user)

    # ------------------------------------------------------------------
    # 4) Validación masiva SIN sudo (Q11)
    # ------------------------------------------------------------------
    def test_bulk_validate_runs_without_sudo(self):
        product = self._managed_product('FASE7 OP VALIDAR')
        so = self._pf_confirm_order(product, 1.0)
        picking = so.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]
        self.assertTrue(picking)

        Pending = self.env['printflow.node.pending.line'].with_user(
            self.operator)
        lines = Pending._pf_populate(
            product_ids=[product.id], node_keys=['delivery'])
        self.assertTrue(lines)

        # Q11: el método de validación NO debe invocar ``sudo`` en su propio
        # modelo (sudo solo para leer/navegar; la validación usa los permisos
        # del usuario). Si lo invocara, la excepción haría fallar el test.
        pending_cls = type(self.env['printflow.node.pending.line'])
        with mock.patch.object(
                pending_cls, 'sudo',
                side_effect=AssertionError('sudo prohibido al validar')):
            result = Pending.with_context(
                active_ids=lines.ids).action_pf_validate_selected()

        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(
            result['res_model'], 'printflow.delivery.bulk.result')
        picking.invalidate_recordset(['state'])
        self.assertEqual(picking.state, 'done')
