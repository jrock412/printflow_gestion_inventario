# -*- coding: utf-8 -*-
"""Override del catálogo: drill-down al diagrama de flujo (PrintFlow).

``models/`` NUNCA importa ``diagnostic/``. El drill-down del tablero de
Productos se resuelve por HOOK: el catálogo (en ``models/``) declara
``_pf_product_flow_action`` como stub y aquí, en el namespace de diagnóstico, se
sobreescribe para devolver la acción real del wizard ``printflow.product.flow``
(Fase 5). El modelo base ya está registrado por el paquete ``models/`` (que se
importa antes que ``diagnostic/``).
"""

from odoo import _, api, models


class PrintflowInventoryCatalog(models.TransientModel):
    """Extiende el catálogo con el drill-down al diagrama de flujo."""

    _inherit = 'printflow.inventory.catalog'

    @api.model
    def _pf_product_flow_action(self, product):
        """Devuelve la acción del diagrama de flujo del producto (Fase 5)."""
        if not product:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('PrintFlow'),
                    'message': _('No hay un producto para abrir el diagrama.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        return self.env['printflow.product.flow'].action_open_product_flow(
            product.id)
