# -*- coding: utf-8 -*-
"""Falla: RESERVA COLGADA real (PrintFlow · patrón de fallas guiadas).

Migra la causa ``data_anomaly`` (reserva colgada) al patrón de falla guiada: su
"Solucionar" deja de ser un one-click ciego y abre la bandeja genérica
(``printflow.flow.failure.tray``) con UNA FILA POR DOCUMENTO que sostiene la
reserva (``stock.move.line`` activa del albarán u OF) y la acción explícita de
saneo/re-reserva ACOTADO al documento de la fila.

Solo se detecta con una RESERVA REAL: un quant con ``reserved > 0`` y
``quantity < reserved``. La EXISTENCIA NEGATIVA pura (``quantity < 0`` y
``reserved <= 0``) NO es esta falla: es la causa ``negative`` y se corrige con
un AJUSTE de inventario. El criterio vive en el motor de salud
(``printflow.order.health.engine.pf_quant_is_hanging_reservation``), fuente
única de verdad que este addon solo LEE.

Evidencias (§3.S): UNA fila por ``stock.move.line`` ACTIVA que sostiene la
reserva colgada de los quants (documento, socio, lote actual o "(sin lote)",
cantidad de la línea, flag "En marcha" y "Reservado por"). FALLBACK honesto:
cada quant colgado SIN línea activa que lo respalde ⇒ UNA fila de quant para
que ningún colgado quede invisible. Acciones guiadas por fila:

  * ``release_document`` (principal): suelta y re-reserva SOLO el documento de
    la fila con el saneo **ACOTADO** (``printflow.stock.remedy.
    _pf_release_hanging_lot_reservation(product, lines=...)``, H-022/H-060):
    suelta SOLO las líneas del documento que apuntan al quant colgado y NUNCA
    una entrega SANA de la misma ubicación. NO es un trasvase entre pedidos:
    nunca le quita la reserva a otro pedido.
  * ``view_document``: navega al documento (albarán u OF) de la fila.
  * ``leave``: cierra la bandeja.

Permisos: VER la bandeja, cualquier operador; EJECUTAR el saneo exige jefe de
taller/administrador (``_pf_assert_can_clean``).

No crea estados nuevos: vive detrás del código ``data_anomaly`` ya existente.
"""

from odoo import _, api, models
from odoo.tools import format_datetime

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    pf_quant_is_hanging_reservation,
)

_EPS = 1e-6


class PrintflowFlowFailureOverReservation(models.AbstractModel):
    """Falla de reserva colgada real (contrato guiado)."""

    _name = 'printflow.flow.failure.over.reservation'
    _inherit = 'printflow.flow.failure'
    _description = 'Falla: reserva colgada real (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # IDENTIDAD Y DETECCIÓN
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_code(self):
        """Código del vocabulario existente (mismo ``pf_cause`` del motor)."""
        return 'data_anomaly'

    @api.model
    def _pf_fault_detect(self, host, ctx=None):
        """Detecta la reserva colgada real del producto (solo lectura).

        Devuelve ``{'product', 'quant_ids'}`` si hay al menos un quant con
        reserva colgada real; ``False`` en cualquier otro caso (incluida la mera
        existencia negativa, que NO es esta falla).
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product:
            return False
        quant_ids = self._pf_hanging_quant_ids(product)
        if not quant_ids:
            return False
        return {'product': product, 'quant_ids': quant_ids}

    # ══════════════════════════════════════════════════════════════════════
    # PRESENTACIÓN (encabezado de la bandeja)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_severity(self, ctx):
        return 'warning'

    @api.model
    def _pf_fault_summary(self, ctx):
        count = len(self._pf_quant_ids_from_ctx(ctx))
        return _(
            '%s reserva(s) colgada(s): hay un quant con más reservado que '
            'existencia física, aunque el total del producto sí alcance. Se '
            'corrige saneando la reserva; no hay que comprar.') % count

    @api.model
    def _pf_fault_steps(self, ctx):
        return [
            _('Revisa las filas: UNA por documento que sostiene la reserva '
              '(verás el físico y el reservado del quant, el lote, la cantidad '
              'de la línea y quién reservó).'),
            _('Pulsa "Liberar y re-reservar" en la fila del documento: suelta '
              'SOLO esa reserva y re-asigna según el stock real, sin quitarle '
              'unidades a ningún otro pedido.'),
            _('Recalcula el diagnóstico para confirmar que el libre quedó sano.'),
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EVIDENCIAS (UNA fila por DOCUMENTO que sostiene la reserva colgada)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_evidences(self, ctx):
        """Construye UNA fila por move.line activa del colgado (+ fallback quant).

        Mismo criterio del saneo acotado (``_hits_hanging`` del remedy): la
        línea apunta al quant colgado (misma ubicación+lote y lote sin
        existencia o sin lote). Lecturas SIN N+1: una búsqueda de líneas +
        el mapeo de documentos por registro. FALLBACK: cada quant colgado sin
        línea activa que lo respalde ⇒ UNA fila de quant.
        """
        observation = (ctx or {}).get('observation') or {}
        product = (ctx or {}).get('product') or observation.get('product')
        quant_ids = observation.get('quant_ids') or self._pf_hanging_quant_ids(
            product)
        quants = self.env['stock.quant'].sudo().browse(quant_ids).exists()
        if not product or not quants:
            return []
        hanging = {}
        lot_stock = {}
        for quant in quants:
            key = (quant.location_id.id, quant.lot_id.id or False)
            hanging[key] = quant
            lot_stock[quant.lot_id.id] = (
                lot_stock.get(quant.lot_id.id, 0.0) + (quant.quantity or 0.0))

        # Líneas ACTIVAS que sostienen alguna reserva colgada (UNA lectura).
        move_lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', _EPS),
            ('location_id.usage', '=', 'internal'),
        ])

        def _sustains(line):
            quant = hanging.get(
                (line.location_id.id, line.lot_id.id or False))
            if not quant:
                return False
            # Guardia anti-entrega-sana (H-022): una línea respaldada por la
            # existencia real de su lote NUNCA entra en el saneo.
            if line.lot_id and lot_stock.get(line.lot_id.id, 0.0) > _EPS:
                return False
            return True

        sustainers = move_lines.filtered(_sustains)
        rows = []
        for index, line in enumerate(sustainers, start=1):
            quant = hanging[(line.location_id.id, line.lot_id.id or False)]
            picking = line.picking_id
            production = (
                line.move_id.production_id
                or line.move_id.raw_material_production_id)
            if picking:
                document_name = picking.name or ''
                document_model, document_res_id = 'stock.picking', picking.id
                document_kind = 'picking'
                partner_name = picking.partner_id.display_name or ''
            elif production:
                document_name = production.name or ''
                document_model, document_res_id = 'mrp.production', production.id
                document_kind = 'production'
                partner_name = ''
            else:
                document_name = _('sin documento')
                document_model, document_res_id = '', 0
                document_kind = 'none'
                partner_name = ''
            physical = quant.quantity or 0.0
            reserved = quant.reserved_quantity or 0.0
            delta = physical - reserved
            rows.append({
                'sequence': index,
                'res_model': 'stock.move.line',
                'res_id': line.id,
                'product_id': product.id,
                'lot_id': line.lot_id.id or False,
                'lot_name': line.lot_id.name or '(sin lote)',
                'location_id': line.location_id.id or False,
                'physical_qty': physical,
                'reserved_qty': reserved,
                'delta_qty': delta,
                'document_name': document_name,
                'document_model': document_model,
                'document_res_id': document_res_id,
                'document_kind': document_kind,
                'partner_name': partner_name,
                'line_qty': line.quantity_product_uom or line.quantity or 0.0,
                'picked': bool(line.picked),
                'reserved_by': self._pf_reserved_by(line),
                'detail': _(
                    'La línea de %(doc)s sostiene %(qty)s del reservado '
                    'colgado en %(loc)s (libre %(delta)s).') % {
                    'doc': document_name,
                    'qty': line.quantity_product_uom or line.quantity or 0.0,
                    'loc': line.location_id.display_name or '',
                    'delta': delta,
                },
            })
        # FALLBACK: caja violeta NO quede invisible — cada quant colgado SIN
        # línea activa que lo respalde ⇒ UNA fila de quant (surface genérica).
        covered = {
            (line.location_id.id, line.lot_id.id or False)
            for line in sustainers}
        orphans = quants.filtered(
            lambda quant: (quant.location_id.id, quant.lot_id.id or False)
            not in covered)
        for index, quant in enumerate(orphans, start=len(rows) + 1):
            physical = quant.quantity or 0.0
            reserved = quant.reserved_quantity or 0.0
            delta = physical - reserved
            rows.append({
                'sequence': index,
                'res_model': 'stock.quant',
                'res_id': quant.id,
                'product_id': quant.product_id.id,
                'lot_id': quant.lot_id.id or False,
                'lot_name': quant.lot_id.name or '',
                'location_id': quant.location_id.id or False,
                'physical_qty': physical,
                'reserved_qty': reserved,
                'delta_qty': delta,
                'document_name': '',
                'document_model': '',
                'document_res_id': 0,
                'document_kind': 'quant',
                'partner_name': '',
                'line_qty': 0.0,
                'picked': False,
                'reserved_by': '',
                'detail': _(
                    'Reservado %(res)s sobre físico %(phy)s en %(loc)s '
                    '(libre %(delta)s): sin movimiento activo que respalde '
                    'la reserva.') % {
                    'res': reserved,
                    'phy': physical,
                    'loc': quant.location_id.display_name or '',
                    'delta': delta,
                },
            })
        return rows

    @api.model
    def _pf_reserved_by(self, line):
        """Quien creó la línea de reserva y cuándo (sin hardcodeo)."""
        user = line.create_uid.display_name or ''
        when = format_datetime(self.env, line.create_date) or ''
        if not user:
            return when
        if not when:
            return user
        return _('%(user)s · %(when)s') % {'user': user, 'when': when}

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES GUIADAS (por fila)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_actions(self, ctx):
        """Acciones por fila (lista blanca explícita; sin ``getattr``)."""
        return [
            {'key': 'release_document', 'label': _('Liberar y re-reservar'),
             'kind': 'execute', 'enabled': True, 'primary': True,
             'sequence': 10},
            {'key': 'view_document', 'label': _('Ver el documento'),
             'kind': 'navigate', 'enabled': True, 'sequence': 20},
            {'key': 'leave', 'label': _('Cerrar'), 'kind': 'close',
             'enabled': True, 'sequence': 30},
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EJECUCIÓN (solo acciones con EFECTO)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_execute(self, action_key, ctx):
        """Sanea el DOCUMENTO de la fila (``release_document``) con el remedy.

        Llama al saneo **ACOTADO** ``_pf_release_hanging_lot_reservation`` con
        ``lines=`` acotado a la línea de la fila (H-022/H-060): nunca suelta
        otra cosa. Re-mide el DELTA del quant (con ``invalidate_recordset``:
        la caché del ORM no revierte sola) y devuelve un mensaje HONESTO por
        fila — nunca un ``UserError`` al operador (las ``UserError`` del
        guardia de permisos SÍ se dejan subir: son el contrato vigente). Las
        acciones ``navigate``/``close`` las resuelve la bandeja.
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product or action_key != 'release_document':
            return ''
        line = ctx.get('line')
        target_line = quant = None
        if line is not None:
            if line.res_model == 'stock.move.line' and line.res_id:
                target_line = self.env['stock.move.line'].sudo().browse(
                    line.res_id).exists()
            elif line.res_model == 'stock.quant' and line.res_id:
                quant = self.env['stock.quant'].sudo().browse(
                    line.res_id).exists()
        if target_line is not None:
            quant = self._pf_sustained_quant(product, target_line)
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        target_move = self.env['stock.move']
        if target_line:
            # El soltar la reserva PUEDE borrarte la línea (CT-03/native):
            # capturo el move ANTES del saneo para el mensaje honesto.
            target_move = target_line.move_id
            result = Remedy._pf_release_hanging_lot_reservation(
                product, lines=target_line)
        else:
            # Fila de quant sin línea activa: saneo acotado de SIEMPRE (sin
            # acote, el mismo que ejecutaba ``release_reservation``).
            result = Remedy._pf_release_hanging_lot_reservation(product)
        cleaned = len(result.get('cleaned_pickings') or [])
        self._pf_log(product, _(
            'PrintFlow: reserva colgada saneada desde la bandeja de fallas '
            'del diagrama (documento: %s; re-asignados: %s).') % (
            (line.document_name if line is not None and line.document_name
             else _('la evidencia')), cleaned))
        return self._pf_release_message(
            line, target_line, quant, target_move=target_move)

    @api.model
    def _pf_sustained_quant(self, product, target_line):
        """Quant colgado que la línea de la fila sostiene (para re-medición)."""
        if not target_line:
            return self.env['stock.quant']
        for quant in self.env['stock.quant'].sudo().browse(
                self._pf_hanging_quant_ids(product)):
            key_left = (quant.location_id.id, quant.lot_id.id or False)
            key_right = (
                target_line.location_id.id, target_line.lot_id.id or False)
            if key_left == key_right:
                return quant
        return self.env['stock.quant']

    @api.model
    def _pf_release_message(self, line, target_line, quant, target_move=None):
        """Mensaje HONESTO por fila según lo que SUCEDIÓ con el quant.

        Cuatro casos (plan §3.S · T2): 1) saneada y el quant quedó sin
        colgado (+ honesto si la línea quedó sin reserva por falta de stock);
        2) se soltó, pero el quant sigue colgado con OTRO(S) documento(s);
        3) no se pudo liberar (el movimiento conserva unidades "en marcha" ⇒
        el ``_pf_unreserve_reservation`` lo salta, riesgo residual declarado
        CT-02). NUNCA ``UserError`` al operador.

        Ojo CT-03/native: tras el saneo la línea del documento PUEDE estar
        ELIMINADA (``_do_unreserve`` des-enlaza las líneas de la reserva
        liberada) ⇒ nunca se lee la línea muerta: se pregunta ``exists()``
        y el move se pasa PRECAPTURADO (``target_move``) desde
        ``_pf_fault_execute``.
        """
        if line is not None and line.document_name:
            prefix = _('Reserva del documento %s saneada') % line.document_name
        else:
            prefix = _('Reserva de la evidencia saneada')
        if not quant:
            return _('%s: sin quant colgado asociado que re-medir.') % prefix
        quant.invalidate_recordset()
        delta_after = (
            (quant.reserved_quantity or 0.0) - (quant.quantity or 0.0))
        released = re_reserved = None
        if target_line is not None and target_line.exists():
            move = target_line.move_id
            move.invalidate_recordset(['picked', 'state'])
            released = (
                target_line.sudo().quantity_product_uom <= _EPS)
            re_reserved = bool(
                released
                and move.state in ('assigned', 'partially_available')
                and bool(move.move_line_ids.sudo().filtered(
                    lambda ml: ml.quantity_product_uom > _EPS)))
        elif target_line is not None and target_move is not None:
            # Línea ELIMINADA por el propio saneo: el move precapturado
            # guarda la verdad del re-reservado (o la falta de stock).
            released = True
            move = target_move
            move.invalidate_recordset(['picked', 'state'])
            re_reserved = bool(
                move.state in ('assigned', 'partially_available')
                and bool(move.move_line_ids.sudo().filtered(
                    lambda ml: ml.quantity_product_uom > _EPS)))
        if delta_after <= _EPS:
            message = _(
                '%s: el quant quedó sin colgado (delta %.2f).') % (
                prefix, delta_after)
            if re_reserved is False:
                message += _(
                    ' No había stock para re-reservar: la línea quedó sin '
                    'reserva.')
            return message
        if released is False:
            return _(
                'No se pudo liberar: el movimiento tiene otras unidades en '
                'marcha.')
        return _(
            'Se soltó, pero el quant sigue colgado con otro(s) '
            'documento(s): revisa el resto de las filas.')

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS (puros, de solo lectura)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_quant_ids_from_ctx(self, ctx):
        """Ids de quant afectados de la observación (o recalculados)."""
        observation = (ctx or {}).get('observation') or {}
        quant_ids = observation.get('quant_ids')
        if quant_ids is not None:
            return quant_ids
        return self._pf_hanging_quant_ids((ctx or {}).get('product'))

    @api.model
    def _pf_hanging_quant_ids(self, product):
        """Ids de quants del producto con RESERVA COLGADA real (solo lectura)."""
        if not product:
            return []
        ids = []
        for quant in self.env['stock.quant'].sudo().search_read(
            [('location_id.usage', 'in', ('internal', 'transit')),
             ('product_id', '=', product.id)],
            ['quantity', 'reserved_quantity'],
        ):
            if pf_quant_is_hanging_reservation(
                    quant['quantity'], quant['reserved_quantity']):
                ids.append(quant['id'])
        return ids

    @api.model
    def _pf_log(self, product, body):
        """Bitácora en el producto afectado (``message_post``)."""
        if not product or not hasattr(product, 'message_post'):
            return
        product.sudo().message_post(
            body=body, message_type='notification',
            subtype_xmlid='mail.mt_note')
