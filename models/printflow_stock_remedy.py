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
    def _pf_release_hanging_lot_reservation(self, product, lines=None):
        """Suelta SOLO las líneas que apuntan al quant colgado y re-reserva NATIVO.

        A diferencia de ``_pf_cleanup_product_reservations`` (motor, que suelta
        **toda** la ubicación), este saneo **NO** des-asigna una entrega **sana** de
        la misma ubicación: solo libera líneas **sin lote** o cuyo lote **no tiene
        existencia**, siempre sobre la MISMA ubicación+lote del quant colgado.

        Cura H-060 (§3.S), tres adiciones:

        * **Guardia del recordset vacío + fallback OF/sin albarán:** el
          ``action_assign()`` solo corre si hay albaranes; los movimientos de
          INSUMO de una OF (``raw_material_production_id``) se re-reservan con la
          primitiva NATIVA ``stock.move._action_assign()`` (reglas de destino
          de Odoo). Así el core ya no lanza ``UserError`` *"Nothing to check
          the availability for."* ante una reserva colgada de OF.
        * **Tachón soltado antes de liberar:** una línea colgada marcada
          ``picked`` no tiene stock que la respalde, y
          ``_pf_unreserve_reservation`` la salta si sigue tachada (CT-02:
          el compute del ``picked`` nunca baja solo). Se destilda la
          **LÍNEA concreta** (nunca ``move.picked = False``: el inverse lo
          arrastra a TODAS las líneas) y el aviso queda en la bitácora del
          documento y del producto.
        * **Acotado por documento (``lines``):** con ``None`` el saneo es el de
          siempre; con un *recordset/lista* de ``stock.move.line``, las
          ``targets`` se acotan a las líneas dadas que SOSTENGAN el colgado:
          nunca suelta más que el DOCUMENTO de la fila.

        :param product.product product: producto a sanear.
        :param lines: ``recordset`` (o lista) de ``stock.move.line`` que acota
            el saneo al documento de la fila; ``None`` = sin acote.
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
        if lines is not None:
            # Acote POR DOCUMENTO (§3.S): solo las líneas dadas que SOSTENGAN
            # el colgado; el saneo nunca suelta más que el documento de la fila.
            scope_ids = set(lines.ids) if hasattr(lines, 'ids') else {
                line.id for line in lines}
            targets = targets.filtered(
                lambda target: target.id in scope_ids)
        if not targets:
            return {'cleaned_pickings': [], 'still_negative': False}

        # 2bis) Tachón (H-060): una línea colgada marcada ``picked`` no tiene
        # stock que la respalde ⇒ se SUELTA con escritura EXPLÍCITA a nivel de
        # la LÍNEA concreta (CT-01: ``move.picked = False`` arrastraría TODAS
        # las líneas por el inverse). Con el tachón puesto,
        # ``_pf_unreserve_reservation`` es no-op (CT-02: el compute nunca baja).
        picked_released = targets.filtered('picked')
        moves_shield = picked_released.move_id.filtered(
            # El escudo del MOVIMIENTO solo baja cuando TODAS sus unidades
            # "en marcha" son las del documento: el inverse no arrastra
            # ninguna línea ajena (equivalencia CT-01) y el compute del core
            # (stock_move.py L208-212) jamás escribe False por su cuenta.
            lambda move: not (move.move_line_ids.filtered('picked')
                              - picked_released))
        if picked_released:
            picked_released.write({'picked': False})
            if moves_shield:
                moves_shield.write({'picked': False})

        # 3) Suelta con la primitiva EXISTENTE del motor y re-reserva NATIVO.
        # Los moves se CAPTURAN antes de liberar: ``_do_unreserve`` (native)
        # ELIMINA las move.lines de la reserva liberada ⇒ ``targets`` queda
        # con registros muertos y no se puede re-acceder después.
        target_moves = targets.move_id
        pickings = target_moves.picking_id.filtered(
            lambda picking: picking.state not in ('done', 'cancel'))
        orphan_moves = target_moves.filtered(
            lambda move: not move.picking_id
            and move.state not in ('done', 'cancel'))
        target_moves._pf_unreserve_reservation()
        # Guardia H-060: el ``action_assign()`` A SECAS revienta (UserError del
        # core "Nothing to check the availability for.") si no hay albaranes.
        if pickings:
            pickings.action_assign()
        # Fallback OF/sin albarán: primitiva NATIVA de ``stock.move`` (mismo
        # override que consume el motor): re-reserva el DESTINO según Odoo.
        if orphan_moves:
            orphan_moves._action_assign()

        # 4) Bitácora + MISMO contrato de retorno del motor.
        notice = ''
        if picked_released:
            notice = _(
                ' La línea estaba marcada "en marcha" y se soltó porque la '
                'reserva no tenía stock que la respaldara.')
        if pickings:
            body = _(
                'PrintFlow: reserva colgada saneada de forma ACOTADA '
                '(solo líneas sin lote o con lote sin existencia). '
                'Albaranes re-asignados: %s.%s') % (
                ', '.join(pickings.mapped('name')), notice)
            for picking in pickings:
                picking.message_post(
                    body=body, message_type='notification',
                    subtype_xmlid='mail.mt_note')
        if orphan_moves:
            # Bitácora por OF (H-060): los insumos SIN albarán anotan en la
            # Orden de Fabricación, mismo estilo que los albaranes.
            productions = orphan_moves.mapped(
                lambda move: move.production_id
                or move.raw_material_production_id)
            for production in productions:
                raw_names = ', '.join(
                    orphan_moves.filtered(
                        lambda move: move.raw_material_production_id
                        == production).mapped('name') or [production.name])
                production.sudo().message_post(body=_(
                    'PrintFlow: reserva colgada saneada de forma ACOTADA en '
                    'el insumo %s (sin albarán). Reserva re-asignada por las '
                    'reglas de destino de Odoo.%s') % (raw_names, notice),
                    message_type='notification',
                    subtype_xmlid='mail.mt_note')
            product.message_post(body=_('PrintFlow: reserva colgada saneada '
                'de forma ACOTADA en el insumo de la OF %s (%s).%s') % (
                ', '.join(productions.mapped('name')), product.display_name,
                notice),
                message_type='notification',
                subtype_xmlid='mail.mt_note')
        state = self._pf_product_reservation_state(product)
        return {
            'cleaned_pickings': pickings.ids,
            'still_negative': bool(
                (state['has_negative_quant']
                 and state['free_global'] < -_EPS)
                or state.get('has_negative_reserved')),
        }
