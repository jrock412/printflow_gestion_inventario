# -*- coding: utf-8 -*-
"""Enganche y contrato de fuente del diagnóstico en el Tablero (PrintFlow).

El PRINCIPAL define ``action_open_diagnostic_wizard`` como envoltorio fino que
delega en el hook override-able ``_pf_diagnostic_action``. Aquí, en el addon de
diagnóstico, se:

  1. Sobreescribe ``_pf_diagnostic_action`` para abrir el Wizard real (Niveles 2/3).
  2. Aloja ``_pf_build_order_inputs``, el contrato de fuente que **consume** el
     adaptador ``printflow.order.diagnostic.source``. Vivía en el board del
     PRINCIPAL y referenciaba al wizard del diagnóstico; se movió aquí para que
     el principal quede con CERO referencias al modelo del diagnóstico.

Con esto, al extraer ``diagnostic/`` a su propio addon, el tablero simplemente
vuelve al stub (notificación amable) si el diagnóstico no está instalado.
"""

from odoo import _, models


class PrintflowOrderBoardDiagnostic(models.Model):
    """Extiende el Tablero: hook del diagnóstico + contrato de fuente."""

    _inherit = 'printflow.order.board'

    # ══════════════════════════════════════════════════════════════════════
    # ENLACE CON EL DIAGNÓSTICO (hook override-able)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_diagnostic_action(self):
        """Abre el Wizard de Diagnóstico y Ruta de Solución del pedido.

        Es una capa de LECTURA + guía: no toca el inventario por sí sola. Las
        rutas que ofrece reutilizan los asistentes ya existentes (compra rápida,
        producción, recepción y ``_fix_over_reservation``).
        """
        self.ensure_one()
        wizard = self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': self.id}
        )
        # Auto-foco de arranque: si el pedido tiene UN SOLO producto terminado
        # con demanda pendiente, el wizard nace enfocado directo al diagrama
        # (se salta la lista intermedia). Con 0 o >=2 productos no toca nada y
        # el formulario decide su nivel por ``focus_line_id`` (ver la vista).
        # Vive AQUÍ y no en ``create()`` para no alterar el snapshot ni los
        # tests que construyen el wizard directamente y validan "payload sin
        # foco".
        wizard._pf_auto_focus_single_product()
        return {
            'name': _('Diagnostico y Ruta de Solucion'),
            'type': 'ir.actions.act_window',
            'res_model': 'printflow.order.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ══════════════════════════════════════════════════════════════════════
    # CONTRATO DE FUENTE DEL DIAGNÓSTICO (lo consume
    # ``printflow.order.diagnostic.source._pf_get_order_inputs``)
    #
    # Normaliza datos ya calculados por el tablero/wizard para que el núcleo del
    # diagnóstico no dependa de este modelo. NO define reglas nuevas: solo reúne
    # lo que ya existe. Sin campos almacenados ni migración.
    # ══════════════════════════════════════════════════════════════════════
    def _pf_build_order_inputs(self):
        """Paquete normalizado del pedido para el diagnóstico.

        Reutiliza los helpers existentes del tablero (snapshot de stock, PO por
        origen) y la demanda normalizada del wizard (terminados + insumos +
        estimados) para no duplicar el cálculo. Devuelve el contrato descrito en
        ``printflow_order_diagnostic_source``: ``order``, ``flags``, ``lines``,
        ``stock``, ``production``, ``purchase``, ``design`` y ``documents``.

        El adaptador solo lo invoca si el modelo fuente está soportado; el
        motor y el propio adaptador NO conocen el tablero.
        """
        self.ensure_one()
        so = self.sale_order_id
        stock_model = self.env['stock.picking']
        purchase_model = self.env['purchase.order']
        production_model = self.env['mrp.production']
        if not so:
            return {
                'order': False,
                'flags': {},
                'lines': [],
                'stock': {},
                'production': {},
                'purchase': {'incoming': {}, 'pending_product_ids': set(),
                             'has_purchase': False},
                'design': {'pending_product_ids': set()},
                'documents': {'sale': False, 'pickings': stock_model,
                              'purchase_orders': purchase_model,
                              'manufactures': production_model},
            }

        # Demanda normalizada y PO del pedido (una sola lectura cada una).
        Diagnostic = self.env['printflow.order.diagnostic.wizard']
        demand = Diagnostic._get_demand_map(self, so)
        products = list(demand.keys())
        purchase_orders = self._find_purchase_orders_by_sale_names([so.name])
        incoming = Diagnostic._get_incoming_map(products, purchase_orders)
        stock = self._get_order_stock_snapshot(products, incoming=incoming)

        # Productos fabricables (BoM o ruta de fabricación aplicable), resueltos
        # en lote por el motor: es la MISMA fuente de verdad que usa el wizard.
        product_recs = self.env['product.product'].browse(
            [p.id for p in products])
        manufacturable = self.env[
            'printflow.order.health.engine'
        ]._pf_manufacturable_products(product_recs)

        lines = [
            {
                'product': product,
                'qty': data['qty'],
                'uom': data['uom'],
                'kind': data['kind'],
                'parent': data.get('parent'),
                'is_manufacturable': product.id in manufacturable,
            }
            for product, data in demand.items()
        ]

        # MO activas/hechas por producto (fuente de la regla de fabricación).
        production = {}
        for mo in self.mrp_production_ids.filtered(lambda m: m.state != 'cancel'):
            if not mo.product_id:
                continue
            entry = production.setdefault(
                mo.product_id.id, {'active': [], 'done': []})
            (entry['done'] if mo.state == 'done' else entry['active']).append(mo)

        # Artes pendientes por producto (misma señal que el diagnóstico).
        design_pending = set()
        for sheet in so.mrp_technical_sheet_ids:
            if (getattr(sheet, 'has_design_service', False)
                    and getattr(sheet, 'design_status', False) == 'pending'
                    and sheet.sale_line_id.product_id):
                design_pending.add(sheet.sale_line_id.product_id.id)

        flags = self._pf_order_health_inputs()
        flags.update({
            'health_supply': self.health_supply,
            'health_stock': self.health_stock,
            'health_production': self.health_production,
            'health_delivered_open': self.health_delivered_open,
            'health_severity': self.health_severity,
        })

        return {
            'order': so,
            'flags': flags,
            'lines': lines,
            'stock': stock,
            'production': production,
            'purchase': {
                'incoming': incoming,
                'pending_product_ids': set(self.pending_purchase_product_ids.ids),
                'has_purchase': self.has_purchase,
            },
            'design': {'pending_product_ids': design_pending},
            'documents': {
                'sale': so,
                'pickings': self._get_delivery_pickings(),
                'purchase_orders': purchase_orders,
                'manufactures': self.mrp_production_ids,
            },
        }
