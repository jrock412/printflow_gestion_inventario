# -*- coding: utf-8 -*-
"""Escáner de diagnóstico de producto (PrintFlow Diagnostic - FASE 2).

Punto de entrada del diagnóstico de PRODUCTO. Es de SOLO LECTURA: ejecuta el
motor de chequeos extensible una sola vez al crear el wizard y persiste el
resultado (hallazgos + evidencias) en un único ``create``.

Diseño:
  * El motor vive en ``printflow.product.check.mixin``. Aquí NO hay reglas de
    negocio: solo se resuelve el ámbito, se ejecuta el barrido y se resume.
  * Cada chequeo corre aislado en try/except: si uno falla, se reporta como
    advertencia ("chequeo no disponible") y el barrido continúa.
  * Toda navegación se construye como ``ir.actions.act_window`` EXPLÍCITA
    (modelo + dominio + res_id). Nunca se referencia un xmlid de una acción o
    menú de PrintFlow.
"""

import logging

from odoo import _, api, fields, models

from ..models.printflow_product_check_mixin import (
    ACTION_KIND_SELECTION,
    AREA_SELECTION,
    CAUSANTE_TYPE_SELECTION,
    SEVERITY_SELECTION,
)

_logger = logging.getLogger(__name__)

# Referencia al mecanismo del core que gobierna el bloqueo de archivado. Se
# expone en pantalla para que el diagnóstico sea trazable.
CORE_REFERENCE = 'sale_mrp/models/mrp_bom.py::_ensure_bom_is_free (Odoo 17 CE)'

ORIGIN_SELECTION = [
    ('order', 'Pedido'),
    ('product', 'Ficha de producto'),
    ('bom', 'Lista de materiales'),
    ('standalone', 'Independiente'),
]

OVERALL_SELECTION = [
    ('ok', 'Sin incidencias'),
    ('warning', 'Con advertencias'),
    ('error', 'Con errores'),
]

# Modelo de la Bandeja de Resolución: agrega las evidencias recolectables.
EVIDENCE_MODEL = 'printflow.product.diagnostic.evidence'


def _pf_resolution_tray_action(env, domain, scanner_id):
    """Construye la acción de la Bandeja de Resolución (v1, SOLO LECTURA).

    La bandeja es una lista de ``printflow.product.diagnostic.evidence`` con
    ``collectible = True``, filtrada por hallazgo (``finding_id``) o por escáner
    (``scanner_id``). Se abre a pantalla completa (``target='current'``) y deja
    el ``scanner_id`` en el contexto para poder volver al diagnóstico.
    """
    return {
        'type': 'ir.actions.act_window',
        'name': _('Bandeja de Resolución'),
        'res_model': EVIDENCE_MODEL,
        'view_mode': 'tree',
        'domain': domain,
        'context': {
            'pf_scanner_id': scanner_id,
            # Agrupación por defecto: un bloque por tipo de causante.
            'search_default_group_causante': 1,
        },
        'target': 'current',
    }


class PrintflowProductDiagnosticWizard(models.TransientModel):
    """Escáner de diagnóstico de uno o varios productos."""

    _name = 'printflow.product.diagnostic.wizard'
    _description = 'Diagnóstico de producto (PrintFlow)'

    # ── Ámbito ─────────────────────────────────────────────────────────
    product_id = fields.Many2one('product.product', string='Producto')
    product_tmpl_id = fields.Many2one('product.template', string='Plantilla')
    product_ids = fields.Many2many(
        'product.product', string='Productos a diagnosticar',
    )

    # ── Origen (para el botón "Volver") ────────────────────────────────
    origin = fields.Selection(ORIGIN_SELECTION, string='Origen', default='standalone')
    origin_model = fields.Char(string='Modelo de origen')
    origin_res_id = fields.Integer(string='Id de origen')
    origin_label = fields.Char(string='Etiqueta de origen')
    origin_action = fields.Char(
        string='Acción de retorno',
        help='Método del registro de origen a invocar para reabrir su pantalla.',
    )

    # ── Resultado del barrido ──────────────────────────────────────────
    overall_severity = fields.Selection(
        OVERALL_SELECTION, string='Resultado', default='ok',
    )
    error_count = fields.Integer(string='Errores')
    warning_count = fields.Integer(string='Advertencias')
    check_total = fields.Integer(string='Chequeos ejecutados')
    headline = fields.Char(string='Titular')
    core_reference = fields.Char(string='Regla del core', readonly=True)

    finding_ids = fields.One2many(
        'printflow.product.diagnostic.finding', 'wizard_id',
        string='Hallazgos',
    )

    # ══════════════════════════════════════════════════════════════════════
    # CREACIÓN: resuelve ámbito y corre el motor UNA sola vez
    # ══════════════════════════════════════════════════════════════════════
    @api.model_create_multi
    def create(self, vals_list):
        """Calcula el barrido y crea el wizard en UN SOLO write.

        El barrido depende SOLO del ámbito (productos/origen), nunca de campos
        transitorios. Se mezcla en los ``vals`` antes de ``super().create()``
        para no necesitar un ``write()`` posterior.
        """
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            ctx = self._pf_build_context(vals)
            snapshot = self._build_scan_snapshot(ctx)
            merged = dict(vals)
            merged.update(snapshot)
            prepared.append(merged)
        return super().create(prepared)

    @api.model
    def _pf_extract_ids(self, raw):
        """Normaliza el valor de un Many2many de ``vals`` a una lista de ids.

        En ``create`` un Many2many llega como lista de comandos
        (``[(6, 0, ids)]``, ``[(4, id)]``...). Aquí se resuelve a mano.
        """
        if not raw:
            return []
        if isinstance(raw, (list, tuple)):
            if raw and all(isinstance(item, int) for item in raw):
                return list(raw)
            ids = []
            for command in raw:
                if not isinstance(command, (list, tuple)) or not command:
                    continue
                if command[0] == 6:
                    return list(command[2] or [])
                if command[0] == 4:
                    ids.append(command[1])
            return ids
        return []

    @api.model
    def _pf_resolve_scope(self, vals):
        """Resuelve el ámbito del diagnóstico a partir de los ``vals``.

        Prioriza ``product_id`` > ``product_ids`` y completa con la plantilla.
        Devuelve ``(products, tmpl, product)``.
        """
        Product = self.env['product.product']
        products = Product
        product = Product
        tmpl = self.env['product.template']

        product_id = vals.get('product_id')
        if product_id:
            product = Product.browse(product_id).exists()
            products |= product

        tmpl_id = vals.get('product_tmpl_id')
        if tmpl_id:
            tmpl = self.env['product.template'].browse(tmpl_id).exists()

        ids = self._pf_extract_ids(vals.get('product_ids'))
        if ids:
            products |= Product.browse(ids).exists()

        if not product and len(products) == 1:
            product = products
        if not tmpl and product:
            tmpl = product.product_tmpl_id
        if not tmpl and products:
            templates = products.mapped('product_tmpl_id')
            tmpl = templates if len(templates) == 1 else self.env['product.template']
        if not products and tmpl:
            products = tmpl.product_variant_ids
        return products, tmpl, product

    @api.model
    def _pf_build_context(self, vals):
        """Construye el ``ctx`` que consumen los chequeos a partir de ``vals``."""
        products, tmpl, product = self._pf_resolve_scope(vals)
        return {
            'env': self.env,
            'products': products,
            'product': product,
            'tmpl': tmpl,
            'origin': vals.get('origin') or 'standalone',
            'origin_model': vals.get('origin_model'),
            'origin_res_id': vals.get('origin_res_id'),
            'origin_label': vals.get('origin_label'),
            'origin_action': vals.get('origin_action'),
        }

    @api.model
    def _build_scan_snapshot(self, ctx):
        """Ejecuta el barrido sobre ``ctx`` y devuelve los ``vals`` a persistir."""
        finding_vals = self._pf_run_checks(ctx)
        errors = sum(1 for finding in finding_vals if finding['severity'] == 'error')
        warnings = sum(1 for finding in finding_vals if finding['severity'] == 'warning')
        overall = 'error' if errors else ('warning' if warnings else 'ok')
        product = ctx.get('product')
        tmpl = ctx.get('tmpl')

        snapshot = {
            'overall_severity': overall,
            'error_count': errors,
            'warning_count': warnings,
            'check_total': len(self.env['printflow.product.check.mixin']._pf_get_checks()),
            'headline': self._pf_headline(errors, warnings, ctx.get('products') or self.env['product.product']),
            'core_reference': CORE_REFERENCE,
            'finding_ids': [(0, 0, finding) for finding in finding_vals],
        }
        if product:
            snapshot['product_id'] = product.id
        if tmpl and len(tmpl) == 1:
            snapshot['product_tmpl_id'] = tmpl.id
        return snapshot

    @api.model
    def _pf_run_checks(self, ctx):
        """Ejecuta los chequeos registrados y devuelve los hallazgos.

        El motor es robusto: cada chequeo corre dentro de try/except; si falla,
        se emite un hallazgo de severidad ``warning`` ("chequeo no disponible")
        y el barrido continúa con los demás.
        """
        mixin = self.env['printflow.product.check.mixin']
        collected = []
        ctx = dict(ctx)
        ctx['add_finding'] = collected.append

        findings = []
        checks = sorted(
            mixin._pf_get_checks(),
            key=lambda check: (check.get('area') or '', check.get('sequence') or 0),
        )
        for check in checks:
            try:
                result = check['method'](ctx) or []
            except Exception as exc:  # noqa: BLE001 - el motor debe sobrevivir
                _logger.exception(
                    'PrintFlow: falló el chequeo %s', check.get('code'))
                result = [mixin._pf_finding(
                    check.get('code') or 'unknown',
                    check.get('area') or 'record',
                    'warning',
                    _('Chequeo no disponible: %s') % (check.get('code') or ''),
                    detail=_('El chequeo se omitió por un error: %s') % exc,
                )]
            if isinstance(result, dict):
                result = [result]
            # El ``sequence`` lo define cada ``_pf_finding`` (default 0); no hay
            # un ``setdefault`` muerto que sobrescribir.
            findings.extend(result)
        # Hallazgos emitidos con el callback ctx['add_finding'] (extensibilidad).
        findings.extend(collected)
        return findings

    @api.model
    def _pf_headline(self, errors, warnings, products):
        """Titular de una línea que resume el barrido."""
        total = len(products)
        if errors and warnings:
            return _('%d error(es) y %d advertencia(s) en %d producto(s).') % (
                errors, warnings, total)
        if errors:
            return _('%d error(es) detectado(s) en %d producto(s).') % (errors, total)
        if warnings:
            return _('%d advertencia(s) en %d producto(s).') % (warnings, total)
        return _('Sin incidencias en %d producto(s).') % total

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES
    # ══════════════════════════════════════════════════════════════════════
    def action_recalculate(self):
        """Recalcula el barrido sobre el MISMO wizard (sin recrearlo)."""
        self.ensure_one()
        vals = {
            'product_id': self.product_id.id,
            'product_tmpl_id': self.product_tmpl_id.id,
            'product_ids': [(6, 0, self.product_ids.ids)],
            'origin': self.origin,
            'origin_model': self.origin_model,
            'origin_res_id': self.origin_res_id,
            'origin_label': self.origin_label,
            'origin_action': self.origin_action,
        }
        snapshot = self._build_scan_snapshot(self._pf_build_context(vals))
        snapshot['finding_ids'] = [(5, 0, 0)] + snapshot.get('finding_ids', [])
        self.write(snapshot)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Producto'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current' if self.origin == 'order' else 'new',
        }

    def action_open_product(self):
        """Abre la ficha real del producto (pantalla completa)."""
        self.ensure_one()
        product = self.product_id or self.product_ids[:1]
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': product.display_name,
            'res_model': 'product.product',
            'res_id': product.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_back_to_origin(self):
        """Vuelve al origen: reabre su pantalla o cierra el diálogo."""
        self.ensure_one()
        if self.origin_action and self.origin_model and self.origin_res_id:
            record = self.env[self.origin_model].browse(self.origin_res_id).exists()
            handler = getattr(record, self.origin_action, None) if record else None
            if handler:
                return handler()
        return {'type': 'ir.actions.act_window_close'}

    def action_open_resolution_tray(self):
        """Abre la Bandeja de Resolución con TODO el barrido (solo lectura).

        Reúne los causantes recolectables (``collectible = True``) de todos los
        hallazgos de este escáner para trabajarlos de un tirón. v1: solo listar,
        seleccionar y navegar; NO modifica datos.
        """
        self.ensure_one()
        return _pf_resolution_tray_action(
            self.env,
            [('collectible', '=', True), ('scanner_id', '=', self.id)],
            self.id,
        )


class PrintflowProductDiagnosticFinding(models.TransientModel):
    """Hallazgo de un chequeo sobre el ámbito diagnosticado."""

    _name = 'printflow.product.diagnostic.finding'
    _description = 'Hallazgo del diagnóstico de producto (PrintFlow)'
    _rec_name = 'title'
    # Errores primero (severity_rank), luego por área, secuencia del chequeo e id.
    _order = 'severity_rank, area, sequence, id'

    # Prioridad de orden derivada de la severidad (error=0 ... ok=3). Se almacena
    # porque ``_order`` necesita una columna real, no un valor calculado al vuelo.
    SEVERITY_RANK = {'error': 0, 'warning': 1, 'info': 2, 'ok': 3}

    wizard_id = fields.Many2one(
        'printflow.product.diagnostic.wizard', string='Diagnóstico',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Secuencia')
    check_code = fields.Char(string='Chequeo')
    area = fields.Selection(AREA_SELECTION, string='Área')
    severity = fields.Selection(SEVERITY_SELECTION, string='Severidad')
    severity_rank = fields.Integer(
        string='Prioridad', compute='_compute_severity_rank', store=True,
    )
    title = fields.Char(string='Título')
    detail = fields.Text(string='Detalle')
    action_hint = fields.Char(
        string='Dónde corregir',
        help='Pista corta y accionable de dónde resolver el hallazgo.',
    )
    highlighted = fields.Boolean(string='Destacado')
    record_count = fields.Integer(string='Nº de registros')

    product_id = fields.Many2one('product.product', string='Producto')
    nav_kind = fields.Selection([
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
    ], string='Tipo de navegación', default='none')
    res_model = fields.Char(string='Modelo destino')
    res_id = fields.Integer(string='Id destino')
    bom_id = fields.Many2one('mrp.bom', string='BOM')
    sale_order_id = fields.Many2one('sale.order', string='Pedido')
    orderpoint_id = fields.Many2one(
        'stock.warehouse.orderpoint', string='Regla de reorden')
    mo_id = fields.Many2one('mrp.production', string='Orden de fabricación')

    evidence_ids = fields.One2many(
        'printflow.product.diagnostic.evidence', 'finding_id', string='Evidencias',
    )

    @api.depends('severity')
    def _compute_severity_rank(self):
        """Traduce la severidad a la prioridad de orden (error primero)."""
        for finding in self:
            finding.severity_rank = self.SEVERITY_RANK.get(
                finding.severity, len(self.SEVERITY_RANK))

    def _pf_sale_order_target_ids(self):
        """Ids de los pedidos que resuelven el hallazgo (evidencias + propio).

        Combina los ``sale_order`` de las evidencias con el ``sale_order_id`` del
        hallazgo, sin duplicados y preservando el orden de aparición.
        """
        self.ensure_one()
        order_ids = self.evidence_ids.mapped('sale_order_id').ids
        if self.sale_order_id:
            order_ids.append(self.sale_order_id.id)
        return list(dict.fromkeys(order_ids))

    def action_open(self):
        """Navega al registro real que explica el hallazgo (target='current')."""
        self.ensure_one()
        return self._pf_nav_action(self.nav_kind or 'none')

    def _pf_nav_action(self, target):
        """Construye la acción de navegación para un destino del vocabulario.

        ``target`` usa el vocabulario ``nav_kind`` documentado en el módulo. Las
        extensiones del hallazgo pueden sobrescribirlo con ``super()`` para
        agregar destinos nuevos (p. ej. ``reserving_sale_orders``).
        """
        self.ensure_one()
        nav = target or 'none'
        action = {
            'type': 'ir.actions.act_window',
            'name': self.title or _('Detalle'),
            'target': 'current',
        }
        if nav == 'sale_orders':
            order_ids = self._pf_sale_order_target_ids()
            action.update(
                res_model='sale.order', view_mode='tree,form',
                domain=[('id', 'in', order_ids)],
                name=_('%s pedido(s) por resolver') % len(order_ids),
            )
            return action
        if nav == 'mo_list':
            mo_ids = self.evidence_ids.mapped('mo_id').ids
            action.update(
                res_model='mrp.production', view_mode='tree,form',
                domain=[('id', 'in', mo_ids)],
                name=_('%s orden(es) de fabricación') % len(mo_ids),
            )
            return action
        if nav == 'quants' and self.product_id:
            action.update(
                res_model='stock.quant', view_mode='list',
                domain=[('product_id', '=', self.product_id.id),
                        ('location_id.usage', '=', 'internal')],
                name=_('Existencias de %s') % self.product_id.display_name,
            )
            return action
        if nav == 'bom_list' and self.product_id:
            action.update(
                res_model='mrp.bom', view_mode='list',
                domain=[('product_tmpl_id', '=',
                         self.product_id.product_tmpl_id.id)],
                name=_('BOM de %s') % self.product_id.product_tmpl_id.display_name,
            )
            return action
        if nav == 'sale_lines' and self.product_id:
            action.update(
                res_model='sale.order.line', view_mode='list',
                domain=[('product_id', '=', self.product_id.id),
                        ('state', '=', 'sale')],
                name=_('Líneas de venta de %s') % self.product_id.display_name,
            )
            return action
        target = {
            'sale_order': (self.sale_order_id, 'sale.order'),
            'bom': (self.bom_id, 'mrp.bom'),
            'orderpoint': (self.orderpoint_id, 'stock.warehouse.orderpoint'),
            'mo': (self.mo_id, 'mrp.production'),
            'product': (self.product_id, 'product.product'),
        }.get(nav)
        if target and target[0]:
            record = target[0]
            action.update(
                res_model=target[1], res_id=record.id, view_mode='form',
                name=record.display_name,
            )
            return action
        if self.res_model and self.res_id:
            action.update(
                res_model=self.res_model, res_id=self.res_id, view_mode='form',
            )
            return action
        return {'type': 'ir.actions.act_window_close'}

    def action_open_resolution_tray(self):
        """Abre la Bandeja de Resolución filtrada a ESTE hallazgo (solo lectura).

        Reúne sus causantes recolectables (``collectible = True``). v1: solo
        listar, seleccionar y navegar; NO modifica datos.
        """
        self.ensure_one()
        return _pf_resolution_tray_action(
            self.env,
            [('collectible', '=', True), ('finding_id', '=', self.id)],
            self.wizard_id.id,
        )


class PrintflowProductDiagnosticEvidence(models.TransientModel):
    """Evidencia concreta (registro navegable) de un hallazgo."""

    _name = 'printflow.product.diagnostic.evidence'
    _description = 'Evidencia del diagnóstico de producto (PrintFlow)'
    _rec_name = 'label'
    _order = 'sequence, id'

    finding_id = fields.Many2one(
        'printflow.product.diagnostic.finding', string='Hallazgo',
        required=True, ondelete='cascade',
    )
    sequence = fields.Integer(string='Secuencia')
    label = fields.Char(string='Etiqueta')
    detail = fields.Text(string='Detalle')
    nav_kind = fields.Selection([
        ('none', 'Sin navegación'),
        ('product', 'Producto'),
        ('quants', 'Existencias'),
        ('bom', 'BOM'),
        ('sale_order', 'Pedido'),
        ('orderpoint', 'Regla de reorden'),
        ('mo', 'Orden de fabricación'),
    ], string='Tipo de navegación', default='none')
    res_model = fields.Char(string='Modelo destino')
    res_id = fields.Integer(string='Id destino')
    product_id = fields.Many2one('product.product', string='Producto')
    sale_order_id = fields.Many2one('sale.order', string='Pedido')
    bom_id = fields.Many2one('mrp.bom', string='BOM')
    orderpoint_id = fields.Many2one(
        'stock.warehouse.orderpoint', string='Regla de reorden')
    mo_id = fields.Many2one('mrp.production', string='Orden de fabricación')

    # ── Bandeja de Resolución (v1, solo lectura) ───────────────────────
    # Todos los campos nuevos tienen default: no requieren migración.
    causante_type = fields.Selection(
        CAUSANTE_TYPE_SELECTION, string='Tipo de causante', default='other',
        help='Naturaleza del registro que causa el hallazgo.',
    )
    collectible = fields.Boolean(
        string='Recolectable', default=False,
        help='Si está marcado, el causante entra en la Bandeja de Resolución.',
    )
    scanner_id = fields.Many2one(
        'printflow.product.diagnostic.wizard', string='Escáner',
        related='finding_id.wizard_id', store=True,
        help='Escáner que originó la evidencia (para filtrar la bandeja).',
    )
    ref_name = fields.Char(
        string='Referencia',
        help='Referencia principal del causante (pedido, BOM, MO, ubicación...).',
    )
    partner_name = fields.Char(
        string='Cliente / proveedor / almacén',
        help='Actor asociado al causante según su tipo.',
    )
    qty = fields.Float(
        string='Cantidad',
        help='Cantidad principal del causante (pedida/mín/requerida).',
    )
    qty_secondary = fields.Float(
        string='Cantidad secundaria',
        help='Cantidad secundaria del causante (entregado/máx/libre/reservado).',
    )
    state_label = fields.Char(
        string='Estado',
        help='Estado legible del causante (facturación, tipo de BOM, MO...).',
    )
    date_ref = fields.Datetime(
        string='Fecha de referencia',
        help='Fecha de referencia del causante (pedido, MO...).',
    )
    action_kind = fields.Selection(
        ACTION_KIND_SELECTION, string='Acción', default='none',
        help='Acción futura de la bandeja. En v1 solo existe la navegación.',
    )
    area = fields.Selection(
        related='finding_id.area', store=True, string='Área',
        help='Área del hallazgo (para agrupar la bandeja).',
    )
    severity = fields.Selection(
        related='finding_id.severity', store=True, string='Severidad',
        help='Severidad del hallazgo (para agrupar la bandeja).',
    )

    def action_open(self):
        """Navega al registro de la evidencia (target='current')."""
        self.ensure_one()
        nav = self.nav_kind or 'none'
        action = {
            'type': 'ir.actions.act_window',
            'name': self.label or _('Detalle'),
            'target': 'current',
        }
        if nav == 'quants' and self.product_id:
            action.update(
                res_model='stock.quant', view_mode='list',
                domain=[('product_id', '=', self.product_id.id),
                        ('location_id.usage', '=', 'internal')],
            )
            return action
        target = {
            'sale_order': (self.sale_order_id, 'sale.order'),
            'bom': (self.bom_id, 'mrp.bom'),
            'orderpoint': (self.orderpoint_id, 'stock.warehouse.orderpoint'),
            'mo': (self.mo_id, 'mrp.production'),
            'product': (self.product_id, 'product.product'),
        }.get(nav)
        if target and target[0]:
            action.update(
                res_model=target[1], res_id=target[0].id, view_mode='form',
                name=target[0].display_name,
            )
            return action
        if self.res_model and self.res_id:
            action.update(
                res_model=self.res_model, res_id=self.res_id, view_mode='form',
            )
            return action
        return {'type': 'ir.actions.act_window_close'}

    # ------------------------------------------------------------------
    # BANDEJA DE RESOLUCIÓN (v1: listar + seleccionar + navegar, sin cambios)
    # ------------------------------------------------------------------
    def _pf_selected_evidences(self):
        """Evidencias sobre las que actúa un botón de cabecera de la bandeja.

        En los botones ``<header>`` de una lista, Odoo invoca el método con los
        registros seleccionados como ``self`` y además deja ``active_ids`` en el
        contexto. Se contemplan ambos casos para no depender de uno solo.
        """
        active_ids = self.env.context.get('active_ids')
        if active_ids:
            return self.browse(active_ids).exists()
        return self

    def _pf_open_selected_notification(self, message):
        """Notificación (no bloqueante) para la bandeja. No modifica datos."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': _('Bandeja de Resolución'),
                'message': message,
                'sticky': False,
            },
        }

    def action_open_selected(self):
        """Abre en una lista los registros reales de las filas seleccionadas.

        v1: SOLO navegación. Si los seleccionados apuntan a un único modelo
        destino, se abre su lista filtrada por los ids reales; si son de modelos
        mixtos, se pide filtrar por tipo. Nunca modifica datos.
        """
        evidences = self._pf_selected_evidences()
        targets = evidences.filtered(lambda ev: ev.res_model and ev.res_id)
        if not targets:
            return self._pf_open_selected_notification(_(
                'Selecciona al menos una fila con un registro destino para '
                'poder abrirlo.'))
        res_models = set(targets.mapped('res_model'))
        if len(res_models) > 1:
            return self._pf_open_selected_notification(_(
                'La selección mezcla varios tipos de registro. Filtra por un '
                'tipo de causante para abrirlos juntos (solo navegación).'))
        res_model = targets[0].res_model
        res_ids = list(dict.fromkeys(targets.mapped('res_id')))
        records = self.env[res_model].browse(res_ids).exists()
        if not records:
            return self._pf_open_selected_notification(_(
                'Los registros seleccionados ya no existen.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Registros seleccionados (%s)') % len(records),
            'res_model': res_model,
            'view_mode': 'tree,form',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }

    def action_back_to_scanner(self):
        """Reabre el escáner de diagnóstico que originó la bandeja."""
        scanner_id = self.env.context.get('pf_scanner_id')
        if not scanner_id:
            scanner_id = self._pf_selected_evidences()[:1].scanner_id.id
        wizard = self.env['printflow.product.diagnostic.wizard'].browse(
            scanner_id).exists()
        if not wizard:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Producto'),
            'res_model': 'printflow.product.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_back_to_resolution_tray(self):
        """Reabre la Bandeja de Resolución del hallazgo (solo navegación).

        Reutiliza el mismo constructor de acción que el resto de la bandeja:
        los causantes recolectables del hallazgo de esta evidencia. Conserva el
        ``scanner_id`` del contexto (o el de la propia evidencia) para que el
        botón "Volver al diagnóstico" siga funcionando al regresar.
        """
        self.ensure_one()
        scanner_id = (
            self.env.context.get('pf_scanner_id') or self.scanner_id.id)
        return _pf_resolution_tray_action(
            self.env,
            [('collectible', '=', True), ('finding_id', '=', self.finding_id.id)],
            scanner_id,
        )
