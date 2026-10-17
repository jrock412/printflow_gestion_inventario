# -*- coding: utf-8 -*-
"""Motor de pendientes por NODO del flujo (PrintFlow).

Única fuente de "pendientes por nodo" para las superficies del flujo: dado un
conjunto de productos, devuelve cuántos documentos pendientes tiene CADA
producto en cada hito (``purchase``, ``receipt``, ``production``, ``delivery``,
``sale``). Para los nodos de INVENTARIO/stock NO recalcula existencias: delega en
``printflow.stock.health`` (una sola lectura de quants).

Diseño (aprobado):
  * ``AbstractModel`` sin estado ni tabla (cero migración, aditivo).
  * Una SOLA pasada por modelo (batch, sin N+1): nunca se consulta por producto.
  * Cero hardcodeo: los nodos habilitados y sus límites salen de
    ``ir.config_parameter``.
  * Regla Q9: en las ENTREGAS se excluyen los albaranes del PROPIO pedido,
    reutilizando el criterio ya probado (``board._get_delivery_pickings()``).
  * Regla Q11: ``sudo()`` SOLO para armar dominios y NAVEGAR; jamás se devuelven
    acciones que escriban sin permiso del usuario.

Dirección de dependencias: este archivo vive en ``models/`` y NO depende de
``diagnostic/`` (el criterio de exclusión se replica aquí a partir del board,
que también es de ``models/``).
"""

import logging
from collections import defaultdict

from odoo import _, api, models

_logger = logging.getLogger(__name__)

# Umbral de comparación de cantidades (mismo que el motor y el resto de piezas).
_EPS = 1e-6

# ── Claves de configuración (cero hardcodeo) ──────────────────────────────
PARAM_NODE_PENDING_ENABLED = (
    'x_product_dimensional_pricing.pf_node_pending_enabled')
PARAM_NODE_PENDING_NODES = (
    'x_product_dimensional_pricing.pf_node_pending_nodes')
PARAM_NODE_PENDING_LIMIT = (
    'x_product_dimensional_pricing.pf_node_pending_limit')
PARAM_CATALOG_LIMIT = (
    'x_product_dimensional_pricing.pf_catalog_limit')

# Nodos de fase 1 con documento propio (dominio por modelo).
NODE_KEYS = ('purchase', 'receipt', 'production', 'delivery', 'sale')

# Estados de OC que cuentan como "SIN CONFIRMAR" (D2/D3). Una OC confirmada
# (``state='purchase'``) NUNCA cuenta como pendiente de Compras: recibir exige
# confirmar antes, así que toda OC recibida está confirmada y la exclusión de
# "ya recibidas" es INTRÍNSECA al filtro de estado (no se usa el frágil
# ``qty_received >= product_qty``). Lo "por recibir" lo expresa el nodo Recepción.
PURCHASE_UNCONFIRMED_STATES = ('draft', 'sent', 'to approve')

# Nodos de INVENTARIO/stock: NO calculan quants aquí, delegan en stock.health.
STOCK_NODE_KEYS = ('stock', 'stock_supply', 'stock_finished')

# Todos los nodos reconocidos (los no listados en el parámetro se ignoran).
ALL_NODE_KEYS = NODE_KEYS + STOCK_NODE_KEYS

# Semilla por defecto de nodos habilitados (fase 1).
DEFAULT_NODE_PENDING_NODES = 'purchase,receipt,production,delivery,sale'

# Acción masiva EXISTENTE de entregas (server action con binding en la lista de
# albaranes). Se devuelve su xmlid; su ejecución respeta los permisos del usuario
# (no se fuerza ``sudo``).
BULK_ACTION_XMLIDS = {
    'delivery':
        'x_product_dimensional_pricing.action_server_printflow_validate_deliveries',
}

# ── Enumeración de DOCUMENTOS pendientes (Fase 4) ─────────────────────────
# Modelo del documento por nodo. Los nodos de INVENTARIO/stock NO tienen
# documento propio (delegan en la bandeja de salud) y se omiten aquí.
PENDING_DOCUMENT_MODELS = {
    'delivery': 'stock.picking',
    'receipt': 'stock.picking',
    'production': 'mrp.production',
    'purchase': 'purchase.order',
    'sale': 'sale.order',
}

# Campos mínimos a leer (una sola pasada por nodo, sin lecturas perezosas).
PENDING_DOCUMENT_FIELDS = {
    'delivery': ['name', 'state', 'scheduled_date'],
    'receipt': ['name', 'state', 'scheduled_date'],
    # OJO: ``mrp.production`` NO tiene ``date_planned_start`` en Odoo 17 CE.
    # Su fecha válida (y obligatoria) es ``date_start`` (regresión Fase 4).
    'production': ['name', 'state', 'product_id', 'date_start'],
    'purchase': ['name', 'state', 'date_order'],
    'sale': ['name', 'state', 'date_order', 'commitment_date'],
}

# Orden estable de los documentos por nodo (fecha ascendente).
PENDING_DOCUMENT_ORDER = {
    'delivery': 'scheduled_date asc, id asc',
    'receipt': 'scheduled_date asc, id asc',
    'production': 'date_start asc, id asc',
    'purchase': 'date_order asc, id asc',
    'sale': 'date_order asc, id asc',
}

# Respaldo en cascada de la fecha programada/comprometida del documento.
# Todos los nombres listados existen en algún modelo de nodo; aun así, el
# saneador de metadata (abajo) descarta cualquiera inexistente en el modelo.
PENDING_DOCUMENT_DATE_FIELDS = (
    'scheduled_date', 'date_start', 'date_order', 'commitment_date',
)


class PrintflowFlowPending(models.AbstractModel):
    """Pendientes por nodo del flujo, en una sola pasada por modelo."""

    _name = 'printflow.flow.pending'
    _description = 'Pendientes por nodo del flujo (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # CONFIGURACIÓN (ir.config_parameter: cero hardcodeo)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_get_param(self, key, default=None):
        """Lee un parámetro de configuración de forma defensiva."""
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def _pf_node_pending_enabled(self):
        """¿Está activo el motor de pendientes por nodo? (default: sí)."""
        raw = str(self._pf_get_param(
            PARAM_NODE_PENDING_ENABLED, '1') or '').lower()
        return raw in ('1', 'true', 'yes', 't')

    @api.model
    def _pf_node_pending_nodes(self):
        """Nodos habilitados (lista de claves reconocidas).

        Devuelve ``[]`` si el motor está deshabilitado. Los valores desconocidos
        del parámetro se descartan para no romper las superficies.
        """
        if not self._pf_node_pending_enabled():
            return []
        raw = self._pf_get_param(
            PARAM_NODE_PENDING_NODES, DEFAULT_NODE_PENDING_NODES) or ''
        keys = [k.strip() for k in raw.replace(';', ',').split(',') if k.strip()]
        return [key for key in keys if key in ALL_NODE_KEYS]

    @api.model
    def _pf_node_pending_limit(self, default=0):
        """Límite de documentos por corrida (0 = sin límite)."""
        raw = self._pf_get_param(PARAM_NODE_PENDING_LIMIT, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    @api.model
    def _pf_catalog_limit(self, default=0):
        """Límite del catálogo de superficies (0 = sin límite). Semilla fase 4/6."""
        raw = self._pf_get_param(PARAM_CATALOG_LIMIT, str(default))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    @api.model
    def _pf_purchase_unconfirmed_states(self):
        """Estados de OC "SIN CONFIRMAR" (FUENTE ÚNICA de este nodo).

        Reexporta la tupla YA existente del motor para que los listados de OC del
        diagrama de producto (``_pf_open_purchase_orders`` y el tray raíz) NO
        dupliquen el criterio de Compras: una OC confirmada (``state='purchase'``)
        es una compra YA hecha y NUNCA cuenta como "sin confirmar".
        """
        return PURCHASE_UNCONFIRMED_STATES

    # ══════════════════════════════════════════════════════════════════════
    # MAPA DE PENDIENTES
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_as_board(self, exclude):
        """Normaliza ``exclude`` al board del pedido (o recordset vacío).

        Acepta un ``printflow.order.board`` (para excluir los documentos del
        propio pedido, regla Q9) o cualquier otra cosa (se ignora).
        """
        if exclude is not None and getattr(
                exclude, '_name', None) == 'printflow.order.board':
            # Se acota a UNO: ``_get_delivery_pickings`` exige ``ensure_one``.
            return exclude[:1]
        return self.env['printflow.order.board']

    @api.model
    def _pf_node_pending_map(self, products, exclude=None):
        """Pendientes por producto y nodo: ``{pid: {node_key: count}}``.

        UNA sola consulta por nodo/modelo (batch, sin N+1). Los productos sin
        pendientes no aparecen; los nodos con 0 tampoco.

        :param products: recordset de ``product.product``.
        :param exclude: board del pedido (``printflow.order.board``) para excluir
            sus propios documentos de entrega (regla Q9), o ``None``.
        :rtype: dict[int, dict[str, int]]
        """
        result = {}
        products = products.filtered(lambda p: p) if products else (
            self.env['product.product'])
        if not products:
            return result
        nodes = self._pf_node_pending_nodes()
        if not nodes:
            return result
        product_ids = products.ids
        board = self._pf_as_board(exclude)
        for node_key in nodes:
            counts = self._pf_node_pending_counts(
                node_key, product_ids, board=board)
            for pid, count in counts.items():
                if count:
                    result.setdefault(pid, {})[node_key] = count
        return result

    @api.model
    def _pf_node_pending_counts(self, node_key, product_ids, board=None):
        """Cuenta documentos pendientes por producto para UN nodo (batch).

        :return: ``{product_id: count}``.
        :rtype: dict[int, int]
        """
        counts = defaultdict(int)
        product_ids = [pid for pid in set(product_ids or []) if pid]
        if not product_ids:
            return counts
        if node_key in STOCK_NODE_KEYS:
            return self._pf_stock_node_pending_counts(node_key, product_ids)
        limit = self._pf_node_pending_limit() or None
        rows = self._pf_node_pending_rows(node_key, product_ids, board)

        if node_key in ('delivery', 'receipt'):
            # Cada ALBARÁN cuenta una vez por producto (aunque tenga varias líneas).
            seen = defaultdict(set)
            for row in rows:
                if row.get('product_id') and row.get('picking_id'):
                    seen[row['product_id'][0]].add(row['picking_id'][0])
            return {pid: len(pickings) for pid, pickings in seen.items()}

        if node_key in ('purchase', 'sale'):
            # Cada PEDIDO (compra/venta) cuenta una vez por producto.
            seen = defaultdict(set)
            key = 'order_id'
            for row in rows:
                if row.get('product_id') and row.get(key):
                    seen[row['product_id'][0]].add(row[key][0])
            return {pid: len(orders) for pid, orders in seen.items()}

        if node_key == 'production':
            # Una MO por fila: se cuenta directo (product_id es del terminado).
            for row in rows:
                if row.get('product_id'):
                    counts[row['product_id'][0]] += 1
            return counts
        return counts

    @api.model
    def _pf_receipt_pending_distinct(self, product_ids):
        """Nº de ALBARANES de entrada ABIERTOS distintos de unos productos (D4).

        Pensado para el nodo RECEPCIÓN del diagrama cuando el producto es
        fabricable: se le pasa el terminado + los componentes de su BOM y se
        cuentan las recepciones PENDIENTES (albaranes ``incoming`` abiertos con
        movimientos de CUALQUIERA de esos productos). Cuenta ``picking_id``
        DISTINTOS: un albarán con varios componentes cuenta UNA sola vez (sin
        doble conteo).

        Reutiliza el lector batch del motor (``_pf_node_pending_rows``), que ya
        respeta ``pf_node_pending_limit``: UNA sola consulta, sin N+1.

        :param product_ids: ids de ``product.product`` (terminado [+ insumos]).
        :rtype: int
        """
        ids = [pid for pid in set(product_ids or []) if pid]
        if not ids:
            return 0
        rows = self._pf_node_pending_rows('receipt', ids)
        return len({
            row['picking_id'][0] for row in rows
            if row.get('picking_id')})

    # ══════════════════════════════════════════════════════════════════════
    # FALTANTE REAL Y PEDIDOS POR COMPRAR (D1/D4)
    #
    # Lectores de SOLO LECTURA que alimentan el faltante REAL del nodo Compras
    # (déficit físico − OC sin confirmar que SÍ cubren demanda) y el botón
    # "Traer pedidos" de la Compra Rápida. Una sola pasada por modelo (sin N+1);
    # el vínculo pedido↔OC se delega en las FUENTES ÚNICAS ya existentes.
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_sale_orders_pending_delivery(self, product_ids):
        """Pedidos con ENTREGA PENDIENTE de un producto: ``{pid: set(names)}``.

        Candidatos del faltante real (D1) y del botón "Traer pedidos" (D4): una
        línea de venta CONFIRMADA (``order_id.state='sale'``) cuya cantidad
        pedida aún NO se entregó (``product_uom_qty − qty_delivered`` > 0).

        UNA ``search_read`` de las líneas + UNA lectura batch de los pedidos para
        traducir ids→nombres (sin N+1, solo LECTURA).

        :param product_ids: ids de ``product.product``.
        :rtype: dict[int, set[str]]
        """
        result = defaultdict(set)
        ids = [pid for pid in set(product_ids or []) if pid]
        if not ids:
            return {}
        lines = self.env['sale.order.line'].sudo().search_read([
            ('order_id.state', '=', 'sale'),
            ('product_id', 'in', ids),
        ], ['product_id', 'order_id', 'product_uom_qty', 'qty_delivered'])
        order_ids = [
            row['order_id'][0] for row in lines if row.get('order_id')]
        names_by_order = {
            row['id']: row.get('name') or ''
            for row in self.env['sale.order'].sudo().browse(
                order_ids).read(['name'])
        }
        for row in lines:
            product = row.get('product_id')
            order = row.get('order_id')
            if not product or not order:
                continue
            pending = (
                (row.get('product_uom_qty') or 0.0)
                - (row.get('qty_delivered') or 0.0))
            if pending <= _EPS:
                continue
            name = names_by_order.get(order[0])
            if name:
                result[product[0]].add(name)
        return dict(result)

    @api.model
    def _pf_purchase_unconfirmed_cover(self, product_ids, sale_order=None):
        """Unidades de OC SIN CONFIRMAR que cubren demanda pendiente (D1).

        ``{pid: qty}`` con la cobertura por producto: se suman las cantidades de
        las líneas de OC del producto en estados SIN CONFIRMAR
        (``PURCHASE_UNCONFIRMED_STATES``, FUENTE ÚNICA) cuyo ``origin``
        referencia un pedido con ENTREGA PENDIENTE del producto
        (``_pf_sale_orders_pending_delivery``).
        Con ``sale_order`` dado, la cobertura se RESTRINGE a ese pedido (paridad
        del diagrama de pedido, D6). El ``origin`` se tokeniza reutilizando la
        FUENTE ÚNICA ``printflow.stock.remedy._pf_origin_sale_names`` (compras
        agrupadas: 1 OC puede referenciar N pedidos).

        UNA ``search_read`` de las líneas + UNA lectura batch del ``origin`` de
        sus OC (sin N+1, solo LECTURA).

        :param product_ids: ids de ``product.product``.
        :param sale_order: ``sale.order`` en foco (opcional; restringe la
            cobertura).
        :rtype: dict[int, float]
        """
        cover = defaultdict(float)
        ids = [pid for pid in set(product_ids or []) if pid]
        if not ids:
            return {}
        lines = self.env['purchase.order.line'].sudo().search_read([
            ('order_id.state', 'in', PURCHASE_UNCONFIRMED_STATES),
            ('product_id', 'in', ids),
        ], ['product_id', 'order_id', 'product_qty'])
        if not lines:
            return {}
        po_ids = [
            row['order_id'][0] for row in lines if row.get('order_id')]
        # UNA lectura batch del ``origin`` de las OC: calienta la caché para
        # tokenizarlo con la fuente única (sin consultas extra).
        po_records = self.env['purchase.order'].sudo().browse(po_ids)
        po_records.read(['origin'])
        remedy = self.env['printflow.stock.remedy']
        names_by_po = {
            po.id: remedy._pf_origin_sale_names(po) for po in po_records}
        pending_by_pid = (
            {} if sale_order
            else self._pf_sale_orders_pending_delivery(ids))
        focus_name = sale_order.name if sale_order else None
        for row in lines:
            product = row.get('product_id')
            order = row.get('order_id')
            if not product or not order:
                continue
            origin_names = names_by_po.get(order[0]) or set()
            if focus_name:
                matches = focus_name in origin_names
            else:
                pending_names = pending_by_pid.get(product[0]) or set()
                matches = bool(origin_names & pending_names)
            if matches:
                cover[product[0]] += row.get('product_qty') or 0.0
        return dict(cover)

    @api.model
    def _pf_sale_orders_requiring_purchase(self, product):
        """Pedidos que REQUIEREN compra de un producto (filtro D4).

        Devuelve los pedidos de ``product`` con ENTREGA PENDIENTE (candidatos de
        ``_pf_sale_orders_pending_delivery``) que NO tienen una compra "EN
        TRÁMITE" que vaya a surtirlos. Una compra está EN TRÁMITE si tiene una
        línea del producto y está: (a) SIN CONFIRMAR
        (``PURCHASE_UNCONFIRMED_STATES``: basta confirmarla) o (b) CONFIRMADA
        (``state='purchase'``) con albarán de entrada ABIERTO (recepción
        pendiente). Esos pedidos se EXCLUYEN (ya tienen entrada futura); los que
        NO tienen OC, tienen OC CANCELADA o ya RECIBIDA (sin recepción abierta)
        REQUIEREN compra. El vínculo pedido↔OC por ``origin`` se delega en la
        FUENTE ÚNICA
        ``printflow.purchase.link.mixin._find_purchase_orders_by_sale_names``.

        Lecturas en lote (sin N+1, solo LECTURA).

        :param product: ``product.product``.
        :rtype: sale.order
        """
        SaleOrder = self.env['sale.order']
        if not product:
            return SaleOrder
        pending = self._pf_sale_orders_pending_delivery(
            product.ids).get(product.id, set())
        if not pending:
            return SaleOrder
        pos = self.env[
            'printflow.purchase.link.mixin'
        ]._find_purchase_orders_by_sale_names(list(pending))
        if not pos:
            return SaleOrder.search([('name', 'in', list(pending))])
        # OC que TIENEN una línea del producto (solo esas pueden surtirlo).
        product_po_ids = {
            row['order_id'][0]
            for row in self.env['purchase.order.line'].sudo().search_read([
                ('order_id', 'in', pos.ids),
                ('product_id', '=', product.id),
            ], ['order_id'])
            if row.get('order_id')
        }
        # UNA lectura del estado / origen de las OC (calienta la caché).
        pos.read(['state', 'origin'])
        unconfirmed_ids = {
            po.id for po in pos
            if po.id in product_po_ids
            and po.state in PURCHASE_UNCONFIRMED_STATES}
        confirmed_ids = {
            po.id for po in pos
            if po.id in product_po_ids and po.state == 'purchase'}
        pending_receipt_ids = set()
        if confirmed_ids:
            pending_receipt_ids = {
                row['purchase_id'][0]
                for row in self.env['stock.picking'].sudo().search_read([
                    ('state', 'not in', ('done', 'cancel')),
                    ('picking_type_id.code', '=', 'incoming'),
                    ('purchase_id', 'in', list(confirmed_ids)),
                ], ['purchase_id'])
                if row.get('purchase_id')
            }
        in_progress_ids = unconfirmed_ids | pending_receipt_ids
        blocked = self.env[
            'printflow.stock.remedy']._pf_origin_sale_names(
                pos.filtered(lambda po: po.id in in_progress_ids))
        requiring = pending - blocked
        if not requiring:
            return SaleOrder
        return SaleOrder.search([('name', 'in', list(requiring))])

    @api.model
    def _pf_node_pending_rows(self, node_key, product_ids, board=None):
        """Lectura batch (``search_read``) de los documentos de UN nodo.

        NO devuelve recordset para no disparar lecturas perezosas: los conteos se
        hacen sobre los dicts leídos.

        :rtype: list[dict]
        """
        Move = self.env['stock.move'].sudo()
        limit = self._pf_node_pending_limit() or None

        if node_key in ('delivery', 'receipt'):
            code = 'outgoing' if node_key == 'delivery' else 'incoming'
            domain = [
                ('state', 'not in', ('done', 'cancel')),
                ('product_id', 'in', product_ids),
                ('picking_id', '!=', False),
                ('picking_id.state', 'not in', ('done', 'cancel')),
                ('picking_id.picking_type_id.code', '=', code),
            ]
            if node_key == 'delivery':
                own = board._get_delivery_pickings().ids if board else []
                if own:
                    domain.append(('picking_id', 'not in', own))
            return Move.search_read(
                domain, ['product_id', 'picking_id'], limit=limit)

        if node_key == 'production':
            return self.env['mrp.production'].sudo().search_read([
                ('state', 'not in', ('done', 'cancel')),
                ('product_id', 'in', product_ids),
            ], ['product_id'], limit=limit)

        if node_key == 'purchase':
            return self.env['purchase.order.line'].sudo().search_read([
                ('order_id.state', 'in', PURCHASE_UNCONFIRMED_STATES),
                ('product_id', 'in', product_ids),
            ], ['product_id', 'order_id'], limit=limit)

        if node_key == 'sale':
            return self.env['sale.order.line'].sudo().search_read([
                ('order_id.state', 'in', ('draft', 'sent', 'sale')),
                ('product_id', 'in', product_ids),
            ], ['product_id', 'order_id'], limit=limit)

        return []

    @api.model
    def _pf_stock_node_pending_counts(self, node_key, product_ids):
        """Pendientes de un nodo de INVENTARIO: delega en ``stock.health``.

        NO recalcula quants: usa la foto agregada de ``printflow.stock.health``
        (una sola lectura). Un producto con estado distinto de ``ok`` cuenta 1 en
        el nodo de stock solicitado.

        :rtype: dict[int, int]
        """
        products = self.env['product.product'].sudo().browse(
            list(product_ids)).exists()
        if not products:
            return {}
        snapshot = self.env['printflow.stock.health']._pf_inventory_snapshot(
            products)
        return {
            pid: 1 for pid, info in snapshot.items()
            if (info.get('state') or 'ok') != 'ok'
        }

    # ══════════════════════════════════════════════════════════════════════
    # DOMINIOS Y ACCIONES
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_node_pending_domain(self, node_key, product_ids, board=None):
        """Dominio (sobre el modelo del nodo) de los documentos pendientes.

        Para entregas (``delivery``) excluye los albaranes del PROPIO pedido
        (regla Q9). Los nodos de stock no tienen dominio propio (delegan).

        :param list product_ids: ids de ``product.product``.
        :param board: ``printflow.order.board`` opcional (exclusión del propio).
        :rtype: list
        """
        product_ids = [pid for pid in set(product_ids or []) if pid]
        if not product_ids:
            return [('id', '=', False)]
        if node_key == 'delivery':
            domain = [
                ('state', 'not in', ('done', 'cancel')),
                ('picking_type_id.code', '=', 'outgoing'),
                ('move_ids.product_id', 'in', product_ids),
                ('move_ids.state', 'not in', ('done', 'cancel')),
            ]
            own = board._get_delivery_pickings().ids if board else []
            if own:
                domain.append(('id', 'not in', own))
            return domain
        if node_key == 'receipt':
            return [
                ('state', 'not in', ('done', 'cancel')),
                ('picking_type_id.code', '=', 'incoming'),
                ('move_ids.product_id', 'in', product_ids),
                ('move_ids.state', 'not in', ('done', 'cancel')),
            ]
        if node_key == 'production':
            return [
                ('state', 'not in', ('done', 'cancel')),
                ('product_id', 'in', product_ids),
            ]
        if node_key == 'purchase':
            return [
                ('state', 'in', PURCHASE_UNCONFIRMED_STATES),
                ('order_line.product_id', 'in', product_ids),
            ]
        if node_key == 'sale':
            return [
                ('state', 'in', ('draft', 'sent', 'sale')),
                ('order_line.product_id', 'in', product_ids),
            ]
        return []

    @api.model
    def _pf_node_pending_action(self, node_key, products, title=None, board=None):
        """``act_window`` de navegación a los pendientes de UN nodo.

        * ``delivery`` / ``receipt`` -> ``stock.picking`` (outgoing / incoming).
        * ``production``            -> ``mrp.production``.
        * ``purchase``              -> ``purchase.order``.
        * ``sale``                  -> ``sale.order``.
        * ``stock``/``stock_supply``/``stock_finished`` -> delega en la bandeja
          de Salud de inventario (``printflow.inventory.health._pf_open_health``).

        Nunca escribe: solo devuelve la acción de apertura (regla Q11).
        """
        products = products.filtered(lambda p: p) if products else (
            self.env['product.product'])
        if node_key in STOCK_NODE_KEYS:
            return self.env['printflow.inventory.health']._pf_open_health(
                products=products, title=title)
        if not products:
            return {'type': 'ir.actions.act_window_close'}
        spec = {
            'delivery': ('stock.picking', 'tree,form', _('Entregas pendientes')),
            'receipt': ('stock.picking', 'tree,form', _('Recepciones pendientes')),
            'production': ('mrp.production', 'tree,form',
                           _('Órdenes de fabricación')),
            'purchase': ('purchase.order', 'tree,form', _('Compras pendientes')),
            'sale': ('sale.order', 'tree,form', _('Ventas abiertas')),
        }.get(node_key)
        if not spec:
            return {'type': 'ir.actions.act_window_close'}
        res_model, view_mode, default_name = spec
        return {
            'type': 'ir.actions.act_window',
            'name': title or default_name,
            'res_model': res_model,
            'view_mode': view_mode,
            'target': 'current',
            'domain': self._pf_node_pending_domain(
                node_key, products.ids, board=board),
        }

    @api.model
    def _pf_node_pending_bulk_action(self, node_key):
        """Xmlid de la acción masiva EXISTENTE del nodo, o ``False``.

        Fase 1: solo ``delivery`` tiene acción masiva (validar entregas). El
        resto devuelve ``False``.
        """
        return BULK_ACTION_XMLIDS.get(node_key) or False

    # ══════════════════════════════════════════════════════════════════════
    # ENUMERACIÓN DE DOCUMENTOS PENDIENTES (Fase 4: Centro de Salud)
    #
    # A diferencia del mapa (producto-céntrico), aquí se listan los DOCUMENTOS
    # pendientes (una fila por documento) para la pestaña "Pendientes" del
    # Centro. Sigue siendo aditivo: no modifica ningún método del mapa.
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_node_pending_document_domain(self, node_key, product_ids=None,
                                         board=None):
        """Dominio sobre el MODELO DEL DOCUMENTO (no sobre ``stock.move``).

        El filtro de producto es OPCIONAL: sin ``product_ids`` devuelve el
        dominio global del nodo. En ``delivery`` aplica la regla Q9 (excluir
        los albaranes del PROPIO pedido) reutilizando ``_pf_as_board``.

        :param str node_key: clave del nodo (``delivery``, ``receipt``, ...).
        :param list product_ids: ids de ``product.product`` (opcional).
        :param board: ``printflow.order.board`` opcional (exclusión Q9).
        :rtype: list
        """
        product_ids = [pid for pid in set(product_ids or []) if pid]
        if node_key == 'delivery':
            domain = [
                ('state', 'not in', ('done', 'cancel')),
                ('picking_type_id.code', '=', 'outgoing'),
            ]
            if product_ids:
                domain += [
                    ('move_ids.product_id', 'in', product_ids),
                    ('move_ids.state', 'not in', ('done', 'cancel')),
                ]
            own = board._get_delivery_pickings().ids if board else []
            if own:
                domain.append(('id', 'not in', own))
            return domain
        if node_key == 'receipt':
            domain = [
                ('state', 'not in', ('done', 'cancel')),
                ('picking_type_id.code', '=', 'incoming'),
            ]
            if product_ids:
                domain += [
                    ('move_ids.product_id', 'in', product_ids),
                    ('move_ids.state', 'not in', ('done', 'cancel')),
                ]
            return domain
        if node_key == 'production':
            domain = [('state', 'not in', ('done', 'cancel'))]
            if product_ids:
                domain.append(('product_id', 'in', product_ids))
            return domain
        if node_key == 'purchase':
            domain = [
                ('state', 'in', PURCHASE_UNCONFIRMED_STATES),
            ]
            if product_ids:
                domain.append(('order_line.product_id', 'in', product_ids))
            return domain
        if node_key == 'sale':
            domain = [('state', 'in', ('draft', 'sent', 'sale'))]
            if product_ids:
                domain.append(('order_line.product_id', 'in', product_ids))
            return domain
        return [('id', '=', False)]

    @api.model
    def _pf_document_model_fields(self, model_name):
        """Nombres de campo REALES del modelo (metadata defensiva, R6).

        Nunca revienta: si el modelo no existe o el ORM no puede leer sus
        metadatos, devuelve un ``set`` vacío para que el llamador degrade.

        :param str model_name: nombre técnico del modelo del documento.
        :rtype: set[str]
        """
        if not model_name or model_name not in self.env:
            return set()
        try:
            # ``_fields`` ya está cacheado por el ORM: sin consulta extra.
            return set(self.env[model_name]._fields)
        except Exception:  # noqa: BLE001 - metadata defensiva
            try:
                return set(self.env[model_name].sudo().fields_get().keys())
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "PrintFlow: no se pudieron leer los campos de '%s'; "
                    "se omite la validación de metadata.", model_name)
                return set()

    @api.model
    def _pf_sanitize_document_read(self, model_name, fields, order):
        """Sanea ``fields`` y ``order`` contra la metadata real del modelo.

        Descarta todo campo y todo término de orden que NO exista en
        ``model_name`` (con ``_logger.warning``) y cae a un orden seguro
        ``'id asc'`` si ningún término sobrevive. Motivo: un campo malo o un
        modelo distinto NO deben tumbar el Centro completo (plan §R6).

        :param str model_name: modelo del documento.
        :param list fields: nombres de campo solicitados.
        :param str order: orden solicitado (``'campo asc, otro desc'``).
        :return: ``(fields_sanos, order_sano)``.
        :rtype: tuple[list[str], str]
        """
        valid = self._pf_document_model_fields(model_name)
        if not valid:
            # Sin metadata fiable: no se pide ningún campo y se ordena por id.
            return [], 'id asc'
        safe_fields = []
        for field_name in (fields or []):
            if field_name in valid:
                safe_fields.append(field_name)
            else:
                _logger.warning(
                    "PrintFlow: campo '%s' inexistente en '%s'; se descarta "
                    "de la enumeración de pendientes.", field_name, model_name)
        safe_terms = []
        for term in str(order or '').split(','):
            term = term.strip()
            if not term:
                continue
            name = term.split()[0]
            if name in valid:
                safe_terms.append(term)
            else:
                _logger.warning(
                    "PrintFlow: orden '%s' inválido en '%s'; se descarta.",
                    term, model_name)
        return safe_fields, (', '.join(safe_terms) or 'id asc')

    @api.model
    def _pf_node_pending_document_rows(self, node_key, product_ids=None,
                                       board=None, limit=0):
        """UNA ``search_read`` del documento del nodo (sin N+1).

        Antes de consultar, valida los campos y el orden contra la metadata
        real del modelo (``_pf_sanitize_document_read``): un campo inexistente
        se descarta y nunca revienta la enumeración global.

        :param int limit: tope de filas de ESTE nodo (0/None = sin límite).
        :rtype: list[dict]
        """
        model_name = PENDING_DOCUMENT_MODELS.get(node_key)
        if not model_name:
            return []
        domain = self._pf_node_pending_document_domain(
            node_key, product_ids, board=board)
        fields = PENDING_DOCUMENT_FIELDS.get(node_key, ['name', 'state'])
        order = PENDING_DOCUMENT_ORDER.get(node_key, 'id asc')
        fields, order = self._pf_sanitize_document_read(
            model_name, fields, order)
        return self.env[model_name].sudo().search_read(
            domain, fields, order=order, limit=(limit or None))

    @api.model
    def _pf_pending_document_state_label(self, model_name, state):
        """Etiqueta legible (traducida) del estado real del modelo.

        Resuelve la ``selection`` del campo ``state`` con ``fields_get``. Si el
        estado no está en la selección, devuelve el código crudo (R6).
        """
        if not model_name or not state:
            return state or ''
        selection = []
        try:
            selection = self.env[model_name].sudo().fields_get(
                ['state']).get('state', {}).get('selection') or []
        except Exception:  # noqa: BLE001 - metadata defensiva
            selection = []
        return dict(selection).get(state, state)

    @api.model
    def _pf_node_pending_document_vals(self, node_key, row, product_ids=None):
        """Traduce un ``dict`` del documento a ``vals`` de la línea pendiente.

        Incluye ``state_label`` (traducido) y ``bulk_action_xmlid`` (solo
        ``delivery`` en Fase 4). La fecha programada se resuelve en cascada.
        """
        model_name = PENDING_DOCUMENT_MODELS.get(node_key) or ''
        state = row.get('state')
        scheduled_date = False
        for field_name in PENDING_DOCUMENT_DATE_FIELDS:
            if row.get(field_name):
                scheduled_date = row[field_name]
                break
        product_ids = [pid for pid in set(product_ids or []) if pid]
        product_id = False
        if product_ids:
            # Con filtro: la fila es a nivel documento y se ancla al producto
            # filtrado (el documento puede tener varias líneas).
            product_id = product_ids[0]
        elif node_key == 'production' and row.get('product_id'):
            product_id = row['product_id'][0]
        return {
            'node_key': node_key,
            'res_model': model_name,
            'res_id': row.get('id'),
            'name': row.get('name') or '',
            'state_label': self._pf_pending_document_state_label(
                model_name, state),
            'product_id': product_id,
            'scheduled_date': scheduled_date,
            'bulk_action_xmlid': self._pf_node_pending_bulk_action(node_key),
        }

    @api.model
    def _pf_pending_document_lines(self, product_ids=None, node_keys=None,
                                   board=None, limit=0):
        """Enumerador GLOBAL de documentos pendientes (para el Centro).

        Recorre los nodos habilitados por ``_pf_node_pending_nodes`` (respeta
        ``pf_node_pending_enabled`` y ``pf_node_pending_nodes``) y hace **una**
        ``search_read`` por nodo con documento (≤5). El ``limit`` se aplica
        **por nodo** (misma semántica que ``_pf_node_pending_rows``).

        :param list product_ids: filtro opcional de ``product.product``.
        :param list node_keys: nodos a enumerar (``None`` = todos los habilitados).
        :param board: ``printflow.order.board`` opcional (exclusión Q9).
        :param int limit: tope de filas POR NODO (0 = sin límite).
        :rtype: list[dict]
        """
        nodes = self._pf_node_pending_nodes()
        if node_keys:
            wanted = set(node_keys)
            nodes = [node for node in nodes if node in wanted]
        documents = [node for node in nodes if node in PENDING_DOCUMENT_MODELS]
        product_ids = [pid for pid in set(product_ids or []) if pid]
        vals_list = []
        for node_key in documents:
            rows = self._pf_node_pending_document_rows(
                node_key, product_ids, board=board, limit=limit)
            for row in rows:
                vals_list.append(self._pf_node_pending_document_vals(
                    node_key, row, product_ids=product_ids))
        return vals_list
