# -*- coding: utf-8 -*-
"""Colaborador hoja de INSUMOS del canvas de flujo (PrintFlow).

Servicio ``AbstractModel`` PURO (sin estado ni tabla ⇒ NO lleva fila en
``security/ir.model.access.csv``; igual que ``printflow.flow.lots`` o
``printflow.flow.presentation``) que concentra la dimensión del ALMACÉN DE
INSUMOS del diagrama de flujo. Antes el hito de insumos solo mostraba el token
CRUDO del motor (``over_reserved``) y no ofrecía camino de solución: este
colaborador detecta el problema REAL de los COMPONENTES y aporta la falla
normalizada que habilita la BANDEJA DE INSUMOS.

Por qué existe
--------------
El estado del hito de insumos sale del plegado que hace el estrategia del
producto sobre ``stock_split['supply']`` (peor estado del snapshot de los
componentes de la BOM). Ese estado puede ser un token del snapshot
(``over_reserved``/``physical``/``contention``/``no_route``) que la capa de
presentación traduce (etiqueta humana + tono ``danger``) y que, además, necesita
un CAMINO DE SOLUCIÓN. La detección NO se reinventa: se reutiliza el snapshot del
motor (``printflow.stock.health._pf_inventory_snapshot``) y el clasificador de
remedios (``printflow.stock.remedy``).

Contrato::

    prep = env['printflow.flow.supply']._pf_prepare(ctx)
    issue = env['printflow.flow.supply']._pf_issue_for_node('stock_supply', prep)
    is_supply = env['printflow.flow.supply']._pf_is_supply_cause('supply_issue')
    failure = env['printflow.flow.supply']._pf_failure_dict('stock_supply', issue)
    rows = env['printflow.flow.supply']._pf_supply_rows(flow_product)

Lee de (solo lectura): ``printflow.stock.health._pf_inventory_snapshot`` /
``printflow.stock.remedy._pf_missing_components`` (motor del addon principal) y
``printflow.flow.strategy.product._pf_bom_components`` (componentes de la BOM).
"""

from odoo import _, api, models

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

# Hito del canvas que representa el ALMACÉN DE INSUMOS.
_SUPPLY_NODE_KEY = 'stock_supply'

# Causa normalizada del playbook que gobierna la bandeja de insumos.
SUPPLY_ISSUE_CAUSE = 'supply_issue'

# Tokens CRUDOS del snapshot de inventario (motor) que expresan un problema REAL
# de abastecimiento de un INSUMO. Lista blanca explícita (NUNCA ``getattr``).
_SUPPLY_PROBLEM_STATES = (
    'over_reserved', 'contention', 'physical', 'no_route')

# Token -> severidad del semáforo/plan. Todo problema es ``danger`` (rojo).
_SUPPLY_STATE_SEVERITY = {
    'over_reserved': 'danger',
    'contention': 'danger',
    'physical': 'danger',
    'no_route': 'danger',
    'ok': 'ok',
    'na': 'ok',
}

# Ranking para elegir el estado MÁS GRAVE entre varios insumos del hito.
_SUPPLY_STATE_RANK = {
    'ok': 0, 'na': 0, 'contention': 1, 'over_reserved': 2, 'physical': 3,
    'no_route': 4,
}

# Microcopy corto por token (idioma de operador).
_SUPPLY_STATE_DETAIL = {
    'over_reserved': _(
        'Hay insumos reservados de más: se apartó más de lo que hay en '
        'almacén.'),
    'contention': _(
        'Los insumos existen pero están apartados por otros pedidos.'),
    'physical': _('No hay existencia de los insumos necesarios.'),
    'no_route': _(
        'Los insumos no tienen forma de reponerse (sin ruta ni proveedor).'),
}


class PrintflowFlowSupply(models.AbstractModel):
    """Colaborador hoja de insumos del canvas de flujo (PrintFlow)."""

    _name = 'printflow.flow.supply'
    _description = 'Colaborador de insumos del canvas de flujo (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # PREPARACIÓN (aditiva; solo cuando hay problema REAL)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_prepare(self, ctx):
        """Detecta el problema del ALMACÉN DE INSUMOS de un contexto de flujo.

        Reutiliza el estado ya plegado por la estrategia (``stock_split``
        ``['supply']``) y el ``stock_status`` de cada COMPONENTE (que sale del
        snapshot del motor). Solo arma un ``issue`` cuando el hito está en un
        token de problema, de modo que la inyección de la falla es ADITIVA.

        :param dict ctx: contexto de flujo normalizado (trae ``members`` y
            ``stock_split``).
        :rtype: dict
        """
        ctx = ctx or {}
        component_pids = sorted({
            member.get('product_id')
            for member in (ctx.get('members') or [])
            if (isinstance(member, dict) and not member.get('is_finished')
                and member.get('product_id'))
        })
        supply_state = (
            (ctx.get('stock_split') or {}).get('supply') or 'ok')
        prep = {
            'by_node': {},
            'component_pids': component_pids,
            'state': supply_state,
        }
        if supply_state not in _SUPPLY_PROBLEM_STATES:
            return prep
        states = self._pf_component_states(ctx, component_pids)
        problem = {
            pid: state for pid, state in states.items()
            if state in _SUPPLY_PROBLEM_STATES
        }
        if not problem:
            return prep
        worst_pid = max(
            problem, key=lambda pid: _SUPPLY_STATE_RANK.get(problem[pid], 0))
        worst_state = problem[worst_pid]
        prep['by_node'] = {_SUPPLY_NODE_KEY: {
            'state': worst_state,
            'severity': _SUPPLY_STATE_SEVERITY.get(worst_state, 'danger'),
            'detail': self._pf_detail(worst_state),
            'hito_key': _SUPPLY_NODE_KEY,
            'product_ids': sorted(problem),
            'product_id': worst_pid,
            'status': worst_state,
        }}
        return prep

    @api.model
    def _pf_component_states(self, ctx, component_pids):
        """``pid -> estado`` de los componentes (miembros ya resueltos).

        Si el contexto no trae el estado de cada componente (miembros sin
        ``stock_status``), lo resuelve en LOTE con el snapshot del motor (una
        sola lectura, sin N+1).
        """
        states = {}
        for member in ctx.get('members') or []:
            if not isinstance(member, dict) or member.get('is_finished'):
                continue
            pid = member.get('product_id')
            if pid:
                states[pid] = member.get('stock_status') or 'ok'
        if states or not component_pids:
            return states
        products = self.env['product.product'].browse(component_pids).exists()
        snapshot = self.env[
            'printflow.stock.health']._pf_inventory_snapshot(products)
        return {
            pid: (snapshot.get(pid) or {}).get('state') or 'ok'
            for pid in component_pids
        }

    # ══════════════════════════════════════════════════════════════════════
    # CONTRATO POR HITO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_issue_for_node(self, key, prep):
        """``supply_issue`` que PORTA un hito (o ``None`` si no aplica)."""
        return (prep or {}).get('by_node', {}).get(key)

    @api.model
    def _pf_is_supply_cause(self, cause):
        """¿La causa corresponde al problema de insumos? (lista blanca)."""
        return bool(cause) and cause == SUPPLY_ISSUE_CAUSE

    @api.model
    def _pf_is_supply_state(self, state):
        """¿El estado del hito es un problema de insumos atendible por la bandeja?

        Lista blanca de los tokens del snapshot de componentes: solo estos
        alimentan la bandeja (``deficit``/``no_supply`` se resuelven por otros
        caminos: ajustar/OF).
        """
        return bool(state) and state in _SUPPLY_PROBLEM_STATES

    @api.model
    def _pf_failure_dict(self, key, issue):
        """Falla NORMALIZADA de insumos (shape de falla-dict del PRODUCTO).

        Reutiliza los MISMOS canales de la falla del producto: ``node='stock'`` +
        ``origin_kind='component'`` resuelven el slot de insumos; ``pf_cause``
        (= ``supply_issue``) resuelve el plan y el remedio. Marca ``is_supply``
        para que el cableado de las filas enrute por ``action_run_pf_plan``.
        """
        issue = issue or {}
        return {
            'node': 'stock',
            'severity': issue.get('severity') or 'danger',
            'summary': issue.get('detail') or _('Problema en los insumos'),
            'pf_cause': SUPPLY_ISSUE_CAUSE,
            'origin_kind': 'component',
            'is_supply': True,
            'origin_product_id': issue.get('product_id') or False,
        }

    # ══════════════════════════════════════════════════════════════════════
    # FILAS DE LA BANDEJA (lectura pura; UNA sola lectura de stock.quant)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_supply_rows(self, flow_product):
        """Filas (dicts) de la bandeja: una por INSUMO con problema / almacén.

        Recorre los componentes de la BOM del producto y, para cada uno en un
        token de problema, lista su existencia interna por ubicación (UNA sola
        lectura de ``stock.quant`` para todos). Si el insumo no tiene quants, deja
        UNA fila sintética (sin ubicación) con ceros: evidencia de que no hay
        existencia.

        :param flow_product: ``product.product`` terminado del diagrama.
        :return: lista de dicts con la evidencia por insumo/almacén.
        :rtype: list[dict]
        """
        if not flow_product:
            return []
        components = self.env[
            'printflow.flow.strategy.product']._pf_bom_components(flow_product)
        if not components:
            return []
        Health = self.env['printflow.stock.health']
        Remedy = self.env['printflow.stock.remedy']
        snapshot = Health._pf_inventory_snapshot(components)
        need_qty = self._pf_need_qty(flow_product)
        missing = Remedy._pf_missing_components(flow_product, need_qty)
        need_by_pid = {m['product'].id: m['need'] for m in missing}
        problem = {
            component.id: (snapshot.get(component.id) or {}).get('state') or 'ok'
            for component in components
        }
        problem = {
            pid: state for pid, state in problem.items()
            if state in _SUPPLY_PROBLEM_STATES
        }
        if not problem:
            return []
        quants_by_pid = self._pf_internal_quants(problem)
        presentation = self.env['printflow.flow.presentation']
        rows = []
        for component in components:
            state = problem.get(component.id)
            if not state:
                continue
            need = need_by_pid.get(component.id, 0.0)
            state_label = presentation._pf_node_status_label(
                _SUPPLY_NODE_KEY, state)
            quants = quants_by_pid.get(component.id) or []
            if not quants:
                rows.append(self._pf_row(
                    component, False, 0.0, 0.0, need, state, state_label))
                continue
            for quant in quants:
                rows.append(self._pf_row(
                    component, quant['location_id'], quant['quantity'],
                    quant['reserved_quantity'], need, state, state_label,
                    quant_id=quant['id']))
        return rows

    @api.model
    def _pf_internal_quants(self, problem_pids):
        """Quants internos de los insumos con problema, agrupados por producto.

        UNA sola lectura (``search_read``) para todos los insumos: agrupa en
        memoria para no caer en N+1.
        """
        grouped = {}
        for quant in self.env['stock.quant'].sudo().search_read(
            [('product_id', 'in', list(problem_pids)),
             ('location_id.usage', '=', 'internal')],
            ['product_id', 'location_id', 'quantity', 'reserved_quantity'],
        ):
            pid = quant['product_id'][0]
            grouped.setdefault(pid, []).append(quant)
        return grouped

    @api.model
    def _pf_row(self, component, location_ref, on_hand, reserved, need, state,
                state_label, quant_id=0):
        """Arma UNA fila de la bandeja (evidencia de un insumo/almacén)."""
        location_id = location_ref[0] if location_ref else False
        location_name = location_ref[1] if location_ref else ''
        on_hand = on_hand or 0.0
        reserved = reserved or 0.0
        return {
            'component_id': component.id,
            'component_name': component.display_name,
            'location_id': location_id,
            'location_name': location_name,
            'on_hand': on_hand,
            'reserved': reserved,
            'free': on_hand - reserved,
            'need': need or 0.0,
            'state': state,
            'state_label': state_label,
            'res_model': 'stock.quant' if quant_id else '',
            'res_id': quant_id or 0,
        }

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS (puros)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_detail(self, state):
        """Microcopy corto y humano del token de problema."""
        return _SUPPLY_STATE_DETAIL.get(
            state, _('Hay un problema con el abastecimiento de los insumos.'))

    @api.model
    def _pf_need_qty(self, flow_product):
        """Cantidad a cubrir del terminado (déficit físico; mínimo 1)."""
        if not flow_product:
            return 0.0
        return max(
            0.0,
            (flow_product.outgoing_qty or 0.0)
            - (flow_product.qty_available or 0.0)
            - (flow_product.incoming_qty or 0.0)) or 1.0
