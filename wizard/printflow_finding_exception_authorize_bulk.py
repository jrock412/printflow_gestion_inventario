# -*- coding: utf-8 -*-
"""Wizard de AUTORIZACIÓN EN BLOQUE de excepciones formales (PrintFlow · F4).

Lo abre una acción sobre la SELECCIÓN de una bandeja (p. ej. la bandeja de lote),
con UNA línea por hallazgo elegible. Captura UN motivo y autoriza de una sola vez
todos los hallazgos listados (cada uno por su ``printflow.finding.exception``; la
restricción única evita duplicados). NO toca inventario.

Contrato::

    wiz = env['printflow.finding.exception.authorize.bulk'].create({
        'line_ids': [(0, 0, {...}), ...], 'reason': '...'})
    wiz.action_authorize()
"""

from odoo import _, fields, models
from odoo.exceptions import UserError


class PrintflowFindingExceptionAuthorizeBulk(models.TransientModel):
    """Modal que autoriza VARIOS hallazgos formales con UN motivo."""

    _name = 'printflow.finding.exception.authorize.bulk'
    _description = 'Autorizar excepciones formales en bloque (PrintFlow)'

    line_ids = fields.One2many(
        'printflow.finding.exception.authorize.line', 'wizard_id',
        string='Excepciones a autorizar')
    source_label = fields.Char(
        string='Origen', readonly=True,
        help='Etiqueta legible del origen de la autorización (trazabilidad).')
    reason = fields.Text(
        string='Motivo',
        help='Justificación COMÚN para todas las excepciones autorizadas.')

    def action_authorize(self):
        """Autoriza TODAS las líneas (guardia + motivo). NO toca stock."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('No hay hallazgos para autorizar.'))
        if not (self.reason or '').strip():
            raise UserError(_('Debes indicar el motivo de la autorización.'))
        Exception = self.env['printflow.finding.exception']
        count = 0
        for line in self.line_ids:
            Exception._pf_authorize(
                line.finding_code, line.target_model, line.target_id,
                reason=self.reason, target_label=line.target_label,
                lot_id=line.lot_id.id or False,
                source_label=self.source_label or '')
            count += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('PrintFlow'),
                'message': _(
                    '%s hallazgo(s) autorizado(s) como excepción. El inventario '
                    'no se ha tocado.') % count,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
