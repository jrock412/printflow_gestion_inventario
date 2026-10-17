# -*- coding: utf-8 -*-
"""Chequeo de rutas de abastecimiento (routing)."""

from odoo import _, api, models


class PrintflowProductCheckRouting(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de rutas de abastecimiento (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'no_route',
            'area': 'routing',
            'sequence': 10,
            'method': self._pf_check_no_route,
        }]

    def _pf_check_no_route(self, ctx):
        """Un producto almacenable sin ruta ni proveedor no se puede reponer.

        - Almacenable sin rutas ni proveedor -> warning, SALVO que sea
          fabricable (un producto con BOM/ruta de fabricación sí se repone).
        - Info con las rutas efectivas (propias + heredadas de la categoría).

        El conjunto de fabricables se resuelve UNA vez por barrido (batch, sin
        N+1) con el motor de salud.
        """
        findings = []
        route_infos = []
        products = ctx['products'].filtered(lambda p: p.type == 'product')
        manufacturable = ctx['env'][
            'printflow.order.health.engine']._pf_manufacturable_products(
            products)
        for product in products:
            routes = product.route_ids | product.route_from_categ_ids
            if (not routes and not product.seller_ids
                    and product.id not in manufacturable):
                findings.append(self._pf_finding(
                    'no_route', 'routing', 'warning',
                    _('Sin ruta ni proveedor: %s') % product.display_name,
                    detail=_(
                        'Producto almacenable sin ruta de abastecimiento ni '
                        'proveedor. No se podrá reponer automáticamente '
                        '(comprar o fabricar).'
                    ),
                    product=product,
                    record_count=1,
                    nav_kind='product',
                    action_hint=_('Ficha del producto (rutas)'),
                    res_model='product.product',
                    res_id=product.id,
                ))
            if routes:
                route_infos.append('%s: %s' % (
                    product.display_name, ', '.join(routes.mapped('name'))))
        if route_infos:
            findings.append(self._pf_finding(
                'no_route', 'routing', 'info',
                _('Rutas efectivas'),
                detail='\n'.join(route_infos),
            ))
        if not findings:
            findings.append(self._pf_finding(
                'no_route', 'routing', 'ok',
                _('Abastecimiento configurado'),
                detail=_('Los productos almacenables tienen ruta o proveedor definido.'),
            ))
        return findings
