# -*- coding: utf-8 -*-
"""Plan de resolución del hallazgo de producto (PrintFlow).

Extiende ``printflow.product.diagnostic.finding`` con campos CALCULADOS y NO
almacenados que explican CÓMO resolver el hallazgo, más los destinos de
navegación del contrato extendido (problema / solución / recopilar). No toca la
detección ni agrega columnas: cero migración.

Reglas:
  * Los textos, pasos y las TRES acciones salen SIEMPRE del
    ``printflow.resolution.playbook`` (única fuente de verdad); aquí solo se
    normaliza la causa (``pf_cause``) y se materializa el plan en campos de
    pantalla.
  * La navegación "quién lo reserva" se resuelve BAJO DEMANDA (al pulsar el
    botón) y SOLO LEE: nunca se calcula en el compute para no provocar N+1.
  * ``action_open()`` se conserva como ALIAS de ``action_open_problem()``
    (compatibilidad con la Bandeja de Resolución y con los tests v1).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .printflow_resolution_playbook import PF_CAUSE_SELECTION, PLAN_ACTION_SELECTION

# Mapa ``check_code`` -> causa normalizada para los códigos que no dependen de
# la severidad ni de datos del producto. ``stock_negative`` y ``record_state``
# se resuelven aparte por ser ambiguos.
CHECK_CODE_TO_CAUSE = {
    'kit_no_own_stock': 'kit_no_own_stock',
    'bom_duplicated': 'bom_duplicated',
    'bom_archive_blocked': 'bom_archive_blocked',
    'orderpoint_kit': 'orderpoint_kit',
    'uom_mismatch': 'uom_mismatch',
    'no_route': 'no_route',
    'pending_sale_lines': 'pending_sale_lines',
    'active_mo': 'active_mo',
}

# Vista de diálogo del plan (se resuelve por xmlid, nunca por id fijo).
PLAN_DETAIL_VIEW_XMLID = (
    'printflow_gestion_inventario.printflow_product_diagnostic_finding_view_form'
)

# Naturaleza de la traba y umbral de comparación (coherente con el clasificador).
RESERVATION_NATURE_SELECTION = [
    ('physical', _('Falta física')),
    ('contention', _('Contención (lo tienen otros)')),
    ('anomaly', _('Anomalía (reserva colgada)')),
    ('ok', _('Sin traba de stock')),
]
_EPS = 1e-6


def pf_reserving_sale_orders(env, product, exclude_sale_order=None):
    """Pedidos de venta que tienen reserva (asignada) del producto.

    Es SOLO LECTURA y se resuelve BAJO DEMANDA. Recorre ``stock.move.line`` no
    terminados que salen de una ubicación interna y traduce cada albarán o
    movimiento a su pedido de venta. Se usa ``sudo`` porque es una navegación de
    diagnóstico y el operador puede no leer todas las ventas.

    :param env: entorno Odoo.
    :param product: ``product.product`` (o vacío).
    :param exclude_sale_order: pedido a excluir (p. ej. el propio pedido).
    :return: ``sale.order`` que reservan el producto (sin duplicados).
    :rtype: sale.order
    """
    if not product:
        return env['sale.order']
    move_lines = env['stock.move.line'].sudo().search([
        ('product_id', '=', product.id),
        ('state', 'not in', ('done', 'cancel')),
        ('quantity', '>', 0),
        ('location_id.usage', '=', 'internal'),
    ])
    orders = (
        move_lines.picking_id.sale_id
        | move_lines.move_id.sale_line_id.order_id
    )
    if exclude_sale_order:
        orders -= exclude_sale_order
    return orders


def pf_reserving_sale_order_ids(env, product, exclude_sale_order=None):
    """Ids de ``sale.order`` que tienen reserva (asignada) del producto.

    Envoltorio de ``pf_reserving_sale_orders`` que devuelve ids (API v1).

    :return: lista de ids de ``sale.order``.
    :rtype: list[int]
    """
    return pf_reserving_sale_orders(
        env, product, exclude_sale_order=exclude_sale_order).ids


class PrintflowProductDiagnosticFinding(models.TransientModel):
    _inherit = 'printflow.product.diagnostic.finding'

    # ── Nuevo destino de navegación: "quién lo reserva" ─────────────────
    nav_kind = fields.Selection(
        selection_add=[
            ('reserving_sale_orders', _('Pedidos que lo reservan')),
        ],
    )

    # ── Plan de resolución (calculado, NO almacenado) ───────────────────
    pf_cause = fields.Selection(
        PF_CAUSE_SELECTION, string='Causa', compute='_compute_pf_resolution',
    )
    pf_plan_summary = fields.Char(
        string='Resumen del plan', compute='_compute_pf_resolution',
    )
    pf_plan_steps = fields.Text(
        string='Pasos para resolverlo', compute='_compute_pf_resolution',
    )

    # ── Tres acciones del contrato extendido (calculadas, NO almacenadas) ─
    # problem = SÍNTOMA (dónde se observa); solution = RAÍZ (dónde se corrige);
    # collect = RAÍZ EN CONJUNTO (lista agregada de causantes-raíz).
    pf_problem_label = fields.Char(
        string='Ir al problema', compute='_compute_pf_resolution')
    pf_problem_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_problem_target = fields.Char(compute='_compute_pf_resolution')
    pf_problem_available = fields.Boolean(
        string='Problema disponible', compute='_compute_pf_resolution')
    pf_solution_label = fields.Char(
        string='Aplicar solución', compute='_compute_pf_resolution')
    pf_solution_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_solution_target = fields.Char(compute='_compute_pf_resolution')
    pf_solution_available = fields.Boolean(
        string='Solución disponible', compute='_compute_pf_resolution')
    pf_collect_label = fields.Char(
        string='Recopilar', compute='_compute_pf_resolution')
    pf_collect_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_collect_target = fields.Char(compute='_compute_pf_resolution')
    pf_collect_available = fields.Boolean(
        string='Recopilar disponible', compute='_compute_pf_resolution')

    # ── REMEDIO estructural (recomendación; calculado, NO almacenado) ───
    # Clasifica la traba (falta física / contención / anomalía) y expone el
    # botón de remedio concreto, sin duplicar el motor de salud.
    pf_reservation_nature = fields.Selection(
        RESERVATION_NATURE_SELECTION, compute='_compute_pf_resolution')
    pf_remedy_key = fields.Char(compute='_compute_pf_resolution')
    pf_remedy_label = fields.Char(
        string='Recomendación', compute='_compute_pf_resolution')
    pf_remedy_kind = fields.Selection(
        PLAN_ACTION_SELECTION, compute='_compute_pf_resolution')
    pf_remedy_target = fields.Char(compute='_compute_pf_resolution')
    pf_remedy_available = fields.Boolean(
        string='Recomendación disponible', compute='_compute_pf_resolution')

    # ── Reserva colgada: saneamiento SIEMPRE disponible (Bloque III §28) ─
    # Aunque el tablero esté 'ok', si el producto tiene un quant con libre < 0
    # el saneamiento por producto se ofrece desde el escáner.
    pf_has_stuck_reservations = fields.Boolean(
        string='Reserva colgada', compute='_compute_pf_stuck_reservations')

    @api.depends('product_id')
    def _compute_pf_stuck_reservations(self):
        Remedy = self.env['printflow.stock.remedy']
        for finding in self:
            finding.pf_has_stuck_reservations = bool(
                finding.product_id) and bool(
                Remedy._pf_negative_quant_product_ids(
                    [finding.product_id.id]))

    def action_cleanup_reservations(self):
        """Sanea (suelta + re-asigna) las reservas colgadas del producto.

        Restringido a jefe de taller/administrador. Es el único botón con efecto
        de datos y NO despoja la reserva de ningún pedido: reasigna por reglas.
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        result = self.env['printflow.stock.health']._pf_cleanup_products(
            self.product_id)
        if result['pickings']:
            self.env['printflow.stock.health']._pf_notify_products(
                self.product_id)
            message = _('Saneamiento: %s albarán(es) re-asignado(s).') % (
                result['pickings'])
            ntype = 'success'
        else:
            message = _('No había reservas colgadas que sanear.')
            ntype = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': message,
                'type': ntype,
                'sticky': False,
            },
        }

    # ── ALIAS DEPRECADOS de 'solution' (compatibilidad v1) ──────────────
    # Las vistas y tests de la versión anterior usaban una acción única. Se
    # mantienen apuntando SIEMPRE a la solución/raíz. No usar en código nuevo.
    pf_action_label = fields.Char(
        string='Acción sugerida', compute='_compute_pf_resolution',
    )
    pf_action_kind = fields.Selection(
        PLAN_ACTION_SELECTION, string='Tipo de acción',
        compute='_compute_pf_resolution',
    )
    pf_action_target = fields.Char(
        string='Destino de la acción', compute='_compute_pf_resolution',
    )
    pf_action_available = fields.Boolean(
        string='Acción disponible', compute='_compute_pf_resolution',
    )

    @api.depends('check_code', 'severity', 'product_id', 'bom_id')
    def _compute_pf_resolution(self):
        """Normaliza la causa y traduce el plan del playbook a campos de vista."""
        Playbook = self.env['printflow.resolution.playbook']
        Remedy = self.env['printflow.stock.remedy']
        empty_plan = {
            'summary': '',
            'steps': [],
            'actions': {
                key: Playbook._pf_action('', 'none', '')
                for key in ('problem', 'solution', 'collect')
            },
        }
        for finding in self:
            cause = finding._pf_resolve_cause()
            product = finding.product_id
            # Naturaleza de la reserva (anomalía / contención) resuelta UNA vez
            # por hallazgo: así el playbook de ``free_exhausted`` ejecuta sus
            # ramas ``anomaly`` / ``contention`` también desde el escáner.
            reservation_nature = ''
            if product and cause == 'free_exhausted':
                reservation_nature = Remedy._pf_classify_reservation(
                    product, 0.0, 0.0)
            plan = (
                Playbook._pf_get_plan(cause, ctx={
                    'product': product,
                    'has_bom': bool(finding.bom_id),
                    'reservation_nature': reservation_nature,
                })
                if cause else empty_plan
            )
            actions = plan['actions']
            problem = actions['problem']
            solution = actions['solution']
            collect = actions['collect']

            finding.pf_cause = cause or False
            finding.pf_plan_summary = plan['summary']
            finding.pf_plan_steps = '\n'.join(
                '%d. %s' % (index, step)
                for index, step in enumerate(plan['steps'], start=1)
            )

            finding.pf_problem_label = problem['label']
            finding.pf_problem_kind = problem['kind']
            finding.pf_problem_target = problem['target']
            finding.pf_solution_label = solution['label']
            finding.pf_solution_kind = solution['kind']
            finding.pf_solution_target = solution['target']
            finding.pf_collect_label = collect['label']
            finding.pf_collect_kind = collect['kind']
            finding.pf_collect_target = collect['target']

            # Regla del mapa: si el SÍNTOMA y la RAÍZ coinciden (mismo destino),
            # se expone un solo botón (la solución) y se oculta el problema.
            same_place = (
                (problem['kind'], problem['target'])
                == (solution['kind'], solution['target'])
            )
            finding.pf_problem_available = problem['available'] and not same_place
            finding.pf_solution_available = solution['available']
            finding.pf_collect_available = collect['available']

            # ALIAS deprecados (== solución).
            finding.pf_action_label = solution['label']
            finding.pf_action_kind = solution['kind']
            finding.pf_action_target = solution['target']
            finding.pf_action_available = solution['available']

            finding._pf_assign_remedy(cause, reservation_nature)

    def _pf_assign_remedy(self, cause, reservation_nature=None):
        """Asigna el REMEDIO estructural del hallazgo (calculado).

        Cubre las causas que produce el motor unificado de flujo. Alineado con
        ``printflow.product.flow.diagnostic._pf_primary_remedy_key``: todas las
        claves devueltas existen en ``REMEDY_META``.

        :param reservation_nature: naturaleza ya resuelta por el llamador
            (``anomaly`` / ``contention`` / ...). Si es ``None`` se recalcula
            (compatibilidad con llamadas directas y tests v1).
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        product = self.product_id
        key = False
        nature = ''
        if product:
            if cause == 'negative':
                key, nature = 'adjust', 'ok'
            elif cause == 'data_anomaly':
                # Reserva colgada: se corrige saneando la reserva, no comprando.
                key, nature = 'fix_over_reservation', 'anomaly'
            elif cause == 'manufacture':
                key, nature = 'manufacture', 'physical'
            elif cause == 'manufacture_components':
                key, nature = 'buy_components', 'physical'
            elif cause == 'buy_product':
                key, nature = 'buy_product', 'physical'
            elif cause == 'no_bom':
                key, nature = 'no_bom', 'physical'
            elif cause == 'mo_stuck':
                # FASE 4: OF trabada -> priorizar (solo navegar a la OF).
                key, nature = 'prioritize_mo', ''
            elif cause == 'personalized_supply_stolen':
                # FASE 4/3: compra propia retenida -> reclamar la porción.
                key, nature = 'claim_own_purchase', 'contention'
            elif cause == 'contention_needs_supply':
                key, nature = 'blocking', 'contention'
            elif cause == 'free_exhausted':
                if reservation_nature is None:
                    state = Remedy._pf_product_reservation_state(product)
                    is_anomaly = (
                        state['has_negative_quant']
                        and state['free_global'] >= -_EPS)
                else:
                    is_anomaly = reservation_nature == 'anomaly'
                if is_anomaly:
                    key, nature = 'fix_over_reservation', 'anomaly'
                else:
                    key, nature = 'blocking', 'contention'
            elif cause in ('no_route', 'record_no_supplier', 'kit_no_own_stock'):
                key = Remedy._pf_physical_remedy_key(product, 0.0) or 'adjust'
                nature = 'physical' if key else ''
            elif cause == 'adjust_inventory':
                key, nature = 'adjust', 'physical'
            # Bloque V: si el hallazgo no tiene remedio de cantidad, se ofrece
            # el remedio de LOTE (trazabilidad) del mismo servicio genérico.
            if not key:
                lot_state = self.env['printflow.stock.health']._pf_lot_state(
                    product)
                # F3: resta de hallazgos AUTORIZADOS (adaptador de GI).
                lot_state = self.env[
                    'printflow.finding.exception.filter']._pf_apply_to_lot_info(
                        product, lot_state)
                if lot_state['state'] != 'lot_ok':
                    key = lot_state['remedy_key']
        self.pf_reservation_nature = nature or False
        self.pf_remedy_key = key or False
        if key:
            label, kind, target = Remedy._pf_remedy_meta(key)
            self.pf_remedy_label = label
            self.pf_remedy_kind = kind
            self.pf_remedy_target = target
            self.pf_remedy_available = kind != 'none'
        else:
            self.pf_remedy_label = ''
            self.pf_remedy_kind = False
            self.pf_remedy_target = ''
            self.pf_remedy_available = False

    def _pf_resolve_cause(self):
        """Traduce ``check_code`` + ``severity`` (y la ficha) a ``pf_cause``.

        Devuelve ``False`` para hallazgos informativos o correctos: no tienen
        nada que resolver y por eso no muestran plan.
        """
        self.ensure_one()
        if self.severity in ('ok', 'info'):
            return False
        code = self.check_code or ''
        if code == 'stock_negative':
            # ``check_inventory`` solo emite la existencia física negativa: la
            # disponibilidad agotada la reporta ``check_flow`` como causa
            # ``free_exhausted`` (prefijo ``flow_``), no este código.
            return 'negative'
        if code == 'record_state':
            product = self.product_id
            if product and not product.active:
                return 'record_archived'
            if product and product.type == 'product' and not product.seller_ids:
                return 'record_no_supplier'
            return False
        # FASE 4: el chequeo de flujo codifica la causa como ``flow_<cause>``.
        if code.startswith('flow_'):
            return code[len('flow_'):]
        return CHECK_CODE_TO_CAUSE.get(code)

    # ------------------------------------------------------------------
    # NAVEGACIÓN BAJO DEMANDA
    # ------------------------------------------------------------------
    def _pf_run_action(self, kind, target):
        """Ejecuta una acción del plan según su ``kind`` y ``target``.

        Es el único punto que traduce el vocabulario del plan a acciones
        Odoo. ``navigate`` solo navega; ``open_wizard`` abre un asistente
        prellenado; ``run_action`` ejecuta el remedio de re-reserva.
        """
        self.ensure_one()
        kind = kind or 'none'
        if kind == 'guide_to_order':
            return self._pf_guide_to_order()
        if kind == 'navigate':
            return self._pf_nav_action(target)
        if kind == 'open_wizard':
            return self._pf_open_wizard(target)
        if kind == 'run_action':
            return self._pf_run_action_target(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_open_wizard(self, target):
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
        self.ensure_one()
        target = target or ''
        if target == 'fix_over_reservation':
            return self._pf_run_fix_over_reservation()
        # Bloque V: remedios de LOTE (restringidos a jefe de taller/admin).
        if target in ('assign_lot', 'reconcile_lot_reservation',
                      'replace_generic_lot', 'separate_lots',
                      'repair_finished_lot'):
            return self._pf_run_lot_remedy(target)
        return {'type': 'ir.actions.act_window_close'}

    def _pf_run_lot_remedy(self, target):
        """Ejecuta un remedio de lote sobre el producto del hallazgo.

        Reutiliza el servicio genérico ``printflow.stock.health``. Nunca asigna
        a un pedido el lote de otro cliente.
        """
        self.ensure_one()
        product = self.product_id
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
        """Botón "Recomendación": ejecuta el remedio del hallazgo."""
        self.ensure_one()
        return self._pf_run_action(
            self.pf_remedy_kind, self.pf_remedy_target)

    def _pf_nav_action(self, target):
        """Extiende la navegación base con los destinos propios del plan."""
        self.ensure_one()
        target = target or 'none'
        if target == 'reserving_sale_orders':
            return self._pf_open_reserving_sale_orders()
        if target == 'quants_adjust':
            return self._pf_open_quants_adjust()
        if target == 'blocking_reservations':
            return self._pf_open_blocking_reservations()
        if target == 'collect_tray':
            return self.action_open_resolution_tray()
        if target == 'bom_duplicates':
            return self._pf_open_bom_duplicates()
        return super()._pf_nav_action(target)

    def action_open_problem(self):
        """Botón "Ir al problema": navega al SÍNTOMA (dónde se observa)."""
        self.ensure_one()
        return self._pf_run_action(
            self.pf_problem_kind, self.pf_problem_target)

    def action_open_solution(self):
        """Botón "Aplicar solución": navega a la RAÍZ (dónde se corrige)."""
        self.ensure_one()
        return self._pf_run_action(
            self.pf_solution_kind, self.pf_solution_target)

    def action_open_collect(self):
        """Botón "Recopilar": abre la RAÍZ EN CONJUNTO (lista agregada).

        Para ``free_exhausted`` es la lista de pedidos que reservan el producto
        (misma fuente bajo demanda que la solución). Para el resto de causas es
        la Bandeja de Resolución del propio hallazgo.
        """
        self.ensure_one()
        return self._pf_run_action(
            self.pf_collect_kind, self.pf_collect_target)

    def action_open(self):
        """ALIAS DEPRECADO del problema (compatibilidad Bandeja/tests v1)."""
        self.ensure_one()
        return self.action_open_problem()

    def action_open_plan_detail(self):
        """Abre el detalle del plan (resumen + pasos) en un diálogo."""
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Plan de resolución'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
        view = self.env.ref(PLAN_DETAIL_VIEW_XMLID, raise_if_not_found=False)
        if view:
            action['views'] = [(view.id, 'form')]
        return action

    # ALIAS DEPRECADO (v1): el botón único del plan era la solución/raíz.
    def action_open_plan(self):
        """Botón del plan de resolución v1: ahora delega en la solución."""
        return self.action_open_solution()

    def _pf_open_reserving_sale_orders(self):
        """Abre la lista de pedidos que reservan el producto (solo lectura)."""
        self.ensure_one()
        orders = pf_reserving_sale_orders(
            self.env, self.product_id, exclude_sale_order=self.sale_order_id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s pedido(s) que lo reservan') % len(orders),
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', orders.ids)],
            'target': 'current',
        }

    def _pf_open_quants_adjust(self):
        """Abre las existencias del producto en MODO AJUSTE de inventario.

        Se construye una ``act_window`` de ``stock.quant`` filtrada por producto
        con ``inventory_mode`` en contexto: así el operador edita la cantidad
        contada sin salir del flujo. Es SOLO una pantalla de edición; no ejecuta
        ningún ajuste por sí sola.
        """
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajuste de inventario de %s')
            % self.product_id.display_name,
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', self.product_id.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'context': {
                'inventory_mode': True,
                'search_default_product_id': self.product_id.id,
            },
            'target': 'current',
        }

    def _pf_open_bom_duplicates(self):
        """Abre la lista de BOM filtrada a las duplicadas del hallazgo.

        Los causantes recolectables del chequeo de BOM duplicada son las propias
        BOM repetidas: se reutilizan para acotar la lista.
        """
        self.ensure_one()
        bom_ids = self.evidence_ids.mapped('bom_id').ids
        if not bom_ids:
            return super()._pf_nav_action('bom_list')
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s lista(s) duplicada(s)') % len(bom_ids),
            'res_model': 'mrp.bom',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', bom_ids)],
            'target': 'current',
        }

    def _pf_guide_to_order(self):
        """Guía al plan de resolución del pedido relacionado.

        Si hay UN solo pedido, abre su diagnóstico (o su ficha); si hay varios
        (o ninguno), abre la lista de pedidos para no perder el gesto.
        """
        self.ensure_one()
        order_ids = self._pf_sale_order_target_ids()
        order = (
            self.env['sale.order'].browse(order_ids).exists()
            if order_ids else self.env['sale.order']
        )
        if len(order) == 1:
            board = self.env['printflow.order.board'].search(
                [('sale_order_id', '=', order.id)], limit=1)
            if board:
                return board.action_open_diagnostic_wizard()
            return {
                'type': 'ir.actions.act_window',
                'name': order.display_name,
                'res_model': 'sale.order',
                'res_id': order.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('%s pedido(s) por resolver') % len(order),
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', order.ids)],
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # REMEDIOS DEL ESCÁNER DE PRODUCTO (open_wizard / run_action)
    #
    # "Abrir ≠ ejecutar". La compra rápida admite producto sin pedido de venta
    # (decisión 10). La re-reserva solo se ofrece si se puede resolver el
    # tablero de origen; si no, se navega a los pedidos que reservan.
    # ------------------------------------------------------------------
    def _pf_resolve_board(self):
        """Tablero del pedido de la evidencia (o del pedido del hallazgo)."""
        self.ensure_one()
        order = self.sale_order_id or self.evidence_ids.mapped('sale_order_id')[:1]
        if not order:
            return self.env['printflow.order.board']
        return self.env['printflow.order.board'].search(
            [('sale_order_id', '=', order.id)], limit=1)

    def _pf_open_create_production(self):
        """Abre/crea la OF del producto (bloquea si no hay BOM: decisión 7)."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        if not Remedy._pf_has_bom(product):
            raise UserError(_(
                'El producto "%s" no tiene lista de materiales (BOM): no se '
                'puede crear una Orden de Fabricación. Crea la BOM o usa Ajuste '
                'de inventario.') % product.display_name)
        bom = self.env['mrp.bom']._bom_find(product).get(product)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Nueva Orden de Fabricación'),
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_product_id': product.id,
                'default_product_qty': 1.0,
                'default_bom_id': bom.id if bom else False,
            },
        }

    def _pf_open_buy_product(self):
        """Compra Rápida del producto, SIN pedido de venta (decisión 10)."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        return self._pf_open_quick_purchase(
            [(product, 1.0)], title=_('Compra Rápida (producto)'))

    def _pf_open_buy_components(self):
        """Compra Rápida de los componentes faltantes de la BOM."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        missing = Remedy._pf_missing_components(product, 1.0)
        if not missing:
            return self._pf_open_buy_product()
        return self._pf_open_quick_purchase(
            [(m['product'], m['need']) for m in missing],
            title=_('Compra Rápida (componentes)'))

    def _pf_open_quick_purchase(self, product_qty_list, title):
        """Crea el asistente de compra rápida con líneas prellenadas."""
        self.ensure_one()
        order = self.sale_order_id or self.evidence_ids.mapped('sale_order_id')[:1]
        line_vals = []
        for product, qty in product_qty_list:
            vals = {
                'product_id': product.id,
                'product_qty': qty or 1.0,
                'product_uom_id': product.uom_id.id,
                'material_received': False,
            }
            if product.seller_ids:
                vals['partner_id'] = product.seller_ids[0].partner_id.id
            if order and order.currency_id:
                vals['currency_id'] = order.currency_id.id
            line_vals.append((0, 0, vals))
        wizard = self.env['mrp.quick.purchase.wizard'].create({
            'sale_order_id': order.id if order else False,
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
        """Re-reserva (saneamiento) si hay tablero; si no, navega a quien reserva.

        Restringido a jefe de taller/administrador (decisión 13).
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        board = self._pf_resolve_board()
        if not board:
            return self._pf_open_reserving_sale_orders()
        still_missing = board._fix_over_reservation_and_refresh()
        board.message_post(
            body=_(
                'Se liberó y re-reservó el inventario desde el diagnóstico de '
                'producto (remedio estructural).'),
            message_type='notification', subtype_xmlid='mail.mt_note',
        )
        if still_missing:
            message = _('Se liberó la reserva colgada, pero aún falta stock '
                        'físico: ahora sí toca comprar o fabricar.')
            ntype = 'warning'
        elif still_missing is None:
            message = _('El pedido de origen no tiene albaranes pendientes de '
                        'reserva.')
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
            },
        }

    def _pf_open_blocking_reservations(self):
        """En el escáner no hay wizard de pedido: se listan los que reservan."""
        self.ensure_one()
        return self._pf_open_reserving_sale_orders()
