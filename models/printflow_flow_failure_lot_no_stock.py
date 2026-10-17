# -*- coding: utf-8 -*-
"""Falla: LOTE RESERVADO SIN EXISTENCIA (``lot_no_stock``) · patrón guiado.

Migra la causa ``lot_no_stock`` al patrón de fallas guiadas: su "Solucionar"
deja de caer a la bandeja CLÁSICA de lote y abre la bandeja GENÉRICA
(``printflow.flow.failure.tray``) con UNA fila por LOTE afectado y la acción
explícita de saneo (re-asignar la reserva por lote).

Por qué existe
--------------
``lot_no_stock`` y ``data_anomaly`` son PRIMOS pero NO iguales (decisión D1 del
Planificador): el motor los separa como estados distintos
(``printflow.stock.health._pf_lot_state``). Aquí el motor detectó
``no_stock_lot_ids``: hay un lote asignado en una ``stock.move.line`` activa
cuyo stock total del lote es ``<= _EPS`` (se retiene un lote que NO tiene
existencia). La evidencia y el saneo difieren del caso de reserva colgada
(``data_anomaly``), por eso es una falla PROPIA y NO una rama de aquella.

La detección NO se reinventa: se delega en el motor del addon principal
(``printflow.stock.health._pf_lot_state``) y se filtra por el adaptador de
excepciones AUTORIZADAS (``printflow.finding.exception.filter``) para no pintar
lo ya declarado intencional (mismo criterio que la bandeja clásica).

Evidencias: UNA fila por LOTE de ``no_stock_lot_ids``, con el detalle que el
operador necesita para decidir:

  * producto / lote / ubicación(es) con reserva;
  * físico total del lote (``physical_qty``; 0 en este estado);
  * reservado del lote (``reserved_qty``);
  * respaldo REAL = cantidad de ``stock.move.line`` activas que lo retienen
    (``support_qty``);
  * delta = respaldo − físico (lo retenido sin respaldo físico);
  * documentos (albaranes/movimientos) que lo retienen (``support_label``).

Acciones guiadas: ``reassign`` (principal, ``execute``),
``view_supporting_moves`` (``navigate``) y ``leave`` (``close``). NO se ofrece
``view_quant``: la fila apunta al LOTE (no a un quant) y un lote sin existencia
puede no tener quant.

Ejecución: ``_pf_fault_execute('reassign')`` reutiliza la primitiva EXISTENTE
del motor (``printflow.stock.health._pf_reassign_by_lot``), la MISMA que ejecuta
el remedio ``reconcile_lot_reservation``: suelta y re-reserva por las reglas de
Odoo y NUNCA reserva un lote vacío. Pasa por el guardia EXISTENTE
``printflow.stock.remedy._pf_assert_can_clean`` (jefe de taller/administrador).
Al ejecutar deja bitácora (``message_post``) en el producto afectado. NO crea
estados nuevos: vive detrás del código ``lot_no_stock`` ya existente.
"""

from odoo import _, api, models

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6


class PrintflowFlowFailureLotNoStock(models.AbstractModel):
    """Falla de lote reservado sin existencia (contrato guiado)."""

    _name = 'printflow.flow.failure.lot.no.stock'
    _inherit = 'printflow.flow.failure'
    _description = 'Falla: lote reservado sin existencia (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # IDENTIDAD Y DETECCIÓN
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_code(self):
        """Código del vocabulario existente (mismo ``pf_cause`` del motor)."""
        return 'lot_no_stock'

    @api.model
    def _pf_fault_detect(self, host, ctx=None):
        """Detecta el estado "lote sin existencia" delegando en el motor.

        Devuelve ``{'product': ..., 'lot_info': ...}`` si el producto está en
        ``lot_no_stock``; ``False`` en cualquier otro caso. ``ctx`` es
        obligatorio para traer el producto (el host del diagrama lo aporta).
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product or product.tracking != 'lot':
            return False
        lot_info = self.env['printflow.stock.health']._pf_lot_state(product)
        # F3: pasa por el adaptador (resta los hallazgos AUTORIZADOS antes de
        # pintar; mismo criterio de la bandeja clásica).
        lot_info = self.env[
            'printflow.finding.exception.filter']._pf_apply_to_lot_info(
                product, lot_info)
        if lot_info.get('state') != 'lot_no_stock':
            return False
        return {'product': product, 'lot_info': lot_info}

    # ══════════════════════════════════════════════════════════════════════
    # PRESENTACIÓN (encabezado de la bandeja)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_severity(self, ctx):
        # Coincide con ``_LOT_STATE_SEVERITY['lot_no_stock']`` (danger).
        return 'danger'

    @api.model
    def _pf_fault_summary(self, ctx):
        count = len(self._pf_no_stock_lot_ids(ctx))
        return _(
            '%s lote(s) reservado(s) sin existencia interna: el documento '
            'retiene un lote que no tiene stock. Se corrige re-asignando la '
            'reserva por lote; no hay que ajustar el físico.') % count

    @api.model
    def _pf_fault_steps(self, ctx):
        return [
            _('Revisa las filas: verás cada lote sin existencia y qué '
              'documentos lo retienen.'),
            _('Pulsa "Reasignar la reserva por lote": suelta y re-asigna según '
              'el stock real de cada lote, sin reservar un lote vacío ni '
              'quitarle unidades a ningún pedido.'),
            _('Recalcula el diagnóstico para confirmar que el lote quedó '
              'resuelto.'),
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EVIDENCIAS (UNA fila por lote afectado)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_evidences(self, ctx):
        """Construye una fila de evidencia por lote sin existencia.

        Solo usa campos del CONTRATO de la línea de la bandeja
        (``printflow.flow.failure.tray.line``): ``_pf_populate`` crea la fila con
        ``dict(row, ...)``, así que cualquier clave ajena rompería el ``create``.
        """
        observation = (ctx or {}).get('observation') or {}
        product = (ctx or {}).get('product') or observation.get('product')
        lot_ids = self._pf_no_stock_lot_ids(ctx)
        lots = self.env['stock.lot'].sudo().browse(lot_ids).exists()
        if not product or not lots:
            return []
        # UNA lectura de quants (físico/reservado por lote) + UNA de move lines
        # activas (respaldo y documentos que retienen), SIN N+1.
        facts = self._pf_lot_facts(product, lots.ids)
        lines = self._pf_move_lines_for_lots(product, lots.ids)
        support = self._pf_support_map(lines)
        rows = []
        for index, lot in enumerate(lots, start=1):
            fact = facts.get(lot.id) or {'physical': 0.0, 'reserved': 0.0}
            physical = fact['physical']
            reserved = fact['reserved']
            entry = support.get(lot.id) or {'qty': 0.0, 'holders': [],
                                            'location_id': False}
            support_qty = entry['qty']
            holders = entry['holders']
            support_label = (', '.join(holders) if holders
                             else _('(sin documento activo)'))
            delta = support_qty - physical
            rows.append({
                'sequence': index,
                'product_id': product.id,
                'lot_id': lot.id,
                'lot_name': lot.name or '',
                'location_id': entry['location_id'] or False,
                'physical_qty': physical,
                'reserved_qty': reserved,
                'support_qty': support_qty,
                'delta_qty': delta,
                'support_label': support_label,
                'detail': _(
                    'Lote %(lot)s sin existencia interna; lo retiene '
                    '%(docs)s.') % {
                    'lot': lot.name or _('(sin lote)'),
                    'docs': support_label,
                },
                'res_model': 'stock.lot',
                'res_id': lot.id,
            })
        return rows

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES GUIADAS (por fila)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_actions(self, ctx):
        """Acciones por fila (lista blanca explícita; sin ``getattr``)."""
        return [
            {'key': 'reassign',
             'label': _('Reasignar la reserva por lote'), 'kind': 'execute',
             'enabled': True, 'primary': True, 'sequence': 10},
            {'key': 'view_supporting_moves',
             'label': _('Ver quién la retiene'), 'kind': 'navigate',
             'enabled': True, 'sequence': 20},
            {'key': 'leave', 'label': _('Cerrar'), 'kind': 'close',
             'enabled': True, 'sequence': 30},
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EJECUCIÓN (solo acciones con EFECTO)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_execute(self, action_key, ctx):
        """Ejecuta el saneo (``reassign``) reutilizando el motor.

        Reutiliza la primitiva EXISTENTE ``_pf_reassign_by_lot``: suelta y
        re-reserva por las reglas de Odoo y nunca reserva un lote vacío. Pasa por
        el guardia EXISTENTE ``_pf_assert_can_clean``. Las acciones
        ``navigate``/``close`` las resuelve la bandeja; aquí se devuelven sin
        efecto.
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product:
            return ''
        if action_key == 'reassign':
            Remedy = self.env['printflow.stock.remedy']
            Remedy._pf_assert_can_clean()
            result = self.env[
                'printflow.stock.health']._pf_reassign_by_lot(product)
            cleaned = len(result.get('cleaned_pickings') or [])
            self._pf_log(product, _(
                'PrintFlow: reserva de lote sin existencia reasignada desde la '
                'bandeja de fallas del diagrama (albaranes re-asignados: %s).'
            ) % cleaned)
            if result.get('still_negative'):
                return _(
                    'Se reasignó la reserva, pero aún falta stock físico: revisa '
                    'la existencia y ajusta el inventario si corresponde.')
            return _(
                'Reservas reasignadas por lote: %s albarán(es) re-asignado(s) '
                'según las reglas de Odoo.') % cleaned
        return ''

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS (puros, de solo lectura)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_no_stock_lot_ids(self, ctx):
        """Ids de lote sin existencia de la observación (o recalculados)."""
        observation = (ctx or {}).get('observation') or {}
        lot_info = observation.get('lot_info')
        if lot_info is None:
            product = (ctx or {}).get('product')
            if not product or product.tracking != 'lot':
                return []
            lot_info = self.env['printflow.stock.health']._pf_lot_state(
                product)
            lot_info = self.env[
                'printflow.finding.exception.filter']._pf_apply_to_lot_info(
                    product, lot_info)
        return lot_info.get('no_stock_lot_ids') or []

    @api.model
    def _pf_move_lines_for_lots(self, product, lot_ids):
        """Move lines ACTIVAS internas del producto con alguno de esos lotes.

        Misma búsqueda que el motor (``_pf_lot_state``) y la bandeja clásica:
        producto, estado activo, ``quantity > eps``, ubicación interna y lote en
        la lista. UNA sola lectura.
        :rtype: stock.move.line
        """
        lot_ids = [lot_id for lot_id in (lot_ids or []) if lot_id]
        if not product or not lot_ids:
            return self.env['stock.move.line']
        return self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', _EPS),
            ('location_id.usage', '=', 'internal'),
            ('lot_id', 'in', lot_ids),
        ])

    @api.model
    def _pf_support_map(self, move_lines):
        """``{lote: {'qty': respaldo, 'holders': [docs], 'location_id': id}}``.

        Agrupa EN MEMORIA las move lines ya leídas (sin consultas extra): suma el
        respaldo por lote, etiqueta "quién lo retiene" (albarán o referencia del
        movimiento) y conserva la primera ubicación con reserva.
        :rtype: dict[int, dict]
        """
        support = {}
        for line in move_lines:
            lot_key = line.lot_id.id or False
            if not lot_key:
                continue
            entry = support.setdefault(
                lot_key, {'qty': 0.0, 'holders': [], 'location_id': False})
            entry['qty'] += line.quantity or 0.0
            label = (
                line.picking_id.name
                or line.move_id.reference
                or line.move_id.name
                or '')
            if label and label not in entry['holders']:
                entry['holders'].append(label)
            if not entry['location_id']:
                entry['location_id'] = line.location_id.id or False
        return support

    @api.model
    def _pf_lot_facts(self, product, lot_ids):
        """``{lote: {'physical': físico, 'reserved': reservado}}`` (una lectura).

        UNA ``search_read`` de quants internos del producto para esos lotes:
        agrega en memoria el físico total y el reservado del lote.
        :rtype: dict[int, dict]
        """
        facts = {}
        lot_ids = [lot_id for lot_id in (lot_ids or []) if lot_id]
        if not product or not lot_ids:
            return facts
        for quant in self.env['stock.quant'].sudo().search_read(
            [('product_id', '=', product.id),
             ('lot_id', 'in', lot_ids),
             ('location_id.usage', '=', 'internal')],
            ['lot_id', 'quantity', 'reserved_quantity'],
        ):
            lot_ref = quant.get('lot_id')
            if not lot_ref:
                continue
            entry = facts.setdefault(
                lot_ref[0], {'physical': 0.0, 'reserved': 0.0})
            entry['physical'] += quant['quantity'] or 0.0
            entry['reserved'] += quant['reserved_quantity'] or 0.0
        return facts

    @api.model
    def _pf_log(self, product, body):
        """Bitácora en el documento/producto afectado (``message_post``)."""
        if not product or not hasattr(product, 'message_post'):
            return
        product.sudo().message_post(
            body=body, message_type='notification',
            subtype_xmlid='mail.mt_note')
