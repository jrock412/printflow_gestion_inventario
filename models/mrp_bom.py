# -*- coding: utf-8 -*-
"""Diagnóstico de archivado de BOM kit (PrintFlow) — FASE 1.

Explica por qué una BOM tipo kit (``phantom``) no se puede archivar y lista las
líneas de venta EXACTAS que la bloquean, reutilizando como ÚNICA autoridad la
regla real del core: ``sale_mrp.models.mrp_bom._ensure_bom_is_free``.

Este archivo agrega SOLO métodos de lectura sobre ``mrp.bom``:
  * No define campos nuevos ni requiere migración.
  * No sobrescribe ``toggle_active`` / ``write`` / ``unlink`` del core.
  * Nunca archiva, borra ni modifica nada: únicamente diagnostica.
"""

from odoo import _, models
from odoo.exceptions import UserError


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    def _pf_archive_blocking_product_ids(self):
        """Espejo EXACTO de la recolección de productos del core.

        Reproduce, para todo el recordset, la acumulación que hace
        ``sale_mrp.models.mrp_bom._ensure_bom_is_free``: por cada BOM kit se
        usan sus variantes concretas si el producto está desglosado, o TODAS
        las variantes de la plantilla si la BOM es a nivel de plantilla.

        :return: Lista de ids de ``product.product`` (con posibles duplicados,
            igual que el core).
        :rtype: list[int]
        """
        product_ids = []
        for bom in self:
            if bom.type != 'phantom':
                continue
            product_ids += bom.product_id.ids or bom.product_tmpl_id.product_variant_ids.ids
        return product_ids

    def _pf_archive_blocking_domain(self, product_ids):
        """Domain ESPEJO de la regla del core.

        Ruta y método del core (Odoo 17 CE):
            ``sale_mrp/models/mrp_bom.py`` -> ``_ensure_bom_is_free``
            (líneas 24-42). El core lo dispara desde ``toggle_active()`` (al
            archivar) y desde ``write()`` (al cambiar de ``phantom`` a otro
            tipo).

        Debe permanecer LÍNEA POR LÍNEA idéntico al del core; si el core
        cambia, el guardián anti-desincronización del wizard lo delata con los
        estados ``desync_core_stricter`` / ``desync_core_laxer``.

        :param product_ids: Variantes del kit devueltas por
            ``_pf_archive_blocking_product_ids``.
        :type product_ids: list[int]
        :return: Domain para ``sale.order.line``.
        :rtype: list
        """
        return [
            ('state', '=', 'sale'),
            ('invoice_status', 'in', ('no', 'to invoice')),
            ('product_id', 'in', product_ids),
            ('move_ids.state', '!=', 'cancel'),
        ]

    def _pf_get_archive_blocking_sale_lines(self):
        """Líneas de venta que el core considera bloqueantes (espejo).

        Solo aplica a BOM tipo kit: para cualquier otra BOM devuelve un
        recordset vacío. Usa ``sudo()`` igual que el core porque la comprobación
        debe funcionar aunque el usuario no pueda leer las ventas.

        :return: Recordset de ``sale.order.line``.
        """
        kit_boms = self.filtered(lambda bom: bom.type == 'phantom')
        product_ids = kit_boms._pf_archive_blocking_product_ids()
        if not product_ids:
            return self.env['sale.order.line']
        domain = self._pf_archive_blocking_domain(product_ids)
        return self.env['sale.order.line'].sudo().search(domain)

    def _pf_is_archive_blocked(self):
        """AUTORIDAD: ¿el core impediría archivar este recordset de BOM?

        NO reimplementa la condición: invoca ``_ensure_bom_is_free`` (la regla
        real del core) y traduce el ``UserError`` a un booleano. Para BOM que no
        son kit el core retorna sin error, por lo que devuelve ``False``.

        :return: ``True`` si el core lanzaría ``UserError`` al archivar.
        :rtype: bool
        """
        try:
            self._ensure_bom_is_free()
        except UserError:
            return True
        return False

    def action_open_bom_archive_diagnostic(self):
        """Abre (en ventana emergente) el diagnóstico de archivado de estas BOM.

        :return: Acción que abre el wizard en un popup (``target='new'``).
        """
        wizard = self.env['printflow.bom.archive.diagnostic.wizard'].create({
            'bom_ids': [(6, 0, self.ids)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Archivado de BOM (kit)'),
            'res_model': 'printflow.bom.archive.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
