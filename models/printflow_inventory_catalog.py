# -*- coding: utf-8 -*-
"""Tablero "Productos": catálogo/índice de productos (PrintFlow · Fase 6).

``TransientModel`` poblado BAJO DEMANDA (cero migración) con UNA fila por
producto del alcance configurado. Es un ÍNDICE (no la bandeja de remedios):
muestra el semáforo agregado, el tipo de flujo, el estado de inventario y los
PENDIENTES por nodo, y ofrece el drill-down al DIAGRAMA DE FLUJO del producto.

Diseño:
  * Reutiliza el motor de salud (``printflow.stock.health``) para el estado y el
    motor de pendientes (``printflow.flow.pending``) para los conteos por nodo.
  * Cero hardcodeo: alcance ``pf_stock_health_scope`` y tope ``pf_catalog_limit``
    (0 = sin tope).
  * Poblado en LOTE (sin N+1): 1 lectura de inventario + ≤5 búsquedas de
    pendientes + 1 ``create``.
  * Aislamiento por usuario: solo se re-crean/ven las filas del usuario actual
    (``create_uid``); dos usuarios no se pisan el tablero transitorio.
  * El drill-down al diagrama pasa por el HOOK ``_pf_product_flow_action``
    (stub aquí; ``diagnostic/`` lo sobreescribe). Así ``models/`` NUNCA importa
    ``diagnostic/``.
"""

from odoo import _, api, fields, models

from .printflow_node_pending_line import PENDING_NODE_SELECTION
# El servicio de salud vive en el addon PRINCIPAL: import absoluto (GI -> principal).
from odoo.addons.x_product_dimensional_pricing.models.printflow_stock_health import (
    INVENTORY_STATE_SELECTION,
    LOT_STATE_SELECTION,
)

# Semáforo agregado del producto (ordenado por prioridad).
SEVERITY_SELECTION = [
    ('ok', 'OK'),
    ('info', 'Informativo'),
    ('warning', 'Atención'),
    ('danger', 'Crítico'),
]

_FLOW_TYPE_SELECTION = [
    ('purchase', 'Compra'),
    ('manufacture', 'Fabricación'),
]

# Estados de inventario que producen alerta (mismo criterio del Bloque IV).
_DANGER_STATES = ('physical', 'no_route')
_WARNING_STATES = ('over_reserved', 'contention')

# Estados de lote que producen alerta (mismo criterio del Bloque V).
_DANGER_LOT_STATES = (
    'lot_missing', 'lot_orphan_reservation', 'lot_no_stock')
_WARNING_LOT_STATES = (
    'lot_generic', 'lot_mixed', 'lot_unassigned_finished')

# Rango de orden por severidad (menor = más grave = primero).
_SEVERITY_RANK = {'danger': 0, 'warning': 1, 'info': 2, 'ok': 3}


class PrintflowInventoryCatalog(models.TransientModel):
    """Índice de productos con semáforo, tipo de flujo y pendientes por nodo."""

    _name = 'printflow.inventory.catalog'
    _description = 'Catálogo de productos (PrintFlow)'
    _order = 'severity_rank, default_code, id'

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, readonly=True)
    default_code = fields.Char(
        related='product_id.default_code', string='Referencia',
        store=True, readonly=True)
    uom_id = fields.Many2one(
        related='product_id.uom_id', string='UdM', readonly=True)
    flow_type = fields.Selection(
        _FLOW_TYPE_SELECTION, string='Tipo de flujo', readonly=True)
    state = fields.Selection(
        INVENTORY_STATE_SELECTION, string='Estado', readonly=True)
    lot_state = fields.Selection(
        LOT_STATE_SELECTION, string='Lote', readonly=True)
    severity = fields.Selection(
        SEVERITY_SELECTION, string='Semáforo', readonly=True)
    severity_rank = fields.Integer(string='Prioridad', readonly=True, default=9)
    node_pending_total = fields.Integer(
        string='Pendientes', readonly=True,
        help='Suma de documentos pendientes del producto en todos los nodos.')
    pending_by_node = fields.Char(
        string='Pendientes por nodo', readonly=True,
        help='Serialización legible, p.ej. "Compras:2 · Entregas:1".')
    has_alert = fields.Boolean(
        string='En alerta', readonly=True,
        help='El producto tiene una alerta de inventario/lote (severity != ok).')
    has_pending = fields.Boolean(
        string='Con pendientes', readonly=True,
        help='El producto tiene documentos pendientes en algún nodo.')

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_reset(self):
        """Descarta SOLO las filas del usuario actual (aislamiento por usuario)."""
        self.sudo().search([('create_uid', '=', self.env.uid)]).unlink()

    @api.model
    def _pf_scope_products(self, only_alerts=False, limit=0):
        """Productos del alcance (todos) o SOLO los que están en alerta.

        ``limit=0`` = sin tope. En ``only_alerts`` se pasa el ``0`` TAL CUAL a
        ``_pf_products_in_alert`` (0 = sin tope; ``None`` usaría el tope de
        saneamiento). En el alcance completo se usa ``search(limit=0)``.
        """
        health = self.env['printflow.stock.health']
        if only_alerts:
            return health._pf_products_in_alert(limit=limit)
        return self.env['product.product'].sudo().search(
            health._pf_scope_product_domain(),
            limit=(limit or None), order='id')

    @api.model
    def _pf_populate(self, only_alerts=False):
        """Reconstruye el catálogo (en lote, sin N+1) y devuelve las filas.

        :param bool only_alerts: si es True, solo los productos en alerta
            (``_pf_products_in_alert``); si no, TODOS los del alcance, con el
            tope ``pf_catalog_limit`` (0 = sin tope).
        :rtype: printflow.inventory.catalog
        """
        health = self.env['printflow.stock.health']
        pending = self.env['printflow.flow.pending']
        engine = self.env['printflow.order.health.engine']
        limit = pending._pf_catalog_limit()

        self._pf_reset()
        products = self._pf_scope_products(
            only_alerts=only_alerts, limit=limit).filtered(lambda p: p)
        if not products:
            return self.browse()

        # ── Memo intra-request (sin N+1): se precalcula UNA vez y se reenvía ──
        # 1) Estado de reserva (una sola lectura de quants).
        reservation_states = engine._pf_reservation_state_map(products.ids)
        # 2) BOM por producto (una sola llamada a ``_bom_find``).
        bom_by_product = engine._pf_bom_by_product(products)
        # 3) Fabricables: reutiliza el mapa de BOM (no re-consulta).
        manufacturable = engine._pf_manufacturable_products(
            products, bom_by_product=bom_by_product)
        # 4) Estado de lote en lote (para ``tracking='lot'``). El adaptador de GI
        #    resta los hallazgos AUTORIZADOS (F3) antes de inyectarlo al snapshot;
        #    con supresiones vacías el resultado es idéntico (motor intacto).
        lot_states = health._pf_lot_states_map(products)
        lot_states = self.env[
            'printflow.finding.exception.filter']._pf_apply_to_lot_map(
                products, lot_states)
        # 5) Snapshot de inventario reutilizando TODOS los mapas anteriores.
        snapshot = health._pf_inventory_snapshot(
            products,
            reservation_states=reservation_states,
            bom_by_product=bom_by_product,
            manufacturable=manufacturable,
            lot_states=lot_states,
        )
        # 6) Pendientes por nodo (una pasada por modelo; sin cambios).
        pending_map = pending._pf_node_pending_map(products)

        rows = []
        for product in products:
            info = snapshot.get(product.id) or {}
            state = info.get('state') or 'ok'
            lot_state = info.get('lot_state') or 'lot_ok'
            node_counts = pending_map.get(product.id) or {}
            total = sum(node_counts.values())
            severity, rank = self._pf_severity(state, lot_state)
            rows.append({
                'product_id': product.id,
                'flow_type': (
                    'manufacture' if product.id in manufacturable
                    else 'purchase'),
                'state': state,
                'lot_state': lot_state,
                'severity': severity,
                'severity_rank': rank,
                'node_pending_total': total,
                'pending_by_node': self._pf_pending_label(node_counts),
                'has_alert': severity != 'ok',
                'has_pending': total > 0,
            })
        return self.create(rows)

    @api.model
    def _pf_severity(self, state, lot_state):
        """Semáforo agregado del producto: estado/lote -> ``(severity, rank)``.

        Fuente única del semáforo del catálogo. No reinventa umbrales: reutiliza
        las selecciones del servicio de salud (``stock.health``).
        """
        if state in _DANGER_STATES or lot_state in _DANGER_LOT_STATES:
            return 'danger', _SEVERITY_RANK['danger']
        if state in _WARNING_STATES or lot_state in _WARNING_LOT_STATES:
            return 'warning', _SEVERITY_RANK['warning']
        return 'ok', _SEVERITY_RANK['ok']

    @api.model
    def _pf_pending_label(self, node_counts):
        """Serialización legible de los pendientes por nodo."""
        if not node_counts:
            return ''
        labels = dict(PENDING_NODE_SELECTION)
        order = [key for key, _label in PENDING_NODE_SELECTION]
        parts = []
        for key in order:
            count = node_counts.get(key)
            if count:
                parts.append('%s:%s' % (labels.get(key, key), count))
        return ' · '.join(parts)

    # ══════════════════════════════════════════════════════════════════════
    # ENTRADA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def action_open_catalog(self, only_alerts=False):
        """Puebla el tablero y devuelve el ``act_window`` lista/kanban.

        :param bool only_alerts: abre con el filtro preestablecido
            "Solo alertas" (``search_default_filter_alert``).
        """
        self._pf_populate(only_alerts=only_alerts)
        context = {'search_default_filter_alert': 1} if only_alerts else {}
        search_view = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_inventory_catalog_view_search')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Productos en alerta') if only_alerts else _('Productos'),
            'res_model': self._name,
            'view_mode': 'list,kanban',
            'target': 'current',
            'search_view_id': search_view.id,
            'domain': [('create_uid', '=', self.env.uid)],
            'context': context,
        }

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES DE FILA
    # ══════════════════════════════════════════════════════════════════════
    def action_open_flow(self):
        """Drill-down: abre el DIAGRAMA DE FLUJO del producto (hook)."""
        self.ensure_one()
        return self._pf_product_flow_action(self.product_id)

    def action_open_alerts(self):
        """Abre la bandeja de alertas filtrada a este producto."""
        self.ensure_one()
        return self.env['printflow.inventory.health']._pf_open_health(
            products=self.product_id,
            title=_('Salud de inventario · %s') % (
                self.product_id.display_name or ''))

    def action_open_product(self):
        """Abre la ficha del producto."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.product_id.display_name,
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _pf_product_flow_action(self, product):
        """HOOK del drill-down al diagrama de flujo (stub del módulo principal).

        En ``models/`` NO se puede depender de ``diagnostic/``: este stub avisa
        que el diagrama no está disponible. ``diagnostic/`` sobreescribe este
        método (``_inherit = 'printflow.inventory.catalog'``) y devuelve la
        acción real de ``printflow.product.flow``.
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': _(
                    'El módulo de diagnóstico no está instalado: no se puede '
                    'abrir el diagrama de flujo del producto.'),
                'type': 'warning',
                'sticky': False,
            },
        }
