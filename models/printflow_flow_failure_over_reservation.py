# -*- coding: utf-8 -*-
"""Falla: RESERVA COLGADA real (PrintFlow · patrón de fallas guiadas).

Migra la causa ``data_anomaly`` (reserva colgada) al patrón de falla guiada: su
"Solucionar" deja de ser un one-click ciego y abre la bandeja genérica
(``printflow.flow.failure.tray``) con UNA fila por quant afectado y la acción
explícita de saneo/re-reserva.

Solo se detecta con una RESERVA REAL: un quant con ``reserved > 0`` y
``quantity < reserved``. La EXISTENCIA NEGATIVA pura (``quantity < 0`` y
``reserved <= 0``) NO es esta falla: es la causa ``negative`` y se corrige con
un AJUSTE de inventario. El criterio vive en el motor de salud
(``printflow.order.health.engine.pf_quant_is_hanging_reservation``), fuente
única de verdad que este addon solo LEE.

Evidencias: UNA fila por quant con reserva colgada (producto/ubicación/lote,
físico, reservado y libre). Acciones guiadas:

  * ``release_reservation`` (principal): suelta y re-reserva por las reglas de
    Odoo con el saneo **ACOTADO** (``printflow.stock.remedy.
    _pf_release_hanging_lot_reservation``, H-022): suelta SOLO las líneas que
    apuntan al quant colgado (misma ubicación+lote) y NUNCA una entrega SANA de
    la misma ubicación. NO es un trasvase entre pedidos: nunca le quita la
    reserva a otro pedido.
  * ``view_quant``: navega al quant afectado (solo lectura).
  * ``leave``: cierra la bandeja.

Permisos: VER la bandeja, cualquier operador; EJECUTAR el saneo exige jefe de
taller/administrador (``_pf_assert_can_clean``).

No crea estados nuevos: vive detrás del código ``data_anomaly`` ya existente.
"""

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    pf_quant_is_hanging_reservation,
)


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
            _('Revisa las filas: verás el físico y el reservado de cada quant '
              'afectado.'),
            _('Pulsa "Liberar y re-reservar": suelta y re-asigna según el stock '
              'real, sin quitarle unidades a ningún pedido.'),
            _('Recalcula el diagnóstico para confirmar que el libre quedó sano.'),
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EVIDENCIAS (UNA fila por quant con reserva colgada)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_evidences(self, ctx):
        """Construye una fila de evidencia por quant con reserva colgada."""
        observation = (ctx or {}).get('observation') or {}
        product = (ctx or {}).get('product') or observation.get('product')
        quant_ids = observation.get('quant_ids') or self._pf_hanging_quant_ids(
            product)
        quants = self.env['stock.quant'].sudo().browse(quant_ids).exists()
        if not product or not quants:
            return []
        rows = []
        for index, quant in enumerate(quants, start=1):
            physical = quant.quantity or 0.0
            reserved = quant.reserved_quantity or 0.0
            delta = physical - reserved
            rows.append({
                'sequence': index,
                'product_id': quant.product_id.id,
                'lot_id': quant.lot_id.id or False,
                'lot_name': quant.lot_id.name or '',
                'location_id': quant.location_id.id or False,
                'physical_qty': physical,
                'reserved_qty': reserved,
                'delta_qty': delta,
                'detail': _(
                    'Reservado %(res)s sobre físico %(phy)s en %(loc)s '
                    '(libre %(delta)s).') % {
                    'res': reserved,
                    'phy': physical,
                    'loc': quant.location_id.display_name or '',
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
            {'key': 'release_reservation', 'label': _('Liberar y re-reservar'),
             'kind': 'execute', 'enabled': True, 'primary': True, 'sequence': 10},
            {'key': 'view_quant', 'label': _('Ver la existencia'),
             'kind': 'navigate', 'enabled': True, 'sequence': 20},
            {'key': 'leave', 'label': _('Cerrar'), 'kind': 'close',
             'enabled': True, 'sequence': 30},
        ]

    # ══════════════════════════════════════════════════════════════════════
    # EJECUCIÓN (solo acciones con EFECTO)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_fault_execute(self, action_key, ctx):
        """Ejecuta el saneo (``release_reservation``) reutilizando el motor.

        Reutiliza el saneo **ACOTADO** ``_pf_release_hanging_lot_reservation``
        (H-022): suelta SOLO las líneas que apuntan al quant colgado (misma
        ubicación+lote), NUNCA una entrega sana de la misma ubicación, y re-asigna
        por las reglas NATIVAS de Odoo. Las acciones ``navigate``/``close`` las
        resuelve la bandeja; aquí se devuelven sin efecto.
        """
        ctx = ctx or {}
        product = ctx.get('product')
        if not product:
            return ''
        if action_key == 'release_reservation':
            Remedy = self.env['printflow.stock.remedy']
            Remedy._pf_assert_can_clean()
            result = Remedy._pf_release_hanging_lot_reservation(product)
            cleaned = len(result.get('cleaned_pickings') or [])
            self._pf_log(product, _(
                'PrintFlow: reserva colgada saneada desde la bandeja de fallas '
                'del diagrama (albaranes re-asignados: %s).') % cleaned)
            if result.get('still_negative'):
                return _(
                    'Se saneó la reserva, pero aún falta stock físico: revisa la '
                    'existencia y ajusta el inventario si corresponde.')
            return _(
                'Reservas saneadas: %s albarán(es) re-asignado(s) según las '
                'reglas de Odoo.') % cleaned
        return ''

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
