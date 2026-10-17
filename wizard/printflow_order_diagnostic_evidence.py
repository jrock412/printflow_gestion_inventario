# -*- coding: utf-8 -*-
"""Bandeja de Resolución del PEDIDO (PrintFlow - FASE 5).

``TransientModel`` que agrega los causantes recolectables de una falla del
diagnóstico de pedido. Comparte el esquema con la bandeja del escáner mediante
``printflow.diagnostic.causante.mixin``. Es de SOLO LECTURA: únicamente lista y
navega (acción ``action_open``), nunca modifica datos.
"""

from odoo import _, api, fields, models

# Registra el mixin antes de construir este modelo (import por paquete).
from ..models import printflow_diagnostic_causante_mixin  # noqa: F401


class PrintflowOrderDiagnosticEvidence(models.TransientModel):
    """Una fila por causante recolectable de una falla del pedido."""

    _name = 'printflow.order.diagnostic.evidence'
    _inherit = ['printflow.diagnostic.causante.mixin']
    _description = 'Causante de la bandeja del pedido (PrintFlow)'
    _rec_name = 'label'
    _order = 'sequence, id'

    failure_id = fields.Many2one(
        'printflow.order.diagnostic.failure', string='Falla',
        required=True, ondelete='cascade',
    )
    wizard_id = fields.Many2one(
        'printflow.order.diagnostic.wizard', string='Diagnóstico',
        related='failure_id.line_id.wizard_id',
    )

    # ------------------------------------------------------------------
    # POBLADO BAJO DEMANDA
    # ------------------------------------------------------------------
    @api.model
    def _pf_populate_for_failure(self, failure):
        """(Re)construye la bandeja de una falla (idempotente por falla)."""
        self.search([('failure_id', '=', failure.id)]).unlink()
        vals_list = failure._pf_collect_causante_vals()
        return self.create(vals_list) if vals_list else self

    @api.model
    def _pf_open_tray_action(self, failure):
        """Acción de la bandeja congelada de una falla (solo lectura)."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bandeja de Resolución del pedido'),
            'res_model': self._name,
            'view_mode': 'tree',
            'domain': [('failure_id', '=', failure.id)],
            'context': {'pf_order_failure_id': failure.id},
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # NAVEGACIÓN (solo lectura)
    # ------------------------------------------------------------------
    def action_open(self):
        """Navega al registro del causante (target='current')."""
        self.ensure_one()
        nav = self.nav_kind or 'none'
        if nav == 'quants' and self.product_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Existencias de %s') % self.product_id.display_name,
                'res_model': 'stock.quant',
                'view_mode': 'list',
                'domain': [
                    ('product_id', '=', self.product_id.id),
                    ('location_id.usage', '=', 'internal'),
                ],
                'target': 'current',
            }
        record_map = {
            'product': (self.product_id, 'product.product'),
            'bom': (self.bom_id, 'mrp.bom'),
            'mo': (self.mo_id, 'mrp.production'),
            'sale_order': (self.sale_order_id, 'sale.order'),
            'purchase_order': (self.purchase_order_id, 'purchase.order'),
            'order_portion': (self.purchase_order_id, 'purchase.order'),
            'picking': (self.picking_id, 'stock.picking'),
        }
        target = record_map.get(nav)
        if target and target[0]:
            record = target[0]
            return {
                'type': 'ir.actions.act_window',
                'name': record.display_name,
                'res_model': target[1],
                'res_id': record.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if self.res_model and self.res_id:
            return {
                'type': 'ir.actions.act_window',
                'name': self.label or _('Detalle'),
                'res_model': self.res_model,
                'res_id': self.res_id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {'type': 'ir.actions.act_window_close'}

    def action_back_to_wizard(self):
        """Reabre el diagnóstico de pedido que originó la bandeja."""
        self.ensure_one()
        wizard = self.env.context.get('pf_order_wizard_id')
        if not wizard:
            wizard = self.mapped('wizard_id')[:1].id
        wizard = self.env['printflow.order.diagnostic.wizard'].browse(
            wizard).exists()
        if not wizard:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico y Ruta de Solución'),
            'res_model': 'printflow.order.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
