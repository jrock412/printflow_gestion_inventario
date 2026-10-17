# -*- coding: utf-8 -*-
"""FASE 1 — Diagnóstico de archivado de BOM kit.

Verifica que el domain espejo del core (``sale_mrp._ensure_bom_is_free``)
coincida con la autoridad (``_pf_is_archive_blocked``):

  * Kit con línea confirmada "to invoice" -> bloquea y el espejo la devuelve.
  * Kit con línea "invoiced"              -> NO bloquea.
  * BOM normal (no kit)                   -> nunca bloquea.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticBomArchive(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Diagnostico BOM Archive',
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        """Producto almacenable: su venta confirmada queda 'to invoice'."""
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
        })

    def _make_bom(self, product, bom_type='phantom'):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'type': bom_type,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
        })

    def _make_sale_line(self, product, qty=1.0, invoice_status=None):
        """Pedido forzado a 'sale' con una línea del producto.

        El forzado de estado evita disparar la cadena de entrega/fabricación en
        el test, pero se crea un movimiento de stock en BORRADOR vinculado a la
        línea: una venta real siempre lo tiene y el core
        (``_ensure_bom_is_free``) exige ``move_ids.state != 'cancel'`` (un
        One2many vacío NO cumple esa condición en Odoo 17).
        """
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        line = so.order_line[:1]
        self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'sale_line_id': line.id,
            'location_id': self.env['stock.location'].search(
                [('usage', '=', 'internal')], limit=1).id,
            'location_dest_id': self.env['stock.location'].search(
                [('usage', '=', 'customer')], limit=1).id,
        })
        if invoice_status:
            # ``invoice_status`` es un campo almacenado: el ORM permite fijarlo
            # directamente y así se prueba el domain real del core sin montar
            # una factura completa.
            line.write({'invoice_status': invoice_status})
        return line

    # ------------------------------------------------------------------
    # Casos
    # ------------------------------------------------------------------
    def test_kit_con_linea_a_facturar_bloquea(self):
        product = self._make_product('KIT BLOQUEADO (DIAG)')
        bom = self._make_bom(product, 'phantom')
        line = self._make_sale_line(product)

        self.assertEqual(
            line.invoice_status, 'to invoice',
            'La venta confirmada de un producto almacenable debe quedar "to invoice".',
        )
        self.assertTrue(
            bom._pf_is_archive_blocked(),
            'El core debe bloquear el archivado de un kit con venta pendiente.',
        )
        self.assertIn(
            line, bom._pf_get_archive_blocking_sale_lines(),
            'El domain espejo debe devolver la misma línea que bloquea el core.',
        )

    def test_kit_con_linea_facturada_no_bloquea(self):
        product = self._make_product('KIT FACTURADO (DIAG)')
        bom = self._make_bom(product, 'phantom')
        line = self._make_sale_line(product, invoice_status='invoiced')

        self.assertEqual(line.invoice_status, 'invoiced')
        self.assertFalse(
            bom._pf_is_archive_blocked(),
            'Una venta ya facturada no debe bloquear el archivado.',
        )
        self.assertFalse(
            bom._pf_get_archive_blocking_sale_lines(),
            'El domain espejo tampoco debe devolver líneas facturadas.',
        )

    def test_bom_normal_nunca_bloquea(self):
        product = self._make_product('BOM NORMAL (DIAG)')
        bom = self._make_bom(product, 'normal')
        self._make_sale_line(product)

        self.assertFalse(
            bom._pf_is_archive_blocked(),
            'El core solo restringe BOM tipo kit: una BOM normal nunca bloquea.',
        )
        self.assertFalse(
            bom._pf_get_archive_blocking_sale_lines(),
            'El espejo debe devolver vacío para una BOM que no es kit.',
        )
