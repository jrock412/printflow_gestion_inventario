# -*- coding: utf-8 -*-
"""Chequeo de unidades de medida (UdM) incompatibles o distintas."""

from odoo import _, api, models


class PrintflowProductCheckUom(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de unidades de medida (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'uom_mismatch',
            'area': 'uom',
            'sequence': 10,
            'method': self._pf_check_uom_mismatch,
        }]

    def _pf_check_uom_mismatch(self, ctx):
        """Detecta incompatibilidades de UdM en el producto y sus BOM.

        - Producto: ``uom_id`` y ``uom_po_id`` de categorías distintas -> error.
        - Línea de BOM: componente cuya ``product_uom_id`` es de otra categoría
          que su ``uom_id`` -> error; distinta UdM de la MISMA categoría (es
          convertible) -> info (no hay nada que resolver).
        """
        findings = []
        seen_lines = set()
        for product in ctx['products']:
            if product.uom_id.category_id != product.uom_po_id.category_id:
                findings.append(self._pf_finding(
                    'uom_mismatch', 'uom', 'error',
                    _('UdM de compra/venta incompatibles: %s') % product.display_name,
                    detail=_(
                        'La UdM de venta (%(sale)s) y la de compra (%(purchase)s) '
                        'pertenecen a categorías distintas; no se pueden '
                        'convertir entre sí.'
                    ) % {
                        'sale': product.uom_id.display_name,
                        'purchase': product.uom_po_id.display_name,
                    },
                    product=product,
                    highlighted=True,
                    record_count=1,
                    nav_kind='product',
                    action_hint=_('Ficha del producto (UdM)'),
                    res_model='product.product',
                    res_id=product.id,
                ))

            boms = ctx['env']['mrp.bom'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('active', '=', True),
            ])
            for bom in boms:
                for line in bom.bom_line_ids:
                    component = line.product_id
                    if not component or not line.product_uom_id:
                        continue
                    if line.id in seen_lines:
                        continue
                    seen_lines.add(line.id)
                    component_uom = component.uom_id
                    if line.product_uom_id.category_id != component_uom.category_id:
                        findings.append(self._pf_finding(
                            'uom_mismatch', 'uom', 'error',
                            _('UdM de BOM incompatible: %s') % component.display_name,
                            detail=_(
                                'La línea de la BOM "%(bom)s" usa %(line_uom)s, '
                                'pero el componente se mide en %(comp_uom)s: '
                                'categorías distintas, no convertibles.'
                            ) % {
                                'bom': bom.display_name,
                                'line_uom': line.product_uom_id.display_name,
                                'comp_uom': component_uom.display_name,
                            },
                            product=component,
                            highlighted=True,
                            record_count=1,
                            bom=bom,
                            nav_kind='bom',
                            action_hint=_('BOM'),
                            res_model='mrp.bom',
                            res_id=bom.id,
                        ))
                    elif line.product_uom_id != component_uom:
                        findings.append(self._pf_finding(
                            'uom_mismatch', 'uom', 'info',
                            _('UdM de BOM distinta a la del componente'),
                            detail=_(
                                'La línea de la BOM "%(bom)s" usa %(line_uom)s '
                                'y el componente %(product)s se mide en '
                                '%(comp_uom)s. Es convertible, pero puede '
                                'generar confusiones en el consumo.'
                            ) % {
                                'bom': bom.display_name,
                                'line_uom': line.product_uom_id.display_name,
                                'product': component.display_name,
                                'comp_uom': component_uom.display_name,
                            },
                            product=component,
                            record_count=1,
                            bom=bom,
                            nav_kind='bom',
                            action_hint=_('BOM'),
                            res_model='mrp.bom',
                            res_id=bom.id,
                        ))
        if not findings:
            findings.append(self._pf_finding(
                'uom_mismatch', 'uom', 'ok',
                _('Unidades de medida coherentes'),
                detail=_('No se detectaron UdM incompatibles ni discrepancias en BOM.'),
            ))
        return findings
