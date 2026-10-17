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

Reparto ADITIVO multi-lote (H-037)
----------------------------------
El wizard en bloque solo sabía asignar **UN** lote por corrida: el protocolo del
motor (``_pf_reassign_lot``) LIBERA la reserva entera y DESPUÉS reserva ⇒ llamarlo
dos veces con dos lotes **borra el primero**. Por eso el 2.º tick del operador
pisaba al 1.º (H-036) y no había forma de cubrir la demanda con varios lotes.

La primitiva NATIVA (``stock.move._update_reserved_quantity``) **NO reemplaza**: si
ya existe una ``stock.move.line`` con la misma clave ``(location, lot, package,
owner)`` le **SUMA** a su ``quantity``; si no, crea una línea nueva. **Nunca borra
las líneas de OTROS lotes** ⇒ llamada N veces con N lotes distintos, la reserva es
**ACUMULATIVA**.

El método ``_pf_reassign_lots`` de aquí abajo aprovecha eso: **UNA** liberación
(``_pf_unreserve_reservation``, del motor) + **N** reservas ADITIVAS
(``_pf_reserve_lot``, del motor), acotando por la demanda que falta. Es el MISMO
protocolo que el camino de un lote; solo cambia el PATRÓN de llamadas (1 liberar +
N sumar en vez de 1 liberar + 1 sumar). Cero escrituras nuevas contra la base.
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

    # ══════════════════════════════════════════════════════════════════════
    # REPARTO ADITIVO MULTI-LOTE (H-037 · UNA liberación + N reservas)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_reassign_lots(self, lots):
        """Reparte la demanda del movimiento entre VARIOS lotes, de forma ADITIVA.

        Patrón: **UNA** liberación + **N** reservas acumulativas.

        1. **Guardián** (espeja el filtro de ``_pf_unreserve_reservation`` del
           motor y el del core): si el movimiento está ``picked`` o en
           ``('done', 'cancel')`` ⇒ devuelve ``0.0``. No se pueden liberar y, por
           tanto, tampoco se apilan reservas sobre lo ya en curso.
        2. Libera la reserva actual con la primitiva del MOTOR
           (``_pf_unreserve_reservation``) — UNA sola vez.
        3. Recorre ``lots`` en el ORDEN recibido (el del plan declarado en la
           tabla) reservando **ADITIVAMENTE** con ``_pf_reserve_lot`` (primitiva
           del MOTOR, que usa ``_update_reserved_quantity``), acotando cada
           reserva por la demanda que falta (``need - taken``) y cortando en
           ``<= _EPS``.

        NO borra los lotes ya reservados entre llamadas: la reserva es acumulativa
        (una ``stock.move.line`` por lote). Un lote sin existencia disponible
        devuelve ``0.0`` y el bucle **continúa** con el siguiente lote del plan.

        Código sí, datos no: solo consume las primitivas NATIVAS del motor
        (``_pf_unreserve_reservation`` / ``_pf_reserve_lot``); no hay
        ``cr.execute`` ni ``cr.commit``, y el motor ``x_product_dimensional_pricing``
        queda SIN CAMBIOS.

        :param list lots: lotes a repartir, en el ORDEN del plan.
        :rtype: float
        """
        self.ensure_one()
        if not lots or self.product_id.tracking != 'lot':
            return 0.0
        # Guardián: si no se puede liberar (picked/done/cancel), no se apila.
        if self.picked or self.state in ('done', 'cancel'):
            return 0.0
        need = self.product_uom_qty or 0.0
        if need <= _EPS:
            return 0.0
        # UNA liberación (primitiva del MOTOR) + N reservas ADITIVAS.
        self._pf_unreserve_reservation()
        taken = 0.0
        for lot in lots:
            remaining = need - taken
            if remaining <= _EPS:
                break
            taken += self._pf_reserve_lot(lot, remaining) or 0.0
        return taken
