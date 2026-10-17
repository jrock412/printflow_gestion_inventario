# -*- coding: utf-8 -*-
"""Wizard de diagnóstico de archivado de BOM kit (PrintFlow) — FASE 1.

Explica por qué una o varias BOM tipo kit (``phantom``) no se pueden archivar y
lista, con enlaces, las líneas de venta EXACTAS que las bloquean.

Principios de diseño:
  * La AUTORIDAD es el core (``mrp.bom._ensure_bom_is_free``); aquí NO se
    reimplementa la condición. El ``domain`` espejo solo SIRVE para explicar y
    para el guardián anti-desincronización.
  * El snapshot se calcula UNA sola vez al crear el wizard y se persiste en un
    único ``create`` (mismo patrón que ``printflow_order_diagnostic_wizard``).
  * Es de SOLO LECTURA: no archiva, no cancela ni factura nada.
"""

from odoo import _, api, fields, models

# Ruta del core que contiene la regla espejo. Si esta ruta cambia, el wizard lo
# advierte en pantalla mediante los estados ``desync_core_*``.
CORE_REFERENCE = 'sale_mrp/models/mrp_bom.py::_ensure_bom_is_free (Odoo 17 CE)'

GUARD_SELECTION = [
    ('no_kit_bom', 'Sin BOM kit'),
    ('free', 'Libre (el core no bloquea)'),
    ('blocked', 'Bloqueado por ventas'),
    ('desync_core_stricter', 'Desincronización: el core bloquea y el espejo no ve líneas'),
    ('desync_core_laxer', 'Desincronización: el core no bloquea y el espejo sí ve líneas'),
]


class PrintflowBomArchiveDiagnosticWizard(models.TransientModel):
    _name = 'printflow.bom.archive.diagnostic.wizard'
    _description = 'Diagnóstico de archivado de BOM kit (PrintFlow)'

    bom_ids = fields.Many2many(
        'mrp.bom', string='BOM a diagnosticar', required=True,
    )
    product_tmpl_id = fields.Many2one('product.template', string='Producto')
    product_ids = fields.Many2many(
        'product.product', string='Variantes evaluadas',
        help='Variantes cuyas líneas de venta pueden bloquear el archivado.',
    )
    is_blocked = fields.Boolean(string='Bloqueado por el core')
    guard_state = fields.Selection(GUARD_SELECTION, string='Estado del guardián')
    core_reference = fields.Char(
        string='Regla del core', readonly=True,
        help='Ruta y método del core que define qué líneas bloquean el archivado.',
    )
    root_cause_headline = fields.Char(string='Causa raíz')
    root_cause_detail = fields.Text(string='Detalle de la causa raíz')
    blocking_count = fields.Integer(string='Líneas bloqueantes')

    bom_line_ids = fields.One2many(
        'printflow.bom.archive.diagnostic.bom.line', 'wizard_id',
        string='Desglose por BOM',
    )
    blocking_line_ids = fields.One2many(
        'printflow.bom.archive.diagnostic.line', 'wizard_id',
        string='Líneas de venta bloqueantes',
    )

    # ------------------------------------------------------------------
    # CREACIÓN: snapshot una sola vez, un solo write
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Construye el snapshot y crea el wizard en UN SOLO write.

        El snapshot depende SOLO de las BOM (no de campos transitorios). Se
        mezcla en los ``vals`` antes de llamar a ``super().create()`` para no
        necesitar un ``write()`` posterior.
        """
        prepared = []
        for vals in vals_list:
            vals = dict(vals)
            boms = self._pf_boms_from_vals(vals)
            snapshot, bom_line_vals, blocking_line_vals = self._build_bom_snapshot(boms)
            snapshot['core_reference'] = CORE_REFERENCE
            snapshot['bom_line_ids'] = [(0, 0, lv) for lv in bom_line_vals]
            snapshot['blocking_line_ids'] = [(0, 0, lv) for lv in blocking_line_vals]
            merged = dict(vals)
            merged.update(snapshot)
            prepared.append(merged)
        return super().create(prepared)

    @api.model
    def _pf_boms_from_vals(self, vals):
        """Resuelve el recordset de ``mrp.bom`` del comando Many2many de ``vals``.

        En ``create`` el valor de un Many2many llega como lista de comandos
        (``[(6, 0, ids)]``, ``[(4, id)]``...). Se resuelve a mano para poder
        calcular el snapshot ANTES de persistir el wizard.

        :rtype: mrp.bom recordset
        """
        raw = vals.get('bom_ids') or []
        ids = []
        if isinstance(raw, (list, tuple)):
            for cmd in raw:
                if not isinstance(cmd, (list, tuple)) or not cmd:
                    continue
                if cmd[0] == 6:
                    ids = list(cmd[2] or [])
                    break
                if cmd[0] == 4:
                    ids.append(cmd[1])
        return self.env['mrp.bom'].browse(ids)

    # ------------------------------------------------------------------
    # CONSTRUCCIÓN DEL SNAPSHOT
    # ------------------------------------------------------------------
    def _build_bom_snapshot(self, boms):
        """Calcula el diagnóstico completo de un recordset de ``mrp.bom``.

        No lee ningún campo transitorio del wizard (recibe ``boms`` explícito)
        para poder invocarse desde ``create`` antes de existir el registro y
        desde ``action_recalculate`` sin recrearlo.

        :param boms: BOM a diagnosticar.
        :rtype: tuple(vals, bom_line_vals, blocking_line_vals)
        """
        boms = boms.exists()
        vals = {
            'is_blocked': False,
            'guard_state': 'no_kit_bom',
            'root_cause_headline': '',
            'root_cause_detail': '',
            'blocking_count': 0,
            'product_tmpl_id': boms[:1].product_tmpl_id.id if boms else False,
            'product_ids': [(6, 0, boms._pf_archive_blocking_product_ids())],
        }
        kit_boms = boms.filtered(lambda bom: bom.type == 'phantom')

        bom_line_vals = []
        blocking_line_vals = []
        if not kit_boms:
            vals['root_cause_headline'] = _(
                'No hay BOM de tipo kit (phantom) que diagnosticar.')
            vals['root_cause_detail'] = _(
                'El archivado solo está restringido para BOM tipo kit. Las BOM '
                'normales o de subcontratación no pasan por la regla del core.')
            return vals, bom_line_vals, blocking_line_vals

        # AUTORIDAD: la regla real del core.
        is_blocked = kit_boms._pf_is_archive_blocked()
        # ESPEJO: las líneas que el domain del core debería encontrar.
        blocking_lines = kit_boms._pf_get_archive_blocking_sale_lines()

        if is_blocked and not blocking_lines:
            guard_state = 'desync_core_stricter'
        elif not is_blocked and blocking_lines:
            guard_state = 'desync_core_laxer'
        elif is_blocked:
            guard_state = 'blocked'
        else:
            guard_state = 'free'

        vals['is_blocked'] = is_blocked
        vals['guard_state'] = guard_state
        vals['blocking_count'] = len(blocking_lines)
        vals['root_cause_headline'], vals['root_cause_detail'] = \
            self._root_cause_text(guard_state, blocking_lines)

        blocking_line_vals = [
            self._prepare_blocking_line_vals(line, kit_boms)
            for line in blocking_lines
        ]
        bom_line_vals = [self._prepare_bom_line_vals(bom) for bom in boms]
        return vals, bom_line_vals, blocking_line_vals

    @api.model
    def _prepare_blocking_line_vals(self, line, kit_boms):
        """Valores del modelo hijo A para una línea de venta bloqueante."""
        return {
            'sale_order_line_id': line.id,
            'product_uom_qty': line.product_uom_qty,
            'qty_delivered': line.qty_delivered,
            'blocking_bom_ids': [
                (6, 0, self._blocking_boms_for_line(line, kit_boms).ids),
            ],
        }

    @api.model
    def _blocking_boms_for_line(self, line, kit_boms):
        """BOM kit cuyo ámbito de productos incluye el de la línea de venta."""
        return kit_boms.filtered(
            lambda bom: line.product_id in (
                bom.product_id or bom.product_tmpl_id.product_variant_ids
            )
        )

    @api.model
    def _prepare_bom_line_vals(self, bom):
        """Valores del modelo hijo B (desglose por BOM)."""
        is_kit = bom.type == 'phantom'
        if is_kit:
            is_blocked = bom._pf_is_archive_blocked()
            blocking_count = len(bom._pf_get_archive_blocking_sale_lines())
        else:
            is_blocked = False
            blocking_count = 0
        scope = bom.product_id or bom.product_tmpl_id
        variants = bom.product_id or bom.product_tmpl_id.product_variant_ids
        return {
            'bom_id': bom.id,
            'product_scope': scope.display_name,
            'variant_count': len(variants),
            'is_blocked': is_blocked,
            'blocking_line_count': blocking_count,
        }

    @api.model
    def _root_cause_text(self, guard_state, blocking_lines):
        """Devuelve ``(headline, detail)`` de la causa raíz según el estado."""
        if guard_state == 'desync_core_stricter':
            return (
                _('La regla del core cambió: bloquea, pero el espejo no encuentra líneas.'),
                _('El core impide archivar estas BOM, pero el domain espejo no '
                  'encontró líneas de venta. Revisa el método %s del core y '
                  'actualiza el domain espejo del módulo.') % CORE_REFERENCE,
            )
        if guard_state == 'desync_core_laxer':
            return (
                _('La regla del core cambió: NO bloquea, pero el espejo sí encuentra líneas.'),
                _('El core permite archivar estas BOM, pero el domain espejo '
                  'encontró líneas de venta. Revisa el método %s del core y '
                  'actualiza el domain espejo del módulo.') % CORE_REFERENCE,
            )
        if guard_state == 'blocked':
            count = len(blocking_lines)
            return (
                _('No se puede archivar: %s línea(s) de venta pendientes.') % count,
                _('El core bloquea el archivado de estas BOM kit porque existen '
                  '%s línea(s) de pedido confirmadas por entregar o facturar. '
                  'Resuélvelas (entrega, facturación o cancelación de la línea) '
                  'para poder archivar.') % count,
            )
        return (
            _('Ninguna venta pendiente bloquea el archivado.'),
            _('El core no encuentra líneas de pedido confirmadas por entregar o '
              'facturar para las variantes de estas BOM kit: puedes archivarlas.'),
        )

    # ------------------------------------------------------------------
    # RECÁLCULO BAJO DEMANDA
    # ------------------------------------------------------------------
    def action_recalculate(self):
        """Recalcula el diagnóstico sobre el MISMO wizard (sin recrearlo).

        Reutiliza ``_build_bom_snapshot`` (única fuente de verdad) y reemplaza
        las líneas hijas con comandos que primero borran las anteriores
        (``(5, 0, 0)``) y luego crean las nuevas: así nunca quedan huérfanas.
        """
        self.ensure_one()
        snapshot, bom_line_vals, blocking_line_vals = self._build_bom_snapshot(
            self.bom_ids)
        snapshot['core_reference'] = CORE_REFERENCE
        snapshot['bom_line_ids'] = [(5, 0, 0)] + [(0, 0, lv) for lv in bom_line_vals]
        snapshot['blocking_line_ids'] = (
            [(5, 0, 0)] + [(0, 0, lv) for lv in blocking_line_vals]
        )
        self.write(snapshot)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Archivado de BOM (kit)'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class PrintflowBomArchiveDiagnosticLine(models.TransientModel):
    """Modelo hijo A: línea de venta que bloquea el archivado."""
    _name = 'printflow.bom.archive.diagnostic.line'
    _description = 'Línea de venta que bloquea el archivado de una BOM (PrintFlow)'
    _order = 'sale_order_line_id, id'

    wizard_id = fields.Many2one(
        'printflow.bom.archive.diagnostic.wizard', string='Wizard',
        required=True, ondelete='cascade',
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Línea de venta', required=True,
        ondelete='cascade',
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Pedido', related='sale_order_line_id.order_id',
    )
    order_name = fields.Char(
        string='Pedido', related='sale_order_line_id.order_id.name',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Cliente',
        related='sale_order_line_id.order_partner_id',
    )
    product_id = fields.Many2one(
        'product.product', string='Producto',
        related='sale_order_line_id.product_id',
    )
    product_uom_qty = fields.Float(
        string='Cantidad', digits='Product Unit of Measure',
    )
    qty_delivered = fields.Float(
        string='Entregado', digits='Product Unit of Measure',
    )
    invoice_status = fields.Selection(
        string='Facturación', related='sale_order_line_id.invoice_status',
    )
    order_state = fields.Selection(
        string='Estado del pedido', related='sale_order_line_id.order_id.state',
    )
    delivery_status = fields.Selection(
        [('pending', 'Pendiente'), ('delivered', 'Entregado')],
        string='Entrega', compute='_compute_delivery_status',
    )
    blocking_bom_ids = fields.Many2many(
        'mrp.bom', string='BOM que bloquea',
    )

    @api.depends('qty_delivered', 'product_uom_qty')
    def _compute_delivery_status(self):
        """Deriva el estado de entrega de lo entregado vs lo pedido."""
        for line in self:
            line.delivery_status = (
                'delivered'
                if line.qty_delivered >= line.product_uom_qty
                else 'pending'
            )

    def action_open_sale_order(self):
        """Navega al pedido real.

        Usa ``target='current'`` (no ``new``) para cerrar el popup del
        diagnóstico y abrir la pantalla real del pedido, evitando diálogos
        anidados.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pedido de Venta'),
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


class PrintflowBomArchiveDiagnosticBomLine(models.TransientModel):
    """Modelo hijo B: desglose del diagnóstico por cada BOM."""
    _name = 'printflow.bom.archive.diagnostic.bom.line'
    _description = 'Desglose por BOM del diagnóstico de archivado (PrintFlow)'
    _order = 'bom_id, id'

    wizard_id = fields.Many2one(
        'printflow.bom.archive.diagnostic.wizard', string='Wizard',
        required=True, ondelete='cascade',
    )
    bom_id = fields.Many2one(
        'mrp.bom', string='BOM', required=True, ondelete='cascade',
    )
    product_scope = fields.Char(string='Ámbito de producto')
    variant_count = fields.Integer(string='Nº de variantes')
    is_blocked = fields.Boolean(string='Bloqueada')
    blocking_line_count = fields.Integer(string='Líneas bloqueantes')
