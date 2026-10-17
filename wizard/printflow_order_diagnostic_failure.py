# -*- coding: utf-8 -*-
"""Falla por nodo del diagnóstico de pedido (PrintFlow).

NUEVO TransientModel ``printflow.order.diagnostic.failure``: una fila por cada
NODO ROTO de una línea de producto/componente (venta, inventario, compras o
fabricación). Es de SOLO LECTURA: los tres botones del plan únicamente NAVEGAN.

Los textos y las tres acciones (problema / solución / recopilar) salen SIEMPRE
del ``printflow.resolution.playbook`` (única fuente de verdad). Aquí solo se
materializa el plan en campos de pantalla y se traduce su vocabulario de
navegación a acciones de Odoo.

BOTÓN UNIFICADO "SOLUCIONAR": desde que se retiró el botón "Recomendación",
``action_open_solution`` ejecuta el REMEDIO estructural (``pf_remedy_*``) cuando
``pf_remedy_available`` es True —ese campo es ahora el GATE de la unificación— y,
en cualquier otro caso, la SOLUCIÓN del playbook (``pf_solution_*``). No hace
falta una regla extra: ``pf_remedy_available`` ya significa "el remedio apunta a
un destino distinto al del plan", porque ``_pf_assign_remedy`` lo apaga por
anti-duplicación.

No agrega campos almacenados en modelos persistentes: cero migración.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.printflow_resolution_playbook import (
    PF_CAUSE_SELECTION,
    PLAN_ACTION_SELECTION,
)
from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_LABELS,
    PF_DIAG_CHAIN_ORDER,
)

# Nodos canónicos del diagnóstico de pedido (mismos valores que el wizard).
# ``supply`` (Almacén insumos) es un nodo propio de la cadena de fabricación: la
# OF sin insumos es su raíz.
NODE_SELECTION = [
    ('sale', 'Venta / POS'),
    ('stock', 'Inventario'),
    ('supply', 'Almacén insumos'),
    ('purchase', 'Compras'),
    ('production', 'Fabricación'),
    ('delivery', 'Entrega'),
]

SEVERITY_SELECTION = [
    ('ok', 'Saludable'),
    ('warning', 'Atención'),
    ('danger', 'Crítico'),
]

# Rol del nodo roto dentro de la CADENA DE FALLAS por niveles (FEATURE A).
PF_CHAIN_ROLE_SELECTION = [
    ('root', 'Raíz'),
    ('consequence', 'Consecuencia'),
    ('independent', 'Independiente'),
]

# Naturaleza de la traba de stock (árbol del Bloque II). Fuente única en
# ``printflow.stock.remedy``.
RESERVATION_NATURE_SELECTION = [
    ('physical', 'Falta física'),
    ('contention', 'Contención (lo tienen otros)'),
    ('anomaly', 'Anomalía (reserva colgada)'),
    ('ok', 'Sin traba de stock'),
]

_EPS = 1e-6

# Dispatcher público del popover de la línea de tiempo: traduce la CLAVE de la
# acción (única que conoce el widget) al método ``_pf_*`` interno del modelo.
# Odoo 17 rechaza invocar métodos privados por RPC (``call_button``), así que el
# popover llama a ``action_run_pf_node`` con la clave y el servidor resuelve el
# método aquí. La lista BLANCA evita que el cliente elija qué método ejecutar.
_PF_NODE_METHODS = {
    'buy_product': '_pf_open_buy_product',
    'buy_components': '_pf_open_buy_components',
    'view_purchase': '_pf_open_purchase_orders',
    'open_receipt': '_pf_open_receipts',
    'open_own_receipt': '_pf_open_own_receipt',
    'quants': '_pf_open_quants',
    'adjust': '_pf_open_quants_adjust',
    'fix_reservation': '_pf_run_fix_over_reservation',
    'blocking': '_pf_open_blocking_reservations',
    'fabricate': '_pf_open_create_production',
    'open_mo': '_pf_open_mo',
    'line_delivery': '_pf_open_line_delivery',
}


class PrintflowOrderDiagnosticFailure(models.TransientModel):
    """Una fila por nodo roto, con su plan de resolución navegable."""

    _name = 'printflow.order.diagnostic.failure'
    _description = 'Falla por nodo del diagnóstico de pedido (PrintFlow)'
    # El orden lo fija el RANK de la cadena (lo rellena el wizard al crear las
    # fallas de la línea): raíz primero, luego sus consecuencias e independientes.
    _order = 'line_id, pf_chain_rank, id'

    line_id = fields.Many2one(
        'printflow.order.diagnostic.wizard.line',
        string='Línea', required=True, ondelete='cascade',
    )
    # Origen de la falla (related, NO almacenados): permiten mostrar en la tabla
    # del nodo a qué producto/componente pertenece cada error del subárbol.
    origin_product_id = fields.Many2one(
        'product.product',
        related='line_id.product_id',
        string='Producto/componente',
        readonly=True,
    )
    origin_kind = fields.Selection(
        related='line_id.line_kind',
        string='Tipo',
        readonly=True,
    )
    node = fields.Selection(NODE_SELECTION, string='Nodo')
    severity = fields.Selection(SEVERITY_SELECTION, string='Severidad')
    summary = fields.Char(string='Detalle')

    # ── Cadena de fallas por niveles (FEATURE A) ────────────────────────
    # Rol del nodo frente a la raíz del subárbol (la calcula el motor, no aquí).
    pf_chain_role = fields.Selection(
        PF_CHAIN_ROLE_SELECTION, string='Rol', compute='_compute_pf_chain')
    pf_chain_parent_node = fields.Selection(
        NODE_SELECTION, string='Nodo padre', compute='_compute_pf_chain')
    pf_chain_depth = fields.Integer(
        string='Profundidad', compute='_compute_pf_chain')
    pf_chain_indent = fields.Char(
        string='Sangría', compute='_compute_pf_chain',
        help='Espacios de sangría según la profundidad en la cadena.')
    pf_chain_label = fields.Char(
        string='Nodo', compute='_compute_pf_chain',
        help='Etiqueta con la cadena: "↳ Inventario (consecuencia de Compras)".')
    pf_chain_note = fields.Char(
        string='Cadena', compute='_compute_pf_chain',
        help='Nota que explica de qué nodo depende esta consecuencia.')
    pf_chain_is_consequence = fields.Boolean(
        string='Es consecuencia', compute='_compute_pf_chain',
        help='Bandera SOLO de vista: oculta los botones de solución en las '
             'consecuencias (la raíz es la única dueña de la solución).')
    # Rank PLANO: lo escribe el wizard al crear las fallas de la línea; es el
    # único campo de la cadena que usa la BD para ORDENAR (los demás son compute).
    pf_chain_rank = fields.Integer(string='Orden de cadena', default=0)

    # ── Fallas acumuladas / backlog (FEATURE B) ─────────────────────────
    pf_is_backlog = fields.Boolean(
        string='Falla acumulada', compute='_compute_pf_backlog')
    pf_backlog_reasons = fields.Char(
        string='Motivos', compute='_compute_pf_backlog')
    pf_backlog_available = fields.Boolean(
        string='Gestionar en Salud de inventario', compute='_compute_pf_backlog',
        help='True solo en la RAÍZ de la cadena cuando la falla es acumulada.')

    # ── Causa (valor que fija el snapshot) y plan (calculado) ───────────
    pf_cause = fields.Selection(PF_CAUSE_SELECTION, string='Causa')
    pf_plan_summary = fields.Char(
        string='Resumen del plan', compute='_compute_pf_resolution',
    )
    pf_plan_steps = fields.Text(
        string='Pasos', compute='_compute_pf_resolution',
    )

    # ── Tres acciones del contrato extendido ────────────────────────────
    pf_problem_label = fields.Char(compute='_compute_pf_resolution')
    pf_problem_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_problem_target = fields.Char(compute='_compute_pf_resolution')
    pf_problem_available = fields.Boolean(compute='_compute_pf_resolution')
    pf_solution_label = fields.Char(compute='_compute_pf_resolution')
    pf_solution_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_solution_target = fields.Char(compute='_compute_pf_resolution')
    pf_solution_available = fields.Boolean(compute='_compute_pf_resolution')
    pf_collect_label = fields.Char(compute='_compute_pf_resolution')
    pf_collect_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_collect_target = fields.Char(compute='_compute_pf_resolution')
    pf_collect_available = fields.Boolean(compute='_compute_pf_resolution')

    # ── Naturaleza de la traba y REMEDIO recomendado (calculados) ───────
    # El remedio es la recomendación estructural del clasificador. Se muestra
    # como botón propio ("Recomendación") SIN alterar el plan de tres acciones
    # histórico (que conserva su contrato). Permite el doble botón cuando hay
    # descuadre de reserva Y falta física a la vez (decisión 12).
    pf_reservation_nature = fields.Selection(
        RESERVATION_NATURE_SELECTION, compute='_compute_pf_resolution')
    pf_remedy_key = fields.Char(compute='_compute_pf_resolution')
    pf_remedy_label = fields.Char(compute='_compute_pf_resolution')
    pf_remedy_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_remedy_target = fields.Char(compute='_compute_pf_resolution')
    pf_remedy_available = fields.Boolean(compute='_compute_pf_resolution')
    pf_second_remedy_label = fields.Char(compute='_compute_pf_resolution')
    pf_second_remedy_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_second_remedy_target = fields.Char(compute='_compute_pf_resolution')
    pf_second_remedy_available = fields.Boolean(compute='_compute_pf_resolution')

    @api.depends('line_id', 'line_id.failure_ids', 'node')
    def _compute_pf_chain(self):
        """Materializa la CADENA DE FALLAS de la línea (raíz -> consecuencias).

        No reimplementa la precedencia: toma ``line.root_cause_node`` ya resuelto
        y delega la clasificación en ``_pf_chain_steps`` del motor. La única
        fuente de verdad de la cadena es el motor.
        """
        engine = self.env['printflow.order.health.engine']
        for failure in self:
            line = failure.line_id
            broken = line.failure_ids.mapped('node') if line else []
            root_node = line.root_cause_node if line else False
            steps = engine._pf_chain_steps(
                broken, root_node, order=PF_DIAG_CHAIN_ORDER)
            step = steps.get(failure.node) or {
                'role': 'independent', 'parent': False, 'depth': 0, 'rank': 0,
            }
            failure.pf_chain_role = step['role']
            failure.pf_chain_parent_node = step['parent'] or False
            failure.pf_chain_depth = step['depth']
            failure.pf_chain_indent = '\u00a0' * (4 * (step['depth'] or 0))
            failure.pf_chain_is_consequence = step['role'] == 'consequence'
            node_label = PF_CHAIN_LABELS.get(failure.node, failure.node or '')
            parent_label = PF_CHAIN_LABELS.get(step['parent'], '')
            if step['role'] == 'consequence' and step['parent']:
                failure.pf_chain_label = _(
                    '↳ %(node)s (consecuencia de %(parent)s)') % {
                    'node': node_label, 'parent': parent_label}
                failure.pf_chain_note = _('Depende de %s') % parent_label
            else:
                failure.pf_chain_label = node_label
                failure.pf_chain_note = ''

    @api.depends('line_id', 'node', 'pf_cause', 'pf_chain_role')
    def _compute_pf_backlog(self):
        """Marca la falla como ACUMULADA (backlog) y sus motivos.

        Es puro: reúne los números (libre agregado, quant negativo, virtual) y el
        conteo de entregas pendientes del pedido, y delega la decisión en
        ``_pf_is_backlog`` del motor. El botón de ruteo a Salud de inventario solo
        se expone en la RAÍZ de la cadena (anti-redundancia).
        """
        engine = self.env['printflow.order.health.engine']
        Remedy = self.env['printflow.stock.remedy']
        enabled = engine._pf_backlog_enabled()
        threshold = engine._pf_backlog_threshold()
        state_cache = {}
        for failure in self:
            line = failure.line_id
            product = line.product_id if line else False
            if not enabled or not product:
                failure.pf_is_backlog = False
                failure.pf_backlog_reasons = ''
                failure.pf_backlog_available = False
                continue
            state = state_cache.get(product.id)
            if state is None:
                state = Remedy._pf_product_reservation_state(product)
                state_cache[product.id] = state
            is_backlog, reasons = engine._pf_is_backlog(
                free_global=state.get('free_global'),
                has_negative_quant=state.get('has_negative_quant'),
                pending_blocking_count=(line.pending_delivery_order_count or 0),
                virtual_available=product.virtual_available,
                threshold=threshold,
            )
            failure.pf_is_backlog = is_backlog
            failure.pf_backlog_reasons = ' · '.join(reasons)
            failure.pf_backlog_available = bool(
                is_backlog and failure.pf_chain_role == 'root')

    @api.depends('pf_cause', 'line_id')
    def _compute_pf_resolution(self):
        """Materializa el plan del playbook y el REMEDIO recomendado.

        El plan de tres acciones (problema/solución/recopilar) se conserva. El
        remedio es una clasificación ADICIONAL del servicio
        ``printflow.stock.remedy`` (falta física / contención / anomalía) que se
        expone como botón propio y permite el doble botón (decisión 12).
        """
        Playbook = self.env['printflow.resolution.playbook']
        empty_actions = {
            key: Playbook._pf_action('', 'none', '')
            for key in ('problem', 'solution', 'collect')
        }
        for failure in self:
            ctx = failure._pf_playbook_ctx()
            plan = (
                Playbook._pf_get_plan(failure.pf_cause, ctx=ctx)
                if failure.pf_cause else {
                    'summary': '', 'steps': [], 'actions': empty_actions,
                }
            )
            actions = plan['actions']
            problem, solution, collect = (
                actions['problem'], actions['solution'], actions['collect'])
            # La Bandeja de Resolución (``collect_tray``) vive en el ESCÁNER de
            # producto, no en este diagnóstico de pedido: aquí no hay a dónde
            # llevar ese "recopilar". Se desactiva SOLO la disponibilidad; el
            # resto del plan conserva el texto del playbook (fuente única).
            if collect['target'] == 'collect_tray':
                collect = dict(collect, available=False)
            # "Libre agotada": el recopilar correcto NO son pedidos de venta
            # sino los ALBARANES DE ENTREGA que apartan la mercancía (incluye
            # POS, cuyo ``sale_id`` es False). Se sustituye localmente, sin
            # tocar el playbook compartido con el escáner.
            if failure.pf_cause == 'free_exhausted':
                collect = {
                    'label': _('Recopilar albaranes de entrega'),
                    'kind': 'navigate',
                    'target': 'delivery_orders',
                    'available': True,
                }
            failure.pf_plan_summary = plan['summary']
            failure.pf_plan_steps = '\n'.join(
                '%d. %s' % (index, step)
                for index, step in enumerate(plan['steps'], start=1)
            )
            failure.pf_problem_label = problem['label']
            failure.pf_problem_kind = problem['kind']
            failure.pf_problem_target = problem['target']
            failure.pf_problem_available = problem['available']
            failure.pf_solution_label = solution['label']
            failure.pf_solution_kind = solution['kind']
            failure.pf_solution_target = solution['target']
            failure.pf_solution_available = solution['available']
            failure.pf_collect_label = collect['label']
            failure.pf_collect_kind = collect['kind']
            failure.pf_collect_target = collect['target']
            failure.pf_collect_available = collect['available']
            # ── Remedio estructural (recomendación) ─────────────────────
            failure.pf_reservation_nature = ctx.get('reservation_nature') or False
            failure._pf_assign_remedy(ctx, problem, solution)

    def _pf_playbook_ctx(self):
        """Contexto para el playbook y el clasificador (solo causas de stock).

        Para las causas que NO son de stock/ruta devuelve un contexto ligero
        (sin consultas) para no provocar N+1.
        """
        self.ensure_one()
        line = self.line_id
        product = line.product_id if line else False
        ctx = {
            'product': product,
            'has_bom': False,
            'is_manufacturable': False,
            'is_purchasable': False,
            'deficit_qty': (line.deficit_qty if line else 0.0) or 0.0,
            'contention_qty': (line.contention_qty if line else 0.0) or 0.0,
            # Atribución por PORCIÓN (OC agrupada) para el caso e/f.
            'incoming_own': (line.incoming_own if line else 0.0) or 0.0,
            'own_received_qty': (line.own_received_qty if line else 0.0) or 0.0,
            'own_reserved_qty': (line.own_reserved_qty if line else 0.0) or 0.0,
            'required_qty': (line.required_qty if line else 0.0) or 0.0,
            'free_for_order': (line.warehouse_free_qty if line else 0.0) or 0.0,
            'virtual_available': 0.0,
            'pf_purchase_on_order': False,
            'missing_components': [],
            'reservation_nature': '',
        }
        stock_causes = {
            'free_exhausted', 'data_anomaly', 'adjust_inventory',
            'order_shortfall', 'order_supply_missing', 'no_route',
            'manufacture', 'manufacture_components', 'buy_product', 'no_bom',
            'contention_needs_supply', 'personalized_supply_stolen',
        }
        if not product or self.pf_cause not in stock_causes:
            return ctx
        Remedy = self.env['printflow.stock.remedy']
        ctx['has_bom'] = Remedy._pf_has_bom(product)
        ctx['is_manufacturable'] = Remedy._pf_is_manufacturable(product)
        ctx['is_purchasable'] = Remedy._pf_is_purchasable(product)
        ctx['virtual_available'] = product.virtual_available
        ctx['pf_purchase_on_order'] = bool(
            product.product_tmpl_id.pf_purchase_on_order)
        state = Remedy._pf_product_reservation_state(product)
        ctx['has_negative_quant'] = state['has_negative_quant']
        ctx['free_global'] = state['free_global']
        nature = Remedy._pf_classify_reservation(
            product, ctx['deficit_qty'], ctx['contention_qty'])
        ctx['reservation_nature'] = nature
        if nature == 'physical':
            key = Remedy._pf_physical_remedy_key(product, ctx['deficit_qty'])
            if key == 'buy_components':
                missing = Remedy._pf_missing_components(
                    product, ctx['deficit_qty'])
                ctx['missing_components'] = [
                    (m['product'].id, m['need'], m['free']) for m in missing
                ]
        return ctx

    def _pf_assign_remedy(self, ctx, problem=None, solution=None):
        """Asigna las etiquetas/acciones del remedio (con doble botón).

        Regla anti-duplicación: ``pf_remedy_available`` es el GATE del botón
        unificado "Solucionar" (si es True manda el remedio; si no, la solución
        del plan). Por eso el remedio primario se OCULTA (``available=False``)
        cuando ofrece exactamente lo mismo que el plan del playbook —"Solucionar"
        ya lo haría por la vía de la solución—, y la "Alternativa" se oculta
        cuando repite cualquiera de esos destinos o al propio primario. Los
        campos ``pf_remedy_*`` / ``pf_second_remedy_*`` se siguen calculando;
        solo cambia la BANDERA de disponibilidad.
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        nature = ctx.get('reservation_nature') or ''
        first_key = second_key = False
        if self.pf_cause == 'personalized_supply_stolen':
            # Caso f: la porción propia recibida está retenida por otro pedido
            # del grupo. Se RECLAMA solo esa porción (nunca la OC completa).
            first_key = 'claim_own_purchase'
        elif self.pf_cause == 'mo_without_materials':
            # La OF no tiene insumos: se abre para cargarlos (guía, no ejecuta).
            first_key = 'load_mo_materials'
        elif nature == 'anomaly':
            # El descuadre manda como primer paso. Si ADEMÁS falta física, se
            # ofrece el segundo botón para comprar/fabricar (decisión 12).
            first_key = 'fix_over_reservation'
            if (ctx.get('deficit_qty') or 0.0) > _EPS:
                second_key = Remedy._pf_physical_remedy_key(
                    ctx.get('product'), ctx['deficit_qty'])
        elif nature == 'contention':
            # 1º NUNCA toca la reserva ajena: ver quién bloquea.
            first_key = 'blocking'
            # Caso e: contención SIN entrada propia ni libre -> 2º abastecer
            # (comprar o fabricar según ruta) por la porción no cubierta.
            no_own_incoming = (ctx.get('incoming_own') or 0.0) <= _EPS
            no_slack = (
                (ctx.get('free_global') or 0.0) < -_EPS
                or (ctx.get('virtual_available') or 0.0) < -_EPS
            )
            if no_own_incoming and no_slack:
                qty = (ctx.get('deficit_qty') or 0.0) or (ctx.get('required_qty') or 0.0)
                second_key = Remedy._pf_physical_remedy_key(
                    ctx.get('product'), qty)
        elif nature == 'physical':
            first_key = Remedy._pf_physical_remedy_key(
                ctx.get('product'), ctx.get('deficit_qty'))
            # Decisión 12: si ADEMÁS hay un quant con libre negativo (descuadre
            # de reserva), se ofrece el saneamiento como segundo botón.
            if (ctx.get('has_negative_quant')
                    and (ctx.get('free_global') or 0.0) >= -_EPS):
                second_key = 'fix_over_reservation'
        # Bloque V: si no hay problema de CANTIDAD, manda el estado de LOTE.
        if not first_key and ctx.get('product'):
            lot_state = self.env['printflow.stock.health']._pf_lot_state(
                ctx.get('product'))
            # F3: resta de hallazgos AUTORIZADOS (adaptador de GI; motor intacto).
            lot_state = self.env[
                'printflow.finding.exception.filter']._pf_apply_to_lot_info(
                    ctx.get('product'), lot_state)
            if lot_state['state'] != 'lot_ok':
                first_key = lot_state['remedy_key']
        first = self._pf_remedy_fields(first_key, Remedy)
        second = self._pf_remedy_fields(second_key, Remedy)
        # Anti-duplicación (apaga el remedio primario cuando el plan ya ofrece
        # lo mismo). El conjunto expuesto del primario son las acciones
        # problem/solution del playbook; el del secundario, esas MÁS el primario.
        # El primario apagado NO se pierde: lo ejecuta el botón unificado
        # "Solucionar" a través de la solución.
        plan_targets = {
            (action.get('kind'), action.get('target'))
            for action in (solution, problem) if action
        }
        first_target = (first['kind'], first['target'])
        if first_target in plan_targets:
            first['available'] = False
        plan_targets.add(first_target)
        if (second['kind'], second['target']) in plan_targets:
            second['available'] = False
        self.pf_remedy_key = first_key or False
        self.pf_remedy_label = first['label']
        self.pf_remedy_kind = first['kind']
        self.pf_remedy_target = first['target']
        self.pf_remedy_available = first['available']
        self.pf_second_remedy_label = second['label']
        self.pf_second_remedy_kind = second['kind']
        self.pf_second_remedy_target = second['target']
        self.pf_second_remedy_available = second['available']

    @api.model
    def _pf_remedy_fields(self, key, Remedy):
        """Traduce una clave de remedio a los campos de pantalla."""
        if not key:
            return {'label': '', 'kind': 'none', 'target': '', 'available': False}
        label, kind, target = Remedy._pf_remedy_meta(key)
        return {
            'label': label, 'kind': kind, 'target': target,
            'available': kind != 'none',
        }

    # ------------------------------------------------------------------
    # NAVEGACIÓN BAJO DEMANDA (solo lectura)
    # ------------------------------------------------------------------
    def action_run_pf_node(self, node_action):
        """Dispatcher PÚBLICO de las acciones del popover de la línea de tiempo.

        Odoo 17 prohíbe invocar métodos privados (nombre con ``_``) vía
        ``/web/dataset/call_button``. El widget conoce solo la CLAVE de la
        acción (``node_action``); este método la traduce, con una lista blanca,
        al ``_pf_*`` interno correspondiente, que conserva intacto su contrato,
        permisos y efectos. Así el frontend no necesita saber nada del backend
        y ningún método privado viaja por RPC.
        """
        self.ensure_one()
        method_name = _PF_NODE_METHODS.get(node_action)
        if not method_name:
            return {'type': 'ir.actions.act_window_close'}
        return getattr(self, method_name)()

    def _pf_run_action(self, kind, target):
        """Traduce un paso del plan a una acción Odoo.

        ``navigate`` solo abre pantallas; ``open_wizard`` abre un asistente
        prellenado (no crea OF/OC hasta que el operador confirma); y
        ``run_action`` ejecuta el único remedio con efecto: la re-reserva.
        """
        self.ensure_one()
        kind = kind or 'none'
        if kind == 'navigate':
            return self._pf_nav_action(target)
        if kind == 'open_wizard':
            return self._pf_open_wizard(target)
        if kind == 'run_action':
            return self._pf_run_action_target(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_open_wizard(self, target):
        """Destinos de creación prellenada (OF/OC). No crean nada por sí solos."""
        self.ensure_one()
        target = target or 'none'
        if target == 'create_production':
            return self._pf_open_create_production()
        if target == 'buy_components':
            return self._pf_open_buy_components()
        if target == 'buy_product':
            return self._pf_open_buy_product()
        return {'type': 'ir.actions.act_window_close'}

    def _pf_run_action_target(self, target):
        """Remedios con efecto (re-reserva y lotes). Restringido por permiso."""
        self.ensure_one()
        target = target or ''
        if target == 'fix_over_reservation':
            return self._pf_run_fix_over_reservation()
        # Caso f: reclama SOLO la porción propia de la OC compartida.
        if target == 'claim_own_purchase':
            return self._pf_run_claim_own_purchase()
        # Bloque V: remedios de LOTE sobre el producto de la línea.
        if target in ('assign_lot', 'reconcile_lot_reservation',
                      'replace_generic_lot', 'separate_lots',
                      'repair_finished_lot'):
            return self._pf_run_lot_remedy(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_run_lot_remedy(self, target):
        """Ejecuta un remedio de lote sobre el producto de la falla.

        Reutiliza ``printflow.stock.health``. Nunca asigna a un pedido el lote
        de otro cliente (regla de trazabilidad).
        """
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        Health = self.env['printflow.stock.health']
        if target == 'reconcile_lot_reservation':
            Health._pf_reassign_by_lot(product)
            message = _('Reserva de lote reconciliada con los movimientos.')
        elif target == 'replace_generic_lot':
            replaced = Health._pf_replace_generic_lot(product)
            message = _('Lotes genéricos sustituidos: %s.') % replaced
        elif target == 'separate_lots':
            Health._pf_replace_generic_lot(product)
            Health._pf_reassign_by_lot(product)
            message = _('Movimientos separados por lote.')
        elif target == 'repair_finished_lot':
            repaired = Health._pf_repair_finished_lot(product)
            message = _('Órdenes de fabricación reparadas: %s.') % repaired
        else:  # assign_lot
            moves = self.env['stock.move'].sudo().search([
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
                ('location_id.usage', '=', 'internal'),
                ('picking_type_id.code', '=', 'outgoing'),
            ])
            for move in moves:
                if not move._pf_has_lot_assigned():
                    move._pf_auto_assign_lot()
            message = _('Se asignó lote a los movimientos que no lo tenían.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success', 'title': _('PrintFlow'),
                'message': message, 'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_apply_remedy(self):
        """Botón "Recomendación": ejecuta el remedio principal."""
        self.ensure_one()
        return self._pf_run_action(
            self.pf_remedy_kind, self.pf_remedy_target)

    def action_apply_second_remedy(self):
        """Botón secundario (doble botón: descuadre + falta física)."""
        self.ensure_one()
        return self._pf_run_action(
            self.pf_second_remedy_kind, self.pf_second_remedy_target)

    def action_open_problem(self):
        """Botón "problema": navega al síntoma del nodo roto."""
        self.ensure_one()
        return self._pf_run_action(self.pf_problem_kind, self.pf_problem_target)

    def _pf_effective_solution(self):
        """Acción resolutiva EFECTIVA del botón unificado "Solucionar".

        Precedencia (diseño aprobado de la unificación):

        * Si ``pf_remedy_available`` es True y el remedio tiene un ``kind``
          real, manda el REMEDIO estructural: ``(pf_remedy_kind,
          pf_remedy_target)``.
        * En cualquier otro caso, manda la SOLUCIÓN del playbook:
          ``(pf_solution_kind, pf_solution_target)``.

        ``pf_remedy_available`` ya significa "el remedio apunta a un destino
        distinto al del plan" (``_pf_assign_remedy`` lo apaga por
        anti-duplicación), de modo que nunca se ejecuta dos veces lo mismo.

        :return: tupla ``(kind, target)`` lista para ``_pf_run_action``.
        """
        self.ensure_one()
        if (self.pf_remedy_available
                and self.pf_remedy_kind not in (False, 'none')):
            return self.pf_remedy_kind, self.pf_remedy_target
        return self.pf_solution_kind, self.pf_solution_target

    def action_open_solution(self):
        """Botón "Solucionar" (unificado): ejecuta la acción resolutiva.

        La decisión remedio-vs-solución vive en ``_pf_effective_solution``;
        aquí solo se traduce el paso elegido a una acción de Odoo. Si la causa
        tiene una FALLA GUIADA registrada (p. ej. ``data_anomaly`` = reserva
        colgada), el botón ABRE la bandeja de decisión en vez del one-click.
        """
        self.ensure_one()
        guided = self._pf_open_registered_failure_tray(self.pf_cause)
        if guided:
            return guided
        kind, target = self._pf_effective_solution()
        return self._pf_run_action(kind, target)

    def _pf_open_registered_failure_tray(self, code):
        """Abre la bandeja guiada de ``code`` si es una falla registrada.

        Devuelve ``False`` cuando la causa NO tiene falla guiada, cuando no hay
        producto o cuando la falla no está presente (sin evidencias): el llamador
        conserva entonces su comportamiento de one-click. La bandeja la pinta el
        modelo que declara la propia falla (``_pf_fault_tray_model``) y se puebla
        con una fila por evidencia.
        """
        self.ensure_one()
        product = self.line_id.product_id if self.line_id else False
        Registry = self.env['printflow.flow.failure.registry']
        # Solo causas NO de lote: el lote conserva su flujo (bandeja de lote y
        # remedios del motor), que ya funciona y no se toca.
        if (not product or code not in Registry._pf_supported()
                or self.env['printflow.flow.lots']._pf_is_lot_cause(code)):
            return False
        failure = Registry._pf_failure_for(code)
        tray_model = failure._pf_fault_tray_model()
        tray = self.env[tray_model]._pf_populate(self, code, product)
        if not tray or not tray.line_ids:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Falla: %s') % (tray.summary or product.display_name),
            'res_model': tray_model,
            'res_id': tray.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_collect(self):
        """Botón "recopilar": abre la lista agregada de causantes-raíz."""
        self.ensure_one()
        return self._pf_run_action(
            self.pf_collect_kind, self.pf_collect_target)

    def action_open_inventory_health(self):
        """Botón "Salud de inventario": abre la bandeja filtrada a este producto.

        Reutiliza el punto de entrada ``_pf_open_health`` de la bandeja (poblado
        bajo demanda). Solo navega; no modifica inventario.
        """
        self.ensure_one()
        product = self.line_id.product_id
        return self.env['printflow.inventory.health']._pf_open_health(
            products=product,
            title=_('Salud de inventario: %s') % (
                product.display_name if product else ''))

    def _pf_nav_action(self, target):
        """Vocabulario de navegación propio del diagnóstico de pedido."""
        self.ensure_one()
        target = target or 'none'
        if target == 'product':
            return self._pf_open_product()
        if target == 'purchase_order':
            return self._pf_open_purchase_orders()
        if target == 'receipt':
            return self._pf_open_receipts()
        if target == 'mo':
            return self._pf_open_mo()
        if target == 'mo_list':
            return self._pf_open_mo(filter_by_product=False)
        if target == 'reserving_sale_orders':
            return self._pf_open_reserving_sale_orders()
        # MEJORA B: destinos nuevos del contrato del playbook.
        if target == 'quants':
            return self._pf_open_quants()
        if target == 'sale_lines':
            return self._pf_open_sale_lines()
        if target == 'sale_orders':
            return self._pf_open_sale_orders()
        # MEJORA C: bandeja de albaranes de entrega que reservan el producto.
        if target == 'delivery_orders':
            return self._pf_open_delivery_orders()
        # Bloque II: lista "quién me bloquea" (por entrega/albarán, ordenada).
        if target == 'blocking_reservations':
            return self._pf_open_blocking_reservations()
        # Nodos nuevos del contrato de remedios.
        if target == 'quants_adjust':
            return self._pf_open_quants_adjust()
        if target == 'bom_list':
            return self._pf_open_bom_list()
        # Nodo Entrega: albarán de entrega del PROPIO producto en el pedido.
        if target == 'line_delivery':
            return self._pf_open_line_delivery()
        # Caso f: compra/recepción PROPIAS del pedido (porción de la OC).
        if target == 'own_purchase':
            return self._pf_open_own_purchase()
        if target == 'own_receipt':
            return self._pf_open_own_receipt()
        # FASE 5: bandeja de causantes del PEDIDO (porción por pedido).
        if target == 'order_collect_tray':
            return self.action_open_collect_tray()
        return {'type': 'ir.actions.act_window_close'}

    def _pf_board(self):
        """Tablero del diagnóstico al que pertenece esta falla."""
        self.ensure_one()
        return self.line_id.wizard_id.board_id

    def _pf_open_product(self):
        """Abre la ficha del producto de la línea."""
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': product.display_name,
            'res_model': 'product.product',
            'res_id': product.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _pf_open_purchase_orders(self):
        """Abre las Órdenes de Compra vinculadas al pedido."""
        self.ensure_one()
        board = self._pf_board()
        so = board.sale_order_id
        pos = (
            board._find_purchase_orders_by_sale_names([so.name])
            if so else self.env['purchase.order']
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s compra(s) del pedido') % len(pos),
            'res_model': 'purchase.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pos.ids)],
            'target': 'current',
        }

    def _pf_open_receipts(self):
        """Abre los albaranes de entrada de las compras del pedido."""
        self.ensure_one()
        board = self._pf_board()
        so = board.sale_order_id
        pos = (
            board._find_purchase_orders_by_sale_names([so.name])
            if so else self.env['purchase.order']
        )
        pickings = self.env['stock.picking'].search([
            ('purchase_id', 'in', pos.ids),
            ('picking_type_id.code', '=', 'incoming'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s albarán(es) de entrada') % len(pickings),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def _pf_open_mo(self, filter_by_product=True):
        """Abre las Órdenes de Fabricación activas del pedido."""
        self.ensure_one()
        board = self._pf_board()
        mos = board.mrp_production_ids.filtered(
            lambda m: m.state not in ('done', 'cancel'))
        if filter_by_product and self.line_id.product_id:
            mos = mos.filtered(
                lambda m: m.product_id == self.line_id.product_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s orden(es) de fabricación') % len(mos),
            'res_model': 'mrp.production',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', mos.ids)],
            'target': 'current',
        }

    def _pf_open_reserving_sale_orders(self):
        """Abre los pedidos que reservan el producto (solo lectura)."""
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        move_lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
        ])
        orders = (
            move_lines.picking_id.sale_id
            | move_lines.move_id.sale_line_id.order_id
        )
        own = self.line_id.wizard_id.board_id.sale_order_id
        if own:
            orders -= own
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s pedido(s) que lo reservan') % len(orders),
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', orders.ids)],
            'target': 'current',
        }

    # ══════════════════════════════════════════════════════════════════════
    # MEJORA B: destinos nuevos del contrato del playbook (solo lectura)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_open_quants(self):
        """Abre las existencias internas del producto de la línea."""
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Existencias de %s') % product.display_name,
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', product.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'target': 'current',
        }

    def _pf_open_sale_lines(self):
        """Abre las líneas de venta del pedido (o del producto, si no hay pedido)."""
        self.ensure_one()
        board = self._pf_board()
        so = board.sale_order_id
        if so:
            domain = [('order_id', '=', so.id)]
            name = _('Líneas del pedido %s') % so.name
        else:
            product = self.line_id.product_id
            if not product:
                return {'type': 'ir.actions.act_window_close'}
            domain = [('product_id', '=', product.id), ('state', '=', 'sale')]
            name = _('Líneas de venta de %s') % product.display_name
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'sale.order.line',
            'view_mode': 'tree,form',
            'domain': domain,
            'target': 'current',
        }

    def _pf_open_sale_orders(self):
        """Abre los pedidos que reservan el producto (reutiliza el helper)."""
        self.ensure_one()
        return self._pf_open_reserving_sale_orders()

    # ══════════════════════════════════════════════════════════════════════
    # MEJORA C: bandeja de albaranes de entrega que reservan el producto
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_collect_picking_limit(self):
        """Límite configurable de la bandeja de "Recopilar" (0 = sin límite)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'x_product_dimensional_pricing.pf_collect_picking_limit', '0')
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    def _pf_delivery_pickings(self):
        """Albaranes de entrega (ajenos al pedido) que RESERVAN el producto.

        El ancla es ``stock.move.line`` (las RESERVAS), NO ``sale.order``: los
        albaranes del POS que apartan el insumo tienen ``sale_id`` False, así que
        un dominio sobre la venta los dejaría fuera (caso real S07301, insumo
        14445). Es de SOLO LECTURA y con ``sudo()``, como el resto de búsquedas
        de reservas de este modelo.
        """
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return self.env['stock.picking']
        own = self._pf_board()._get_delivery_pickings()
        domain = [
            ('state', 'not in', ('done', 'cancel')),
            ('picking_type_id.code', '=', 'outgoing'),
            ('move_line_ids.product_id', '=', product.id),
            ('move_line_ids.state', 'not in', ('done', 'cancel')),
            ('move_line_ids.quantity', '>', 0),
            ('move_line_ids.location_id.usage', '=', 'internal'),
        ]
        if own:
            domain.append(('id', 'not in', own.ids))
        return self.env['stock.picking'].sudo().search(
            domain, order='scheduled_date asc, id asc',
            limit=self._pf_collect_picking_limit())

    def _pf_open_delivery_orders(self):
        """Abre la bandeja CONGELADA de albaranes de entrega que lo reservan."""
        self.ensure_one()
        pickings = self._pf_delivery_pickings()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Albaranes de entrega que lo reservan (%d)') % len(pickings),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def _pf_open_line_delivery(self):
        """Abre la entrega del PROPIO producto de esta línea (nodo Entrega).

        Delegación al tablero: ``action_open_product_delivery`` filtra los
        albaranes del pedido a los que contienen movimientos de ESTE producto.
        El botón de fila del wizard usa la MISMA acción (paridad falla<->botón).
        """
        self.ensure_one()
        board = self._pf_board()
        if not board:
            return {'type': 'ir.actions.act_window_close'}
        return board.action_open_product_delivery(self.line_id.product_id)

    # ══════════════════════════════════════════════════════════════════════
    # REMEDIOS DEL BLOQUE I/II (open_wizard / run_action)
    #
    # "Abrir ≠ ejecutar": los creadores solo devuelven una acción con contexto
    # prellenado. La ÚNICA acción con efecto de datos es la re-reserva, que
    # reutiliza el remedio ya probado del tablero.
    # ══════════════════════════════════════════════════════════════════════
    def _pf_deficit_qty(self):
        """Cantidad a cubrir: el déficit físico, o 1 si no hay cifra."""
        self.ensure_one()
        return (self.line_id.deficit_qty or 0.0) or 1.0

    def _pf_purchase_shortfall_qty(self):
        """Cantidad a comprar: el faltante REAL del pedido, o 1 si no hay cifra.

        Paridad con el diagrama de producto (D6): del déficit de la línea se resta
        la cobertura de OC SIN CONFIRMAR RESTRINGIDA a ESTE pedido (``sale_order``
        del board), para no duplicar entradas al confirmar esas OC. Reutiliza la
        FUENTE ÚNICA del motor de pendientes. La OF y la compra de COMPONENTES
        siguen usando ``_pf_deficit_qty`` (D7). Solo LECTURA.
        """
        self.ensure_one()
        line = self.line_id
        product = line.product_id if line else False
        if not product:
            return 1.0
        deficit = (line.deficit_qty or 0.0)
        board = self._pf_board()
        cover = self.env[
            'printflow.flow.pending']._pf_purchase_unconfirmed_cover(
                [product.id],
                sale_order=board.sale_order_id if board else None
            ).get(product.id, 0.0) or 0.0
        return max(0.0, deficit - cover) or 1.0

    def _pf_open_create_production(self):
        """Abre/crea la Orden de Fabricación del producto (sin confirmarla).

        Decisión 7: si el producto NO tiene lista de materiales se BLOQUEA con
        un mensaje claro (una OF sin BOM sería inútil).
        """
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        if not Remedy._pf_has_bom(product):
            raise UserError(_(
                'El producto "%s" no tiene lista de materiales (BOM): no se '
                'puede crear una Orden de Fabricación real. Crea la BOM o usa '
                'Ajuste de inventario.') % product.display_name)
        board = self._pf_board()
        mos = board.sale_order_id.mrp_production_ids.filtered(
            lambda m: m.product_id == product and m.state not in ('done', 'cancel')
        ) if board else self.env['mrp.production']
        if len(mos) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': mos.name,
                'res_model': 'mrp.production',
                'res_id': mos.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if mos:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Órdenes de Fabricación'),
                'res_model': 'mrp.production',
                'view_mode': 'list,form',
                'domain': [('id', 'in', mos.ids)],
                'target': 'current',
            }
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva Orden de Fabricación'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_product_id': product.id,
                'default_product_qty': self._pf_deficit_qty(),
                'default_bom_id': bom.id if bom else False,
                'default_origin': (board.sale_order_id.name if board else '') or '',
            },
        }

    def _pf_open_buy_components(self):
        """Abre la Compra Rápida con los componentes faltantes de la BOM."""
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        missing = Remedy._pf_missing_components(product, self._pf_deficit_qty())
        if not missing:
            return self._pf_open_buy_product()
        return self._pf_open_quick_purchase([
            (m['product'], m['need']) for m in missing
        ], title=_('Compra Rápida (componentes)'))

    def _pf_open_buy_product(self):
        """Abre la Compra Rápida prellenada con el producto faltante."""
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return self._pf_open_quick_purchase(
            [(product, self._pf_purchase_shortfall_qty())],
            title=_('Compra Rápida (producto)'))

    def _pf_open_quick_purchase(self, product_qty_list, title):
        """Crea el asistente de Compra Rápida con líneas prellenadas.

        Reutiliza ``mrp.quick.purchase.wizard`` sin forzar la recepción: el
        operador confirma. Si el pedido no tiene venta (p. ej. POS), el wizard
        ya admite ``sale_order_id`` vacío (decisión 10).

        La cantidad viene del FALTANTE REAL del pedido, así que se CONGELA
        (``pf_freeze_qty``): al "Traer pedidos" el wizard NO la recalcula con la
        lista de pedidos (D3). ``product_id`` es el producto de REFERENCIA (el que
        se está comprando).
        """
        self.ensure_one()
        board = self._pf_board()
        so = board.sale_order_id if board else self.env['sale.order']
        line_vals = []
        for product, qty in product_qty_list:
            vals = {
                'product_id': product.id,
                'product_qty': qty or 1.0,
                'product_uom_id': product.uom_id.id,
                # No forzamos recepción: solo se genera la OC.
                'material_received': False,
            }
            if product.seller_ids:
                vals['partner_id'] = product.seller_ids[0].partner_id.id
            if so and so.currency_id:
                vals['currency_id'] = so.currency_id.id
            line_vals.append((0, 0, vals))
        reference = (
            product_qty_list[0][0] if product_qty_list else False)
        wizard = self.env['mrp.quick.purchase.wizard'].create({
            'sale_order_id': so.id if so else False,
            'product_id': reference.id if reference else False,
            'pf_freeze_qty': True,
            'purchase_line_ids': line_vals,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'mrp.quick.purchase.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _pf_run_fix_over_reservation(self):
        """Ejecuta la re-reserva (saneamiento) del pedido en foco.

        Restringido a jefe de taller/administrador (decisión 13). NO toca la
        reserva de otros pedidos: solo suelta y re-reserva los albaranes de
        ESTE pedido.
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        board = self._pf_board()
        if not board:
            return {'type': 'ir.actions.act_window_close'}
        still_missing = board._fix_over_reservation_and_refresh()
        if still_missing is None:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('PrintFlow'),
                    'message': _(
                        'Este pedido no tiene albaranes de entrega pendientes '
                        'de reserva.'),
                    'sticky': False,
                },
            }
        board.message_post(
            body=_(
                'Se liberó y re-reservó el inventario desde el diagnóstico de '
                'pedido (remedio estructural).'),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
        if still_missing:
            message = _(
                'Se liberó la reserva colgada, pero aún falta stock físico: '
                'ahora sí toca comprar o fabricar.')
            ntype = 'warning'
        else:
            message = _('Reservas reajustadas al stock real del almacén.')
            ntype = 'success'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': ntype,
                'title': _('PrintFlow'),
                'message': message,
                'sticky': ntype == 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ══════════════════════════════════════════════════════════════════════
    # CASO f — COMPRA PROPIA RETENIDA: reparto de la PORCIÓN propia
    #
    # Reparación NO automática y NO destructiva: exige permiso (reutiliza
    # ``_pf_assert_can_clean``) y SOLO mueve la porción que le corresponde a
    # este pedido. Nunca la OC completa ni la porción de otro pedido del grupo.
    # ══════════════════════════════════════════════════════════════════════
    def _pf_own_purchase_orders(self):
        """PO propias del pedido: la vinculada (``pf_linked_po_id``) o las del
        ``origin`` (para el reparto agrupado)."""
        self.ensure_one()
        board = self._pf_board()
        so = board.sale_order_id if board else self.env['sale.order']
        if not so:
            return self.env['purchase.order']
        if so.pf_linked_po_id:
            return so.pf_linked_po_id
        return self.env['printflow.stock.remedy']._pf_purchase_orders_for_sale(so)

    def _pf_open_own_purchase(self):
        """Abre la OC propia (porción) del pedido."""
        self.ensure_one()
        pos = self._pf_own_purchase_orders()
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s compra(s) propia(s)') % len(pos),
            'res_model': 'purchase.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pos.ids)],
            'target': 'current',
        }

    def _pf_open_own_receipt(self):
        """Abre los albaranes de entrada de la compra propia del pedido."""
        self.ensure_one()
        pos = self._pf_own_purchase_orders()
        pickings = self.env['stock.picking'].search([
            ('purchase_id', 'in', pos.ids),
            ('picking_type_id.code', '=', 'incoming'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s recepción(es) propia(s)') % len(pickings),
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', pickings.ids)],
            'target': 'current',
        }

    def _pf_release_group_excess(self, product, own_so, Remedy):
        """Libera SOLO el exceso que los pedidos del grupo retienen por encima
        de su propia porción. Nunca baja a un pedido por debajo de su porción."""
        pos = Remedy._pf_purchase_orders_for_sale(own_so)
        names = Remedy._pf_origin_sale_names(pos)
        if not names or not product:
            return 0.0
        others = self.env['sale.order'].search(
            [('name', 'in', list(names)), ('id', '!=', own_so.id)])
        released = 0.0
        MoveLine = self.env['stock.move.line'].sudo()
        for other in others:
            portion = Remedy._pf_own_portion(
                product, other)['own_received_qty']
            move_lines = MoveLine.search([
                ('picking_id', 'in', other.picking_ids.ids),
                ('state', 'not in', ('done', 'cancel')),
                ('product_id', '=', product.id),
                ('location_id.usage', '=', 'internal'),
                ('quantity', '>', 0),
            ])
            if not move_lines:
                continue
            reserved = sum(move_lines.mapped('quantity_product_uom'))
            excess = reserved - portion
            if excess <= _EPS:
                continue
            for move_line in move_lines.sorted(
                    lambda m: m.quantity_product_uom, reverse=True):
                if excess <= _EPS:
                    break
                qty_product = move_line.quantity_product_uom
                if qty_product <= _EPS:
                    continue
                take = min(qty_product, excess)
                new_product = qty_product - take
                if new_product <= _EPS:
                    move_line.unlink()
                else:
                    ratio = (move_line.quantity / qty_product) if qty_product else 1.0
                    move_line.write({'quantity': new_product * ratio})
                excess -= take
                released += take
        return released

    def _pf_run_claim_own_purchase(self):
        """Botón "Reclamar mi parte": reparte SOLO la porción propia.

        Restringido a jefe de taller/administrador. Reutiliza el permiso del
        saneamiento. Nunca toca la porción de otro pedido del grupo.
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        line = self.line_id
        product = line.product_id
        board = self._pf_board()
        so = board.sale_order_id if board else self.env['sale.order']
        if not product or not so:
            return {'type': 'ir.actions.act_window_close'}
        own = Remedy._pf_own_portion(
            product, so, reserved_order=line.order_reserved_qty)
        own_received = own['own_received_qty']
        target_qty = min(line.required_qty or 0.0, own_received) or own_received
        released = self._pf_release_group_excess(product, so, Remedy)
        pickings = board._get_delivery_pickings() if board else self.env['stock.picking']
        if pickings:
            pickings.do_unreserve()
            pickings.action_assign()
        body = _(
            'PrintFlow: reparto de la porción propia de la compra compartida. '
            'Porción del pedido: %(portion).2f; se liberó del grupo el exceso '
            'de %(released).2f. No se tocó la porción de otros pedidos.'
        ) % {'portion': target_qty, 'released': released}
        if pickings:
            pickings.message_post(
                body=body, message_type='notification',
                subtype_xmlid='mail.mt_note')
        for po in self._pf_own_purchase_orders():
            po.message_post(
                body=body, message_type='notification',
                subtype_xmlid='mail.mt_note')
        message = _(
            'Se reclamó la porción propia del pedido (%(portion).2f). '
            'Exceso liberado del grupo: %(released).2f.'
        ) % {'portion': target_qty, 'released': released}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success', 'title': _('PrintFlow'),
                'message': message, 'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _pf_own_receipts(self):
        """Albaranes de entrada de la compra propia del pedido."""
        pos = self._pf_own_purchase_orders()
        if not pos:
            return self.env['stock.picking']
        return self.env['stock.picking'].search([
            ('purchase_id', 'in', pos.ids),
            ('picking_type_id.code', '=', 'incoming'),
        ])

    @api.model
    def _pf_state_label(self, record, field_name='state'):
        field = record._fields.get(field_name)
        selection = getattr(field, 'selection', None)
        if not selection:
            return ''
        return dict(selection).get(record[field_name], '')

    def _pf_collect_causante_vals(self):
        """Causantes recolectables de ESTA falla para la Bandeja del pedido.

        Solo describe registros existentes (producto, OC, albaranes, MO,
        porción por pedido). No modifica datos.
        """
        self.ensure_one()
        line = self.line_id
        product = line.product_id
        board = self._pf_board()
        so = board.sale_order_id if board else self.env['sale.order']
        Remedy = self.env['printflow.stock.remedy']
        vals = []
        counter = {'n': 0}

        def add(**kw):
            counter['n'] += 1
            kw.setdefault('sequence', counter['n'] * 10)
            kw.setdefault('failure_id', self.id)
            vals.append(kw)

        if product:
            add(
                label=_('Producto: %s') % product.display_name,
                causante_type='product', collectible=True,
                ref_name=product.display_name, nav_kind='product',
                product_id=product.id,
                res_model='product.product', res_id=product.id,
            )
        if self.node == 'purchase' or self.pf_cause == 'personalized_supply_stolen':
            for po in self._pf_own_purchase_orders():
                add(
                    label=_('Orden de compra %s') % po.name,
                    causante_type='purchase_order', collectible=True,
                    ref_name=po.name,
                    partner_name=po.partner_id.display_name,
                    state_label=self._pf_state_label(po, 'state'),
                    purchase_order_id=po.id, nav_kind='purchase_order',
                    res_model='purchase.order', res_id=po.id,
                )
        if self.node == 'production' and board:
            for mo in board.mrp_production_ids.filtered(
                    lambda m: m.state not in ('done', 'cancel')):
                if product and mo.product_id != product:
                    continue
                add(
                    label=_('Orden de fabricación %s') % mo.name,
                    causante_type='mo', collectible=True,
                    ref_name=mo.name,
                    product_id=mo.product_id.id,
                    state_label=self._pf_state_label(mo, 'state'),
                    qty=mo.product_qty, date_ref=mo.date_start,
                    mo_id=mo.id, nav_kind='mo',
                    res_model='mrp.production', res_id=mo.id,
                )
        if self.node == 'delivery' and board:
            for picking in board._get_delivery_pickings():
                add(
                    label=_('Entrega %s') % picking.name,
                    causante_type='picking', collectible=True,
                    ref_name=picking.name,
                    partner_name=picking.partner_id.display_name,
                    state_label=self._pf_state_label(picking, 'state'),
                    picking_id=picking.id, nav_kind='picking',
                    res_model='stock.picking', res_id=picking.id,
                )
        if self.node == 'stock':
            # Albaranes que retienen el stock (incluye POS sin pedido).
            for picking in self._pf_delivery_pickings():
                add(
                    label=_('Albarán que lo retiene: %s') % picking.name,
                    causante_type='picking', collectible=True,
                    ref_name=picking.name,
                    partner_name=picking.partner_id.display_name,
                    state_label=self._pf_state_label(picking, 'state'),
                    date_ref=picking.scheduled_date,
                    picking_id=picking.id, nav_kind='picking',
                    res_model='stock.picking', res_id=picking.id,
                )
            # Caso f: porción propia por pedido + recepción y albarán propios.
            if self.pf_cause == 'personalized_supply_stolen' and so and product:
                own = Remedy._pf_own_portion(
                    product, so, reserved_order=line.order_reserved_qty)
                for po in self._pf_own_purchase_orders():
                    add(
                        label=_('Porción de %(so)s en OC %(po)s') % {
                            'so': so.name, 'po': po.name},
                        causante_type='order_portion', collectible=True,
                        ref_name=po.name,
                        partner_name=so.partner_id.display_name,
                        state_label=so.name,
                        qty=own['own_received_qty'],
                        qty_secondary=own['own_reserved_qty'],
                        origin_group=own['origin_group'],
                        product_id=product.id,
                        purchase_order_id=po.id, nav_kind='purchase_order',
                        res_model='purchase.order', res_id=po.id,
                    )
                for picking in self._pf_own_receipts():
                    add(
                        label=_('Recepción propia %s') % picking.name,
                        causante_type='picking', collectible=True,
                        ref_name=picking.name,
                        state_label=self._pf_state_label(picking, 'state'),
                        picking_id=picking.id, nav_kind='picking',
                        res_model='stock.picking', res_id=picking.id,
                    )
                if board:
                    for picking in board._get_delivery_pickings():
                        add(
                            label=_('Albarán propio %s') % picking.name,
                            causante_type='picking', collectible=True,
                            ref_name=picking.name,
                            state_label=self._pf_state_label(picking, 'state'),
                            picking_id=picking.id, nav_kind='picking',
                            res_model='stock.picking', res_id=picking.id,
                        )
        return vals

    def action_open_collect_tray(self):
        """Abre la Bandeja de Resolución del PEDIDO para esta falla."""
        self.ensure_one()
        Evidence = self.env['printflow.order.diagnostic.evidence']
        Evidence._pf_populate_for_failure(self)
        action = Evidence._pf_open_tray_action(self)
        action['context'] = dict(
            action.get('context') or {},
            pf_order_wizard_id=self.line_id.wizard_id.id,
        )
        return action

    def _pf_open_blocking_reservations(self):
        """Abre la lista "quién me bloquea" (por entrega/albarán, ordenada)."""
        self.ensure_one()
        product = self.line_id.product_id
        board = self._pf_board()
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        own = board._get_delivery_pickings().ids if board else []
        records = self.env['printflow.order.blocking.reservation']._pf_populate_for_product(
            product, self.line_id.wizard_id, exclude_picking_ids=own)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s entrega(s) que lo bloquean') % len(records),
            'res_model': 'printflow.order.blocking.reservation',
            'view_mode': 'tree',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }

    def _pf_open_quants_adjust(self):
        """Abre las existencias del producto en modo ajuste.

        Decisión 8: además de abrir la pantalla, PROPONE la cantidad a ajustar
        (déficit físico) por contexto.
        """
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        suggested = self.line_id.deficit_qty or 0.0
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajuste de inventario de %s (sugerido: %.2f)') % (
                product.display_name, suggested),
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', product.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'context': {
                'inventory_mode': True,
                'search_default_product_id': product.id,
                'default_inventory_quantity': suggested,
                'pf_suggested_qty': suggested,
            },
            'target': 'current',
        }

    def _pf_open_bom_list(self):
        """Abre las listas de materiales del producto (para crearla)."""
        self.ensure_one()
        product = self.line_id.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Listas de materiales de %s') % product.display_name,
            'res_model': 'mrp.bom',
            'view_mode': 'list,form',
            'domain': [('product_tmpl_id', '=', product.product_tmpl_id.id)],
            'target': 'current',
        }
