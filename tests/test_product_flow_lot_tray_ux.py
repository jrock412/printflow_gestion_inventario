# -*- coding: utf-8 -*-
"""UX de la bandeja de lote: "Corregible" y contexto propio/actual (PrintFlow).

Custodia que la bandeja:
  * exponga el lote PROPIO y el lote ACTUAL de la fila;
  * marque "Corregible" (``can_correct_doc``) según la ventana del documento;
  * oculte el botón "Elegir lote" cuando el documento no es corregible.

``TransactionCase`` hace rollback; crea sus propios registros.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowLotTrayUx(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Tray UX'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None, reserved=0.0):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot,
            reserved_quantity=reserved)

    def _outgoing(self, product, lot, sale_line=None):
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        move = self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': 2.0,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
        })
        move._action_confirm()
        # La reserva nativa (at_confirm) tomaría el lote con stock y
        # contaminaría el disponible esperado: la soltamos antes de crear la
        # línea manual con el lote indicado.
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'quantity': 2.0,
            'lot_id': lot.id,
        })
        if sale_line:
            move.sale_line_id = sale_line.id
        return picking, move

    def _tray(self, product, lot_state):
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        return self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])

    def _sale_line(self, product):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 2.0,
                'product_uom': product.uom_id.id,
            })],
        })
        return order.order_line.filtered(
            lambda line: line.product_id == product)[:1]

    # ==================================================================
    # La bandeja expone propio/actual y marca "Corregible"
    # ==================================================================
    def test_tray_exposes_context_and_corregible(self):
        product = self._product('TRAY UX')
        line = self._sale_line(product)
        own_name = line._get_exclusive_lot_name()
        ghost = self._lot(product, 'TRAY-UX-FANTASMA')
        picking, _move = self._outgoing(product, ghost, sale_line=line)

        tray = self._tray(product, 'lot_no_stock')
        row = tray.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        self.assertTrue(row)
        self.assertEqual(row.lot_name_actual, ghost.name)
        self.assertEqual(row.own_lot_name, own_name)
        self.assertTrue(row.can_correct_doc, 'El documento está abierto.')

        # Documento validado: deja de ser corregible.
        picking.write({'state': 'done'})
        tray2 = self._tray(product, 'lot_no_stock')
        row2 = tray2.filtered(lambda r: r.kind == 'no_stock_lot')[:1]
        self.assertTrue(row2)
        self.assertFalse(row2.can_correct_doc)

    # ==================================================================
    # La bandeja expone la EXISTENCIA del lote original y del usado
    # ==================================================================
    def test_tray_exposes_lot_quantities(self):
        product = self._product('TRAY UX QTY')
        line = self._sale_line(product)
        own_name = line._get_exclusive_lot_name()
        own_lot = self._lot(product, own_name)
        self._stock(product, 4.0, lot=own_lot)
        used = self._lot(product, 'LOTE-GENERICO-TRAY-QTY')
        self._stock(product, 7.0, lot=used, reserved=2.0)
        _picking, _move = self._outgoing(product, used, sale_line=line)

        tray = self._tray(product, 'lot_generic')
        row = tray.filtered(lambda r: r.kind == 'generic_lot')[:1]
        self.assertTrue(row)
        self.assertEqual(row.own_lot_name, own_name)
        self.assertAlmostEqual(row.own_lot_qty, 4.0)
        self.assertEqual(row.lot_name, used.name)
        self.assertAlmostEqual(row.used_lot_qty, 7.0)
        self.assertAlmostEqual(row.used_lot_available, 5.0)

    # ==================================================================
    # Guardia de vista: el botón "Elegir lote" se oculta si no es corregible
    # ==================================================================
    def test_view_hides_picker_when_not_correctable(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree').arch
        self.assertIn('can_correct_doc', arch)
        self.assertIn('lot_name_actual', arch)
        # Columnas mínimas para decidir.
        self.assertIn('name="own_lot_name"', arch)
        self.assertIn('name="own_lot_qty"', arch)
        self.assertIn('name="used_lot_qty"', arch)
        self.assertIn('name="used_lot_available"', arch)

    # ==================================================================
    # Guardia de vista: el lote propio se rotula "sugerido" (no "original")
    # ==================================================================
    def test_view_labels_own_lot_as_suggested(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree').arch
        # Etiquetas nuevas visibles.
        self.assertIn('string="Lote sugerido"', arch)
        self.assertIn('string="Existencia sugerida"', arch)
        # Las etiquetas engañosas desaparecen.
        self.assertNotIn('Lote original', arch)
        self.assertNotIn('Existencia original', arch)
        # Los nombres TÉCNICOS de los campos quedan intactos.
        self.assertIn('name="own_lot_name"', arch)
        self.assertIn('name="own_lot_qty"', arch)

    # ==================================================================
    # Guardia de vista: la OF terminada sin lote CON lote sugerido NO
    # ofrece "Elegir lote" (se resuelve creando el sugerido en cabecera).
    # ==================================================================
    def test_view_hides_picker_for_unassigned_mo_with_suggested_lot(self):
        """La fila ``unassigned_mo`` con ``own_lot_name`` oculta "Elegir lote".

        El caso se resuelve CREANDO el lote sugerido (corrección de cabecera
        "Reparar el lote del terminado"); "Elegir lote" solo queda como salida de
        emergencia cuando NO hay lote sugerido. La condición se aplica igual en
        la lista (tree) y en el formulario (form).
        """
        condition = "kind == 'unassigned_mo' and own_lot_name"
        for xml_id in (
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree',
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_form',
        ):
            arch = self.env.ref(xml_id).arch
            self.assertIn(condition, arch, 'Debe ocultar el botón en %s.' % xml_id)

    # ==================================================================
    # Guardia de vista: columna "Documento" + existencias condicionales
    # ==================================================================
    def test_tree_exposes_document_and_conditional_quantities(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_tree').arch
        # Columna Documento legible (agnóstica al modelo de la fila).
        self.assertIn('name="document_ref"', arch)
        self.assertIn('string="Documento"', arch)
        # Modo declarado (oculto) para poder evaluar las condiciones por fila.
        self.assertIn('name="lot_action_mode"', arch)
        # Las TRES columnas de existencia se muestran SOLO al ASIGNAR un lote.
        self.assertEqual(
            arch.count("invisible=\"lot_action_mode != 'assign'\""), 3,
            'Las 3 columnas de existencia deben depender de lot_action_mode.')
        # Rótulo dinámico: el MISMO campo con DOS strings mutuamente excluyentes.
        self.assertEqual(arch.count('name="own_lot_name"'), 2)
        self.assertIn('string="Lote sugerido"', arch)
        self.assertIn('string="Lote propio"', arch)
        self.assertIn("invisible=\"lot_action_mode != 'create'\"", arch)
        # Los nombres TÉCNICOS quedan intactos.
        for fname in ('own_lot_name', 'own_lot_qty', 'used_lot_qty',
                      'used_lot_available'):
            self.assertIn('name="%s"' % fname, arch)
        # F7: el botón "Abrir documento" se ELIMINA de la lista; el gesto natural
        # de abrir el documento es el clic en la columna "Documento"
        # (``document_ref``, Reference navegable, ya presente arriba).
        self.assertNotIn('string="Abrir documento"', arch)
        self.assertNotIn('name="action_open" type="object"', arch)

    def test_form_exposes_document_and_dynamic_label(self):
        arch = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_tray_view_form').arch
        self.assertIn('name="document_ref"', arch)
        self.assertIn('name="lot_action_mode"', arch)
        self.assertEqual(arch.count('name="own_lot_name"'), 2)
        self.assertIn('string="Lote sugerido"', arch)
        self.assertIn('string="Lote propio"', arch)
