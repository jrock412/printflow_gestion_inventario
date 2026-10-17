# -*- coding: utf-8 -*-
"""Falla GENÉRICA (fallback del registry de fallas guiadas · PrintFlow).

Fallback MÍNIMO que el registry devuelve cuando un código de falla no está
mapeado (o llega vacío). Hereda el contrato ``printflow.flow.failure`` e
implementa lo justo para que la bandeja genérica siempre tenga algo que mostrar
y NUNCA reviente por un código inesperado.

No crea estados nuevos: vive detrás del código ``generic``.
"""

from odoo import _, api, models


class PrintflowFlowFailureGeneric(models.AbstractModel):
    """Falla de respaldo: ""sin guía específica, revísalo manualmente""."""

    _name = 'printflow.flow.failure.generic'
    _inherit = 'printflow.flow.failure'
    _description = 'Falla genérica (fallback del registry · PrintFlow)'

    @api.model
    def _pf_fault_code(self):
        """Código del fallback."""
        return 'generic'

    @api.model
    def _pf_fault_detect(self, host, ctx=None):
        """Siempre ""presente"": es el último recurso de la bandeja."""
        ctx = ctx or {}
        return {'generic': True, 'product': ctx.get('product')}

    @api.model
    def _pf_fault_severity(self, ctx):
        return 'warning'

    @api.model
    def _pf_fault_summary(self, ctx):
        return _('Hallazgo sin guía específica: revísalo manualmente.')

    @api.model
    def _pf_fault_steps(self, ctx):
        return [_('Abre el registro afectado y corrígelo manualmente.')]

    @api.model
    def _pf_fault_evidences(self, ctx):
        """Sin evidencias propias: el fallback solo informa."""
        return []

    @api.model
    def _pf_fault_actions(self, ctx):
        """Única acción: cerrar la bandeja."""
        return [{
            'key': 'leave', 'label': _('Cerrar'), 'kind': 'close',
            'enabled': True, 'primary': True,
        }]

    @api.model
    def _pf_fault_execute(self, action_key, ctx):
        """El fallback no ejecuta nada (no tiene corrección automática)."""
        return ''
