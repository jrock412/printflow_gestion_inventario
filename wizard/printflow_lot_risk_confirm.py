# -*- coding: utf-8 -*-
"""Confirmación de RIESGO de las correcciones que TOCAN inventario (PrintFlow · F5).

Las acciones "Crear lote sugerido" y "Corrección automática" de la bandeja de
lote ESCRIBEN inventario/trazabilidad. Por la regla de trabajo
(``regla-trabajo-odoo-17-ce``) y el incidente ``-229``, quedan DEGRADADAS a vía
SECUNDARIA: este modal exige una confirmación explícita (con motivo) antes de
ejecutarlas. La vía PRIMARIA pasa a ser "Autorizar excepción" (no toca stock).

Contrato::

    action = env['printflow.lot.risk.confirm']._pf_open('apply_correction', row)
    env['printflow.lot.risk.confirm'].browse(action['res_id']).action_confirm()
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PrintflowLotRiskConfirm(models.TransientModel):
    """Modal que confirma una corrección de inventario de la bandeja de lote."""

    _name = 'printflow.lot.risk.confirm'
    _description = 'Confirmar corrección de inventario (PrintFlow)'

    action_key = fields.Selection(
        selection=[
            ('create_suggested_lots', 'Crear lote sugerido'),
            ('apply_correction', 'Corrección automática'),
        ],
        string='Acción', required=True, readonly=True)
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True)
    lot_state = fields.Char(string='Estado de lote', readonly=True)
    message = fields.Text(
        string='Aviso', compute='_compute_message', readonly=True)
    reason = fields.Text(
        string='Motivo',
        help='Justificación de la corrección. Se registra en el documento '
             'afectado (bitácora) antes de tocar el inventario.')

    @api.depends('action_key')
    def _compute_message(self):
        messages = {
            'create_suggested_lots': _(
                'Esta acción CREA/ASIGNA el lote sugerido del pedido a la Orden '
                'de Fabricación: ESCRIBE inventario y trazabilidad (no solo '
                'silencio un hallazgo). Si el problema es FORMAL (la MO ya está '
                'terminada sin lote), la vía recomendada es "Autorizar '
                'excepción", que NO toca el inventario.'),
            'apply_correction': _(
                'Esta acción ejecuta el remedio del motor sobre los ítems '
                'seleccionados: ESCRIBE inventario y trazabilidad. Si el '
                'problema es FORMAL, la vía recomendada es "Autorizar '
                'excepción", que NO toca el inventario.'),
        }
        for rec in self:
            rec.message = messages.get(rec.action_key, '')

    @api.model
    def _pf_open(self, action_key, first_row):
        """Crea el modal prellenado y devuelve su ``act_window`` (target ``new``)."""
        wizard = self.create({
            'action_key': action_key,
            'product_id': first_row.product_id.id or False,
            'lot_state': first_row.lot_state or '',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirmar corrección de inventario'),
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        """Ejecuta la acción CONFIRMADA sobre las filas de la bandeja actual."""
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_(
                'Debes indicar el motivo para ejecutar una corrección que toca '
                'el inventario.'))
        domain = [('product_id', '=', self.product_id.id)]
        if self.lot_state:
            domain.append(('lot_state', '=', self.lot_state))
        records = self.env['printflow.flow.lot.tray'].search(domain)
        if self.action_key == 'create_suggested_lots':
            return records.action_create_suggested_lots()
        return records.action_apply_correction()
