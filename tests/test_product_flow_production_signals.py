# -*- coding: utf-8 -*-
"""Señales REALES de la OF y cadena de fallas en el diagrama del PRODUCTO.

Candado de la alineación del diagrama de producto con el del pedido:

  * CA-1: con una Orden de Fabricación ACTIVA, el nodo FABRICACIÓN refleja la
    realidad (ya NO dice "No aplica"). Antes ``active_mos``/``done_mos`` iban
    QUEMADOS en vacío en ``printflow.flow.strategy.product._pf_flow_context`` y
    el nodo quedaba ciego aunque el badge de pendientes sí contara la OF.
  * CA-2: cuando hay fallas encadenadas, el diagrama muestra la CADENA DE FALLAS
    (``global.chain_summary`` y el campo homónimo del wizard), igual que el
    pedido. Antes ``chain_summary`` iba quemado en vacío.
  * Contraste (D2): un fabricable SIN OF sigue ``na`` (no se fabrica un falso
    "sin orden").

Es de SOLO LECTURA: crea sus propios registros y ``TransactionCase`` hace
rollback al terminar (cero escritura persistente). No usa ``cr.execute`` ni
``cr.commit``: el módulo es de lectura para el producto.
"""

import json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowProductionSignals(TransactionCase):
    """La estrategia del producto lee la OF real y arma la cadena de fallas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Señales OF', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Flow = cls.env['printflow.product.flow']
        cls.Canvas = cls.env['printflow.flow.canvas']
        cls.Strategy = cls.env['printflow.flow.strategy.product']

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests del producto)
    # ------------------------------------------------------------------
    def _product(self, name, **extra):
        vals = {
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
        }
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _manufacturable(self, name):
        """Terminado fabricable con BOM a un COMPONENTE (sin stock)."""
        component = self._product('%s COMPONENTE' % name)
        finished = self._product(name)
        finished.product_tmpl_id.route_ids = [(5, 0, 0)]
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [(0, 0, {
                'product_id': component.id, 'product_qty': 1.0})],
        })
        return finished

    def _purchasable(self, name):
        product = self._product(
            name, purchase_ok=True,
            seller_ids=[(0, 0, {'partner_id': self.supplier.id})])
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _make_mo(self, product, qty=1.0):
        """OF en BORRADOR (activa: ``state`` != cancel/done) con su BOM."""
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        return self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': product.uom_id.id,
            'bom_id': bom.id if bom else False,
        })

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        return self.Flow.browse(action['res_id'])

    def _payload(self, wizard):
        return self.Canvas._pf_build_payload(wizard, 'product')

    def _node(self, payload, key):
        return next(node for node in payload['nodes'] if node['key'] == key)

    # ==================================================================
    # CA-1: la OF real enciende FABRICACIÓN
    # ==================================================================
    def test_active_mo_is_not_na(self):
        """Con una OF viva, FABRICACIÓN deja de decir "No aplica"."""
        product = self._manufacturable('SENAL OF ACTIVA')
        mo = self._make_mo(product)
        self.assertNotIn(
            mo.state, ('cancel', 'done'),
            'La OF de prueba debe estar activa (no cancelada ni terminada).')

        wizard = self._wizard(product)
        payload = self._payload(wizard)
        self.assertEqual(payload['flow_type'], 'manufacture')
        node = self._node(payload, 'production')
        self.assertNotEqual(
            node['status'], 'na',
            'El nodo Fabricación no debe quedar "No aplica" con OF activa.')
        self.assertNotEqual(node['tone'], 'na')

    def test_without_mo_manufacturable_stays_na(self):
        """Contraste (D2): un fabricable SIN OF sigue ``na`` (sin falso no_mo)."""
        product = self._manufacturable('SENAL SIN OF')
        wizard = self._wizard(product)
        payload = self._payload(wizard)
        node = self._node(payload, 'production')
        self.assertEqual(node['status'], 'na')
        self.assertEqual(node['tone'], 'na')

    # ==================================================================
    # CA-2: la cadena de fallas del producto (raíz -> consecuencias)
    # ==================================================================
    def test_chain_summary_purchase_deficit(self):
        """Déficit físico: Compras (origen) -> Inventario (consecuencia)."""
        product = self._purchasable('SENAL CADENA COMPRA')
        # Existencia negativa -> déficit físico -> Compras raíz + Inventario.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        wizard = self._wizard(product)
        payload = self._payload(wizard)
        summary = payload['global']['chain_summary']
        self.assertTrue(summary, 'La cadena de fallas no debe estar vacía.')
        self.assertIn('(origen)', summary)
        self.assertIn('(consecuencia)', summary)
        self.assertIn(' → ', summary)
        # El campo del wizard es el MISMO texto (lo pinta la franja de la vista).
        self.assertEqual(wizard.chain_summary, summary)

    def test_chain_summary_empty_when_healthy(self):
        """Un producto sano NO inventa cadena de fallas."""
        product = self._purchasable('SENAL CADENA SANA')
        wizard = self._wizard(product)
        payload = self._payload(wizard)
        self.assertFalse(payload['global']['chain_summary'])
        self.assertFalse(wizard.chain_summary)

    # ==================================================================
    # D1: el helper de lectura de OF reutiliza la clasificación del motor
    # ==================================================================
    def test_product_mos_helper_classifies(self):
        product = self._manufacturable('SENAL HELPER MOS')
        self.assertFalse(
            self.Strategy._pf_product_mos(product)['non_done'],
            'Sin OF, los baldes van vacíos.')
        mo = self._make_mo(product)
        buckets = self.Strategy._pf_product_mos(product)
        self.assertIn(mo, buckets['non_done'])
        self.assertIn(mo, buckets['draft'])
        self.assertFalse(buckets['done'])

    def test_wizard_serializes_chain_summary(self):
        """El payload serializado expone la cadena (contrato del widget)."""
        product = self._purchasable('SENAL PAYLOAD CADENA')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -2.0)
        wizard = self._wizard(product)
        serialized = json.loads(wizard.timeline_json)
        self.assertTrue(serialized['global']['chain_summary'])

    # ==================================================================
    # CA-3: la vista del producto trae leyenda + franja de cadena
    # ==================================================================
    def test_product_flow_view_has_legend_and_chain(self):
        """La leyenda de colores y el campo de cadena viven en la VISTA."""
        view = self.env.ref(
            'printflow_gestion_inventario.printflow_product_flow_view_form')
        arch = view.arch_db or ''
        self.assertIn('o_pf_timeline_legend', arch)
        self.assertIn('o_pf_legend_dot', arch)
        self.assertIn('name="chain_summary"', arch)
        self.assertIn('Cadena de fallas', arch)
