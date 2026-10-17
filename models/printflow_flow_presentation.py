# -*- coding: utf-8 -*-
"""Presentación PURA del canvas de flujo (PrintFlow).

Servicio ``AbstractModel`` sin tabla que concentra la presentación del canvas:
geometría/celdas, orden de ejes, metadatos de nodos, mapas de tono, etiquetas de
estado, resolución del slot de nodo/falla y las primitivas de arista.

Se EXTRAJO del servicio ``printflow.flow.canvas`` (Fase 1 del refactor OOP,
``docs/plan_fases_orquestador_oop_v2.md``) SIN cambiar comportamiento: los mapas
y las funciones se movieron TAL CUAL para que el canvas DELEGUE en este objeto.
No toca la base de datos ni el motor de reglas: es una hoja de presentación que
solo lee constantes y datos ya resueltos.

Contrato::

    env['printflow.flow.presentation']._pf_key_by_slot(axis) -> dict
    env['printflow.flow.presentation']._pf_failure_slot(failure) -> str | False
    env['printflow.flow.presentation']._pf_node_tone(key, status) -> str
    env['printflow.flow.presentation']._pf_flow_edges(...) -> list[dict]

El ``host`` que consume el canvas NO vive aquí; este servicio no conoce pedido ni
producto: solo geometría, tonos, etiquetas, slots y aristas.
"""

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_SLOTS,
    PF_NODE_TO_SLOT,
)


class PrintflowFlowPresentation(models.AbstractModel):
    """Presentación pura del canvas del flujo (pedido y producto)."""

    _name = 'printflow.flow.presentation'
    _description = 'Presentación del canvas de flujo (PrintFlow)'

    # ── Geometría del canvas (SOLO presentación) ─────────────────────────
    _PF_FLOW_CELL = {
        'w': 176, 'h': 132, 'gap_x': 24, 'gap_y': 28, 'pad_top': 72}

    # Orden SECUENCIAL del recorrido físico por TIPO de flujo.
    _PF_AXIS_ORDER = {
        'purchase': (
            'purchase', 'receipt', 'stock', 'delivery', 'customer'),
        'manufacture': (
            'purchase', 'receipt', 'stock_supply', 'production',
            'stock_finished', 'delivery', 'customer'),
    }

    # Metadatos de PRESENTACIÓN de cada nodo del canvas.
    _PF_NODE_META = {
        'purchase': {
            'label': _('Compras'), 'kind': 'node', 'shape': 'process',
            'owner': 'purchase', 'chain': 'purchase'},
        'receipt': {
            'label': _('Recepción'), 'kind': 'node', 'shape': 'process',
            'owner': 'purchase', 'chain': 'purchase'},
        'stock': {
            'label': _('Inventario'), 'kind': 'node', 'shape': 'process',
            'owner': 'stock', 'chain': 'inventory'},
        'stock_supply': {
            'label': _('Almacén insumos'), 'kind': 'node', 'shape': 'process',
            'owner': 'stock', 'chain': 'supply'},
        'production': {
            'label': _('Fabricación'), 'kind': 'node', 'shape': 'process',
            'owner': 'production', 'chain': 'production'},
        'stock_finished': {
            'label': _('Almacén terminado'), 'kind': 'node', 'shape': 'process',
            'owner': 'stock', 'chain': 'inventory'},
        'delivery': {
            'label': _('Entrega'), 'kind': 'node', 'shape': 'process',
            'owner': 'delivery', 'chain': 'delivery'},
        'customer': {
            'label': _('Cliente'), 'kind': 'terminal', 'shape': 'end',
            'owner': 'delivery', 'chain': 'delivery'},
    }

    # Hitos del canvas que exponen un LISTADO de pendientes accionable.
    _PF_PENDING_ACTION_KEYS = (
        'purchase', 'receipt', 'production', 'delivery',
        'stock', 'stock_supply', 'stock_finished',
    )

    # Destino del PLAN (playbook) -> CLAVE de acción del popover del PRODUCTO.
    # El wizard ``printflow.product.flow`` resuelve la clave con su lista blanca
    # (``_PF_NODE_METHODS``). Permite que las filas del panel y las acciones del
    # nodo reutilicen UN solo dispatcher público (``action_run_pf_node``).
    _PF_PLAN_TARGET_TO_NODE_KEY = {
        'product': 'product',
        'quants': 'quants',
        'quants_adjust': 'adjust',
        'create_production': 'fabricate',
        'buy_components': 'buy_components',
        'buy_product': 'buy_product',
        'bom_list': 'bom_list',
        'fix_over_reservation': 'fix_reservation',
        'reserving_sale_orders': 'blocking',
        'blocking_reservations': 'blocking',
        'purchase_order': 'purchase_orders',
        'receipt': 'receipt',
        'mo': 'mo',
        'mo_list': 'mo',
        'line_delivery': 'delivery_orders',
        'delivery_orders': 'delivery_orders',
        'collect_tray': 'collect',
        # Bandeja gestionable de INSUMOS: el plan del playbook (target
        # 'supply_tray') abre la bandeja por la CLAVE 'fix_supply' del popover.
        'supply_tray': 'fix_supply',
    }

    # Semáforo: estado crudo -> tono (mismo mapa que el widget).
    # Los tokens de LOTE (``lot_no_stock`` / ``lot_generic``) se agregan de forma
    # ADITIVA por ``owner``: el colaborador ``printflow.flow.lots`` expresa la
    # severidad del lote A TRAVÉS del ``status`` del nodo (SOLO en el producto),
    # así el candado ``node.tone == _pf_node_tone(key, node.status)`` sigue verde
    # sin que la explicación repinte el tone.
    _PF_DANGER_STATES = {
        'sale': ('error',), 'stock': ('deficit', 'over', 'no_supply',
                                      'lot_no_stock',
                                      # Tokens CRUDOS del snapshot de inventario
                                      # (motor) que pueden escurrirse al hito de
                                      # insumos/terminado sin traducción: TODOS
                                      # son problemas → se pintan en ROJO
                                      # (danger), nunca gris.
                                      'over_reserved', 'physical', 'contention',
                                      'no_route'),
        'purchase': ('missing',),
        'production': ('no_mo', 'late', 'to_launch', 'no_supply',
                       'lot_no_stock'),
        'delivery': ('lot_no_stock',),
    }
    _PF_WARNING_STATES = {
        'sale': ('pending',),
        'stock': ('lot_generic',), 'purchase': ('pending',),
        'production': ('design', 'material', 'in_progress', 'lot_generic'),
        'delivery': ('pending', 'partial', 'lot_generic'),
    }

    # Etiqueta de estado ESPECÍFICA de cada HITO del canvas.
    _PF_NODE_STATUS_LABELS = {
        'purchase': {
            'ok': _('Comprado'), 'missing': _('Falta comprar'),
            'pending': _('Compra sin recibir'), 'na': _('No aplica'),
        },
        'receipt': {
            'ok': _('Recibido'), 'pending': _('Por recibir'),
            'na': _('No aplica'),
        },
        'stock': {
            'ok': _('Disponible'), 'over': _('Stock en contención'),
            'deficit': _('Sin stock'), 'na': _('Sin dato / N/A'),
            'over_reserved': _('Reservado de más'),
            'physical': _('No hay existencia'),
            'contention': _('Apartado por otros pedidos'),
            'no_route': _('Sin forma de reponer'),
        },
        'stock_supply': {
            'ok': _('Insumos disponibles'), 'over': _('Stock en contención'),
            'deficit': _('Sin stock'), 'no_supply': _('Sin insumos'),
            'na': _('Sin dato / N/A'),
            'over_reserved': _('Reservado de más'),
            'physical': _('No hay existencia'),
            'contention': _('Apartado por otros pedidos'),
            'no_route': _('Sin forma de reponer'),
        },
        'stock_finished': {
            'ok': _('Disponible'), 'over': _('Stock en contención'),
            'deficit': _('Sin stock'), 'na': _('Sin dato / N/A'),
            'over_reserved': _('Reservado de más'),
            'physical': _('No hay existencia'),
            'contention': _('Apartado por otros pedidos'),
            'no_route': _('Sin forma de reponer'),
        },
        'production': {
            'ok': _('Fabricado'), 'in_progress': _('OF en proceso'),
            'design': _('Arte pendiente'), 'material': _('Falta material'),
            'late': _('Retraso +24h'), 'to_launch': _('Sin lanzar'),
            'no_mo': _('Sin orden de fabricación'), 'no_supply': _('Sin insumos'),
            'na': _('No aplica'),
        },
        'delivery': {
            'ok': _('Entregado'), 'pending': _('Pendiente'),
            'partial': _('Entrega parcial'), 'na': _('Sin dato / N/A'),
        },
        'customer': {'ok': _('Entregado')},
    }

    # Respaldo GENÉRICO para hitos/estados no cubiertos arriba.
    _PF_STATUS_LABELS_DEFAULT = {
        'ok': _('Sano'), 'na': _('Sin dato / N/A'), 'pending': _('Pendiente'),
        'partial': _('Entrega parcial'), 'error': _('Cancelado'),
        'deficit': _('Sin stock'), 'over': _('Stock en contención'),
        'missing': _('Falta comprar'), 'design': _('Arte pendiente'),
        'material': _('Falta material'), 'no_mo': _('Sin orden de fabricación'),
        'late': _('Retraso'), 'to_launch': _('Sin lanzar'),
        'no_supply': _('Sin insumos'), 'done': _('Listo'),
        'in_progress': _('OF en proceso'),
        # Tokens de LOTE (aditivos): etiqueta del estado del nodo cuando el hito
        # porta un problema de lote (solo producto).
        'lot_no_stock': _('Lote sin existencia'),
        'lot_generic': _('Lote genérico'),
        # Tokens CRUDOS del snapshot de inventario (aditivos): etiqueta humana
        # para el hito de insumos/terminado (evita imprimir el token técnico).
        'over_reserved': _('Reservado de más'),
        'physical': _('No hay existencia'),
        'contention': _('Apartado por otros pedidos'),
        'no_route': _('Sin forma de reponer'),
    }

    # Etiqueta EXPLÍCITA del badge de PENDIENTES por HITO (D5). Evita el genérico
    # "N pendiente(s)" que se confundía con "Falta comprar": cada nodo dice DE
    # QUÉ son sus pendientes. Los hitos NO listados conservan el texto genérico
    # (compatibilidad visual, O-1).
    _PF_NODE_PENDING_LABELS = {
        'purchase': _('OC sin confirmar'),
        'receipt': _('por recibir'),
        'production': _('OF pendientes'),
        'delivery': _('por entregar'),
        'stock': _('con alerta'),
        'stock_supply': _('con alerta'),
        'stock_finished': _('con alerta'),
    }
    _PF_NODE_PENDING_LABEL_DEFAULT = _('pendiente(s)')

    # Etiqueta EXPLÍCITA del badge de FALTANTE por HITO (D1). La magnitud del
    # déficit se pinta en un badge ADITIVO aparte (no en el ``status_label`` ni
    # en el ``summary``, que cuando el nodo está roto muestra el ``summary``). El
    # único hito con faltante es Compras; el resto conserva la etiqueta vacía.
    _PF_NODE_SHORTFALL_LABELS = {
        'purchase': _('Faltan comprar'),
    }
    _PF_NODE_SHORTFALL_LABEL_DEFAULT = ''

    # ══════════════════════════════════════════════════════════════════════
    # SLOTS (resolución pura por nodo / falla)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_key_by_slot(self, axis):
        """Hito PRINCIPAL del eje que representa cada slot del canvas."""
        key_by_slot = {}
        for key in axis:
            slot = self._PF_NODE_META[key]['chain']
            current = key_by_slot.get(slot)
            if current is None:
                key_by_slot[slot] = key
                continue
            meta = self._PF_NODE_META[key]
            cur_meta = self._PF_NODE_META[current]
            if key == slot or (
                    meta['kind'] == 'node' and cur_meta['kind'] != 'node'):
                key_by_slot[slot] = key
        return key_by_slot

    @api.model
    def _pf_failure_slot(self, failure):
        """Slot de canvas de una falla (separa INSUMOS de TERMINADO)."""
        node = failure.node
        if node == 'stock':
            return (
                'supply' if failure.origin_kind in ('component', 'estimated')
                else 'inventory')
        return PF_NODE_TO_SLOT.get(node, node)

    @api.model
    def _pf_product_failure_slot(self, failure):
        """Slot de canvas de una FALLA en DICT (gemelo de ``_pf_failure_slot``).

        El terminado cae en ``inventory``; los insumos viajan con ``supply`` solo
        cuando la falla declara ``origin_kind`` de insumo.
        """
        node = failure.get('node')
        if node == 'stock':
            origin_kind = failure.get('origin_kind')
            return (
                'supply' if origin_kind in ('component', 'estimated')
                else 'inventory')
        return PF_NODE_TO_SLOT.get(node, node)

    # ══════════════════════════════════════════════════════════════════════
    # TONOS (semáforo)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_severity_tone(self, severity):
        """Severidad ('danger'/'warning'/...) -> tono del semáforo."""
        if severity == 'danger':
            return 'danger'
        if severity in ('warning', 'warn'):
            return 'warn'
        return 'ok'

    @api.model
    def _pf_status_tone(self, node, status):
        """Tono del semáforo de un nodo CAUSAL (fuente única del backend)."""
        if not status or status == 'na':
            return 'na'
        if status == 'ok':
            return 'ok'
        if status in self._PF_DANGER_STATES.get(node, ()):
            return 'danger'
        if status in self._PF_WARNING_STATES.get(node, ()):
            return 'warn'
        return 'na'

    def _pf_node_tone(self, key, status):
        """Tono de un HITO del canvas (traduce su estado crudo)."""
        if key == 'customer':
            return 'ok'
        return self._pf_status_tone(self._PF_NODE_META[key]['owner'], status)

    # ══════════════════════════════════════════════════════════════════════
    # ETIQUETAS DE ESTADO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_node_status_label(self, key, status):
        """Etiqueta de estado del HITO para el texto del nodo (sano o roto)."""
        if not status:
            return ''
        return (
            self._PF_NODE_STATUS_LABELS.get(key, {}).get(status)
            or self._PF_STATUS_LABELS_DEFAULT.get(status)
            or status
        )

    @api.model
    def _pf_node_pending_label(self, key):
        """Etiqueta EXPLÍCITA del badge de pendientes de un HITO (D5).

        Sustituye el genérico "N pendiente(s)" (que convivía con "Falta comprar"
        y se malinterpretaba) por un texto que dice DE QUÉ son los pendientes:
        p. ej. "OC sin confirmar" en Compras, "por recibir" en Recepción. Los
        hitos no listados devuelven el texto genérico (compatibilidad, O-1).
        """
        return self._PF_NODE_PENDING_LABELS.get(
            key, self._PF_NODE_PENDING_LABEL_DEFAULT)

    @api.model
    def _pf_node_shortfall_label(self, key):
        """Etiqueta EXPLÍCITA del badge de FALTANTE de un HITO (D1).

        Acompaña a la magnitud (``shortfall_qty``) que cada estrategia coloca en
        ``ctx['shortfall_by_key']``: p. ej. "Faltan comprar" en Compras. Los
        hitos sin faltante devuelven la cadena vacía (el badge no se pinta).
        """
        return self._PF_NODE_SHORTFALL_LABELS.get(
            key, self._PF_NODE_SHORTFALL_LABEL_DEFAULT)

    # ══════════════════════════════════════════════════════════════════════
    # ARISTAS (primitivas del diagrama)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_edge(self, eid, src, dst, etype, label='', lane=None, side=None,
                 tone=None, chain=False, style='solid'):
        """Un tramo del diagrama (mismo contrato que el widget espera)."""
        return {
            'id': eid, 'from': src, 'to': dst, 'type': etype,
            'label': label, 'lane': lane, 'side': side,
            'tone': tone, 'chain': chain, 'style': style,
        }

    def _pf_flow_edges(self, axis, statuses, roles, root_canvas_key,
                       key_by_slot):
        """Aristas del canvas: flujo secuencial + errores raíz -> consecuencia."""
        edges = []
        for index in range(len(axis) - 1):
            src, dst = axis[index], axis[index + 1]
            edges.append(self._pf_edge(
                'flow-%s-%s' % (src, dst), src, dst, 'flow'))
        if not root_canvas_key:
            return edges
        root_slot = self._PF_NODE_META[root_canvas_key]['chain']
        root_index = PF_CHAIN_SLOTS.index(root_slot)
        for key in axis:
            slot = self._PF_NODE_META[key]['chain']
            if key == root_canvas_key:
                continue
            if roles.get(slot) != 'consequence':
                continue
            if PF_CHAIN_SLOTS.index(slot) <= root_index:
                continue
            edges.append(self._pf_edge(
                'error-%s-%s' % (root_canvas_key, key),
                root_canvas_key, key, 'error',
                label=_('Causa → Consecuencia'),
                tone=self._pf_node_tone(key, statuses.get(key)),
                chain=True))
        return edges
