# -*- coding: utf-8 -*-
"""Builder ÚNICO del payload del canvas de flujo (PrintFlow · Fase 4).

Servicio ``AbstractModel`` sin tabla que concentra el **único bucle** de armado
del payload que consume el widget OWL ``printflow_order_timeline`` (nodos,
aristas, geometría y ``global``). Se EXTRAJO del servicio
``printflow.flow.canvas`` (Fase 4 del refactor OOP,
``docs/plan_fases_orquestador_oop_v2.md``) SIN cambiar comportamiento.

Contrato::

    env['printflow.flow.payload.builder']._pf_build(context, strategy) -> dict

Diseño (el corazón de la Variante 2):

  * **Agnóstico del caso.** El Builder NO importa ni menciona ``order`` /
    ``product``: solo lee el **contexto normalizado** y llama a los **hooks** de
    la estrategia (``strategy._pf_node_actions``, ``strategy._pf_node_panel``,
    ``strategy._pf_root_tray``). Así desaparecen los constructores gemelos.
  * **Los deltas viven en el contexto/estrategia**, nunca en un ``if caso ==``:
      - ``owner_policy``      -> la estrategia resuelve la falla "dueña"
        (``strategy._pf_node_owner_failure``): ``min_rank`` (pedido) vs ``first``
        (producto).
      - ``host_fallback_policy`` -> se aplica en la estrategia AL repartir las
        fallas por hito: ``parent_then_axis0`` (pedido) vs ``axis0`` (producto).
      - ``external_failure_ids`` -> el Builder cuenta con ``_pf_external_count``
        las fallas externas del hito (``extra_count``); el producto manda
        ``set()``.
      - otros valores constantes por caso (``info``/``pending`` de entrega,
        ``focus``, ``root_label_node``) viajan como claves del contexto.
"""

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_LABELS,
    PF_CHAIN_ORDER,
)


class PrintflowFlowPayloadBuilder(models.AbstractModel):
    """Builder único del payload del canvas (contexto + estrategia)."""

    _name = 'printflow.flow.payload.builder'
    _description = 'Builder único del payload del canvas de flujo (PrintFlow)'

    @api.model
    def _pf_build(self, context, strategy):
        """Payload del diagrama a partir del contexto NORMALIZADO y la estrategia.

        :param dict context: contexto de flujo normalizado (§A.3). Debe traer
            ``host``, ``axis``, ``statuses``, ``roles``, ``hosted``,
            ``root_canvas_key``, ``anomaly_keys``, ``pending_by_key``,
            ``external_failure_ids``, ``context_failure``, ``focus`` y, si
            aplica, ``root_label_node``.
        :param strategy: recordset de la estrategia del caso (order/product);
            aporta los hooks de acciones/panel/tray y la selección de la falla
            "dueña".
        """
        ctx = context
        presentation = self.env['printflow.flow.presentation']
        actions = self.env['printflow.flow.actions']
        explain = self.env['printflow.flow.explain']
        host = ctx.get('host')
        axis = ctx['axis']
        statuses = ctx['statuses']
        roles = ctx['roles']
        parents = ctx['parents']
        key_by_slot = ctx['key_by_slot']
        hosted = ctx['hosted']
        root_canvas_key = ctx['root_canvas_key']
        anomaly_keys = ctx['anomaly_keys']
        pending_by_key = ctx.get('pending_by_key') or {}
        external_ids = ctx.get('external_failure_ids') or set()
        context_failure = ctx.get('context_failure')
        focus = bool(ctx.get('focus'))
        root_label_node = ctx.get('root_label_node', '')
        empty_failures = strategy._pf_empty_node_failures()

        nodes = []
        node_count = len(axis)
        rows = 2 if node_count > 4 else 1
        per_row = (node_count + 1) // 2 if rows == 2 else node_count
        # Capa de EXPLICACIÓN: el estado de lote ya lo resolvió la estrategia del
        # caso en UNA sola pasada (``ctx['lot_prep']``, colaborador
        # ``printflow.flow.lots``); cada nodo reutiliza ese ``prep`` sin
        # recalcular. Si no viniera (compatibilidad), se arma el respaldo.
        explain_prep = ctx.get('lot_prep') or explain._pf_prepare(ctx, strategy)
        for index, key in enumerate(axis):
            meta = presentation._PF_NODE_META[key]
            slot = meta['chain']
            status = statuses.get(key)
            is_terminal = key == 'customer'
            node_anomaly = key in anomaly_keys
            role = 'none' if is_terminal else roles.get(slot, 'none')
            tone = presentation._pf_node_tone(key, status)
            node_failures = (
                empty_failures if is_terminal
                else hosted.get(key, empty_failures))
            owner_failure = (
                None if is_terminal
                else strategy._pf_node_owner_failure(node_failures))
            parent_key = (
                key_by_slot.get(parents.get(slot))
                if role == 'consequence' else None)
            is_root = key == root_canvas_key
            summary, summary_more = strategy._pf_node_summary(
                node_failures, owner_failure)
            if rows == 2 and index >= per_row:
                col = index - per_row
                row = 1
            else:
                col = index
                row = 0
            node_info = (
                (ctx.get('pending_delivery_count') or 0)
                if (key == 'delivery' and focus) else 0)
            node_pending = pending_by_key.get(key, 0) if focus else 0
            node_pending_action = None
            if (focus and node_pending > 0
                    and key in presentation._PF_PENDING_ACTION_KEYS):
                node_pending_action = actions._pf_pending_action(
                    host, key, node_pending)
            node = {
                'key': key,
                'label': meta['label'],
                'seq': index + 1,
                'kind': meta['kind'],
                'shape': meta['shape'],
                'col': col,
                'row': row,
                'owner': meta['owner'],
                'chain': slot,
                'status': (status or None) if focus else None,
                'status_label': (
                    presentation._pf_node_status_label(key, status)
                    if focus else ''),
                'tone': tone,
                'role': role,
                'parent': parent_key,
                'issues': len(node_failures),
                'anomaly': bool(node_anomaly),
                'summary': summary,
                'summary_more': summary_more,
                'extra_count': (
                    self._pf_external_count(node_failures, external_ids)
                    if focus else 0),
                'info': node_info,
                'pending': node_pending,
                # Etiqueta EXPLÍCITA del pendiente (ADITIVA, D5): el widget la
                # concatena al número para no decir un genérico "pendiente(s)".
                'pending_label': presentation._pf_node_pending_label(key),
                # Magnitud del FALTANTE por hito (ADITIVA, D1): el déficit real
                # que cada estrategia colocó en ``ctx['shortfall_by_key']``.
                # Solo Compras lo trae (>0); el resto queda en 0. NO se toca
                # ``status_label``/``summary``/``tone`` (contrato intacto).
                'shortfall_qty': (
                    float((ctx.get('shortfall_by_key') or {}).get(key) or 0.0)
                    if focus else 0.0),
                'shortfall_label': presentation._pf_node_shortfall_label(key),
                'pending_action': node_pending_action,
                'actions': (
                    strategy._pf_node_actions(
                        host, key, owner_failure, role, status, is_root,
                        context_failure, anomaly=node_anomaly,
                        pending=node_pending, context=ctx)
                    if focus else []),
                'panel': strategy._pf_node_panel(
                    host, node_failures, roles, ctx),
            }
            if role == 'consequence' and root_canvas_key:
                node['root_link'] = {
                    'label': _('Se rompió porque falló %s') % PF_CHAIN_LABELS.get(
                        root_label_node, root_label_node),
                    'target_key': root_canvas_key,
                }
            if is_root:
                node['tray'] = strategy._pf_root_tray(host, ctx, owner_failure)
            # Capa de EXPLICACIÓN (aditiva): sintetiza status/summary/panel/pending
            # más el estado de lote. NO toca `tone` (paridad del semáforo intacta).
            node['explain'] = explain._pf_node_explain(
                key, node, ctx, explain_prep, node_failures=node_failures,
                owner_failure=owner_failure, node_pending=node_pending)
            nodes.append(node)

        return {
            'order': list(PF_CHAIN_ORDER),
            'flow_type': ctx['flow_type'],
            'axis': axis,
            'global': {
                'severity': ctx.get('severity') or None,
                'root': ctx.get('root_cause_node') or None,
                'chain_summary': ctx.get('chain_summary') or '',
            },
            'nodes': nodes,
            'layout': {
                'grid': {'cols': per_row, 'rows': rows},
                'cell': dict(presentation._PF_FLOW_CELL),
            },
            'edges': presentation._pf_flow_edges(
                axis, statuses, roles, root_canvas_key, key_by_slot),
        }

    @api.model
    def _pf_external_count(self, node_failures, external_ids):
        """Cuenta las fallas del hito que pertenecen a ORÍGENES externos.

        Es la política del delta ``extra_count`` (§A.5): el Builder cuenta con
        ``external_failure_ids``; el producto manda el conjunto VACÍO y por eso su
        ``extra_count`` siempre es 0 sin ramificar por caso. Tolera el shape
        registro (pedido) y el shape dict (producto) de la falla.
        """
        if not external_ids:
            return 0
        count = 0
        for failure in node_failures:
            failure_id = (
                failure.get('id') if isinstance(failure, dict)
                else failure.id)
            if failure_id in external_ids:
                count += 1
        return count
