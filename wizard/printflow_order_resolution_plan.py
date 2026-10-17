# -*- coding: utf-8 -*-
"""Plan de acción del diagnóstico de pedido (PrintFlow).

Extiende ``printflow.order.diagnostic.wizard`` con campos CALCULADOS y NO
almacenados que traducen el diagnóstico a lenguaje de mostrador: causa llana,
plan de pasos y etiqueta contextual del botón según la ruta recomendada.

No toca la detección (déficit vs contención se conservan intactos) ni agrega
columnas: cero migración.
"""

from odoo import _, api, fields, models

from .printflow_order_diagnostic_wizard import _EPS
from ..models.printflow_resolution_playbook import (
    PLAN_ACTION_SELECTION,
)

# Etiqueta contextual del botón según la ruta recomendada. Fuente única.
ROUTE_BUTTON_LABELS = {
    'reassign': _('Liberar y re-reservar'),
    'purchase': _('Generar solicitud de compra'),
    'produce': _('Lanzar/priorizar fabricación'),
    'receive': _('Recibir la compra'),
    'design': _('Aprobar el arte'),
    'none': _('Solo diagnóstico'),
}


class PrintflowOrderDiagnosticWizard(models.TransientModel):
    _inherit = 'printflow.order.diagnostic.wizard'

    # ── Plan de acción (calculado, NO almacenado) ───────────────────────
    root_cause_plain = fields.Char(
        string='Causa en palabras simples', compute='_compute_resolution_plan',
    )
    resolution_plan_title = fields.Char(
        string='Título del plan', compute='_compute_resolution_plan',
    )
    resolution_plan_steps = fields.Text(
        string='Pasos del plan', compute='_compute_resolution_plan',
    )
    resolution_plan_button_label = fields.Char(
        string='Etiqueta del botón', compute='_compute_resolution_plan',
    )

    @api.depends(
        'sale_status', 'stock_status', 'purchase_status', 'production_status',
        'has_deficit', 'deficit_total', 'over_reserved_total',
        'recommended_route',
    )
    def _compute_resolution_plan(self):
        """Materializa el plan de acción a partir del diagnóstico ya calculado."""
        for rec in self:
            rec.root_cause_plain = rec._pf_root_cause_plain()
            steps = rec._pf_resolution_steps()
            rec.resolution_plan_title = _('Plan de acción')
            rec.resolution_plan_steps = '\n'.join(
                '%d. %s' % (index, step)
                for index, step in enumerate(steps, start=1)
            )
            rec.resolution_plan_button_label = ROUTE_BUTTON_LABELS.get(
                rec.recommended_route or 'none', '')

    def _pf_root_cause_plain(self):
        """Traduce la contención/déficit del diagnóstico a lenguaje llano."""
        self.ensure_one()
        if self.sale_status != 'ok':
            return _(
                'El pedido todavía no está confirmado: confírmalo para generar '
                'la operación.')
        if self.stock_status == 'over' or self.over_reserved_total > _EPS:
            return _(
                'Las existencias ya están apartadas para otros pedidos: a este '
                'pedido no le queda nada libre. Hay que reasignar, no comprar.')
        if self.deficit_total > _EPS or self.stock_status == 'deficit':
            return _(
                'No alcanza lo que hay en almacén ni lo que viene en camino: '
                'hay que comprar o fabricar lo que falta.')
        if self.purchase_status == 'pending':
            return _(
                'La compra ya existe, pero la mercancía todavía no ha entrado '
                'al almacén.')
        if self.production_status == 'design':
            return _('El arte del pedido está pendiente de aprobación.')
        if self.production_status in (
                'no_mo', 'material', 'late', 'to_launch', 'no_supply'):
            return _(
                'La fabricación del pedido está trabada: revisa su Orden de '
                'Fabricación.')
        return _('El pedido no muestra trabas de stock: solo queda monitorearlo.')

    def _pf_resolution_steps(self):
        """Pasos concretos según la ruta recomendada."""
        self.ensure_one()
        route = self.recommended_route or 'none'
        plans = {
            'reassign': [
                _('Abre los pedidos que tienen apartado el stock.'),
                _('Decide a qué pedido le mueves o liberas la reserva.'),
                _('Pulsa "Liberar y re-reservar" para reajustar al stock '
                  'real.'),
            ],
            'purchase': [
                _('Revisa cuánto falta de verdad (el déficit físico).'),
                _('Genera la solicitud de compra por esa cantidad.'),
                _('Cuando llegue, recíbela para liberar el pedido.'),
            ],
            'produce': [
                _('Revisa la Orden de Fabricación del pedido.'),
                _('Prioriza su material faltante.'),
                _('Lánzala y confirma la producción.'),
            ],
            'receive': [
                _('Abre la compra pendiente.'),
                _('Valida el albarán de entrada.'),
                _('Verifica que el stock quedó reservado al pedido.'),
            ],
            'design': [
                _('Revisa el arte pendiente del pedido.'),
                _('Apruébalo para que producción pueda avanzar.'),
                _('Confirma que la Orden de Fabricación tomó el material.'),
            ],
            'none': [
                _('No hay acciones pendientes por ahora.'),
                _('Solo queda monitorear el pedido.'),
                _('Si algo cambia, recalcula el diagnóstico.'),
            ],
        }
        return plans.get(route, plans['none'])

    def action_apply_plan(self):
        """Ejecuta la ruta RECOMENDADA (botón del Plan de acción).

        Reutiliza el dispatcher existente ``action_apply_route`` sin duplicar
        lógica: fija ``resolution_route`` en la recomendada (campo transitorio)
        y delega. Al ser el recomendado, el label del botón coincide con la
        acción ejecutada.
        """
        self.ensure_one()
        self.resolution_route = self.recommended_route or 'none'
        return self.action_apply_route()

    # ── Remedy de CABECERA (decisión 9) ────────────────────────────────
    # Recomendación estructural del clasificador, elevada a la cabecera del
    # diagnóstico además de por fila. Todos los campos son calculados y NO
    # almacenados: cero migración.
    remedy_available = fields.Boolean(
        string='Hay recomendación', compute='_compute_remedy_header')
    remedy_label = fields.Char(
        string='Recomendación', compute='_compute_remedy_header')
    remedy_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_remedy_header')
    remedy_target = fields.Char(compute='_compute_remedy_header')
    remedy_secondary_available = fields.Boolean(
        string='Hay recomendación alternativa', compute='_compute_remedy_header')
    remedy_secondary_label = fields.Char(
        string='Recomendación alternativa', compute='_compute_remedy_header')

    # ── Saneamiento SIEMPRE disponible ante reserva colgada (Bloque III §28) ─
    pf_has_stuck_reservations = fields.Boolean(
        string='Reservas colgadas', compute='_compute_stuck_reservations')

    @api.depends('deficit_line_ids.product_id', 'board_id')
    def _compute_stuck_reservations(self):
        """True si algún producto del pedido tiene un quant con libre < 0.

        No se condiciona a ``health_stock == 'over'``: aunque el tablero esté
        'ok', una reserva colgada debe poder sanearse desde el diagnóstico.
        """
        Remedy = self.env['printflow.stock.remedy']
        for rec in self:
            products = rec.deficit_line_ids.mapped('product_id')
            rec.pf_has_stuck_reservations = bool(products) and bool(
                Remedy._pf_negative_quant_product_ids(products.ids))

    def action_cleanup_order_reservations(self):
        """Saneamiento global de las reservas colgadas del pedido (con permiso)."""
        self.ensure_one()
        return self.board_id.action_cleanup_over_reservations()

    @api.depends(
        'deficit_line_ids',
        'deficit_line_ids.failure_ids',
    )
    def _compute_remedy_header(self):
        """Eleva a la cabecera el remedio del diagnóstico.

        El botón primario "Recomendación" se retiró de la cabecera (duplicaba
        la solución del playbook). Se conserva la ALTERNATIVA, por lo que cada
        indicador se toma de la primera falla que lo trae disponible de forma
        INDEPENDIENTE (el primario ya no condiciona la alternativa).
        """
        for rec in self:
            primary = rec._pf_first_remedy_failure()
            alternative = rec._pf_first_second_remedy_failure()
            rec.remedy_available = bool(primary)
            rec.remedy_label = primary.pf_remedy_label if primary else ''
            rec.remedy_kind = primary.pf_remedy_kind if primary else False
            rec.remedy_target = primary.pf_remedy_target if primary else ''
            rec.remedy_secondary_available = bool(alternative)
            rec.remedy_secondary_label = (
                alternative.pf_second_remedy_label if alternative else '')

    def _pf_first_remedy_failure(self):
        """Primera falla (por severidad) con remedio PRIMARIO disponible."""
        return self._pf_first_failure_with('pf_remedy_available')

    def _pf_first_second_remedy_failure(self):
        """Primera falla (por severidad) con remedio ALTERNATIVO disponible."""
        return self._pf_first_failure_with('pf_second_remedy_available')

    def _pf_first_failure_with(self, field_name):
        """Primera falla (por severidad) cuyo campo booleano esté activo."""
        self.ensure_one()
        Failure = self.env['printflow.order.diagnostic.failure']
        failures = self.deficit_line_ids.failure_ids.filtered(field_name)
        if not failures:
            return Failure
        order = {'danger': 0, 'warning': 1, 'ok': 2}
        return failures.sorted(
            key=lambda f: order.get(f.severity or 'ok', 3))[:1]

    def action_apply_remedy(self):
        """Botón de cabecera: ejecuta el remedio recomendado."""
        self.ensure_one()
        failure = self._pf_first_remedy_failure()
        if not failure:
            return {'type': 'ir.actions.act_window_close'}
        return failure.action_apply_remedy()

    def action_apply_secondary_remedy(self):
        """Botón de cabecera: ejecuta el remedio alternativo (doble botón)."""
        self.ensure_one()
        failure = self._pf_first_second_remedy_failure()
        if not failure:
            return {'type': 'ir.actions.act_window_close'}
        return failure.action_apply_second_remedy()
