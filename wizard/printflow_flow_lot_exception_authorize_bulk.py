# -*- coding: utf-8 -*-
"""Wizard de AUTORIZACIÓN EN BLOQUE de lotes (PrintFlow).

La BANDEJA de lote (``printflow.flow.lot.tray``) lo abre desde el botón de ACCIÓN
SOBRE LA SELECCIÓN ("Autorizar excepción") para capturar UN motivo y autorizar de
una sola vez los lotes de las filas seleccionadas. Reutiliza la autorización
persistente del motor (``printflow.stock.health._pf_authorize_lot_exception``):
un registro ``printflow.lot.exception`` por LOTE DISTINTO (la restricción única
por ``lot_id`` + ``company_id`` evita duplicados).

Por qué un wizard nuevo y no reutilizar el unitario
---------------------------------------------------
El wizard unitario (``printflow.flow.lot.exception.authorize``) modela UN lote con
su documento de origen; forzarlo a "varios lotes" ensuciaría ese contrato. Este
wizard en bloque es más simple y limpio: una lista de lotes + UN motivo.

Contrato::

    wiz = env['printflow.flow.lot.exception.authorize.bulk'].create({...})
    action = wiz.action_authorize()   # guardia + motivo + autorización en bloque
"""

from odoo import _, fields, models
from odoo.exceptions import UserError


class PrintflowFlowLotExceptionAuthorizeBulk(models.TransientModel):
    """Modal que autoriza VARIOS lotes como excepción documentada."""

    _name = 'printflow.flow.lot.exception.authorize.bulk'
    _description = 'Autorizar lotes en bloque como excepción (PrintFlow)'

    lot_ids = fields.Many2many(
        'stock.lot', 'printflow_lot_exc_bulk_lot_rel',
        'wizard_id', 'lot_id', string='Lotes', required=True,
        help='Lotes DISTINTOS a autorizar (uno por excepción).')
    source_label = fields.Char(
        string='Origen', readonly=True,
        help='Etiqueta legible del origen de la autorización (trazabilidad).')
    skipped = fields.Integer(
        string='Omitidos', readonly=True,
        help='Filas seleccionadas que NO se autorizan (ya autorizadas o no '
             'autorizables).')
    reason = fields.Text(
        string='Motivo',
        help='Justificación COMÚN para todos los lotes autorizados. Queda '
             'guardada junto con quién autoriza.')
    finding_code = fields.Char(
        string='Hallazgo', readonly=True,
        help='Clave del hallazgo formal COMÚN a la selección (registry de GI). Si '
             'su destino declarado es el LOTE, al confirmar se autoriza TAMBIÉN '
             'ese hallazgo sobre cada lote, además de la excepción de mezcla.')

    def action_authorize(self):
        """Autoriza TODOS los lotes de la selección (guardia + motivo)."""
        self.ensure_one()
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        if not self.lot_ids:
            raise UserError(_('No hay lotes para autorizar.'))
        if not (self.reason or '').strip():
            raise UserError(_('Debes indicar el motivo de la autorización.'))
        Health = self.env['printflow.stock.health']
        Exception = self.env['printflow.finding.exception']
        source_label = self.source_label or _(
            'Autorización en bloque desde la bandeja de lote')
        for lot in self.lot_ids:
            Health._pf_authorize_lot_exception(
                lot, reason=self.reason, source_label=source_label)
            # ADEMÁS: el hallazgo FORMAL del lote (genérico/sin existencia/mezcla)
            # se autoriza sobre el LOTE, que es lo que declara el registry
            # (H-065). Si el código no aplica al lote, no hace nada.
            Exception._pf_authorize_lot_finding(
                self.finding_code, lot, reason=self.reason,
                source_label=source_label)
        message = _('%s lote(s) autorizado(s).') % len(self.lot_ids)
        if self.skipped:
            message = '%s %s' % (message, _(
                '%s fila(s) omitida(s) (ya autorizadas o no autorizables).'
            ) % self.skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('PrintFlow'),
                'message': message,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
