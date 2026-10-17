# -*- coding: utf-8 -*-
"""Orquestador DELGADO del canvas de flujo (PrintFlow).

Servicio ``AbstractModel`` sin tabla que resuelve el CASO de flujo y delega el
armado del payload que consume el widget OWL ``printflow_order_timeline``. La
fábrica REAL vive en capas pequeñas y cohesivas (refactor OOP, Fases 1-5):

  * ``printflow.flow.registry``        -> resuelve ``mode`` -> estrategia.
  * ``printflow.flow.strategy.*``      -> traduce la fuente al contexto normalizado.
  * ``printflow.flow.payload.builder`` -> único bucle de armado (nodos/aristas).
  * ``printflow.flow.presentation``    -> presentación pura (geometría, tonos...).
  * ``printflow.flow.actions``         -> kit de acciones y shapes de fila.

Contrato::

    env['printflow.flow.canvas']._pf_build_payload(host, mode='order') -> dict

El ``host`` es el registro que expone por DUCK TYPING los atributos que el
orquestador necesita (``focus_line_id``, ``board_id``, ``focus_*``, ``_name``,
``id``, ``_pf_collect_subtree`` para el pedido; ``product_id``,
``_pf_product_canvas_ctx`` para el producto). Así el canvas NO depende de un
modelo concreto.

PARIDAD EXACTA (Fase 6 del refactor OOP): este servicio quedó REDUCIDO al
contrato (``_pf_build_payload``) más los wrappers que el wizard de niveles expone
y que los tests de diagnóstico invocan directamente (``_pf_node_summary``,
``_pf_node_status_label``, ``_pf_failure_slot``, ``_pf_key_by_slot``,
``_pf_node_actions``, ``_pf_anomaly_node_keys``, ``_pf_chain_summary``). Los
"gemelos"/delegadores muertos del pedido y del producto se RETIRARON porque ya
no tenían consumidores: viven, TAL CUAL, en la estrategia o en las capas puras.

Cualquier cambio de forma rompería ``test_diagnostic_timeline_payload``,
``test_flow_canvas_parity`` y el candado del producto
``test_product_flow_payload_parity``.
"""

from odoo import _, api, models

from odoo.addons.x_product_dimensional_pricing.models.printflow_order_health_engine import (  # noqa: E501
    PF_CHAIN_LABELS,
)


class PrintflowFlowCanvas(models.AbstractModel):
    """Orquestador delgado del canvas del flujo (pedido y producto)."""

    _name = 'printflow.flow.canvas'
    _description = 'Canvas de flujo compartido (PrintFlow)'

    # ══════════════════════════════════════════════════════════════════════
    # ENTRADA (CONTRATO DEL ORQUESTADOR)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_build_payload(self, host, mode='order'):
        """Payload del canvas del ``host`` según ``mode`` (ORQUESTADOR delgado).

        No tiene reglas ni armado: (a) resuelve la ESTRATEGIA del caso por el
        selector ``printflow.flow.registry`` (sin conocer casos concretos),
        (b) le pide el contexto de flujo normalizado y (c) delega el armado en el
        Builder único ``printflow.flow.payload.builder``.

        :param host: registro que expone los atributos del canvas por duck
            typing (wizard de pedido o ``printflow.product.flow``).
        :param str mode: ``'order'`` (paridad exacta, por defecto) o
            ``'product'``. ``'auto'`` es opt-in y lo resuelve el registry a
            partir del host, sin cambiar el default.
        """
        registry = self.env['printflow.flow.registry']
        strategy = registry._pf_strategy_for(mode, host)
        context = strategy._pf_flow_context(host)
        return self.env[
            'printflow.flow.payload.builder']._pf_build(context, strategy)

    # ══════════════════════════════════════════════════════════════════════
    # WRAPPERS QUE EL WIZARD DE NIVELES EXPONE
    #
    # Firmas históricas conservadas: los tests de diagnóstico invocan estos
    # métodos privados a través de los wrappers del wizard
    # (``printflow_order_diagnostic_levels.py``), que delegan AQUÍ.
    # ══════════════════════════════════════════════════════════════════════
    def _pf_node_actions(self, host, node_key, owner, node_role, node_status,
                         is_root=False, context_failure=None, anomaly=False,
                         pending=0):
        """Delegador: acciones del popover del pedido (estrategia del pedido).

        Conserva la FIRMA histórica; el vocabulario vive ahora en
        ``printflow.flow.strategy.order`` (Fase 4 del refactor OOP).
        """
        return self.env['printflow.flow.strategy.order']._pf_node_actions(
            host, node_key, owner, node_role, node_status, is_root,
            context_failure=context_failure, anomaly=anomaly, pending=pending)

    @api.model
    def _pf_key_by_slot(self, axis):
        """Delegador: hito PRINCIPAL del eje por slot (estrategia/interfaz)."""
        return self.env['printflow.flow.strategy']._pf_key_by_slot(axis)

    @api.model
    def _pf_failure_slot(self, failure):
        """Delegador: slot de canvas de una falla (presentación pura)."""
        return self.env[
            'printflow.flow.presentation']._pf_failure_slot(failure)

    @api.model
    def _pf_node_status_label(self, key, status):
        """Delegador: etiqueta de estado del HITO (presentación pura)."""
        return self.env[
            'printflow.flow.presentation']._pf_node_status_label(key, status)

    @api.model
    def _pf_node_summary(self, owner_failure, issues):
        """Resumen CORTO del problema que se pinta en la tarjeta del nodo."""
        if owner_failure is None:
            return '', 0
        return owner_failure.summary or '', max(0, (issues or 0) - 1)

    @api.model
    def _pf_anomaly_node_keys(self, host, line):
        """Delegador: hitos que detectan reservas colgadas (estrategia pedido)."""
        return self.env[
            'printflow.flow.strategy.order']._pf_anomaly_node_keys(host, line)

    @api.model
    def _pf_chain_summary(self, failures):
        """Resume la cadena raíz -> consecuencias en orden de ``rank``."""
        chain = failures.filtered(
            lambda f: f.pf_chain_role in ('root', 'consequence'))
        ordered = sorted(chain, key=lambda f: (f.pf_chain_rank or 0, f.id))
        seen = set()
        parts = []
        for failure in ordered:
            if failure.node in seen:
                continue
            seen.add(failure.node)
            label = PF_CHAIN_LABELS.get(failure.node, failure.node or '')
            suffix = (_('origen') if failure.pf_chain_role == 'root'
                      else _('consecuencia'))
            parts.append('%s (%s)' % (label, suffix))
        return ' → '.join(parts)
