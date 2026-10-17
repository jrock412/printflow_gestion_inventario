# -*- coding: utf-8 -*-
"""Capa de EXPLICACIÓN del diagrama de flujo (PrintFlow).

Servicio ``AbstractModel`` PURO (sin estado ni tabla ⇒ NO lleva fila en
``security/ir.model.access.csv``) que SINTETIZA, por CADA nodo del canvas, una
explicación humana de cinco claves::

    node['explain'] = {
        'headline': str,   # 1 línea, humano
        'what': str,       # 2-3 líneas
        'why': list[str],  # motivos
        'how': list[str],  # pasos de solución (TEXTO, no botones)
        'severity': str,   # 'ok' | 'info' | 'warn' | 'danger'
    }

Principios de diseño (plan aprobado):

  * **Anti-duplicación.** ``explain`` SINTETIZA lo que el builder YA calculó
    (``status``/``summary``/``panel``/``pending``) en prosa. La ÚNICA fuente
    nueva que consume es el ESTADO DE LOTE de ``printflow.stock.health``.
  * **La severidad NO repinta el nodo.** ``severity`` se DERIVA (nunca escribe
    ``node['tone']``): el más grave de (a) el tono del nodo, (b) el estado de
    lote del producto que porta el hito y (c) la presencia de pendientes. La
    paridad del semáforo queda intacta.
  * **Sin N+1.** El ``prep`` del colaborador ``printflow.flow.lots`` calcula EN
    LOTE el estado de lote de TODOS los productos del subárbol (UNA sola pasada,
    memoizado en ``ctx['lot_prep']``) y el bucle del builder lo reutiliza en cada
    nodo. ``_pf_prepare(ctx, strategy)`` se conserva como respaldo histórico.
  * **Textos traducibles.** Todo el microcopy pasa por ``_()`` con placeholders
    ``%s``: cero texto quemado.
  * **``how`` reutiliza el playbook.** Los pasos salen de
    ``printflow.resolution.playbook._pf_get_plan``; si el hito porta un problema
    de LOTE, salen del ``lot_issue`` (colaborador ``printflow.flow.lots``): su
    PRIMER paso es la ETIQUETA del botón que ejecuta la solución.

Contrato::

    prep = ctx['lot_prep']  # printflow.flow.lots._pf_prepare(ctx)
    node['explain'] = env['printflow.flow.explain']._pf_node_explain(
        key, node, ctx, prep, node_failures=..., owner_failure=...,
        node_pending=...)
"""

from odoo import _, api, models

# Tono del semáforo -> severidad base de la explicación.
_TONE_SEVERITY = {
    'ok': 'ok',
    'warn': 'warn',
    'danger': 'danger',
    'na': 'info',
}

# Estado de lote -> severidad (según el plan aprobado).
_LOT_STATE_SEVERITY = {
    'lot_orphan_reservation': 'danger',
    'lot_missing': 'danger',
    'lot_no_stock': 'danger',
    'lot_generic': 'warn',
    'lot_mixed': 'warn',
    'lot_unassigned_finished': 'warn',
    'lot_ok': 'ok',
}

# Ranking para elegir el estado MÁS GRAVE (sin repetir la regla en cada sitio).
_SEVERITY_RANK = {'ok': 0, 'info': 1, 'warn': 2, 'danger': 3}


class PrintflowFlowExplain(models.AbstractModel):
    """Capa de explicación por nodo del canvas de flujo (PrintFlow)."""

    _name = 'printflow.flow.explain'
    _description = 'Capa de explicación del diagrama de flujo (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # PREPARACIÓN EN LOTE (sin N+1)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_prepare(self, ctx, strategy=None):
        """Estado de lote de TODOS los productos del subárbol, en UNA pasada.

        Separa los productos TERMINADOS de los COMPONENTES (según los miembros
        planos del contexto) y calcula el estado de lote en lote con
        ``printflow.stock.health._pf_lot_states_map`` (una sola búsqueda). El
        ``strategy`` se recibe por contrato pero no se necesita aquí.

        :param dict ctx: contexto de flujo normalizado (trae ``members`` y, si
            aplica, ``product``).
        :param strategy: estrategia del caso (no usada; reservada por contrato).
        :rtype: dict
        """
        ctx = ctx or {}
        finished_pids = []
        component_pids = []
        for member in (ctx.get('members') or []):
            if not isinstance(member, dict):
                continue
            pid = member.get('product_id')
            if not pid:
                continue
            if member.get('is_finished'):
                finished_pids.append(pid)
            else:
                component_pids.append(pid)
        product = ctx.get('product')
        if product:
            finished_pids.append(product.id)
        all_pids = sorted(set(finished_pids) | set(component_pids))
        lot_by_pid = {}
        if all_pids:
            products = self.env['product.product'].browse(all_pids).exists()
            if products:
                lot_by_pid = self.env[
                    'printflow.stock.health']._pf_lot_states_map(products)
                # F3: resta de hallazgos AUTORIZADOS (adaptador de GI; motor
                # intacto). Con supresiones vacías, resultado idéntico.
                lot_by_pid = self.env[
                    'printflow.finding.exception.filter']._pf_apply_to_lot_map(
                        products, lot_by_pid)
        return {
            'lot_by_pid': lot_by_pid,
            'finished_pids': sorted(set(finished_pids)),
            'component_pids': sorted(set(component_pids)),
        }

    # ══════════════════════════════════════════════════════════════════════
    # CONTRATO POR NODO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_node_explain(self, key, node, ctx, prep, node_failures=None,
                         owner_failure=None, node_pending=0):
        """Explicación humana de UN nodo del canvas (siempre las 5 claves).

        :param str key: clave del hito (``purchase``, ``stock``, ``delivery``...).
        :param dict node: nodo ya armado por el builder (lee ``label``,
            ``status_label``, ``summary``, ``tone``, ``panel``/``issues``).
        :param dict ctx: contexto de flujo normalizado (no se relee en detalle).
        :param dict prep: resultado de ``_pf_prepare`` (estado de lote en lote).
        :param node_failures: fallas del hito (registro o lista de dicts).
        :param owner_failure: falla "dueña" del hito (registro o dict) con
            ``pf_cause``; gobierna ``how`` cuando no hay problema de lote.
        :param int node_pending: pendientes acumulados del hito.
        :rtype: dict
        """
        node = node or {}
        label = node.get('label') or ''
        status_label = node.get('status_label') or ''
        summary = node.get('summary') or ''
        panel = node.get('panel') or []
        tone = node.get('tone') or 'na'

        severity = _TONE_SEVERITY.get(tone, 'info')
        why = []
        how = []

        # (1) Dimensión de LOTE: la ÚNICA fuente nueva que consume la capa.
        # El ``lot_issue`` lo resuelve el colaborador ``printflow.flow.lots``
        # (una sola pasada en el Builder); aquí solo se CONSUME. El primer paso
        # del "cómo" es la ETIQUETA del botón que ejecuta la solución.
        lot_issue = self.env['printflow.flow.lots']._pf_issue_for_node(
            key, prep)
        lot_state = (lot_issue or {}).get('state') or 'lot_ok'
        if lot_state != 'lot_ok':
            severity = self._pf_worst(
                severity, lot_issue.get('severity')
                or _LOT_STATE_SEVERITY.get(lot_state, 'warn'))
            detail = lot_issue.get('detail') or ''
            why.append(
                _('El lote de este hito tiene un problema: %s') % detail
                if detail else _('El lote de este hito tiene un problema.'))
            how = self._pf_lot_how(lot_issue)

        # (2) Pendientes acumulados del hito.
        if node_pending:
            severity = self._pf_worst(severity, 'warn')
            why.append(
                _('Hay %s documento(s) pendiente(s) en este hito.')
                % node_pending)

        # (3) Causa del hito (playbook) cuando el lote no manda.
        cause = self._pf_owner_failure_cause(owner_failure)
        if not how and cause:
            plan = self.env[
                'printflow.resolution.playbook']._pf_get_plan(cause)
            how = list(plan.get('steps') or [])
            if plan.get('summary'):
                why.append(plan['summary'])

        what = self._pf_what(
            label, status_label, summary, panel, node_failures, node_pending)
        headline = self._pf_headline(
            label, status_label, summary, lot_issue, severity)
        return {
            'headline': headline,
            'what': what,
            'why': why,
            'how': how,
            'severity': severity,
        }

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS (puros)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_worst(self, *severities):
        """La severidad MÁS GRAVE de las dadas (ranking ok < info < warn < danger)."""
        worst = 'ok'
        for severity in severities:
            if (_SEVERITY_RANK.get(severity, 0)
                    > _SEVERITY_RANK.get(worst, 0)):
                worst = severity
        return worst

    @api.model
    def _pf_lot_how(self, lot_issue):
        """Pasos de solución de un problema de lote.

        El PRIMER paso es la ETIQUETA del botón que ejecuta la solución (el
        ``solution`` del ``lot_issue``, ya adaptado por modo); después van los
        pasos del plan del playbook (fuente única).
        """
        plan = (lot_issue or {}).get('plan') or {}
        steps = list(plan.get('steps') or [])
        label = ((lot_issue or {}).get('solution') or {}).get('label') or ''
        return ([label] if label else []) + steps

    @api.model
    def _pf_owner_failure_cause(self, owner_failure):
        """Causa normalizada (``pf_cause``) de la falla dueña (registro o dict)."""
        if owner_failure is None:
            return False
        if isinstance(owner_failure, dict):
            return owner_failure.get('pf_cause') or False
        return owner_failure.pf_cause or False

    @api.model
    def _pf_what(self, label, status_label, summary, panel, node_failures,
                 node_pending):
        """Síntesis en PROSA (2-3 líneas) de lo ya existente en el nodo."""
        parts = []
        if label and status_label:
            parts.append(
                _('El hito «%s» está en estado «%s».') % (label, status_label))
        elif label:
            parts.append(_('Hito «%s».') % label)
        if summary:
            parts.append(summary)
        issues = len(node_failures) if node_failures is not None else len(panel)
        if issues > 1:
            parts.append(
                _('Se detectaron %s hallazgos en este hito.') % issues)
        if node_pending:
            parts.append(
                _('Hay %s documentos pendientes en este hito.') % node_pending)
        return ' '.join(parts)

    @api.model
    def _pf_headline(self, label, status_label, summary, lot_issue, severity):
        """Titular de UNA línea para el nodo."""
        lot_state = (lot_issue or {}).get('state') or 'lot_ok'
        if lot_state != 'lot_ok':
            detail = (lot_issue or {}).get('detail')
            return _('%s: %s') % (
                label, detail or _('problema de lote'))
        if summary:
            return summary
        if severity == 'ok':
            return _('%s: todo correcto') % label
        if status_label:
            return _('%s: %s') % (label, status_label)
        return _('%s: revisar') % label
