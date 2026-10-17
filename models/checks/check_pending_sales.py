# -*- coding: utf-8 -*-
"""Chequeo de líneas de venta confirmadas pendientes de entregar o facturar."""

from odoo import _, api, models

from ..printflow_product_check_mixin import EPS

# Límite de líneas leídas por barrido. Si el resultado lo alcanza, se avisa del
# truncado (puede haber más líneas no evaluadas).
_PENDING_LINES_LIMIT = 200


class PrintflowProductCheckPendingSales(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de ventas pendientes (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'pending_sale_lines',
            'area': 'sales',
            'sequence': 10,
            'method': self._pf_check_pending_sales,
        }]

    def _pf_check_pending_sales(self, ctx):
        """Líneas de pedido confirmadas con entrega o facturación pendiente.

        Es un aviso informativo para el operador: explica por qué el producto
        tiene demanda comprometida. La evidencia navega al pedido de cada línea.
        """
        products = ctx['products']
        if not products:
            return [self._pf_finding(
                'pending_sale_lines', 'sales', 'info',
                _('Sin productos que evaluar'),
            )]
        lines = ctx['env']['sale.order.line'].search([
            ('product_id', 'in', products.ids),
            ('state', '=', 'sale'),
        ], limit=_PENDING_LINES_LIMIT)
        truncated = len(lines) >= _PENDING_LINES_LIMIT
        pending = lines.filtered(
            lambda line: (line.product_uom_qty - line.qty_delivered) > EPS
            or line.invoice_status in ('to invoice',)
        )
        findings = []
        if truncated:
            findings.append(self._pf_finding(
                'pending_sale_lines', 'sales', 'info',
                _('Resultado limitado a %s líneas') % _PENDING_LINES_LIMIT,
                detail=_(
                    'Se leyeron las primeras %s líneas de venta confirmadas; '
                    'puede haber más fuera del ámbito de este barrido.'
                ) % _PENDING_LINES_LIMIT,
            ))
        for product in products:
            product_lines = pending.filtered(lambda line: line.product_id == product)
            if not product_lines:
                continue
            evidences = []
            for line in product_lines:
                order = line.order_id
                evidences.append(self._pf_evidence(
                    _('%s · línea #%s') % (order.name or '', line.id),
                    detail=_('Cantidad %(qty).2f | entregado %(del).2f | '
                             'facturación: %(inv)s') % {
                        'qty': line.product_uom_qty,
                        'del': line.qty_delivered,
                        'inv': line.invoice_status,
                    },
                    product=product,
                    sale_order=order,
                    nav_kind='sale_order',
                    res_model='sale.order',
                    res_id=order.id,
                    # Causante recolectable: el pedido pendiente.
                    causante_type='sale_order',
                    collectible=True,
                    ref_name=order.name or '',
                    partner_name=order.partner_id.display_name,
                    qty=line.product_uom_qty,
                    qty_secondary=line.qty_delivered,
                    state_label=_('Facturación: %s')
                    % self._pf_selection_label(line, 'invoice_status'),
                    date_ref=order.date_order,
                    action_kind='none',
                ))
            findings.append(self._pf_finding(
                'pending_sale_lines', 'sales', 'warning',
                _('Ventas pendientes: %s') % product.display_name,
                detail=_('%s línea(s) de pedido confirmadas con entrega o '
                         'facturación pendiente.') % len(product_lines),
                product=product,
                record_count=len(product_lines),
                nav_kind='sale_orders',
                action_hint=_('Pedidos pendientes (%s)') % len(product_lines),
                evidences=evidences,
            ))
        if not findings:
            findings.append(self._pf_finding(
                'pending_sale_lines', 'sales', 'ok',
                _('Sin ventas pendientes'),
                detail=_('Ninguno de los productos evaluados tiene líneas de '
                         'pedido confirmadas pendientes.'),
            ))
        return findings
