# -*- coding: utf-8 -*-
"""Diagrama de flujo de UN PRODUCTO sin venta (PrintFlow · Fase 5).

``TransientModel`` de SOLO LECTURA que pinta el MISMO canvas del diagnóstico de
pedido (widget OWL ``printflow_order_timeline``) para un producto sin venta: el
recorrido físico (Compras -> Recepción -> Inventario/Fabricación -> Entrega ->
Cliente) con semáforos por hito, pendientes por nodo y acciones de NAVEGACIÓN.

Diseño:
  * El payload lo arma el servicio compartido ``printflow.flow.canvas`` en
    ``mode='product'`` (fuente única con el pedido).
  * Los estados NO se reinventan: se reutiliza
    ``printflow.product.flow.diagnostic._pf_flow_verdict`` (la misma función del
    escáner de producto y del chequeo de flujo).
  * Es de solo lectura: navega (producto, listados/bandeja por hito); no escribe.
  * Cada wizard es un registro propio del usuario que lo abre (no hay tablero
    compartido), así que dos usuarios no se pisan.
"""

import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

# Dispatcher del popover del producto: la CLAVE de la acción (única que conoce
# el widget) se traduce, con lista blanca, al método ``_pf_*``/público del
# wizard. Odoo 17 rechaza invocar métodos privados por RPC (``call_button``), así
# que el popover llama a ``action_run_pf_node`` y el servidor resuelve aquí.
_PF_NODE_METHODS = {
    'product': 'action_open_product',
    'quants': '_pf_open_quants',
    'adjust': '_pf_open_quants_adjust',
    'fabricate': '_pf_open_create_production',
    'buy_product': '_pf_open_buy_product',
    'buy_components': '_pf_open_buy_components',
    'bom_list': '_pf_open_bom_list',
    'fix_reservation': '_pf_run_fix_over_reservation',
    'cleanup_reservations': '_pf_run_fix_over_reservation',
    'blocking': '_pf_open_blocking_reservations',
    'purchase_orders': '_pf_open_purchase_orders',
    'view_purchase': '_pf_open_purchase_orders',
    'receipt': '_pf_open_receipts',
    'mo': '_pf_open_mo',
    'delivery_orders': '_pf_open_delivery_orders',
    'inventory_health': '_pf_open_inventory_health',
    'collect': 'action_open_collect_causante',
    # Bandeja gestionable de INSUMOS: la abre el botón "Solucionar los insumos"
    # del hito ALMACÉN DE INSUMOS (y el mapeo del plan target 'supply_tray').
    'fix_supply': '_pf_open_supply_tray',
}

# Nodo de quiebre del motor de flujo (misma selección del wizard de pedido).
ROOT_CAUSE_SELECTION = [
    ('sale', 'Venta / POS'),
    ('stock', 'Inventario'),
    ('supply', 'Almacén insumos'),
    ('purchase', 'Compras'),
    ('production', 'Fabricación'),
    ('delivery', 'Entrega'),
]

# Lista blanca EXPLÍCITA de tipos (``kind``) que admite el REPARTO multi-lote
# (H-037). Espeja el alcance de la bandeja "Asignar lote en bloque": SOLO los
# destinos que esa bandeja produce como resolubles (``missing_move`` = entrega por
# movimiento; ``pending_order`` = entrega por albarán sin lote). Se declara como
# tupla fija y se consulta con ``in`` (NUNCA ``getattr`` por convención): si un
# ``kind`` no está aquí, el reparto devuelve ``0.0`` y no escribe nada.
_SPLIT_KINDS = ('missing_move', 'pending_order')


class PrintflowProductFlow(models.TransientModel):
    """Diagrama de flujo de un producto sin venta (solo lectura)."""

    _name = 'printflow.product.flow'
    _description = 'Diagrama de flujo del producto (PrintFlow)'

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, readonly=True,
        ondelete='cascade')
    name = fields.Char(
        string='Título', compute='_compute_header_fields', readonly=True)
    flow_type = fields.Selection(
        [('purchase', 'Compra'), ('manufacture', 'Fabricación')],
        string='Tipo de flujo', compute='_compute_header_fields', readonly=True)
    severity = fields.Selection(
        [('ok', 'Sano'), ('warning', 'Atención'), ('danger', 'Crítico')],
        string='Semáforo', compute='_compute_header_fields', readonly=True)
    root_cause_node = fields.Selection(
        ROOT_CAUSE_SELECTION, string='Nodo de quiebre',
        compute='_compute_header_fields', readonly=True)
    chain_summary = fields.Char(
        string='Cadena de fallas', compute='_compute_header_fields',
        readonly=True)
    timeline_json = fields.Text(
        string='Diagrama (JSON)', compute='_compute_timeline_json')

    # ══════════════════════════════════════════════════════════════════════
    # ENTRADA (drill-down)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def action_open_product_flow(self, product_id):
        """Crea el wizard del producto y devuelve la ventana a pantalla completa."""
        product = (
            self.env['product.product'].browse(product_id).exists()
            if product_id else self.env['product.product'])
        if not product:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('PrintFlow'),
                    'message': _('No hay un producto válido para diagnosticar.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        wizard = self.create({'product_id': product.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Flujo de %s') % product.display_name,
            'res_model': self._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTOS
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('product_id')
    def _compute_header_fields(self):
        """Cabecera del diagrama (título, tipo de flujo, semáforo, raíz)."""
        for rec in self:
            ctx = rec._pf_product_canvas_ctx()
            rec.flow_type = ctx.get('flow_type') or 'purchase'
            rec.severity = ctx.get('severity') or 'ok'
            rec.root_cause_node = ctx.get('root_cause_node') or False
            rec.chain_summary = ctx.get('chain_summary') or ''
            rec.name = _('Flujo de %s') % (
                rec.product_id.display_name or '')

    @api.depends('product_id')
    def _compute_timeline_json(self):
        """Serializa el canvas del producto (mismo widget del pedido)."""
        for rec in self:
            rec.timeline_json = json.dumps(
                rec.env['printflow.flow.canvas']._pf_build_payload(
                    rec, 'product'))

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES (recómputo solo lectura)
    # ══════════════════════════════════════════════════════════════════════
    def action_recalculate(self):
        """Recalcula el diagrama sobre el MISMO wizard (sin recrearlo).

        Cuando el operador valida/confirma algo en otra pestaña (una OC, una
        recepción, una reserva), el diagrama sigue mostrando datos VIEJOS: los
        compute (``timeline_json``, ``severity``, ``root_cause_node``,
        ``chain_summary``) dependen SOLO de ``product_id`` —que no cambia—, así
        que el ORM conserva su caché. Este botón la suelta y recarga el mismo
        registro a pantalla completa. Solo LECTURA: ``invalidate_*`` es caché en
        memoria, nunca escritura.
        """
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        # 1) Fuentes del producto (cantidades computadas): suelta la caché del
        #    ORM para releer movimientos/quants actuales (SIN escribir en BD).
        self.env['product.product'].invalidate_model([
            'qty_available', 'outgoing_qty', 'incoming_qty',
            'free_qty', 'virtual_available'])
        # 2) Compute del wizard (dependen de product_id, que NO cambia).
        self.invalidate_recordset()
        # 3) Recarga el MISMO registro a pantalla completa.
        return {
            'type': 'ir.actions.act_window',
            'name': self.name or _('Flujo del producto'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ══════════════════════════════════════════════════════════════════════
    # CONTEXTO DEL CANVAS (adaptador del host para el servicio compartido)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_product_canvas_ctx(self):
        """Contexto del producto (delega en la estrategia del caso sin venta).

        El armado vive en ``printflow.flow.strategy.product`` (Fase 3 del
        refactor OOP): este método se conserva como DELEGADOR con la MISMA firma
        porque hay consumidores (tests, ``_compute_header_fields`` y
        ``action_run_pf_plan``) que lo invocan directamente.
        """
        self.ensure_one()
        return self.env[
            'printflow.flow.strategy.product']._pf_flow_context(self)

    def _pf_product_members(self, product, manufacturable, verdict):
        """Delegador: miembros planos del producto (estrategia del producto)."""
        return self.env[
            'printflow.flow.strategy.product']._pf_product_members(
                product, manufacturable, verdict)

    @api.model
    def _pf_bom_components(self, product):
        """Delegador: componentes de la BOM aplicable (estrategia del producto)."""
        return self.env[
            'printflow.flow.strategy.product']._pf_bom_components(product)

    # ══════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN (solo lectura)
    # ══════════════════════════════════════════════════════════════════════
    def action_open_product(self):
        """Abre la ficha del producto en pantalla completa."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.product_id.display_name,
            'res_model': 'product.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_node_pending(self, node_key=None):
        """Abre el listado/bandeja de pendientes de un hito (motor Fase 2).

        Los nodos de STOCK delegan en la bandeja de Salud de Inventario; el
        resto, en listas nativas. Solo navega; no escribe.
        """
        self.ensure_one()
        if not node_key or not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        return self.env['printflow.flow.pending']._pf_node_pending_action(
            node_key, self.product_id)

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES DEL POPOVER (público + dispatcher con lista blanca)
    # ══════════════════════════════════════════════════════════════════════
    def action_run_pf_node(self, node_action):
        """Dispatcher PÚBLICO de las acciones del popover del producto.

        Odoo 17 prohíbe invocar métodos privados vía ``call_button``. El widget
        conoce solo la CLAVE de la acción; este método la traduce, con la lista
        blanca ``_PF_NODE_METHODS``, al método correspondiente. Así ningún método
        privado viaja por RPC y el frontend no sabe nada del backend.
        """
        self.ensure_one()
        method_name = _PF_NODE_METHODS.get(node_action)
        if not method_name:
            return {'type': 'ir.actions.act_window_close'}
        return getattr(self, method_name)()

    def action_run_pf_plan(self, cause=None, which='solution', product_id=None):
        """Dispatcher PÚBLICO de las filas del PANEL (problema/solución).

        Reutiliza el playbook para recomputar el plan de la causa y ejecuta la
        acción elegida con el vocabulario de ``_pf_run_action``. El cliente solo
        envía la causa y cuál de las dos acciones, nunca el destino.

        Novedad (bandeja gestionable de lote): cuando la causa es un estado de
        LOTE (``_pf_is_lot_cause``) y se pide la SOLUCIÓN, NO se ejecuta el
        remedio directo: se ABRE la bandeja ``printflow.flow.lot.tray`` para que
        el operador vea lo afectado y decida. El resto conserva su comportamiento.
        El tercer argumento ``product_id`` (ADITIVO) identifica el producto del
        lote cuando la fila pertenece a un COMPONENTE distinto del foco.
        """
        self.ensure_one()
        if which not in ('problem', 'solution'):
            return {'type': 'ir.actions.act_window_close'}
        if which == 'solution' and self.env[
                'printflow.flow.lots']._pf_is_lot_cause(cause):
            # Fase 1 del patrón de fallas guiadas: la falla HUÉRFANA abre la
            # bandeja GENÉRICA (poblada por ``printflow.flow.failure.lot.orphan``)
            # cuando la fila trae el producto explícito (la fila del panel del
            # diagrama) o cuando la configuración la fuerza. El resto de causas
            # conserva INTACTO su flujo (bandeja de lote clásica, fallback).
            if self._pf_use_guided_failure_tray(cause, product_id):
                return self._pf_open_failure_tray(cause, product_id)
            return self._pf_open_lot_tray(cause, product_id)
        if which == 'solution' and self.env[
                'printflow.flow.supply']._pf_is_supply_cause(cause):
            return self._pf_open_supply_tray()
        if (which == 'solution'
                and cause in self.env[
                    'printflow.flow.failure.registry']._pf_supported()):
            # Causa con FALLA GUIADA registrada (p. ej. ``data_anomaly`` =
            # reserva colgada): el "Solucionar" abre la bandeja de DECISIÓN en
            # vez del one-click. Espejo del patrón de lote/insumos.
            return self._pf_open_failure_tray(cause, product_id)
        plan = self._pf_product_plan_for_cause(cause)
        action = ((plan or {}).get('actions') or {}).get(which) or {}
        return self._pf_run_action(action.get('kind'), action.get('target'))

    def _pf_open_lot_tray(self, lot_state, product_id=None):
        """Abre la bandeja gestionable del estado de lote (puebla bajo demanda).

        La bandeja se puebla desde el motor principal (``_pf_lot_state``) con una
        fila por ítem afectado; el operador ve qué está mal y aplica la
        corrección sobre la selección. Solo lista y navega al abrir: la
        escritura vive en ``action_apply_correction`` (con su guardia de permisos).
        """
        self.ensure_one()
        product = (
            self.env['product.product'].browse(product_id).exists()
            if product_id else self.product_id)
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        tray = self.env[
            'printflow.flow.lot.tray']._pf_populate(product, lot_state)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bandeja de lote: %s') % product.display_name,
            'res_model': 'printflow.flow.lot.tray',
            'view_mode': 'tree',
            'domain': [('id', 'in', tray.ids)],
            'target': 'current',
        }

    def _pf_use_guided_failure_tray(self, cause, product_id=None):
        """¿Abrir la bandeja GENÉRICA de fallas para esta causa? (Fase 1).

        Solo aplica a causas con falla REGISTRADA en
        ``printflow.flow.failure.registry``. Se usa cuando la fila trae el
        producto EXPLÍCITO (la fila del panel del diagrama, con su 3er argumento)
        o cuando la configuración fuerza la superficie guiada
        (``pf_failure_guided_tray``). Las llamadas sin contexto (flujo clásico,
        2 argumentos) conservan la bandeja de lote: así NO se rompe ningún
        consumidor previo.

        Devuelve ``False`` para las causas que NO tienen falla registrada (así el
        orquestador ni siquiera consulta la superficie guiada).
        """
        self.ensure_one()
        Registry = self.env['printflow.flow.failure.registry']
        if cause not in Registry._pf_supported():
            return False
        return bool(product_id) or Registry._pf_guided_tray_forced()

    def _pf_open_failure_tray(self, code, product_id=None):
        """Abre la bandeja GENÉRICA de la falla ``code`` (puebla bajo demanda).

        La bandeja la pinta el modelo que declara la propia falla
        (``_pf_fault_tray_model``) y se puebla con ``_pf_populate``: la superficie
        no conoce ninguna falla en particular. Si la falla NO está presente (su
        detección devuelve algo falsy), cae a la bandeja de lote clásica para no
        dejar al operador sin salida.
        """
        self.ensure_one()
        product = (
            self.env['product.product'].browse(product_id).exists()
            if product_id else self.product_id)
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Registry = self.env['printflow.flow.failure.registry']
        failure = Registry._pf_failure_for(code)
        tray_model = failure._pf_fault_tray_model()
        tray = self.env[tray_model]._pf_populate(self, code, product)
        if not tray or not tray.line_ids:
            # La falla no está presente: no hay evidencias que gestionar. Solo
            # la de LOTE conserva su bandeja clásica como fallback; el resto
            # cierra (p. ej. ``data_anomaly`` no tiene bandeja de lote).
            if self.env['printflow.flow.lots']._pf_is_lot_cause(code):
                return self._pf_open_lot_tray(code, product_id)
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Falla: %s') % (tray.summary or product.display_name),
            'res_model': tray_model,
            'res_id': tray.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _pf_open_supply_tray(self):
        """Abre la bandeja gestionable de INSUMOS (puebla bajo demanda).

        La bandeja se puebla desde el colaborador ``printflow.flow.supply`` con
        una fila por insumo/almacén afectado; el operador ve qué insumo está mal
        y elige la vía (traslado/compra/ajuste) o la corrección automática. Solo
        lista y navega al abrir: la escritura vive en las acciones de la bandeja
        (la automática conserva su guardia de permisos).
        """
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        tray = self.env[
            'printflow.flow.supply.tray']._pf_populate(product)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bandeja de insumos: %s') % product.display_name,
            'res_model': 'printflow.flow.supply.tray',
            'view_mode': 'tree',
            'domain': [('id', 'in', tray.ids)],
            'target': 'current',
        }

    def _pf_product_plan_for_cause(self, cause):
        """Plan del playbook para una causa, con el contexto del producto.

        Delega en la estrategia del producto para que las causas de LOTE reciban
        el plan ADAPTADO al modo (sin el ``replace_generic_lot`` que exige
        pedido). Lo usa ``action_run_pf_plan`` para el caso ``problem`` (la
        ``solution`` de lote/insumos abre la bandeja gestionable antes de llegar
        aquí).
        """
        self.ensure_one()
        ctx = self._pf_product_canvas_ctx()
        return self.env['printflow.flow.strategy.product']._pf_product_plan(
            cause, ctx.get('playbook_ctx') or {})

    def _pf_run_action(self, kind, target):
        """Traduce un paso del plan a una acción Odoo (solo navega aquí)."""
        self.ensure_one()
        kind = kind or 'none'
        if kind == 'navigate':
            return self._pf_nav_action(target)
        if kind == 'open_wizard':
            return self._pf_open_wizard(target)
        if kind == 'run_action':
            return self._pf_run_action_target(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_run_action_target(self, target):
        """Remedios con efecto (requieren permiso de jefe de taller/admin).

        El saneo/re-reserva por producto y los remedios de LOTE del Bloque V. Para
        el PRODUCTO, el "Solucionar" de un hallazgo de lote abre la bandeja
        gestionable; este camino queda para el remedio directo (p. ej. los alias
        del plan que sí son ``run_action``).
        """
        self.ensure_one()
        if target == 'fix_over_reservation':
            return self._pf_run_fix_over_reservation()
        if target in ('assign_lot', 'reconcile_lot_reservation',
                      'separate_lots', 'repair_finished_lot',
                      'replace_generic_lot'):
            return self._pf_run_lot_remedy(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_open_wizard(self, target):
        """Destinos de creación prellenada (OF/OC). No crean nada por sí solos."""
        self.ensure_one()
        if target == 'create_production':
            return self._pf_open_create_production()
        if target == 'buy_components':
            return self._pf_open_buy_components()
        if target == 'buy_product':
            return self._pf_open_buy_product()
        return {'type': 'ir.actions.act_window_close'}

    def _pf_nav_action(self, target):
        """Vocabulario de navegación del producto (solo lectura)."""
        self.ensure_one()
        target = target or 'none'
        if target == 'product':
            return self.action_open_product()
        if target == 'quants':
            return self._pf_open_quants()
        if target == 'quants_adjust':
            return self._pf_open_quants_adjust()
        if target == 'bom_list':
            return self._pf_open_bom_list()
        if target in ('mo', 'mo_list'):
            return self._pf_open_mo()
        if target == 'purchase_order':
            return self._pf_open_purchase_orders()
        if target == 'receipt':
            return self._pf_open_receipts()
        if target in ('reserving_sale_orders', 'blocking_reservations'):
            return self._pf_open_blocking_reservations()
        if target in ('delivery_orders', 'line_delivery'):
            return self._pf_open_delivery_orders()
        return {'type': 'ir.actions.act_window_close'}

    # ══════════════════════════════════════════════════════════════════════
    # DESTINOS CONCRETOS (solo lectura; abrir ≠ ejecutar)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_deficit_qty(self):
        """Cantidad a cubrir: el déficit físico, o 1 si no hay cifra."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return 1.0
        deficit = max(
            0.0,
            (product.outgoing_qty or 0.0)
            - (product.qty_available or 0.0)
            - (product.incoming_qty or 0.0))
        return deficit or 1.0

    def _pf_purchase_shortfall_qty(self):
        """Cantidad a comprar: el faltante REAL del producto, o 1 si no hay cifra.

        Faltante REAL (D1) = déficit físico − cobertura de OC SIN CONFIRMAR que ya
        apuntan a pedidos con entrega pendiente del producto. Reutiliza la FUENTE
        ÚNICA del motor de pendientes: si se comprara el déficit crudo y luego se
        confirmaran esas OC, la entrada se DUPLICARÍA. La OF y la compra de
        COMPONENTES siguen usando ``_pf_deficit_qty`` (D7: la cobertura del
        terminado no es trasladable a los insumos). Solo LECTURA.
        """
        self.ensure_one()
        product = self.product_id
        if not product:
            return 1.0
        deficit = max(
            0.0,
            (product.outgoing_qty or 0.0)
            - (product.qty_available or 0.0)
            - (product.incoming_qty or 0.0))
        cover = self.env[
            'printflow.flow.pending']._pf_purchase_unconfirmed_cover(
                [product.id]).get(product.id, 0.0) or 0.0
        return max(0.0, deficit - cover) or 1.0

    def _pf_open_quants(self):
        """Abre las existencias internas del producto."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Existencias de %s') % self.product_id.display_name,
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', self.product_id.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'target': 'current',
        }

    def _pf_open_quants_adjust(self):
        """Abre las existencias en modo AJUSTE (propone el déficit como cantidad)."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        suggested = max(
            0.0,
            (self.product_id.outgoing_qty or 0.0)
            - (self.product_id.qty_available or 0.0)
            - (self.product_id.incoming_qty or 0.0))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajuste de inventario de %s (sugerido: %.2f)') % (
                self.product_id.display_name, suggested),
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', self.product_id.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'context': {
                'inventory_mode': True,
                'search_default_product_id': self.product_id.id,
                'default_inventory_quantity': suggested,
                'pf_suggested_qty': suggested,
            },
            'target': 'current',
        }

    def _pf_open_bom_list(self):
        """Abre las listas de materiales del producto (para crearla)."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Listas de materiales de %s')
            % self.product_id.display_name,
            'res_model': 'mrp.bom',
            'view_mode': 'list,form',
            'domain': [
                ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
            ],
            'target': 'current',
        }

    def _pf_open_purchase_orders(self):
        """Abre las órdenes de compra SIN CONFIRMAR que incluyen el producto.

        D3: NO lista las compras ya hechas (confirmadas/recibidas). El criterio de
        "sin confirmar" sale de la FUENTE ÚNICA del motor de pendientes
        (``printflow.flow.pending``): no se duplica la tupla de estados.
        """
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        lines = self.env['purchase.order.line'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('order_id.state', 'in', self.env[
                'printflow.flow.pending']._pf_purchase_unconfirmed_states()),
        ])
        pos = lines.mapped('order_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s OC sin confirmar del producto') % len(pos),
            'res_model': 'purchase.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pos.ids)],
            'target': 'current',
        }

    def _pf_open_receipts(self):
        """Abre los albaranes de entrada que mueven el producto."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        pickings = self.env['stock.picking'].sudo().search([
            ('picking_type_id.code', '=', 'incoming'),
            ('state', 'not in', ('done', 'cancel')),
            ('move_ids.product_id', '=', self.product_id.id),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s recepción(es) del producto') % len(pickings),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def _pf_open_mo(self):
        """Abre las órdenes de fabricación activas del producto."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        mos = self.env['mrp.production'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('state', 'not in', ('done', 'cancel')),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s orden(es) de fabricación') % len(mos),
            'res_model': 'mrp.production',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', mos.ids)],
            'target': 'current',
        }

    def _pf_open_delivery_orders(self):
        """Abre las entregas (albaranes) que RESERVAN el producto."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        pickings = self.env['stock.picking'].sudo().search([
            ('state', 'not in', ('done', 'cancel')),
            ('picking_type_id.code', '=', 'outgoing'),
            ('move_line_ids.product_id', '=', self.product_id.id),
            ('move_line_ids.state', 'not in', ('done', 'cancel')),
            ('move_line_ids.quantity', '>', 0),
            ('move_line_ids.location_id.usage', '=', 'internal'),
        ], order='scheduled_date asc, id asc')
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s entrega(s) que lo reservan') % len(pickings),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def _pf_open_inventory_health(self):
        """Abre la bandeja de Salud de inventario filtrada a este producto."""
        self.ensure_one()
        return self.env['printflow.inventory.health']._pf_open_health(
            products=self.product_id,
            title=_('Salud de inventario: %s') % (
                self.product_id.display_name or ''))

    def _pf_open_blocking_reservations(self):
        """Abre la lista "quién me bloquea" (por entrega/albarán, ordenada)."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        records = self.env[
            'printflow.order.blocking.reservation'
        ]._pf_populate_for_product(product, product_flow_id=self.id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s entrega(s) que lo bloquean') % len(records),
            'res_model': 'printflow.order.blocking.reservation',
            'view_mode': 'tree',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }

    # ══════════════════════════════════════════════════════════════════════
    # REMEDIOS (open_wizard / run_action): "abrir ≠ ejecutar"
    # ══════════════════════════════════════════════════════════════════════
    def _pf_open_create_production(self):
        """Abre/crea la OF del producto (bloquea si no hay BOM: decisión 7)."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        if not Remedy._pf_has_bom(product):
            raise UserError(_(
                'El producto "%s" no tiene lista de materiales (BOM): no se '
                'puede crear una Orden de Fabricación real. Crea la BOM o usa '
                'Ajuste de inventario.') % product.display_name)
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva Orden de Fabricación'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_product_id': product.id,
                'default_product_qty': self._pf_deficit_qty(),
                'default_bom_id': bom.id if bom else False,
            },
        }

    def _pf_open_buy_product(self):
        """Abre la Compra Rápida prellenada con el producto faltante."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return self._pf_open_quick_purchase(
            [(product, self._pf_purchase_shortfall_qty())],
            title=_('Compra Rápida (producto)'))

    def _pf_open_buy_components(self):
        """Abre la Compra Rápida con los componentes faltantes de la BOM."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        missing = Remedy._pf_missing_components(product, self._pf_deficit_qty())
        if not missing:
            return self._pf_open_buy_product()
        return self._pf_open_quick_purchase(
            [(m['product'], m['need']) for m in missing],
            title=_('Compra Rápida (componentes)'))

    def _pf_open_quick_purchase(self, product_qty_list, title):
        """Crea la Compra Rápida SIN pedido de venta (decisión 10).

        Reutiliza ``mrp.quick.purchase.wizard`` sin forzar la recepción: el
        operador confirma. ``sale_order_id`` va vacío (producto sin venta).

        La cantidad viene del FALTANTE REAL fijado por la resolución del nodo
        Compras, así que se CONGELA (``pf_freeze_qty``): al "Traer pedidos" el
        wizard NO la recalcula con la lista de pedidos (D3). ``product_id`` es el
        producto de REFERENCIA (el que se está comprando): alimenta el dominio de
        "Agrupar pedidos" y la visibilidad del botón "Traer pedidos".
        """
        self.ensure_one()
        line_vals = []
        for product, qty in product_qty_list:
            vals = {
                'product_id': product.id,
                'product_qty': qty or 1.0,
                'product_uom_id': product.uom_id.id,
                # No forzamos recepción: solo se genera la OC.
                'material_received': False,
            }
            if product.seller_ids:
                vals['partner_id'] = product.seller_ids[0].partner_id.id
            line_vals.append((0, 0, vals))
        reference = (
            product_qty_list[0][0] if product_qty_list else self.product_id)
        wizard = self.env['mrp.quick.purchase.wizard'].create({
            'sale_order_id': False,
            'product_id': reference.id if reference else False,
            'pf_freeze_qty': True,
            'purchase_line_ids': line_vals,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'mrp.quick.purchase.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _pf_run_fix_over_reservation(self):
        """Sanea (suelta + re-asigna) las reservas colgadas del producto.

        Restringido a jefe de taller/administrador. NO despoja la reserva de
        ningún pedido: reasigna por reglas de Odoo (reutiliza el remedio ya
        probado de ``printflow.stock.remedy``).
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        result = Remedy._pf_cleanup_product_reservations(product)
        if result['cleaned_pickings']:
            message = _(
                'Reservas reajustadas al stock real: %s albarán(es).') % (
                    len(result['cleaned_pickings']))
            ntype = 'success' if not result['still_negative'] else 'warning'
        else:
            message = _('No había reservas colgadas que sanear.')
            ntype = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': ntype,
                'title': _('PrintFlow'),
                'message': message,
                'sticky': ntype == 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _pf_run_lot_remedy(self, target):
        """Ejecuta un remedio de LOTE sobre el producto del diagrama.

        Delgador de ``_pf_execute_lot_remedy`` (FUENTE ÚNICA del mapa
        target->helper y del guardia de permisos): el wizard solo envuelve el
        mensaje en una notificación. Así la bandeja gestionable
        (``printflow.flow.lot.tray``) y este camino comparten EXACTAMENTE la
        misma ejecución.
        """
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        message = self._pf_execute_lot_remedy(product, target)
        return self._pf_lot_remedy_notification(message)

    @api.model
    def _pf_execute_lot_remedy(self, product, target):
        """Ejecuta el remedio de lote (FUENTE ÚNICA: guardia + mapa target).

        Espejo de ``printflow.order.diagnostic.failure._pf_run_lot_remedy``: el
        mismo guardia de permisos (jefe de taller/admin) y las mismas llamadas de
        LECTURA/ESCRITURA del motor del addon principal
        (``printflow.stock.health``). Nunca asigna a un pedido el lote de otro
        cliente (regla de trazabilidad); sin pedido, ``replace_generic_lot`` es
        no-op y ``separate_lots`` ejecuta la parte segura.

        Devuelve el MENSAJE de resultado; los llamadores lo envuelven en la
        notificación de su superficie (wizard o bandeja).

        :param product: ``product.product`` a corregir.
        :param str target: destino del remedio (lista blanca explícita).
        :rtype: str
        """
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        if not product:
            return _('No hay un producto sobre el que aplicar la corrección.')
        Health = self.env['printflow.stock.health']
        if target == 'reconcile_lot_reservation':
            Health._pf_reassign_by_lot(product)
            return _('Reserva de lote reconciliada con los movimientos.')
        if target == 'replace_generic_lot':
            replaced = Health._pf_replace_generic_lot(product)
            return _('Lotes genéricos sustituidos: %s.') % replaced
        if target == 'separate_lots':
            Health._pf_replace_generic_lot(product)
            Health._pf_reassign_by_lot(product)
            return _('Movimientos separados por lote.')
        if target == 'repair_finished_lot':
            repaired = Health._pf_repair_finished_lot(product)
            return _('Órdenes de fabricación reparadas: %s.') % repaired
        if target == 'assign_lot':
            moves = self.env['stock.move'].sudo().search([
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
                ('location_id.usage', '=', 'internal'),
                ('picking_type_id.code', '=', 'outgoing'),
            ])
            for move in moves:
                if not move._pf_has_lot_assigned():
                    move._pf_auto_assign_lot()
            return _('Se asignó lote a los movimientos que no lo tenían.')
        return _('No hay una corrección disponible para este hallazgo.')

    def _pf_lot_remedy_notification(self, message):
        """Notificación estándar del resultado de un remedio de lote."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success', 'title': _('PrintFlow'),
                'message': message, 'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ══════════════════════════════════════════════════════════════════════
    # ASIGNACIÓN DE UN LOTE ELEGIDO POR EL OPERADOR (selector por documento)
    #
    # Orquestador ÚNICO de ESCRITURA del selector de lote. Despacho por
    # MAPA/LISTA BLANCA explícita (NUNCA ``getattr`` por convención) y guardia
    # de permisos ``_pf_assert_can_clean()``. Reutiliza SOLO primitivas del
    # motor: no inventa escrituras nuevas.
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_assign_lot_to_document(self, target_kind, res_model, res_id, lot,
                                   product=None):
        """Asigna el lote ELEGIDO al documento (guardia + despacho + escritura).

        :param str target_kind: tipo de ítem afectado (clave del mapa).
        :param str res_model: modelo del documento de la fila.
        :param int res_id: id del documento de la fila.
        :param stock.lot lot: lote que el operador eligió asignar.
        :param product.product product: producto del documento (opcional; por
            defecto el del lote).
        :return: mensaje de resultado (lo envuelve el selector en su notificación).
        :rtype: str
        """
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        if not lot:
            raise UserError(_('No se indicó el lote a asignar.'))
        product = (product or lot.product_id)
        # Lista blanca explícita tipo -> handler. Solo los ítems listados admiten
        # elección; la reserva huérfana NO (se corrige con "Corrección automática").
        handlers = {
            'missing_move': self._pf_assign_lot_on_move_doc,
            'pending_order': self._pf_assign_lot_on_pending_order_doc,
            'no_stock_lot': self._pf_assign_lot_on_move_doc,
            'generic_lot': self._pf_assign_lot_on_move_doc,
            'mixed_lot': self._pf_assign_lot_on_move_doc,
            'unassigned_mo': self._pf_assign_lot_on_mo_doc,
            'component_move': self._pf_assign_lot_on_component_doc,
        }
        handler = handlers.get(target_kind or '')
        if not handler:
            raise UserError(_(
                'Este ítem no permite elegir un lote (tipo: %s).') % (
                    target_kind or _('desconocido')))
        assigned = handler(res_model, res_id, lot, product)
        if not assigned:
            raise UserError(_(
                'El lote "%s" no tiene existencia disponible para asignarlo a '
                'este documento.') % lot.name)
        return _('Lote "%s" asignado al documento.') % lot.name

    @api.model
    def _pf_assign_lot_on_move_doc(self, res_model, res_id, lot, product):
        """Entrega/Terminado por MOVIMIENTO (``stock.move``): reescribe su reserva."""
        move = (
            self.env['stock.move'].sudo().browse(res_id).exists()
            if res_model == 'stock.move' and res_id
            else self.env['stock.move'])
        if not move:
            return 0
        return 1 if self._pf_reassign_move_lot(move, lot, product) else 0

    @api.model
    def _pf_assign_lot_on_pending_order_doc(self, res_model, res_id, lot, product):
        """Entrega en ORDEN pendiente (``stock.picking``) sin lote (H-026).

        La fila ``pending_order`` de la bandeja apunta a la ORDEN (albarán) y NO
        a un ``stock.move``: se resuelve su movimiento activo del producto (mismo
        camino que ``printflow.flow.lot.tray._pf_document_move``) y se delega la
        ESCRITURA en ``_pf_reassign_move_lot`` (protocolo NATIVO de reserva). Con
        esto el "Elegir lote" por fila deja de lanzar ``UserError`` y la acción en
        bloque reutiliza el MISMO escritor (D4/D9). Acepta también un
        ``stock.move`` directo (por si la fila trae el movimiento). Devuelve ``0``
        si no hay movimiento activo o si la reserva da 0: el orquestador lanza su
        ``UserError``, que el bloque captura POR DESTINO.
        """
        Move = self.env['stock.move'].sudo()
        move = Move
        if res_model == 'stock.move' and res_id:
            move = Move.browse(res_id).exists()
        elif res_model == 'stock.picking' and res_id:
            move = Move.search([
                ('picking_id', '=', res_id),
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
            ], limit=1)
        if not move:
            return 0
        return 1 if self._pf_reassign_move_lot(move, lot, product) else 0

    @api.model
    def _pf_assign_lot_on_mo_doc(self, res_model, res_id, lot, product):
        """Fabricación (``mrp.production`` done): asigna el lote ELEGIDO al terminado.

        Delega en la PRIMITIVA ÚNICA del motor
        ``mrp.production._pf_assign_finished_lot``: re-etiqueta los quants (lote
        viejo −, lote nuevo +, TOTAL intacto) SIN mover existencia y NIEGA
        (``UserError``) si el físico no alcanza, evitando el quant fantasma. No
        reimplementa la escritura (antes duplicaba el patrón escribiendo
        ``lot_producing_id`` a mano).
        """
        mo = (
            self.env['mrp.production'].sudo().browse(res_id).exists()
            if res_model == 'mrp.production' and res_id
            else self.env['mrp.production'])
        if not mo or mo.product_id.tracking != 'lot':
            return 0
        mo._pf_assign_finished_lot(lot)
        return 1

    @api.model
    def _pf_assign_lot_on_component_doc(self, res_model, res_id, lot, product):
        """Almacén de insumos (``stock.move`` de ``move_raw_ids``) de una MO.

        Reutiliza el helper EXISTENTE ``mrp.production._assign_lot_to_move``, que
        acepta el lote ELEGIDO y solo reescribe si cambia (no re-reserva).
        """
        move = (
            self.env['stock.move'].sudo().browse(res_id).exists()
            if res_model == 'stock.move' and res_id
            else self.env['stock.move'])
        if not move or move.product_id.tracking != 'lot':
            return 0
        mo = move.raw_material_production_id or move.production_id
        if not mo:
            return 0
        mo._assign_lot_to_move(move, lot)
        return 1

    @api.model
    def _pf_reassign_move_lot(self, move, lot, product=None):
        """Reescribe la reserva de UN movimiento con el lote ELEGIDO.

        Escritura ACOTADA al propio movimiento (Hueco 1): NO suelta el albarán
        (``do_unreserve()``) ni toca los movimientos HERMANOS, así reasignar un
        lote solo afecta a esa entrega.

        Delega en el **mecanismo ÚNICO** de cambio de lote
        (``stock.move._pf_reassign_lots``), el MISMO que consume el contenedor
        en bloque: el baile del tachón (destildar → liberar → reservar →
        devolver) vive allí, no se duplica aquí. Así este camino deja de
        **sumar reserva en silencio** sobre una unidad tachada (H-056 · CA-6).
        PROHIBIDO ``unlink()`` + ``create()`` a mano. Devuelve ``True`` si
        reservó algo.

        :param stock.move move: movimiento a reasignar.
        :param stock.lot lot: lote elegido.
        :param product.product product: producto del movimiento (opcional).
        :rtype: bool
        """
        product = product or move.product_id
        if not move or not product or product.tracking != 'lot':
            return False
        own_lines = move.move_line_ids
        # Idempotencia: ya reserva el lote elegido (y ningún otro) -> nada que hacer.
        if own_lines and not own_lines.filtered(lambda ml: ml.lot_id != lot):
            move._recompute_state()
            return True
        # Mecanismo ÚNICO (baile del tachón incluido): 1 liberación + 1 reserva.
        taken = move._pf_reassign_lots([lot])
        return taken > _EPS

    # ══════════════════════════════════════════════════════════════════════
    # REPARTO MULTI-LOTE ELEGIDO POR EL OPERADOR (H-037)
    #
    # Orquestador HERMANO de ``_pf_assign_lot_to_document`` (el de UN lote, que NO
    # se toca). Mismo módulo escritor, misma guardia de permisos y misma lista
    # blanca explícita de ``kind``; la única diferencia es que aquí se reservan N
    # lotes de forma ADITIVA sobre el MISMO movimiento (ver ``_pf_reassign_lots``).
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_assign_lots_to_document(self, target_kind, res_model, res_id, lots,
                                    product=None):
        """Reparte VARIOS lotes entre la demanda del documento (guardia + escritura).

        Sigue el MISMO protocolo NATIVO que el camino de un lote; solo cambia el
        PATRÓN (1 liberación + N reservas ADITIVAS). No inventa escrituras: consume
        ``stock.move._pf_reassign_lots`` (PrintFlow), que a su vez consume las
        primitivas del motor ``_pf_unreserve_reservation`` / ``_pf_reserve_lot``.

        :param str target_kind: tipo de ítem afectado (lista blanca ``_SPLIT_KINDS``).
        :param str res_model: modelo del documento de la fila.
        :param int res_id: id del documento de la fila.
        :param list lots: lotes del plan, EN ORDEN (el de la tabla de candidatos).
        :param product.product product: producto del documento (opcional).
        :return: cantidad realmente reservada (``float``; ``0.0`` si no aplica).
        :rtype: float
        """
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        if not lots:
            raise UserError(_('No se indicaron lotes para el reparto.'))
        # Lista blanca EXPLÍCITA: un ``kind`` fuera de ella no escribe nada.
        if (target_kind or '') not in _SPLIT_KINDS:
            return 0.0
        move = self._pf_split_target_move(res_model, res_id, product)
        if not move:
            return 0.0
        # ``list(...)`` fija el ORDEN del plan sin ambigüedad del ORM.
        return move._pf_reassign_lots(list(lots))

    @api.model
    def _pf_split_target_move(self, res_model, res_id, product):
        """Resuelve el movimiento del destino del REPARTO (resolver PRIVADO propio).

        Mismo camino que ``_pf_assign_lot_on_pending_order_doc`` (entrega por
        ``stock.move`` directo o por ``stock.picking`` buscando el movimiento
        activo del producto), pero SIN tocar el handler existente. Cualquier otro
        modelo devuelve un recordset vacío.

        :param str res_model: modelo del documento de la fila.
        :param int res_id: id del documento de la fila.
        :param product.product product: producto del documento.
        :rtype: models.Model
        """
        Move = self.env['stock.move'].sudo()
        if res_model == 'stock.move' and res_id:
            return Move.browse(res_id).exists()
        if res_model == 'stock.picking' and res_id and product:
            return Move.search([
                ('picking_id', '=', res_id),
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
            ], limit=1)
        return Move

    def action_open_collect_causante(self):
        """Abre la Bandeja de Resolución del ESCÁNER para este producto.

        Reutiliza el motor de chequeos (``printflow.product.diagnostic.wizard``)
        y su bandeja (``printflow.product.diagnostic.evidence``): solo lista y
        navega, no modifica datos.
        """
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        scanner = self.env['printflow.product.diagnostic.wizard'].create({
            'product_ids': [(6, 0, [product.id])],
            'origin': 'product',
            'origin_model': 'product.product',
            'origin_res_id': product.id,
            'origin_label': product.display_name or '',
        })
        return scanner.action_open_resolution_tray()
