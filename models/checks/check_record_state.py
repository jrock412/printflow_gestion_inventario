# -*- coding: utf-8 -*-
"""Chequeo del estado de la ficha del producto (archivado, sin proveedor, código)."""

from odoo import _, api, models


class PrintflowProductCheckRecordState(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo del estado de la ficha (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'record_state',
            'area': 'record',
            'sequence': 10,
            'method': self._pf_check_record_state,
        }]

    def _pf_check_record_state(self, ctx):
        """Resume el estado de la ficha: archivado, sin proveedor y código.

        - Producto archivado                  -> warning.
        - Almacenable sin proveedor           -> warning, SALVO que sea
          fabricable (un producto con BOM/ruta de fabricación no necesita
          proveedor para reponerse).
        - Info con el código interno de cada ficha.
        """
        findings = []
        infos = []
        # Conjunto de fabricables resuelto UNA vez por barrido (batch, sin N+1).
        manufacturable = ctx['env'][
            'printflow.order.health.engine']._pf_manufacturable_products(
            ctx['products'])
        for product in ctx['products']:
            if not product.active:
                findings.append(self._pf_finding(
                    'record_state', 'record', 'warning',
                    _('Producto archivado: %s') % product.display_name,
                    detail=_('La ficha está archivada (activo = no). No aparece '
                             'en búsquedas por defecto ni se puede vender.'),
                    product=product,
                    record_count=1,
                    nav_kind='product',
                    action_hint=_('Ficha del producto'),
                    res_model='product.product',
                    res_id=product.id,
                ))
            if (product.type == 'product' and not product.seller_ids
                    and product.id not in manufacturable):
                findings.append(self._pf_finding(
                    'record_state', 'record', 'warning',
                    _('Almacenable sin proveedor: %s') % product.display_name,
                    detail=_('Producto almacenable sin proveedor configurado: '
                             'no se podrá comprar automáticamente.'),
                    product=product,
                    record_count=1,
                    nav_kind='product',
                    action_hint=_('Ficha del producto'),
                    res_model='product.product',
                    res_id=product.id,
                ))
            infos.append('%s -> %s' % (
                product.display_name,
                product.default_code or _('sin código interno'),
            ))
        if infos:
            findings.append(self._pf_finding(
                'record_state', 'record', 'info',
                _('Fichas evaluadas'),
                detail='\n'.join(infos[:50]),
            ))
        if not findings and not infos:
            findings.append(self._pf_finding(
                'record_state', 'record', 'info',
                _('Sin productos que evaluar'),
            ))
        return findings
