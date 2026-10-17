# -*- coding: utf-8 -*-
"""Wizard de Diagnóstico y Ruta de Solución (PrintFlow).

Se abre desde la tarjeta del Tablero de Pedidos y muestra el pedido como una
LÍNEA DE TIEMPO de 4 nodos:

    Venta/POS  ->  Inventario  ->  Compras  ->  Fabricación

El objetivo NO es tocar el inventario por detrás, sino EXPLICAR por qué el
pedido está trabado (causa raíz) y ofrecer rutas de solución que el operador
ejecuta de forma consciente, reutilizando los asistentes que YA existen
(compra rápida, producción, recepción y el remedio de sobre-reserva).

Principio de diseño (anti-cascada):
  * Todo el cálculo ocurre UNA sola vez, al crear el wizard (bajo demanda),
    sobre UN pedido concreto. No hay computes almacenados ni bucles sobre el
    tablero completo.
  * No se reimplementa lógica de negocio: se leen los semáforos ya calculados
    del tablero (health_*) y se consultan quants/PO solo para este pedido.
  * Ninguna ruta es destructiva: la reasignación de reservas reutiliza
    ``_fix_over_reservation_and_refresh`` del tablero, que solo suelta y vuelve
    a reservar según el stock físico real.
"""
import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_DIAG_CHAIN_ORDER,
)

_logger = logging.getLogger(__name__)

_EPS = 1e-6

# Snapshot de stock por defecto (producto sin quant ni reservas). Lo devuelve el
# helper del tablero con las mismas claves; aquí solo se usa como respaldo.
_EMPTY_STOCK_SNAPSHOT = {
    'on_hand': 0.0,
    'reserved_total': 0.0,
    'reserved_order': 0.0,
    'reserved_others': 0.0,
    'free_global': 0.0,
    'free_for_order': 0.0,
    'incoming': 0.0,
}

# Opciones compartidas por ``resolution_route`` y ``recommended_route``. Una
# sola fuente de verdad evita que ambas listas se desincronicen (A4). Los
# valores almacenados en BD no cambian.
ROUTE_SELECTION = [
    ('purchase', 'Generar Solicitud de Compra (PO) por el déficit'),
    ('produce', 'Lanzar / priorizar la Orden de Fabricación (MO)'),
    ('reassign', 'Liberar y re-reservar según el stock real (reasignar)'),
    ('receive', 'Recibir la compra pendiente (validar albarán de entrada)'),
    ('design', 'Aprobar el arte pendiente del pedido'),
    ('deliver', 'Entregar el pedido (validar albarán)'),
    ('none', 'Solo diagnóstico (no ejecutar nada)'),
]


class PrintflowOrderDiagnosticWizard(models.TransientModel):
    _name = 'printflow.order.diagnostic.wizard'
    _description = 'Diagnóstico y ruta de solución del pedido (PrintFlow)'

    # ── Contexto ────────────────────────────────────────────────────────
    board_id = fields.Many2one(
        'printflow.order.board', string='Pedido', required=True, ondelete='cascade',
    )
    sale_order_id = fields.Many2one(
        'sale.order', related='board_id.sale_order_id', string='Pedido de Venta',
    )
    name = fields.Char(related='board_id.name', string='Referencia')
    partner_id = fields.Many2one(related='board_id.partner_id', string='Cliente')
    currency_id = fields.Many2one(related='board_id.currency_id')
    amount_total = fields.Monetary(
        related='board_id.amount_total', currency_field='currency_id', string='Total',
    )
    origin_channel = fields.Selection(related='board_id.origin_channel')
    procurement_type = fields.Selection(related='board_id.procurement_type')

    # ── Banderas para los enlaces directos a documentos (C2) ─────────────
    # Son campos RELATED (no almacenados) al tablero: no agregan columnas ni
    # requieren migración. Solo ocultan los botones cuando el documento no
    # existe, porque los métodos del tablero lanzan UserError si falta.
    has_delivery_picking = fields.Boolean(
        related='board_id.has_delivery_picking', string='Tiene albarán de entrega',
    )
    has_production = fields.Boolean(
        related='board_id.has_production', string='Tiene fabricación',
    )
    has_purchase = fields.Boolean(
        related='board_id.has_purchase', string='Tiene compra',
    )

    # ── Nodos de la linea de tiempo (snapshot, no almacenado entre pedidos) ─
    sale_status = fields.Selection(
        [('ok', 'OK'), ('pending', 'BORRADOR'), ('error', 'CANCELADO'), ('na', 'N/A')],
        string='Venta',
    )
    stock_status = fields.Selection(
        [('ok', 'OK'), ('deficit', 'SIN STOCK'), ('over', 'SOBREPEDIDO'), ('na', 'N/A')],
        string='Inventario',
    )
    purchase_status = fields.Selection(
        [('ok', 'OK'), ('missing', 'FALTA COMPRAR'), ('pending', 'POR RECIBIR'), ('na', 'N/A')],
        string='Compras',
    )
    production_status = fields.Selection(
        [('ok', 'OK'), ('design', 'ARTE PENDIENTE'), ('no_mo', 'SIN ORDEN'),
         ('material', 'FALTA MATERIAL'), ('late', 'RETRASO'),
         ('to_launch', 'SIN LANZAR'), ('no_supply', 'SIN INSUMOS'),
         ('in_progress', 'EN PROCESO'),
         ('na', 'N/A')],
        string='Fabricación',
    )
    delivery_status = fields.Selection(
        [('ok', 'ENTREGADO'), ('pending', 'PENDIENTE'),
         ('partial', 'PARCIAL'), ('na', 'N/A')],
        string='Entrega',
        help='Estado de entrega del pedido según el MISMO primitivo que el '
             'tablero (movimientos a cliente + recolección POS).',
    )
    sale_summary = fields.Char(string='Detalle venta')
    stock_summary = fields.Char(string='Detalle inventario')
    purchase_summary = fields.Char(string='Detalle compras')
    production_summary = fields.Char(string='Detalle fabricación')

    # ── Análisis de causa raíz ──────────────────────────────────────────
    root_cause_node = fields.Selection(
        [('sale', 'Venta / POS'), ('stock', 'Inventario'),
         ('supply', 'Almacén insumos'), ('purchase', 'Compras'),
         ('production', 'Fabricación'), ('delivery', 'Entrega')],
        string='Nodo de quiebre',
    )
    root_cause_detail = fields.Text(string='Análisis de la causa raíz')
    has_deficit = fields.Boolean(string='Hay déficit')
    deficit_total = fields.Float(
        string='Déficit (falta física)',
        help='Suma de la falta física del pedido: obliga a comprar o fabricar.',
    )
    incoming_total = fields.Float(string='En camino (compras)')
    over_reserved_total = fields.Float(
        string='Contención (otros pedidos)',
        help='Suma de la cantidad que el pedido necesita pero está reservada por '
             'OTROS pedidos. Se resuelve reasignando reservas, no comprando.',
    )

    deficit_line_ids = fields.One2many(
        'printflow.order.diagnostic.wizard.line', 'wizard_id',
        string='Detalle por producto',
    )

    # ── Presentación (campos calculados de solo lectura, NO almacenados) ──
    # Solo formatean/acortan lo que ya calculó el diagnóstico para la pantalla.
    # No son almacenados: no hay columnas nuevas ni migración, y no alteran
    # ninguna regla de negocio (déficit vs contención se conservan intactos).
    amount_total_display = fields.Float(
        string='Total', compute='_compute_amount_total_display', digits=(16, 2),
        help='Total del pedido formateado a 2 decimales para la cabecera.',
    )
    recommended_route_short = fields.Char(
        string='Ruta recomendada (corta)', compute='_compute_recommended_route_short',
        help='Etiqueta corta de la ruta recomendada, para mostrar como badge.',
    )
    stock_summary_short = fields.Char(
        string='Resumen inventario', compute='_compute_summary_short',
    )
    purchase_summary_short = fields.Char(
        string='Resumen compras', compute='_compute_summary_short',
    )
    production_summary_short = fields.Char(
        string='Resumen fabricación', compute='_compute_summary_short',
    )
    root_cause_headline = fields.Char(
        string='Causa raíz (titular)', compute='_compute_root_cause_display',
        help='Primera línea del análisis: el mensaje corto a destacar.',
    )
    root_cause_notes = fields.Text(
        string='Causa raíz (notas)', compute='_compute_root_cause_display',
        help='Avisos del análisis que no son el desglose por producto.',
    )

    # ── Rutas de resolución ─────────────────────────────────────────────
    resolution_route = fields.Selection(
        ROUTE_SELECTION,
        string='Ruta elegida', default='none',
    )
    recommended_route = fields.Selection(
        ROUTE_SELECTION,
        string='Ruta recomendada', default='none',
    )

    # ══════════════════════════════════════════════════════════════════════
    # CREACION: se calcula el diagnóstico UNA sola vez (bajo demanda)
    # ══════════════════════════════════════════════════════════════════════
    @api.model_create_multi
    def create(self, vals_list):
        """Construye el snapshot y crea el wizard en UN SOLO write (A6).

        El snapshot depende EXCLUSIVAMENTE del tablero (``board_id``), nunca de
        campos transitorios del wizard. Para cada vals calculamos el
        diagnóstico y lo mezclamos antes de llamar a ``super().create()``: así
        evitamos el ``write()`` posterior y la doble escritura que provocaba
        recálculos intermedios innecesarios.
        """
        prepared = []
        hierarchies = []
        for vals in vals_list:
            board = self.env['printflow.order.board'].browse(vals.get('board_id'))
            # Refresco acotado del tablero ANTES de construir el snapshot: el
            # wizard usa los semáforos del tablero como respaldo cuando el
            # desglose numérico no detecta déficit/contención. Si venían viejos,
            # el snapshot nacía obsoleto (p.ej. SOBREPEDIDO fantasma).
            self._pf_refresh_board(board)
            snapshot, line_vals = self._build_snapshot(board)
            commands, hierarchy = self._pf_split_line_commands(line_vals)
            snapshot['deficit_line_ids'] = commands
            # La ruta elegida arranca en la recomendada (el operador puede cambiarla).
            snapshot['resolution_route'] = snapshot.get('recommended_route', 'none')
            merged = dict(vals)
            merged.update(snapshot)
            prepared.append(merged)
            hierarchies.append(hierarchy)
        records = super().create(prepared)
        # Segunda pasada ADITIVA: cuelga cada componente de su producto primario
        # y crea las filas de falla por nodo (necesitan los ids de las líneas).
        for record, hierarchy in zip(records, hierarchies):
            record._pf_apply_line_hierarchy(hierarchy)
        return records

    # ══════════════════════════════════════════════════════════════════════
    # JERARQUIA Y FALLAS POR LINEA (aditivo, sin tocar la deteccion)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_split_line_commands(self, line_vals):
        """Separa los comandos O2m de la metadata de jerarquía/fallas.

        ``_build_snapshot`` anota cada línea con ``_parent_product_id`` y
        ``_failure_vals``. Esas claves NO son campos: se extraen antes de crear
        las líneas y se devuelven como metadata para la segunda pasada.

        :return: ``(commands, hierarchy)`` donde ``commands`` es la lista de
            comandos ``(0, 0, vals)`` lista para el O2m y ``hierarchy`` es una
            lista de dicts ``{product_id, parent_product_id, failures}``.
        """
        commands = []
        hierarchy = []
        for raw in line_vals:
            vals = dict(raw)
            parent_product_id = vals.pop('_parent_product_id', None)
            failures = vals.pop('_failure_vals', [])
            is_display_only = vals.pop('_is_display_only', False)
            commands.append((0, 0, vals))
            hierarchy.append({
                'product_id': vals['product_id'],
                'parent_product_id': parent_product_id,
                'is_display_only': is_display_only,
                'failures': failures,
            })
        return commands, hierarchy

    def _pf_apply_line_hierarchy(self, hierarchy):
        """Cuelga componentes de su producto primario y crea las fallas.

        Se ejecuta DESPUÉS de crear las líneas (necesita sus ids). El producto
        primario es el PRIMER terminado en el mapa de demanda: un componente
        compartido por varios terminados cuelga de ese primero (sin M2m).
        """
        self.ensure_one()
        line_by_product = {}
        for line in self.deficit_line_ids:
            line_by_product.setdefault(line.product_id.id, line)
        Failure = self.env['printflow.order.diagnostic.failure']
        for meta in hierarchy:
            line = line_by_product.get(meta['product_id'])
            if not line:
                continue
            if meta.get('is_display_only'):
                # MEJORA A: fila de solo display (producto ya entregado). Se
                # marca el campo y NO se cuelga ni genera fallas (sus
                # ``_failure_vals`` vienen vacíos por diseño).
                line.is_display_only = True
                continue
            parent_product_id = meta.get('parent_product_id')
            if parent_product_id and not line.parent_line_id:
                parent = line_by_product.get(parent_product_id)
                if parent and parent != line:
                    line.parent_line_id = parent.id
            created = Failure
            for failure_vals in meta.get('failures') or []:
                created |= Failure.create(dict(failure_vals, line_id=line.id))
            if created:
                self._pf_assign_chain_rank(line, created)
        # Segunda pasada de agregación: ya con las fallas y la jerarquía listas,
        # se pliega el subárbol en los ``flow_*`` de cada línea.
        self._pf_apply_flow_rollup()

    def _pf_assign_chain_rank(self, line, failures):
        """Escribe el RANK de la cadena en las fallas recién creadas de la línea.

        El ``pf_chain_rank`` es un campo PLANO (la BD lo necesita para el
        ``_order``); el rol/padre/profundidad siguen siendo compute del modelo de
        falla, que lee la misma cadena del motor. Aquí solo se ordena: raíz (0),
        consecuencias e independientes.
        """
        engine = self.env['printflow.order.health.engine']
        line.invalidate_recordset(['failure_ids'])
        steps = engine._pf_chain_steps(
            failures.mapped('node'), line.root_cause_node,
            order=PF_DIAG_CHAIN_ORDER)
        for failure in failures:
            failure.pf_chain_rank = (steps.get(failure.node) or {}).get('rank', 0)
        # La cadena recién creada puede no verse en los computes hasta invalidar:
        # se fuerza el recálculo con TODAS las fallas de la línea ya presentes.
        failures.invalidate_recordset([
            'pf_chain_role', 'pf_chain_parent_node', 'pf_chain_depth',
            'pf_chain_indent', 'pf_chain_label', 'pf_chain_note',
            'pf_chain_is_consequence', 'pf_is_backlog', 'pf_backlog_reasons',
            'pf_backlog_available',
        ])

    def _pf_apply_flow_rollup(self):
        """Pliega el subárbol en los ``flow_*`` de cada línea (segunda pasada).

        Para las líneas NO terminadas, ``flow_*`` = sus propios ``*``. Para el
        terminado, ``flow_*`` = ``_pf_flow_rollup`` sobre él y sus componentes.
        Los textos de las fallas NO se reescriben: solo se agregan.
        """
        self.ensure_one()
        engine = self.env['printflow.order.health.engine']
        for line in self.deficit_line_ids:
            if line.line_kind != 'finished':
                line.write({
                    'flow_sale_status': line.sale_status,
                    'flow_stock_status': line.stock_status,
                    'flow_purchase_status': line.purchase_status,
                    'flow_production_status': line.production_status,
                    'flow_delivery_status': line.delivery_status,
                    'flow_supply_status': line.stock_status or 'na',
                    'flow_severity': line.severity,
                    'flow_failure_summary': line.failure_summary or '',
                })
                continue
            members = self._pf_collect_subtree(line)
            rollup = engine._pf_flow_rollup(members)
            stock_split = engine._pf_flow_stock_split(members)
            line.write({
                'flow_sale_status': rollup['flow_sale_status'],
                'flow_stock_status': rollup['flow_stock_status'],
                'flow_purchase_status': rollup['flow_purchase_status'],
                'flow_production_status': rollup['flow_production_status'],
                'flow_delivery_status': rollup['flow_delivery_status'],
                'flow_supply_status': engine._pf_supply_node_status(
                    stock_split.get('supply'),
                    line.has_mo_without_materials),
                'flow_severity': rollup['flow_severity'],
                'flow_failure_summary': rollup['flow_failure_summary'],
            })
        # `flow_failure_ids` es un computado que une las fallas del subárbol. Su
        # primer cálculo puede no ver la jerarquía recién creada, así que se
        # invalida y se recalculan los contadores con el subárbol ya enlazado;
        # si no, el terminado no incluiría las fallas de sus componentes.
        self.deficit_line_ids.invalidate_recordset(['flow_failure_ids'])
        for line in self.deficit_line_ids:
            line.flow_failed_node_count = len(line.flow_failure_ids)

    def _pf_collect_subtree(self, line):
        """Miembros planos del subárbol (la línea + todos sus descendientes)."""
        members = [self._pf_line_member(line)]
        for child in line.child_line_ids:
            members.extend(self._pf_collect_subtree(child))
        return members

    @api.model
    def _pf_line_member(self, line):
        """Dict plano de una línea que consume ``_pf_flow_rollup``.

        Incluye las fallas PROPIAS de la línea (con su nodo y su origen) para
        que el motor arme el resumen agrupado por área sin conocer el modelo.
        """
        return {
            'is_finished': line.line_kind == 'finished',
            'is_manufacturable': line.is_manufacturable,
            'product_id': line.product_id.id,
            'product_name': line.product_id.display_name,
            'sale_status': line.sale_status,
            'stock_status': line.stock_status,
            'purchase_status': line.purchase_status,
            'production_status': line.production_status,
            'delivery_status': line.delivery_status,
            'severity': line.severity,
            'failures': [
                {
                    'node': failure.node,
                    'summary': failure.summary,
                    'origin_id': failure.origin_product_id.id,
                    'origin_name': failure.origin_product_id.display_name,
                }
                for failure in line.failure_ids
            ],
            'failure_summary': line.failure_summary or '',
        }

    # ══════════════════════════════════════════════════════════════════════
    # RECOLECCION DE DATOS (solo para ESTE pedido)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_sale_lines_to_show(self, so):
        """Líneas de venta que el diagnóstico considera del pedido.

        Filtro EXACTO histórico: si hay líneas gestionadas por PrintFlow, se usan
        SOLO esas; si no, se cae a todos los productos no-servicio. Se mantiene
        en un único helper para que el mapa de demanda y la lista de líneas a
        mostrar (incluidas las ya entregadas) no se desincronicen.
        """
        managed = so.order_line.filtered(
            lambda l: l.product_id and not l.display_type
            and getattr(l, 'is_printflow_managed', False)
        )
        return managed or so.order_line.filtered(
            lambda l: l.product_id and not l.display_type
            and l.product_id.type != 'service'
        )

    def _get_demand_map(self, board, so, notices=None):
        """Demanda real del pedido: producto terminado (líneas de venta) e
        insumos (componentes de las MO activas o ESTIMADOS vía BoM).

        Devuelve ``{product.product: {'qty': float, 'uom': uom.uom, 'kind': str}}``.

        La UdM de referencia del mapa es SIEMPRE ``product.uom_id``: cada aporte
        (línea de venta o movimiento de consumo de MO) se convierte a esa UdM con
        ``_compute_quantity`` antes de acumular. Así dos líneas del mismo producto
        en UdM distintas (ej. Unidades y Docenas) consolidan en una sola cifra
        correcta en vez de sumar números en unidades heterogéneas.

        ``kind`` se fija en el primer encontrado: ``finished`` para líneas de
        venta, ``component`` para insumos de MO y ``estimated`` para insumos
        calculados desde la BoM cuando el pedido es de fabricación pero aún no
        tiene Orden de Fabricación (caso "SIN ORDEN"). Si un mismo producto
        aparece como terminado Y como componente, se conserva la primera
        clasificación (el orden es venta primero, luego MO): lo REAL manda.

        :param notices: lista opcional donde se anotan los productos terminados
            que no se pudieron estimar por no tener BoM.
        """
        demand = {}
        for line in self._pf_sale_lines_to_show(so):
            product = line.product_id
            # Solo cuenta la demanda PENDIENTE: una línea ya entregada (total o
            # de más) no necesita abastecimiento y no debe generar falla de
            # inventario (falso positivo de FONDO NEGRO en S07301).
            pending_qty = (line.product_uom_qty or 0.0) - (line.qty_delivered or 0.0)
            if pending_qty <= _EPS:
                continue
            entry = demand.setdefault(
                product,
                {'qty': 0.0, 'uom': product.uom_id, 'kind': 'finished',
                 # parent=None: un terminado no cuelga de nadie.
                 'parent': None},
            )
            entry['qty'] += line.product_uom._compute_quantity(
                pending_qty, product.uom_id)
        for mo in board.mrp_production_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            for move in mo.move_raw_ids.filtered(
                lambda m: m.product_id and m.state not in ('done', 'cancel')
            ):
                product = move.product_id
                # Parentesco ADITIVO: cada insumo de una MO se cuelga del
                # producto terminado de ESA MO (primer terminado que lo
                # consume). Si el producto ya venía de una venta, lo REAL manda
                # y se conserva su clasificación 'finished' sin padre.
                entry = demand.setdefault(
                    product,
                    {'qty': 0.0, 'uom': product.uom_id, 'kind': 'component',
                     'parent': mo.product_id},
                )
                entry['qty'] += move.product_uom._compute_quantity(
                    move.product_uom_qty or 0.0, product.uom_id)
        # B1.2: si es un pedido de fabricación, estima los insumos de los
        # terminados que aún NO tienen MO propia (explosión de BoM + consumo
        # dinámico). Es un cálculo bajo demanda, SOLO para este pedido.
        if board.procurement_type != 'purchase':
            self._add_estimated_components(board, so, demand, notices)
        return demand

    def _add_estimated_components(self, board, so, demand, notices):
        """Estima insumos vía BoM para terminados sin MO activa (caso "SIN ORDEN").

        Reglas de prioridad/deduplicación:
          * Lo REAL manda: si el insumo ya viene de una línea de venta o de una
            MO activa, la estimación se descarta (nunca se duplica).
          * Entre estimaciones del mismo insumo SÍ se suma: dos terminados
            distintos pueden compartir la misma materia prima y la demanda total
            debe reflejarlo.
          * Si un terminado no tiene BoM, no se inventan insumos: se anota el
            aviso en ``notices`` para que el diagnóstico lo explique.
        """
        if notices is None:
            notices = []

        # MOs activas agrupadas por producto terminado (lo REAL manda).
        mos_by_product = defaultdict(lambda: self.env['mrp.production'])
        for mo in board.mrp_production_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        ):
            if mo.product_id:
                mos_by_product[mo.product_id] |= mo

        finished_to_estimate = self.env['product.product']
        for product, data in demand.items():
            if data['kind'] != 'finished':
                continue
            if mos_by_product.get(product):
                continue  # Ya tiene MO real: no se estima.
            finished_to_estimate |= product
        if not finished_to_estimate:
            return

        # COBERTURA: un terminado que ya tiene existencia suficiente para su
        # demanda pendiente NO necesita producirse; especular sus insumos por
        # BoM solo aportaba contenciones fantasma (caso S07301: PLASTIFICACION
        # cubierta por existencia, insumo 14445 reservado por otros pedidos ->
        # "SOBREPEDIDO" que el tablero no ve). La única excepción es que el
        # tablero marque ``production_alert='no_order'`` (una ficha en producción
        # sin MO): ahí sí hay que estimar los materiales que faltan.
        covered = self._pf_covered_finished_products(board, demand, finished_to_estimate)

        # Mecanismo nativo de Odoo 17 (misma resolución que usa la MO real).
        bom_by_product = self.env['mrp.bom']._bom_find(finished_to_estimate)

        for product in finished_to_estimate:
            if product.id in covered:
                continue
            bom = bom_by_product.get(product)
            if not bom:
                notices.append(product.display_name)
                continue
            sale_line = so.order_line.filtered(
                lambda l, p=product: l.product_id == p and not l.display_type
            )[:1]
            self._accumulate_bom_estimate(demand, product, bom, sale_line)

    def _pf_covered_finished_products(self, board, demand, products):
        """Ids de terminados YA cubiertos por existencia para su demanda pendiente.

        Un terminado cubierto (``free_for_order >= required``) no necesita
        producirse, así que no tiene sentido explotar su BoM para inventar
        insumos. La compuerta solo aplica cuando la producción YA se ejecutó
        (``pf_has_done_mo``): en pedidos sin MO terminada, el wizard sigue
        estimando los insumos (análisis temprano de materiales). Se exceptúa el
        caso en que el tablero pida orden (``production_alert='no_order'``).

        Se reutiliza ``_get_order_stock_snapshot`` (la MISMA lectura de reservas
        que el resto del diagnóstico) para que "cubierto" y el semáforo de stock
        hablen de lo mismo. Es de SOLO LECTURA y acotado al pedido.
        """
        if not board.pf_has_done_mo or not products:
            return set()
        if board.production_alert == 'no_order':
            return set()
        snapshot = board._get_order_stock_snapshot(products)
        covered = set()
        for product in products:
            required = demand.get(product, {}).get('qty', 0.0)
            free = snapshot.get(product.id, {}).get('free_for_order', 0.0)
            if free >= required - _EPS:
                covered.add(product.id)
        return covered

    def _accumulate_bom_estimate(self, demand, finished_product, bom, sale_line):
        """Suma al mapa los insumos de una BoM aplicando el consumo dinámico.

        Cantidad base por línea = ``(bom_line.product_qty / bom.product_qty) *
        cantidad_terminada`` (la demanda ``finished`` en su UdM de referencia),
        tal como indica la especificación; se respeta la UdM de la línea de BoM.
        """
        finished_qty = demand[finished_product]['qty']
        factor = finished_qty / (bom.product_qty or 1.0)
        # La cantidad del terminado que manda es la PENDIENTE (la demanda del
        # mapa ya descontó lo entregado). Se usa también en las dimensiones y en
        # el insumo inyectado para no pedir material de la parte ya entregada.
        pending_line_qty = (
            (sale_line.product_uom_qty or 0.0) - (sale_line.qty_delivered or 0.0)
            if sale_line else finished_qty
        )
        dims = {
            'area': sale_line.dim_area if sale_line else 0.0,
            'height': sale_line.dim_height if sale_line else 0.0,
            'qty': pending_line_qty if sale_line else finished_qty,
            'sheets_qty': getattr(sale_line, 'sheets_qty', 0.0),
            'nesting_total_sheets': getattr(sale_line, 'nesting_total_sheets', 0),
            'nesting_pieces_per_sheet': getattr(sale_line, 'nesting_pieces_per_sheet', 0),
        }
        finished_tmpl = finished_product.product_tmpl_id
        for bom_line in bom.bom_line_ids:
            if not bom_line.product_id:
                continue
            self._add_estimated_component(
                demand,
                bom_line.product_id,
                finished_tmpl,
                dims,
                factor * (bom_line.product_qty or 0.0),
                bom_line.product_uom_id,
                parent_product=finished_product,
            )
        # Insumo inyectado desde la venta (mismo criterio que mrp.production.create).
        # Se pide solo por la cantidad PENDIENTE de la línea.
        if sale_line and sale_line.raw_material_id:
            self._add_estimated_component(
                demand,
                sale_line.raw_material_id,
                finished_tmpl,
                dims,
                pending_line_qty,
                sale_line.raw_material_id.uom_id,
                parent_product=finished_product,
            )

    def _add_estimated_component(
            self, demand, raw_product, finished_tmpl, dims, default_qty,
            default_uom, parent_product=None):
        """Agrega o consolida un insumo estimado en el mapa de demanda.

        Reproduce el redondeo que aplica ``_apply_raw_consumption_qtys`` en la MO
        real (UdM de consumo si la regla la define, o la UdM del movimiento) y
        normaliza la cantidad a ``product.uom_id`` (la UdM del mapa).

        ``parent_product`` (aditivo) es el terminado del que cuelga el insumo:
        alimenta la jerarquía por producto del diagnóstico por niveles.
        """
        existing = demand.get(raw_product)
        if existing and existing['kind'] in ('finished', 'component'):
            return  # Lo REAL manda.
        Production = self.env['mrp.production']
        raw_tmpl = raw_product.product_tmpl_id
        qty = Production._raw_consumption_qty_from_dims(
            raw_tmpl, finished_tmpl, dims, default_qty)
        rule = Production._find_consumption_rule(raw_tmpl, finished_tmpl)
        qty_uom = rule.consumption_uom_id if rule and rule.consumption_uom_id else default_uom
        if qty_uom:
            qty = float_round(qty, precision_rounding=qty_uom.rounding)
        qty_ref = qty if (not qty_uom or qty_uom == raw_product.uom_id) else \
            qty_uom._compute_quantity(qty, raw_product.uom_id)
        if existing:
            existing['qty'] += qty_ref
            return
        demand[raw_product] = {
            'qty': qty_ref,
            'uom': raw_product.uom_id,
            'kind': 'estimated',
            'parent': parent_product,
        }

    def _get_incoming_map(self, products, purchase_orders, sale_name=None):
        """Unidades en camino de las PO vinculadas a este pedido (sin recibir).

        Recibe las órdenes de compra YA buscadas por el llamador (A5): así el
        snapshot las localiza UNA sola vez en vez de re-ejecutar el ``search``
        desde aquí. Devuelve ``{product_id: [(qty, uom), ...]}``.

        Con ``sale_name`` se devuelve la PORCIÓN propia del pedido (compras
        agrupadas: 1 OC = N pedidos); sin él, el comportamiento es IDÉNTICO al
        histórico (suma de los remanentes de todas las líneas).
        """
        incoming = {}
        if not products:
            return incoming
        if sale_name:
            order = self.env['sale.order'].search(
                [('name', '=', sale_name)], limit=1)
            if order:
                Remedy = self.env['printflow.stock.remedy']
                pos = purchase_orders or Remedy._pf_purchase_orders_for_sale(order)
                pos = pos.filtered(lambda p: p.state not in ('cancel', 'draft'))
                origin_names = Remedy._pf_origin_sale_names(pos)
                demand_map = Remedy._pf_demand_map(products, origin_names)
                for product in products:
                    own = Remedy._pf_own_portion(
                        product, order, purchase_orders=pos,
                        demand_by_so=demand_map.get(product.id, {}))
                    if own['incoming_own'] > _EPS:
                        incoming[product.id] = [
                            (own['incoming_own'], product.uom_id)]
            return incoming
        if not purchase_orders:
            return incoming
        pids = {p.id for p in products}
        for po in purchase_orders.filtered(lambda p: p.state not in ('cancel', 'draft')):
            for line in po.order_line:
                if line.product_id.id not in pids:
                    continue
                remaining = (line.product_qty or 0.0) - (line.qty_received or 0.0)
                if remaining > _EPS:
                    incoming.setdefault(line.product_id.id, []).append(
                        (remaining, line.product_uom)
                    )
        return incoming

    @api.model
    def _pf_is_personalized_supply_stolen(
            self, own_received, required, reserved_order, free_for_order):
        """Condición del caso f (tolerancia anti-falso-positivo), pura.

        Robo del abastecimiento propio: hay porción recibida (>0) y el pedido
        NO la tiene reservada (``reserved_order`` < menor entre requerido y
        recibido) y tampoco hay libre para él (``free_for_order`` < requerido).
        Si la porción propia SÍ está reservada, NO se marca.
        """
        if (own_received or 0.0) <= _EPS:
            return False
        return (
            (reserved_order or 0.0) < min(required or 0.0, own_received) - _EPS
            and (free_for_order or 0.0) < (required or 0.0) - _EPS
        )

    @api.model
    def _pf_portion_map(self, products, so, purchase_orders, stock_snapshot):
        """Porción propia por producto para la OC agrupada (una sola pasada).

        Reutiliza la demanda del grupo calculada UNA vez y el reservado del
        pedido del snapshot, para no provocar N+1. ``products`` puede ser lista
        o recordset.
        """
        result = {}
        if not products or not so:
            return result
        Remedy = self.env['printflow.stock.remedy']
        pos = purchase_orders
        if pos is None:
            pos = Remedy._pf_purchase_orders_for_sale(so)
        pos = pos.filtered(lambda p: p.state not in ('cancel', 'draft'))
        origin_names = Remedy._pf_origin_sale_names(pos)
        demand_map = Remedy._pf_demand_map(products, origin_names)
        for product in products:
            reserved = stock_snapshot.get(
                product.id, {}).get('reserved_order', 0.0)
            result[product.id] = Remedy._pf_own_portion(
                product, so, purchase_orders=pos,
                demand_by_so=demand_map.get(product.id, {}),
                reserved_order=reserved)
        return result

    @api.model
    def _selection_label(self, model_name, field_name, value):
        field = self.env[model_name]._fields.get(field_name)
        for key, label in (field.selection if field else []):
            if key == value:
                return label
        return value or ''

    # ══════════════════════════════════════════════════════════════════════
    # PRESENTACION (calculos de pantalla, sin tocar la logica de negocio)
    #
    # Ninguno de estos campos se almacena: se calculan bajo demanda a partir de
    # los campos que ya produce ``_build_snapshot``. Solo adaptan el contenido
    # a la interfaz (etiquetas cortas, formato de moneda, titular de causa raíz).
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('amount_total')
    def _compute_amount_total_display(self):
        """Copia el total a un Float de 2 decimales (el widget 'monetary' lo
        formatea con el símbolo de la moneda usando ESA precisión, porque el
        campo Monetary original expone la precisión de la moneda configurada)."""
        for rec in self:
            rec.amount_total_display = rec.amount_total or 0.0

    @api.depends('recommended_route')
    def _compute_recommended_route_short(self):
        """Etiquetas cortas de la ruta recomendada para el badge."""
        labels = {
            'purchase': _('Comprar'),
            'produce': _('Fabricar'),
            'reassign': _('Reasignar'),
            'receive': _('Recibir mercancía'),
            'design': _('Aprobar arte'),
            'deliver': _('Entregar'),
            'none': _('Solo diagnóstico'),
        }
        for rec in self:
            rec.recommended_route_short = labels.get(rec.recommended_route, '')

    @api.depends('stock_status', 'purchase_status', 'production_status')
    def _compute_summary_short(self):
        """Resúmenes de una línea para las tarjetas de la línea de tiempo.

        No llevan cifras a propósito: cualquier número formateado en Python
        volvería a mezclar separadores (punto/coma). Las cifras viven en los
        campos Float de las alertas y en la tabla por producto.
        """
        stock_labels = {
            'ok': _('Stock suficiente'),
            'deficit': _('Falta stock físico'),
            'over': _('Stock en contención'),
            'na': _('Sin evaluar'),
        }
        purchase_labels = {
            'ok': _('Sin pendientes'),
            'missing': _('Falta comprar'),
            'pending': _('Por recibir'),
            'na': _('No aplica'),
        }
        production_labels = {
            'ok': _('Al día'),
            'design': _('Arte pendiente'),
            'no_mo': _('Sin orden de fabricación'),
            'material': _('Falta material'),
            'late': _('Retraso'),
            'to_launch': _('Sin lanzar'),
            'no_supply': _('Sin insumos'),
            'in_progress': _('OF en proceso'),
            'na': _('No aplica'),
        }
        for rec in self:
            rec.stock_summary_short = stock_labels.get(rec.stock_status, '')
            rec.purchase_summary_short = purchase_labels.get(rec.purchase_status, '')
            rec.production_summary_short = production_labels.get(rec.production_status, '')

    @api.depends('root_cause_detail')
    def _compute_root_cause_display(self):
        """Separa el detalle largo de la causa raíz.

        * ``root_cause_headline``: la primera línea (mensaje corto a destacar).
        * ``root_cause_notes``: los avisos que NO son el desglose por producto
          (las líneas de producto empiezan por '-'), porque ese desglose ya se
          muestra en la tabla "Matemática del problema".
        """
        for rec in self:
            lines = [
                line.strip()
                for line in (rec.root_cause_detail or '').splitlines()
                if line.strip()
            ]
            rec.root_cause_headline = lines[0] if lines else ''
            notes = [line for line in lines[1:] if not line.startswith('-')]
            rec.root_cause_notes = '\n'.join(notes)

    # ══════════════════════════════════════════════════════════════════════
    # CONSTRUCCION DEL DIAGNOSTICO
    # ══════════════════════════════════════════════════════════════════════
    def _pf_display_only_line_vals(self, so, demand_products):
        """Filas TERMINADAS para productos del pedido sin demanda pendiente.

        MEJORA A: una línea 100% entregada ya no genera demanda (ver
        ``_get_demand_map``), pero debe seguir VIÉNDOSE en "Productos del
        pedido". Estas filas van con todos los números en 0 y la marca interna
        ``_is_display_only`` para que el motor NO se consulte por ellas. No
        consultan quants: no representan necesidad alguna.
        """
        vals = []
        for line in self._pf_sale_lines_to_show(so):
            product = line.product_id
            if product in demand_products:
                continue
            vals.append({
                'product_id': product.id,
                'line_kind': 'finished',
                'required_qty': 0.0,
                'on_hand_qty': 0.0,
                'reserved_qty': 0.0,
                'free_qty': 0.0,
                'order_reserved_qty': 0.0,
                'warehouse_free_qty': 0.0,
                'contention_qty': 0.0,
                'is_contention': False,
                'incoming_qty': 0.0,
                'deficit_qty': 0.0,
                'is_over_reserved': False,
                'uom_id': product.uom_id.id,
                '_parent_product_id': None,
                '_is_display_only': True,
            })
        return vals

    def _build_snapshot(self, board):
        """Calcula el diagnóstico completo a partir SOLO del tablero (A6).

        No lee ningún campo transitorio del wizard: recibe el ``board`` explícito
        para poder invocarse desde ``create()`` antes de que el registro exista.
        Devuelve ``(vals, line_vals)`` listos para mezclar en el ``create``.
        """
        so = board.sale_order_id
        vals = {
            'sale_status': 'na', 'stock_status': 'na',
            'purchase_status': 'na', 'production_status': 'na',
            'delivery_status': 'na',
            'sale_summary': '', 'stock_summary': '',
            'purchase_summary': '', 'production_summary': '',
            'root_cause_node': False, 'root_cause_detail': '',
            'has_deficit': False, 'deficit_total': 0.0,
            'incoming_total': 0.0, 'over_reserved_total': 0.0,
            'recommended_route': 'none',
        }
        if not so:
            vals['root_cause_detail'] = _('El pedido no tiene venta asociada.')
            return vals, []

        # ── Nodo 1: Venta / POS ─────────────────────────────────────────
        sale_map = {'cancel': 'error', 'draft': 'pending', 'sent': 'pending',
                    'sale': 'ok', 'done': 'ok'}
        vals['sale_status'] = sale_map.get(so.state, 'pending')
        # Resumen CORTO para la tarjeta: sin montos (el total se muestra aparte
        # como campo monetario) y en español. Antes se armaba con ``%.2f`` y el
        # código ISO de la moneda ("Sales Order - 11518.75 VE"), lo que metía un
        # separador decimal anglosajón y un símbolo equivocado en la pantalla.
        sale_state_labels = {
            'done': _('Completado'),
            'sale': _('Confirmado'),
            'draft': _('Borrador'),
            'sent': _('Enviado'),
            'cancel': _('Cancelado'),
        }
        vals['sale_summary'] = sale_state_labels.get(
            so.state, self._selection_label('sale.order', 'state', so.state))

        # ── Nodo 2: Inventario (falta física vs contención de ESTE pedido) ──
        estimate_notices = []
        demand = self._get_demand_map(board, so, notices=estimate_notices)
        products = list(demand.keys())
        # A5: las PO se localizan UNA sola vez y se reutilizan para las entrantes.
        purchase_orders = board._find_purchase_orders_by_sale_names([so.name])
        # Porción propia (OC agrupada 1:N) para la matemática del pedido; y el
        # total global solo como contexto. Con un único pedido, propios y global
        # coinciden (paridad histórica).
        incoming = self._get_incoming_map(products, purchase_orders, sale_name=so.name)
        incoming_global = self._get_incoming_map(products, purchase_orders)
        # B2: ÚNICA lectura de quants/reservas del diagnóstico. El helper del
        # tablero separa el reservado de ESTE pedido del reservado por OTROS.
        stock_snapshot = board._get_order_stock_snapshot(products, incoming=incoming)
        portion_by_pid = self._pf_portion_map(
            products, so, purchase_orders, stock_snapshot)

        line_vals = []
        deficit_total = 0.0        # FALTA FÍSICA: obliga a comprar/fabricar.
        incoming_total = 0.0
        contention_total = 0.0     # CONTENCIÓN: lo tienen reservado otros pedidos.
        engine = self.env['printflow.order.health.engine']
        for product, data in demand.items():
            pid = product.id
            # La UdM del mapa es siempre product.uom_id (ver _get_demand_map).
            target = data['uom'] or product.uom_id
            snap = stock_snapshot.get(pid, _EMPTY_STOCK_SNAPSHOT)
            # stock.quant ya expresa cantidad/reservado en la UdM de referencia
            # del producto, por lo que no hay que reconvertir.
            on_hand = snap['on_hand']
            reserved_order = snap['reserved_order']
            free_for_order = snap['free_for_order']
            inc = snap['incoming']
            required = data['qty']
            # Global (solo contexto): suma cruda de todas las líneas del grupo.
            global_inc = 0.0
            for qty, uom in incoming_global.get(pid, []):
                global_inc += (uom or target)._compute_quantity(qty, target)
            portion = portion_by_pid.get(pid, {})
            # Falta física: ni el stock físico ni lo que viene en camino cubren
            # la demanda. Es lo que realmente obliga a comprar o fabricar.
            physical_shortfall = max(0.0, required - on_hand - inc)
            # Contención: el pedido no consigue su parte porque otros pedidos
            # tienen reservado el stock. No hay que comprar: hay que reasignar.
            contention = max(
                0.0,
                (required - reserved_order - inc) - max(0.0, free_for_order),
            )
            if physical_shortfall > _EPS:
                # Si falta stock físico, la parte no disponible NO es contención
                # de otros: simplemente no existe. La contención solo aplica
                # cuando el stock físico alcanza para la demanda.
                contention = 0.0
            if engine._pf_skips_inventory(product):
                # Los productos que NO gestionan inventario (consumible/servicio
                # sin compra por pedido) no tienen quants: se tratan como
                # satisfechos, igual que el tablero. Se anulan AMBOS para no
                # inventar un falso "Sobrepedido" (contención).
                physical_shortfall = 0.0
                contention = 0.0
            is_contention = contention > _EPS
            deficit_total += physical_shortfall
            incoming_total += inc
            contention_total += contention
            line_vals.append({
                'product_id': pid,
                'line_kind': data['kind'],
                'required_qty': required,
                'on_hand_qty': on_hand,
                # reserved_qty / free_qty ya reflejan la atribución a ESTE pedido.
                'reserved_qty': reserved_order,
                'free_qty': free_for_order,
                # Campos explícitos con la nueva semántica de la PARTE B2.
                'order_reserved_qty': reserved_order,
                'warehouse_free_qty': free_for_order,
                'contention_qty': contention,
                'is_contention': is_contention,
                'incoming_qty': inc,
                'deficit_qty': physical_shortfall,
                # is_over_reserved se mantiene como alias de is_contention para
                # no romper la decoración de la vista ni el árbol _order.
                'is_over_reserved': is_contention,
                'uom_id': target.id,
                # ── Atribución por PORCIÓN (OC agrupada 1:N) ──────────────
                # ``incoming_qty`` es la porción PROPIA; el global queda solo
                # como contexto. Los importes de porción alimentan el caso f.
                'incoming_global_qty': global_inc,
                'own_supply_qty': portion.get('own_supply_qty', 0.0),
                'own_received_qty': portion.get('own_received_qty', 0.0),
                'incoming_own': portion.get('incoming_own', 0.0),
                'own_reserved_qty': portion.get('own_reserved_qty', 0.0),
                'own_portion_kind': portion.get('own_portion_kind', 'none'),
                'origin_group': portion.get('origin_group', ''),
                # ADITIVO: producto terminado del que cuelga este insumo
                # (None para los terminados). Clave interna: se separa antes de
                # crear las líneas y alimenta la jerarquía por niveles.
                '_parent_product_id': data['parent'].id if data.get('parent') else None,
            })
        line_vals.sort(key=lambda v: (v['deficit_qty'], v['is_over_reserved']), reverse=True)
        # MEJORA A: agrega las líneas SIN demanda (ya entregadas) como filas
        # terminadas de solo display, DESPUÉS de ordenar la demanda y ANTES de
        # anotar. Así el operador ve todos los productos del pedido y el motor
        # solo se consulta por los que sí tienen necesidad (paridad intacta).
        line_vals += self._pf_display_only_line_vals(so, set(demand.keys()))
        # ── Nodo 5: Entrega (fuente ÚNICA: snapshot de entrega del pedido) ──
        # Compuerta semántica: solo se evalúa en etapa de entrega; antes -> 'na'.
        delivery_snapshot = {}
        if board.state in ('ready', 'partial_delivered', 'delivered'):
            delivery_snapshot = self.env['sale.order']._pf_delivery_snapshot(
                [so.id]).get(so.id) or {}
            if delivery_snapshot.get('all_delivered'):
                vals['delivery_status'] = 'ok'
            elif delivery_snapshot.get('is_partial'):
                vals['delivery_status'] = 'partial'
            elif (delivery_snapshot.get('pending_line_count') or 0) > 0 \
                    and not (delivery_snapshot.get('delivered_line_count') or 0):
                vals['delivery_status'] = 'pending'
        # ADITIVO: anota cada línea con su semáforo por nodo, causa raíz,
        # resumen de fallas y metadata de jerarquía. No altera la detección.
        self._pf_annotate_lines(board, so, line_vals, delivery_snapshot)

        vals['deficit_total'] = deficit_total
        vals['incoming_total'] = incoming_total
        vals['over_reserved_total'] = contention_total
        vals['has_deficit'] = deficit_total > _EPS

        # El nodo INVENTARIO ya NO se copia ciegamente del semáforo del tablero:
        # se cruza con el desglose numérico por producto de ESTE pedido. Regla de
        # PRECEDENCIA (de mayor a menor prioridad):
        #   1. Pedido no confirmado              -> 'na'.
        #   2. El desglose detecta falta física  -> 'deficit' (manda sobre todo).
        #   3. El desglose detecta contención    -> 'over' (lo tienen otros).
        #   4. En cualquier otro caso, se respeta el semáforo del tablero
        #      (health_stock: missing -> deficit, over -> over, ok -> ok).
        # La falta física tiene prioridad sobre la contención porque exige
        # comprar o fabricar; la contención se corrige reasignando reservas.
        # Así el nodo nunca contradice a la matemática ni a la ruta sugerida.
        if so.state in ('draft', 'sent', 'cancel'):
            vals['stock_status'] = 'na'
        elif deficit_total > _EPS:
            vals['stock_status'] = 'deficit'
        elif contention_total > _EPS:
            vals['stock_status'] = 'over'
        else:
            vals['stock_status'] = {
                'ok': 'ok', 'over': 'over', 'missing': 'deficit',
            }.get(board.health_stock or 'ok', 'ok')
        vals['stock_summary'] = self._stock_summary(vals, line_vals)

        # ── Nodo 3: Compras ─────────────────────────────────────────────
        if so.state in ('draft', 'sent', 'cancel'):
            vals['purchase_status'] = 'na'
            vals['purchase_summary'] = _('Sin compras (pedido no confirmado).')
        else:
            supply_map = {'ok': 'ok', 'missing': 'missing', 'pending': 'pending'}
            vals['purchase_status'] = supply_map.get(board.health_supply or 'ok', 'ok')
            vals['purchase_summary'] = self._purchase_summary(board, vals['purchase_status'])

        # ── Nodo 4: Fabricación ─────────────────────────────────────────
        # El nodo FABRICACIÓN se lee del semáforo health_production (mismos
        # estados que el badge): ok / design / no_mo / material / late.
        if so.state in ('draft', 'sent', 'cancel'):
            vals['production_status'] = 'na'
        else:
            health_prod = board.health_production or 'ok'
            # En productos de compra sin incidencias mostramos N/A (no hay nada
            # que fabricar); si hay arte pendiente, se respeta el semáforo.
            if health_prod == 'ok' and board.procurement_type == 'purchase':
                vals['production_status'] = 'na'
            else:
                vals['production_status'] = health_prod
        # La OF SIN INSUMOS gana sobre "sin lanzar": el quiebre real está en el
        # ALMACÉN INSUMOS (raíz), no en Fabricación (consecuencia). El veredicto
        # NO se recalcula aquí: se ESPEJA el que el motor ya dio por línea en
        # ``_pf_annotate_lines`` (fuente única). Gate estrecho: solo el caso
        # 'to_launch' se afina, para conservar la paridad del head en el resto.
        if vals['production_status'] == 'to_launch':
            if any(lv.get('line_kind') == 'finished'
                   and lv.get('production_status') == 'no_supply'
                   for lv in line_vals):
                vals['production_status'] = 'no_supply'
        vals['production_summary'] = self._production_summary(board, vals['production_status'])

        # ── Causa raiz y ruta recomendada ───────────────────────────────
        root, detail = self._root_cause(board, vals, line_vals)
        if estimate_notices:
            # No se pudo estimar (sin BoM): se deja constancia sin romper el flujo.
            notes = [
                _('No se pudo estimar los insumos de "%s" (sin BoM).') % name
                for name in estimate_notices
            ]
            detail = (detail + '\n' if detail else '') + '\n'.join(notes)
        vals['root_cause_node'] = root
        vals['root_cause_detail'] = detail
        vals['recommended_route'] = self._recommend_route(board, vals, deficit_total)
        return vals, line_vals

    def _stock_summary(self, vals, line_vals):
        if vals['stock_status'] == 'na':
            return _('Sin evaluar (pedido no confirmado).')
        gaps = [l for l in line_vals if l['deficit_qty'] > _EPS or l['is_over_reserved']]
        if not gaps:
            # El semáforo del tablero marca una incidencia, pero el desglose
            # numérico por producto no la respalda: se avisa sin contradecir.
            if vals['stock_status'] == 'deficit':
                return _('El semáforo marca sin stock, pero el desglose por producto no lo refleja: revisa la orden de fabricación.')
            if vals['stock_status'] == 'over':
                return _('El semáforo marca sobrepedido (contención), pero el desglose por producto no lo refleja: revisa las reservas del pedido.')
            return _('Stock suficiente para la demanda del pedido.')
        if vals['stock_status'] == 'over':
            return _('%d producto(s) en contención (el stock lo tienen otros pedidos). Contención: %.2f. Falta física: %.2f.') % (
                len(gaps), vals['over_reserved_total'], vals['deficit_total'])
        return _('%d producto(s) con déficit (falta física de stock). Déficit: %.2f. En camino: %.2f.') % (
            len(gaps), vals['deficit_total'], vals['incoming_total'])

    def _purchase_summary(self, board, status):
        if status == 'na':
            return _('No aplica (el producto no gestiona inventario).')
        if status == 'missing':
            detail = board.pending_purchase_components or ''
            return _('Falta generar la compra. %s') % detail if detail else _('Falta generar la compra.')
        if status == 'pending':
            return _('La compra existe pero el albarán de entrada no está validado.')
        return _('Sin compras pendientes.')

    def _production_summary(self, board, status):
        if status == 'na':
            return _('No aplica (producto de compra).')
        if status == 'no_mo':
            return _('No existe Orden de Fabricación para el pedido.')
        if status == 'to_launch':
            return _('La orden de fabricación está sin lanzar (en borrador).')
        if status == 'in_progress':
            return _('La orden de fabricación está lanzada y en proceso.')
        if status == 'no_supply':
            return _('La orden de fabricación no tiene insumos cargados.')
        if status == 'design':
            return _('El arte está pendiente de aprobación del cliente.')
        missing = board.material_missing_count or 0
        total = board.material_total_count or 0
        if status == 'material':
            return _('Faltan %(missing)s de %(total)s materiales.') % {'missing': missing, 'total': total}
        if status == 'late':
            return _('Más de 24h sin material (%(missing)s de %(total)s).') % {'missing': missing, 'total': total}
        return _('Materiales completos (%(total)s).') % {'total': total}

    def _root_cause(self, board, vals, line_vals):
        sale = vals['sale_status']
        stock = vals['stock_status']
        purchase = vals['purchase_status']
        production = vals['production_status']
        delivery = vals.get('delivery_status') or 'na'

        # Precedencia CANÓNICA (fuente única): el motor de salud decide el nodo
        # de quiebre. Fabricación trabada (incl. SIN LANZAR) gana sobre el
        # déficit de stock.
        root = self.env['printflow.order.health.engine']._pf_root_cause_node(
            {
                'sale_status': sale,
                'stock_status': stock,
                'purchase_status': purchase,
                'production_status': production,
                'delivery_status': delivery,
            },
            vals.get('deficit_total') or 0.0,
        )

        if not root:
            return False, _(
                'El flujo del pedido no muestra quiebres: venta, inventario, '
                'compras, fabricación y entrega están en orden.')

        parts = []
        if root == 'sale':
            parts.append(_('El pedido de venta no está confirmado (estado: %s). '
                           'Confírmalo para generar la operación.')
                         % self._selection_label('sale.order', 'state', board.sale_order_id.state))
        if root == 'stock':
            parts.append(self._root_stock_text(vals, line_vals))
        if root == 'purchase':
            parts.append(_('El abastecimiento está incompleto: %s') % self._purchase_summary(board, purchase))
        if root == 'production':
            parts.append(_('La fabricación está trabada: %s') % self._production_summary(board, production))
        if root == 'supply':
            parts.append(_(
                'La Orden de Fabricación no tiene insumos cargados: %s')
                % self._production_summary(board, production))
        if root == 'delivery':
            parts.append(_('La entrega está pendiente: %s')
                         % self._delivery_summary(board, delivery))
        return root, '\n'.join(parts)

    def _delivery_summary(self, board, status):
        """Microcopy del nodo Entrega (mismo criterio que la falla del motor)."""
        if status == 'partial':
            return _('el pedido está listo pero sólo se ha entregado una parte; '
                     'valida el albarán pendiente cuando el cliente lo reciba.')
        return _('el producto está listo pero todavía no se le ha entregado al '
                 'cliente; valida el albarán de entrega.')

    def _root_stock_text(self, vals, line_vals):
        """Texto de la causa raíz de inventario.

        Distingue explícitamente las dos causas B2: falta física (comprar/
        fabricar) vs contención (el stock existe pero lo tienen otros pedidos).

        A5: se recolectan todos los ids de producto y UdM, se traen en un solo
        ``browse`` en lote y se resuelven en diccionarios antes del bucle, para
        no disparar una consulta N+1 por línea.
        """
        gaps = [
            l for l in line_vals
            if l['deficit_qty'] > _EPS or l['is_over_reserved']
        ]
        product_ids = list({l['product_id'] for l in gaps})
        uom_ids = list({l['uom_id'] for l in gaps if l.get('uom_id')})
        product_names = dict(zip(
            product_ids,
            self.env['product.product'].browse(product_ids).mapped('display_name'),
        ))
        uom_names = dict(zip(
            uom_ids,
            self.env['uom.uom'].browse(uom_ids).mapped('name'),
        ))
        lines = []
        for l in gaps:
            product = product_names.get(l['product_id'], '')
            kind = {
                'finished': _('producto terminado'),
                'component': _('insumo/materia prima'),
                'estimated': _('insumo estimado (sin MO)'),
            }.get(l['line_kind'], l['line_kind'] or '')
            uom = uom_names.get(l['uom_id']) or ''
            lines.append(_(
                "  - '%(product)s' (%(kind)s) requiere %(req).2f %(uom)s; "
                "hay %(on_hand).2f, reservado por el pedido %(reserved).2f, "
                "libre para el pedido %(free).2f; en camino %(incoming).2f; "
                "falta física %(deficit).2f; contención %(contention).2f."
            ) % {
                'product': product, 'kind': kind, 'uom': uom,
                'req': l['required_qty'], 'on_hand': l['on_hand_qty'],
                'reserved': l['order_reserved_qty'], 'free': l['warehouse_free_qty'],
                'incoming': l['incoming_qty'], 'deficit': l['deficit_qty'],
                'contention': l['contention_qty'],
            })
        header = _('Inventario: falta stock físico; hay que comprar o fabricar.')
        if vals['stock_status'] == 'over':
            header = _('Inventario: el stock existe pero está comprometido; '
                       'lo tienen reservado otros pedidos (contención). '
                       'No hay que comprar: hay que reasignar.')
        return header + ('\n' + '\n'.join(lines) if lines else '')

    def _recommend_route(self, board, vals, deficit_total):
        """Ruta recomendada según la causa real del inventario.

        B2: si hay FALTA FÍSICA se compra/fabrica; si solo hay CONTENCIÓN (el
        stock existe pero lo tienen otros pedidos) se REASIGNA, nunca se compra.
        """
        stock = vals['stock_status']
        purchase = vals['purchase_status']
        production = vals['production_status']
        delivery = vals.get('delivery_status') or 'na'

        if deficit_total > _EPS:
            if board.procurement_type == 'purchase' or purchase == 'missing':
                return 'purchase'
            if purchase == 'pending':
                return 'receive'
            if production in ('no_mo', 'material', 'late', 'to_launch', 'no_supply'):
                return 'produce'
            return 'purchase'
        if stock == 'over':
            return 'reassign'
        if purchase == 'pending':
            return 'receive'
        if production == 'design':
            return 'design'
        if production in ('no_mo', 'material', 'late', 'to_launch', 'no_supply'):
            return 'produce'
        # Sin déficit/stock/compra/fabricación pendientes: si el pedido está en
        # etapa de entrega y aún no se entregó (parcial o total), hay que entregar.
        if delivery in ('pending', 'partial'):
            return 'deliver'
        return 'none'

    # ══════════════════════════════════════════════════════════════════════
    # AVISO INFORMATIVO: ÓRDENES DE ENTREGA PENDIENTES DEL PRODUCTO
    #
    # Es un AVISO, no una falla: cuenta cuántos albaranes de entrega (outgoing,
    # no terminados) de OTROS orígenes contienen el producto. NO altera
    # ``severity``/``failed_node_count`` ni crea ``diagnostic.failure``. El
    # ancla es ``stock.move`` (los MOVIMIENTOS), NO las reservas: un albarán en
    # espera puede no tener reserva y aun así ser relevante para el aviso.
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_pending_delivery_pickings(self, board, product_ids):
        """Albaranes de entrega pendientes (ajenos al pedido) con esos productos.

        Definición de "pendiente": ``stock.picking`` de tipo ``outgoing`` con
        ``state`` distinto de ``done``/``cancel`` que tiene AL MENOS un
        movimiento (``stock.move``) no terminado de alguno de esos productos.
        Se EXCLUYEN los albaranes del PROPIO pedido
        (``board._get_delivery_pickings``). Lectura con ``sudo()``; cero escrituras.

        :param board: ``printflow.order.board`` del pedido (o recordset vacío).
        :param product_ids: iterable de ``product.product`` ids.
        :return: recordset de ``stock.picking``.
        """
        product_ids = [pid for pid in set(product_ids or []) if pid]
        if not product_ids:
            return self.env['stock.picking'].sudo()
        own = board._get_delivery_pickings().ids if board else []
        domain = [
            ('state', 'not in', ('done', 'cancel')),
            ('picking_type_id.code', '=', 'outgoing'),
            ('move_ids.product_id', 'in', product_ids),
            ('move_ids.state', 'not in', ('done', 'cancel')),
        ]
        if own:
            domain.append(('id', 'not in', own))
        return self.env['stock.picking'].sudo().search(
            domain, order='scheduled_date asc, id asc')

    @api.model
    def _pf_pending_delivery_counts(self, board, product_ids):
        """Cuenta, por producto, los albaranes de entrega ajenos pendientes.

        Una SOLA búsqueda para TODOS los productos (batch, sin N+1). Devuelve
        ``{product_id: count}``; cada albarán cuenta UNA vez por producto aunque
        tenga varias líneas del mismo. Es la base del aviso informativo.
        """
        counts = defaultdict(int)
        wanted = {pid for pid in (product_ids or []) if pid}
        if not wanted or not board:
            return counts
        pickings = self._pf_pending_delivery_pickings(board, wanted)
        for picking in pickings:
            pending_pids = set(picking.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
            ).mapped('product_id').ids)
            for pid in wanted & pending_pids:
                counts[pid] += 1
        return counts

    # ══════════════════════════════════════════════════════════════════════
    # ESTADO POR PRODUCTO/NODO (aditivo: NO reimplementa la deteccion)
    #
    # Traduce los números que YA calculó ``_build_snapshot`` (déficit,
    # contención, entrante) más los semáforos del tablero a un estado por nodo
    # y por línea. Usa el MISMO umbral que ``health_severity``.
    # ══════════════════════════════════════════════════════════════════════
    def _pf_annotate_lines(self, board, so, line_vals, delivery=None):
        """Anota cada línea con semáforo, nodos, jerarquía y fallas.

        El ESTADO por producto/nodo se calcula llamando al MOTOR de salud
        (``printflow.order.health.engine``), con los MISMOS datos que usa el
        tablero. Aquí NO se reimplementa ninguna regla: la única fuente de verdad
        es el motor, de modo que las fallas del wizard coincidan con el tablero.

        Paridad con el tablero:
          * El sobrepedido real se toma de ``_pf_over_reserved_products``
            (libre AGREGADO < 0) y solo aplica bajo la compuerta del tablero
            (pedido en etapa de entrega y con MO hecha o compra recibida).
          * La reserva colgada (quant con libre < 0 compensado) se toma de
            ``_pf_reservation_anomaly_products`` y genera la falla
            ``data_anomaly``, nunca "Sobrepedido" (Bloque III, §27).
          * Las MO se separan por producto en ``active`` / ``done`` (misma
            clasificación que ``_pf_build_order_inputs``): una MO ``done`` cuenta
            como existente y NO dispara el falso "Sin orden de fabricación".
          * La entrega por producto sale del MISMO helper que usa el tablero
            (``delivery``), no de una fórmula nueva.

        :param dict delivery: snapshot de entrega del pedido (o ``{}``).
        """
        if not line_vals:
            return
        # Aviso informativo (NO falla): órdenes de entrega pendientes por
        # producto. Una SOLA búsqueda para todos los terminados del pedido.
        finished_pids = {
            lv['product_id'] for lv in line_vals
            if lv.get('line_kind') == 'finished'
        }
        pending_delivery_counts = self._pf_pending_delivery_counts(
            board, finished_pids)
        engine = self.env['printflow.order.health.engine']
        # Clasificador único de remedios: se instancia UNA vez fuera del loop.
        Remedy = self.env['printflow.stock.remedy']
        # Entrega: estado por producto del helper compartido con el tablero. La
        # compuerta es la etapa de entrega (incluye 'delivered'); antes -> 'na'.
        delivery_stage = board.state in ('ready', 'partial_delivered', 'delivered')
        delivery_products = (delivery or {}).get('products') or {}
        delivery_product_qty = (delivery or {}).get('product_qty') or {}
        # Fabricabilidad de TODOS los productos del pedido en UNA sola llamada
        # (BoM o ruta de fabricación): misma fuente de verdad que el tablero.
        manufacturable = engine._pf_manufacturable_products(
            self.env['product.product'].browse(
                [lv['product_id'] for lv in line_vals]))
        sale_status = {'cancel': 'error', 'draft': 'pending', 'sent': 'pending',
                       'sale': 'ok', 'done': 'ok'}.get(so.state, 'pending')
        unconfirmed = so.state in ('draft', 'sent', 'cancel')

        # MO activas/hechas/borrador por producto. La clasificación es la MISMA
        # fuente que el tablero (``_pf_classify_mos``): 'active' = no terminadas
        # (incluye borrador); 'draft' permite detectar la OF sin lanzar.
        mos_by_product = defaultdict(list)
        for mo in board.mrp_production_ids.filtered(
                lambda m: m.state != 'cancel'):
            if mo.product_id:
                mos_by_product[mo.product_id.id].append(mo)
        production_by_product = {}
        for pid, product_mos in mos_by_product.items():
            buckets = engine._pf_classify_mos(product_mos)
            production_by_product[pid] = {
                'active': buckets['non_done'],
                'done': buckets['done'],
                'draft': buckets['draft'],
            }

        # Compuerta del tablero para la sobre-reserva global: solo cuenta si el
        # pedido está en etapa de entrega y ya tiene MO hecha o compra recibida.
        # Además solo se evalúan productos con demanda PENDIENTE real: si la
        # línea ya está entregada (required_qty == 0) no debe marcarse aunque su
        # quant global esté sobre-reservado (falso positivo de S07301).
        in_delivery_stage = board.state in ('ready', 'partial_delivered')
        # Etapa de FABRICACIÓN/entrega: gatea el ``to_launch`` (la OF sin lanzar
        # solo es un bloqueo cuando el pedido ya entró a taller).
        in_production_stage = board.state in (
            'in_production', 'ready', 'partial_delivered')
        over_reserved = set()
        reservation_anomaly = set()
        if in_delivery_stage and (board.pf_has_done_mo or board.pf_incoming_done):
            pending_pids = [
                lv['product_id'] for lv in line_vals
                if (lv.get('required_qty') or 0.0) > _EPS
            ]
            # Criterio ÚNICO (Bloque III, §27): "sobre" es libre AGREGADO < 0;
            # el quant suelto negativo compensado se expone como anomalía.
            over_reserved = engine._pf_over_reserved_products(pending_pids)
            reservation_anomaly = engine._pf_reservation_anomaly_products(
                pending_pids)

        # Artes pendientes por producto (misma señal que el diagnóstico).
        design_pending = set()
        for sheet in so.mrp_technical_sheet_ids:
            if (getattr(sheet, 'has_design_service', False)
                    and getattr(sheet, 'design_status', False) == 'pending'
                    and sheet.sale_line_id.product_id):
                design_pending.add(sheet.sale_line_id.product_id.id)

        pending_purchase = set(board.pending_purchase_product_ids.ids)

        child_count = defaultdict(int)
        for lv in line_vals:
            parent_pid = lv.get('_parent_product_id')
            if parent_pid:
                child_count[parent_pid] += 1

        # Terminados YA cubiertos por existencia (misma regla de cobertura que la
        # estimación de insumos): si el terminado tiene stock suficiente y la
        # producción ya se ejecutó (MO terminada), no hace falta fabricarlo y el
        # motor no debe inventar un "SIN ORDEN" (falso positivo del caso S07301).
        covered_finished = set()
        if board.pf_has_done_mo:
            covered_finished = {
                lv['product_id'] for lv in line_vals
                if lv.get('line_kind') == 'finished'
                and (lv.get('warehouse_free_qty') or 0.0)
                    >= (lv.get('required_qty') or 0.0) - _EPS
            }

        for lv in line_vals:
            # MEJORA A: las filas de solo display (producto YA ENTREGADO) no
            # pasan por el motor: van sanas, sin fallas y sin componentes. Las
            # líneas con demanda siguen 100% por el motor (paridad intacta).
            if lv.get('_is_display_only'):
                pid = lv['product_id']
                lv['sale_status'] = 'ok'
                lv['stock_status'] = 'ok'
                lv['purchase_status'] = 'ok'
                lv['production_status'] = 'ok'
                # Fila de un producto YA entregado (sin demanda): entrega OK.
                lv['delivery_status'] = 'ok'
                lv['severity'] = 'ok'
                lv['root_cause_node'] = False
                lv['failed_node_count'] = 0
                lv['failure_summary'] = ''
                lv['_failure_vals'] = []
                lv['has_components'] = False
                lv['component_count'] = 0
                lv['is_manufacturable'] = pid in manufacturable
                # Aviso informativo (NO falla): el producto ya se entregó en
                # este pedido, pero puede seguir esperando en órdenes ajenas.
                lv['pending_delivery_order_count'] = pending_delivery_counts.get(
                    pid, 0)
                continue
            is_finished = lv['line_kind'] == 'finished'
            sale = sale_status if is_finished else 'na'
            pid = lv['product_id']
            product = self.env['product.product'].browse(pid)
            # Criterio único de "gestiona inventario": un consumible/servicio (o
            # un servicio) que NO sea compra por pedido no produce déficit ni
            # falta de compra. Se propaga al motor para que su veredicto coincida
            # con el tablero.
            is_stock_tracked = not engine._pf_skips_inventory(product)
            mos = production_by_product.get(pid) or {
                'active': [], 'done': [], 'draft': []}
            # Entrega: componentes/estimados -> 'na'; terminados -> helper; fuera
            # de la etapa de entrega -> 'na' (compuerta semántica).
            if is_finished and delivery_stage:
                delivery = delivery_products.get(pid, 'na')
            else:
                delivery = 'na'
            delivery_done, delivery_required = delivery_product_qty.get(
                pid, (None, None))

            # ── Estado por producto: SIEMPRE a través del motor ─────────
            # La bandera "OF sin insumos" se calcula UNA sola vez y viaja al
            # motor y al roll-up (``flow_supply_status``): así INSUMOS y
            # FABRICACIÓN comparten la misma lectura de la OF.
            mo_without_materials = engine._pf_mo_without_materials(
                mos['active'])
            production = engine._pf_product_production({
                'active_mos': mos['active'],
                'done_mos': mos['done'],
                'has_draft_mo': bool(mos['draft']),
                'mo_without_materials': mo_without_materials,
                'in_production_stage': in_production_stage,
                'procurement_type': board.procurement_type,
                'is_manufacturable': pid in manufacturable,
                'design_pending': pid in design_pending,
                'production_alert': board.production_alert or False,
                'in_delivery_stage': in_delivery_stage,
                'is_stock_covered': pid in covered_finished,
                'is_late_material': board.is_late_material,
            })
            stock = engine._pf_product_stock({
                'deficit_qty': lv['deficit_qty'],
                'contention_qty': lv['contention_qty'],
                'in_over_reserved': pid in over_reserved,
                'is_stock_tracked': is_stock_tracked,
            })
            purchase = engine._pf_product_supply({
                'purchase_ok': product.purchase_ok,
                'incoming_qty': lv['incoming_qty'],
                'deficit_qty': lv['deficit_qty'],
                'pending_product_ids': pending_purchase,
                'order_health_supply': board.health_supply,
                'product_id': pid,
                'is_stock_tracked': is_stock_tracked,
            })
            if unconfirmed:
                stock = 'na'
                purchase = 'na'
                production = 'na'

            severity = engine._pf_product_severity({
                'sale_status': sale,
                'stock_status': stock,
                'purchase_status': purchase,
                'production_status': production,
                'delivery_status': delivery,
                'reservation_anomaly': pid in reservation_anomaly,
            })

            # Nodo de quiebre: precedencia CANÓNICA única del motor de salud.
            root = engine._pf_root_cause_node(
                {
                    'sale_status': sale,
                    'stock_status': stock,
                    'purchase_status': purchase,
                    'production_status': production,
                    'delivery_status': delivery,
                },
                lv['deficit_qty'],
                is_stock_tracked=is_stock_tracked,
            )

            # Remedio FÍSICO del déficit: la MISMA fuente que el escáner. Solo
            # se clasifica cuando hay déficit (evita N+1 en líneas sanas).
            physical_remedy = (
                Remedy._pf_physical_remedy_key(product, lv['deficit_qty'])
                if stock == 'deficit' and product else False)
            # Fallas por nodo: ÚNICA fuente de verdad en el motor de salud.
            failures = engine._pf_product_failures({
                'sale_status': sale,
                'stock_status': stock,
                'purchase_status': purchase,
                'production_status': production,
                'delivery_status': delivery,
                'delivery_delivered': delivery_done,
                'delivery_required': delivery_required,
                'deficit_qty': lv['deficit_qty'],
                'contention_qty': lv['contention_qty'],
                'reservation_anomaly': pid in reservation_anomaly,
                'physical_remedy': physical_remedy,
                # Defensa espejo del motor: sin inventario no hay fallas
                # stock/compra.
                'is_stock_tracked': is_stock_tracked,
                # Arte pendiente: señal ADICIONAL del nodo Fabricación (no
                # reemplaza el estado de la OF, ver `_pf_product_production`).
                'design_pending': pid in design_pending,
            })
            # Caso f (personalizado con reparto): la porción PROPIA ya recibida
            # está retenida por otro pedido del grupo. Reclasifica SOLO la falla
            # de stock; exige las 4 condiciones simultáneas (tolerancia anti
            # falso-positivo). Solo aplica a productos `pf_purchase_on_order`.
            if (product.product_tmpl_id.pf_purchase_on_order
                    and (lv.get('own_received_qty') or 0.0) > _EPS):
                stolen = self._pf_is_personalized_supply_stolen(
                    lv.get('own_received_qty'),
                    lv.get('required_qty'),
                    lv.get('order_reserved_qty'),
                    lv.get('warehouse_free_qty'),
                )
                if stolen:
                    for failure in failures:
                        if failure.get('node') == 'stock':
                            failure['pf_cause'] = 'personalized_supply_stolen'
            lv['severity'] = severity
            lv['sale_status'] = sale
            lv['stock_status'] = stock
            lv['purchase_status'] = purchase
            lv['production_status'] = production
            lv['has_mo_without_materials'] = mo_without_materials
            lv['delivery_status'] = delivery
            lv['is_manufacturable'] = pid in manufacturable
            lv['root_cause_node'] = root
            lv['failed_node_count'] = len(failures)
            lv['failure_summary'] = ' · '.join(f['summary'] for f in failures)
            if is_finished:
                count = child_count.get(lv['product_id'], 0)
                lv['has_components'] = count > 0
                lv['component_count'] = count
            else:
                lv['has_components'] = False
                lv['component_count'] = 0
            lv['_failure_vals'] = failures
            # Aviso informativo: solo los terminados pueden tener albaranes de
            # entrega pendientes del producto; componentes/estimados quedan en 0.
            lv['pending_delivery_order_count'] = (
                pending_delivery_counts.get(pid, 0) if is_finished else 0)

    # ══════════════════════════════════════════════════════════════════════
    # RECALCULO BAJO DEMANDA (C1)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_refresh_board(self, board):
        """Recalcula el tablero ACOTADO a este pedido (anti-cascada).

        El wizard lee ``board.health_stock`` / ``health_supply`` /
        ``health_production`` como RESPALDO cuando el desglose numérico por
        producto no detecta déficit ni contención. Si esos semáforos quedaron
        VIEJOS (nadie recalculó la tarjeta tras cambiar reservas/entregas), el
        wizard mostraría un dato obsoleto (p.ej. SOBREPEDIDO fantasma).

        Se reutiliza ``recompute_states`` con un dominio de UNA sola tarjeta, por
        lo que NUNCA se recalcula el tablero completo. Devuelve el ``board`` ya
        fresco para encadenar la construcción del snapshot.
        """
        if board:
            board.recompute_states(domain=[('id', '=', board.id)])
        return board

    def action_recalculate(self):
        """Recalcula el diagnóstico sobre el MISMO wizard (sin recrearlo).

        Reutiliza ``_build_snapshot`` (única fuente de verdad del diagnóstico)
        y reemplaza las líneas con comandos que primero borran las anteriores
        (``(5, 0, 0)``) y luego crean las nuevas: así nunca quedan líneas
        huérfanas. Conserva la ``resolution_route`` elegida por el operador y
        PRESERVA el foco (``focus_line_id``), re-apuntando la línea al registro
        nuevo del MISMO producto. Devuelve la acción que recarga el wizard para
        que la UI muestre los números frescos.
        """
        self.ensure_one()
        focus_product_id = (
            self.focus_line_id.product_id.id if self.focus_line_id else False)
        # Refresca el tablero SOLO de este pedido antes de reconstruir el
        # diagnóstico: sin esto, el respaldo a los health_* almacenados podía
        # seguir mostrando un semáforo viejo (p.ej. SOBREPEDIDO persistente).
        self._pf_refresh_board(self.board_id)
        snapshot, line_vals = self._build_snapshot(self.board_id)
        commands, hierarchy = self._pf_split_line_commands(line_vals)
        snapshot['deficit_line_ids'] = [(5, 0, 0)] + commands
        self.write(snapshot)
        self._pf_apply_line_hierarchy(hierarchy)
        # Re-apunta el foco a la línea nueva del mismo producto. Si el producto
        # ya no forma parte del diagnóstico, se limpia el foco.
        if focus_product_id:
            new_focus = self.deficit_line_ids.filtered(
                lambda l: l.product_id.id == focus_product_id)[:1]
            self.write({'focus_line_id': new_focus.id if new_focus else False})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico y Ruta de Solución'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ══════════════════════════════════════════════════════════════════════
    # ENLACES DIRECTOS A LOS DOCUMENTOS DEL PEDIDO (C2)
    #
    # Wrappers finos: la lógica (y los UserError) viven en el tablero. Estos
    # nombres cortos permiten llamarlos desde el XML del wizard sin depender
    # de ``board_id.metodo`` en el árbol de nodos.
    # ══════════════════════════════════════════════════════════════════════
    def action_open_sale(self):
        """Abre el pedido de venta asociado al diagnóstico."""
        self.ensure_one()
        return self.board_id.action_open_sale_order()

    def action_open_stock_picking(self):
        """Abre el albarán de entrega (POS o venta) asociado al pedido."""
        self.ensure_one()
        return self.board_id.action_open_delivery_picking()

    def action_open_purchase(self):
        """Abre la(s) orden(es) de compra vinculadas a este pedido."""
        self.ensure_one()
        return self.board_id.action_open_purchase_order()

    def action_open_production(self):
        """Abre la Orden de Fabricación del pedido."""
        self.ensure_one()
        return self.board_id.action_open_production_order()

    # ══════════════════════════════════════════════════════════════════════
    # PUENTE AL ESCANER DE PRODUCTO (FASE 2) — solo añadidos
    #
    # Nivel 1 (pedido) -> Nivel 2 (producto). Se abre a pantalla completa
    # (target='current') para CERRAR este popup y evitar diálogos anidados.
    # El escáner declara el origen para poder "Volver" reabriendo este wizard.
    # ══════════════════════════════════════════════════════════════════════
    def action_scan_order_products(self):
        """Escanea todos los productos (no servicio) de las líneas del pedido."""
        self.ensure_one()
        board = self.board_id
        so = board.sale_order_id
        products = so.order_line.filtered(
            lambda line: line.product_id
            and not line.display_type
            and line.product_id.type != 'service'
        ).mapped('product_id')
        return self._pf_open_product_scanner(products, board)

    def _pf_open_product_scanner(self, products, board):
        """Crea el escáner de producto y devuelve su acción (pantalla completa)."""
        wizard = self.env['printflow.product.diagnostic.wizard'].create({
            'product_ids': [(6, 0, products.ids)],
            'origin': 'order',
            'origin_model': 'printflow.order.board',
            'origin_res_id': board.id,
            'origin_label': board.name or board.sale_order_id.name or '',
            'origin_action': 'action_open_diagnostic_wizard',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Producto'),
            'res_model': 'printflow.product.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ══════════════════════════════════════════════════════════════════════
    # EJECUCION DE LA RUTA ELEGIDA
    # ══════════════════════════════════════════════════════════════════════
    def action_apply_route(self):
        """Dispatcher: ejecuta la ruta elegida por el operador.

        C3: tras ejecutar con éxito una ruta deja una bitácora en el chatter
        del pedido ANTES de devolver la acción que cambia de pantalla. No se
        registra si la ruta es 'none' (solo diagnóstico) ni en 'reassign'
        (``_route_reassign`` ya publica su propio mensaje: no se duplica).
        """
        self.ensure_one()
        route = self.resolution_route
        if route == 'purchase':
            action = self._route_purchase()
        elif route == 'produce':
            action = self._route_produce()
        elif route == 'reassign':
            action = self._route_reassign()
        elif route == 'receive':
            action = self.board_id.action_receive_purchase_materials()
        elif route == 'design':
            action = self.board_id.action_approve_design_all()
        elif route == 'deliver':
            action = self._route_deliver()
        else:
            return {'type': 'ir.actions.act_window_close'}
        if route != 'reassign':
            self.board_id.message_post(
                body=self._route_log_message(route),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
        return action

    def _route_log_message(self, route):
        """Texto de la bitácora de la ruta ejecutada (C3)."""
        self.ensure_one()
        route_label = self._selection_label(self._name, 'resolution_route', route)
        return _(
            "Diagnóstico: se ejecutó la ruta '%(route)s' — déficit físico "
            "%(deficit).2f, contención %(contention).2f, en camino %(incoming).2f."
        ) % {
            'route': route_label,
            'deficit': self.deficit_total,
            'contention': self.over_reserved_total,
            'incoming': self.incoming_total,
        }

    def _route_purchase(self):
        """Abre la Compra Rápida pre-cargada con TODAS las líneas con faltante.

        A2: se recolectan TODAS las líneas con déficit positivo (no solo la
        primera) y se arma UN solo ``mrp.quick.purchase.wizard``. No se fuerza
        la recepción: cada línea nace con ``material_received`` en False.

        B2: aquí solo entra lo que FALTA FÍSICAMENTE. La contención (el stock
        existe pero lo tienen otros pedidos) se resuelve reasignando, así que si
        no hay falta física no se precargan líneas de compra: se abre la compra
        genérica del pedido (decisión explícita del operador).
        """
        self.ensure_one()
        board = self.board_id
        deficit_lines = self.deficit_line_ids.filtered(lambda l: l.deficit_qty > _EPS)
        if not deficit_lines:
            if board.has_purchase_on_order_component:
                return board.action_open_quick_purchase_component()
            return board.action_open_quick_purchase()
        lines = deficit_lines
        qty_of = lambda l: l.deficit_qty  # noqa: E731

        so = self.sale_order_id
        purchase_line_vals = []
        for line in lines:
            product = line.product_id
            vals = {
                'product_id': product.id,
                'product_qty': qty_of(line),
                'product_uom_id': (line.uom_id or product.uom_id).id,
                # No forzamos la recepción: primero se genera la PO y el operador
                # decide cuándo recibir (mantiene el inventario intacto).
                'material_received': False,
            }
            if product.seller_ids:
                vals['partner_id'] = product.seller_ids[0].partner_id.id
            if so.currency_id:
                vals['currency_id'] = so.currency_id.id
            purchase_line_vals.append((0, 0, vals))

        wizard = self.env['mrp.quick.purchase.wizard'].create({
            'sale_order_id': so.id,
            'purchase_line_ids': purchase_line_vals,
        })
        return {
            'name': _('Compra Rápida (déficit)'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.quick.purchase.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _route_deliver(self):
        """Abre la confirmación de entrega del pedido (reutiliza el tablero).

        No reimplementa la entrega: delega en ``action_validate_delivery`` del
        tablero, que abre el asistente con las líneas ya cargadas.
        """
        self.ensure_one()
        return self.board_id.action_validate_delivery()

    def _route_produce(self):
        """Abre / procesa la Orden de Fabricación del pedido."""
        self.ensure_one()
        board = self.board_id
        mos = board.sale_order_id.mrp_production_ids.filtered(
            lambda m: m.state not in ('done', 'cancel')
        )
        if not mos:
            raise UserError(_(
                'Este pedido no tiene una Orden de Fabricación activa. '
                'Genera primero la compra del insumo faltante.'))
        return board.action_view_production_order()

    def _route_reassign(self):
        """Libera y re-reserva los albaranes (delegando en el tablero).

        A3: toda la lógica vive en ``_fix_over_reservation_and_refresh()`` del
        tablero; aquí solo se arma la notificación del wizard (que sí cierra al
        terminar).
        """
        self.ensure_one()
        board = self.board_id
        still_missing = board._fix_over_reservation_and_refresh()
        if still_missing is None:
            raise UserError(_(
                'Este pedido no tiene albaranes de entrega pendientes de reserva.'))
        board.message_post(
            body=_('Se liberó y re-reservó el inventario desde el Diagnóstico de Pedido.'),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
        if still_missing:
            message = _('Se liberó la sobre-reserva, pero aún falta stock físico. '
                        'Revisa el inventario real antes de entregar.')
            ntype = 'warning'
        else:
            message = _('Reservas reajustadas al stock real del almacén.')
            ntype = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': message,
                'type': ntype,
                'sticky': ntype == 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class PrintflowOrderDiagnosticWizardLine(models.TransientModel):
    """Detalle por producto: falta física vs contención (la 'matemática' del problema)."""
    _name = 'printflow.order.diagnostic.wizard.line'
    _description = 'Detalle de déficit por producto (PrintFlow)'
    _order = 'deficit_qty desc, is_over_reserved desc'

    wizard_id = fields.Many2one(
        'printflow.order.diagnostic.wizard', string='Wizard', required=True, ondelete='cascade',
    )
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    line_kind = fields.Selection(
        [('finished', 'Producto terminado'),
         ('component', 'Insumo / materia prima'),
         ('estimated', 'Insumo estimado (sin MO)')],
        string='Tipo',
    )
    uom_id = fields.Many2one('uom.uom', string='UdM')
    required_qty = fields.Float(string='Requerido')
    on_hand_qty = fields.Float(string='En almacén')
    # B2 — atribución al pedido:
    reserved_qty = fields.Float(
        string='Reservado (pedido)',
        help='Cantidad reservada imputable a ESTE pedido (sus albaranes de entrega).',
    )
    free_qty = fields.Float(
        string='Libre (pedido)',
        help='Existencia del almacén menos lo reservado por OTROS pedidos: lo que '
             'este pedido podría llegar a reservar.',
    )
    incoming_qty = fields.Float(string='En camino')
    # B2 — campos explícitos de la nueva semántica:
    order_reserved_qty = fields.Float(
        string='Reservado del pedido',
        help='Reservado por los albaranes de entrega de ESTE pedido (mismo valor '
             'que reserved_qty, con nombre explícito).',
    )
    warehouse_free_qty = fields.Float(
        string='Libre para el pedido',
        help='Existencia menos lo reservado por OTROS pedidos (mismo valor que '
             'free_qty, con nombre explícito).',
    )
    deficit_qty = fields.Float(
        string='Falta física',
        help='max(0, requerido - existencia - en camino). Obliga a comprar o fabricar.',
    )
    contention_qty = fields.Float(
        string='Contención',
        help='Cantidad que el pedido necesita pero está reservada por OTROS pedidos.',
    )
    is_contention = fields.Boolean(
        string='En contención',
        help='True si el stock existe pero lo tienen reservado otros pedidos.',
    )
    is_over_reserved = fields.Boolean(
        string='Sobre-reservado',
        help='Alias histórico de is_contention (compatibilidad de vistas y del orden).',
    )

    def action_scan_product(self):
        """Escanea ESTE producto con el escáner de diagnóstico (FASE 2).

        Se abre a pantalla completa (``target='current'``) para cerrar el popup
        del diagnóstico de pedido y evitar diálogos anidados. El origen apunta
        al tablero para poder "Volver".
        """
        self.ensure_one()
        wizard = self.env['printflow.product.diagnostic.wizard'].create({
            'product_id': self.product_id.id,
            'origin': 'order',
            'origin_model': 'printflow.order.board',
            'origin_res_id': self.wizard_id.board_id.id,
            'origin_label': self.wizard_id.board_id.name or '',
            'origin_action': 'action_open_diagnostic_wizard',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Producto'),
            'res_model': 'printflow.product.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }