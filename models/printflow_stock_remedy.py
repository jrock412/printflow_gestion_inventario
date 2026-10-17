# -*- coding: utf-8 -*-
"""Saneo ACOTADO de la reserva colgada de un producto (PrintFlow).

Se **hereda** (``_inherit``) el motor ``printflow.stock.remedy`` para **acotar** el
saneo del estado ``data_anomaly`` ("Reserva colgada") **sin tocar** el motor
``x_product_dimensional_pricing``: el método ``_pf_cleanup_product_reservations``
del motor queda **INTACTO** (lo siguen usando el cron y otros llamadores).

Por qué existe este método (H-022):
    El método del motor localiza las **ubicaciones** con reserva colgada y suelta
    **TODAS** las ``stock.move.line`` que reservan ahí. Como el producto puede ser de
    entrega **EXCLUSIVA por lote**, una entrega **SANA** (con su lote y con existencia)
    que comparte ubicación se re-asigna contra su lote exclusivo (vacío) y queda
    **sin lote**: se pierde la excepción del operador. Este saneo **ACOTADO** suelta
    SOLO las líneas que apuntan al quant colgado (misma ubicación **y** mismo lote) y
    **NUNCA** una línea respaldada por un lote con existencia ⇒ la entrega sana queda
    intacta (CA-4).

Patrón ADITIVO (anexo 3.H): la clase del motor no se modifica; PrintFlow solo AGREGA
un método. Se reutilizan las primitivas **EXISTENTES** del motor
(``pf_quant_is_hanging_reservation``, ``stock.move._pf_unreserve_reservation`` y la
guardia ``_pf_assert_can_clean``). Solo LECTURA de datos ajenos + el saneo del propio
flujo del producto; sin ``cr.execute`` ni ``cr.commit``.
"""
from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (
    pf_quant_is_hanging_reservation,
)

_EPS = 1e-6


class PrintflowStockRemedy(models.AbstractModel):
    """Extiende el motor de saneos con el saneo ACOTADO de reserva colgada."""

    _inherit = 'printflow.stock.remedy'

    @api.model
    def _pf_release_hanging_lot_reservation(self, product):
        """Suelta SOLO las líneas que apuntan al quant colgado y re-reserva NATIVO.

        A diferencia de ``_pf_cleanup_product_reservations`` (motor, que suelta
        **toda** la ubicación), este saneo **NO** des-asigna una entrega **sana** de
        la misma ubicación: solo libera líneas **sin lote** o cuyo lote **no tiene
        existencia**, siempre sobre la MISMA ubicación+lote del quant colgado.

        :param product.product product: producto a sanear.
        :return: MISMO contrato del motor:
            ``{'cleaned_pickings': [ids], 'still_negative': bool}``.
        """
        product.ensure_one()
        self._pf_assert_can_clean()

        # 1) Quants del producto (UNA lectura) → quants colgados + existencia por lote.
        quants = self.env['stock.quant'].sudo().search_read(
            [('product_id', '=', product.id),
             ('location_id.usage', 'in', ('internal', 'transit'))],
            ['location_id', 'lot_id', 'quantity', 'reserved_quantity'])
        hanging_pairs = set()
        lot_stock = {}
        for quant in quants:
            lot = quant['lot_id'][0] if quant['lot_id'] else False
            lot_stock[lot] = lot_stock.get(lot, 0.0) + quant['quantity']
            if pf_quant_is_hanging_reservation(
                    quant['quantity'], quant['reserved_quantity']):
                hanging_pairs.add((quant['location_id'][0], lot))
        if not hanging_pairs:
            return {'cleaned_pickings': [], 'still_negative': False}

        def _hits_hanging(move_line):
            """¿La línea apunta al quant colgado y NO está respaldada por lote real?"""
            lot = move_line.lot_id.id or False
            if (move_line.location_id.id, lot) not in hanging_pairs:
                return False
            # Guardia anti-entrega-sana: nunca suelta una línea respaldada por la
            # existencia real de un lote (la excepción del operador queda intacta).
            if lot and lot_stock.get(lot, 0.0) > _EPS:
                return False
            return True

        # 2) Líneas activas del producto que apuntan al quant colgado (UNA lectura).
        move_lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
        ])
        targets = move_lines.filtered(_hits_hanging)
        if not targets:
            return {'cleaned_pickings': [], 'still_negative': False}

        # 3) Suelta con la primitiva EXISTENTE del motor y re-reserva NATIVO.
        pickings = targets.move_id.picking_id.filtered(
            lambda picking: picking.state not in ('done', 'cancel'))
        targets.move_id._pf_unreserve_reservation()
        pickings.action_assign()

        # 4) Bitácora + MISMO contrato de retorno del motor.
        if pickings:
            body = _(
                'PrintFlow: reserva colgada saneada de forma ACOTADA '
                '(solo líneas sin lote o con lote sin existencia). '
                'Albaranes re-asignados: %s.') % ', '.join(pickings.mapped('name'))
            for picking in pickings:
                picking.message_post(
                    body=body, message_type='notification',
                    subtype_xmlid='mail.mt_note')
        state = self._pf_product_reservation_state(product)
        return {
            'cleaned_pickings': pickings.ids,
            'still_negative': bool(
                (state['has_negative_quant']
                 and state['free_global'] < -_EPS)
                or state.get('has_negative_reserved')),
        }
