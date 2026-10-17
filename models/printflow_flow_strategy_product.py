# -*- coding: utf-8 -*-
"""Estrategia de flujo del PRODUCTO (sin venta) — PrintFlow · Fase 3.

Adaptador ``printflow.flow.strategy.product`` que traduce el wizard
``printflow.product.flow`` (y su contexto ``_pf_product_canvas_ctx``) al
**contexto de flujo normalizado** que consume el builder del canvas. Hereda la
interfaz ``printflow.flow.strategy`` y aporta SOLO la traducción del caso
producto (dicts del veredicto del motor).

Se EXTRAJO del wizard de producto y del servicio ``printflow.flow.canvas``
(Fase 3 del refactor OOP, ``docs/plan_fases_orquestador_oop_v2.md``) **SIN cambiar
comportamiento**: ``_pf_product_canvas_ctx`` y sus helpers de contexto
(``_pf_product_members``, ``_pf_bom_components`` y los gemelos ``_pf_product_*``
basados en dicts) se movieron TAL CUAL. El wizard y el canvas conservan
DELEGADORES con la MISMA firma.

Nota de alcance (Fases 3-4): las fallas del producto siguen siendo DICTS y las
del pedido REGISTROS; la normalización a un shape único es de una fase posterior.
El Builder ÚNICO (``printflow.flow.payload.builder``) consume este contexto y
resuelve el vocabulario por caso mediante los hooks de esta estrategia.
"""

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_LABELS,
    PF_CHAIN_SLOTS,
    PF_NODE_TO_SLOT,
)

_EPS = 1e-6

# Inversa de ``PF_NODE_TO_SLOT``: el SLOT de canvas (``inventory``) vuelve al
# nodo CAUSAL del motor (``stock``), que es la clave de ``PF_CHAIN_LABELS``. Se
# usa SOLO para rotular la cadena de fallas del producto (mismo vocabulario del
# pedido) sin duplicar etiquetas.
_PF_SLOT_TO_CHAIN_NODE = {
    slot: node for node, slot in PF_NODE_TO_SLOT.items()}


class PrintflowFlowStrategyProduct(models.AbstractModel):
    """Estrategia del caso PRODUCTO (sin venta)."""

    _name = 'printflow.flow.strategy.product'
    _inherit = 'printflow.flow.strategy'
    _description = 'Estrategia de flujo del producto (PrintFlow)'

    @api.model
    def _pf_flow_case(self):
        return 'product'

    # ══════════════════════════════════════════════════════════════════════
    # CONTEXTO NORMALIZADO DEL PRODUCTO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_flow_context(self, host):
        """Contexto de flujo del PRODUCTO (envuelve ``_pf_product_canvas_ctx``).

        Reutiliza el motor unificado ``printflow.product.flow.diagnostic``
        (``_pf_flow_verdict``) para los estados de hito; NO reimplementa reglas.
        Añade las piezas derivadas (eje, slots, roles, raíz del canvas y
        políticas del caso) para que el builder no lea el host directo.
        """
        host.ensure_one()
        product = host.product_id
        if not product:
            base = {
                'flow_type': 'purchase', 'statuses': {}, 'members': [],
                'stock_split': {'supply': 'ok', 'finished': 'ok'},
                'pending_by_key': {}, 'severity': 'ok',
                'root_cause_node': False, 'chain_summary': '',
                'product': False, 'failures': [], 'cause': False,
                'remedy_key': False, 'playbook_ctx': {},
                'mode': 'product', 'has_order': False, 'lot_prep': {},
                'shortfall_by_key': {},
            }
            return self._pf_with_derived(base, host)

        engine = self.env['printflow.order.health.engine']
        remedy = self.env['printflow.stock.remedy']
        flow = self.env['printflow.product.flow.diagnostic']

        deficit = max(
            0.0,
            (product.outgoing_qty or 0.0)
            - (product.qty_available or 0.0)
            - (product.incoming_qty or 0.0),
        )
        over_reserved = product.id in engine._pf_over_reserved_products(
            [product.id])
        anomaly = product.id in engine._pf_reservation_anomaly_products(
            [product.id])
        # Fabricabilidad por la FUENTE ÚNICA del motor (misma que el pedido y el
        # tablero): BoM o ruta de fabricación.
        manufacturable = product.id in engine._pf_manufacturable_products(
            product)
        physical_remedy = (
            remedy._pf_physical_remedy_key(product, deficit)
            if deficit > _EPS else False)
        # Señales REALES de la Orden de Fabricación del producto (D1): se leen en
        # UNA sola pasada y se clasifican con el helper del motor (nunca se
        # reinventa la clasificación). Así el nodo FABRICACIÓN refleja la OF viva
        # en vez de quedar ciego ("No aplica" con OF en curso).
        mos = self._pf_product_mos(product)
        mo_without_materials = engine._pf_mo_without_materials(mos['non_done'])
        # Compuertas sin venta (D2): sin etapa de pedido el borrador de OF ES un
        # "sin lanzar" real (in_production_stage=True); sin venta no hay entrega
        # (in_delivery_stage=False), así un fabricable SIN OF queda ``na`` y nunca
        # dispara el falso "sin orden". NO se pasa producción_alert/cobertura/
        # retraso/arte (D2/D3/D4): sin fuente fiable por producto.
        verdict = flow._pf_flow_verdict({
            'product_id': product.id,
            'is_finished': True,
            'sale_status': 'na',
            'purchase_ok': product.purchase_ok,
            'incoming_qty': product.incoming_qty,
            'deficit_qty': deficit,
            'in_over_reserved': over_reserved,
            'reservation_anomaly': anomaly,
            'is_manufacturable': manufacturable,
            'active_mos': mos['non_done'],
            'done_mos': mos['done'],
            'has_draft_mo': bool(mos['draft']),
            'mo_without_materials': mo_without_materials,
            'in_production_stage': True,
            'in_delivery_stage': False,
            'physical_remedy': physical_remedy,
        })

        flow_type = 'manufacture' if manufacturable else 'purchase'
        statuses = {
            'purchase': verdict.get('purchase_status') or 'na',
            'delivery': 'na',
            'customer': 'ok',
        }
        members = self._pf_product_members(product, manufacturable, verdict)
        stock_split = engine._pf_flow_stock_split(members)
        if flow_type == 'manufacture':
            statuses['production'] = verdict.get('production_status') or 'na'
            statuses['stock_supply'] = stock_split.get('supply') or 'ok'
            statuses['stock_finished'] = stock_split.get('finished') or 'ok'
        else:
            statuses['stock'] = verdict.get('stock_status') or 'na'

        pending_by_key = self.env[
            'printflow.flow.pending']._pf_node_pending_map(
                product).get(product.id, {})
        # Recepción = señal PROPIA (D6): se deriva de las recepciones REALES
        # (albaranes de entrada abiertos), NO del proxy de ``purchase_status``.
        # Si el producto es FABRICABLE, además de las del terminado se cuentan
        # las de los INSUMOS de su BOM (D4), para saber si "falta validar la
        # recepción de un componente". Albaranes distintos: sin doble conteo.
        if manufacturable:
            components = self._pf_bom_components(product)
            if components:
                receipt_count = self.env[
                    'printflow.flow.pending']._pf_receipt_pending_distinct(
                        [product.id] + components.ids)
                if receipt_count:
                    pending_by_key['receipt'] = receipt_count
                else:
                    pending_by_key.pop('receipt', None)
        # ``na`` (no ``ok``/"Recibido") cuando no hay recepción abierta: evita una
        # lectura extra de albaranes ``done`` y preserva el candado del producto.
        statuses['receipt'] = (
            'pending' if pending_by_key.get('receipt') else 'na')
        # Naturaleza de la traba SIN recalcular reglas: se deriva de las banderas
        # ya resueltas arriba (precedencia física > contención > anomalía).
        reservation_nature = (
            'physical' if deficit > _EPS
            else 'contention' if over_reserved
            else 'anomaly' if anomaly
            else 'ok')
        playbook_ctx = {
            'product': product,
            'has_bom': remedy._pf_has_bom(product),
            'is_manufacturable': manufacturable,
            'is_purchasable': remedy._pf_is_purchasable(product),
            'deficit_qty': deficit,
            'reservation_nature': reservation_nature,
        }
        # FALTANTE REAL de Compras (D1): del déficit FÍSICO se resta la cobertura
        # de OC SIN CONFIRMAR que apuntan a pedidos con entrega pendiente del
        # producto (lo ya pedido y por confirmar). Sin OC sin confirmar la
        # cobertura es 0 y el faltante == déficit (candados intactos). El déficit
        # crudo se CONSERVA intacto (Inventario/veredicto lo usan como magnitud).
        cover = self.env[
            'printflow.flow.pending']._pf_purchase_unconfirmed_cover(
                [product.id]).get(product.id, 0.0)
        shortfall = max(0.0, deficit - cover)
        base = {
            'flow_type': flow_type,
            'statuses': statuses,
            'members': members,
            'stock_split': stock_split,
            'pending_by_key': pending_by_key,
            'severity': verdict.get('severity') or 'ok',
            'root_cause_node': verdict.get('root_cause_node') or False,
            'chain_summary': '',
            'product': product,
            'failures': verdict.get('failures') or [],
            'cause': verdict.get('cause') or False,
            'remedy_key': verdict.get('remedy_key') or False,
            'playbook_ctx': playbook_ctx,
            # Contexto NORMALIZADO para el playbook (microcopy sin "el pedido").
            'mode': 'product',
            'has_order': False,
            # Magnitud del FALTANTE de Compras (D1/D4): el faltante REAL
            # (déficit − OC sin confirmar), NUNCA de un caso concreto. Solo se
            # llena el nodo ``purchase`` cuando está ``missing`` (faltante > 0).
            'shortfall_by_key': (
                {'purchase': shortfall}
                if (statuses.get('purchase') == 'missing'
                    and shortfall > _EPS)
                else {}),
        }
        # Dimensión de LOTE (colaborador hoja): calcula el prep UNA sola vez,
        # inyecta la falla normalizada por hito y deriva el ``status`` del nodo
        # (semáforo) SOLO cuando el hito no tiene estado propio.
        # Dimensión de INSUMOS (colaborador hoja): ADITIVA, solo aporta falla
        # cuando el hito de insumos tiene un problema REAL (no repinta status).
        base['failures'] = (
            list(base['failures'])
            + self._pf_lot_failures(base)
            + self._pf_supply_failures(base))
        return self._pf_with_derived(base, host)

    @api.model
    def _pf_with_derived(self, ctx, host):
        """Añade al contexto base las piezas DERIVADAS que consume el builder."""
        presentation = self.env['printflow.flow.presentation']
        flow_type = ctx.get('flow_type') or 'purchase'
        axis = list(presentation._PF_AXIS_ORDER[flow_type])
        members = ctx.get('members') or []
        failures = ctx.get('failures') or []
        key_by_slot = self._pf_key_by_slot(axis)
        slot_failures = self._pf_slot_failures_from_dicts(failures)
        broken_slots = self._pf_product_broken_slots(
            axis, ctx.get('statuses') or {}, slot_failures)
        root_slot = PF_NODE_TO_SLOT.get(ctx.get('root_cause_node') or '')
        roles, parents = self._pf_slot_chain_roles(broken_slots, root_slot)
        root_label_node = ctx.get('root_cause_node') or ''
        # P1 · CADENA INVERTIDA (D1): si la ENTREGA reservó sin lote y deja la
        # reserva COLGADA en el inventario, son la MISMA falla ⇒ la raíz pasa a
        # ser la Entrega (aguas arriba del hecho) y el Inventario su
        # consecuencia. Solo se acopla cuando coexisten AMBAS señales
        # (``_pf_lot_coupled_roles``); si no, ``roles``/``parents``/raíz quedan
        # EXACTAMENTE como hoy. Sin claves nuevas en el payload.
        coupled = self._pf_lot_coupled_roles(
            roles, ctx.get('statuses') or {}, slot_failures)
        if coupled is not roles:
            roles = coupled
            parents = dict(parents)
            parents['inventory'] = 'delivery'
            root_slot = 'delivery'
            root_label_node = 'delivery'
        root_canvas_key = key_by_slot.get(root_slot) if root_slot else None
        ctx.update({
            'case': self._pf_flow_case(),
            'host': host,
            'has_focus': bool(ctx.get('product')),
            # Política de RENDER del caso producto: el diagrama SIEMPRE pinta
            # estados/acciones (a diferencia del pedido, que sin foco es SEGURO).
            'focus': True,
            # Nodo del rótulo de ``root_link`` (normalizado: el producto cae a '').
            'root_label_node': root_label_node,
            'axis': axis,
            'anomaly_keys': self._pf_anomaly_node_keys_from_members(
                flow_type, members),
            'key_by_slot': key_by_slot,
            'slot_failures': slot_failures,
            'broken_slots': broken_slots,
            'root_slot': root_slot,
            'roles': roles,
            'parents': parents,
            'root_canvas_key': root_canvas_key,
            'hosted': self._pf_product_hosted_failures(
                failures, axis, key_by_slot),
            'external_failure_ids': set(),
            'context_failure': None,
            'pending_delivery_count': 0,
            'owner_policy': 'first',
            'host_fallback_policy': 'axis0',
        })
        # Cadena de fallas del producto (D5): se deriva de los roles recién
        # calculados (mismo formato/vocabulario del pedido). Con la raíz ya
        # resuelta, deja de ser una cadena vacía cuando hay fallas encadenadas.
        ctx['chain_summary'] = self._pf_product_chain_summary(ctx)
        return ctx

    # ══════════════════════════════════════════════════════════════════════
    # DIMENSIÓN DE LOTE (colaborador hoja ``printflow.flow.lots``)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_lot_failures(self, ctx):
        """Inyecta la falla NORMALIZADA de lote y deriva el ``status`` del hito.

        Override del hook del contrato (solo el PRODUCTO inyecta): el PEDIDO
        conserva su fila del motor sin duplicar. Calcula el ``lot_prep`` UNA vez
        (memoizado en ``ctx['lot_prep']`` para el Builder/explain), y por cada
        hito que porta un ``lot_issue``: (a) si el hito NO tiene estado propio
        (``na``) le fija el ``status`` de lote (semáforo vía ``status``, nunca
        repintando el tone) y (b) aporta la falla-dict que habilita el botón.
        """
        presentation = self.env['printflow.flow.presentation']
        lots = self.env['printflow.flow.lots']
        flow_type = ctx.get('flow_type') or 'purchase'
        axis = list(presentation._PF_AXIS_ORDER[flow_type])
        lot_prep = lots._pf_prepare(ctx)
        ctx['lot_prep'] = lot_prep
        statuses = ctx.get('statuses') or {}
        failures = []
        for key in axis:
            issue = lots._pf_issue_for_node(key, lot_prep)
            if not issue:
                continue
            if not statuses.get(key) or statuses.get(key) == 'na':
                statuses[key] = issue.get('status') or 'na'
            failures.append(lots._pf_failure_dict(key, issue))
        return failures

    @api.model
    def _pf_lot_coupling_active(self, slot_failures):
        """¿Entrega "sin lote" e Inventario "reserva colgada" son la MISMA falla?

        Condición ESTRICTA (D1), SIN lecturas nuevas: coexisten (a) el estado de
        lote ``lot_missing`` (movimiento de salida SIN lote asignado) en el slot
        ``delivery`` y (b) la falla ``data_anomaly`` (reserva colgada) en el slot
        ``inventory``. Cuando el producto mezcla AMBAS señales, la entrega que
        reservó sin lote dejó el reservado colgado en el inventario: es UN MISMO
        hecho con dos superficies de resolución. Si cualquiera de las dos falta,
        NO se acopla (el comportamiento actual queda intacto).

        :param dict slot_failures: mapa ``slot -> [falla-dict]`` (ya leído).
        :rtype: bool
        """
        delivery = (slot_failures or {}).get('delivery') or []
        inventory = (slot_failures or {}).get('inventory') or []
        has_missing = any(
            failure.get('pf_cause') == 'lot_missing' for failure in delivery)
        has_anomaly = any(
            failure.get('pf_cause') == 'data_anomaly' for failure in inventory)
        return has_missing and has_anomaly

    @api.model
    def _pf_lot_coupled_roles(self, roles, statuses, slot_failures):
        """Roles con la cadena INVERTIDA cuando Entrega e Inventario son UNA.

        La cadena causal ``PF_CHAIN_SLOTS`` va compras → … → inventario →
        entrega; aquí la RAÍZ es la ENTREGA (reservó sin lote) y la CONSECUENCIA
        es el INVENTARIO (reserva colgada), es decir, al revés. Como
        ``_pf_slot_chain_roles`` solo marca ``consequence`` a los slots
        POSTERIORES a la raíz, un acoplamiento invertido quedaría como dos fallas
        ``independiente`` (sin cadena raíz→consecuencia). Este helper DEVUELVE
        una copia de ``roles`` con ``delivery='root'`` e ``inventory='consequence'``
        SOLO cuando el acoplamiento está activo (``_pf_lot_coupling_active``);
        si no, devuelve ``roles`` SIN tocar (misma referencia: permite al
        llamador detectar el no-op).

        :param dict roles: roles ya calculados por ``_pf_slot_chain_roles``.
        :param dict statuses: estados por hito (semáforo) del contexto.
        :param dict slot_failures: mapa ``slot -> [falla-dict]``.
        :rtype: dict
        """
        if not self._pf_lot_coupling_active(slot_failures):
            return roles
        coupled = dict(roles)
        coupled['delivery'] = 'root'
        coupled['inventory'] = 'consequence'
        return coupled

    # ══════════════════════════════════════════════════════════════════════
    # DIMENSIÓN DE INSUMOS (colaborador hoja ``printflow.flow.supply``)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_supply_failures(self, ctx):
        """Inyecta la falla NORMALIZADA de INSUMOS (colaborador hoja).

        Gemelo de ``_pf_lot_failures`` pero ADITIVO: solo aporta falla cuando el
        hito del ALMACÉN DE INSUMOS tiene un problema REAL. El ``status`` del
        hito ya lo plegó ``stock_split['supply']`` (semáforo por ``status``,
        nunca repintando el ``tone``); aquí solo se agrega la falla que habilita
        el botón "Solucionar" y su bandeja. El ``prep`` se memoiza en
        ``ctx['supply_prep']`` para que el resto del armado no lo recalcule.
        """
        supply = self.env['printflow.flow.supply']
        prep = supply._pf_prepare(ctx)
        ctx['supply_prep'] = prep
        failures = []
        presentation = self.env['printflow.flow.presentation']
        flow_type = ctx.get('flow_type') or 'purchase'
        for key in presentation._PF_AXIS_ORDER[flow_type]:
            issue = supply._pf_issue_for_node(key, prep)
            if not issue:
                continue
            failures.append(supply._pf_failure_dict(key, issue))
        return failures

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS DE CONTEXTO DEL PRODUCTO (movidos TAL CUAL)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_product_failure_slot(self, failure):
        """Slot de canvas de una FALLA en DICT (presentación pura)."""
        return self.env[
            'printflow.flow.presentation']._pf_product_failure_slot(failure)

    @api.model
    def _pf_slot_failures_from_dicts(self, failures):
        """Agrupa las fallas en DICT por slot (gemelo de ``_pf_slot_failures``)."""
        grouped = {}
        for failure in failures or []:
            slot = self._pf_product_failure_slot(failure)
            if not slot:
                continue
            grouped.setdefault(slot, []).append(failure)
        return grouped

    @api.model
    def _pf_product_hosted_failures(self, failures, axis, key_by_slot):
        """Reparte cada falla dict en UN SOLO hito del eje (gemelo del pedido)."""
        hosted = {key: [] for key in axis}
        for failure in failures or []:
            slot = self._pf_product_failure_slot(failure)
            host_key = key_by_slot.get(slot) or axis[0]
            hosted[host_key].append(failure)
        return hosted

    @api.model
    def _pf_product_broken_slots(self, axis, statuses, slot_failures):
        """Slots con novedad para un PRODUCTO (delega en el helper compartido)."""
        return self._pf_broken_slots(axis, statuses, slot_failures)

    @api.model
    def _pf_product_node_owner_failure(self, node_failures):
        """Falla 'dueña' de un hito del producto (la primera del nodo)."""
        return node_failures[0] if node_failures else None

    # ── Overrides del contrato (política del caso producto) ──────────────
    @api.model
    def _pf_node_owner_failure(self, node_failures):
        """Delta ``owner_policy='first'``: falla 'dueña' = la PRIMERA del nodo.

        El pedido usa ``min_rank`` (raíz si existe; si no, menor ``rank``). Este
        override lo aplica el Builder a través de la estrategia, sin ramificar por
        caso.
        """
        return node_failures[0] if node_failures else None

    @api.model
    def _pf_node_summary(self, node_failures, owner_failure=None):
        """Resumen corto del problema (falla dueña = primera del nodo)."""
        owner = owner_failure
        if owner is None:
            owner = self._pf_product_node_owner_failure(node_failures)
        if owner is None:
            return '', 0
        return owner.get('summary') or '', max(0, len(node_failures) - 1)

    @api.model
    def _pf_product_members(self, product, manufacturable, verdict):
        """Miembros planos del producto (terminado + componentes de su BOM).

        El terminado aporta su ``stock_status``; los componentes (una nivel de
        BOM) aportan el suyo para el hito "Almacén insumos". Una sola lectura de
        inventario por lote (``_pf_inventory_snapshot``), sin N+1.
        """
        members = [{
            'is_finished': True,
            'product_id': product.id,
            'stock_status': verdict.get('stock_status') or 'ok',
        }]
        if not manufacturable:
            return members
        components = self._pf_bom_components(product)
        if not components:
            return members
        snapshot = self.env[
            'printflow.stock.health']._pf_inventory_snapshot(components)
        for component in components:
            members.append({
                'is_finished': False,
                'product_id': component.id,
                'stock_status': (
                    snapshot.get(component.id) or {}).get('state') or 'ok',
            })
        return members

    @api.model
    def _pf_product_mos(self, product):
        """OF reales del producto (sin cancelar) clasificadas por el motor (D1).

        Lectura de SOLO LECTURA en UNA sola pasada (``search`` por producto) y
        clasificación REUTILIZADA (``engine._pf_classify_mos``): nunca se
        reinventa el criterio. Sin OF devuelve los tres baldes vacíos.

        :param product.product product: producto a inspeccionar.
        :rtype: dict ``{'non_done': [...], 'draft': [...], 'done': [...]}``.
        """
        engine = self.env['printflow.order.health.engine']
        if not product:
            return {'non_done': [], 'draft': [], 'done': []}
        mos = self.env['mrp.production'].sudo().search([
            ('product_id', '=', product.id),
            ('state', '!=', 'cancel'),
        ])
        return engine._pf_classify_mos(mos)

    @api.model
    def _pf_product_chain_summary(self, ctx):
        """Resume la cadena raíz -> consecuencias del producto (D5).

        Deriva de lo YA calculado en el contexto (``roles`` por slot y la raíz):
        NO lee registros de pedido ni reimplementa la cadena. Reproduce el MISMO
        formato del pedido (``canvas._pf_chain_summary``): ``Etiqueta (origen) →
        Etiqueta (consecuencia)``, con la RAÍZ primero y el resto por
        ``PF_CHAIN_SLOTS``, y deduplicado por nodo causal.

        El orden raíz→consecuencia (no solo por ``PF_CHAIN_SLOTS``) es necesario
        para la cadena INVERTIDA del acoplamiento de lote (D1), donde la raíz
        (Entrega) es POSTERIOR a su consecuencia (Inventario) en el orden causal
        del canvas: sin él, la franja empezaría por la consecuencia.

        :param dict ctx: contexto de flujo (con ``roles`` ya resuelto).
        :rtype: str
        """
        roles = ctx.get('roles') or {}
        if not roles:
            return ''
        seen = set()
        parts = []
        for wanted in ('root', 'consequence'):
            for slot in PF_CHAIN_SLOTS:
                if roles.get(slot) != wanted:
                    continue
                node = _PF_SLOT_TO_CHAIN_NODE.get(slot, slot)
                if node in seen:
                    continue
                seen.add(node)
                label = PF_CHAIN_LABELS.get(node, node or '')
                suffix = _('origen') if wanted == 'root' else _('consecuencia')
                parts.append('%s (%s)' % (label, suffix))
        return ' → '.join(parts)

    # ══════════════════════════════════════════════════════════════════════
    # HOOKS DE PRESENTACIÓN DEL PRODUCTO (vocabulario del caso; Fase 4)
    #
    # Movidos TAL CUAL desde ``printflow.flow.canvas`` (los métodos homónimos
    # quedan allí como delegadores). El Builder único los invoca a través de la
    # estrategia; el vocabulario NO se unifica entre pedido y producto.
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_node_actions(self, host, node_key, owner_failure=None, role='none',
                         status=None, is_root=False, context_failure=None,
                         anomaly=False, pending=0, context=None):
        """Acciones del popover de un hito del producto (reutiliza los servicios).

        Conserva "Abrir listado" y "Abrir producto" y agrega las acciones ricas
        del pedido (Solucionar, Ver el problema, Comprar producto/componentes,
        Fabricar, Recibir mercancía, Ajustar inventario, Liberar y re-reservar,
        Sanear reservas, Ver quién me bloquea, Salud de inventario, Recopilar,
        Ver pendientes), resueltas por métodos PÚBLICOS del wizard. El plan del
        playbook se reutiliza para "Solucionar"/"Ver el problema".
        """
        actions = []
        presentation = self.env['printflow.flow.presentation']
        is_consequence = role == 'consequence'
        playbook_ctx = (context or {}).get('playbook_ctx') or {}
        owner = owner_failure

        def add(key, label, method='action_run_pf_node', args=None,
                kind='navigate', primary=False, sublabel=None, enabled=True):
            if is_consequence and kind == 'run_action':
                return
            actions.append(self._pf_action(
                key, label, kind=kind, res_model=host._name, res_id=host.id,
                method=method, enabled=enabled, args=args, primary=primary,
                sublabel=sublabel))

        # Solución / problema del hito a partir del plan del playbook.
        if owner is not None:
            cause = owner.get('pf_cause')
            plan = self._pf_product_plan(cause, playbook_ctx)
            plan_actions = (plan or {}).get('actions') or {}
            problem = plan_actions.get('problem') or {}
            # El botón "Solucionar" vive SOLO en la FILA del panel (no en el
            # nodo): así el hallazgo ofrece UNA sola entrada y la corrección se
            # gestiona desde la bandeja que abre esa fila.
            if problem.get('available'):
                add('problem', problem.get('label') or _('Ver el problema'),
                    method='action_run_pf_plan', args=[cause, 'problem'])

        if node_key in presentation._PF_PENDING_ACTION_KEYS:
            add('open_list', _('Abrir listado'),
                method='action_open_node_pending', args=[node_key])
        if node_key == 'purchase':
            add('buy_product', _('Comprar producto'), args=['buy_product'])
            add('buy_components', _('Comprar componentes'),
                args=['buy_components'])
            add('view_purchase', _('Ver OC sin confirmar'),
                args=['purchase_orders'])
        elif node_key == 'receipt':
            add('receive', _('RECIBIR MERCANCÍA'), args=['receipt'])
        elif node_key in ('stock', 'stock_supply', 'stock_finished'):
            add('quants', _('Ver existencias'), args=['quants'])
            add('adjust', _('Ajustar inventario'), args=['adjust'])
            if self._pf_can_clean_reservations():
                add('fix_reservation', _('Liberar y re-reservar'),
                    args=['fix_reservation'], kind='run_action')
                if anomaly:
                    add('cleanup_reservations', _('Sanear reservas colgadas'),
                        args=['cleanup_reservations'], kind='run_action')
            add('blocking', _('Ver quién me bloquea'), args=['blocking'])
            if node_key == 'stock_supply':
                add('fabricate', _('Ir a la Orden de Fabricación'),
                    args=['fabricate'])
                # Bandeja gestionable de insumos: solo con un token de problema
                # que la bandeja atiende (reserva de más / sin existencia /
                # apartado por otros / sin forma de reponer).
                if self.env[
                        'printflow.flow.supply']._pf_is_supply_state(status):
                    add('fix_supply', _('Solucionar los insumos'),
                        args=['fix_supply'])
        elif node_key == 'production':
            add('fabricate', _('Ir a la Orden de Fabricación'),
                args=['fabricate'])
        elif node_key == 'delivery':
            add('delivery_orders', _('Ver órdenes pendientes'),
                args=['delivery_orders'])
        if (pending and node_key != 'delivery'
                and node_key in presentation._PF_PENDING_ACTION_KEYS):
            add('pending', _('Ver pendientes (%s)') % pending,
                method='action_open_node_pending', args=[node_key])
        add('open_product', _('Abrir producto'), method='action_open_product')
        if is_root:
            add('collect', _('Recopilar'),
                method='action_open_collect_causante')
            add('inventory_health', _('Salud de inventario'),
                args=['inventory_health'])
        return actions

    @api.model
    def _pf_node_panel(self, host, node_failures, roles_by_slot, context):
        """Detalle del popover de un hito: una fila por falla.

        Gemelo de ``printflow.flow.strategy.order._pf_node_panel``, pero armado
        con DICTS: usa ``pf_cause`` + ``printflow.resolution.playbook`` para el
        plan y el microcopy. Las acciones de cada fila se cablean al wizard
        ``printflow.product.flow``.
        """
        playbook_ctx = (context or {}).get('playbook_ctx') or {}
        rows = []
        for index, failure in enumerate(node_failures):
            slot = self._pf_product_failure_slot(failure)
            role = roles_by_slot.get(slot, 'none')
            is_consequence = role == 'consequence'
            plan = self._pf_product_plan(failure.get('pf_cause'), playbook_ctx)
            plan_actions = (plan or {}).get('actions') or {}
            problem = plan_actions.get('problem') or {}
            solution = plan_actions.get('solution') or {}
            collect = plan_actions.get('collect') or {}
            rows.append(self.env['printflow.flow.actions']._pf_panel_row({
                'failure_id': index + 1,
                'label': PF_CHAIN_LABELS.get(
                    failure.get('node'), failure.get('node') or ''),
                'detail': failure.get('summary') or '',
                'origin': '',
                'origin_kind': failure.get('origin_kind') or '',
                'chain_note': (
                    _('Depende de la raíz de la cadena')
                    if is_consequence else ''),
                'plan_summary': plan['summary'] if plan else '',
                'role': role,
                'tone': self.env[
                    'printflow.flow.presentation']._pf_severity_tone(
                        failure.get('severity')),
                'is_consequence': is_consequence,
                'problem_available': bool(problem.get('available')),
                'solution_available': bool(
                    solution.get('available') and not is_consequence),
                'collect_available': bool(
                    collect.get('available') and not is_consequence),
                'actions': self._pf_product_failure_row_actions(
                    failure, plan, host, is_consequence),
            }))
        return rows

    @api.model
    def _pf_product_failure_row_actions(
            self, failure, plan, host, is_consequence):
        """Acciones POR FILA del panel, cableadas a ``printflow.product.flow``.

        Se expone el destino del plan como CLAVE de la lista blanca del wizard
        (``action_run_pf_node``), para que el frontend nunca invoque un método
        privado ni la falla de un pedido. Las filas de LOTE (``is_lot``) se
        enrutan por el dispatcher público ``action_run_pf_plan`` con la CAUSA
        (= estado de lote), porque su solución ya viene ADAPTADA por modo.
        """
        actions = []
        if not plan:
            return actions
        plan_actions = plan.get('actions') or {}
        problem = plan_actions.get('problem') or {}
        solution = plan_actions.get('solution') or {}
        is_lot = bool(failure.get('is_lot'))
        is_supply = bool(failure.get('is_supply'))
        cause = failure.get('pf_cause')
        # Causa con FALLA GUIADA registrada (p. ej. ``data_anomaly``): su
        # "Solucionar" abre la bandeja de decisión por ``action_run_pf_plan``,
        # igual que lote/insumos, en vez del one-click del nodo.
        is_registered = bool(cause) and cause in self.env[
            'printflow.flow.failure.registry']._pf_supported()
        if solution.get('available') and not is_consequence:
            if is_lot or is_registered:
                actions.append(self._pf_action(
                    'solution', _('Solucionar'), kind='navigate',
                    res_model=host._name, res_id=host.id,
                    method='action_run_pf_plan',
                    args=[cause, 'solution', failure.get('origin_product_id')],
                    primary=True, sublabel=solution.get('label') or ''))
            elif is_supply:
                # Bandeja gestionable de INSUMOS: el dispatcher abre la bandeja
                # (la solución se decide allí: traslado/compra/ajuste).
                actions.append(self._pf_action(
                    'solution', _('Solucionar'), kind='navigate',
                    res_model=host._name, res_id=host.id,
                    method='action_run_pf_plan',
                    args=[cause, 'solution'],
                    primary=True, sublabel=solution.get('label') or ''))
            else:
                node_key = self._pf_plan_action_to_node_key(
                    solution.get('kind'), solution.get('target'))
                actions.append(self._pf_action(
                    'solution', _('Solucionar'), kind='navigate',
                    res_model=host._name, res_id=host.id,
                    method='action_run_pf_node', args=[node_key], primary=True,
                    sublabel=solution.get('label') or ''))
        if problem.get('available'):
            if is_lot:
                actions.append(self._pf_action(
                    'problem', problem.get('label') or _('Ver el problema'),
                    kind='navigate', res_model=host._name, res_id=host.id,
                    method='action_run_pf_plan', args=[cause, 'problem']))
            elif is_supply:
                actions.append(self._pf_action(
                    'problem', problem.get('label') or _('Ver el problema'),
                    kind='navigate', res_model=host._name, res_id=host.id,
                    method='action_run_pf_plan', args=[cause, 'problem']))
            else:
                node_key = self._pf_plan_action_to_node_key(
                    problem.get('kind'), problem.get('target'))
                actions.append(self._pf_action(
                    'problem', problem.get('label') or _('Ver el problema'),
                    kind='navigate', res_model=host._name, res_id=host.id,
                    method='action_run_pf_node', args=[node_key]))
        return actions

    @api.model
    def _pf_root_tray(self, host, context, owner_failure=None):
        """Filas del tray del nodo raíz del producto (misma forma del pedido).

        Describe registros existentes (producto, BOM, MO, OC y entregas que lo
        reservan) para la Bandeja de Resolución: la lista solo NAVEGA, no
        escribe. El tope por tipo sale de configuración (cero hardcodeo).
        """
        product = (context or {}).get('product')
        if not product:
            return []
        limit = self._pf_product_tray_limit()
        rows = [self.env['printflow.flow.actions']._pf_tray_row({
            'label': _('Producto: %s') % product.display_name,
            'detail': _('Ficha del producto'),
            'ref_name': product.display_name,
            'state_label': '',
            'res_model': 'product.product',
            'res_id': product.id,
        })]
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        if bom:
            rows.append(self.env['printflow.flow.actions']._pf_tray_row({
                'label': _('Lista de materiales'),
                'detail': bom.display_name,
                'ref_name': bom.display_name,
                'state_label': self._pf_selection_label(bom, 'type'),
                'res_model': 'mrp.bom',
                'res_id': bom.id,
            }))
        mos = self.env['mrp.production'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
        ], limit=limit, order='date_start asc, id asc')
        for mo in mos:
            rows.append(self.env['printflow.flow.actions']._pf_tray_row({
                'label': _('Orden de fabricación %s') % mo.name,
                'detail': product.display_name,
                'ref_name': mo.name,
                'state_label': self._pf_selection_label(mo, 'state'),
                'res_model': 'mrp.production',
                'res_id': mo.id,
            }))
        order_lines = self.env['purchase.order.line'].sudo().search([
            ('product_id', '=', product.id),
            ('order_id.state', 'in', self.env[
                'printflow.flow.pending']._pf_purchase_unconfirmed_states()),
        ], limit=limit, order='id asc')
        for po in order_lines.mapped('order_id'):
            rows.append(self.env['printflow.flow.actions']._pf_tray_row({
                'label': _('Orden de compra %s') % po.name,
                'detail': po.partner_id.display_name,
                'ref_name': po.name,
                'state_label': self._pf_selection_label(po, 'state'),
                'res_model': 'purchase.order',
                'res_id': po.id,
            }))
        pickings = self.env['stock.picking'].sudo().search([
            ('state', 'not in', ('done', 'cancel')),
            ('picking_type_id.code', '=', 'outgoing'),
            ('move_line_ids.product_id', '=', product.id),
            ('move_line_ids.state', 'not in', ('done', 'cancel')),
            ('move_line_ids.quantity', '>', 0),
            ('move_line_ids.location_id.usage', '=', 'internal'),
        ], limit=limit, order='scheduled_date asc, id asc')
        for picking in pickings:
            rows.append(self.env['printflow.flow.actions']._pf_tray_row({
                'label': _('Entrega %s') % picking.name,
                'detail': picking.partner_id.display_name,
                'ref_name': picking.name,
                'state_label': self._pf_selection_label(picking, 'state'),
                'res_model': 'stock.picking',
                'res_id': picking.id,
            }))
        return rows

    @api.model
    def _pf_product_plan(self, cause, playbook_ctx):
        """Plan del playbook para una causa del producto (o ``None``).

        Las causas de LOTE se enrutan por el colaborador ``printflow.flow.lots``:
        su plan trae la acción ADAPTADA al modo producto (sustituto navegable o
        remedio seguro), sin ejecutar el ``replace_generic_lot`` que exige pedido.
        """
        if not cause:
            return None
        lots = self.env['printflow.flow.lots']
        if lots._pf_is_lot_cause(cause):
            return lots._pf_plan_for_state(cause, 'product')
        return self.env['printflow.resolution.playbook']._pf_get_plan(
            cause, ctx=playbook_ctx or {})

    @api.model
    def _pf_plan_action_to_node_key(self, kind, target):
        """Traduce un destino del playbook a la CLAVE del popover del producto."""
        presentation = self.env['printflow.flow.presentation']
        if kind in (False, 'none'):
            return 'product'
        return presentation._PF_PLAN_TARGET_TO_NODE_KEY.get(
            target or '', 'product')

    @api.model
    def _pf_selection_label(self, record, field_name='state'):
        """Etiqueta legible de un campo Selection (o su valor crudo)."""
        field = record._fields.get(field_name)
        selection = getattr(field, 'selection', None)
        if not selection:
            return ''
        return dict(selection).get(record[field_name], record[field_name] or '')

    @api.model
    def _pf_product_tray_limit(self):
        """Tope de filas por tipo del tray del producto (0 = sin tope)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'x_product_dimensional_pricing.pf_product_tray_limit', '5')
        try:
            return int(raw or 0) or None
        except (TypeError, ValueError):
            return 5
