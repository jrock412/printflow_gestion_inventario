# -*- coding: utf-8 -*-
"""Estrategia de flujo del PEDIDO (con venta) — PrintFlow · Fase 3.

Adaptador ``printflow.flow.strategy.order`` que traduce el **wizard de pedido**
(registros ``printflow.order.diagnostic.failure`` + subárbol del foco) al
**contexto de flujo normalizado** que consume el builder del canvas. Hereda la
interfaz ``printflow.flow.strategy`` y aporta SOLO la traducción del caso pedido.

Se EXTRAJO del servicio ``printflow.flow.canvas`` (Fase 3 del refactor OOP,
``docs/plan_fases_orquestador_oop_v2.md``) **SIN cambiar comportamiento**: los
helpers de contexto (``_pf_canvas_statuses``, ``_pf_anomaly_node_keys``,
``_pf_node_pending_lookup``, ``_pf_slot_failures``, ``_pf_hosted_failures``,
``_pf_failure_host``, ``_pf_root_slot``) se movieron TAL CUAL. El canvas conserva
DELEGADORES con la MISMA firma para no romper wrappers ni tests.

No toca el motor de reglas (solo lo consulta) ni la base de datos.
"""

import logging

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_LABELS,
    PF_NODE_TO_SLOT,
)

_logger = logging.getLogger(__name__)

# Umbral de comparación de cantidades (mismo que el motor y el resto de piezas).
_EPS = 1e-6


class PrintflowFlowStrategyOrder(models.AbstractModel):
    """Estrategia del caso PEDIDO (con venta)."""

    _name = 'printflow.flow.strategy.order'
    _inherit = 'printflow.flow.strategy'
    _description = 'Estrategia de flujo del pedido (PrintFlow)'

    @api.model
    def _pf_flow_case(self):
        return 'order'

    # ══════════════════════════════════════════════════════════════════════
    # CONTEXTO NORMALIZADO DEL PEDIDO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_flow_context(self, host):
        """Contexto de flujo del PEDIDO a partir del wizard y su línea enfocada.

        Reúne en UN solo dict todo lo que el builder necesita: tipo de flujo,
        eje, estados, miembros, reparto de stock, pendientes por nodo, fallas
        (registros), roles/padres de la cadena, raíz del canvas y las políticas
        del caso (``owner_policy``/``host_fallback_policy``). Sin foco devuelve
        un contexto SEGURO (sin estados ni acciones).
        """
        presentation = self.env['printflow.flow.presentation']
        Failure = self.env['printflow.order.diagnostic.failure']
        line = host.focus_line_id
        failures = line.flow_failure_ids if line else Failure
        flow_type = (
            'manufacture' if (line and line.is_manufacturable) else 'purchase')
        axis = list(presentation._PF_AXIS_ORDER[flow_type])
        members = host._pf_collect_subtree(line) if line else []
        stock_split = self.env[
            'printflow.order.health.engine']._pf_flow_stock_split(members)
        statuses = self._pf_canvas_statuses(host, line, flow_type, stock_split)
        anomaly_keys = self._pf_anomaly_node_keys(host, line) if line else set()

        slot_failures = self._pf_slot_failures(failures)
        key_by_slot = self._pf_key_by_slot(axis)
        broken_slots = self._pf_broken_slots(axis, statuses, slot_failures)
        root_failure = failures.filtered(
            lambda f: f.pf_chain_role == 'root')[:1]
        root_slot = (
            self._pf_failure_slot(root_failure) if root_failure
            else self._pf_root_slot(line))
        roles, parents = self._pf_slot_chain_roles(broken_slots, root_slot)
        root_canvas_key = key_by_slot.get(root_slot) if root_slot else None
        hosted, external_ids = self._pf_hosted_failures(
            failures, axis, key_by_slot, line)
        context_failure = (
            self._pf_node_owner_failure(line.failure_ids) if line else None)
        # Delta de PENDIENTES: en el pedido, el nodo ENTREGA usa el conteo de
        # entregas AJENAS pendientes (``focus_pending_delivery_order_count``), no
        # el mapa genérico. La estrategia da FORMA al mapa para que el Builder
        # sea uniforme (``pending_by_key.get(key, 0)``).
        pending_by_key = (
            self._pf_node_pending_lookup(line, host.board_id) if line else {})
        if line:
            pending_by_key = dict(pending_by_key)
            pending_by_key['delivery'] = (
                host.focus_pending_delivery_order_count or 0)
            # Recepción = señal PROPIA (D6): albaranes de entrada REALES del
            # terminado (+ insumos de la BOM si el producto es fabricable, D4).
            # Se calcula DESPUÉS de ``broken_slots`` (arriba) para que su
            # semáforo NO abra cadena por sí solo (guard de D6).
            if line.is_manufacturable and line.product_id:
                components = self._pf_bom_components(line.product_id)
                if components:
                    receipt_count = self.env[
                        'printflow.flow.pending']._pf_receipt_pending_distinct(
                            [line.product_id.id] + components.ids)
                    if receipt_count:
                        pending_by_key['receipt'] = receipt_count
                    else:
                        pending_by_key.pop('receipt', None)
            statuses['receipt'] = (
                'pending' if pending_by_key.get('receipt') else 'na')

        deficit = (line.deficit_qty if line else 0.0) or 0.0
        # FALTANTE REAL de Compras (D1/D6, paridad con el producto): del déficit
        # de la línea se resta la cobertura de OC SIN CONFIRMAR RESTRINGIDA a
        # este pedido (``sale_order``), para no duplicar entradas. Sin OC sin
        # confirmar la cobertura es 0 y el faltante == déficit.
        cover = 0.0
        if line and line.product_id:
            # El pedido enfocado sale del BOARD del wizard (la línea del wizard
            # no guarda el ``sale.order``): se usa la MISMA fuente del resto del
            # contexto (``host.board_id``), sin inventar campos.
            cover = self.env[
                'printflow.flow.pending']._pf_purchase_unconfirmed_cover(
                    [line.product_id.id],
                    sale_order=host.board_id.sale_order_id
                ).get(line.product_id.id, 0.0)
        shortfall = max(0.0, deficit - cover)
        return {
            'case': self._pf_flow_case(),
            'line': line,
            'host': host,
            'has_focus': bool(line),
            # Política de RENDER: con foco el Builder pinta estados/acciones; sin
            # foco devuelve un payload SEGURO (mismo comportamiento histórico).
            'focus': bool(line),
            # Nodo del rótulo de ``root_link`` (raw: el pedido usa ``False`` si no
            # hay nodo raíz; el Builder no debe normalizarlo).
            'root_label_node': (line.root_cause_node if line else ''),
            'flow_type': flow_type,
            'axis': axis,
            'statuses': statuses,
            'members': members,
            'stock_split': stock_split,
            'pending_by_key': pending_by_key,
            # Magnitud del FALTANTE de Compras (D1/D4/D6): el faltante REAL de la
            # línea (déficit − OC sin confirmar del pedido). Solo se llena el
            # nodo ``purchase`` cuando está ``missing`` (faltante > 0).
            'shortfall_by_key': (
                {'purchase': shortfall}
                if (line and statuses.get('purchase') == 'missing'
                    and shortfall > _EPS) else {}),
            'failures': failures,
            'severity': (line.flow_severity if line else None) or None,
            'root_cause_node': (line.root_cause_node if line else None) or None,
            'chain_summary': host.focus_chain_summary or '',
            'product': line.product_id if line else False,
            'pending_delivery_count': (
                host.focus_pending_delivery_order_count if line else 0),
            'anomaly_keys': anomaly_keys,
            'slot_failures': slot_failures,
            'key_by_slot': key_by_slot,
            'broken_slots': broken_slots,
            'root_slot': root_slot,
            'roles': roles,
            'parents': parents,
            'root_canvas_key': root_canvas_key,
            'hosted': hosted,
            'external_failure_ids': external_ids,
            'context_failure': context_failure,
            'owner_policy': 'min_rank',
            'host_fallback_policy': 'parent_then_axis0',
            # Contexto NORMALIZADO para el playbook: en el PEDIDO el microcopy
            # conserva "el pedido". El ``lot_prep`` lo usa SOLO la capa de
            # explicación (el pedido NO inyecta falla de lote: su fila ya nace
            # del motor y una segunda fila la duplicaría).
            'mode': 'order',
            'has_order': True,
            'lot_prep': self.env['printflow.flow.lots']._pf_prepare({
                'members': members,
                'product': line.product_id if line else False,
                'mode': 'order',
                'has_order': True,
            }),
        }

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS DE CONTEXTO DEL PEDIDO (movidos TAL CUAL desde el canvas)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_failure_slot(self, failure):
        """Slot de canvas de una falla (delega en presentación pura)."""
        return self.env[
            'printflow.flow.presentation']._pf_failure_slot(failure)

    @api.model
    def _pf_slot_failures(self, failures):
        """Agrupa las fallas del subárbol por slot de canvas."""
        Failure = self.env['printflow.order.diagnostic.failure']
        grouped = {}
        for failure in failures:
            slot = self._pf_failure_slot(failure)
            if not slot:
                continue
            grouped[slot] = grouped.get(slot, Failure) | failure
        return grouped

    @api.model
    def _pf_hosted_failures(self, failures, axis, key_by_slot, line):
        """Reparte CADA falla del subárbol en UN SOLO hito del eje."""
        Failure = self.env['printflow.order.diagnostic.failure']
        hosted = {key: Failure for key in axis}
        external_ids = set()
        focus_product = line.product_id if line else None
        for failure in failures:
            host_key, is_orphan = self._pf_failure_host(
                failure, axis, key_by_slot)
            hosted[host_key] |= failure
            is_external = is_orphan or failure.node == 'sale'
            if not is_external and focus_product:
                is_external = failure.origin_product_id != focus_product
            if is_external:
                external_ids.add(failure.id)
        return hosted, external_ids

    @api.model
    def _pf_failure_host(self, failure, axis, key_by_slot):
        """Hito del eje que cobija una falla: ``(key, es_externa)``."""
        slot = self._pf_failure_slot(failure)
        host_key = key_by_slot.get(slot)
        if host_key:
            return host_key, False
        parent = failure.pf_chain_parent_node
        if parent:
            parent_slot = PF_NODE_TO_SLOT.get(parent, parent)
            host_key = key_by_slot.get(parent_slot)
            if host_key:
                return host_key, True
        return axis[0], True

    @api.model
    def _pf_root_slot(self, line):
        """Slot de canvas del nodo raíz causal (``line.root_cause_node``)."""
        if not line or not line.root_cause_node:
            return None
        return PF_NODE_TO_SLOT.get(
            line.root_cause_node, line.root_cause_node)

    @api.model
    def _pf_canvas_statuses(self, host, line, flow_type, stock_split):
        """Estado crudo de cada hito del canvas (solo señales existentes)."""
        presentation = self.env['printflow.flow.presentation']
        if not line:
            return {key: 'na' for key in presentation._PF_AXIS_ORDER[flow_type]}
        purchase = host.focus_purchase_status or 'na'
        delivery = host.focus_delivery_status or 'na'
        statuses = {
            'purchase': purchase,
            # El estado de RECEPCIÓN se desacopla del proxy de compra (D6): lo
            # fija ``_pf_flow_context`` a partir de las recepciones REALES una
            # vez resuelta la tabla de pendientes. Aquí nace en ``na``.
            'receipt': 'na',
            'delivery': delivery,
            'customer': 'ok',
        }
        if flow_type == 'manufacture':
            supply = (
                host.focus_supply_status
                or stock_split.get('supply') or 'ok')
            statuses['stock_supply'] = supply
            statuses['stock_finished'] = stock_split.get('finished') or 'ok'
            statuses['production'] = host.focus_production_status or 'na'
        else:
            statuses['stock'] = host.focus_stock_status or 'na'
        return statuses

    @api.model
    def _pf_anomaly_node_keys(self, host, line):
        """Claves de NODO del eje que detectan reservas colgadas (solo lectura)."""
        if not line:
            return set()
        members = host._pf_collect_subtree(line)
        flow_type = 'manufacture' if line.is_manufacturable else 'purchase'
        return self._pf_anomaly_node_keys_from_members(flow_type, members)

    @api.model
    def _pf_node_pending_lookup(self, line, board=None):
        """Pendientes por NODO del producto enfocado: ``{node_key: count}``."""
        if not line or not line.product_id:
            return {}
        try:
            pending_map = self.env[
                'printflow.flow.pending']._pf_node_pending_map(
                    line.product_id, exclude=board)
        except Exception:  # noqa: BLE001 - aditivo: nunca tumbar el canvas
            _logger.exception(
                'PrintFlow: falló el cálculo de pendientes por nodo del '
                'producto %s', line.product_id.id)
            return {}
        return pending_map.get(line.product_id.id) or {}

    # ══════════════════════════════════════════════════════════════════════
    # HOOKS DE PRESENTACIÓN DEL PEDIDO (vocabulario del caso; Fase 4)
    #
    # Movidos TAL CUAL desde ``printflow.flow.canvas`` (los métodos homónimos
    # quedan allí como delegadores). El Builder único los invoca a través de la
    # estrategia; el vocabulario NO se unifica entre pedido y producto.
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_node_actions(self, host, node_key, owner_failure=None, role='none',
                         status=None, is_root=False, context_failure=None,
                         anomaly=False, pending=0, context=None):
        """Acciones DIRECTAS del popover de un hito (solo presentación)."""
        actions = []
        presentation = self.env['printflow.flow.presentation']
        board = host.board_id
        is_consequence = role == 'consequence'
        owner = owner_failure
        owner_context = owner if owner is not None else context_failure

        def add(key, label, kind, failure_id=None, res_model=None, res_id=None,
                method=None, enabled=True, args=None, primary=False,
                sublabel=None):
            if is_consequence and kind == 'run_action':
                return
            actions.append(self._pf_action(
                key, label, kind, failure_id, res_model, res_id, method,
                enabled, args=args, primary=primary, sublabel=sublabel))

        def failure_action(key, label, kind='navigate', primary=False,
                           sublabel=None):
            if owner_context is None:
                return
            add(key, label, kind, owner_context.id, owner_context._name,
                owner_context.id, 'action_run_pf_node', args=[key],
                primary=primary, sublabel=sublabel)

        def board_action(key, label, method, kind='run_action'):
            if not board:
                return
            add(key, label, kind, None, 'printflow.order.board', board.id,
                method)

        if owner is not None and not is_consequence and (
                owner.pf_solution_available or owner.pf_remedy_available):
            if owner.pf_remedy_available:
                sublabel, kind = owner.pf_remedy_label, owner.pf_remedy_kind
            else:
                sublabel, kind = owner.pf_solution_label, owner.pf_solution_kind
            if kind != 'run_action':
                add('solution', _('Solucionar'), kind, owner.id,
                    primary=True, sublabel=sublabel)
        if owner is not None and owner.pf_problem_available:
            add('problem', owner.pf_problem_label or _('Ver el problema'),
                owner.pf_problem_kind or 'navigate', owner.id)
        if (owner is not None and not is_consequence
                and owner.pf_second_remedy_available):
            add('second_remedy',
                owner.pf_second_remedy_label or _('Alternativa'),
                owner.pf_second_remedy_kind or 'navigate', owner.id)
        if node_key == 'purchase':
            failure_action(
                'buy_product', _('Comprar producto'), kind='open_wizard')
            failure_action(
                'buy_components', _('Comprar componentes'),
                kind='open_wizard')
            board_action(
                'quick_purchase', _('COMPRA RÁPIDA'),
                'action_open_quick_purchase', kind='open_wizard')
            board_action(
                'quick_purchase_component', _('COMPRA RÁPIDA componente'),
                'action_open_quick_purchase_component', kind='open_wizard')
            failure_action(
                'view_purchase', _('Ver OC sin confirmar'))
        elif node_key == 'receipt':
            board_action(
                'receive', _('RECIBIR MERCANCÍA'),
                'action_receive_purchase_materials', kind='run_action')
            failure_action(
                'open_receipt', _('Abrir albarán'))
            failure_action(
                'open_own_receipt', _('Abrir albarán propio'))
        elif node_key in ('stock', 'stock_supply', 'stock_finished'):
            failure_action('quants', _('Ver existencias'))
            failure_action(
                'adjust', _('Ajustar inventario'))
            if self._pf_can_clean_reservations():
                failure_action(
                    'fix_reservation', _('Liberar y re-reservar'),
                    kind='run_action')
            if anomaly and self._pf_can_clean_reservations():
                board_action(
                    'cleanup_reservations', _('Sanear reservas colgadas'),
                    'action_cleanup_over_reservations', kind='run_action')
            failure_action(
                'blocking', _('Ver quién me bloquea'))
            if node_key == 'stock_supply':
                failure_action(
                    'fabricate', _('Ir a la Orden de Fabricación'),
                    kind='open_wizard')
        elif node_key == 'production':
            failure_action(
                'fabricate', _('Ir a la Orden de Fabricación'),
                kind='open_wizard')
            board_action(
                'approve_design', _('APROBAR ARTE'),
                'action_approve_design_all', kind='run_action')
        elif node_key == 'delivery':
            failure_action(
                'line_delivery', _('Ir a la entrega'))
            add('pending_deliveries', _('Ver órdenes pendientes'), 'navigate',
                None, host._name, host.id,
                'action_open_pending_delivery_orders')
        if (pending and node_key != 'delivery'
                and node_key in presentation._PF_PENDING_ACTION_KEYS):
            add('pending', _('Ver pendientes (%s)') % pending, 'navigate',
                None, host._name, host.id, 'action_open_node_pending',
                args=[node_key])
        if is_root and owner is not None:
            add('collect', _('Recopilar'), 'navigate', owner.id, owner._name,
                owner.id, 'action_open_collect_tray')
            if owner.pf_backlog_available:
                add('inventory_health', _('Salud de inventario'), 'navigate',
                    owner.id)
        return actions

    @api.model
    def _pf_node_panel(self, host, node_failures, roles_by_slot, context):
        """Detalle del área FUSIONADO en el popover: una fila por falla."""
        rows = []
        for failure in node_failures:
            is_consequence = bool(failure.pf_chain_is_consequence)
            rows.append(self.env['printflow.flow.actions']._pf_panel_row({
                'failure_id': failure.id,
                'label': failure.pf_chain_label or PF_CHAIN_LABELS.get(
                    failure.node, failure.node or ''),
                'detail': failure.summary or '',
                'origin': failure.origin_product_id.display_name or '',
                'origin_kind': failure.origin_kind or '',
                'chain_note': failure.pf_chain_note or '',
                'plan_summary': failure.pf_plan_summary or '',
                'role': failure.pf_chain_role or 'none',
                'tone': (
                    'danger' if failure.severity == 'danger'
                    else 'warn' if failure.severity == 'warning' else 'ok'),
                'is_consequence': is_consequence,
                'problem_available': bool(failure.pf_problem_available),
                'solution_available': bool(
                    not is_consequence and (
                        failure.pf_solution_available
                        or failure.pf_remedy_available)),
                'collect_available': bool(
                    not is_consequence
                    and failure.pf_collect_available),
                'actions': self._pf_failure_row_actions(
                    failure, is_consequence),
            }))
        return rows

    @api.model
    def _pf_failure_row_actions(self, failure, is_consequence):
        """Acciones POR FILA del panel (métodos PÚBLICOS de la falla)."""
        actions = []
        if not is_consequence:
            if (failure.pf_remedy_available
                    and failure.pf_remedy_kind not in (False, 'none')):
                actions.append({
                    'key': 'solution',
                    'label': _('Solucionar'),
                    'sublabel': failure.pf_remedy_label or '',
                    'failure_id': failure.id,
                    'enabled': True,
                    'primary': True,
                })
            elif failure.pf_solution_available:
                actions.append({
                    'key': 'solution',
                    'label': _('Solucionar'),
                    'sublabel': failure.pf_solution_label or '',
                    'failure_id': failure.id,
                    'enabled': True,
                    'primary': True,
                })
        if failure.pf_problem_available:
            actions.append({
                'key': 'problem',
                'label': failure.pf_problem_label or _('Ver el problema'),
                'failure_id': failure.id,
                'enabled': True,
            })
        if not is_consequence and failure.pf_second_remedy_available:
            actions.append({
                'key': 'second_remedy',
                'label': failure.pf_second_remedy_label or _('Alternativa'),
                'failure_id': failure.id,
                'enabled': True,
            })
        return actions

    @api.model
    def _pf_root_tray(self, host, context, owner_failure=None):
        """Bandeja de Resolución serializada como CONTENIDO del nodo raíz."""
        owner = owner_failure
        if owner is None:
            return []
        rows = []
        for vals in owner._pf_collect_causante_vals():
            rows.append(
                self.env['printflow.flow.actions']._pf_tray_row(vals))
        return rows
