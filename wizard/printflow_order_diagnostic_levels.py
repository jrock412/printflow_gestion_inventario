# -*- coding: utf-8 -*-
"""Diagnóstico de pedido como CENTRO DE OPERACIONES (PrintFlow).

El diagrama de línea de tiempo muestra el FLUJO FÍSICO COMPLETO del producto y
permite RESOLVER el error desde el propio nodo (popover de acciones directas):

  * Producto COMPRADO:
      Compras -> Recepción -> Inventario -> Entrega -> Cliente
  * Producto FABRICADO:
      Compras (componentes) -> Recepción -> Almacén insumos -> Fabricación ->
      Almacén terminado -> Entrega -> Cliente

El TIPO lo DETECTA EL MOTOR (``is_manufacturable``: BoM o ruta de fabricación);
el usuario no configura nada.

Decisiones de arquitectura:

  * ``receipt`` pertenece al nodo CAUSAL ``purchase``; ``stock_supply`` y
    ``stock_finished`` pertenecen al nodo CAUSAL ``stock``. Son hitos de
    PRESENTACIÓN: el motor de cadena (``PF_CHAIN_ORDER``) NO se toca.
  * El estado de ``stock_supply`` / ``stock_finished`` sale del roll-up por
    miembro (``_pf_flow_stock_split`` del motor), no de un estado nuevo.
  * El ESQUELETO se muestra SIEMPRE COMPLETO: los hitos que no aplican quedan
    visibles en gris "N/A".
  * El Nivel 3 (detalle del área) se ELIMINÓ: su contenido se fusionó como
    ``panel`` dentro del popover del nodo.
  * ``focus_node`` y sus campos derivados se retiraron; el estado de navegación
    queda en ``focus_line_id``.

Fase 5 (rediseño del Centro de Salud): el ARMADO del payload se EXTRAJO al
servicio compartido ``printflow.flow.canvas`` (en ``diagnostic/models/``), que
también alimenta el diagrama de un PRODUCTO sin venta. Este wizard conserva
MÉTODOS DELEGADORES con la MISMA firma (los tests de diagnóstico invocan métodos
privados directamente); así la paridad del pedido se mantiene EXACTA.

Es de SOLO LECTURA: navega y reutiliza los remedios/wizards existentes con los
permisos del usuario (nunca con ``sudo`` para escribir).
"""

import json

from odoo import _, api, fields, models

from odoo.addons.printflow_gestion_inventario.wizard.printflow_order_diagnostic_wizard import (  # noqa: E501
    _EPS,
)
from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_LABELS,
)


class PrintflowOrderDiagnosticWizard(models.TransientModel):
    """Navegación del diagnóstico de pedido (canvas + popover resolutivo)."""

    _inherit = 'printflow.order.diagnostic.wizard'

    # ── Foco ────────────────────────────────────────────────────────────
    # El Nivel 3 se eliminó: solo hay ``focus_line_id`` (producto enfocado).
    focus_line_id = fields.Many2one(
        'printflow.order.diagnostic.wizard.line',
        string='Línea enfocada',
        help='Producto terminado que se está diagnosticando.',
    )

    # ── Nivel 1: SOLO productos terminados (sin componentes) ────────────
    product_line_ids = fields.One2many(
        'printflow.order.diagnostic.wizard.line', 'wizard_id',
        string='Productos del pedido',
        domain=[('line_kind', '=', 'finished')],
    )

    # ── Campos del producto enfocado (related, NO almacenados) ──────────
    # Apuntan a los ``flow_*`` (roll-up del subárbol), no a los estados crudos.
    focus_product_id = fields.Many2one(
        'product.product', related='focus_line_id.product_id', string='Producto')
    focus_line_kind = fields.Selection(
        related='focus_line_id.line_kind', string='Tipo')
    focus_severity = fields.Selection(
        related='focus_line_id.flow_severity', string='Semáforo')
    focus_sale_status = fields.Selection(
        related='focus_line_id.flow_sale_status', string='Venta')
    focus_stock_status = fields.Selection(
        related='focus_line_id.flow_stock_status', string='Inventario')
    focus_purchase_status = fields.Selection(
        related='focus_line_id.flow_purchase_status', string='Compras')
    focus_production_status = fields.Selection(
        related='focus_line_id.flow_production_status', string='Fabricación')
    focus_supply_status = fields.Selection(
        related='focus_line_id.flow_supply_status',
        string='Almacén insumos (flujo)')
    focus_delivery_status = fields.Selection(
        related='focus_line_id.flow_delivery_status', string='Entrega')
    focus_pending_delivery_order_count = fields.Integer(
        related='focus_line_id.pending_delivery_order_count',
        string='Órdenes de entrega pendientes')
    focus_root_cause_node = fields.Selection(
        related='focus_line_id.root_cause_node', string='Nodo de quiebre')
    focus_failed_node_count = fields.Integer(
        related='focus_line_id.flow_failed_node_count', string='Nodos rotos')
    focus_failure_summary = fields.Char(
        related='focus_line_id.flow_failure_summary', string='Qué pasa')
    focus_deficit_qty = fields.Float(
        related='focus_line_id.deficit_qty', string='Falta física')
    focus_contention_qty = fields.Float(
        related='focus_line_id.contention_qty', string='Contención')
    focus_incoming_qty = fields.Float(
        related='focus_line_id.incoming_qty', string='En camino')
    focus_flow_failure_ids = fields.One2many(
        related='focus_line_id.flow_failure_ids',
        string='Fallas del flujo')

    # ── Contadores por nodo causal (alimentan los badges del canvas) ────
    node_sale_issue_count = fields.Integer(
        compute='_compute_focus_node', string='Problemas de venta')
    node_stock_issue_count = fields.Integer(
        compute='_compute_focus_node', string='Problemas de inventario')
    node_purchase_issue_count = fields.Integer(
        compute='_compute_focus_node', string='Problemas de compras')
    node_production_issue_count = fields.Integer(
        compute='_compute_focus_node', string='Problemas de fabricación')
    node_delivery_issue_count = fields.Integer(
        compute='_compute_focus_node', string='Problemas de entrega')
    is_timeline = fields.Boolean(
        compute='_compute_nav_flags', string='En línea de tiempo')

    # ── Selector de producto (Nivel 1) ──────────────────────────────────
    finished_product_count = fields.Integer(
        compute='_compute_product_selector_flags',
        string='Productos con demanda pendiente',
        help='Número de productos terminados con demanda pendiente '
             '(requerido > 0). No incluye los ya entregados.')
    can_switch_product = fields.Boolean(
        compute='_compute_product_selector_flags',
        string='Puede cambiar de producto',
        help='True cuando hay más de un producto con demanda pendiente.')
    show_product_selector = fields.Boolean(
        compute='_compute_product_selector_flags',
        string='Mostrar selector de producto',
        help='True sin foco y con más de un producto con demanda pendiente: '
             'es cuando la vista muestra el selector del Nivel 1.')

    # ── DIAGRAMA DE LÍNEA DE TIEMPO (payload para el widget OWL) ────────
    focus_timeline_json = fields.Text(
        compute='_compute_timeline_json', string='Línea de tiempo (JSON)')

    # ── Cadena de fallas del producto enfocado (FEATURE A) ──────────────
    focus_chain_summary = fields.Char(
        compute='_compute_focus_node', string='Cadena de fallas',
        help='Cadena raíz -> consecuencias del producto enfocado, p. ej. '
             '"Compras (origen) → Inventario (consecuencia)".')
    focus_chain_root_label = fields.Char(
        compute='_compute_focus_node', string='Origen de la cadena')
    node_sale_is_consequence = fields.Boolean(
        compute='_compute_focus_node', string='Venta es consecuencia')
    node_stock_is_consequence = fields.Boolean(
        compute='_compute_focus_node', string='Inventario es consecuencia')
    node_purchase_is_consequence = fields.Boolean(
        compute='_compute_focus_node', string='Compras es consecuencia')
    node_production_is_consequence = fields.Boolean(
        compute='_compute_focus_node', string='Fabricación es consecuencia')
    node_delivery_is_consequence = fields.Boolean(
        compute='_compute_focus_node', string='Entrega es consecuencia')

    # ── Falla acumulada / backlog (FEATURE B) ───────────────────────────
    pf_has_backlog = fields.Boolean(
        compute='_compute_focus_node', string='Tiene falla acumulada',
        help='Algún producto del pedido tiene una falla sistémica de '
             'inventario (backlog): se puede gestionar en la bandeja Salud de '
             'inventario.')

    @api.depends('focus_line_id')
    def _compute_focus_node(self):
        """Cuenta las fallas por nodo causal y arma la cadena del producto."""
        Failure = self.env['printflow.order.diagnostic.failure']
        for rec in self:
            failures = (
                rec.focus_line_id.flow_failure_ids
                if rec.focus_line_id else Failure
            )
            counts = {
                'sale': 0, 'stock': 0, 'purchase': 0, 'production': 0,
                'delivery': 0,
            }
            for failure in failures:
                if failure.node in counts:
                    counts[failure.node] += 1
            rec.node_sale_issue_count = counts['sale']
            rec.node_stock_issue_count = counts['stock']
            rec.node_purchase_issue_count = counts['purchase']
            rec.node_production_issue_count = counts['production']
            rec.node_delivery_issue_count = counts['delivery']
            # ── Cadena de fallas (raíz -> consecuencias) ────────────────
            consequence_nodes = set(failures.filtered(
                lambda f: f.pf_chain_is_consequence).mapped('node'))
            rec.node_sale_is_consequence = 'sale' in consequence_nodes
            rec.node_stock_is_consequence = 'stock' in consequence_nodes
            rec.node_purchase_is_consequence = 'purchase' in consequence_nodes
            rec.node_production_is_consequence = 'production' in consequence_nodes
            rec.node_delivery_is_consequence = 'delivery' in consequence_nodes
            rec.focus_chain_summary = self._pf_chain_summary(failures)
            rec.focus_chain_root_label = (
                PF_CHAIN_LABELS.get(rec.focus_root_cause_node, '')
                if rec.focus_root_cause_node else '')
            # Backlog de TODO el pedido: gatea el aviso de cabecera y su botón.
            rec.pf_has_backlog = any(
                rec.deficit_line_ids.failure_ids.mapped('pf_is_backlog'))

    @api.depends('focus_line_id')
    def _compute_nav_flags(self):
        """Bandera de la interfaz: hay producto enfocado (línea de tiempo)."""
        for rec in self:
            rec.is_timeline = bool(rec.focus_line_id)

    @api.depends('focus_line_id', 'product_line_ids.required_qty',
                 'product_line_ids.line_kind')
    def _compute_product_selector_flags(self):
        """Cuenta terminados con demanda pendiente y deriva el selector."""
        for rec in self:
            pending = rec.product_line_ids.filtered(
                lambda line: (line.required_qty or 0.0) > _EPS)
            rec.finished_product_count = len(pending)
            rec.can_switch_product = rec.finished_product_count > 1
            rec.show_product_selector = (
                not rec.focus_line_id) and rec.finished_product_count > 1

    @api.depends('focus_line_id')
    def _compute_timeline_json(self):
        """Serializa el canvas del producto enfocado para el widget OWL.

        Campo TRANSITORIO de solo presentación: no persiste y no altera ningún
        contrato. Delega el armado del payload en ``_pf_timeline_payload``.
        """
        for rec in self:
            rec.focus_timeline_json = json.dumps(rec._pf_timeline_payload())

    # ══════════════════════════════════════════════════════════════════════
    # PAYLOAD DEL CANVAS (delega en ``printflow.flow.canvas``)
    #
    # La FÁBRICA del payload vive en
    # ``diagnostic/models/printflow_flow_canvas.py`` (fuente ÚNICA compartida
    # por el pedido y el producto). Aquí se conservan wrappers DELEGADORES con
    # la MISMA firma porque los tests de diagnóstico invocan estos métodos
    # privados directamente (paridad exacta).
    # ══════════════════════════════════════════════════════════════════════
    def _pf_canvas(self):
        """Servicio compartido del canvas (fuente única del payload)."""
        return self.env['printflow.flow.canvas']

    def _pf_timeline_payload(self):
        """Payload del canvas del PEDIDO (delega en el servicio compartido)."""
        self.ensure_one()
        return self._pf_canvas()._pf_build_payload(self, 'order')

    def _pf_node_summary(self, owner_failure, issues):
        """Wrapper delegador: resumen corto del problema en la tarjeta."""
        return self._pf_canvas()._pf_node_summary(owner_failure, issues)

    def _pf_node_status_label(self, key, status):
        """Wrapper delegador: etiqueta de estado ESPECÍFICA del hito."""
        return self._pf_canvas()._pf_node_status_label(key, status)

    def _pf_failure_slot(self, failure):
        """Wrapper delegador: slot de canvas de una falla (component->supply)."""
        return self._pf_canvas()._pf_failure_slot(failure)

    def _pf_key_by_slot(self, axis):
        """Wrapper delegador: hito PRINCIPAL del eje por slot."""
        return self._pf_canvas()._pf_key_by_slot(axis)

    def _pf_node_actions(self, node_key, owner, node_role, node_status,
                         is_root=False, context_failure=None, anomaly=False,
                         pending=0):
        """Wrapper delegador: acciones DIRECTAS del popover de un hito."""
        return self._pf_canvas()._pf_node_actions(
            self, node_key, owner, node_role, node_status, is_root,
            context_failure, anomaly, pending)

    def _pf_anomaly_node_keys(self, line):
        """Wrapper delegador: hitos que detectan reservas colgadas."""
        return self._pf_canvas()._pf_anomaly_node_keys(self, line)

    def _pf_chain_summary(self, failures):
        """Wrapper delegador: resumen de la cadena raíz -> consecuencias."""
        return self._pf_canvas()._pf_chain_summary(failures)

    # ══════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN (sin recrear el wizard)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_reload_action(self):
        """Acción que recarga ESTE wizard para reflejar el cambio de foco."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico y Ruta de Solución'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _pf_auto_focus_single_product(self):
        """Auto-foco de arranque: enfoca si hay UN SOLO producto con demanda.

        Cuenta los terminados con demanda PENDIENTE (``required_qty > 0``); las
        filas de producto ya entregado (demanda 0) NO cuentan. Con EXACTAMENTE
        uno, escribe ``focus_line_id`` y devuelve ``True`` (el formulario salta
        directo al diagrama); con 0 o >=2 no toca nada y devuelve ``False`` (el
        formulario muestra el selector del Nivel 1).

        Se invoca desde el tablero (``_pf_diagnostic_action``) y NUNCA desde
        ``create()``: así no altera el snapshot ni los tests que construyen el
        wizard directamente y validan "payload sin foco".
        """
        self.ensure_one()
        pending = self.product_line_ids.filtered(
            lambda line: (line.required_qty or 0.0) > _EPS)
        if len(pending) != 1:
            return False
        self.write({'focus_line_id': pending.id})
        return True

    def action_back_to_products(self):
        """Vuelve al Nivel 1 (productos) y limpia el foco."""
        self.ensure_one()
        self.write({'focus_line_id': False})
        return self._pf_reload_action()

    def action_open_pending_delivery_orders(self):
        """Abre los albaranes de entrega pendientes del producto enfocado.

        AVISO informativo: reutiliza el dominio de "pendientes" (movimientos,
        sin exigir reserva) y EXCLUYE los albaranes del propio pedido. Solo
        navega; no ejecuta cambios ni genera fallas.
        """
        self.ensure_one()
        product = self.focus_product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        pickings = self._pf_pending_delivery_pickings(
            self.board_id, [product.id])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Órdenes de entrega pendientes de %s (%d)') % (
                product.display_name, len(pickings)),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def action_open_inventory_health(self):
        """Abre Salud de inventario con TODOS los productos backlog del pedido.

        Solo navega; la bandeja se puebla bajo demanda y se filtra a los
        productos con falla acumulada. Es la ruta de cabecera de la FEATURE B.
        """
        self.ensure_one()
        failures = self.deficit_line_ids.failure_ids.filtered(
            lambda f: f.pf_is_backlog)
        products = failures.mapped('line_id.product_id')
        return self.env['printflow.inventory.health']._pf_open_health(
            products=products,
            title=_('Salud de inventario (pedido %s)') % (self.name or ''))

    def action_open_node_pending(self, node_key=None):
        """Abre el LISTADO/bandeja de PENDIENTES de un nodo (Fase 3).

        Dispatcher PÚBLICO que invoca el badge de pendientes del canvas (vía
        ``/web/dataset/call_button``). Delega en el motor de Fase 2
        (``printflow.flow.pending``): los nodos de STOCK abren la bandeja de
        Salud de Inventario; el resto, listas nativas (compras, recepciones,
        órdenes de fabricación, entregas, ventas). Solo navega; no escribe.
        """
        self.ensure_one()
        product = self.focus_product_id
        if not node_key or not product:
            return {'type': 'ir.actions.act_window_close'}
        return self.env['printflow.flow.pending']._pf_node_pending_action(
            node_key, product, board=self.board_id)

    def action_scan_product(self):
        """Abre el escáner de producto para la línea enfocada (línea de tiempo).

        Reutiliza el puente existente ``_pf_open_product_scanner`` del wizard
        base: abre a pantalla completa y declara el origen (el tablero) para
        poder volver.
        """
        self.ensure_one()
        product = self.focus_product_id
        if not product:
            return {'type': 'ir.actions.act_window.close'}
        return self._pf_open_product_scanner(product, self.board_id)
