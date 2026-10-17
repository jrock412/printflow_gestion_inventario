# -*- coding: utf-8 -*-
"""Adaptador de FILTRADO de hallazgos autorizados (PrintFlow · GI · F2).

Como el motor ``x_product_dimensional_pricing`` NO se toca (D1), la exclusión de
un hallazgo autorizado se hace en GI: cada superficie de GI que consume el
``lot_info`` del motor llama a este adaptador DESPUÉS de leerlo y pinta la
versión FILTRADA. Centralizar aquí evita dispersar ``if tipo == ...`` por las
diez superficies.

Qué hace
--------
Para cada ``finding_code`` de la lista blanca
(``printflow.finding.exception.registry``) RESTA del ``lot_info`` los destinos
autorizados activos:

* ``unassigned_mo_ids`` contra las ``mrp.production`` autorizadas;
* ``missing_move_ids`` contra los ``stock.move`` autorizados;
* ``no_stock_lot_ids`` / ``generic_lot_ids`` contra los ``stock.lot`` autorizados;
* ``mixed_lots`` (NOMBRES) contra los ``stock.lot`` autorizados.

Tras la resta, **recalcula** el ``state`` y el remedio reaplicando la MISMA
precedencia del motor (huérfana > sin lote > sin existencia > genérico > mezcla >
terminado sin lote > ok) y el mapa ``LOT_REMEDY_BY_STATE`` (constante que GI ya
importa del motor). NO re-lee la base ni reimplementa la detección: solo
RECLASIFICA lo que el motor ya devolvió.

Garantía de NO-REGRESIÓN (CA-12): con supresiones VACÍAS, el resultado es
IDÉNTICO al del motor (no altera listas ni estado).

Contrato::

    info = env['printflow.stock.health']._pf_lot_state(product)
    info = env['printflow.finding.exception.filter']._pf_apply_to_lot_info(
        product, info)
    lot_map = env['...filter']._pf_apply_to_lot_map(products, lot_map)
"""

from odoo import api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_stock_remedy import (  # noqa: E501
    LOT_REMEDY_BY_STATE,
)

# Precedencia de estado del MOTOR, reaplicada sobre las listas ya filtradas
# (mismo orden: huérfana > sin lote > sin existencia > genérico > mezcla >
# terminado sin lote > ok). El estado huérfano NO es autorizable, pero se
# conserva en la precedencia para no alterar el resultado del motor.
_PF_STATE_PRECEDENCE = (
    ('orphan_quant_ids', 'lot_orphan_reservation'),
    ('missing_move_ids', 'lot_missing'),
    ('no_stock_lot_ids', 'lot_no_stock'),
    ('generic_lot_ids', 'lot_generic'),
    ('mixed_lots', 'lot_mixed'),
    ('unassigned_mo_ids', 'lot_unassigned_finished'),
)


class PrintflowFindingExceptionFilter(models.AbstractModel):
    """Adaptador que resta los hallazgos autorizados del ``lot_info`` del motor."""

    _name = 'printflow.finding.exception.filter'
    _description = 'Adaptador de filtrado de excepciones formales (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # API (contrato de las superficies)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_apply_to_lot_info(self, product, lot_info):
        """Devuelve una COPIA del ``lot_info`` con los hallazgos autorizados ya
        restados y el ``state``/remedios recalculados (una superficie unitaria).

        :param product: ``product.product`` del ``lot_info``.
        :param dict lot_info: salida de ``_pf_lot_state`` del motor.
        :rtype: dict
        """
        if not product or lot_info is None:
            return lot_info
        filtered = self._pf_apply_to_lot_map(product, {product.id: lot_info})
        return filtered.get(product.id, lot_info)

    @api.model
    def _pf_apply_to_lot_map(self, products, lot_map):
        """La misma operación en LOTE (una sola consulta de supresiones).

        :param products: recordset de ``product.product`` (o uno solo).
        :param dict lot_map: ``pid -> lot_info`` (salida de ``_pf_lot_states_map``).
        :rtype: dict[int, dict]
        """
        if not lot_map:
            return {}
        products = products if products else self.env['product.product']
        Registry = self.env['printflow.finding.exception.registry']
        Exception = self.env['printflow.finding.exception']
        # Supresiones por código (una consulta por código de la lista blanca;
        # todas las superficies comparten este único punto).
        suppressed = {
            code: Exception._pf_suppressed_targets(code)
            for code in Registry._pf_supported()
        }
        # ``mixed_lots`` trae NOMBRES: se resuelven a ids en UNA búsqueda para
        # saber cuáles fueron autorizados (finding_code='lot_mixed').
        drop_mixed_by_pid = self._pf_mixed_names_to_drop(
            products, lot_map, suppressed.get('lot_mixed') or set())
        result = {}
        for pid, info in lot_map.items():
            result[pid] = self._pf_filter_info(
                info, suppressed, drop_mixed_by_pid.get(pid) or set())
        return result

    # ══════════════════════════════════════════════════════════════════════
    # NÚCLEO (puro)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_filter_info(self, info, suppressed, drop_mixed_names=None):
        """Copia filtrada de UN ``lot_info`` (con ``state``/remedios recalculados)."""
        if not info:
            return info
        Registry = self.env['printflow.finding.exception.registry']
        reg = Registry._pf_registry()
        drop_mixed_names = drop_mixed_names or set()
        new = dict(info)
        for code, shape in reg.items():
            key = shape.get('list_key')
            if not key:
                continue
            if key == 'mixed_lots':
                names = info.get(key) or []
                new[key] = [
                    name for name in names if name not in drop_mixed_names]
            else:
                drop_ids = suppressed.get(code) or set()
                current = info.get(key) or []
                new[key] = [item for item in current if item not in drop_ids]
        self._pf_recompute_state_remedy(new)
        return new

    @api.model
    def _pf_recompute_state_remedy(self, info):
        """Recalcula ``state`` + remedio del ``lot_info`` IN PLACE (precedencia)."""
        state = 'lot_ok'
        for key, candidate in _PF_STATE_PRECEDENCE:
            if info.get(key):
                state = candidate
                break
        info['state'] = state
        Remedy = self.env['printflow.stock.remedy']
        key = LOT_REMEDY_BY_STATE.get(state)
        label, kind, target = Remedy._pf_remedy_meta(key) if key else ('', 'none', '')
        info['remedy_key'] = key or False
        info['remedy_label'] = label
        info['remedy_kind'] = kind
        info['remedy_target'] = target
        info['remedy_available'] = kind != 'none'
        return info

    @api.model
    def _pf_mixed_names_to_drop(self, products, lot_map, authorized_lot_ids):
        """``pid -> set(nombres de lote a descartar)`` para ``mixed_lots``.

        Los nombres de ``mixed_lots`` se resuelven a ids con UNA búsqueda acotada
        (producto + nombre) y se descartan los que estén autorizados como
        ``lot_mixed``.
        :rtype: dict[int, set[str]]
        """
        if not authorized_lot_ids:
            return {}
        names = set()
        for info in lot_map.values():
            for name in (info or {}).get('mixed_lots') or []:
                if name:
                    names.add(name)
        if not names:
            return {}
        domain = [('name', 'in', list(names))]
        if products:
            domain.append(('product_id', 'in', products.ids))
        drop = {}
        for lot in self.env['stock.lot'].sudo().search(domain):
            if lot.id in authorized_lot_ids:
                drop.setdefault(lot.product_id.id, set()).add(lot.name)
        return drop
