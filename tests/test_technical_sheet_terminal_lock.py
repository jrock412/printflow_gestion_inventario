# -*- coding: utf-8 -*-
"""Candado de fichas terminales al recibir/entregar (PrintFlow).

Custodia el contrato de la tarea de la Sección 3 del CONTEXT.md (hallazgo H-013):
al validar un albarán, el motor ``x_product_dimensional_pricing`` recalcula las
fichas de los pedidos del ``origin`` con ``_compute_state_from_docs()``, que
asigna ``is_partial_fabrication`` (``compute + store``) a TODAS las fichas,
incluidas las de estado TERMINAL. Sin la extensión ADITIVA de la whitelist del
candado, esa asignación disparaba el ``UserError`` "No se puede modificar una
ficha finalizada, cancelada o archivada" y bloqueaba la recepción.

  * **CA-1** — un albarán de ENTRADA cuyo ``origin`` referencia pedidos con ficha
    terminal **se valida** sin ``UserError`` (queda ``done``).
  * **CA-2** — la ficha terminal **no se altera** (sigue ``archived_delivered``);
    una ficha NO bloqueada del mismo documento **sí se recalcula**; y escribir un
    campo de negocio en la bloqueada **sigue** lanzando ``UserError`` (el candado
    permanece estricto: solo se habilita el campo computado).
  * **CA-3** — el hook gemelo de ENTREGA queda saneado con el MISMO arreglo: un
    albarán de SALIDA cuya línea de venta tenga ficha terminal se valida sin
    ``UserError``.
  * **CA-4** — solo LECTURA + escrituras propias del cómputo; ``TransactionCase``
    (rollback); el archivo de producción nuevo sin ``cr.execute``/``cr.commit``;
    la clase de PrintFlow queda registrada en el MRO del modelo del motor.
"""

import os

from odoo.exceptions import UserError
from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Archivo de PRODUCCIÓN del candado (solo lectura: sin SQL crudo ni commit).
_TOUCHED_FILES = (os.path.join('models', 'mrp_technical_sheet.py'),)

_PF_MODULE = 'printflow_gestion_inventario'


@tagged('post_install', '-at_install')
class TestTechnicalSheetTerminalLock(TransactionCase):
    """CA-1..CA-4: el candado terminal respeta el cómputo sin bloquear el albarán."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Sheet = cls.env['mrp.technical.sheet']
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Candado Terminal'})
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Proveedor Candado Terminal', 'supplier_rank': 1})

    # ------------------------------------------------------------------
    # Utilidades de armado
    # ------------------------------------------------------------------
    def _product(self, name):
        """Producto de stock, comprable y gestionado por PrintFlow."""
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
            'purchase_ok': True,
            'x_is_printflow_managed': True,
        })

    def _sale_order(self, product, qty=2.0):
        """Pedido de venta confirmado con una línea del producto."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
            })],
        })
        so.action_confirm()
        return so

    def _sheet_for(self, so, product, name='Ficha Candado'):
        """Ficha técnica ligada a la línea del producto en el pedido."""
        line = so.order_line.filtered(lambda l: l.product_id == product)[:1]
        return self.Sheet.create({'sale_line_id': line.id, 'name': name})

    def _force_terminal(self, sheet, state='archived_delivered'):
        """Fuerza el estado TERMINAL saltando el candado (setup del test)."""
        sheet.with_context(bypass_sheet_write_lock=True).write({'state': state})
        sheet.flush_recordset()
        self.assertEqual(sheet.state, state)
        return sheet

    def _purchase_order(self, product, so, qty=2.0):
        """OC (``origin`` = pedido) confirmada: genera el albarán de entrada."""
        po = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'origin': so.name,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        po.button_confirm()
        return po

    def _incoming(self, po):
        picking = po.picking_ids.filtered(
            lambda p: getattr(p.picking_type_id, 'code', '') == 'incoming')
        self.assertTrue(picking, 'La OC debe generar el albarán de entrada.')
        return picking

    def _outgoing(self, so):
        picking = so.picking_ids.filtered(
            lambda p: getattr(p.picking_type_id, 'code', '') == 'outgoing')
        self.assertTrue(picking, 'El pedido debe generar el albarán de salida.')
        return picking

    def _pick_fully(self, picking):
        """Asigna y marca el picking completo (sin backorder: recepción/entrega total)."""
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True

    def _stock_location(self):
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        return warehouse.lot_stock_id

    # ==================================================================
    # CA-1 — El albarán de ENTRADA se valida con ficha terminal en el origin
    # ==================================================================
    def test_ca1_incoming_validates_with_terminal_sheet(self):
        product = self._product('CANDADO ENTRADA CA1')
        so = self._sale_order(product)
        sheet = self._force_terminal(self._sheet_for(so, product))
        picking = self._incoming(self._purchase_order(product, so))
        self._pick_fully(picking)

        # Sin la extensión de la whitelist, el cómputo del motor lanzaría el
        # UserError al escribir el campo computado en la ficha archivada.
        picking.button_validate()

        self.assertEqual(
            picking.state, 'done',
            'El albarán de entrada debe poder validarse (sin UserError).')
        self.assertEqual(
            sheet.state, 'archived_delivered',
            'La ficha terminal no debe alterarse.')

    # ==================================================================
    # CA-2 — Terminal intacta, no-bloqueada recalculada y candado estricto
    # ==================================================================
    def test_ca2_terminal_untouched_and_lock_intact(self):
        product = self._product('CANDADO CA2')
        so = self._sale_order(product)
        blocked = self._force_terminal(
            self._sheet_for(so, product, 'Ficha Bloqueada'))
        # Ficha NO bloqueada del mismo documento, marcada con un estado OBSOLETO
        # para comprobar que el recálculo del hook la refresca.
        live = self._sheet_for(so, product, 'Ficha Viva')
        live.with_context(bypass_sheet_write_lock=True).write({'state': 'draft'})
        self.assertEqual(live.state, 'draft')

        picking = self._incoming(self._purchase_order(product, so))
        self._pick_fully(picking)
        picking.button_validate()

        # La bloqueada NO cambió...
        self.assertEqual(
            blocked.state, 'archived_delivered',
            'La ficha terminal debe conservar su estado.')
        # ...y la NO bloqueada SÍ fue recalculada por el hook.
        self.assertNotEqual(
            live.state, 'draft',
            'Una ficha no bloqueada del mismo documento debe recalcularse.')
        # El candado sigue estricto: un campo de negocio sigue prohibido.
        with self.assertRaises(UserError):
            blocked.write({'name': 'intento manual'})

    # ==================================================================
    # CA-3 — El hook gemelo de ENTREGA queda saneado con el mismo arreglo
    # ==================================================================
    def test_ca3_outgoing_validates_with_terminal_sheet(self):
        product = self._product('CANDADO SALIDA CA3')
        so = self._sale_order(product)
        self._force_terminal(self._sheet_for(so, product))
        picking = self._outgoing(so)
        # Stock suficiente para completar la entrega sin backorder.
        self.env['stock.quant']._update_available_quantity(
            product, self._stock_location(), 10.0)
        self._pick_fully(picking)

        picking.button_validate()

        self.assertEqual(
            picking.state, 'done',
            'El albarán de salida debe poder validarse (sin UserError).')

    # ==================================================================
    # CA-4 — Solo lectura / motor intacto / extensión registrada
    # ==================================================================
    def test_ca4_touched_files_have_no_raw_sql(self):
        module_path = get_module_path(_PF_MODULE)
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)

    def test_ca4_printflow_class_registered_and_whitelist_extended(self):
        cls = type(self.Sheet)
        pf_classes = [
            klass for klass in cls.mro()
            if _PF_MODULE in (klass.__module__ or '')
        ]
        self.assertTrue(
            pf_classes,
            'La clase de PrintFlow debe estar registrada en el MRO del modelo.')
        self.assertTrue(
            any('_printflow_skip_terminal_write_lock' in klass.__dict__
                for klass in pf_classes),
            'PrintFlow debe sobrescribir el método-seam del candado.')

        # Set ADITIVO propio presente (el motor NO se redefine).
        self.assertIn(
            'is_partial_fabrication', self.Sheet._PF_TERMINAL_EXTRA_WRITE_FIELDS)

        sheet = self._force_terminal(
            self.Sheet.create({'name': 'Candado seam CA4'}))
        # El campo computado queda permitido en la ficha terminal...
        self.assertTrue(sheet._printflow_skip_terminal_write_lock(
            {'is_partial_fabrication': False}))
        # ...y el candado del motor conserva EXACTAMENTE su comportamiento.
        self.assertTrue(sheet._printflow_skip_terminal_write_lock(
            {'production_id': 1}))
        self.assertFalse(sheet._printflow_skip_terminal_write_lock(
            {'dim_width': 10.0}))
        self.assertTrue(
            sheet.with_context(bypass_sheet_write_lock=True)
            ._printflow_skip_terminal_write_lock({'dim_width': 10.0}))
