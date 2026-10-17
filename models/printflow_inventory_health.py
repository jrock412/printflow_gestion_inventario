# -*- coding: utf-8 -*-
"""Superficie "Salud de inventario" (PrintFlow).

TransientModel poblado BAJO DEMANDA al abrir la vista (cero migración). Lista
los productos en alerta (quant con libre negativo o sobrepedido agregado),
independientemente de que exista o no un pedido, con su estado y sus botones.
Reutiliza el servicio ``printflow.stock.health`` (detección) y
``printflow.stock.remedy`` (saneamiento).

Regla de oro: ningún botón despoja la reserva de un pedido ajeno. El único con
efecto de datos es el saneamiento (suelta + re-asigna por reglas de Odoo), y
requiere jefe de taller o administrador.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_EPS = 1e-6

# Orden por severidad dentro de la bandeja.
STATE_RANK = {
    'physical': 0,
    'over_reserved': 1,
    'contention': 2,
    'no_route': 3,
    'ok': 4,
}

# Reexporta las selecciones del servicio (del addon PRINCIPAL) para que las
# vistas no las dupliquen. Import absoluto: el cerebro vive en PrintFlow y este
# addon solo lo LEE (dirección GI -> principal).
from odoo.addons.x_product_dimensional_pricing.models.printflow_stock_health import (  # noqa: E402,E501
    INVENTORY_STATE_SELECTION,
    LOT_STATE_SELECTION,
    NATURE_SELECTION,
)
from odoo.addons.x_product_dimensional_pricing.models.printflow_stock_remedy import (  # noqa: E402,E501
    PLAN_ACTION_SELECTION,
)


class PrintflowInventoryHealth(models.TransientModel):
    """Una fila por producto en alerta de inventario (solo lectura + remedios)."""

    _name = 'printflow.inventory.health'
    _description = 'Salud de inventario (PrintFlow)'
    _order = 'severity_rank, product_id'

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, readonly=True)
    product_tmpl_id = fields.Many2one(
        related='product_id.product_tmpl_id', string='Plantilla', readonly=True)
    default_code = fields.Char(
        related='product_id.default_code', string='Referencia', readonly=True)
    uom_id = fields.Many2one(
        related='product_id.uom_id', string='UdM', readonly=True)
    state = fields.Selection(
        INVENTORY_STATE_SELECTION, string='Estado', readonly=True)
    nature = fields.Selection(
        NATURE_SELECTION, string='Naturaleza', readonly=True)
    severity_rank = fields.Integer(string='Prioridad', readonly=True)
    on_hand = fields.Float(string='En almacén', readonly=True)
    reserved = fields.Float(string='Reservado', readonly=True)
    free_global = fields.Float(string='Libre agregado', readonly=True)
    has_negative_quant = fields.Boolean(
        string='Quant negativo', readonly=True,
        help='Existe una ubicación con más reservado que existencia (reserva colgada).')
    deficit_qty = fields.Float(string='Falta física', readonly=True)
    contention_qty = fields.Float(string='Contención', readonly=True)
    route_summary = fields.Char(string='Ruta', readonly=True)
    location_id = fields.Many2one(
        'stock.location', string='Ubicación en alerta', readonly=True)
    has_blocking = fields.Boolean(
        string='Otros lo retienen', readonly=True,
        help='Hay entregas de otros pedidos que reservan este producto.')

    # ── Movimientos huérfanos (F2-B) y guard de activación de lote (H4) ──
    has_orphan_moves = fields.Boolean(
        string='Movimientos huérfanos', readonly=True,
        help='Tiene movimientos sin albarán, orden de fabricación ni ajuste de '
             'inventario (reservas huérfanas) que pueden purgarse.')
    orphan_move_count = fields.Integer(
        string='Nº huérfanos', readonly=True)
    needs_legacy_lot = fields.Boolean(
        string='Necesita lote legado', readonly=True,
        help='Tiene existencias internas sin lote: asígnales el lote legado '
             'LEGADO-<producto> antes de activar el seguimiento por lote.')
    lot_activation_ready = fields.Boolean(
        string='Listo para activar lote', readonly=True,
        help='No tiene pendientes sucios (movimientos sin lote, existencias '
             'sueltas ni reservas huérfanas): puede pasar a seguimiento por lote.')
    lot_activation_reason = fields.Char(
        string='Falta para activar lote', readonly=True)

    # ── Remedy recomendado (mapa único estado -> remedio -> destino) ─────
    remedy_key = fields.Char(string='Remedio', readonly=True)
    remedy_label = fields.Char(string='Recomendación', readonly=True)
    remedy_kind = fields.Selection(
        PLAN_ACTION_SELECTION, string='Tipo de acción', readonly=True)
    remedy_target = fields.Char(string='Destino', readonly=True)
    remedy_available = fields.Boolean(string='Hay remedio', readonly=True)

    # ── Dimensión de LOTE / trazabilidad (Bloque V) ─────────────────────
    lot_state = fields.Selection(
        LOT_STATE_SELECTION, string='Estado de lote', readonly=True)
    lot_detail = fields.Char(string='Detalle de lote', readonly=True)
    lot_remedy_key = fields.Char(string='Remedio de lote', readonly=True)
    lot_remedy_label = fields.Char(
        string='Recomendación de lote', readonly=True)
    lot_remedy_kind = fields.Selection(
        PLAN_ACTION_SELECTION, string='Tipo (lote)', readonly=True)
    lot_remedy_target = fields.Char(string='Destino (lote)', readonly=True)
    lot_remedy_available = fields.Boolean(
        string='Hay remedio de lote', readonly=True)

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, products=None, domain=None, limit=None):
        """Reconstruye la bandeja con los productos en alerta.

        :param products: recordset opcional; si no se pasa, se buscan por
            ``printflow.stock.health._pf_products_in_alert``.
        :return: recordset de ``printflow.inventory.health``.
        """
        Health = self.env['printflow.stock.health']
        if products is None:
            products = Health._pf_products_in_alert(
                domain=domain, limit=limit)
        products = products.filtered(lambda p: p)
        self.sudo().search([]).unlink()
        if not products:
            return self.browse()
        # F3: el adaptador de GI resta los hallazgos AUTORIZADOS del estado de
        # lote ANTES del snapshot (motor intacto). CA-5: si el hallazgo silenciado
        # era el ÚNICO motivo de alerta, el producto sale de la bandeja. Sin
        # excepciones, ``lot_states == raw_lot_states`` y NO se descarta nada
        # (paridad histórica, CA-12).
        raw_lot_states = Health._pf_lot_states_map(products)
        lot_states = self.env[
            'printflow.finding.exception.filter']._pf_apply_to_lot_map(
                products, raw_lot_states)
        snapshot = Health._pf_inventory_snapshot(products, lot_states=lot_states)

        def _pf_silenced_out(product):
            raw = raw_lot_states.get(product.id) or {}
            filtered = lot_states.get(product.id) or {}
            return (
                (raw.get('state') or 'lot_ok') != 'lot_ok'
                and (filtered.get('state') or 'lot_ok') == 'lot_ok'
                and (snapshot.get(product.id, {}).get('state') or 'ok') == 'ok')

        products = products.filtered(lambda p: not _pf_silenced_out(p))
        if not products:
            return self.browse()
        blocking = self._pf_blocking_products(products)
        negative_loc = self._pf_negative_locations(products)
        # F2-B: conteo de movimientos huérfanos por producto (una sola pasada).
        orphan_count = {}
        for move in Health._pf_orphan_moves(products):
            orphan_count[move.product_id.id] = (
                orphan_count.get(move.product_id.id, 0) + 1)
        rows = []
        for product in products:
            info = snapshot.get(product.id) or {}
            state = info.get('state') or 'ok'
            # H4: guard de activación por lote (semáforo previo por producto).
            ready, reason_codes = Health._pf_lot_activation_ready(product)
            reasons = [
                self._pf_activation_reason_label(code)
                for code in reason_codes
            ]
            rows.append({
                'product_id': product.id,
                'state': state,
                'nature': info.get('nature') or 'ok',
                'severity_rank': STATE_RANK.get(state, 9),
                'on_hand': info.get('on_hand') or 0.0,
                'reserved': info.get('reserved') or 0.0,
                'free_global': info.get('free_global') or 0.0,
                'has_negative_quant': bool(info.get('has_negative_quant')),
                'deficit_qty': info.get('deficit_qty') or 0.0,
                'contention_qty': info.get('contention_qty') or 0.0,
                'route_summary': info.get('route_summary') or '',
                'location_id': negative_loc.get(product.id, False),
                'has_blocking': product.id in blocking,
                'has_orphan_moves': product.id in orphan_count,
                'orphan_move_count': orphan_count.get(product.id, 0),
                'needs_legacy_lot': 'loose_quants' in reason_codes,
                'lot_activation_ready': ready,
                'lot_activation_reason': ', '.join(reasons),
                'remedy_key': info.get('remedy_key') or False,
                'remedy_label': info.get('remedy_label') or '',
                'remedy_kind': info.get('remedy_kind') or False,
                'remedy_target': info.get('remedy_target') or '',
                'remedy_available': bool(info.get('remedy_available')),
                'lot_state': info.get('lot_state') or 'lot_ok',
                'lot_detail': info.get('lot_detail') or '',
                'lot_remedy_key': info.get('lot_remedy_key') or False,
                'lot_remedy_label': info.get('lot_remedy_label') or '',
                'lot_remedy_kind': info.get('lot_remedy_kind') or False,
                'lot_remedy_target': info.get('lot_remedy_target') or '',
                'lot_remedy_available': bool(info.get('lot_remedy_available')),
            })
        return self.create(rows)

    @api.model
    def _pf_activation_reason_label(self, code):
        """Traduce el código del guard H4 a texto legible."""
        return {
            'pending_moves': _('movimientos sin lote'),
            'loose_quants': _('existencias sin lote'),
            'orphan_moves': _('reservas huérfanas'),
        }.get(code, code)

    @api.model
    def _pf_blocking_products(self, products):
        """Ids de productos que OTROS albaranes (no terminados) reservan."""
        blocking = set()
        if not products:
            return blocking
        move_lines = self.env['stock.move.line'].sudo().search([
            ('product_id', 'in', products.ids),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
        ])
        for move_line in move_lines:
            if move_line.picking_id and move_line.picking_id.state not in (
                    'done', 'cancel'):
                blocking.add(move_line.product_id.id)
        return blocking

    @api.model
    def _pf_negative_locations(self, products):
        """Primera ubicación con libre negativo por producto (contexto visual)."""
        locations = {}
        if not products:
            return locations
        for quant in self.env['stock.quant'].sudo().search([
            ('product_id', 'in', products.ids),
            ('location_id.usage', 'in', ('internal', 'transit')),
        ]):
            if (quant.quantity - quant.reserved_quantity) < -_EPS:
                locations.setdefault(quant.product_id.id, quant.location_id.id)
        return locations

    @api.model
    def _pf_open_health(self, products=None, domain=None, title=None):
        """Abre la bandeja poblada (punto de entrada del menú/acción).

        :param products: recordset opcional de ``product.product``. Si viene, la
            bandeja se PUEBLA solo con esos productos y el ``act_window`` se
            FILTRA a ellos (ruteo contextual desde el diagnóstico de pedido).
        :param list domain: dominio opcional de población/filtro cuando no se
            pasan ``products``.
        :param str title: título contextual de la ventana.

        Sin ``products`` (y sin ``domain``) el comportamiento es IDÉNTICO al
        histórico: puebla con todos los productos en alerta y abre la bandeja.
        """
        if products is not None or domain is not None:
            if products is None:
                products = self.env['printflow.stock.health']._pf_products_in_alert(
                    domain=domain)
            products = products.filtered(lambda p: p)
            self._pf_populate(products=products)
            return {
                'type': 'ir.actions.act_window',
                'name': title or _('Salud de inventario'),
                'res_model': self._name,
                'view_mode': 'list,form',
                'target': 'current',
                'domain': [('product_id', 'in', products.ids)],
            }
        products = self.env['printflow.stock.health']._pf_products_in_alert()
        self._pf_populate(products=products)
        return {
            'type': 'ir.actions.act_window',
            'name': title or _('Salud de inventario'),
            'res_model': self._name,
            'view_mode': 'list,form',
            'target': 'current',
            'context': {'search_default_filter_alert': 1},
        }

    @api.model
    def action_open_all_alerts(self):
        """Botón "Ver todas las alertas": reabre la bandeja SIN filtro de producto.

        Wrapper público (los botones de vista no invocan métodos ``_``): delega
        en ``_pf_open_health()`` sin ``products``, es decir, el comportamiento
        general de la bandeja.
        """
        return self._pf_open_health()

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES DE FILA
    # ══════════════════════════════════════════════════════════════════════
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

    def action_cleanup_reservations(self):
        """Sanea (suelta + re-asigna) las reservas colgadas de ESTE producto."""
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        result = self.env['printflow.stock.health']._pf_cleanup_products(
            self.product_id)
        self.unlink()
        if result['pickings']:
            message = _('Saneamiento: %s albarán(es) re-asignado(s).') % (
                result['pickings'])
            ntype = 'success'
        else:
            message = _('No había reservas colgadas que sanear.')
            ntype = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': message,
                'type': ntype,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model
    def action_cleanup_all(self):
        """Saneamiento GLOBAL de todos los productos en alerta (con permiso)."""
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        result = self.env['printflow.stock.health']._pf_cleanup_all()
        self._pf_populate()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': _(
                    'Saneamiento global: %(products)s producto(s), '
                    '%(pickings)s albarán(es) re-asignado(s).') % result,
                'type': 'success' if result['pickings'] else 'warning',
                'sticky': False,
            },
        }

    # ══════════════════════════════════════════════════════════════════════
    # MOVIMIENTOS HUÉRFANOS (F2-B) Y LOTE LEGADO (H3)
    # ══════════════════════════════════════════════════════════════════════
    def action_purge_orphan_moves(self):
        """Purga los movimientos huérfanos de ESTE producto (F2-B)."""
        self.ensure_one()
        result = self.env['printflow.stock.health']._pf_purge_orphan_moves(
            self.product_id)
        self.unlink()
        return self._pf_notify(
            result['purged'],
            _('Movimientos huérfanos purgados: %s.') % result['purged'],
            _('No había movimientos huérfanos que purgar.'))

    @api.model
    def action_purge_all_orphan_moves(self):
        """Purga GLOBAL de todos los movimientos huérfanos (F2-B, con permiso)."""
        result = self.env[
            'printflow.stock.health']._pf_purge_all_orphan_moves()
        self._pf_populate()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': _(
                    'Purga global: %s movimiento(s) huérfano(s) purgado(s).') % (
                        result['purged']),
                'type': 'success' if result['purged'] else 'warning',
                'sticky': False,
            },
        }

    @api.model
    def action_open_orphan_moves(self):
        """Abre la bandeja SOLO con los productos que tienen huérfanos (F2-B)."""
        products = self.env[
            'printflow.stock.health']._pf_orphan_moves().mapped('product_id')
        self._pf_populate(products=products)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Movimientos huérfanos'),
            'res_model': self._name,
            'view_mode': 'list,form',
            'target': 'current',
            'domain': [('product_id', 'in', products.ids)],
        }

    def action_assign_legacy_lot(self):
        """Asigna el lote legado a las existencias previas de ESTE producto (H3)."""
        self.ensure_one()
        result = self.env[
            'printflow.stock.health']._pf_assign_legacy_lot_to_quants(
                self.product_id)
        self.unlink()
        return self._pf_notify(
            result['assigned'],
            _('Lote legado asignado a %s existencia(s).') % result['assigned'],
            _('No había existencias previas sin lote.'))

    def _pf_notify(self, count, success_message, empty_message):
        """Notificación estándar de una acción de fila con resultado."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': success_message if count else empty_message,
                'type': 'success' if count else 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ══════════════════════════════════════════════════════════════════════
    # MAPA ESTADO -> REMEDIO -> DESTINO -> BOTÓN (D3)
    # ══════════════════════════════════════════════════════════════════════
    def action_apply_remedy(self):
        """Ejecuta el remedio recomendado de la fila."""
        self.ensure_one()
        kind = self.remedy_kind or 'none'
        target = self.remedy_target or ''
        if kind == 'run_action':
            return self._pf_run_action(target)
        if kind == 'navigate':
            return self._pf_nav_action(target)
        if kind == 'open_wizard':
            return self._pf_open_wizard(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_run_action(self, target):
        """Remedios con efecto (Bloques IV/V). Restringido por permiso.

        Todos mutan el inventario o la trazabilidad, así que exigen jefe de
        taller/administrador. Ninguno asigna a un pedido el lote de otro.
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Health = self.env['printflow.stock.health']
        target = target or ''
        message = ''
        if target == 'fix_over_reservation':
            Remedy._pf_assert_can_clean()
            Health._pf_cleanup_products(self.product_id)
            message = _('Reservas del producto reajustadas al stock real.')
        elif target == 'reconcile_lot_reservation':
            Remedy._pf_assert_can_clean()
            Health._pf_reassign_by_lot(self.product_id)
            message = _('Reserva de lote reconciliada con los movimientos.')
        elif target == 'assign_lot':
            Remedy._pf_assert_can_clean()
            self._pf_assign_lots_to_moves()
            message = _('Se asignó lote a los movimientos que no lo tenían.')
        elif target == 'replace_generic_lot':
            Remedy._pf_assert_can_clean()
            replaced = Health._pf_replace_generic_lot(self.product_id)
            message = _('Lotes genéricos sustituidos: %s.') % replaced
        elif target == 'separate_lots':
            Remedy._pf_assert_can_clean()
            Health._pf_replace_generic_lot(self.product_id)
            Health._pf_reassign_by_lot(self.product_id)
            message = _('Movimientos separados por lote.')
        elif target == 'repair_finished_lot':
            Remedy._pf_assert_can_clean()
            repaired = Health._pf_repair_finished_lot(self.product_id)
            message = _('Órdenes de fabricación reparadas: %s.') % repaired
        else:
            return {'type': 'ir.actions.act_window_close'}
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'), 'message': message,
                'type': 'success', 'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _pf_assign_lots_to_moves(self):
        """Asigna lote (exclusivo o con existencia) a los movimientos activos."""
        self.ensure_one()
        moves = self.env['stock.move'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('state', 'not in', ('done', 'cancel')),
            ('location_id.usage', '=', 'internal'),
            ('picking_type_id.code', '=', 'outgoing'),
        ])
        for move in moves:
            if not move._pf_has_lot_assigned():
                move._pf_auto_assign_lot()

    def _pf_nav_action(self, target):
        """Destinos de navegación del mapa."""
        self.ensure_one()
        if target == 'quants_adjust':
            return self._pf_open_quants_adjust()
        if target == 'bom_list':
            return self._pf_open_bom_list()
        if target == 'blocking_reservations':
            return self._pf_open_blocking()
        return {'type': 'ir.actions.act_window_close'}

    def _pf_open_wizard(self, target):
        """Destinos de creación prellenada (abrir ≠ ejecutar)."""
        self.ensure_one()
        if target == 'create_production':
            return self._pf_open_create_production()
        if target == 'buy_components':
            return self._pf_open_buy_components()
        if target == 'buy_product':
            return self._pf_open_buy_product()
        return {'type': 'ir.actions.act_window_close'}

    # ── Destinos concretos ──────────────────────────────────────────────
    def _pf_open_quants_adjust(self):
        """Ajuste de inventario del producto (propone el déficit como cantidad)."""
        self.ensure_one()
        suggested = self.deficit_qty or 0.0
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajuste de inventario de %s (sugerido: %.2f)') % (
                self.product_id.display_name, suggested),
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', self.product_id.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'context': {
                'inventory_mode': True,
                'search_default_product_id': self.product_id.id,
                'default_inventory_quantity': suggested,
                'pf_suggested_qty': suggested,
            },
            'target': 'current',
        }

    def _pf_open_bom_list(self):
        """Listas de materiales del producto (para crearla)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Listas de materiales de %s') % self.product_id.display_name,
            'res_model': 'mrp.bom',
            'view_mode': 'list,form',
            'domain': [
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
            ],
            'target': 'current',
        }

    def _pf_open_blocking(self):
        """Abre las entregas (albaranes) que retienen el producto."""
        self.ensure_one()
        pickings = self._pf_blocking_pickings()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s entrega(s) que lo reservan') % len(pickings),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def _pf_blocking_pickings(self):
        """Albaranes de salida no terminados que reservan el producto."""
        self.ensure_one()
        return self.env['stock.picking'].sudo().search([
            ('state', 'not in', ('done', 'cancel')),
            ('picking_type_id.code', '=', 'outgoing'),
            ('move_line_ids.product_id', '=', self.product_id.id),
            ('move_line_ids.state', 'not in', ('done', 'cancel')),
            ('move_line_ids.quantity', '>', 0),
            ('move_line_ids.location_id.usage', '=', 'internal'),
        ])

    def _pf_open_create_production(self):
        """Abre/crea la OF del producto (bloquea si no hay BOM)."""
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        if not Remedy._pf_has_bom(self.product_id):
            raise UserError(_(
                'El producto "%s" no tiene lista de materiales (BOM): no se '
                'puede crear una Orden de Fabricación real. Crea la BOM o usa '
                'Ajuste de inventario.') % self.product_id.display_name)
        bom = self.env['mrp.bom']._bom_find(self.product_id).get(self.product_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva Orden de Fabricación'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_product_id': self.product_id.id,
                'default_product_qty': self.deficit_qty or 1.0,
                'default_bom_id': bom.id if bom else False,
            },
        }

    def _pf_open_buy_components(self):
        """Compra Rápida prellenada con los componentes faltantes de la BOM."""
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        missing = Remedy._pf_missing_components(
            self.product_id, self.deficit_qty or 1.0)
        if not missing:
            return self._pf_open_buy_product()
        return self._pf_open_quick_purchase(
            [(m['product'], m['need']) for m in missing],
            title=_('Compra Rápida (componentes)'))

    def _pf_open_buy_product(self):
        """Compra Rápida prellenada con el producto faltante (sin venta)."""
        self.ensure_one()
        return self._pf_open_quick_purchase(
            [(self.product_id, self.deficit_qty or 1.0)],
            title=_('Compra Rápida (producto)'))

    def _pf_open_quick_purchase(self, product_qty_list, title):
        """Crea el asistente de Compra Rápida con líneas prellenadas."""
        self.ensure_one()
        line_vals = []
        for product, qty in product_qty_list:
            vals = {
                'product_id': product.id,
                'product_qty': qty or 1.0,
                'product_uom_id': product.uom_id.id,
                'material_received': False,
            }
            if product.seller_ids:
                vals['partner_id'] = product.seller_ids[0].partner_id.id
            line_vals.append((0, 0, vals))
        wizard = self.env['mrp.quick.purchase.wizard'].create({
            'sale_order_id': False,
            'purchase_line_ids': line_vals,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'mrp.quick.purchase.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
