# -*- coding: utf-8 -*-
"""Chequeo de FLUJO unificado del escáner de producto (PrintFlow - FASE 4).

Consume el motor unificado ``printflow.product.flow.diagnostic`` en scope
'product': arma un contexto plano por producto y vuelca el veredicto como un
hallazgo ESTÁNDAR del escáner. NO reimplementa el árbol de causa-raíz: ese vive
en el orquestador (única fuente de verdad), que a su vez reutiliza el motor de
salud.

El ``check_code`` del hallazgo es ``flow_<cause>`` para que el playbook resuelva
la causa normalizada sin una tabla estática adicional.
"""

from odoo import _, api, models

from ..printflow_product_check_mixin import EPS

# cause -> (nav_kind, res_model) del vocabulario del hallazgo.
_CAUSE_NAV = {
    'free_exhausted': ('quants', 'stock.quant'),
    'data_anomaly': ('quants', 'stock.quant'),
    'order_shortfall': ('product', 'product.product'),
    'manufacture': ('product', 'product.product'),
    'manufacture_components': ('product', 'product.product'),
    'buy_product': ('product', 'product.product'),
    'no_bom': ('bom_list', 'mrp.bom'),
    'adjust_inventory': ('quants', 'stock.quant'),
    'mo_stuck': ('product', 'product.product'),
    'personalized_supply_stolen': ('product', 'product.product'),
    'contention_needs_supply': ('product', 'product.product'),
}

# cause -> etiqueta corta del título.
_CAUSE_LABEL = {
    'free_exhausted': _('Libre agotada'),
    'data_anomaly': _('Reserva colgada'),
    'order_shortfall': _('Déficit sin ruta'),
    'manufacture': _('Fabricar'),
    'manufacture_components': _('Comprar componentes'),
    'buy_product': _('Comprar el producto'),
    'no_bom': _('Sin lista de materiales'),
    'adjust_inventory': _('Ajustar inventario'),
    'mo_stuck': _('OF trabada'),
    'personalized_supply_stolen': _('Compra propia retenida'),
    'contention_needs_supply': _('Contención sin cobertura'),
}


class PrintflowProductCheckFlow(models.AbstractModel):
    """Chequeo que vuelca el veredicto del motor unificado por producto."""

    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de flujo unificado (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'product_flow',
            'area': 'flow',
            'sequence': 5,
            'method': self._pf_check_product_flow,
        }]

    def _pf_check_product_flow(self, ctx):
        """Emite un hallazgo de flujo por cada producto con causa raíz."""
        env = ctx['env']
        products = ctx['products']
        if not products:
            return [self._pf_finding(
                'product_flow', 'flow', 'info', _('Sin productos que evaluar'))]
        engine = env['printflow.order.health.engine']
        flow = env['printflow.product.flow.diagnostic']
        remedy = env['printflow.stock.remedy']

        manufacturable = engine._pf_manufacturable_products(products)
        over_reserved = engine._pf_over_reserved_products(products.ids)
        anomalies = engine._pf_reservation_anomaly_products(products.ids)

        findings = []
        problems = 0
        for product in products:
            # Solo los productos que GESTIONAN INVENTARIO pueden fabricar un
            # déficit en el escáner. Un consumible/servicio (sin compra por
            # pedido) no tiene quants: se salta, igual que el tablero.
            if not engine._pf_is_stock_tracked(product):
                continue
            deficit = max(
                0.0,
                (product.outgoing_qty or 0.0)
                - (product.qty_available or 0.0)
                - (product.incoming_qty or 0.0),
            )
            physical_remedy = (
                remedy._pf_physical_remedy_key(product, deficit)
                if deficit > EPS else False
            )
            verdict = flow._pf_flow_verdict({
                'product_id': product.id,
                'is_finished': True,
                'sale_status': 'ok',
                'purchase_ok': product.purchase_ok,
                'incoming_qty': product.incoming_qty,
                'deficit_qty': deficit,
                'in_over_reserved': product.id in over_reserved,
                'reservation_anomaly': product.id in anomalies,
                'is_manufacturable': product.id in manufacturable,
                'active_mos': [],
                'done_mos': [],
                'physical_remedy': physical_remedy,
            })
            cause = verdict['cause']
            if not cause:
                continue
            problems += 1
            nav_kind, res_model = _CAUSE_NAV.get(
                cause, ('product', 'product.product'))
            label = _CAUSE_LABEL.get(cause, cause)
            findings.append(self._pf_finding(
                'flow_%s' % cause, 'flow',
                'error' if verdict['severity'] == 'danger' else 'warning',
                _('Flujo: %(label)s') % {'label': label},
                detail=_(
                    'El motor de flujo clasifica la traba como "%s". Revisa el '
                    'plan de resolución del hallazgo para resolverla en su raíz.'
                ) % label,
                product=product,
                record_count=1,
                nav_kind=nav_kind,
                res_model=res_model,
                action_hint=_('Resolver la causa raíz'),
                evidences=[self._pf_evidence(
                    label,
                    detail=verdict['root_cause_node'] or '',
                    product=product,
                    nav_kind=nav_kind,
                    res_model=res_model,
                    causante_type='product',
                    collectible=False,
                    ref_name=product.display_name,
                    qty=deficit,
                )],
            ))
        if not problems:
            findings.append(self._pf_finding(
                'product_flow', 'flow', 'ok',
                _('Flujo sin trabas'),
                detail=_(
                    'Ninguno de los %s producto(s) evaluados tiene una causa '
                    'raíz pendiente en su flujo.'
                ) % len(products),
            ))
        return findings
