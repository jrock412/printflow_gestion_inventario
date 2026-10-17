# -*- coding: utf-8 -*-
"""Presentación del pedido en el selector de la Compra Rápida (D5).

Extiende ``sale.order`` (``_inherit`` + ``super()``) para que el selector
"Agrupar pedidos" de la Compra Rápida muestre "número de venta − cliente" en
lugar de solo el número (hoy `S06637`), que obliga al operador a adivinar de qué
cliente es cada pedido.

El cambio se ACTIVA solo con el contexto ``pf_purchase_partner_label`` (lo
activa la vista heredada del wizard sobre el campo del selector); sin ese
contexto el ``display_name`` de ``sale.order`` queda IDÉNTICO en todo el sistema
⇒ cero efecto colateral. Solo LECTURA: no escribe ningún dato.
"""

from odoo import api, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.depends('name', 'partner_id')
    def _compute_display_name(self):
        """``display_name`` = "SXXX − Cliente" SOLO en el contexto del selector.

        Se reutiliza el ``display_name`` nativo (``super()``) y, si el contexto
        ``pf_purchase_partner_label`` está presente, se le añade el cliente para
        que el selector de la Compra Rápida permita leer de quién es el pedido.
        """
        super()._compute_display_name()
        if not self.env.context.get('pf_purchase_partner_label'):
            return
        for rec in self:
            partner = rec.partner_id.name if rec.partner_id else ''
            rec.display_name = '%s − %s' % (rec.name, partner)
