# -*- coding: utf-8 -*-
"""Línea del wizard de autorización EN BLOQUE de excepciones formales (PrintFlow).

Modela UN hallazgo a autorizar (finding_code + target_model + target_id) dentro
del wizard ``printflow.finding.exception.authorize.bulk``. Se puebla desde la
selección de una bandeja (una fila por hallazgo).
"""

from odoo import api, fields, models


class PrintflowFindingExceptionAuthorizeLine(models.TransientModel):
    """Un hallazgo a autorizar dentro del bloque."""

    _name = 'printflow.finding.exception.authorize.line'
    _description = 'Línea de autorización en bloque (PrintFlow)'

    wizard_id = fields.Many2one(
        'printflow.finding.exception.authorize.bulk', string='Asistente',
        required=True, ondelete='cascade')
    finding_code = fields.Char(string='Hallazgo', required=True)
    finding_label = fields.Char(
        string='Hallazgo', compute='_compute_finding_label')
    target_model = fields.Char(string='Modelo destino', required=True)
    target_id = fields.Integer(string='Id destino', required=True)
    target_label = fields.Char(string='Registro afectado')
    lot_id = fields.Many2one('stock.lot', string='Lote')

    @api.depends('finding_code')
    def _compute_finding_label(self):
        Registry = self.env['printflow.finding.exception.registry']
        for rec in self:
            rec.finding_label = Registry._pf_label(rec.finding_code)
