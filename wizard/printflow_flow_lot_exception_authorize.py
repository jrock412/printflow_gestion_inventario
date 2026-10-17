# -*- coding: utf-8 -*-
"""Wizard de AUTORIZACIÓN de un lote como excepción documentada (PrintFlow).

La BANDEJA de lote (``printflow.flow.lot.tray``) abre este modal con el botón de
fila "Autorizar excepción" para capturar el MOTIVO. Al confirmar, delega en
``printflow.stock.health._pf_authorize_lot_exception`` (autorización PERSISTENTE
con motivo + autorizador) y el detector de mezcla deja de reportar el lote.

Por qué un modal y no el selector
---------------------------------
El caso real (un lote ya asignado que debe declararse INTENCIONAL) no admite
"reasignar": el lote ya está en el documento y el selector bloquea un lote igual
al actual. Este wizard autoriza la asignación ACTUAL sin tocar el lote.

La escritura no vive aquí: la ejecuta el motor. Este wizard solo captura el
motivo y pasa por la guardia ``printflow.stock.remedy._pf_assert_can_clean``
(jefe de taller/admin).

Contrato::

    wiz = env['printflow.flow.lot.exception.authorize'].create({...})
    action = wiz.action_authorize()   # guardia + motivo + autorización
"""

from odoo import _, fields, models
from odoo.exceptions import UserError


class PrintflowFlowLotExceptionAuthorize(models.TransientModel):
    """Modal que autoriza un lote como excepción documentada."""

    _name = 'printflow.flow.lot.exception.authorize'
    _description = 'Autorizar lote como excepción (PrintFlow)'

    lot_id = fields.Many2one(
        'stock.lot', string='Lote', required=True, readonly=True,
        ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True)
    lot_name = fields.Char(
        string='Lote', related='lot_id.name', readonly=True)
    reason = fields.Text(
        string='Motivo',
        help='Justificación de por qué se autoriza compartir este lote entre '
             'pedidos. Queda guardada junto con quién autoriza.')
    source_model = fields.Char(string='Modelo origen', readonly=True)
    source_id = fields.Integer(string='Id origen', readonly=True)
    source_label = fields.Char(string='Documento origen', readonly=True)

    def action_authorize(self):
        """Autoriza el lote (guardia + motivo + escritura en el motor)."""
        self.ensure_one()
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        if not self.lot_id:
            raise UserError(_('No se indicó el lote a autorizar.'))
        if not (self.reason or '').strip():
            raise UserError(_('Debes indicar el motivo de la autorización.'))
        self.env['printflow.stock.health']._pf_authorize_lot_exception(
            self.lot_id,
            reason=self.reason,
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
                    'Lote "%s" autorizado como excepción documentada.') % (
                        self.lot_id.name),
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
