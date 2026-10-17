# -*- coding: utf-8 -*-
"""Esquema COMPARTIDO de causantes del diagnóstico (PrintFlow - FASE 5).

``AbstractModel`` con los campos comunes de una fila de "recopilar". La bandeja
del ESCÁNER (``printflow.product.diagnostic.evidence``) y la bandeja del PEDIDO
(``printflow.order.diagnostic.evidence``) comparten este esquema para que el
etiquetado (tipo de causante, referencia, cantidades, porción por pedido) sea el
mismo en ambos flujos.

NO fija la navegación: cada bandeja resuelve su ``nav_kind`` en su propio
``action_open``. Es pure schema: cero estado propio, cero migración.
"""

from odoo import fields, models

from .printflow_product_check_mixin import (
    ACTION_KIND_SELECTION,
    CAUSANTE_TYPE_SELECTION,
)

# Vocabulario de navegación compartido por las bandejas. La unión cubre los
# destinos del escáner y los del pedido (compra/recepción/porción).
CAUSANTE_NAV_SELECTION = [
    ('none', 'Sin navegación'),
    ('product', 'Producto'),
    ('quants', 'Existencias'),
    ('bom', 'BOM'),
    ('bom_list', 'Lista de BOM'),
    ('sale_order', 'Pedido'),
    ('sale_lines', 'Líneas de venta'),
    ('sale_orders', 'Lista de pedidos'),
    ('orderpoint', 'Regla de reorden'),
    ('mo', 'Orden de fabricación'),
    ('mo_list', 'Lista de órdenes de fabricación'),
    ('reserving_sale_orders', 'Pedidos que lo reservan'),
    ('blocking_reservations', 'Quién me bloquea'),
    ('delivery_orders', 'Albaranes de entrega'),
    ('line_delivery', 'Entrega del producto'),
    ('purchase_order', 'Orden de compra'),
    ('picking', 'Albarán'),
    ('order_portion', 'Porción por pedido'),
    ('collect_tray', 'Bandeja de resolución'),
    ('order_collect_tray', 'Bandeja del pedido'),
    ('flow', 'Flujo unificado'),
]


class PrintflowDiagnosticCausanteMixin(models.AbstractModel):
    """Campos comunes de una fila de causante recolectable."""

    _name = 'printflow.diagnostic.causante.mixin'
    _description = 'Esquema compartido de causantes (PrintFlow)'

    sequence = fields.Integer(string='Secuencia')
    label = fields.Char(string='Etiqueta')
    detail = fields.Text(string='Detalle')
    nav_kind = fields.Selection(
        CAUSANTE_NAV_SELECTION, string='Tipo de navegación', default='none')
    res_model = fields.Char(string='Modelo destino')
    res_id = fields.Integer(string='Id destino')

    product_id = fields.Many2one('product.product', string='Producto')
    sale_order_id = fields.Many2one('sale.order', string='Pedido')
    bom_id = fields.Many2one('mrp.bom', string='BOM')
    orderpoint_id = fields.Many2one(
        'stock.warehouse.orderpoint', string='Regla de reorden')
    mo_id = fields.Many2one('mrp.production', string='Orden de fabricación')
    purchase_order_id = fields.Many2one(
        'purchase.order', string='Orden de compra')
    picking_id = fields.Many2one('stock.picking', string='Albarán')

    causante_type = fields.Selection(
        CAUSANTE_TYPE_SELECTION, string='Tipo de causante', default='other')
    collectible = fields.Boolean(
        string='Recolectable', default=False,
        help='Si está marcado, el causante entra en la bandeja agregada.')
    ref_name = fields.Char(string='Referencia')
    partner_name = fields.Char(string='Cliente / proveedor / almacén')
    qty = fields.Float(string='Cantidad')
    qty_secondary = fields.Float(string='Cantidad secundaria')
    state_label = fields.Char(string='Estado')
    date_ref = fields.Datetime(string='Fecha de referencia')
    action_kind = fields.Selection(
        ACTION_KIND_SELECTION, string='Acción', default='none')
    origin_group = fields.Char(
        string='Grupo de origen',
        help='Pedidos que comparten la OC (porción por pedido).')
