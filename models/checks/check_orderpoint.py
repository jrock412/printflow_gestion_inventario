# -*- coding: utf-8 -*-
"""Chequeo de reglas de reorden (orderpoints)."""

from odoo import _, api, models

from ..printflow_product_check_mixin import EPS


class PrintflowProductCheckOrderpoint(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de reglas de reorden (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'orderpoint_kit',
            'area': 'orderpoint',
            'sequence': 10,
            'method': self._pf_check_orderpoint_kit,
        }]

    def _pf_check_orderpoint_kit(self, ctx):
        """Valida la coherencia entre reglas de reorden y kits.

        El core prohíbe crear una BOM kit para un producto con regla de reorden
        (``mrp.bom.check_kit_has_not_orderpoint``). Por eso:

          - orderpoint sobre un kit              -> error (dato incoherente).
          - regla sin umbrales (mín≈0 y máx≈0)   -> warning (regla inerte).
          - cualquier otro caso                  -> SIN hallazgo por producto
            (una regla de reorden normal NO es un problema); se resume en un
            único informativo.
          - sin orderpoints                      -> ok.

        Se usa el ``EPS`` del mixin para comparar mín/máx.
        """
        orderpoint_model = ctx['env']['stock.warehouse.orderpoint']
        findings = []
        problems = 0
        with_thresholds = 0
        for product in ctx['products']:
            orderpoints = orderpoint_model.search([('product_id', '=', product.id)])
            for orderpoint in orderpoints:
                product_min = orderpoint.product_min_qty
                product_max = orderpoint.product_max_qty
                is_inert = abs(product_min) <= EPS and abs(product_max) <= EPS
                if product.is_kits:
                    severity = 'error'
                    title = _('Regla de reorden sobre un kit: %s') % product.display_name
                    detail = _(
                        'Un kit (BOM phantom) no debería tener regla de reorden: '
                        'su reposición es la de sus componentes. El core '
                        'bloquearía crear la BOM kit para este producto.'
                    )
                elif is_inert:
                    severity = 'warning'
                    title = _('Regla de reorden sin umbrales: %s') % product.display_name
                    detail = _(
                        'La regla de reorden tiene mín y máx en cero: no repone '
                        'nada (regla inerte). Verifica si es intencional.'
                    )
                else:
                    # Regla normal con umbrales: NO se alerta por producto.
                    with_thresholds += 1
                    continue
                problems += 1
                findings.append(self._pf_finding(
                    'orderpoint_kit', 'orderpoint', severity, title,
                    detail=detail,
                    product=product,
                    highlighted=severity == 'error',
                    record_count=1,
                    orderpoint=orderpoint,
                    nav_kind='orderpoint',
                    action_hint=_('Regla de reorden'),
                    res_model='stock.warehouse.orderpoint',
                    res_id=orderpoint.id,
                    # Causante recolectable: la regla de reorden a revisar.
                    evidences=[self._pf_evidence(
                        orderpoint.display_name,
                        detail=_('Mín %(min).2f | Máx %(max).2f') % {
                            'min': product_min,
                            'max': product_max,
                        },
                        product=product,
                        orderpoint=orderpoint,
                        nav_kind='orderpoint',
                        res_model='stock.warehouse.orderpoint',
                        res_id=orderpoint.id,
                        causante_type='orderpoint',
                        collectible=True,
                        ref_name=orderpoint.display_name,
                        partner_name=orderpoint.warehouse_id.display_name,
                        qty=product_min,
                        qty_secondary=product_max,
                        action_kind='none',
                    )],
                ))
        if with_thresholds:
            findings.append(self._pf_finding(
                'orderpoint_kit', 'orderpoint', 'info',
                _('Reglas de reorden con umbrales'),
                detail=_(
                    '%s regla(s) de reorden tienen mín/máx definidos y no '
                    'presentan incidencias.' % with_thresholds),
            ))
        if not problems and not with_thresholds:
            findings.append(self._pf_finding(
                'orderpoint_kit', 'orderpoint', 'ok',
                _('Sin reglas de reorden'),
                detail=_(
                    'Ninguno de los productos evaluados tiene reglas de reorden '
                    'que revisar.'),
            ))
        return findings
