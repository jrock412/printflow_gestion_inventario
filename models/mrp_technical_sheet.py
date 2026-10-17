# -*- coding: utf-8 -*-
"""Extensión ADITIVA del candado de fichas terminales (``mrp.technical.sheet``).

Problema que resuelve (H-013): al validar un albarán de entrada, el motor
``x_product_dimensional_pricing`` recalcula las fichas de los pedidos del
``origin`` de la OC con ``_compute_state_from_docs()``. Ese cómputo asigna
``is_partial_fabrication`` (campo ``compute + store``) a TODAS las fichas,
incluidas las que están en estado TERMINAL (``archived_delivered``,
``archived_orphan``, ``done`` o ``cancel``), ANTES del ``continue`` que las
omite. Como ese campo NO estaba en la whitelist del candado ``write()``, la
asignación disparaba el ``UserError`` "No se puede modificar una ficha
finalizada, cancelada o archivada" y el albarán no se podía validar.

Pieza de esta fase (D1, opción c: 100 % PrintFlow):
- Se EXTIENDE la whitelist del candado sobrescribiendo el MÉTODO-seam
  ``_printflow_skip_terminal_write_lock`` con ``super()`` + un set ADITIVO
  PROPIO. ``super()`` conserva la semántica del motor (contextos de sistema y
  whitelist original) y este set añade SOLO el campo computado
  ``is_partial_fabrication`` (``readonly`` en UI ⇒ NO editable a mano). NO se
  toca el motor ``x_product_dimensional_pricing`` ni su constante
  ``_PRINTFLOW_TECHNICAL_WRITE_FIELDS``.

Este método-seam es el gemelo para recepción y entrega: el mismo arreglo sanea
los dos hooks (recepción y entrega) con UN solo cambio de nivel de campo.

Dirección de dependencias: vive en ``models/`` del addon PrintFlow; NO importa
``wizard/``. Solo se LEE/ENGANCHA (regla "código sí, datos no").
"""

from odoo import models


class MrpTechnicalSheet(models.Model):
    """Ficha Técnica (PrintFlow): amplía el candado terminal con un campo de cómputo."""

    _inherit = 'mrp.technical.sheet'

    # Campos que el RECÁLCULO (``_compute_state_from_docs``) escribe en fichas
    # bloqueadas y que quedaron FUERA de la whitelist del motor.
    # ``is_partial_fabrication`` es un campo ``compute + store`` ``readonly``:
    # el cómputo lo asigna a TODAS las fichas, incluidas las terminales, por lo
    # que habilitarlo NO abre la edición manual de una ficha finalizada (solo
    # permite que el cómputo del motor deje su valor).
    _PF_TERMINAL_EXTRA_WRITE_FIELDS = frozenset({'is_partial_fabrication'})

    def _printflow_skip_terminal_write_lock(self, vals):
        """Amplía la whitelist del candado terminal (D1).

        Delega en ``super()`` el comportamiento del motor (contextos de sistema
        y whitelist original) y, si este NO autoriza, permite SOLO los campos
        ADITIVOS de este set (el campo computado ``is_partial_fabrication``).
        La edición manual de una ficha finalizada sigue bloqueada para cualquier
        campo de negocio (``name``, ``dim_width``, ``manual_done``, …).
        """
        if super()._printflow_skip_terminal_write_lock(vals):
            return True
        return bool(vals) and set(vals).issubset(
            self._PF_TERMINAL_EXTRA_WRITE_FIELDS)
