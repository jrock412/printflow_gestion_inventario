# -*- coding: utf-8 -*-
"""Wizard GENÉRICO de autorización de una excepción formal (PrintFlow · F4).

Lo abre CUALQUIER superficie de GI (bandeja de lote, bandeja de fallas, etc.) a
través de ``printflow.finding.exception._pf_authorize_action(...)``. Captura el
MOTIVO y confirma; al aceptar delega en
``printflow.finding.exception._pf_authorize`` (autorización PERSISTENTE con
motivo + autorizador). NO toca inventario.

Contrato::

    action = env['printflow.finding.exception']._pf_authorize_action(
        'lot_unassigned_finished', 'mrp.production', mo.id)
    wiz = env['printflow.finding.exception.authorize'].browse(action['res_id'])
    wiz.action_authorize()
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PrintflowFindingExceptionAuthorize(models.TransientModel):
    """Modal que autoriza un hallazgo formal sobre un registro dado."""

    _name = 'printflow.finding.exception.authorize'
    _description = 'Autorizar excepción formal (PrintFlow)'

    finding_code = fields.Char(
        string='Hallazgo', required=True, readonly=True,
        help='Clave del hallazgo formal (lista blanca del registry).')
    finding_label = fields.Char(
        string='Hallazgo', compute='_compute_finding_label')
    target_model = fields.Char(
        string='Modelo destino', required=True, readonly=True)
    target_id = fields.Integer(
        string='Id destino', required=True, readonly=True)
    target_label = fields.Char(
        string='Registro afectado', readonly=True)
    lot_id = fields.Many2one(
        'stock.lot', string='Lote', readonly=True,
        help='Lote del hallazgo (solo en hallazgos basados en lote).')
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True)
    source_model = fields.Char(string='Modelo origen', readonly=True)
    source_id = fields.Integer(string='Id origen', readonly=True)
    source_label = fields.Char(string='Documento origen', readonly=True)
    reason = fields.Text(
        string='Motivo',
        help='Justificación de por qué se autoriza el hallazgo como excepción. '
             'Queda guardada junto con quién autoriza.')

    @api.depends('finding_code')
    def _compute_finding_label(self):
        Registry = self.env['printflow.finding.exception.registry']
        for rec in self:
            rec.finding_label = Registry._pf_label(rec.finding_code)

    def action_authorize(self):
        """Autoriza el hallazgo (guardia + motivo + bitácora). NO toca stock."""
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_('Debes indicar el motivo de la autorización.'))
        self.env['printflow.finding.exception']._pf_authorize(
            self.finding_code,
            self.target_model,
            self.target_id,
            reason=self.reason,
            target_label=self.target_label,
            lot_id=self.lot_id.id or False,
            source_model=self.source_model or '',
            source_id=self.source_id or 0,
            source_label=self.source_label or '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('PrintFlow'),
                'message': _(
                    'Hallazgo "%s" autorizado como excepción. El inventario no '
                    'se ha tocado.') % (self.finding_label or self.finding_code),
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
