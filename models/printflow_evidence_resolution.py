# -*- coding: utf-8 -*-
"""Resolución en la evidencia de producto (PrintFlow).

Extiende ``printflow.product.diagnostic.evidence`` con la causa, la etiqueta
v1 y las nuevas etiquetas del contrato extendido (problema / solución /
recopilar), todas heredadas de su hallazgo mediante campos ``related``
(calculados, NO almacenados). Así la Bandeja de Resolución puede mostrar "Qué
hacer" y ofrecer la acción contextual sin duplicar textos.

Cero migración: ningún campo se almacena.
"""

from odoo import _, fields, models

from .printflow_finding_resolution import pf_reserving_sale_order_ids


class PrintflowProductDiagnosticEvidence(models.TransientModel):
    _inherit = 'printflow.product.diagnostic.evidence'

    # ── Nuevo destino de navegación: "quién lo reserva" ─────────────────
    nav_kind = fields.Selection(
        selection_add=[
            ('reserving_sale_orders', _('Pedidos que lo reservan')),
        ],
    )

    # ── Causa y acciones heredadas del hallazgo (related, NO almacenadas) ─
    pf_cause = fields.Selection(
        related='finding_id.pf_cause', string='Causa', readonly=True,
    )
    # ALIAS DEPRECADO (v1): equivale a ``pf_solution_label``.
    pf_action_label = fields.Char(
        related='finding_id.pf_action_label', string='Acción sugerida',
        readonly=True,
    )
    # Etiquetas de las tres acciones del contrato extendido (solo lectura).
    pf_problem_label = fields.Char(
        related='finding_id.pf_problem_label', string='Ir al problema',
        readonly=True,
    )
    pf_solution_label = fields.Char(
        related='finding_id.pf_solution_label', string='Aplicar solución',
        readonly=True,
    )
    pf_collect_label = fields.Char(
        related='finding_id.pf_collect_label', string='Recopilar',
        readonly=True,
    )

    # ── Remedio del hallazgo (related, NO almacenado) ──────────────────
    pf_remedy_available = fields.Boolean(
        related='finding_id.pf_remedy_available',
        string='Recomendación disponible', readonly=True,
    )
    pf_remedy_label = fields.Char(
        related='finding_id.pf_remedy_label', string='Recomendación',
        readonly=True,
    )
    pf_remedy_kind = fields.Selection(
        related='finding_id.pf_remedy_kind', readonly=True,
    )
    pf_remedy_target = fields.Char(
        related='finding_id.pf_remedy_target', readonly=True,
    )

    def action_apply_remedy(self):
        """Ejecuta el remedio del hallazgo de esta evidencia (delegación)."""
        self.ensure_one()
        return self.finding_id.action_apply_remedy()

    def _pf_open_reserving_sale_orders(self):
        """Abre la lista de pedidos que reservan el producto (solo lectura)."""
        self.ensure_one()
        order_ids = pf_reserving_sale_order_ids(
            self.env, self.product_id, exclude_sale_order=self.sale_order_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s pedido(s) que lo reservan') % len(order_ids),
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', order_ids)],
            'target': 'current',
        }

    def action_open(self):
        """Navega al registro del causante.

        Si el hallazgo de origen propone "quién lo reserva" (solución o
        recopilar), la evidencia usa ese destino; en cualquier otro caso delega
        en la navegación base. Todo es SOLO LECTURA y se resuelve bajo demanda.
        """
        self.ensure_one()
        finding = self.finding_id
        wants_reserving = (
            self.nav_kind == 'reserving_sale_orders'
            or finding.pf_solution_target == 'reserving_sale_orders'
            or finding.pf_collect_target == 'reserving_sale_orders'
        )
        if wants_reserving:
            return self._pf_open_reserving_sale_orders()
        return super().action_open()
