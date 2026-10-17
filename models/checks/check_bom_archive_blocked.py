# -*- coding: utf-8 -*-
"""Chequeo de archivado de BOM bloqueado.

REUTILIZA la FASE 1: la autoridad sigue siendo el core
(``sale_mrp.mrp_bom._ensure_bom_is_free``) a través de
``mrp.bom._pf_is_archive_blocked`` y el espejo
``mrp.bom._pf_get_archive_blocking_sale_lines``. NO abre el wizard de la FASE 1
(se evita anidar diálogos): muestra el detalle en línea + evidencias.
"""

from odoo import _, api, models


class PrintflowProductCheckBomArchiveBlocked(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de archivado de BOM bloqueado (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'bom_archive_blocked',
            'area': 'bom',
            'sequence': 20,
            'method': self._pf_check_bom_archive_blocked,
        }]

    def _pf_check_bom_archive_blocked(self, ctx):
        """Lista las ventas pendientes que impiden archivar una BOM kit."""
        findings = []
        seen_boms = set()
        for product in ctx['products']:
            for bom in self._pf_boms_for_product(product, bom_type='phantom'):
                if bom.id in seen_boms:
                    continue
                seen_boms.add(bom.id)
                if not bom._pf_is_archive_blocked():
                    continue
                blocking_lines = bom._pf_get_archive_blocking_sale_lines()
                findings.append(self._pf_finding(
                    'bom_archive_blocked', 'bom', 'error',
                    _('Archivado bloqueado: %s') % bom.display_name,
                    detail=_(
                        'El core impide archivar esta BOM kit porque hay %s '
                        'línea(s) de venta confirmadas por entregar o facturar. '
                        'Resuélvelas (entrega, facturación o cancelación) para '
                        'poder archivarla.'
                    ) % len(blocking_lines),
                    product=product,
                    highlighted=True,
                    record_count=len(blocking_lines),
                    bom=bom,
                    nav_kind='sale_orders',
                    action_hint=_('Pedidos bloqueantes (%s)') % len(blocking_lines),
                    evidences=self._pf_archive_blocking_evidences(
                        blocking_lines, bom, product),
                ))
        if not findings:
            findings.append(self._pf_finding(
                'bom_archive_blocked', 'bom', 'ok',
                _('Ninguna BOM kit bloqueada'),
                detail=_(
                    'Ninguna BOM kit del ámbito está bloqueada por ventas '
                    'pendientes; se pueden archivar.'),
            ))
        return findings

    def _pf_archive_blocking_evidences(self, blocking_lines, bom, product):
        """Evidencias del bloqueo: primero los pedidos, luego la BOM (secundaria).

        Las evidencias por pedido son la acción principal (a dónde ir a
        resolver). La BOM del kit se deja como evidencia SECUNDARIA navegable:
        es el dato que se quiere archivar, no el que hay que corregir.
        """
        evidences = []
        for line in blocking_lines:
            order = line.order_id
            evidences.append(self._pf_evidence(
                _('%s · línea #%s') % (order.name or '', line.id),
                detail=_('%(product)s | cantidad %(qty).2f | entregado %(del).2f '
                         '| facturación: %(inv)s') % {
                    'product': line.product_id.display_name,
                    'qty': line.product_uom_qty,
                    'del': line.qty_delivered,
                    'inv': line.invoice_status,
                },
                product=line.product_id,
                sale_order=order,
                nav_kind='sale_order',
                res_model='sale.order',
                res_id=order.id,
                # Causante recolectable: el pedido es a donde hay que ir.
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
        # Evidencia secundaria (NO recolectable): la BOM kit que se desea
        # archivar es el dato a proteger, no el causante a corregir.
        evidences.append(self._pf_evidence(
            _('BOM kit: %s') % bom.display_name,
            detail=_('Lista de materiales que se desea archivar: %s')
            % bom.display_name,
            product=product,
            bom=bom,
            nav_kind='bom',
            res_model='mrp.bom',
            res_id=bom.id,
            causante_type='bom',
            collectible=False,
            ref_name=bom.display_name,
            action_kind='none',
        ))
        return evidences
