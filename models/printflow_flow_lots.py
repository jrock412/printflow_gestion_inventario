# -*- coding: utf-8 -*-
"""Colaborador hoja de LOTES del canvas de flujo (PrintFlow · Bloque V).

Servicio ``AbstractModel`` PURO (sin estado ni tabla ⇒ NO lleva fila en
``security/ir.model.access.csv``; igual que ``printflow.flow.presentation`` o
``printflow.flow.actions``) que concentra la dimensión de LOTE del diagrama de
flujo. Antes vivía privada en la capa de explicación (solo-texto) y su acción se
descartaba: por eso el PRODUCTO mostraba el problema pero no ofrecía el botón
que lo resuelve.

Por qué existe
--------------
El lote deja de ser un cálculo privado de ``printflow.flow.explain`` y pasa a
ser una PIEZA COMPARTIDA. Resuelve en UNA sola pasada un ``lot_issue`` por hito
(el estado de lote de TODOS los productos del subárbol con
``printflow.stock.health._pf_lot_states_map``) y ese mismo objeto alimenta las
TRES zonas del panel: ``summary``/``panel``/``actions``/``explain``. La
estrategia del PRODUCTO inyecta su "falla normalizada" en ``hosted``/``failures``
para que las zonas EXISTENTES la consuman por los canales ya probados.

Contrato::

    prep = env['printflow.flow.lots']._pf_prepare(ctx)
    issue = env['printflow.flow.lots']._pf_issue_for_node(key, prep)
    status = env['printflow.flow.lots']._pf_lot_canvas_status(lot_state)
    plan = env['printflow.flow.lots']._pf_plan_for_state(lot_state, mode)
    failure = env['printflow.flow.lots']._pf_failure_dict(key, issue)

Lee de (solo lectura): ``LOT_REMEDY_BY_STATE`` + ``stock.remedy._pf_remedy_meta``
(motor del addon principal), ``stock.health._pf_lot_states_map`` /
``_pf_lot_detail`` y ``printflow.resolution.playbook._pf_get_plan``.

Regla transversal: TODO remedio que ESCRIBE pasa por el guardia de permisos
``printflow.stock.remedy._pf_assert_can_clean()`` (jefe de taller/admin). Este
colaborador solo PREPARA la acción: la ejecuta el wizard (con su guardia).
"""

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_stock_remedy import (  # noqa: E501
    LOT_REMEDY_BY_STATE,
)

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

# ── Selector de lote por DOCUMENTO (decisión consciente del operador) ────
# Clave del parámetro de configuración (cero hardcodeo). Conserva el namespace
# del addon principal para no requerir migración de datos (cero escritura); la
# siembra vive en este addon (``data/ir_config_parameter_data.xml``).
PARAM_LOT_ASSIGN_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')

# Política ante una asignación de lote que NO es el lote propio del documento.
EXCEPTION_POLICY_SELECTION = [
    ('warn', _('Solo avisar')),
    ('confirm', _('Exigir confirmación')),
    ('confirm_reason', _('Exigir confirmación y motivo (por defecto)')),
]
DEFAULT_EXCEPTION_POLICY = 'confirm_reason'

# Hitos que portan el lote del producto TERMINADO del subárbol (mismo criterio
# que la capa de explicación: fabricación, almacén terminado y entrega).
_FINISHED_LOT_KEYS = ('production', 'stock_finished', 'delivery')
# Hito que porta el lote de los COMPONENTES (almacén de insumos).
_SUPPLY_LOT_KEYS = ('stock_supply',)

# Estado de lote -> severidad del semáforo/plan.
_LOT_STATE_SEVERITY = {
    'lot_orphan_reservation': 'danger',
    'lot_missing': 'danger',
    'lot_no_stock': 'danger',
    'lot_generic': 'warn',
    'lot_mixed': 'warn',
    'lot_unassigned_finished': 'warn',
    'lot_ok': 'ok',
}

# Ranking para elegir el estado MÁS GRAVE entre varios productos del hito.
_SEVERITY_RANK = {'ok': 0, 'info': 1, 'warn': 2, 'danger': 3}

# Estado de lote -> estado CRUDO del nodo (semáforo por ``status``, NUNCA por
# repintado del tone desde explain). Solo se aplica en el PRODUCTO.
_LOT_CANVAS_STATUS = {
    'lot_orphan_reservation': 'lot_no_stock',
    'lot_missing': 'lot_no_stock',
    'lot_no_stock': 'lot_no_stock',
    'lot_generic': 'lot_generic',
    'lot_mixed': 'lot_generic',
    'lot_unassigned_finished': 'lot_generic',
}

# Hito del canvas -> nodo CAUSAL que cobija su falla (para el reparto por slot).
# El almacén de insumos viaja con ``stock`` + ``origin_kind='component'``.
_LOT_NODE_BY_KEY = {
    'purchase': 'purchase',
    'receipt': 'receipt',
    'stock': 'stock',
    'stock_supply': 'stock',
    'stock_finished': 'stock',
    'production': 'production',
    'delivery': 'delivery',
    'customer': 'delivery',
}

# Remedio SIN venta por estado de lote (caso PRODUCTO). El mapa declara
# ``(kind, target, label)`` de la acción del hito y usa SOLO remedios que NO
# exigen pedido (los mismos helpers de ``printflow.stock.health`` que ejecuta el
# wizard): ``reconcile_lot_reservation`` (``_pf_reassign_by_lot``),
# ``separate_lots`` (``_pf_replace_generic_lot`` es no-op sin venta +
# ``_pf_reassign_by_lot``), ``assign_lot`` y ``repair_finished_lot``
# (``_pf_repair_finished_lot``: crea/recupera el lote exclusivo del terminado;
# también funciona sin venta). Ya NO hay sustitutos navegables:
# el "Solucionar" de la fila abre la BANDEJA gestionable de lote, donde el
# operador ve lo afectado y ejecuta el remedio sobre la selección.
# Se indexa por ESTADO (no por remedio) porque varios estados comparten remedio
# pero llevan microcopy distinto.
LOT_PRODUCT_FALLBACK = {
    'lot_orphan_reservation': (
        'run_action', 'reconcile_lot_reservation',
        _('Reconciliar la reserva de lote')),
    'lot_missing': (
        'run_action', 'assign_lot', _('Asignar un lote con existencia')),
    'lot_no_stock': (
        'run_action', 'reconcile_lot_reservation',
        _('Reconciliar la reserva de lote')),
    'lot_generic': (
        'run_action', 'separate_lots', _('Separar los lotes mezclados')),
    'lot_mixed': (
        'run_action', 'reconcile_lot_reservation',
        _('Reasignar reservas por lote')),
    'lot_unassigned_finished': (
        'run_action', 'repair_finished_lot',
        _('Reparar el lote del terminado')),
}


class PrintflowFlowLots(models.AbstractModel):
    """Colaborador hoja de lotes del canvas de flujo (PrintFlow)."""

    _name = 'printflow.flow.lots'
    _description = 'Colaborador de lotes del canvas de flujo (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # PREPARACIÓN EN LOTE (una sola pasada, sin N+1)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_prepare(self, ctx):
        """Estado de lote de TODOS los productos del subárbol, en UNA pasada.

        Separa los productos TERMINADOS de los COMPONENTES (según los miembros
        planos del contexto) y calcula el estado de lote en bloque con
        ``printflow.stock.health._pf_lot_states_map`` (una sola búsqueda). Luego
        resuelve UN ``lot_issue`` por hito candidato y lo deja en ``by_node`` para
        que el Builder y los hooks NO recalculen.

        :param dict ctx: contexto de flujo normalizado (trae ``members``,
            ``product``, ``mode`` y ``has_order``).
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
                # F3: el adaptador de GI resta los hallazgos AUTORIZADOS antes de
                # pintar (el motor NO se toca). Con supresiones vacías, sin cambios.
                lot_by_pid = self.env[
                    'printflow.finding.exception.filter']._pf_apply_to_lot_map(
                        products, lot_by_pid)
        prep = {
            'by_pid': lot_by_pid,
            'by_node': {},
            'finished_pids': sorted(set(finished_pids)),
            'component_pids': sorted(set(component_pids)),
            # Extras internos: viajan en el prep (NUNCA en el payload) para que
            # ``_pf_issue_for_node`` adapte el plan por modo sin tocar el ctx.
            'mode': ctx.get('mode') or 'product',
            'has_order': bool(ctx.get('has_order')),
        }
        by_node = {}
        for key in _FINISHED_LOT_KEYS + _SUPPLY_LOT_KEYS:
            issue = self._pf_issue_from_key(key, prep)
            if issue:
                by_node[key] = issue
        prep['by_node'] = by_node
        return prep

    # ══════════════════════════════════════════════════════════════════════
    # CONTRATO POR HITO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_issue_for_node(self, key, prep):
        """``lot_issue`` que PORTA un hito (o ``None`` si no aplica).

        Si el ``prep`` viene del colaborador (trae ``by_node``) solo consulta el
        mapa. Si viene del ``prep`` HISTÓRICO de la explicación (``lot_by_pid`` +
        ``finished_pids``/``component_pids``) lo reconstruye al vuelo, para
        conservar el contrato de los llamadores/tests previos.
        """
        prep = prep or {}
        by_node = prep.get('by_node')
        if by_node is not None:
            return by_node.get(key)
        return self._pf_issue_from_key(key, prep)

    @api.model
    def _pf_lot_canvas_status(self, lot_state):
        """Estado CRUDO del nodo que expresa la severidad del lote (semáforo)."""
        return _LOT_CANVAS_STATUS.get(lot_state or '', lot_state or 'na')

    @api.model
    def _pf_plan_for_state(self, lot_state, mode):
        """Plan del playbook de un estado de lote, con la acción ADAPTADA al modo.

        En el PEDIDO (``mode='order'``) la acción del hito es el REMEDIO del
        ``LOT_REMEDY_BY_STATE`` (idéntico al botón del diagnóstico). En el
        PRODUCTO (sin venta) se sustituye por el remedio SIN pedido de
        ``LOT_PRODUCT_FALLBACK`` (siempre ``run_action``): el "Solucionar" de la
        fila abre la bandeja gestionable y allí se ejecuta sobre la selección.
        """
        mode = mode or 'product'
        ctx = {'has_order': mode == 'order', 'mode': mode}
        plan = self.env['printflow.resolution.playbook']._pf_get_plan(
            lot_state, ctx=ctx)
        remedy_key = LOT_REMEDY_BY_STATE.get(lot_state)
        if remedy_key:
            label, kind, target = self.env[
                'printflow.stock.remedy']._pf_remedy_meta(remedy_key)
        else:
            label, kind, target = '', 'none', ''
        if mode == 'order':
            action = (kind, target, label)
        else:
            action = LOT_PRODUCT_FALLBACK.get(
                lot_state, (kind, target, label))
        return self._pf_apply_action(plan, action)

    @api.model
    def _pf_failure_dict(self, key, lot_issue):
        """Falla NORMALIZADA de lote (shape de falla-dict del PRODUCTO).

        Reutiliza los MISMOS canales de la falla del producto: ``node`` +
        ``origin_kind`` resuelven el slot; ``pf_cause`` (= estado de lote)
        resuelve el plan y el remedio. Marca ``is_lot`` para que el cableado de
        las filas enrute por ``action_run_pf_plan``.
        """
        node = _LOT_NODE_BY_KEY.get(key, key)
        origin_kind = 'component' if key == 'stock_supply' else ''
        return {
            'node': node,
            'severity': lot_issue.get('severity') or 'warn',
            'summary': lot_issue.get('detail') or _('Problema de lote'),
            'pf_cause': lot_issue.get('state'),
            'origin_kind': origin_kind,
            'is_lot': True,
            'origin_product_id': lot_issue.get('product_id') or False,
        }

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS (puros)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_is_lot_cause(self, cause):
        """¿La causa corresponde a un estado de lote conocido? (lista blanca)."""
        return bool(cause) and cause in LOT_REMEDY_BY_STATE

    @api.model
    def _pf_expected_exclusive_lot_name(self, lot_info):
        """Lote EXCLUSIVO esperado del pedido para los movimientos SIN lote.

        La entrega que reserva sin lote debe tomar el lote EXCLUSIVO de su pedido
        (``SXXXXX-Lyyyy``); su nombre se DERIVA con el helper EXISTENTE del motor
        (``sale.order.line._get_exclusive_lot_name``), NUNCA se inventa. Se lee
        de los movimientos YA identificados en ``missing_move_ids`` (los mismos
        que el motor listó ⇒ SIN lecturas nuevas ni N+1). Devuelve ``''`` cuando
        NO es determinable (producto suelto, sin línea de venta o sin nombre de
        pedido), para que el texto quede NEUTRO (no miente).

        :param dict lot_info: estado de lote del motor (con ``missing_move_ids``).
        :rtype: str
        """
        move_ids = [
            mid for mid in (lot_info.get('missing_move_ids') or []) if mid]
        if not move_ids:
            return ''
        moves = self.env['stock.move'].sudo().browse(move_ids).exists()
        for move in moves:
            line = move.sale_line_id
            if not line:
                continue
            name = line._get_exclusive_lot_name()
            if name:
                return name
        return ''

    # ══════════════════════════════════════════════════════════════════════
    # CANDIDATOS A ASIGNAR (lectura pura; UNA sola lectura de stock.quant)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_available_lots(self, product, exclude_lot_ids=None,
                           location_id=None, demand_qty=None,
                           include_lot_ids=None):
        """Lotes del producto con existencia interna real (ver cantidades).

        Colaborador HOJA y de SOLO LECTURA: alimenta el selector de lote por
        documento (``printflow.flow.lot.picker``). Hace UNA sola lectura de
        ``stock.quant`` (agrupa por lote en memoria, sin N+1), descarta los lotes
        sin existencia disponible NI reserva y ordena por disponible descendente.

        Reglas de cantidad (petición explícita del negocio):

        * ``available``/``available_here`` = ``cantidad - max(reservado, 0)``: una
          reserva NEGATIVA NO infla el libre (es una anomalía, no disponibilidad);
        * ``reserved`` se informa acotado a ``>= 0`` (sin negativos);
        * se EXCLUYEN los quants fantasma (``físico <= 0`` y ``reservado < 0``);
        * un lote con ``libre == 0`` pero ``reservado > 0`` NO desaparece: se lista
          como OCUPADO (``is_occupied``) con quién lo retiene (``holder_names``),
          pero NO es elegible (``available_here == 0``).

        :param product: ``product.product`` del que se listan los lotes.
        :param list exclude_lot_ids: ids de lote a excluir.
        :param location_id: ubicación del documento (id o ``stock.location``).
        :param float demand_qty: demanda del documento (para ``covers_demand``).
        :param list include_lot_ids: ids de lote que se listan SIEMPRE, aunque
            tengan 0 existencia (available=0, available_here=0): sirve para que
            el lote PROPIO y el ACTUAL aparezcan aunque no tengan stock. Con
            ``None`` el camino por defecto queda IDÉNTICO (sin consultas extra).
        :return: lista de dicts ``{lot_id, lot_name, qty_on_hand, available,
            available_here, covers_demand, reserved, location_names, is_generic,
            is_occupied, holder_names}``. ``qty_on_hand`` es la cantidad FÍSICA
            total del lote (suma de quants internos).
        :rtype: list[dict]
        """
        if not product:
            return []
        exclude = set(exclude_lot_ids or [])
        include = [
            lot_id for lot_id in (include_lot_ids or [])
            if lot_id and lot_id not in exclude]
        include_set = set(include)
        here_ids = self._pf_location_subtree_ids(location_id)
        demand = demand_qty or 0.0
        totals = {}
        # ÚNICA lectura: quants internos del producto (una fila por lote/ubicación).
        for quant in self.env['stock.quant'].sudo().search_read(
            [('product_id', '=', product.id),
             ('location_id.usage', '=', 'internal')],
            ['lot_id', 'quantity', 'reserved_quantity', 'location_id'],
        ):
            lot_ref = quant['lot_id']
            if not lot_ref:
                continue
            lot_id = lot_ref[0]
            if lot_id in exclude:
                continue
            qty = quant['quantity'] or 0.0
            res = quant['reserved_quantity'] or 0.0
            # Quant FANTASMA (sin físico y con reserva negativa): no listarlo.
            if qty <= _EPS and res < -_EPS:
                continue
            entry = totals.setdefault(lot_id, {
                'lot_id': lot_id,
                'lot_name': lot_ref[1],
                'qty_on_hand': 0.0,
                'available': 0.0,
                'available_here': 0.0,
                'reserved': 0.0,
                'locations': set(),
            })
            # Existencia FÍSICA total (independiente de reservas).
            entry['qty_on_hand'] += qty
            # Libre real: la reserva negativa NO suma disponibilidad.
            free = qty - max(res, 0.0)
            entry['available'] += free
            entry['reserved'] += max(res, 0.0)
            loc_ref = quant['location_id']
            if loc_ref:
                entry['locations'].add(loc_ref[1])
            # Libre EN la ubicación del documento (o total si no se indicó una).
            if here_ids is None or (loc_ref and loc_ref[0] in here_ids):
                entry['available_here'] += free
        # Lotes FORZADOS (lote propio/actual): se listan AUNQUE no tengan quant,
        # con ceros, para que el operador SIEMPRE los vea. Solo cuando el
        # llamador los pide (camino por defecto intacto: sin consultas extra).
        if include:
            for included_lot in self.env['stock.lot'].sudo().browse(
                    include).exists():
                totals.setdefault(included_lot.id, {
                    'lot_id': included_lot.id,
                    'lot_name': included_lot.name,
                    'qty_on_hand': 0.0,
                    'available': 0.0,
                    'available_here': 0.0,
                    'reserved': 0.0,
                    'locations': set(),
                })
        # Precarga de nombres en UNA lectura: ``_pf_lot_is_generic`` lee ``name``.
        lots = self.env['stock.lot'].sudo().browse(list(totals.keys())).exists()
        lots.mapped('name')
        # Quién retiene cada lote (documentos/pedidos que hoy lo reservan): UNA
        # sola lectura agregada; alimenta la columna "Lo retiene".
        holders = self._pf_lot_holders(product, list(totals.keys()))
        Health = self.env['printflow.stock.health']
        result = []
        for lot in lots:
            entry = totals.get(lot.id)
            if not entry:
                continue
            available = entry['available']
            # Se descarta solo lo que NI libre NI reserva tiene. Los lotes
            # OCUPADOS (libre 0, reservado > 0) se conservan para informar, y los
            # FORZADOS (lote propio/actual) SIEMPRE se listan.
            if (available <= _EPS and entry['reserved'] <= _EPS
                    and lot.id not in include_set):
                continue
            available_here = entry['available_here']
            result.append({
                'lot_id': lot.id,
                'lot_name': lot.name,
                'qty_on_hand': entry['qty_on_hand'],
                'available': available,
                'available_here': available_here,
                'covers_demand': bool(
                    demand <= _EPS or available_here >= demand - _EPS),
                'reserved': entry['reserved'],
                'location_names': ', '.join(sorted(entry['locations'])),
                'is_generic': Health._pf_lot_is_generic(lot),
                'is_occupied': bool(
                    available <= _EPS and entry['reserved'] > _EPS),
                'holder_names': ', '.join(holders.get(lot.id) or []),
            })
        result.sort(key=lambda cand: cand['available'], reverse=True)
        return result

    @api.model
    def _pf_lot_holders(self, product, lot_ids):
        """Quién RESERVA hoy cada lote (documentos/pedidos), en UNA lectura.

        Devuelve ``{lot_id: [etiquetas de documento ordenadas]}`` a partir de las
        ``stock.move.line`` activas internas del producto con esos lotes. Sirve
        para informar al operador "quién lo retiene" en el selector. Lectura pura.
        :rtype: dict[int, list[str]]
        """
        lot_ids = [lot_id for lot_id in (lot_ids or []) if lot_id]
        if not product or not lot_ids:
            return {}
        holders = {}
        for line in self.env['stock.move.line'].sudo().search_read([
            ('product_id', '=', product.id),
            ('lot_id', 'in', lot_ids),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', _EPS),
            ('location_id.usage', '=', 'internal'),
        ], ['lot_id', 'picking_id', 'move_id']):
            lot_ref = line.get('lot_id')
            if not lot_ref:
                continue
            picking_ref = line.get('picking_id')
            move_ref = line.get('move_id')
            label = (picking_ref[1] if picking_ref
                     else (move_ref[1] if move_ref else ''))
            bucket = holders.setdefault(lot_ref[0], set())
            if label:
                bucket.add(label)
        return {
            lot_id: sorted(labels)
            for lot_id, labels in holders.items()
        }

    @api.model
    def _pf_location_subtree_ids(self, location_id):
        """Ids de la ubicación y su subárbol (o ``None`` si no se indicó).

        Réplica barata del criterio de ``_get_available_quantity`` (que por
        defecto incluye hijas). UNA sola búsqueda; sin ubicación devuelve
        ``None`` para no agregar consultas al camino por defecto.
        :rtype: set[int] | None
        """
        if not location_id:
            return None
        ident = location_id.id if hasattr(location_id, 'id') else location_id
        location = self.env['stock.location'].sudo().browse(ident).exists()
        if not location:
            return None
        return set(self.env['stock.location'].sudo().search(
            [('id', 'child_of', location.id)]).ids)

    @api.model
    def _pf_issue_from_key(self, key, prep):
        """Construye el ``lot_issue`` de un hito a partir del ``prep``."""
        lot_info = self._pf_best_lot_info(key, prep)
        if not lot_info:
            return None
        return self._pf_issue_from_lot_info(key, lot_info, prep)

    @api.model
    def _pf_best_lot_info(self, key, prep):
        """Estado de lote MÁS GRAVE que porta el hito (o ``None``)."""
        if key not in _FINISHED_LOT_KEYS and key not in _SUPPLY_LOT_KEYS:
            return None
        by_pid = prep.get('by_pid') or prep.get('lot_by_pid') or {}
        if key in _FINISHED_LOT_KEYS:
            pids = prep.get('finished_pids') or []
        else:
            pids = prep.get('component_pids') or []
        infos = [by_pid.get(pid) for pid in pids if by_pid.get(pid)]
        if not infos:
            return None
        return max(
            infos,
            key=lambda info: _SEVERITY_RANK.get(
                _LOT_STATE_SEVERITY.get(
                    (info or {}).get('state') or 'lot_ok', 'ok'),
                0))

    @api.model
    def _pf_issue_from_lot_info(self, key, lot_info, prep):
        """Arma el ``lot_issue`` (forma interna, NO viaja cruda en el payload)."""
        state = lot_info.get('state') or 'lot_ok'
        if state == 'lot_ok':
            return None
        mode = prep.get('mode') or (
            'order' if prep.get('has_order') else 'product')
        plan = self._pf_plan_for_state(state, mode)
        actions = plan.get('actions') or {}
        product = lot_info.get('product')
        detail = self.env['printflow.stock.health']._pf_lot_detail(lot_info)
        # P1 · CAUSA RAÍZ explícita (D1): en la entrega SIN lote se nombra el
        # lote EXCLUSIVO esperado del pedido, para que el operador sepa QUÉ lote
        # falta (p. ej. ``S03275-L5356``). Solo caso PRODUCTO (paridad del pedido
        # intacta) y solo si es determinable; si no, el detalle queda neutro.
        if key == 'delivery' and state == 'lot_missing' and mode == 'product':
            expected = self._pf_expected_exclusive_lot_name(lot_info)
            if expected:
                detail = _('%s; se espera el lote exclusivo del pedido %s') % (
                    detail, expected)
        return {
            'state': state,
            'severity': _LOT_STATE_SEVERITY.get(state, 'warn'),
            'detail': detail,
            'hito_key': key,
            'product_id': product.id if product else False,
            'plan': plan,
            'solution': dict(actions.get('solution') or {}),
            'problem': dict(actions.get('problem') or {}),
            'status': self._pf_lot_canvas_status(state),
        }

    @api.model
    def _pf_apply_action(self, plan, action):
        """Sustituye la acción ``solution`` del plan por la del hito.

        ``action`` es ``(kind, target, label)``. Si el destino del problema
        coincide con el de la solución, apaga el problema (mismo criterio del
        playbook): el hallazgo ofrece UN botón.
        """
        kind, target, label = action
        kind = kind or 'none'
        actions = dict(plan.get('actions') or {})
        solution = dict(actions.get('solution') or {})
        solution.update({
            'label': label or '',
            'kind': kind,
            'target': target or '',
            'available': kind != 'none',
        })
        actions['solution'] = solution
        problem = dict(actions.get('problem') or {})
        if (problem.get('kind'), problem.get('target')) == (
                solution['kind'], solution['target']):
            problem['available'] = False
        actions['problem'] = problem
        new_plan = dict(plan)
        new_plan['actions'] = actions
        # ALIAS deprecados: siguen a la solución efectiva del hito.
        new_plan['action_label'] = solution['label']
        new_plan['action_kind'] = solution['kind']
        new_plan['target'] = solution['target']
        return new_plan
