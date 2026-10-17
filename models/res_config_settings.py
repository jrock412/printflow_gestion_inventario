# -*- coding: utf-8 -*-
"""Configuración de la app "Salud de Inventario" (PrintFlow · GI).

Aporta SOLO los parámetros del motor de pendientes por nodo y del catálogo.
Las claves se **mantienen** con el namespace del addon principal
(``x_product_dimensional_pricing.pf_node_pending_*`` y ``.pf_catalog_limit``)
para no requerir migración de datos (cero escritura).
"""

from odoo import fields, models

from .printflow_flow_pending import (
    DEFAULT_NODE_PENDING_NODES,
    PARAM_CATALOG_LIMIT,
    PARAM_NODE_PENDING_ENABLED,
    PARAM_NODE_PENDING_LIMIT,
    PARAM_NODE_PENDING_NODES,
)
from .printflow_flow_lots import (
    DEFAULT_EXCEPTION_POLICY,
    EXCEPTION_POLICY_SELECTION,
    PARAM_LOT_ASSIGN_EXCEPTION_POLICY,
)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Tableros de GI (pendientes por nodo y catálogo) ──────────────────
    # Cero hardcodeo: las claves reutilizan las constantes del motor
    # ``printflow.flow.pending`` (fuente única; deben coincidir EXACTAMENTE).
    pf_node_pending_enabled = fields.Boolean(
        string='Activar avisos de pendientes por nodo',
        config_parameter=PARAM_NODE_PENDING_ENABLED,
        default=True,
        help='Interruptor global del motor de pendientes por nodo. Si se '
             'desactiva, los tableros y el diagrama no muestran pendientes.',
    )
    pf_node_pending_nodes = fields.Char(
        string='Nodos con pendientes (claves separadas por coma)',
        config_parameter=PARAM_NODE_PENDING_NODES,
        default=DEFAULT_NODE_PENDING_NODES,
        help='Nodos considerados al enumerar pendientes. Claves válidas: '
             'purchase, receipt, production, delivery, sale (y los nodos de '
             'inventario stock, stock_supply, stock_finished).',
    )
    pf_node_pending_limit = fields.Integer(
        string='Límite de documentos por nodo (0 = sin límite)',
        config_parameter=PARAM_NODE_PENDING_LIMIT,
        default=0,
        help='Tope de documentos enumerados POR NODO (0 = sin límite).',
    )
    pf_catalog_limit = fields.Integer(
        string='Límite de productos en el tablero Productos (0 = todos)',
        config_parameter=PARAM_CATALOG_LIMIT,
        default=0,
        help='Tope de productos que puebla el tablero "Productos" '
             '(0 = todos los del alcance).',
    )

    # ── Selector de lote por documento (asignación consciente) ───────────
    pf_lot_assign_exception_policy = fields.Selection(
        EXCEPTION_POLICY_SELECTION,
        string='Asignación de lote por excepción',
        config_parameter=PARAM_LOT_ASSIGN_EXCEPTION_POLICY,
        default=DEFAULT_EXCEPTION_POLICY,
        help='Qué exige PrintFlow cuando el operador elige, en la bandeja '
             'gestionable de lote, un lote que NO es el propio del documento: '
             'solo avisar; exigir el check de confirmación; o exigir '
             'confirmación y motivo. El operador siempre puede elegir; la '
             'política solo agrega fricción y registro.',
    )
