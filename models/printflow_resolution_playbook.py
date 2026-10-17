# -*- coding: utf-8 -*-
"""Playbook de resolución del diagnóstico de producto (PrintFlow).

ÚNICA fuente de verdad de los TEXTOS y PASOS que explican CÓMO resolver un
hallazgo. No toca la detección: recibe una causa normalizada (``pf_cause``) y
devuelve un plan listo para pintar en pantalla.

Contrato del plan (v2, contrato extendido de 3 acciones)::

    {
        'summary': str,                 # microcopy en palabras simples
        'steps': [str, ...],            # pasos numerados
        'actions': {
            'problem':  {'label', 'kind', 'target', 'available'},
            'solution': {'label', 'kind', 'target', 'available'},
            'collect':  {'label', 'kind', 'target', 'available'},
        },
        # ALIAS DEPRECADOS (compatibilidad v1): apuntan SIEMPRE a 'solution'.
        'action_label': str,
        'action_kind': str,
        'target': str,
    }

Semántica de las tres acciones:

  * ``problem``  -> SÍNTOMA: dónde se observa el hallazgo.
  * ``solution`` -> RAÍZ: dónde se corrige el hallazgo.
  * ``collect``  -> RAÍZ EN CONJUNTO: lista agregada de causantes-raíz.

Cuando síntoma y raíz coinciden (mismo ``kind`` y ``target``), el hallazgo oculta
"problema" y ofrece un solo botón (la solución): esa regla se aplica al
materializar el plan en el hallazgo, no aquí.

``kind`` ∈ ``none | navigate | guide_to_order``. ``available`` = ``kind != none``.

El contrato de ``target`` es el vocabulario de navegación (``nav_kind``) más dos
destinos propios del plan: ``quants_adjust`` (ajuste de inventario),
``bom_duplicates`` (lista de BOM filtrada a las duplicadas) y ``collect_tray``
(Bandeja de Resolución del hallazgo). ``reserving_sale_orders`` abre bajo demanda
la lista de pedidos que reservan el producto.

Diseño: ``AbstractModel`` sin estado ni tabla (cero migración). Toda causa
desconocida cae al plan GENÉRICO ("Revisa el registro señalado").
"""

from odoo import _, api, models

# La selección de tipos de acción del plan vive en el PRINCIPAL (clasificador de
# remedios); se reexporta aquí para no duplicarla y respetar la dirección
# correcta de dependencia: diagnóstico -> principal.
from odoo.addons.x_product_dimensional_pricing.models.printflow_stock_remedy import (  # noqa: E501
    PLAN_ACTION_SELECTION,
)

# Causas normalizadas del diagnóstico. Se derivan de ``check_code`` + ``severity``
# en el hallazgo (``pf_cause``). Fuente única de verdad.
PF_CAUSE_SELECTION = [
    ('negative', _('Existencia negativa')),
    ('free_exhausted', _('Libre agotada (apartado por otros)')),
    ('data_anomaly', _('Reserva colgada (inconsistencia de datos)')),
    ('adjust_inventory', _('Sin ruta: ajustar inventario')),
    ('manufacture', _('Falta física: fabricar')),
    ('manufacture_components', _('Falta física: comprar componentes')),
    ('buy_product', _('Falta física: comprar el producto')),
    ('no_bom', _('Fabricable sin lista de materiales')),
    ('kit_no_own_stock', _('Kit sin stock propio')),
    ('bom_duplicated', _('Lista de materiales duplicada')),
    ('bom_archive_blocked', _('Archivado de lista bloqueado')),
    ('orderpoint_kit', _('Regla de reorden a revisar')),
    ('uom_mismatch', _('Unidades de medida incompatibles')),
    ('no_route', _('Sin ruta ni proveedor')),
    ('pending_sale_lines', _('Ventas pendientes')),
    ('active_mo', _('Órdenes de fabricación activas')),
    ('record_archived', _('Producto archivado')),
    ('record_no_supplier', _('Almacenable sin proveedor')),
    # Causas del diagnóstico de PEDIDO por producto/nivel. Reutilizan el mismo
    # contrato de tres acciones; los destinos propios ('product',
    # 'purchase_order', 'receipt', 'mo') los resuelve el wizard de niveles.
    ('order_shortfall', _('Déficit sin ruta (pedido)')),
    ('order_supply_missing', _('Falta comprar (pedido)')),
    ('order_receive_pending', _('Compra por recibir (pedido)')),
    ('order_production_blocked', _('Fabricación trabada (pedido)')),
    ('order_delivery_pending', _('Pendiente por entrega (pedido)')),
    # La OF existe pero NO tiene insumos cargados (raíz en el almacén de
    # insumos): hay que abrirla y cargar/definir sus materiales.
    ('mo_without_materials', _('OF sin insumos cargados')),
    # Causas NUEVAS del motor unificado de flujo (casos d, e, f).
    ('mo_stuck', _('Orden de fabricación trabada')),
    ('contention_needs_supply', _('Contención sin entrada ni libre')),
    ('personalized_supply_stolen', _('Abastecimiento propio retenido')),
    # ── Bloque V: causas de LOTE / trazabilidad ─────────────────────────
    ('lot_missing', _('Movimiento sin lote')),
    ('lot_orphan_reservation', _('Reserva de lote huérfana')),
    ('lot_no_stock', _('Lote reservado sin existencia')),
    ('lot_generic', _('Lote genérico en producto gestionado')),
    ('lot_mixed', _('Lotes mezclados')),
    ('lot_unassigned_finished', _('Terminado sin lote')),
    # Causa del ALMACÉN DE INSUMOS: un componente está reservado de más, sin
    # existencia, apartado por otros pedidos o sin forma de reponer.
    ('supply_issue', _('Problema en el almacén de insumos')),
]

# Claves de las tres acciones del contrato extendido.
PLAN_ACTION_KEYS = ('problem', 'solution', 'collect')


class PrintflowResolutionPlaybook(models.AbstractModel):
    """Motor de microcopy de resolución (solo texto y pasos)."""

    _name = 'printflow.resolution.playbook'
    _description = 'Playbook de resolución del diagnóstico (PrintFlow)'

    # ------------------------------------------------------------------
    # CONTRATO
    # ------------------------------------------------------------------
    @api.model
    def _pf_get_plan(self, pf_cause, ctx=None):
        """Devuelve el plan de resolución de una causa normalizada.

        :param str pf_cause: valor de ``PF_CAUSE_SELECTION`` (o ``False``).
        :param dict ctx: contexto opcional para el microcopy (p. ej.
            ``{'product': product.product, 'has_bom': bool}``). Nunca dispara
            consultas extra.
        :return: dict con ``summary``, ``steps`` y ``actions`` (problem,
            solution, collect). Incluye los ALIAS DEPRECADOS ``action_label``,
            ``action_kind`` y ``target`` (== ``solution``).
        :rtype: dict
        """
        ctx = ctx or {}
        builder = self._pf_plan_builders().get(pf_cause)
        plan = builder(ctx) if builder else self._pf_plan_fallback()
        return self._pf_normalize_plan(plan)

    @api.model
    def _pf_action(self, label, kind='none', target=''):
        """Construye UNA de las tres acciones del contrato extendido.

        :param str label: etiqueta visible del botón.
        :param str kind: ``none | navigate | guide_to_order``.
        :param str target: destino de navegación (vocabulario ``nav_kind``).
        :rtype: dict
        """
        kind = kind or 'none'
        return {
            'label': label or '',
            'kind': kind,
            'target': target or '',
            'available': kind != 'none',
        }

    @api.model
    def _pf_normalize_plan(self, plan):
        """Completa las tres acciones y agrega los ALIAS deprecados de la raíz.

        Garantiza que ``actions`` siempre traiga las tres claves y que cada
        acción sea un dict válido con ``available`` coherente con su ``kind``.
        Los alias ``action_label`` / ``action_kind`` / ``target`` se mantienen
        SOLO por compatibilidad con las vistas y tests v1.
        """
        actions = dict(plan.get('actions') or {})
        for key in PLAN_ACTION_KEYS:
            action = dict(actions.get(key) or {})
            action.setdefault('label', '')
            action.setdefault('kind', 'none')
            action.setdefault('target', '')
            action['kind'] = action['kind'] or 'none'
            action['target'] = action['target'] or ''
            action['available'] = action['kind'] != 'none'
            actions[key] = action
        # Regla del mapa: si el SÍNTOMA y la RAÍZ coinciden (mismo destino), el
        # plan expone un solo botón (la solución) y desactiva "problema".
        problem, solution = actions['problem'], actions['solution']
        if (problem['kind'], problem['target']) == (
                solution['kind'], solution['target']):
            problem['available'] = False
        return {
            'summary': plan.get('summary', ''),
            'steps': list(plan.get('steps') or []),
            'actions': actions,
            # ALIAS DEPRECADOS (v1): la acción única era la solución/raíz.
            'action_label': solution['label'],
            'action_kind': solution['kind'],
            'target': solution['target'],
        }

    @api.model
    def _pf_plan(self, summary, steps, problem, solution, collect=None):
        """Ensambla un plan con sus tres acciones (collect opcional)."""
        return {
            'summary': summary,
            'steps': steps,
            'actions': {
                'problem': problem,
                'solution': solution,
                'collect': collect or self._pf_action('', 'none', ''),
            },
        }

    @api.model
    def _pf_plan_builders(self):
        """Mapa causa -> constructor del plan (extensible sin tocar el motor)."""
        return {
            'negative': self._pf_plan_negative,
            'free_exhausted': self._pf_plan_free_exhausted,
            'data_anomaly': self._pf_plan_data_anomaly,
            'adjust_inventory': self._pf_plan_adjust_inventory,
            'manufacture': self._pf_plan_manufacture,
            'manufacture_components': self._pf_plan_manufacture_components,
            'buy_product': self._pf_plan_buy_product,
            'no_bom': self._pf_plan_no_bom,
            'kit_no_own_stock': self._pf_plan_kit_no_own_stock,
            'bom_duplicated': self._pf_plan_bom_duplicated,
            'bom_archive_blocked': self._pf_plan_bom_archive_blocked,
            'orderpoint_kit': self._pf_plan_orderpoint_kit,
            'uom_mismatch': self._pf_plan_uom_mismatch,
            'no_route': self._pf_plan_no_route,
            'pending_sale_lines': self._pf_plan_pending_sale_lines,
            'active_mo': self._pf_plan_active_mo,
            'record_archived': self._pf_plan_record_archived,
            'record_no_supplier': self._pf_plan_record_no_supplier,
            'order_shortfall': self._pf_plan_order_shortfall,
            'order_supply_missing': self._pf_plan_order_supply_missing,
            'order_receive_pending': self._pf_plan_order_receive_pending,
            'order_production_blocked': self._pf_plan_order_production_blocked,
            'order_delivery_pending': self._pf_plan_order_delivery_pending,
            # OF sin insumos (raíz en el almacén de insumos).
            'mo_without_materials': self._pf_plan_mo_without_materials,
            # Causas nuevas del motor unificado (d, e, f).
            'mo_stuck': self._pf_plan_mo_stuck,
            'contention_needs_supply': self._pf_plan_contention_needs_supply,
            'personalized_supply_stolen': self._pf_plan_personalized_supply_stolen,
            # Bloque V: planes de lote.
            'lot_missing': self._pf_plan_lot_missing,
            'lot_orphan_reservation': self._pf_plan_lot_orphan_reservation,
            'lot_no_stock': self._pf_plan_lot_no_stock,
            'lot_generic': self._pf_plan_lot_generic,
            'lot_mixed': self._pf_plan_lot_mixed,
            'lot_unassigned_finished': self._pf_plan_lot_unassigned_finished,
            # Almacén de insumos (componentes de la BOM).
            'supply_issue': self._pf_plan_supply_issue,
        }

    # ------------------------------------------------------------------
    # PLANES (un método por causa; textos cortos, de mostrador)
    # ------------------------------------------------------------------
    @api.model
    def _pf_plan_negative(self, ctx):
        """Error de existencia negativa: se corrige con un ajuste de inventario.

        Síntoma y raíz viven en las existencias, pero la raíz se corrige en modo
        ajuste (``quants_adjust``). No hay raíz agregada que recopilar.
        """
        return self._pf_plan(
            summary=_(
                'La existencia física está en negativo: se descargó más de lo '
                'que había en almacén.'),
            steps=[
                _('Abre las existencias por ubicación para ver dónde quedó el '
                  'negativo.'),
                _('Revisa el último movimiento o ajuste que lo provocó.'),
                _('Corrige el conteo con un ajuste de inventario y recalcula '
                  'el diagnóstico.'),
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Ajustar el inventario'), 'navigate', 'quants_adjust'),
        )

    @api.model
    def _pf_plan_free_exhausted(self, ctx):
        """CASO CENTRAL: libre agotada por reservas de otros pedidos.

        Sin ``ctx`` (escáner de producto) conserva el plan histórico: el síntoma
        se ve en las existencias y la raíz son los pedidos que apartan el stock.

        Con ``ctx['reservation_nature']`` ramifica:
          * ``anomaly``    -> reserva colgada: se corrige con re-reserva.
          * ``contention`` -> lo tienen OTROS pedidos: se resuelve la causa raíz
            del bloqueante (nunca se le quita la reserva).
        """
        nature = (ctx or {}).get('reservation_nature') or ''
        if nature == 'anomaly':
            return self._pf_plan_data_anomaly(ctx)
        if nature == 'contention':
            return self._pf_plan_contention(ctx)
        return self._pf_plan(
            summary=_(
                'Todo lo que hay en almacén ya está apartado para otros '
                'pedidos: a este pedido no le queda nada libre.'),
            steps=[
                _('Mira las entregas que lo tienen apartado y decide cuál es '
                  'menos urgente.'),
                _('Resuelve la causa raíz en el pedido/albarán que lo bloquea '
                  '(su fabricación, su compra o su BOM).'),
                _('Si de verdad no alcanza, compra o fabrica más; la reserva '
                  'ajena no se toca.'),
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Ver qué pedidos lo reservan'), 'navigate',
                'reserving_sale_orders'),
            collect=self._pf_action(
                _('Recopilar pedidos que lo reservan'), 'navigate',
                'reserving_sale_orders'),
        )

    @api.model
    def _pf_plan_contention(self, ctx):
        """CONTENCIÓN real: el stock existe pero lo retienen otras entregas.

        La unidad de la lista es la ENTREGA/ALBARÁN (incluye POS sin pedido).
        La solución NO libera reserva ajena: guía a resolver la raíz del
        bloqueante y a reasignar desde el tablero.
        """
        return self._pf_plan(
            summary=_(
                'El stock existe, pero lo tienen apartado otras entregas. No '
                'hay que comprar: hay que resolver la raíz del bloqueante.'),
            steps=[
                _('Abre "Quién me bloquea" y localiza la entrega que retiene '
                  'el stock (con su pedido, cliente y fecha comprometida).'),
                _('Entra a la raíz de esa entrega y resuélvela allí (su OF, su '
                  'BOM, su compra). No se le quita la reserva.'),
                _('Recalcula el diagnóstico para confirmar que el stock quedó '
                  'libre.'),
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Ver quién me bloquea'), 'navigate', 'blocking_reservations'),
            collect=self._pf_action(
                _('Recopilar entregas que lo reservan'), 'navigate',
                'delivery_orders'),
        )

    @api.model
    def _pf_plan_data_anomaly(self, ctx):
        """ANOMALÍA: reserva colgada en una ubicación sin existencia.

        No falta mercancía ni la tienen otros: hay un quant con libre negativo
        compensado por otros. Se corrige saneando la reserva; comprar o fabricar
        sería un error.
        """
        return self._pf_plan(
            summary=_(
                'No falta mercancía ni la tienen otros: hay una reserva '
                'inconsistente en una ubicación sin existencia. Corrige la '
                'reserva; no compres.'),
            steps=[
                _('Revisa las existencias: verás un quant con libre negativo '
                  'aunque el total del producto sí alcanza.'),
                _('Pulsa "Liberar y re-reservar" para reasignar según el stock '
                  'real. No le quita unidades a ningún pedido.'),
                _('Si tras recalcular sigue faltando stock físico, entonces sí '
                  'toca comprar o fabricar.'),
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Liberar y re-reservar (sanear la reserva)'),
                'run_action', 'fix_over_reservation'),
            collect=self._pf_action(
                _('Recopilar entregas que lo reservan'), 'navigate',
                'delivery_orders'),
        )

    @api.model
    def _pf_plan_adjust_inventory(self, ctx):
        """Sin ruta ni proveedor: la salida honesta es contar/ajustar o corregir."""
        return self._pf_plan(
            summary=_(
                'Este producto no se fabrica ni se compra (sin ruta ni '
                'proveedor): la única salida es contar/ajustar la existencia o '
                'corregir la ficha.'),
            steps=[
                _('Abre la ficha del producto y revisa su ruta de '
                  'abastecimiento y su proveedor.'),
                _('Si no hay ruta, ajusta el inventario por la cantidad que '
                  'falta.'),
                _('Recalcula el diagnóstico para confirmar.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Ajustar el inventario'), 'navigate', 'quants_adjust'),
        )

    @api.model
    def _pf_plan_manufacture(self, ctx):
        """Fabricable con BOM y componentes disponibles: lanzar la OF."""
        return self._pf_plan(
            summary=_(
                'El producto se fabrica y tiene sus componentes: lanza la Orden '
                'de Fabricación por lo que falta.'),
            steps=[
                _('Abre/crea la Orden de Fabricación por la cantidad faltante.'),
                _('Verifica el consumo de componentes.'),
                _('Confírmala y recalcúlala para liberar el pedido.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Fabricar'), 'open_wizard', 'create_production'),
        )

    @api.model
    def _pf_plan_manufacture_components(self, ctx):
        """Fabricable con BOM pero faltan componentes: comprar los insumos."""
        return self._pf_plan(
            summary=_(
                'El producto se fabrica pero faltan componentes: compra los '
                'materiales que la lista de materiales requiere.'),
            steps=[
                _('Revisa qué componentes de la BOM no tienen existencia.'),
                _('Genera la compra de esos componentes.'),
                _('Cuando lleguen, recíbelos y lanza la fabricación.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Comprar los componentes'), 'open_wizard', 'buy_components'),
        )

    @api.model
    def _pf_plan_buy_product(self, ctx):
        """No se fabrica pero se compra: generar la compra del producto."""
        return self._pf_plan(
            summary=_(
                'Este producto no se fabrica pero sí se compra: genera la '
                'compra por la cantidad que falta.'),
            steps=[
                _('Revisa la cantidad faltante (el déficit físico).'),
                _('Genera la Orden de Compra con el proveedor del producto.'),
                _('Recíbela para liberar el pedido.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Comprar el producto'), 'open_wizard', 'buy_product'),
        )

    @api.model
    def _pf_plan_no_bom(self, ctx):
        """Fabricable por regla pero SIN BOM: no se puede crear una OF real."""
        return self._pf_plan(
            summary=_(
                'Es fabricable por su ruta pero NO tiene lista de materiales: '
                'Odoo no puede crear una Orden de Fabricación real. Crea la BOM '
                'o ajusta el inventario.'),
            steps=[
                _('Abre las listas de materiales del producto y crea la que '
                  'falta.'),
                _('Si el producto tampoco se compra, ajusta el inventario.'),
                _('Recalcula el diagnóstico para confirmar.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Ver listas de materiales'), 'navigate', 'bom_list'),
        )

    @api.model
    def _pf_plan_kit_no_own_stock(self, ctx):
        """Kit sin stock propio: el kit no se almacena, sus componentes sí."""
        return self._pf_plan(
            summary=_(
                'Es un kit: no guarda stock propio. Su disponibilidad sale de '
                'sus componentes.'),
            steps=[
                _('Abre la lista de materiales del kit y revisa sus '
                  'componentes.'),
                _('Identifica qué componente no tiene existencia libre '
                  'suficiente.'),
                _('Repón ese componente (compra o fabricación) y recalcula.'),
            ],
            problem=self._pf_action(
                _('Ver existencias del kit'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Ver componentes del kit (BOM)'), 'navigate', 'bom'),
            collect=self._pf_action(
                _('Recopilar componentes sin stock'), 'navigate',
                'collect_tray'),
        )

    @api.model
    def _pf_plan_bom_duplicated(self, ctx):
        """BOM duplicada: el síntoma y la raíz están en la lista de BOM."""
        return self._pf_plan(
            summary=_(
                'Hay más de una lista de materiales activa del mismo tipo: '
                'Odoo no sabrá cuál usar al fabricar.'),
            steps=[
                _('Abre la lista de listas de materiales del producto.'),
                _('Compara las duplicadas y quédate con la correcta.'),
                _('Archiva las que no uses para dejar una sola por tipo.'),
            ],
            problem=self._pf_action(
                _('Ver listas de materiales'), 'navigate', 'bom_list'),
            solution=self._pf_action(
                _('Ver solo las duplicadas'), 'navigate', 'bom_duplicates'),
            collect=self._pf_action(
                _('Recopilar listas duplicadas'), 'navigate', 'collect_tray'),
        )

    @api.model
    def _pf_plan_bom_archive_blocked(self, ctx):
        """Archivado de BOM bloqueado: hay pedidos confirmados usándola."""
        return self._pf_plan(
            summary=_(
                'No se puede archivar la lista de materiales porque hay '
                'pedidos confirmados que todavía la están usando.'),
            steps=[
                _('Abre los pedidos que bloquean el archivado.'),
                _('Entrégalos, factúralos o cancélalos según corresponda.'),
                _('Vuelve y archiva la lista de materiales.'),
            ],
            problem=self._pf_action(
                _('Ver la lista de materiales del kit'), 'navigate', 'bom'),
            solution=self._pf_action(
                _('Ver pedidos que la bloquean'), 'navigate', 'sale_orders'),
            collect=self._pf_action(
                _('Recopilar pedidos bloqueantes'), 'navigate',
                'collect_tray'),
        )

    @api.model
    def _pf_plan_orderpoint_kit(self, ctx):
        """Regla de reorden a revisar: el síntoma es la ficha (el producto)."""
        return self._pf_plan(
            summary=_(
                'Hay una regla de reorden sobre un producto que no debería '
                'reponerse por esa vía.'),
            steps=[
                _('Abre la regla de reorden señalada.'),
                _('Verifica si de verdad la necesitas para este producto.'),
                _('Ajusta o elimina la regla y recalcula el diagnóstico.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Ver regla de reorden'), 'navigate', 'orderpoint'),
            collect=self._pf_action(
                _('Recopilar regla de reorden'), 'navigate', 'collect_tray'),
        )

    @api.model
    def _pf_plan_uom_mismatch(self, ctx):
        """UdM incompatible: si el hallazgo trae BOM, la raíz está en la BOM."""
        has_bom = bool(ctx.get('has_bom'))
        solution = (
            self._pf_action(_('Ver la lista de materiales'), 'navigate', 'bom')
            if has_bom
            else self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product')
        )
        return self._pf_plan(
            summary=_(
                'Hay unidades de medida que no se pueden convertir entre sí: '
                'el consumo o la compra puede quedar mal calculado.'),
            steps=[
                _('Abre la ficha del producto o la lista de materiales '
                  'señalada.'),
                _('Corrige la unidad de medida para que sea de la misma '
                  'categoría.'),
                _('Guarda y recalcula el diagnóstico.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=solution,
        )

    @api.model
    def _pf_plan_no_route(self, ctx):
        """Sin ruta ni proveedor: un solo botón (la ficha del producto)."""
        return self._pf_plan(
            summary=_(
                'Este producto no tiene ruta de abastecimiento ni proveedor: '
                'no se va a reponer solo.'),
            steps=[
                _('Abre la ficha del producto.'),
                _('Agrega la ruta de compra/fabricación o el proveedor con su '
                  'precio.'),
                _('Guarda y recalcula el diagnóstico.'),
            ],
            problem=self._pf_action('', 'none', ''),
            solution=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
        )

    @api.model
    def _pf_plan_pending_sale_lines(self, ctx):
        """Ventas pendientes: el síntoma son las líneas; la raíz, los pedidos."""
        return self._pf_plan(
            summary=_(
                'Hay pedidos confirmados con entrega o facturación pendiente: '
                'esa es la demanda que tiene comprometido el stock.'),
            steps=[
                _('Abre los pedidos pendientes.'),
                _('Entrégalos o factúralos para liberar el compromiso.'),
                _('Recalcula el diagnóstico para confirmar.'),
            ],
            problem=self._pf_action(
                _('Ver líneas de venta'), 'navigate', 'sale_lines'),
            solution=self._pf_action(
                _('Ver pedidos pendientes'), 'navigate', 'sale_orders'),
            collect=self._pf_action(
                _('Recopilar pedidos pendientes'), 'navigate', 'collect_tray'),
        )

    @api.model
    def _pf_plan_active_mo(self, ctx):
        """MO activas: el síntoma es la lista; la raíz, la orden concreta."""
        return self._pf_plan(
            summary=_(
                'Hay órdenes de fabricación en curso que consumen o van a '
                'consumir este producto.'),
            steps=[
                _('Abre las órdenes de fabricación señaladas.'),
                _('Revisa si están trabadas o esperando material.'),
                _('Priorízalas o ciérralas para liberar la reserva.'),
            ],
            problem=self._pf_action(
                _('Ver órdenes de fabricación'), 'navigate', 'mo_list'),
            solution=self._pf_action(
                _('Ver la orden de fabricación'), 'navigate', 'mo'),
            collect=self._pf_action(
                _('Recopilar órdenes de fabricación'), 'navigate',
                'collect_tray'),
        )

    @api.model
    def _pf_plan_record_archived(self, ctx):
        """Producto archivado: un solo botón (la ficha del producto)."""
        return self._pf_plan(
            summary=_(
                'La ficha del producto está archivada: no se vende ni aparece '
                'en las búsquedas.'),
            steps=[
                _('Abre la ficha del producto.'),
                _('Reactívala si debe seguir vendiéndose.'),
                _('Guarda y recalcula el diagnóstico.'),
            ],
            problem=self._pf_action('', 'none', ''),
            solution=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
        )

    @api.model
    def _pf_plan_record_no_supplier(self, ctx):
        """Almacenable sin proveedor: un solo botón (la ficha del producto)."""
        return self._pf_plan(
            summary=_(
                'Es un producto almacenable sin proveedor: no se puede comprar '
                'automáticamente.'),
            steps=[
                _('Abre la ficha del producto.'),
                _('Agrega el proveedor y su precio de compra.'),
                _('Guarda y recalcula el diagnóstico.'),
            ],
            problem=self._pf_action('', 'none', ''),
            solution=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
        )

    # ------------------------------------------------------------------
    # PLANES DEL DIAGNÓSTICO DE PEDIDO POR PRODUCTO (causas nuevas)
    #
    # El nodo roto de una línea de producto/componente se traduce a una de
    # estas causas. Reutilizan el contrato de tres acciones y el vocabulario de
    # destino que resuelve el wizard de niveles:
    #   * product        -> ficha del producto de la línea.
    #   * purchase_order -> Órdenes de Compra vinculadas al pedido.
    #   * receipt        -> albaranes de entrada de esas compras.
    #   * mo             -> Órdenes de Fabricación del pedido.
    # ------------------------------------------------------------------
    @api.model
    def _pf_plan_order_shortfall(self, ctx):
        """Déficit sin ruta: falta stock físico y no hay compra ni fabricación."""
        return self._pf_plan(
            summary=_(
                'No alcanza lo que hay en almacén ni lo que viene en camino, y '
                'el pedido no tiene una ruta clara para reponerlo.'),
            steps=[
                _('Abre la ficha del producto para revisar su ruta de '
                  'abastecimiento.'),
                _('Compra o fabrica la cantidad que falta.'),
                _('Recalcula el diagnóstico para confirmar que el déficit bajó.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Ver la compra del pedido'), 'navigate', 'purchase_order'),
        )

    @api.model
    def _pf_plan_order_supply_missing(self, ctx):
        """Falta comprar: producto comprable con déficit y sin compra generada."""
        return self._pf_plan(
            summary=_(
                'Falta generar la compra: el producto se compra pero todavía no '
                'tiene Orden de Compra por lo que falta.'),
            steps=[
                _('Revisa la cantidad que falta de verdad (el déficit físico).'),
                _('Genera la solicitud de compra por esa cantidad.'),
                _('Cuando llegue, recíbela para liberar el pedido.'),
            ],
            problem=self._pf_action(
                _('Abrir ficha del producto'), 'navigate', 'product'),
            solution=self._pf_action(
                _('Comprar lo que falta'), 'open_wizard', 'buy_product'),
        )

    @api.model
    def _pf_plan_order_receive_pending(self, ctx):
        """Compra por recibir: la PO existe pero el albarán no está validado."""
        return self._pf_plan(
            summary=_(
                'La compra ya existe, pero la mercancía todavía no ha entrado '
                'al almacén.'),
            steps=[
                _('Abre la compra del pedido.'),
                _('Valida el albarán de entrada cuando llegue la mercancía.'),
                _('Verifica que el stock quedó reservado al pedido.'),
            ],
            problem=self._pf_action(
                _('Ver la compra del pedido'), 'navigate', 'purchase_order'),
            solution=self._pf_action(
                _('Abrir el albarán de entrada'), 'navigate', 'receipt'),
        )

    @api.model
    def _pf_plan_order_production_blocked(self, ctx):
        """Fabricación trabada: sin MO, sin material o con retraso/arte pendiente."""
        return self._pf_plan(
            summary=_(
                'La fabricación del pedido está trabada: revisa su Orden de '
                'Fabricación, su material o el arte pendiente.'),
            steps=[
                _('Abre la Orden de Fabricación del pedido.'),
                _('Revisa si está sin lanzar, sin material o con arte pendiente.'),
                _('Priorízala o completa lo que falte y recalcula.'),
            ],
            problem=self._pf_action(
                _('Ver la Orden de Fabricación'), 'navigate', 'mo'),
            solution=self._pf_action(
                _('Abrir la Orden de Fabricación'), 'navigate', 'mo'),
        )

    @api.model
    def _pf_plan_mo_without_materials(self, ctx):
        """La OF existe pero NO tiene insumos cargados (raíz ALMACÉN INSUMOS).

        El síntoma y la raíz viven en la ORDEN DE FABRICACIÓN: se abre para
        cargar/definir sus materiales. No confirma ni planifica nada.
        """
        return self._pf_plan(
            summary=_(
                'La Orden de Fabricación del pedido no tiene insumos cargados: '
                'sin materiales no se puede fabricar. Ábrela y carga sus '
                'insumos.'),
            steps=[
                _('Abre la Orden de Fabricación del pedido.'),
                _('Revisa su lista de materiales y sus componentes cargados.'),
                _('Completa los insumos y lanza la fabricación; recalcúlala '
                  'después.'),
            ],
            problem=self._pf_action(
                _('Ver la Orden de Fabricación'), 'navigate', 'mo'),
            solution=self._pf_action(
                _('Cargar los insumos de la OF'), 'navigate', 'mo'),
        )

    @api.model
    def _pf_plan_order_delivery_pending(self, ctx):
        """Pendiente por entrega: el producto está listo pero no se ha entregado.

        Síntoma y raíz viven en el MISMO albarán (``line_delivery``): la regla
        del mapa deja un solo botón (la solución) y desactiva "problema".
        """
        return self._pf_plan(
            summary=_(
                'El producto está listo pero todavía no se le ha entregado al '
                'cliente.'),
            steps=[
                _('Abre la entrega de este producto.'),
                _('Valídala cuando el cliente reciba la mercancía.'),
                _('Recalcula el diagnóstico para confirmar la entrega.'),
            ],
            problem=self._pf_action(
                _('Ir a la entrega de este producto'), 'navigate', 'line_delivery'),
            solution=self._pf_action(
                _('Ir a la entrega de este producto'), 'navigate', 'line_delivery'),
        )

    # ------------------------------------------------------------------
    # PLANES DEL MOTOR UNIFICADO DE FLUJO (casos nuevos d, e, f)
    # ------------------------------------------------------------------
    @api.model
    def _pf_plan_mo_stuck(self, ctx):
        """Caso d: la OF EXISTE pero está trabada/atrasada.

        El botón SOLO NAVEGA/abre la OF (guía, 1 clic): el diagnóstico es de
        solo lectura y NO ejecuta ``action_confirm`` ni planificación. La raíz
        (priorizar/desatascar la orden) la decide el jefe de taller en la OF.
        """
        return self._pf_plan(
            summary=_(
                'La Orden de Fabricación del pedido existe pero está trabada '
                '(esperando material o atrasada): ábrela y priorízala.'),
            steps=[
                _('Abre la Orden de Fabricación señalada.'),
                _('Revisa si espera material o si lleva más de 24h sin avanzar.'),
                _('Priorízala o completa su material desde la propia OF y '
                  'recalcula el diagnóstico.'),
            ],
            problem=self._pf_action(
                _('Ver la Orden de Fabricación'), 'navigate', 'mo'),
            solution=self._pf_action(
                _('Priorizar la Orden de Fabricación'), 'navigate', 'mo'),
        )

    @api.model
    def _pf_plan_contention_needs_supply(self, ctx):
        """Caso e: contención SIN entrada propia ni libre.

        Mantiene el 1er paso ``blocking`` (NUNCA toca la reserva ajena) y añade
        un 2º remedio de abastecimiento (comprar o fabricar) por la porción que
        al pedido no le queda cubierta.
        """
        return self._pf_plan(
            summary=_(
                'El stock existe pero lo retienen otros pedidos y este pedido '
                'no tiene entrada propia ni libre: primero resuelve el bloqueo '
                'ajeno; si de verdad no alcanza, compra o fabrica tu parte.'),
            steps=[
                _('Abre "Quién me bloquea" y resuelve la raíz de la entrega '
                  'que retiene el stock. No se le quita la reserva a nadie.'),
                _('Revisa si este pedido tiene una compra propia en camino.'),
                _('Si no alcanza, compra o fabrica SOLO lo que le falta a este '
                  'pedido y recalcula.'),
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Ver quién me bloquea'), 'navigate', 'blocking_reservations'),
            collect=self._pf_action(
                _('Recopilar entregas que lo reservan'), 'navigate',
                'delivery_orders'),
        )

    @api.model
    def _pf_plan_personalized_supply_stolen(self, ctx):
        """Caso f: compra propia recibida retenida por otro pedido del grupo.

        Se REPARTA solo la PORCIÓN propia de la OC compartida (nunca la OC
        completa ni la de otro pedido). Requiere permiso de jefe de taller.
        """
        return self._pf_plan(
            summary=_(
                'La compra propia de este pedido ya se recibió, pero otro '
                'pedido del grupo la tiene retenida. Reclama SOLO tu porción: '
                'la compra es compartida entre varios pedidos.'),
            steps=[
                _('Revisa la Orden de Compra compartida y la recepción.'),
                _('Pulsa "Reclamar mi parte": libera y re-reserva exactamente '
                  'la porción de este pedido, no la de los demás.'),
                _('Recalcula el diagnóstico para confirmar que tu parte quedó '
                  'reservada.'),
            ],
            problem=self._pf_action(
                _('Ver la compra compartida'), 'navigate', 'purchase_order'),
            solution=self._pf_action(
                _('Reclamar mi parte de la compra'), 'run_action',
                'claim_own_purchase'),
            collect=self._pf_action(
                _('Recopilar la porción por pedido'), 'navigate',
                'order_collect_tray'),
        )

    # ------------------------------------------------------------------
    # PLANES DE LOTE / TRAZABILIDAD (Bloque V)
    #
    # El negocio usa lotes para trazabilidad de productos personalizados: cada
    # lote es de un CLIENTE distinto y nunca se mezclan. El lote EXCLUSIVO del
    # pedido es ``<pedido>-L<linea>``. Todos los remedios reutilizan helpers
    # existentes y nunca asignan a un pedido el lote de otro cliente.
    # ------------------------------------------------------------------
    @api.model
    def _pf_plan_lot_missing(self, ctx):
        """Movimiento de salida de producto por lote sin trazabilidad.

        Microcopy por modo: sin pedido (``has_order`` falsy) el lote "del pedido"
        no existe; se habla de "un lote con existencia real" y de revisar la
        entrega o los movimientos afectados.

        P1 (D1): la entrega que reservó SIN lote y el nodo Inventario con la
        "Reserva colgada" son la MISMA falla (la raíz es la Entrega; el
        Inventario su consecuencia), así que el resumen y los pasos lo dicen
        explícitamente para que el operador no los trate como dos problemas.
        """
        has_order = bool((ctx or {}).get('has_order'))
        assign_step = (
            _('Asigna el lote del pedido (si es gestionado) o un lote con '
              'existencia; nunca un lote de otro cliente.')
            if has_order else
            _('Asigna un lote con existencia real; nunca un lote de otro '
              'cliente.'))
        validate_step = (
            _('Vuelve a validar la entrega.')
            if has_order else
            _('Revisa la entrega o los movimientos afectados.'))
        return self._pf_plan(
            summary=_(
                'Hay movimientos de salida de un producto por lote SIN lote '
                'asignado: sin lote no hay trazabilidad y la reserva queda '
                'COLGADA en el inventario. Es la MISMA falla vista en dos nodos: '
                'la raíz es la Entrega (reservó sin lote) y la consecuencia es '
                'el Inventario (reserva colgada).'),
            steps=[
                _('Revisa los movimientos señalados: no tienen lote.'),
                assign_step,
                _('El nodo Inventario con "Reserva colgada" es la CONSECUENCIA '
                  'de esta misma entrega sin lote: se resuelve al asignar el '
                  'lote correcto.'),
                validate_step,
            ],
            problem=self._pf_action(
                _('Ver existencias por lote'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Asignar el lote del pedido'), 'run_action', 'assign_lot'),
        )

    @api.model
    def _pf_plan_lot_orphan_reservation(self, ctx):
        """Quant con reservado sin movimiento que lo respalde."""
        has_order = bool((ctx or {}).get('has_order'))
        still_step = (
            _('Si la entrega sigue trabada, reasigna por lote con existencia.')
            if has_order else
            _('Si el problema sigue trabado, reasigna por lote con existencia.'))
        return self._pf_plan(
            summary=_(
                'Hay una reserva de lote inconsistente: un quant retiene '
                'cantidad sin un movimiento que la respalde. No falta '
                'mercancía; hay que reconciliar la reserva.'),
            steps=[
                _('Revisa las existencias: hay un lote con reservado sin '
                  'movimiento.'),
                _('Pulsa "Reconciliar la reserva de lote" para dejarla en el '
                  'reservado real. No se le quita a ningún pedido.'),
                still_step,
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Reconciliar la reserva de lote'), 'run_action',
                'reconcile_lot_reservation'),
        )

    @api.model
    def _pf_plan_lot_no_stock(self, ctx):
        """Lote reservado sin existencia interna (no reservable por lote)."""
        has_order = bool((ctx or {}).get('has_order'))
        replace_step = (
            _('Sustitúyelo por el lote exclusivo del pedido o por un lote '
              'con existencia real.')
            if has_order else
            _('Sustitúyelo por un lote que tenga existencia real.'))
        validate_step = (
            _('Vuelve a validar la entrega.')
            if has_order else
            _('Revisa la entrega o los movimientos afectados.'))
        return self._pf_plan(
            summary=_(
                'Un movimiento reserva un lote que NO tiene existencia en '
                'almacén: ese lote no se puede entregar. Sustitúyelo por uno '
                'con existencia (o por el lote exclusivo del pedido).'),
            steps=[
                _('Identifica el lote señalado: no tiene existencia interna.'),
                replace_step,
                validate_step,
            ],
            problem=self._pf_action(
                _('Ver existencias por lote'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Sustituir por el lote del pedido'), 'run_action',
                'replace_generic_lot'),
        )

    @api.model
    def _pf_plan_lot_generic(self, ctx):
        """Lote genérico/compartido en un producto que exige lote exclusivo."""
        has_order = bool((ctx or {}).get('has_order'))
        replace_step = (
            _('Sustitúyelos por el lote exclusivo del pedido; nunca se '
              'comparte un lote entre clientes.')
            if has_order else
            _('Sustitúyelos por un lote con existencia real; nunca se comparte '
              'un lote entre clientes.'))
        validate_step = (
            _('Vuelve a validar la entrega.')
            if has_order else
            _('Revisa la entrega o los movimientos afectados.'))
        return self._pf_plan(
            summary=_(
                'Un producto personalizado está usando un lote genérico: eso '
                'mezcla la trazabilidad entre clientes. Asígnale su lote '
                'exclusivo (el del pedido).'),
            steps=[
                _('Revisa los movimientos que usan el lote genérico.'),
                replace_step,
                validate_step,
            ],
            problem=self._pf_action(
                _('Ver movimientos con lote genérico'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Sustituir el lote genérico por el del pedido'), 'run_action',
                'replace_generic_lot'),
        )

    @api.model
    def _pf_plan_lot_mixed(self, ctx):
        """Varios lotes en un mismo movimiento o un lote entre clientes."""
        has_order = bool((ctx or {}).get('has_order'))
        summary = (
            _('Hay más de un lote en un mismo movimiento (o un lote usado '
              'por pedidos distintos): la trazabilidad quedó mezclada. '
              'Sepárala: una línea, un lote.')
            if has_order else
            _('Hay más de un lote en un mismo movimiento (o un lote usado '
              'en documentos distintos): la trazabilidad quedó mezclada. '
              'Sepárala: una línea, un lote.'))
        validate_step = (
            _('Vuelve a validar la entrega.')
            if has_order else
            _('Revisa la entrega o los movimientos afectados.'))
        return self._pf_plan(
            summary=summary,
            steps=[
                _('Revisa los movimientos con varios lotes o el lote '
                  'compartido entre clientes.'),
                _('Separa por lote: cada movimiento queda con un solo lote.'),
                validate_step,
            ],
            problem=self._pf_action(
                _('Ver lotes mezclados'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Separar los lotes mezclados'), 'run_action', 'separate_lots'),
        )

    @api.model
    def _pf_plan_lot_unassigned_finished(self, ctx):
        """MO terminada de producto por lote sin lote producido."""
        has_order = bool((ctx or {}).get('has_order'))
        repair_step = (
            _('Repara el lote del terminado (le asigna el lote exclusivo '
              'del pedido y re-reserva la entrega).')
            if has_order else
            _('Repara el lote del terminado (le asigna un lote con existencia '
              'real y re-reserva la entrega).'))
        return self._pf_plan(
            summary=_(
                'Hay órdenes de fabricación terminadas de un producto por '
                'lote que quedaron SIN lote: el stock terminado no tiene '
                'trazabilidad.'),
            steps=[
                _('Revisa las órdenes terminadas señaladas.'),
                repair_step,
                _('Verifica la trazabilidad del stock terminado.'),
            ],
            problem=self._pf_action(
                _('Ver órdenes de fabricación'), 'navigate', 'mo'),
            solution=self._pf_action(
                _('Reparar el lote del terminado'), 'run_action',
                'repair_finished_lot'),
        )

    # ------------------------------------------------------------------
    # PLAN DEL ALMACÉN DE INSUMOS
    #
    # El problema NO está en el terminado ni en la venta: es un COMPONENTE de la
    # lista de materiales que no puede cubrir la fabricación (está reservado de
    # más, sin existencia, apartado por otros pedidos o sin forma de reponer). El
    # síntoma se ve en las existencias y la corrección se decide en la BANDEJA de
    # insumos, donde el operador elige traslado, compra o ajuste.
    # ------------------------------------------------------------------
    @api.model
    def _pf_plan_supply_issue(self, ctx):
        """Problema de INSUMOS: el componente de la BOM no cubre la fabricación."""
        return self._pf_plan(
            summary=_(
                'Un insumo falta o está comprometido: revisa la existencia y '
                'elige cómo reponerlo.'),
            steps=[
                _('Abre las existencias del insumo para ver qué falta.'),
                _('Elige en la bandeja: traslado, compra o ajuste.'),
                _('Recalcula el diagnóstico para confirmar.'),
            ],
            problem=self._pf_action(
                _('Ver existencias por ubicación'), 'navigate', 'quants'),
            solution=self._pf_action(
                _('Solucionar los insumos'), 'navigate', 'supply_tray'),
        )

    # ------------------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------------------
    @api.model
    def _pf_plan_fallback(self):
        """Plan genérico para causas no reconocidas (nunca deja sin texto)."""
        return self._pf_plan(
            summary=_('Revisa el registro señalado.'),
            steps=[
                _('Abre el registro que señala el hallazgo.'),
                _('Corrige lo que corresponda y guarda.'),
                _('Vuelve y recalcula el diagnóstico para confirmar.'),
            ],
            problem=self._pf_action('', 'none', ''),
            solution=self._pf_action('', 'none', ''),
        )
