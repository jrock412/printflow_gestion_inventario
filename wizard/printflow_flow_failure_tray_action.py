# -*- coding: utf-8 -*-
"""Acción guiada por fila de la bandeja de fallas (PrintFlow · Fase 1).

``TransientModel`` de SOLO LECTURA: cuelga de una línea de evidencia
(``printflow.flow.failure.tray.line``) y declara UNA acción guiada
(``key``/``label``/``kind``/``enabled``/``primary``). La crea la bandeja desde
``_pf_fault_actions`` de la falla: la superficie NO inventa acciones.

``kind``:
  * ``execute``  -> la ejecuta la falla (``_pf_fault_execute``);
  * ``navigate`` -> la resuelve la bandeja (abre un registro/lista);
  * ``close``    -> cierra la bandeja.
"""

from odoo import fields, models

ACTION_KIND_SELECTION = [
    ('execute', 'Ejecutar'),
    ('navigate', 'Navegar'),
    ('close', 'Cerrar'),
]


class PrintflowFlowFailureTrayAction(models.TransientModel):
    """Una acción guiada de una fila de evidencia (solo lectura)."""

    _name = 'printflow.flow.failure.tray.action'
    _description = 'Acción guiada de la bandeja de fallas (PrintFlow)'
    _order = 'sequence, id'

    line_id = fields.Many2one(
        'printflow.flow.failure.tray.line', string='Evidencia',
        required=True, ondelete='cascade')
    tray_id = fields.Many2one(
        'printflow.flow.failure.tray', string='Bandeja',
        related='line_id.tray_id', store=False, readonly=True)
    sequence = fields.Integer(string='Orden', default=10)
    key = fields.Char(string='Clave', readonly=True)
    label = fields.Char(string='Acción', readonly=True)
    kind = fields.Selection(
        ACTION_KIND_SELECTION, string='Tipo', readonly=True)
    enabled = fields.Boolean(string='Habilitada', readonly=True, default=True)
    primary = fields.Boolean(string='Principal', readonly=True)

    def action_run(self):
        """Despacha ESTA acción por la lista blanca de la bandeja.

        Método PÚBLICO (Odoo 17 rechaza invocar privados desde un botón): delega
        el despacho en ``printflow.flow.failure.tray.action_run``, que valida que
        la acción exista para la fila y luego ejecuta/navega/cierra. El cliente
        nunca elige un método: solo aprieta el botón de la fila.
        """
        self.ensure_one()
        return self.line_id.tray_id.action_run(
            line_id=self.line_id.id, action_key=self.key)
