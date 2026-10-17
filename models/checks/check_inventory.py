# -*- coding: utf-8 -*-
"""Chequeo de inventario: existencia física negativa (error).

La DISPONIBILIDAD (contención / libre agotada) NO se evalúa aquí: es propiedad
exclusiva del motor de flujo (``check_flow`` / ``flow_free_exhausted``), que es
la única autoridad de causa y severidad. Tener dos hallazgos del mismo síntoma
en dos chequeos producía dobles avisos con severidades distintas.
"""

from odoo import _, api, models

from ..printflow_product_check_mixin import EPS


class PrintflowProductCheckInventory(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de inventario (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'stock_negative',
            'area': 'inventory',
            'sequence': 10,
            'method': self._pf_check_stock_negative,
        }]

    def _pf_check_stock_negative(self, ctx):
        """Detecta existencia física negativa (error).

        - ``qty_available < 0`` -> error.

        La disponibilidad libre agotada / contención la reporta el chequeo de
        flujo (``product_flow``), no este. La evidencia lista los quants internos
        por ubicación (o avisa que no hay existencias propias) con navegación a
        la lista de existencias.
        """
        findings = []
        problems = 0
        for product in ctx['products']:
            qty_available = product.qty_available
            free_qty = product.free_qty
            outgoing_qty = product.outgoing_qty
            if qty_available < -EPS:
                problems += 1
                findings.append(self._pf_finding(
                    'stock_negative', 'inventory', 'error',
                    _('Stock negativo: %s') % product.display_name,
                    detail=_(
                        'Existencia física %(qty).2f, libre %(free).2f, '
                        'saliente %(out).2f. Un valor negativo indica un '
                        'descargo mayor que lo que había en almacén.'
                    ) % {
                        'qty': qty_available,
                        'free': free_qty,
                        'out': outgoing_qty,
                    },
                    product=product,
                    highlighted=True,
                    record_count=1,
                    nav_kind='quants',
                    action_hint=_('Existencias por ubicación'),
                    res_model='stock.quant',
                    evidences=self._pf_quant_evidences(product),
                ))
        if not problems:
            findings.append(self._pf_finding(
                'stock_negative', 'inventory', 'ok',
                _('Sin problemas de existencia'),
                detail=_(
                    'Ninguno de los %s producto(s) evaluados tiene existencia '
                    'física negativa.'
                ) % len(ctx['products']),
            ))
        return findings
