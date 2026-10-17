# -*- coding: utf-8 -*-
"""Falla: reserva de lote HUÉRFANA / NEGATIVA (PrintFlow · Fase 1).

Primera falla concreta del patrón guiado. Detecta el estado
``lot_orphan_reservation`` delegando en el motor del addon principal
(``printflow.stock.health._pf_lot_state``), que ya pliega la reserva NEGATIVA
(``negative_reserved_quant_ids``) en ``orphan_quant_ids``. La detección NO se
reinventa: se reutiliza el motor.

Evidencias: UNA fila por quant afectado, con el detalle que el operador necesita
para decidir:

  * producto / lote / ubicación;
  * físico (``quantity``) y reservado HOY (``reserved_quantity``);
  * respaldo REAL = suma de ``stock.move.line`` activas del mismo
    producto/lote/ubicación (quién respalda ese reservado);
  * delta = respaldo − reservado (lo que la reconciliación corregiría).

Acciones guiadas: ``reconcile`` (principal), ``view_supporting_moves``,
``view_quant`` y ``leave``. La corrección RIESGOSA de liberar/reasignar NO
pertenece a esta superficie: el operador solo reconcilia (el motor conserva su
primitiva ``_pf_reassign_by_lot`` para otros flujos).

Ejecución: ``_pf_fault_execute('reconcile')`` llama la primitiva NATIVA de
reconciliación del motor (``_pf_reconcile_reserved_quant``); ``reconcile`` pasa
por el guardia SEGURO ``_pf_assert_can_reconcile`` (operador). Al ejecutar deja
bitácora (``message_post``) en el producto afectado. NO crea estados nuevos:
reutiliza ``lot_orphan_reservation``.
"""

from odoo import _, api, models

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6


class PrintflowFlowFailureLotOrphan(models.AbstractModel):
    """Falla de reserva de lote huérfana/negativa (contrato guiado)."""

    _name = 'printflow.flow.failure.lot.orphan'
    _inherit = 'printflow.flow.failure'
    _description = 'Falla: reserva de lote huérfana (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # IDENTIDAD Y DETECCIÓN
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_code(self):
        """Código del vocabulario existente (mismo ``pf_cause`` del motor)."""
        return 'lot_orphan_reservation'

    @api.model
    def _pf_fault_detect(self, host, ctx=None):
        """Detecta el estado huérfano delegando en el motor (solo lectura).

        Devuelve ``{'product': ..., 'lot_info': ...}`` si el producto está en
        ``lot_orphan_reservation``; ``False`` en cualquier otro caso. ``ctx`` es
        obligatorio para traer el producto (el host del diagrama lo aporta).
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product or product.tracking != 'lot':
            return False
        lot_info = self.env['printflow.stock.health']._pf_lot_state(product)
        # F3: pasa por el adaptador (no-op para la reserva huérfana, que NO es
        # autorizable; se aplica por consistencia y para futuros formalismos).
        lot_info = self.env[
            'printflow.finding.exception.filter']._pf_apply_to_lot_info(
                product, lot_info)
        if lot_info.get('state') != 'lot_orphan_reservation':
            return False
        return {'product': product, 'lot_info': lot_info}

    # ══════════════════════════════════════════════════════════════════════
    # PRESENTACIÓN (encabezado de la bandeja)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_severity(self, ctx):
        return 'danger'

    @api.model
    def _pf_fault_summary(self, ctx):
        count = len(self._pf_orphan_quant_ids(ctx))
        return _(
            '%s reserva(s) de lote inconsistente(s): el reservado no cuadra con '
            'los movimientos que lo respaldan.') % count

    @api.model
    def _pf_fault_steps(self, ctx):
        return [
            _('Revisa las filas: verás el físico, el reservado y el respaldo '
              'real de cada quant afectado.'),
            _('Pulsa "Reconciliar la reserva": deja el reservado igual al '
              'respaldo real (no toca el físico ni le quita a ningún pedido).'),
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EVIDENCIAS (UNA fila por quant afectado)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_evidences(self, ctx):
        """Construye las filas de evidencia del estado huérfano."""
        observation = (ctx or {}).get('observation') or {}
        product = observation.get('product') or (ctx or {}).get('product')
        quant_ids = self._pf_orphan_quant_ids(ctx)
        quants = self.env['stock.quant'].sudo().browse(quant_ids).exists()
        if not product or not quants:
            return []
        support = self._pf_support_map(product)
        rows = []
        for quant in quants:
            key = (quant.lot_id.id or False, quant.location_id.id)
            support_qty, holders = support.get(key, (0.0, []))
            reserved = quant.reserved_quantity or 0.0
            delta = support_qty - reserved
            support_label = ', '.join(holders) if holders else _('(sin respaldo)')
            rows.append({
                'product_id': quant.product_id.id,
                'lot_id': quant.lot_id.id or False,
                'lot_name': quant.lot_id.name or '',
                'location_id': quant.location_id.id or False,
                'physical_qty': quant.quantity or 0.0,
                'reserved_qty': reserved,
                'support_qty': support_qty,
                'delta_qty': delta,
                'support_label': support_label,
                'detail': _(
                    'Lote %(lot)s · %(loc)s · reservado %(res)s · respaldo '
                    '%(sup)s · delta %(delta)s') % {
                    'lot': quant.lot_id.name or _('(sin lote)'),
                    'loc': quant.location_id.display_name or '',
                    'res': reserved,
                    'sup': support_qty,
                    'delta': delta,
                },
                'res_model': 'stock.quant',
                'res_id': quant.id,
            })
        return rows

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES GUIADAS (por fila)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_actions(self, ctx):
        """Acciones por fila (lista blanca explícita; sin ``getattr``)."""
        return [
            {'key': 'reconcile', 'label': _('Reconciliar la reserva'),
             'kind': 'execute', 'enabled': True, 'primary': True, 'sequence': 10},
            {'key': 'view_supporting_moves',
             'label': _('Ver quién la respalda'), 'kind': 'navigate',
             'enabled': True, 'sequence': 20},
            {'key': 'view_quant', 'label': _('Ver la existencia'),
             'kind': 'navigate', 'enabled': True, 'sequence': 30},
            {'key': 'leave', 'label': _('Cerrar'), 'kind': 'close',
             'enabled': True, 'sequence': 40},
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EJECUCIÓN (solo acciones con EFECTO)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_execute(self, action_key, ctx):
        """Ejecuta una acción con EFECTO reutilizando las primitivas del motor.

        Solo ``reconcile`` (SEGURO, guardia configurable). Las acciones
        ``navigate``/``close`` las resuelve la bandeja: aquí se devuelve sin
        efecto.
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product:
            return ''
        Remedy = self.env['printflow.stock.remedy']
        Health = self.env['printflow.stock.health']
        if action_key == 'reconcile':
            Remedy._pf_assert_can_reconcile()
            result = Health._pf_reconcile_reserved_quant(product)
            self._pf_log(product, _(
                'PrintFlow: reserva de lote reconciliada con los movimientos '
                '(quants corregidos: %s).') % result.get('reconciled'))
            return _('Reserva reconciliada: %s quant(s).') % result.get(
                'reconciled')
        return ''

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS (puros, de solo lectura)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_orphan_quant_ids(self, ctx):
        """Ids de quant afectados (huérfanos + reserva negativa)."""
        observation = (ctx or {}).get('observation') or {}
        lot_info = observation.get('lot_info') or {}
        return lot_info.get('orphan_quant_ids') or []

    @api.model
    def _pf_support_map(self, product):
        """``(lote, ubicación) -> (qty_respaldada, [quién respalda])``.

        UNA sola lectura de ``stock.move.line`` activas del producto (internas o
        en tránsito con cantidad), agrupada por ``(lote, ubicación)``. La etiqueta
        de "quién respalda" prioriza el albarán; si no, la referencia del
        movimiento. Es solo lectura.

        :rtype: dict[tuple, tuple[float, list[str]]]
        """
        support = {}
        if not product:
            return support
        lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', _EPS),
            ('location_id.usage', 'in', ('internal', 'transit')),
        ])
        for line in lines:
            key = (line.lot_id.id or False, line.location_id.id or False)
            entry = support.setdefault(key, {'qty': 0.0, 'holders': []})
            entry['qty'] += line.quantity or 0.0
            label = (
                line.picking_id.name
                or line.move_id.reference
                or line.move_id.name
                or '')
            if label and label not in entry['holders']:
                entry['holders'].append(label)
        return {
            key: (entry['qty'], entry['holders'])
            for key, entry in support.items()
        }

    @api.model
    def _pf_log(self, product, body):
        """Bitácora en el documento/producto afectado (``message_post``)."""
        if not product or not hasattr(product, 'message_post'):
            return
        product.sudo().message_post(
            body=body, message_type='notification',
            subtype_xmlid='mail.mt_note')
