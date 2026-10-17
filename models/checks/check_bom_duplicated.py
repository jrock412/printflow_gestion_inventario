# -*- coding: utf-8 -*-
"""Chequeo de BOM duplicadas: más de una BOM activa del mismo tipo."""

from odoo import _, api, models

# Etiqueta de negocio del tipo de BOM para la Bandeja de Resolución.
BOM_TYPE_LABELS = {
    'phantom': _('Kit'),
    'normal': _('Normal'),
    'subcontract': _('Subcontratación'),
}


class PrintflowProductCheckBomDuplicated(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de BOM duplicadas (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'bom_duplicated',
            'area': 'bom',
            'sequence': 10,
            'method': self._pf_check_bom_duplicated,
        }]

    def _pf_check_bom_duplicated(self, ctx):
        """Avisa cuando la plantilla tiene varias BOM activas del mismo tipo.

        Tener más de una BOM activa por tipo genera ambigüedad al fabricar
        (Odoo elige una por secuencia). La navegación abre la lista de BOM de la
        plantilla.
        """
        findings = []
        for tmpl in ctx['products'].mapped('product_tmpl_id'):
            boms = ctx['env']['mrp.bom'].search([
                ('product_tmpl_id', '=', tmpl.id),
                ('active', '=', True),
            ])
            grouped = self._pf_group_boms_by_type(boms)
            for bom_type, group in grouped.items():
                if len(group) <= 1:
                    continue
                evidences = [
                    self._pf_evidence(
                        bom.display_name,
                        detail=_('Tipo: %s | %s línea(s)') % (
                            bom_type, len(bom.bom_line_ids)),
                        product=tmpl.product_variant_id,
                        bom=bom,
                        nav_kind='bom',
                        res_model='mrp.bom',
                        res_id=bom.id,
                        # Causante recolectable: cada BOM duplicada.
                        causante_type='bom',
                        collectible=True,
                        ref_name=bom.display_name,
                        partner_name=tmpl.display_name,
                        qty=len(bom.bom_line_ids),
                        state_label=BOM_TYPE_LABELS.get(bom_type, bom_type),
                        action_kind='none',
                    )
                    for bom in group
                ]
                findings.append(self._pf_finding(
                    'bom_duplicated', 'bom', 'warning',
                    _('BOM duplicada (%(type)s) en %(product)s') % {
                        'type': bom_type, 'product': tmpl.display_name,
                    },
                    detail=_(
                        'Hay %s BOM activas del mismo tipo para esta plantilla. '
                        'Odoo elegirá una por secuencia al fabricar: archiva las '
                        'que no uses para evitar ambigüedad.'
                    ) % len(group),
                    product=tmpl.product_variant_id,
                    record_count=len(group),
                    nav_kind='bom_list',
                    action_hint=_('Lista de BOM del producto'),
                    res_model='mrp.bom',
                    evidences=evidences,
                ))
        if not findings:
            findings.append(self._pf_finding(
                'bom_duplicated', 'bom', 'ok',
                _('Sin BOM duplicadas'),
                detail=_('Cada plantilla tiene como máximo una BOM activa por tipo.'),
            ))
        return findings
