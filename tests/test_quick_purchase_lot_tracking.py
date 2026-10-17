# -*- coding: utf-8 -*-
"""Lote de la Compra Rápida hacia la OC y el albarán de entrada (PrintFlow).

Custodia el contrato de la tarea de la Sección 3 del CONTEXT.md (hallazgo H-011):

  * **CA-1** — al confirmar la Compra Rápida de PrintFlow (``pf_freeze_qty=True``)
    con ``material_received=False`` y un lote indicado, el lote queda PERSISTIDO en
    el documento de compra: ``purchase.order.pf_lot_name == lote``.
  * **CA-2** — el albarán de entrada abierto de esa OC trae el lote PRE-RELLENADO en
    sus ``stock.move.line`` (``lot_id``/``lot_name``) y el ``stock.lot`` existe. El
    albarán NO se valida por detrás ("abrir ≠ ejecutar": queda ABIERTO).
  * **CA-3** — la Compra Rápida NORMAL (sin ``pf_freeze_qty``) queda INTACTA: no
    escribe ``pf_lot_name`` ni prellena lote; y la recepción AUTOMÁTICA
    (``material_received=True``) sigue validando el albarán como antes.
  * **CA-4** — solo LECTURA de lo existente + las escrituras propias del flujo;
    ``TransactionCase`` (rollback); sin ``cr.execute``/``cr.commit``; el motor
    externo ``x_product_dimensional_pricing`` SIN CAMBIOS (solo se hereda/reutiliza).

El lote se materializa reutilizando el helper canónico ``mrp.production._get_or_create_lot``
del motor (solo lectura/uso). El albarán se suelta SOLO por el botón nativo "Validar"
del operador; el fix NUNCA llama ``button_validate``.
"""

import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Archivos de PRODUCCIÓN del lote (solo lectura: sin SQL crudo ni commit).
_TOUCHED_FILES = (
    os.path.join('models', 'purchase_order.py'),
    os.path.join('models', 'printflow_quick_purchase_bridge.py'),
)


@tagged('post_install', '-at_install')
class TestQuickPurchaseLotTracking(TransactionCase):
    """CA-1..CA-4: el lote de la Compra Rápida viaja a la OC y a la entrada."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Quick = cls.env['mrp.quick.purchase.wizard']
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Lote Compra Rápida', 'supplier_rank': 1,
        })

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _lot_product(self, name):
        """Producto por LOTE, comprable, con proveedor (``seller_ids``)."""
        product = self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'tracking': 'lot',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
            'seller_ids': [(0, 0, {
                'partner_id': self.supplier.id, 'price': 10.0,
            })],
        })
        # Rutas limpias: la OC se crea por el wizard (no por reglas de almacén).
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _confirm_wizard(self, product, lot_name, material_received, freeze,
                        qty=5.0):
        """Abre la Compra Rápida (estilo PrintFlow) y confirma; devuelve la OC."""
        wizard = self.Quick.create({
            'pf_freeze_qty': freeze,
            'purchase_line_ids': [(0, 0, {
                'product_id': product.id,
                'product_qty': qty,
                'product_uom_id': product.uom_id.id,
                'partner_id': self.supplier.id,
                'lot_name': lot_name,
                'material_received': material_received,
            })],
        })
        before = self.env['purchase.order'].search([]).ids
        wizard.action_confirm()
        created = self.env['purchase.order'].search([('id', 'not in', before)])
        self.assertEqual(len(created), 1, 'Debe crearse UNA Orden de Compra.')
        return created

    def _incoming(self, po):
        picking = po.picking_ids.filtered(
            lambda p: getattr(p.picking_type_id, 'code', '') == 'incoming')
        self.assertTrue(
            picking, 'Confirmar la OC debe generar el albarán de entrada.')
        return picking

    # ==================================================================
    # CA-1 — El lote queda PERSISTIDO en la Orden de Compra
    # ==================================================================
    def test_ca1_lot_persisted_in_purchase_order(self):
        product = self._lot_product('LOTE COMPRA CA1')
        po = self._confirm_wizard(
            product, lot_name='LOTE-TEST', material_received=False, freeze=True)
        self.assertEqual(
            po.pf_lot_name, 'LOTE-TEST',
            'El lote de la Compra Rápida debe quedar persistido en la OC.')

    # ==================================================================
    # CA-2 — El albarán de entrada trae el lote PRE-RELLENADO (sin validar)
    # ==================================================================
    def test_ca2_incoming_move_line_prefilled_with_lot(self):
        product = self._lot_product('LOTE COMPRA CA2')
        po = self._confirm_wizard(
            product, lot_name='LOTE-TEST', material_received=False, freeze=True)
        picking = self._incoming(po)
        # "Abrir ≠ ejecutar": el albarán sigue ABIERTO (no se valida por detrás).
        self.assertNotIn(
            picking.state, ('done', 'cancel'),
            'El fix NO debe validar el albarán (abrir ≠ ejecutar).')
        move_lines = picking.move_ids.filtered(
            lambda m: m.product_id.tracking == 'lot').move_line_ids
        self.assertTrue(
            move_lines, 'La entrada debe traer su move line prellenada.')
        self.assertEqual(
            set(move_lines.mapped('lot_id.name')), {'LOTE-TEST'},
            'El lote previsto debe viajar prellenado en la move line.')
        lots = self.env['stock.lot'].search([
            ('name', '=', 'LOTE-TEST'), ('product_id', '=', product.id)])
        self.assertEqual(len(lots), 1, 'El stock.lot debe existir.')
        self.assertEqual(move_lines.mapped('lot_id'), lots)

    # ==================================================================
    # CA-3(a) — Compra Rápida NORMAL: sin persistencia ni prellenado
    # ==================================================================
    def test_ca3_normal_quick_purchase_no_lot(self):
        product = self._lot_product('LOTE COMPRA CA3N')
        po = self._confirm_wizard(
            product, lot_name='LOTE-NORMAL', material_received=False,
            freeze=False)
        self.assertFalse(
            po.pf_lot_name,
            'La Compra Rápida normal NO debe escribir pf_lot_name (GATE).')
        picking = self._incoming(po)
        self.assertFalse(
            picking.move_ids.mapped('move_line_ids.lot_id'),
            'La Compra Rápida normal NO debe prellenar lote (intacta).')
        self.assertFalse(self.env['stock.lot'].search([
            ('name', '=', 'LOTE-NORMAL'), ('product_id', '=', product.id)]))

    # ==================================================================
    # CA-3(b) — Recepción AUTOMÁTICA: el albarán se valida como antes
    # ==================================================================
    def test_ca3_automatic_reception_intact(self):
        product = self._lot_product('LOTE COMPRA CA3A')
        po = self._confirm_wizard(
            product, lot_name='LOTE-AUTO', material_received=True, freeze=False)
        self.assertFalse(
            po.pf_lot_name,
            'La recepción automática normal NO debe escribir pf_lot_name.')
        picking = self._incoming(po)
        self.assertEqual(
            picking.state, 'done',
            'La recepción automática debe seguir validando el albarán.')
        self.assertTrue(self.env['stock.lot'].search([
            ('name', '=', 'LOTE-AUTO'), ('product_id', '=', product.id)]))

    # ==================================================================
    # CA-4 — Solo lectura / motor externo intacto
    # ==================================================================
    def test_ca4_touched_files_have_no_raw_sql(self):
        module_path = get_module_path('printflow_gestion_inventario')
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)

    def test_ca4_external_motor_untouched(self):
        motor_path = get_module_path('x_product_dimensional_pricing')
        target = os.path.join(
            motor_path, 'wizard', 'mrp_quick_purchase_wizard.py')
        with open(target, encoding='utf-8') as handle:
            source = handle.read()
        # El motor NO conoce la marca de PrintFlow (solo se hereda desde aquí).
        self.assertNotIn('pf_freeze_qty', source)
        # Sus helpers canónicos siguen ahí (se REUTILIZAN, no se reinventan).
        self.assertIn('_get_or_create_lot', source)
        self.assertIn('_validate_incoming_pickings', source)
