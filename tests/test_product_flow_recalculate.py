# -*- coding: utf-8 -*-
"""Botón "Recalcular" en el diagrama de flujo del PRODUCTO (paridad de UX).

Custodia el contrato de la tarea de la Sección 3 del CONTEXT.md. El diagrama del
producto (``printflow.product.flow``, vista ``printflow_product_flow_view_form``)
pinta el MISMO widget OWL (``printflow_order_timeline``) que sus pantallas
hermanas (el diagnóstico del PEDIDO y el escáner de PRODUCTO), pero le FALTABA el
botón "Recalcular" que sí tienen ellas. Sin él, tras validar/confirmar algo en
otra pestaña, el diagrama mostraba datos viejos (caché de los campos compute
``timeline_json``/``severity``/…) y había que cerrarlo y reabrirlo.

  * **CA-1** — la vista del diagrama trae el botón "Recalcular" que invoca
    ``action_recalculate``.
  * **CA-2** — ``action_recalculate()`` recarga el MISMO wizard
    (``res_model='printflow.product.flow'``, ``res_id=self.id``,
    ``view_mode='form'``, ``target='current'``) y, tras cambiar una FUENTE, el
    diagrama refleja datos FRESCOS (``timeline_json`` y ``severity`` cambian).
  * **CA-3** — SOLO LECTURA: ``TransactionCase`` (rollback), sin ``cr.execute`` /
    ``cr.commit``; el recómputo no altera ninguna existencia.
  * **CA-4** — paridad serializado↔fábrica: ``timeline_json`` ==
    ``json.dumps(_pf_build_payload(wizard, 'product'))`` tras el recálculo
    (candado ADITIVO, sin tocar los candados existentes).

Crea sus propios registros y ``TransactionCase`` hace rollback al terminar.
"""

import json
import os

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Archivos de PRODUCCIÓN de la tarea (solo lectura: sin SQL crudo ni commit).
_TOUCHED_FILES = (
    os.path.join('wizard', 'printflow_product_flow.py'),
    os.path.join('wizard', 'printflow_product_flow_views.xml'),
)


@tagged('post_install', '-at_install')
class TestProductFlowRecalculate(TransactionCase):
    """CA-1..CA-4 del botón "Recalcular" del diagrama del producto."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flow = cls.env['printflow.product.flow']
        cls.Canvas = cls.env['printflow.flow.canvas']
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Proveedor Recalcular', 'supplier_rank': 1})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id

    # ------------------------------------------------------------------
    # Utilidades (mismo patrón que el resto de tests del producto)
    # ------------------------------------------------------------------
    def _purchasable(self, name):
        """Producto COMPRABLE (sin ruta de fabricación) -> eje Compras."""
        product = self.env['product.product'].create({
            'name': name, 'type': 'product',
            'x_is_printflow_managed': True,
            'purchase_ok': True,
            'seller_ids': [(0, 0, {'partner_id': self.supplier.id})],
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _wizard(self, product):
        action = self.Flow.action_open_product_flow(product.id)
        self.assertEqual(action['res_model'], self.Flow._name)
        return self.Flow.browse(action['res_id'])

    # ==================================================================
    # CA-1 — La vista del diagrama trae el botón "Recalcular"
    # ==================================================================
    def test_ca1_view_has_recalculate_button(self):
        view = self.env.ref(
            'printflow_gestion_inventario.printflow_product_flow_view_form')
        arch = view.arch_db or ''
        self.assertIn('name="action_recalculate"', arch)
        self.assertIn('Recalcular', arch)

    # ==================================================================
    # CA-2 — Recarga el MISMO wizard y refresca el diagrama
    # ==================================================================
    def test_ca2_recalculate_reloads_same_record_with_fresh_data(self):
        product = self._purchasable('RECALCULAR CA2')
        # Fuente VIEJA: existencia negativa -> déficit -> Compras (raíz) -> Crítico.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        wizard = self._wizard(product)
        before_json = wizard.timeline_json
        before_severity = wizard.severity
        self.assertEqual(
            before_severity, 'danger',
            'Con déficit físico, el semáforo del producto debe ser Crítico.')

        # Cambia la FUENTE (existencia: -3.0 -> +3.0) SIN tocar ``product_id``:
        # los compute del wizard no lo saben hasta que el botón suelta la caché.
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, 6.0)

        action = wizard.action_recalculate()

        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.product.flow')
        self.assertEqual(action['res_id'], wizard.id)
        self.assertEqual(action['view_mode'], 'form')
        self.assertEqual(action['target'], 'current')

        self.assertNotEqual(
            wizard.timeline_json, before_json,
            'El diagrama debe recalcularse con los datos actuales.')
        self.assertNotEqual(
            wizard.severity, before_severity,
            'El semáforo debe refrescarse tras soltar la caché.')

    # ==================================================================
    # CA-3 — SOLO LECTURA
    # ==================================================================
    def test_ca3_is_read_only(self):
        product = self._purchasable('RECALCULAR CA3')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -2.0)
        qty_before = product.qty_available
        wizard = self._wizard(product)

        wizard.action_recalculate()

        self.assertEqual(
            product.qty_available, qty_before,
            'Recalcular solo suelta la caché: no altera existencias.')

    def test_ca3_touched_files_have_no_raw_sql(self):
        module_path = get_module_path('printflow_gestion_inventario')
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)

    # ==================================================================
    # CA-4 — Paridad serializado↔fábrica tras el recálculo
    # ==================================================================
    def test_ca4_serialized_matches_factory(self):
        product = self._purchasable('RECALCULAR CA4')
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, -3.0)
        wizard = self._wizard(product)

        wizard.action_recalculate()

        serialized = wizard.timeline_json
        self.assertEqual(
            serialized,
            json.dumps(self.Canvas._pf_build_payload(wizard, 'product')),
            'El JSON serializado debe ser EXACTAMENTE la fábrica del canvas.')
