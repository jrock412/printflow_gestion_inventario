# -*- coding: utf-8 -*-
"""Fase 4 — Enumeración de documentos pendientes.

``_pf_pending_document_lines`` enumera documentos de varios nodos con UNA
búsqueda por nodo (sin N+1); ``bulk_action_xmlid`` solo en ``delivery``; el tope
``pf_node_pending_limit`` se aplica POR NODO.
"""
from unittest.mock import patch

from odoo import fields
from odoo.addons.printflow_gestion_inventario.models import (
    printflow_flow_pending as pending_engine,
)
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNodePendingEnumeration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Pending = cls.env['printflow.flow.pending']
        # Parámetros deterministas (transitorio: rollback al terminar la clase).
        cls._set_param_cls('pf_node_pending_enabled', '1')
        cls._set_param_cls(
            'pf_node_pending_nodes', 'purchase,receipt,production,delivery,sale')
        cls._set_param_cls('pf_node_pending_limit', '0')
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Enumeración (F4)',
        })
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Enumeración (F4)',
        })

    @classmethod
    def _set_param_cls(cls, key, value):
        cls.env['ir.config_parameter'].sudo().set_param(
            'x_product_dimensional_pricing.%s' % key, value)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _add_stock(self, product, qty):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty)

    def _confirm_order(self, product, qty=1.0):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _purchase_order(self, product):
        return self.env['purchase.order'].create({
            'partner_id': self.supplier.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': 1.0,
                'price_unit': 1.0,
                'name': product.name,
                'product_uom': product.uom_id.id,
                'date_planned': fields.Datetime.now(),
            })],
        })

    def _production_order(self, product, qty=1.0):
        picking_type = self.env['stock.picking.type'].search(
            [('code', '=', 'mrp_operation'),
             ('company_id', '=', self.env.company.id)], limit=1)
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': product.uom_id.id,
            'picking_type_id': picking_type.id,
            'date_start': fields.Datetime.now(),
        })

    def _set_param(self, key, value):
        self.env['ir.config_parameter'].sudo().set_param(
            'x_product_dimensional_pricing.%s' % key, value)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def test_enumerates_nodes_and_only_delivery_is_bulk(self):
        product = self._product('ENUM DOCS')
        self._add_stock(product, 10.0)
        self._confirm_order(product)
        self._purchase_order(product)

        vals = self.Pending._pf_pending_document_lines(
            node_keys=['delivery', 'purchase'])
        by_node = {}
        for val in vals:
            by_node.setdefault(val['node_key'], []).append(val)

        self.assertTrue(by_node.get('delivery'), 'Debe listar la entrega.')
        self.assertTrue(by_node.get('purchase'), 'Debe listar la compra.')
        bulk_xmlid = (
            'x_product_dimensional_pricing.'
            'action_server_printflow_validate_deliveries')
        for val in by_node['delivery']:
            self.assertEqual(val['bulk_action_xmlid'], bulk_xmlid)
        for val in by_node['purchase']:
            self.assertFalse(val['bulk_action_xmlid'])

    def test_one_query_per_node_no_n_plus_1(self):
        """Con 3 entregas pendientes, UNA sola búsqueda sobre ``stock.picking``."""
        self._set_param('pf_node_pending_enabled', '1')
        self._set_param('pf_node_pending_nodes', 'delivery')
        product = self._product('ENUM N+1')
        self._add_stock(product, 10.0)
        for _i in range(3):
            self._confirm_order(product)

        Picking = self.env['stock.picking']
        original = type(Picking).search_read
        calls = []

        def _spy(records, *args, **kwargs):
            calls.append(args)
            return original(records, *args, **kwargs)

        with patch.object(type(Picking), 'search_read', _spy):
            self.Pending._pf_pending_document_lines(node_keys=['delivery'])
        self.assertEqual(
            len(calls), 1,
            'La enumeración debe hacer UNA búsqueda por nodo, no por documento.')

    def test_limit_is_per_node(self):
        """``pf_node_pending_limit`` acota CADA nodo, no el total."""
        self._set_param('pf_node_pending_nodes', 'delivery,purchase')
        self._set_param('pf_node_pending_limit', '1')
        product = self._product('ENUM LIMITE')
        self._add_stock(product, 20.0)
        for _i in range(3):
            self._confirm_order(product)
        for _i in range(2):
            self._purchase_order(product)

        vals = self.Pending._pf_pending_document_lines(
            node_keys=['delivery', 'purchase'])
        counts = {}
        for val in vals:
            counts[val['node_key']] = counts.get(val['node_key'], 0) + 1
        self.assertEqual(counts.get('delivery'), 1)
        self.assertEqual(counts.get('purchase'), 1)

    def test_product_filter_anchors_line(self):
        self._set_param('pf_node_pending_nodes', 'delivery')
        product = self._product('ENUM FILTRO')
        self._add_stock(product, 10.0)
        self._confirm_order(product)

        vals = self.Pending._pf_pending_document_lines(
            product_ids=[product.id], node_keys=['delivery'])
        self.assertTrue(vals)
        self.assertTrue(all(val['product_id'] == product.id for val in vals))

    # ------------------------------------------------------------------
    # Regresión Fase 4: ``mrp.production`` NO tiene ``date_planned_start``.
    # El Centro reventaba al poblar porque la enumeración pedía ese campo
    # inexistente. Estos tests blindan los campos/orden y la degradación.
    # ------------------------------------------------------------------
    def test_production_constants_use_valid_fields(self):
        """Las constantes de ``production`` solo nombran campos que EXISTEN."""
        available = set(self.env['mrp.production']._fields)
        self.assertNotIn(
            'date_planned_start', available,
            'Premisa de la regresión: el modelo no debe tener ese campo.')
        for field_name in pending_engine.PENDING_DOCUMENT_FIELDS['production']:
            self.assertIn(
                field_name, available,
                "Campo inválido en PENDING_DOCUMENT_FIELDS['production']: %s"
                % field_name)
        for term in pending_engine.PENDING_DOCUMENT_ORDER[
                'production'].split(','):
            field_name = term.strip().split()[0]
            self.assertIn(
                field_name, available,
                "Campo inválido en el orden de producción: %s" % field_name)
        # La cascada de fechas no puede nombrar campos inexistentes: cada
        # término debe existir en al menos uno de los modelos de nodo.
        union = set()
        for model_name in set(pending_engine.PENDING_DOCUMENT_MODELS.values()):
            union |= set(self.env[model_name]._fields)
        for field_name in pending_engine.PENDING_DOCUMENT_DATE_FIELDS:
            self.assertIn(
                field_name, union,
                "Campo de fecha inexistente en todos los nodos: %s"
                % field_name)

    def test_production_enumeration_does_not_crash(self):
        """``_pf_pending_document_lines(production)`` no revienta con MO."""
        product = self._product('ENUM PRODUCCION')
        mo = self._production_order(product)
        vals = self.Pending._pf_pending_document_lines(
            node_keys=['production'])
        self.assertTrue(
            any(val['res_id'] == mo.id for val in vals),
            'La MO pendiente debe aparecer en la enumeración.')

    def test_sanitize_drops_invalid_field_and_order(self):
        """El saneador descarta campos/orden inexistentes y cae a ``id asc``."""
        fields_safe, order_safe = self.Pending._pf_sanitize_document_read(
            'mrp.production',
            ['name', 'date_planned_start', 'state'],
            'date_planned_start asc, id asc')
        self.assertEqual(fields_safe, ['name', 'state'])
        self.assertEqual(order_safe, 'id asc')

    def test_sanitize_falls_back_when_model_unknown(self):
        """Con un modelo inexistente, el saneador no revienta y degrada."""
        fields_safe, order_safe = self.Pending._pf_sanitize_document_read(
            'modelo.inexistente.printflow', ['name'], 'date_start asc')
        self.assertEqual(fields_safe, [])
        self.assertEqual(order_safe, 'id asc')
