# -*- coding: utf-8 -*-
"""Motor UNIFICADO de causa-raíz por flujo (PrintFlow).

``AbstractModel`` PURO: **no consulta la base de datos**. Recibe un contexto
plano con los números y banderas YA resueltos por quien sí puede leer BD (el
Wizard de Diagnóstico de PEDIDO y el ESCÁNER de PRODUCTO) y devuelve el veredicto
de UN producto/componente:

  * semáforos por nodo (venta / inventario / compras / fabricación / entrega),
  * severidad y fallas (reutilizando el motor de salud, única fuente de verdad),
  * ``root_cause_node`` (nodo de quiebre),
  * ``cause`` normalizada del playbook,
  * ``remedy_key`` estructural.

Es la ÚNICA fuente del árbol de causa-raíz por flujo: pedido y escáner lo
consumen para no divergir. NO reimplementa reglas: delega en
``printflow.order.health.engine`` (``_pf_product_stock``, ``_pf_product_supply``,
``_pf_product_production``, ``_pf_product_severity``, ``_pf_product_failures``) y
solo agrega la decisión de causa/remedio a partir de banderas planas.

Principio anti-cascada: NADA aquí dispara consultas. La lectura de BD (BoM,
quants, MOs, POs) vive en el wizard/escáner bajo demanda. Por eso este motor se
puede testear con dicts y llamar desde un ``compute`` sin N+1.
"""

from odoo import api, models

# Mapa remedio físico -> causa normalizada: FUENTE ÚNICA en el motor de salud.
# La capa ``diagnostic/`` depende de ``models/`` (nunca al revés).
from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import PF_PHYSICAL_REMEDY_TO_CAUSE

# Mismo umbral que el motor de salud y el tablero.
_EPS = 1e-6


class PrintflowProductFlowDiagnostic(models.AbstractModel):
    """Motor unificado de causa-raíz por flujo (PrintFlow)."""

    _name = 'printflow.product.flow.diagnostic'
    _description = 'Motor unificado de causa-raíz por flujo (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # CONTRATO CENTRAL
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_flow_verdict(self, ctx):
        """Veredicto de UN producto/componente a partir de un contexto plano.

        ``ctx`` (dict) admite las claves que ya construye el diagnóstico de
        pedido/escáner. Las más relevantes:

          * ``sale_status``         estado de venta de la línea ('ok'/'pending'/
            'error'/'na').
          * ``is_finished``         True para el producto terminado.
          * ``deficit_qty``         falta física (obliga a comprar/fabricar).
          * ``contention_qty``      cantidad retenida por OTROS pedidos.
          * ``in_over_reserved``    libre AGREGADO negativo (sobrepedido real).
          * ``purchase_ok``         el producto es comprable.
          * ``incoming_qty``        unidades en camino (compras del pedido).
          * ``pending_product_ids`` set de ids con compra pendiente.
          * ``order_health_supply`` semáforo de abastecimiento del pedido.
          * ``active_mos`` / ``done_mos`` listas planas de MO (no recordset).
          * ``has_draft_mo``        hay una MO en BORRADOR (OF sin lanzar).
          * ``in_production_stage`` el pedido está en taller (gatea ``to_launch``).
          * ``is_manufacturable``   BoM o ruta de fabricación.
          * ``design_pending``      arte pendiente.
          * ``production_alert``    alerta de producción del tablero.
          * ``in_delivery_stage``   el pedido está en etapa de entrega.
          * ``is_stock_covered``    el terminado ya tiene existencia suficiente.
          * ``is_late_material``    material retrasado +24h.
          * ``delivery_status``     'ok'/'pending'/'partial'/'na'.
          * ``reservation_anomaly`` reserva colgada (quant libre < 0 compensado).
          * ``unconfirmed``         pedido no confirmado -> nodos en 'na'.
          * ``physical_remedy``     clave del remedio físico ya resuelta por el
            llamador (``_pf_physical_remedy_key``); alimenta la causa de déficit.
          * ``mo_stuck``            hay MO activa trabada/atrasada (caso d). Es
            un flag OPCIONAL: lo define el llamador. Su default es ``False``,
            para no fabricar la causa ``mo_stuck`` cuando nadie lo ha resuelto.

        :return: dict con ``sale_status``, ``stock_status``, ``purchase_status``,
            ``production_status``, ``delivery_status``, ``severity``,
            ``failures``, ``root_cause_node``, ``cause`` y ``remedy_key``.
        :rtype: dict
        """
        ctx = dict(ctx or {})
        engine = self.env['printflow.order.health.engine']

        is_finished = ctx.get('is_finished', True)
        sale = ctx.get('sale_status') or ('ok' if is_finished else 'na')
        delivery = ctx.get('delivery_status') or 'na'
        deficit = ctx.get('deficit_qty') or 0.0
        contention = ctx.get('contention_qty') or 0.0
        # Paridad con el wizard: una bandera ausente (None) NO cambia nada; solo
        # el ``False`` explícito activa el "no gestiona inventario".
        is_stock_tracked = ctx.get('is_stock_tracked')

        stock = engine._pf_product_stock({
            'deficit_qty': deficit,
            'contention_qty': contention,
            'in_over_reserved': bool(ctx.get('in_over_reserved')),
            'is_stock_tracked': is_stock_tracked,
        })
        purchase = engine._pf_product_supply({
            'purchase_ok': ctx.get('purchase_ok'),
            'incoming_qty': ctx.get('incoming_qty') or 0.0,
            'deficit_qty': deficit,
            'pending_product_ids': ctx.get('pending_product_ids') or set(),
            'order_health_supply': ctx.get('order_health_supply'),
            'product_id': ctx.get('product_id'),
            'is_stock_tracked': is_stock_tracked,
        })
        production = engine._pf_product_production(
            self._pf_production_input(ctx))
        if ctx.get('unconfirmed'):
            stock = 'na'
            purchase = 'na'
            production = 'na'

        reservation_anomaly = bool(ctx.get('reservation_anomaly'))
        severity = engine._pf_product_severity({
            'sale_status': sale,
            'stock_status': stock,
            'purchase_status': purchase,
            'production_status': production,
            'delivery_status': delivery,
            'reservation_anomaly': reservation_anomaly,
        })
        failures = engine._pf_product_failures({
            'sale_status': sale,
            'stock_status': stock,
            'purchase_status': purchase,
            'production_status': production,
            'delivery_status': delivery,
            'delivery_delivered': ctx.get('delivery_delivered'),
            'delivery_required': ctx.get('delivery_required'),
            'deficit_qty': deficit,
            'contention_qty': contention,
            'reservation_anomaly': reservation_anomaly,
            'physical_remedy': ctx.get('physical_remedy'),
            # Arte pendiente: señal ADICIONAL del nodo Fabricación (misma regla
            # que el wizard). No reemplaza el estado de la OF.
            'design_pending': ctx.get('design_pending'),
        })
        statuses = {
            'sale_status': sale,
            'stock_status': stock,
            'purchase_status': purchase,
            'production_status': production,
            'delivery_status': delivery,
        }
        root = self._pf_root_cause_node(statuses, deficit, is_stock_tracked)
        cause = self._pf_primary_cause(ctx, statuses, failures)
        remedy = self._pf_primary_remedy_key(ctx, statuses, cause)
        return dict(
            statuses,
            severity=severity,
            failures=failures,
            root_cause_node=root,
            cause=cause,
            remedy_key=remedy,
        )

    # ══════════════════════════════════════════════════════════════════════
    # NODO DE QUIEBRE Y CAUSA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_production_input(self, ctx):
        """Arma la entrada de ``_pf_product_production`` preservando el fallback.

        Solo incluye ``is_manufacturable`` cuando el llamador lo resolvió: así,
        si falta, el motor cae a su comportamiento histórico y la paridad se
        mantiene. Reenvía ``has_draft_mo`` e ``in_production_stage``: si el
        llamador no los trae quedan en ``None`` y la rama ``to_launch`` es inerte
        (el escáner, que no lee MOs, mantiene la paridad).
        """
        data = {
            'active_mos': ctx.get('active_mos') or [],
            'done_mos': ctx.get('done_mos') or [],
            'has_draft_mo': ctx.get('has_draft_mo'),
            'mo_without_materials': ctx.get('mo_without_materials'),
            'in_production_stage': ctx.get('in_production_stage'),
            'procurement_type': ctx.get('procurement_type'),
            'design_pending': ctx.get('design_pending'),
            'production_alert': ctx.get('production_alert'),
            'in_delivery_stage': ctx.get('in_delivery_stage'),
            'is_stock_covered': ctx.get('is_stock_covered'),
            'is_late_material': ctx.get('is_late_material'),
        }
        if 'is_manufacturable' in ctx:
            data['is_manufacturable'] = ctx.get('is_manufacturable')
        return data

    @api.model
    def _pf_root_cause_node(self, statuses, deficit_qty=0.0,
                            is_stock_tracked=True):
        """Nodo de quiebre por PRECEDENCIA (delega en el motor de salud).

        La implementación canónica vive en
        ``printflow.order.health.engine._pf_root_cause_node`` (fabricación
        trabada, incluida la OF sin lanzar, gana sobre el déficit de stock). Se
        conserva este método como fachada del motor de flujo para no duplicar la
        regla. ``is_stock_tracked=False`` salta los pasos de stock/compra.
        """
        return self.env[
            'printflow.order.health.engine'
        ]._pf_root_cause_node(statuses, deficit_qty, is_stock_tracked)

    @api.model
    def _pf_primary_cause(self, ctx, statuses, failures=None):
        """Causa normalizada (``pf_cause``) del veredicto.

        Usa la falla más grave del nodo de quiebre para conservar los textos y
        causas del motor; agrega las causas nuevas ``mo_stuck`` (OF trabada) y
        ``contention_needs_supply`` (contención sin entrada propia ni libre).
        """
        statuses = statuses or {}
        production = statuses.get('production_status')
        # La OF sin insumos es su propia causa (raíz en el ALMACÉN INSUMOS).
        if production == 'no_supply':
            return 'mo_without_materials'
        # Caso d: OF existe pero trabada/atrasada/sin lanzar -> priorizar, no
        # crear. El flag lo define el llamador; sin él NO se fabrica ``mo_stuck``.
        if (production in ('material', 'late', 'to_launch')
                and ctx.get('mo_stuck', False)):
            return 'mo_stuck'
        root = self._pf_root_cause_node(
            statuses, ctx.get('deficit_qty') or 0.0,
            ctx.get('is_stock_tracked'))
        if not root:
            return False
        # Caso c: fabricable SIN OF en etapa de entrega -> hay que CREAR la OF.
        if root == 'production' and production == 'no_mo':
            return 'manufacture'
        # Un déficit FÍSICO se clasifica por su remedio físico (§4.2) aunque el
        # nodo de quiebre por precedencia sea 'purchase' (producto comprable con
        # compra faltante): el remedio estructural manda, y así el escáner y el
        # pedido cuentan la misma causa que la fila de stock.
        if (statuses.get('stock_status') == 'deficit'
                and ctx.get('physical_remedy')):
            return PF_PHYSICAL_REMEDY_TO_CAUSE.get(
                ctx.get('physical_remedy'), 'order_shortfall')
        for failure in failures or []:
            if failure.get('node') == root:
                return failure.get('pf_cause')
        # Sin falla materializada: se deriva de la causa física ya resuelta.
        if root == 'stock' and statuses.get('stock_status') == 'deficit':
            remedy = ctx.get('physical_remedy')
            return PF_PHYSICAL_REMEDY_TO_CAUSE.get(remedy, 'order_shortfall')
        return False

    @api.model
    def _pf_primary_remedy_key(self, ctx, statuses, cause):
        """Clave de remedio estructural del veredicto (o ``False``).

        Reutiliza el vocabulario de ``printflow.stock.remedy``. Es puro: recibe
        la causa física ya resuelta en ``ctx['physical_remedy']``.
        """
        statuses = statuses or {}
        if cause == 'data_anomaly':
            return 'fix_over_reservation'
        if cause == 'free_exhausted':
            return 'blocking'
        if cause == 'mo_stuck':
            return 'prioritize_mo'
        if cause == 'mo_without_materials':
            return 'load_mo_materials'
        if cause in ('manufacture', 'manufacture_components', 'buy_product',
                     'no_bom', 'adjust_inventory'):
            return ctx.get('physical_remedy') or cause
        if cause == 'personalized_supply_stolen':
            return 'claim_own_purchase'
        if statuses.get('stock_status') == 'deficit':
            return ctx.get('physical_remedy') or False
        return False
