# -*- coding: utf-8 -*-
"""Lanzadores de diagnóstico de PRODUCTO desde la ficha (PrintFlow).

Extiende ``product.template`` con los dos botones de la ficha que abren los
wizards del diagnóstico: el archivado de BOM kit (``..._bom_archive...``) y el
escáner de producto (``..._product_diagnostic_wizard``).

Vivían en ``models/product_template.py`` del PRINCIPAL; se movieron aquí (D4)
para que el principal quede con CERO referencias a los modelos del diagnóstico.
Al extraer ``diagnostic/``, estos launchers viajan con él.
"""

from odoo import _, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def action_open_bom_archive_diagnostic(self):
        """Abre el diagnóstico de archivado para las BOM kit activas del producto.

        Reúne SOLO las BOM activas de tipo ``phantom`` (las únicas que el core
        restringe al archivar) y delega en el wizard. Si no hay kits, avisa con
        una notificación informativa en lugar de lanzar un error.

        :return: Acción del wizard (popup) o notificación informativa.
        """
        self.ensure_one()
        kit_boms = self.bom_ids.filtered(
            lambda bom: bom.active and bom.type == 'phantom')
        if not kit_boms:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('PrintFlow'),
                    'message': _(
                        'Este producto no tiene BOM de tipo kit (phantom) activas '
                        'que diagnosticar.'),
                    'type': 'info',
                    'sticky': False,
                },
            }
        return kit_boms.action_open_bom_archive_diagnostic()

    def action_scan_product_diagnostic(self):
        """Abre el escáner de diagnóstico de producto (FASE 2).

        Decisión de UX: desde la ficha de producto se abre en POPUP
        (``target='new'``) y sin ``board_id`` (prueba de desacople del tablero).
        El escáner es de solo lectura y declara origen ``product`` para saber
        cómo comportarse.

        :return: Acción que abre el escáner en un popup.
        """
        self.ensure_one()
        variants = self.product_variant_ids
        wizard = self.env['printflow.product.diagnostic.wizard'].create({
            'product_tmpl_id': self.id,
            'product_ids': [(6, 0, variants.ids)],
            'origin': 'product',
            'origin_model': 'product.template',
            'origin_res_id': self.id,
            'origin_label': self.display_name,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Producto'),
            'res_model': 'printflow.product.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
