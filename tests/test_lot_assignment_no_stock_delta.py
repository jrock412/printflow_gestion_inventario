# -*- coding: utf-8 -*-
"""CRÍTICO — asignar/corregir el lote de un terminado NO mueve existencia.

Custodia la FAMILIA de fallas "arreglo que toca stock como efecto secundario"
(quant negativo ``FONDO NEGRO`` generado por "Crear lotes sugeridos"):

  * (a) MO ``done`` sin lote con su terminado físico (``stock.move.line`` done)
    y la existencia SIN lote en destino: tras ``printflow_repair_lot`` /
    ``_pf_assign_lot_on_mo_doc`` la cantidad TOTAL de existencia del producto no
    cambia y NO aparece ningún quant negativo. El lote es un dato FORMAL: se
    re-etiqueta (lote viejo −, lote nuevo +) SIN alterar el físico total.
  * (b) si el "cajón sin lote" NO alcanza para cubrir la re-etiqueta, la
    operación se NIEGA (``UserError``) SIN modificar ningún quant.
  * (c) ``stock.move._pf_move_lot_stock`` mueve el físico entre lotes respetando
    el libre REAL del lote origen: nunca lo deja negativo ni toca el cajón sin
    lote. ``_pf_replace_generic_lot`` (que lo usa) tampoco deja un lote negativo.

Transaccional: ``TransactionCase`` hace rollback al terminar.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLotAssignmentNoStockDelta(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Lote Sin Delta'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        # Ubicación de producción VIRTUAL (usage='production'): el origen del
        # terminado no debe contar como existencia interna.
        cls.production_location = cls.env['stock.location'].create({
            'name': 'PF Virtual Production',
            'usage': 'production',
            'location_id': cls.env.ref(
                'stock.stock_location_locations_virtual').id,
        })
        cls.Production = cls.env['mrp.production']
        cls.Health = cls.env['printflow.stock.health']
        cls.Flow = cls.env['printflow.product.flow']

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

    def _stock(self, product, qty, lot=None, reserved=0.0, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty, lot_id=lot,
            reserved_quantity=reserved)

    def _exclusive_sale(self, product, qty=1.0):
        return self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })

    def _done_mo_no_lot(self, product, so, qty, dest_location):
        """MO ``done`` SIN lote con su terminado físico (``move_line`` SIN lote).

        La línea se crea ANTES de cerrar el movimiento: así su ``create`` no
        dispara el posteo de quants y el escenario queda controlado (es el estado
        que dejó la bug: MO vieja terminada sin lote + existencia sin lote).
        """
        manu_type = self.warehouse.manu_type_id
        mo = self.Production.create({
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': product.uom_id.id,
            'origin': so.name,
            'picking_type_id': manu_type.id,
            'location_src_id': self.production_location.id,
            'location_dest_id': dest_location.id,
        })
        finished = mo.move_finished_ids.filtered(
            lambda m: m.product_id == mo.product_id)
        self.env['stock.move.line'].create({
            'move_id': finished.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': mo.location_src_id.id,
            'location_dest_id': dest_location.id,
            'quantity': qty,
            'lot_id': False,
        })
        finished.write({'state': 'done'})
        mo.write({'state': 'done'})
        return mo, finished

    def _internal_quants(self, product):
        return self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ])

    def _internal_total(self, product):
        return sum(self._internal_quants(product).mapped('quantity'))

    def _assert_no_negative_internal(self, product):
        negatives = self._internal_quants(product).filtered(
            lambda q: q.quantity < -1e-6)
        self.assertFalse(
            negatives,
            'No debe quedar ningún quant interno negativo (fantasma): %s'
            % [(q.id, q.lot_id.name, q.quantity) for q in negatives])

    # ==================================================================
    # (a) Reparar el lote del terminado NO cambia la existencia total
    # ==================================================================
    def test_repair_finished_lot_keeps_stock(self):
        product = self._product('PF REPARAR LOTE A')
        so = self._exclusive_sale(product)
        qty = 5.0
        mo, _finished = self._done_mo_no_lot(
            product, so, qty, self.stock_location)
        # Existencia real del terminado, todavía SIN lote (el "cajón sin lote").
        self._stock(product, qty, lot=None, location=self.stock_location)
        self.assertFalse(mo.lot_producing_id)
        total_before = self._internal_total(product)
        self.assertAlmostEqual(total_before, qty, places=6)

        lot_id = self.Production.printflow_repair_lot(mo.id)

        lot = self.env['stock.lot'].browse(lot_id)
        self.assertEqual(mo.lot_producing_id, lot, 'El lote debe quedar asignado.')
        # La EXISTENCIA total no cambia (no se creó ni se destruyó físico).
        self.assertAlmostEqual(
            self._internal_total(product), total_before, places=6,
            msg='Reparar el lote no debe mover la existencia total.')
        self._assert_no_negative_internal(product)
        # El físico quedó bajo el lote nuevo (re-etiqueta, no creación).
        lot_qty = sum(self._internal_quants(product).filtered(
            lambda q: q.lot_id == lot).mapped('quantity'))
        self.assertAlmostEqual(lot_qty, qty, places=6)

    def test_assign_lot_on_mo_doc_keeps_stock(self):
        product = self._product('PF ASIGNAR DOC A')
        so = self._exclusive_sale(product)
        qty = 3.0
        mo, _finished = self._done_mo_no_lot(
            product, so, qty, self.stock_location)
        self._stock(product, qty, lot=None, location=self.stock_location)
        chosen = self._lot(product, 'PF-DOC-ELEGIDO')
        total_before = self._internal_total(product)

        res = self.Flow._pf_assign_lot_on_mo_doc(
            'mrp.production', mo.id, chosen, product)

        self.assertEqual(res, 1)
        self.assertEqual(mo.lot_producing_id, chosen)
        self.assertAlmostEqual(self._internal_total(product), total_before, places=6)
        self._assert_no_negative_internal(product)

    # ==================================================================
    # (b) Si el cajón sin lote no alcanza -> se NIEGA sin tocar quants
    # ==================================================================
    def test_repair_finished_lot_refuses_when_insufficient(self):
        product = self._product('PF REPARAR LOTE B')
        so = self._exclusive_sale(product)
        qty = 5.0
        mo, _finished = self._done_mo_no_lot(
            product, so, qty, self.stock_location)
        # NO se agrega existencia: el físico ya no está (p.ej. se despachó).
        total_before = self._internal_total(product)
        self.assertAlmostEqual(total_before, 0.0, places=6)

        with self.assertRaises(UserError):
            self.Production.printflow_repair_lot(mo.id)

        self.assertFalse(mo.lot_producing_id, 'La operación no debe asignar nada.')
        self.assertAlmostEqual(
            self._internal_total(product), total_before, places=6,
            msg='Negar la operación no debe modificar la existencia.')
        self._assert_no_negative_internal(product)

    def test_repair_refuses_partial_drawer(self):
        product = self._product('PF REPARAR LOTE B2')
        so = self._exclusive_sale(product)
        qty = 5.0
        mo, _finished = self._done_mo_no_lot(
            product, so, qty, self.stock_location)
        # Cajón sin lote INSUFICIENTE (2 de 5): debe negarse, no ir a negativo.
        self._stock(product, 2.0, lot=None, location=self.stock_location)
        total_before = self._internal_total(product)

        with self.assertRaises(UserError):
            self.Production.printflow_repair_lot(mo.id)

        self.assertFalse(mo.lot_producing_id)
        self.assertAlmostEqual(self._internal_total(product), total_before, places=6)
        self._assert_no_negative_internal(product)

    # ==================================================================
    # (c) _pf_move_lot_stock respeta el libre REAL y nunca deja negativo
    # ==================================================================
    def _move(self, product, qty):
        return self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
        })

    def test_move_lot_stock_never_negative(self):
        product = self._product('PF MOVER LOTE C')
        old = self._lot(product, 'PF-C-OLD')
        new = self._lot(product, 'PF-C-NEW')
        self._stock(product, 5.0, lot=old, reserved=2.0)
        move = self._move(product, 10.0)

        # El libre real del lote viejo es 5 - 2 = 3 (nunca toca el reservado).
        moved = move._pf_move_lot_stock(old, new, 10.0)

        self.assertAlmostEqual(moved, 3.0, places=6)
        old_q = sum(self._internal_quants(product).filtered(
            lambda q: q.lot_id == old).mapped('quantity'))
        new_q = sum(self._internal_quants(product).filtered(
            lambda q: q.lot_id == new).mapped('quantity'))
        self.assertAlmostEqual(old_q, 2.0, places=6)
        self.assertAlmostEqual(new_q, 3.0, places=6)
        self._assert_no_negative_internal(product)

    def test_move_lot_stock_does_not_steal_lotless(self):
        product = self._product('PF MOVER LOTE C2')
        old = self._lot(product, 'PF-C2-OLD')
        new = self._lot(product, 'PF-C2-NEW')
        # El lote viejo NO tiene existencia; el físico está en el cajón sin lote.
        self._stock(product, 8.0, lot=None)
        before = self._internal_total(product)
        move = self._move(product, 8.0)

        moved = move._pf_move_lot_stock(old, new, 8.0)

        self.assertAlmostEqual(moved, 0.0, places=6)
        self.assertAlmostEqual(self._internal_total(product), before, places=6)
        self._assert_no_negative_internal(product)

    def test_replace_generic_lot_never_negative(self):
        product = self._product('PF GENERICO INSUF')
        generic = self._lot(product, 'LOTE-GENERICO-INSUF')
        self._stock(product, 1.0, lot=generic)
        sale = self._exclusive_sale(product, qty=2.0)
        sale_line = sale.order_line[:1]
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
            'sale_line_id': sale_line.id,
        })
        move._action_confirm()
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'picking_id': picking.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'quantity': 2.0,
            'lot_id': generic.id,
        })
        before = self._internal_total(product)

        self.Health._pf_replace_generic_lot(product)

        self.assertAlmostEqual(self._internal_total(product), before, places=6)
        self._assert_no_negative_internal(product)

    # ==================================================================
    # CRÍTICO 2 — el ajustador de stock expuesto por RPC se eliminó
    # ==================================================================
    def test_adjust_lot_stock_rpc_removed(self):
        Production = type(self.env['mrp.production'])
        self.assertFalse(
            any('printflow_adjust_lot_stock' in klass.__dict__
                for klass in Production.__mro__),
            'printflow_adjust_lot_stock (RPC destructivo) debe estar eliminado.')
