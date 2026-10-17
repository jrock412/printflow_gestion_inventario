# -*- coding: utf-8 -*-
"""Chequeo de órdenes de fabricación activas."""

from odoo import _, api, models

# Límite de MO leídas por barrido. Si el resultado lo alcanza, se avisa del
# truncado (puede haber más MO no evaluadas).
_MO_LIMIT = 100


class PrintflowProductCheckManufacturing(models.AbstractModel):
    _inherit = 'printflow.product.check.mixin'
    _description = 'Chequeo de fabricación (PrintFlow)'

    @api.model
    def _pf_get_checks(self):
        return super()._pf_get_checks() + [{
            'code': 'active_mo',
            'area': 'manufacturing',
            'sequence': 10,
            'method': self._pf_check_active_mo,
        }]

    def _pf_check_active_mo(self, ctx):
        """Órdenes de fabricación activas que bloquean editar/borrar la BOM.

        El core no permite borrar una BOM con MO en curso
        (``mrp.bom._unlink_except_running_mo``). Aquí solo se avisa.
        """
        products = ctx['products']
        if not products:
            return [self._pf_finding(
                'active_mo', 'manufacturing', 'info',
                _('Sin productos que evaluar'),
            )]
        mos = ctx['env']['mrp.production'].search([
            ('product_id', 'in', products.ids),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=_MO_LIMIT)
        truncated = len(mos) >= _MO_LIMIT
        if not mos:
            return [self._pf_finding(
                'active_mo', 'manufacturing', 'info',
                _('Sin órdenes de fabricación activas'),
                detail=_('Los productos evaluados no tienen MO en curso: sus BOM '
                         'se pueden editar o borrar sin bloqueos de producción.'),
            )]
        evidences = [
            self._pf_evidence(
                _('%s · %s') % (mo.name, mo.state),
                detail=_('Cantidad %(qty).2f | producto %(product)s') % {
                    'qty': mo.product_qty,
                    'product': mo.product_id.display_name,
                },
                product=mo.product_id,
                mo=mo,
                nav_kind='mo',
                res_model='mrp.production',
                res_id=mo.id,
                # Causante recolectable: la orden de fabricación activa.
                causante_type='mo',
                collectible=True,
                ref_name=mo.name,
                partner_name=mo.product_id.display_name,
                qty=mo.product_qty,
                state_label=self._pf_selection_label(mo, 'state'),
                date_ref=mo.date_start,
                action_kind='none',
            )
            for mo in mos
        ]
        findings = [self._pf_finding(
            'active_mo', 'manufacturing', 'warning',
            _('Órdenes de fabricación activas'),
            detail=_(
                '%s MO en curso referencian estos productos. Mientras estén '
                'activas, el core impide borrar sus BOM; los cambios pueden '
                'marcar la BOM como desactualizada.'
            ) % len(mos),
            record_count=len(mos),
            nav_kind='mo_list',
            action_hint=_('Órdenes de fabricación (%s)') % len(mos),
            evidences=evidences,
        )]
        if truncated:
            findings.append(self._pf_finding(
                'active_mo', 'manufacturing', 'info',
                _('Resultado limitado a %s órdenes') % _MO_LIMIT,
                detail=_(
                    'Se leyeron las primeras %s órdenes de fabricación activas; '
                    'puede haber más fuera del ámbito de este barrido.'
                ) % _MO_LIMIT,
            ))
        return findings
