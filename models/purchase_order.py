# -*- coding: utf-8 -*-
"""Enganche de PrintFlow sobre la Orden de Compra (``purchase.order``).

Persiste y propaga el lote indicado en la Compra Rápida hacia el lado de
COMPRA/ENTRADA, SIN tocar el motor ``x_product_dimensional_pricing`` (``_inherit``
+ ``super()``; cambios ADITIVOS).

Problema que resuelve (H-011): la Compra Rápida abierta desde PrintFlow corre con
``material_received=False`` a propósito ("abrir ≠ ejecutar": crea la OC, NO fuerza
la recepción). El lote vivía SOLO en la línea del wizard (transient) y, al quedar
el albarán abierto, nunca se materializaba: el operador debía teclearlo de nuevo al
validar.

Piezas de esta fase:
- (D1) Campo ADITIVO ``pf_lot_name`` (espejo de ``sale.order.pf_lot_name``): la OC
  guarda el NOMBRE del lote previsto (documento de compra estable).
- (D2) ``button_confirm``: tras confirmar (``super()``), se PRELLENA el albarán de
  entrada abierto escribiendo ``lot_id``/``lot_name`` en sus ``stock.move.line``
  (mismo patrón que ``_validate_incoming_pickings`` del motor, pero **SIN**
  ``button_validate``). El lote se materializa idempotentemente reutilizando
  ``mrp.production._get_or_create_lot``.

Dirección de dependencias: vive en ``models/`` del addon PrintFlow; NO importa
``wizard/``. Solo se LEE/ENGANCHA (regla "código sí, datos no"): las escrituras son
las PROPIAS del flujo (crear el lote pedido y prellenar la línea del albarán).
"""

from odoo import fields, models


class PurchaseOrder(models.Model):
    """Orden de Compra (PrintFlow): persiste y prellena el lote previsto."""

    _inherit = 'purchase.order'

    pf_lot_name = fields.Char(
        string='Lote previsto',
        help='Nombre del lote indicado en la Compra Rápida; se prellena en el '
             'albarán de entrada y se materializa como stock.lot al validar.')

    def button_confirm(self):
        """Confirma la OC y PRELLENA el lote del albarán de entrada (D2).

        Delega en ``super()`` el flujo NATIVO de confirmación y, acto seguido,
        deja el lote previsto cargado en la entrada abierta. NO valida el albarán
        ("abrir ≠ ejecutar"): el operador lo suelta con el botón nativo cuando
        quiera.
        """
        res = super().button_confirm()
        self._pf_prefill_incoming_lot()
        return res

    def _pf_prefill_incoming_lot(self):
        """Prellena el lote previsto en las líneas de la entrada abierta (D2).

        Para cada OC con ``pf_lot_name``: asigna las move lines de su albarán de
        entrada (``action_assign``, primitiva NATIVA e idempotente) y escribe
        ``lot_id``/``lot_name`` en las move lines del producto por lote que aún
        NO tienen lote. El ``stock.lot`` se crea/recupera idempotentemente con el
        helper canónico ``mrp.production._get_or_create_lot``. NO crea move lines a
        mano y NO valida el albarán.
        """
        for po in self.filtered(lambda p: p.pf_lot_name):
            pickings = po.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
                and getattr(p.picking_type_id, 'code', '') == 'incoming')
            for picking in pickings:
                picking.action_assign()
                moves = picking.move_ids.filtered(
                    lambda m: m.product_id.tracking == 'lot'
                    and m.state not in ('done', 'cancel'))
                for move in moves:
                    lot = self.env['mrp.production']._get_or_create_lot(
                        move.product_id, po.pf_lot_name)
                    move.move_line_ids.filtered(
                        lambda ml: not ml.lot_id).write({
                            'lot_id': lot.id,
                            'lot_name': lot.name,
                        })
