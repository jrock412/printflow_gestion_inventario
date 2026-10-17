# -*- coding: utf-8 -*-
"""Chequeo de kits: un kit no tiene stock propio y su disponibilidad es derivada."""

from odoo import _, api, models


class PrintflowProductCheckKit(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de kits (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'kit_no_own_stock',
            'area': 'kit',
            'sequence': 10,
            'method': self._pf_check_kit_no_own_stock,
        }]

    def _pf_check_kit_no_own_stock(self, ctx):
        """Explica que un kit no almacena stock propio.

        - Kit con BOM phantom cuyos componentes no tienen disponibilidad libre
          suficiente -> warning, con una evidencia por COMPONENTE (ficha /
          existencias). El componente SIEMPRE sale de la línea de BOM
          (``bom_line.product_id``); en ``mrp.bom.explode`` el campo
          ``data['product']`` es el producto PADRE (el kit), nunca el componente.
        - Si el kit además tiene quants propios, se añade ese dato como nota de
          contexto, SIN saltarse la evaluación de componentes.
        - Kit cuyos componentes alcanzan -> info (o ``ok`` si tiene quants
          propios, avisando de que revisarla si debería almacenarse).
        """
        kits = ctx['products'].filtered(lambda product: product.is_kits)
        if not kits:
            return [self._pf_finding(
                'kit_no_own_stock', 'kit', 'ok',
                _('Sin kits en el ámbito'),
                detail=_('Ninguno de los productos evaluados es un kit (BOM phantom).'),
            )]

        findings = []
        seen_boms = set()
        for product in kits:
            bom = self._pf_boms_for_product(product, bom_type='phantom')[:1]
            if not bom or bom.id in seen_boms:
                continue
            seen_boms.add(bom.id)
            # Se evalúan SIEMPRE los componentes, aunque el kit tenga quants.
            has_own_stock = bool(self._pf_quants_for_product(product, limit=1))
            missing = self._pf_kit_missing_components(ctx, bom, product)
            own_stock_note = _(
                ' Además, el kit tiene quants propios: revisa si debería '
                'almacenarse directamente en lugar de fabricarse.'
            ) if has_own_stock else ''
            if missing:
                evidences = []
                for item in missing:
                    component = item['product']
                    need = item['need']
                    available = item['free']
                    evidences.append(self._pf_evidence(
                        component.display_name,
                        detail=_('Requiere %(need).2f, libre %(free).2f') % {
                            'need': need, 'free': available,
                        },
                        product=component,
                        nav_kind='product',
                        res_model='product.product',
                        res_id=component.id,
                        # Causante recolectable: componente sin disponibilidad.
                        causante_type='component',
                        collectible=True,
                        ref_name=component.display_name,
                        qty=need,
                        qty_secondary=available,
                        action_kind='none',
                    ))
                findings.append(self._pf_finding(
                    'kit_no_own_stock', 'kit', 'warning',
                    _('Kit con componentes sin disponibilidad: %s') % product.display_name,
                    detail=_(
                        'El kit no guarda stock propio (su disponibilidad se '
                        'deriva de los componentes) y %s componente(s) no '
                        'tienen existencia libre suficiente.'
                    ) % len(missing) + own_stock_note,
                    product=product,
                    bom=bom,
                    record_count=len(missing),
                    nav_kind='bom',
                    action_hint=_('BOM del kit (componentes)'),
                    res_model='mrp.bom',
                    res_id=bom.id,
                    evidences=evidences,
                ))
            elif has_own_stock:
                findings.append(self._pf_finding(
                    'kit_no_own_stock', 'kit', 'ok',
                    _('Kit con existencias propias: %s') % product.display_name,
                    detail=_(
                        'El kit tiene quants propios y ninguno de sus '
                        'componentes presenta faltantes; revisa si debería '
                        'almacenarse directamente en lugar de fabricarse.'),
                    product=product,
                    bom=bom,
                    nav_kind='bom',
                    action_hint=_('BOM del kit (componentes)'),
                    res_model='mrp.bom',
                    res_id=bom.id,
                ))
            else:
                findings.append(self._pf_finding(
                    'kit_no_own_stock', 'kit', 'info',
                    _('Kit sin quants propios: disponibilidad derivada'),
                    detail=_(
                        'El kit %s no almacena stock propio. Su disponibilidad '
                        'se calcula a partir de los componentes de la BOM y '
                        'todos tienen existencia libre suficiente.'
                    ) % product.display_name,
                    product=product,
                    bom=bom,
                    nav_kind='bom',
                    action_hint=_('BOM del kit (componentes)'),
                    res_model='mrp.bom',
                    res_id=bom.id,
                    evidences=self._pf_quant_evidences(product),
                ))
        return findings or [self._pf_finding(
            'kit_no_own_stock', 'kit', 'ok',
            _('Sin incidencias en kits'),
            detail=_('Los kits evaluados no presentan faltantes de componentes.'),
        )]

    def _pf_kit_missing_components(self, ctx, bom, product):
        """Componentes de la BOM cuyo stock libre no cubre la cantidad requerida.

        Delega en ``printflow.stock.remedy._pf_missing_components`` (fuente única
        del desglose de BOM): allí el componente SIEMPRE se toma de
        ``bom_line.product_id`` y se invalida la caché de ``free_qty`` antes de
        comparar. En ``mrp.bom.explode`` el campo ``data['product']`` es el
        producto PADRE (el kit), por eso NO se usa.

        :return: Lista de dicts ``{'product', 'need', 'free'}``.
        :rtype: list[dict]
        """
        return self.env['printflow.stock.remedy']._pf_missing_components(
            product, 1.0)
