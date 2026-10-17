# -*- coding: utf-8 -*-
"""INTERFAZ (contrato) de las estrategias del canvas de flujo (PrintFlow).

Servicio ``AbstractModel`` sin tabla que define el **contrato común** que
consumen los constructores del canvas (``printflow.flow.canvas``): producir el
**contexto de flujo normalizado** del host (``_pf_flow_context``) y exponer los
**hooks de caso** de presentación de acciones/panel/tray.

Es la pieza que separa "traducir la fuente" (estrategia) de "armar el payload"
(builder). Los adaptadores concretos son:

  * ``printflow.flow.strategy.order``   -> host PEDIDO (con venta).
  * ``printflow.flow.strategy.product`` -> host PRODUCTO (sin venta).

Reglas de diseño (Fase 3 del refactor OOP,
``docs/plan_fases_orquestador_oop_v2.md``):

  * Esta base NO conoce pedido ni producto: solo declara el contrato y aporta los
    helpers COMPARTIDOS (geometría de slots, roles de cadena, anomalías por
    miembro y selección de la falla "dueña") que dependen únicamente de
    ``printflow.flow.presentation`` y del motor de salud.
  * Los adaptadores la heredan con ``_inherit`` y aportan **solo** su traducción
    de fuente. El motor de reglas NO se toca: la estrategia solo da FORMA a lo
    que el motor ya decidió.
  * Los hooks de acciones/panel/tray se declaran aquí (contrato) y su
    vocabulario se implementa **por caso** (nunca unificado): el Builder futuro
    no ramifica por caso concreto.

Contrato::

    ctx = env['printflow.flow.strategy.order']._pf_flow_context(host)   # o .product
    ctx['statuses'] / ctx['members'] / ctx['failures'] / ...
"""

from odoo import api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_SLOTS,
)


class PrintflowFlowStrategy(models.AbstractModel):
    """Contrato común de las estrategias del canvas de flujo."""

    _name = 'printflow.flow.strategy'
    _description = 'Interfaz de estrategia del canvas de flujo (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # CONTRATO (lo implementa cada adaptador)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_flow_case(self):
        """Etiqueta del caso de flujo (``'order'`` / ``'product'``)."""
        raise NotImplementedError

    @api.model
    def _pf_flow_context(self, host):
        """Contexto de flujo NORMALIZADO del ``host`` (contrato abstracto).

        :param host: registro que expone los datos de la fuente por duck typing
            (wizard de pedido o ``printflow.product.flow``).
        :return: dict con la forma documentada en el diseño (§A.3). La estrategia
            del caso concreto es quien la llena.
        """
        raise NotImplementedError

    # ── Hooks de presentación por caso (contrato; default vacío) ─────────
    @api.model
    def _pf_node_actions(self, host, node_key, owner_failure=None, role='none',
                         status=None, is_root=False, context_failure=None,
                         anomaly=False, pending=0, context=None):
        """Acciones del popover de un hito (vocabulario POR estrategia).

        ``context`` es el contexto de flujo normalizado: el pedido resuelve sus
        acciones por la falla ANFITRIONA (``owner_failure``) y el producto por el
        ``playbook_ctx`` del contexto. El Builder lo pasa SIEMPRE; los adaptadores
        ignoran lo que no necesiten.
        """
        return []

    @api.model
    def _pf_node_panel(self, host, node_failures, roles_by_slot, context):
        """Filas del panel de un hito (vocabulario POR estrategia)."""
        return []

    @api.model
    def _pf_root_tray(self, host, context, owner_failure=None):
        """Filas del tray del nodo raíz (vocabulario POR estrategia)."""
        return []

    # ── Hook de LOTES (contrato; default vacío) ──────────────────────────
    @api.model
    def _pf_lot_failures(self, context):
        """Fallas NORMALIZADAS de lote que el caso INYECTA al ``hosted``.

        Default vacío: el PEDIDO NO inyecta lote (su fila ya nace de la falla del
        motor y una segunda fila la duplicaría). El PRODUCTO lo sobreescribe para
        derivar el ``status`` del hito y aportar la falla-dict que habilita el
        botón "Solucionar" por los canales existentes.
        """
        return []

    # ── Hooks de contenido por caso (contrato; default genérico) ─────────
    @api.model
    def _pf_empty_node_failures(self):
        """Contenedor VACÍO de fallas del caso (registro o dict según adaptador).

        El Builder lo usa como respaldo cuando un hito no tiene fallas. Los dos
        adaptadores usan un contenedor distinto; por defecto, una lista vacía.
        """
        return []

    @api.model
    def _pf_node_summary(self, node_failures, owner_failure=None):
        """Resumen corto ``(texto, extras)`` de una tarjeta del hito.

        Por defecto (pedido) lee ``summary`` del registro dueño; el adaptador de
        producto lo sobreescribe para leer el dict del veredicto.
        """
        if owner_failure is None:
            return '', 0
        return owner_failure.summary or '', max(0, len(node_failures) - 1)

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS COMPARTIDOS (caso-agnósticos; dependen de presentation/engine)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_action(self, key, label, kind='navigate', failure_id=None,
                   res_model=None, res_id=None, method=None, enabled=True,
                   target_key=None, args=None, primary=False, sublabel=None):
        """Delegador del contrato de acción del popover (kit de acciones)."""
        return self.env['printflow.flow.actions']._pf_action(
            key, label, kind=kind, failure_id=failure_id, res_model=res_model,
            res_id=res_id, method=method, enabled=enabled,
            target_key=target_key, args=args, primary=primary,
            sublabel=sublabel)

    @api.model
    def _pf_can_clean_reservations(self):
        """¿El usuario puede sanear reservas? (mismos grupos que la vista)."""
        actions = self.env['printflow.flow.actions']
        user = self.env.user
        return any(
            user.has_group(xmlid)
            for xmlid in actions._PF_CLEAN_GROUP_XMLIDS)

    @api.model
    def _pf_key_by_slot(self, axis):
        """Hito PRINCIPAL del eje que representa cada slot del canvas."""
        return self.env['printflow.flow.presentation']._pf_key_by_slot(axis)

    @api.model
    def _pf_bom_components(self, product):
        """Productos de las líneas de la BOM aplicable al producto (o vacío).

        Helper COMPARTIDO caso-agnóstico (D4): lo usan tanto la estrategia del
        producto (miembros de insumos) como la del pedido (expansión del nodo
        Recepción a los insumos). SOLO lee la BOM aplicable, sin escribir nada.
        """
        if not product:
            return self.env['product.product']
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        if not bom:
            return self.env['product.product']
        return bom.bom_line_ids.product_id

    @api.model
    def _pf_slot_chain_roles(self, broken_slots, root_slot):
        """Rol/padre por SLOT de canvas (raíz = hito más aguas arriba)."""
        engine = self.env['printflow.order.health.engine']
        steps = engine._pf_chain_steps(
            broken_slots, root_slot, order=PF_CHAIN_SLOTS)
        roles = {}
        parents = {}
        for slot, step in steps.items():
            roles[slot] = step['role']
            if step['role'] == 'consequence':
                parents[slot] = step['parent']
        return roles, parents

    @api.model
    def _pf_broken_slots(self, axis, statuses, slot_failures):
        """Slots con novedad (falla propia o semáforo danger/warn).

        Se OMITE ``receipt`` en la detección por tono (D6): su semáforo comparte
        el slot ``purchase`` con el nodo Compras, y su nueva señal propia ("por
        recibir") NO debe abrir cadena por sí sola (la cadena causal la deciden
        Compras/Inventario/Fabricación). Igual que ya se omite ``customer``.
        """
        presentation = self.env['printflow.flow.presentation']
        slots = set(slot_failures)
        for key in axis:
            if key in ('customer', 'receipt'):
                continue
            tone = presentation._pf_node_tone(key, statuses.get(key))
            if tone in ('danger', 'warn'):
                slots.add(presentation._PF_NODE_META[key]['chain'])
        return slots

    @api.model
    def _pf_anomaly_node_keys_from_members(self, flow_type, members):
        """Anomalías por hito a partir de miembros planos ``{product_id,...}``."""
        presentation = self.env['printflow.flow.presentation']
        product_ids = [
            member.get('product_id') for member in (members or [])
            if member.get('product_id')
        ]
        if not product_ids:
            return set()
        anomaly_ids = self.env[
            'printflow.stock.remedy']._pf_negative_quant_product_ids(
                product_ids)
        if not anomaly_ids:
            return set()
        axis = list(presentation._PF_AXIS_ORDER[flow_type])
        key_by_slot = self._pf_key_by_slot(axis)
        finished_anomaly = False
        supply_anomaly = False
        for member in members:
            if member.get('product_id') not in anomaly_ids:
                continue
            if member.get('is_finished'):
                finished_anomaly = True
            else:
                supply_anomaly = True
        keys = set()
        inventory_key = key_by_slot.get('inventory')
        if finished_anomaly and inventory_key:
            keys.add(inventory_key)
        supply_key = key_by_slot.get('supply')
        if supply_anomaly:
            if supply_key:
                keys.add(supply_key)
            elif inventory_key:
                keys.add(inventory_key)
        return keys

    @api.model
    def _pf_node_owner_failure(self, node_failures):
        """Falla 'dueña' de un hito: la raíz si existe; si no, la de menor rank."""
        if not node_failures:
            return None
        root = node_failures.filtered(lambda f: f.pf_chain_role == 'root')[:1]
        if root:
            return root
        return node_failures.sorted(
            key=lambda f: (f.pf_chain_rank or 0, f.id))[:1]
