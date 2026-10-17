# -*- coding: utf-8 -*-
"""Preserva la reserva de lote EXCEPTUADA por el operador al re-asignar (H-030).

Por qué existe (H-030)
----------------------
Al validar entregas EN LOTE, el motor del "validar entregas en lote" corre
``picking.action_assign()`` antes de validar cada albarán. El NATIVO de Odoo
(``stock_move._action_assign``) NO re-asigna un movimiento que YA está reservado
(filtra por ``state in ('confirmed','waiting','partially_available')`` y respeta
la reserva existente). Pero la rama EXCLUSIVA del motor
(``x_product_dimensional_pricing``: movimientos de producto por lote con
``_is_exclusive_delivery()``) llama SIEMPRE a ``_assign_exclusive_lot()`` sin ese
filtro ⇒ ``_pf_reassign_lot`` LIBERA la reserva actual (la excepción del
operador) y reserva el lote EXCLUSIVO del pedido ``S…-Lyyy``, que sigue VACÍO ⇒
reserva 0 ⇒ el albarán pierde su lote, queda ``state != 'assigned'`` y el motor
del bulk lo OMITE con *"Sin stock reservado."*.

Qué se hace
-----------
Se HEREDA ``stock.move`` (``_inherit`` + ``super()``) y se sobrescribe el seam
MÁS PEQUEÑO (``_assign_exclusive_lot``) con un GUARDIÁN DE PRESERVACIÓN: si el
movimiento YA reserva un lote y el lote exclusivo del pedido NO tiene disponible,
se CONSERVA la reserva del operador (solo se re-sincroniza el estado). En
cualquier otro caso se delega en ``super()`` y el motor queda INTACTO (mejor:
comportamiento actual sin cambios).

Espeja la regla del propio core ("si ya está reservado, no se toca"): no se
inventa una regla nueva, solo se le aplica a la rama EXCLUSIVA del motor la regla
que el NATIVO ya aplica.

Código sí, datos no
-------------------
Este override NO escribe inventario: solo LEE (``move_line_ids``, el lote
exclusivo y la disponibilidad del quant). El motor
``x_product_dimensional_pricing`` NO se edita (se hereda); no hay
``cr.execute`` de escritura ni ``cr.commit``.
"""

from odoo import models

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6


class StockMove(models.Model):
    """Aplica la regla del core ("ya reservado ⇒ no se toca") a la rama EXCLUSIVA."""

    _inherit = 'stock.move'

    # ══════════════════════════════════════════════════════════════════════
    # GUARDIÁN DE PRESERVACIÓN (H-030)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_keep_current_lot_reservation(self):
        """True si la reserva de lote ACTUAL debe CONSERVARSE (no re-asignar).

        Se cumple SOLO cuando las tres condiciones se dan a la vez:

        1. el producto va por lote (``tracking == 'lot'``);
        2. el movimiento YA reserva un lote (existe una ``stock.move.line``
           activa con ``lot_id``, ``not picked`` y ``quantity > _EPS``);
        3. el lote exclusivo del pedido EXISTE pero NO tiene disponible en la
           ubicación del movimiento (``_get_available_quantity <= _EPS``): el
           motor, si se le dejara actuar, lo reservaría con resultado 0 y
           soltaría la excepción del operador.

        Cualquier otro caso devuelve ``False`` ⇒ se delega en ``super()`` y el
        motor mantiene su comportamiento (sin reserva previa, con el lote
        exclusivo CON existencia, o producto no exclusivo/por lote). Es la misma
        regla del core: "si ya está reservado, no se toca".

        :rtype: bool
        """
        self.ensure_one()
        if self.product_id.tracking != 'lot':
            return False
        reserved_lines = self.move_line_ids.filtered(
            lambda ml: ml.lot_id and not ml.picked and ml.quantity > _EPS)
        if not reserved_lines:
            return False
        lot = self._get_exclusive_delivery_lot()
        if not lot:
            return False
        free = self.env['stock.quant']._get_available_quantity(
            self.product_id, self.location_id, lot_id=lot)
        return free <= _EPS

    # ══════════════════════════════════════════════════════════════════════
    # SEAM DEL MOTOR (override ADITIVO con ``super()``)
    # ══════════════════════════════════════════════════════════════════════
    def _assign_exclusive_lot(self):
        """Reserva el lote exclusivo SALVO si hay que preservar la excepción.

        Con el guardián activo se CONSERVA la reserva del operador (solo se
        re-sincroniza el ``state`` del movimiento) y se devuelve ``True``; en
        cualquier otro caso se delega en el motor
        (``x_product_dimensional_pricing``) vía ``super()``, que queda INTACTO.
        """
        self.ensure_one()
        if self._pf_keep_current_lot_reservation():
            self._recompute_state()
            return True
        return super()._assign_exclusive_lot()
