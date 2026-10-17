# -*- coding: utf-8 -*-
"""Lista REAL de Pendientes (PrintFlow · Fase 4b).

Custodia:
  * ``action_open_pending`` devuelve un ``act_window`` ``view_mode='list'`` con
    buscador;
  * la lista NO tiene columna booleana ``pf_selected`` ni ``center_id``;
  * el ``<search>`` trae filtros por nodo y el filtro "Validables";
  * ``action_pf_dispatch`` abre el DOCUMENTO de la fila;
  * existen las server actions nativas (validar / abrir) enganchadas a la lista.

Son de SOLO LECTURA y ``TransactionCase`` hace rollback al terminar.
"""

from odoo.tests.common import TransactionCase, tagged

from .printflow_stock_test_helpers import PrintflowStockHealthTestMixin

_MODULE = 'printflow_gestion_inventario'
# Las CLAVES de parámetro conservan el namespace del addon principal (cero
# migración); los xmlids de vistas/acciones viven ahora en GI (_MODULE).
_PARAM_MODULE = 'x_product_dimensional_pricing'


@tagged('post_install', '-at_install')
class TestPendingListSurface(
        PrintflowStockHealthTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pf_disable_reservation_limit()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Pendientes (F4b)'})
        cls.Pending = cls.env['printflow.node.pending.line']
        cls.env['ir.config_parameter'].sudo().set_param(
            _PARAM_MODULE + '.pf_node_pending_enabled', '1')
        cls.env['ir.config_parameter'].sudo().set_param(
            _PARAM_MODULE + '.pf_node_pending_nodes', 'delivery')
        cls.env['ir.config_parameter'].sudo().set_param(
            _PARAM_MODULE + '.pf_node_pending_limit', '0')

    def test_action_open_pending_returns_list(self):
        action = self.Pending.action_open_pending()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.node.pending.line')
        self.assertEqual(action['view_mode'], 'list')
        self.assertTrue(action.get('search_view_id'))

    def test_list_view_has_no_boolean_column(self):
        view = self.env.ref(
            '%s.printflow_node_pending_line_view_list' % _MODULE)
        arch = view.arch_db or ''
        self.assertNotIn('pf_selected', arch)
        self.assertNotIn('center_id', arch)

    def test_search_view_has_node_filters(self):
        view = self.env.ref(
            '%s.printflow_node_pending_line_view_search' % _MODULE)
        arch = view.arch_db or ''
        for token in ('filter_delivery', 'filter_bulk', 'group_node'):
            self.assertIn(token, arch)

    def test_dispatch_opens_document(self):
        product = self._pf_product('PENDIENTES DISPATCH')
        self._pf_add_stock(product, 10.0)
        so = self._pf_confirm_order(product, 1.0)
        picking = so.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]
        self.assertTrue(picking)

        line = self.Pending.create({
            'node_key': 'delivery',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'name': picking.name,
        })
        action = line.action_pf_dispatch()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'stock.picking')
        self.assertEqual(action['res_id'], picking.id)

    def test_native_server_actions_exist(self):
        validate = self.env.ref(
            '%s.action_server_printflow_validate_selected' % _MODULE)
        dispatch = self.env.ref(
            '%s.action_server_printflow_node_pending_dispatch' % _MODULE)
        open_pending = self.env.ref(
            '%s.action_server_printflow_open_pending' % _MODULE)
        self.assertEqual(validate.binding_view_types, 'list')
        self.assertEqual(dispatch.binding_view_types, 'list')
        self.assertEqual(validate.model_id.model, 'printflow.node.pending.line')
        self.assertTrue(open_pending)
