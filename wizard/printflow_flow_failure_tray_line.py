# -*- coding: utf-8 -*-
"""Línea de evidencia de la bandeja genérica de fallas (PrintFlow · Fase 1).

``TransientModel`` de SOLO LECTURA: UNA fila por evidencia que la falla describe
(para la reserva huérfana, un quant afectado). Solo se crea desde
``printflow.flow.failure.tray._pf_populate`` (la superficie no la puebla a mano).

Campos técnicos: ``res_model``/``res_id`` apuntan al registro afectado (el quant)
para poder NAVEGAR a él; ``action_ids`` cuelga las acciones guiadas por fila.
"""

from odoo import _, api, fields, models


class PrintflowFlowFailureTrayLine(models.TransientModel):
    """Una fila de evidencia de la falla (solo lectura)."""

    _name = 'printflow.flow.failure.tray.line'
    _description = 'Línea de evidencia de la bandeja de fallas (PrintFlow)'
    _order = 'sequence, id'

    tray_id = fields.Many2one(
        'printflow.flow.failure.tray', string='Bandeja',
        required=True, ondelete='cascade')
    sequence = fields.Integer(string='Orden', default=10)

    # ── Registro afectado (navegación) ──────────────────────────────────
    res_model = fields.Char(string='Modelo', readonly=True)
    res_id = fields.Integer(string='Id del registro', readonly=True)

    # ── Evidencia ───────────────────────────────────────────────────────
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Lote', readonly=True)
    lot_name = fields.Char(string='Lote', readonly=True)
    location_id = fields.Many2one(
        'stock.location', string='Ubicación', readonly=True)
    physical_qty = fields.Float(
        string='Físico', readonly=True, digits='Product Unit of Measure')
    reserved_qty = fields.Float(
        string='Reservado hoy', readonly=True, digits='Product Unit of Measure')
    support_qty = fields.Float(
        string='Respaldo real', readonly=True, digits='Product Unit of Measure')
    delta_qty = fields.Float(
        string='Delta', readonly=True, digits='Product Unit of Measure')
    support_label = fields.Char(
        string='Lo respalda', readonly=True,
        help='Documentos (albaranes/movimientos) que respaldan el reservado, o '
             '"(sin respaldo)" si ninguno.')
    detail = fields.Char(string='Detalle', readonly=True)

    # ── Acciones guiadas por fila ───────────────────────────────────────
    action_ids = fields.One2many(
        'printflow.flow.failure.tray.action', 'line_id',
        string='Acciones', readonly=True)

    # ── Acción PRINCIPAL (botón directo en la tarjeta de evidencia) ─────
    primary_label = fields.Char(
        string='Acción principal', compute='_compute_primary_action',
        help='Etiqueta de la acción que la falla marca como principal. Es el '
             'texto del botón directo que ve el operador (p. ej. "Reconciliar '
             'la reserva"), sin entrar a "Gestionar".')

    @api.depends('action_ids.primary', 'action_ids.label')
    def _compute_primary_action(self):
        """Expone la etiqueta de la acción principal declarada por la falla."""
        for line in self:
            action = line.action_ids.filtered(lambda act: act.primary)[:1]
            line.primary_label = action.label if action else False

    def action_open(self):
        """Abre ESTA fila en un diálogo (para ver el detalle y las acciones).

        Método PÚBLICO a propósito: Odoo 17 no permite invocar privados desde un
        botón. Solo abre el diálogo; la escritura vive en las acciones guiadas.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.lot_name or self.product_id.display_name or _('Evidencia'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_run_primary(self):
        """Ejecuta la acción PRINCIPAL de la fila (botón DIRECTO). Público.

        Resuelve la acción marcada como principal y delega el despacho en
        ``printflow.flow.failure.tray.action_run`` (lista blanca): la superficie
        no conoce la falla ni decide por tipo, solo reenvía la clave que la
        propia falla declaró. Sin acción principal, cierra la bandeja.
        """
        self.ensure_one()
        action = self.action_ids.filtered(lambda act: act.primary)[:1]
        if not action:
            return {'type': 'ir.actions.act_window_close'}
        return self.tray_id.action_run(line_id=self.id, action_key=action.key)
