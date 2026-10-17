# -*- coding: utf-8 -*-
"""SELECTOR / Factory de estrategias del canvas de flujo (PrintFlow · Fase 5).

Servicio ``AbstractModel`` sin tabla que resuelve el CASO de flujo (``mode``) al
**NOMBRE** del modelo de la estrategia correspondiente y devuelve el recordset.
Es el **punto de extensión** del orquestador ``printflow.flow.canvas``: agregar
un caso nuevo (p. ej. POS) **NO** toca el orquestador; basta con mapear el
``mode`` aquí (o con un ``_inherit`` que fusione el mapa) y registrar la
estrategia.

Contrato::

    strategy = env['printflow.flow.registry']._pf_strategy_for('order')
    strategy = env['printflow.flow.registry']._pf_strategy_for('product')

Reglas de diseño (Fase 5 del refactor OOP,
``docs/plan_fases_orquestador_oop_v2.md`` y ``docs/diseno_orquestador_oop_v2.md``):

  * **Resuelve por NOMBRE** (``self.env[...]``): NO importa ni menciona las
    clases concretas de ``order``/``product``. Esto materializa la inversión de
    dependencias del orquestador.
  * ``_pf_registry()`` expone el mapa ``mode -> nombre de modelo`` para permitir
    la extensión **sin editar el orquestador**.
  * **HUECO RESERVADO**: ``'pos'`` queda documentado como reserva futura; **NO**
    se implementa ``printflow.flow.strategy.pos`` en esta fase.
  * ``mode`` por defecto sigue siendo ``'order'`` (paridad histórica: cualquier
    modo desconocido cae al caso pedido, igual que el ``else`` del orquestador
    original).
  * ``'auto'`` es **OPT-IN**: deduce el caso del host por *duck typing* y NUNCA
    cambia el default. Si no se usa, el comportamiento es idéntico al histórico.
"""

from odoo import api, models


class PrintflowFlowRegistry(models.AbstractModel):
    """Selector de estrategias del canvas: ``mode`` -> estrategia."""

    _name = 'printflow.flow.registry'
    _description = 'Selector de estrategias del canvas de flujo (PrintFlow)'

    # Modo de respaldo (paridad histórica: modo desconocido -> caso pedido).
    _PF_DEFAULT_MODE = 'order'

    # ══════════════════════════════════════════════════════════════════════
    # MAPA DE CASOS (punto de extensión)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_registry(self):
        """Mapa ``mode -> nombre de modelo`` de la estrategia del caso.

        Es el **punto de extensión** del orquestador: un caso nuevo (p. ej. POS)
        se agrega aquí (o vía ``_inherit`` que fusione el mapa) **sin tocar**
        ``printflow.flow.canvas``. Los nombres se resuelven en tiempo de
        ejecución con ``self.env[...]`` (sin import duro).
        """
        return {
            'order': 'printflow.flow.strategy.order',
            'product': 'printflow.flow.strategy.product',
            # ── HUECO RESERVADO (NO implementado) ──────────────────────────
            # POS queda como reserva futura NO agendada. Cuando exista la fuente
            # de datos del caso POS, agregar aquí:
            #   'pos': 'printflow.flow.strategy.pos',
            # y crear ``printflow_flow_strategy_pos.py`` con
            # ``_inherit = 'printflow.flow.strategy'``. El orquestador NO se
            # edita: ya resuelve por este mapa.
        }

    @api.model
    def _pf_supported_modes(self):
        """Modos SOPORTADOS por el registry (sin contar el valor ``'auto'``)."""
        return list(self._pf_registry())

    # ══════════════════════════════════════════════════════════════════════
    # RESOLUCIÓN DEL CASO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_strategy_for(self, mode, host=None):
        """Devuelve la ESTRATEGIA (recordset) del caso ``mode``.

        :param str mode: ``'order'`` (default histórico) o ``'product'``. El
            valor ``'auto'`` es opt-in y se resuelve con ``host``.
        :param host: host del caso; SOLO se usa cuando ``mode == 'auto'``.
        :return: recordset del modelo de la estrategia (nunca vacío).
        """
        resolved = self._pf_resolve_mode(mode, host)
        name = self._pf_registry().get(resolved)
        if not name:
            name = self._pf_registry()[self._PF_DEFAULT_MODE]
        return self.env[name]

    @api.model
    def _pf_resolve_mode(self, mode, host=None):
        """Normaliza el ``mode``: aplica ``'auto'`` (opt-in) y cae al default."""
        if mode == 'auto':
            return self._pf_detect_mode(host)
        return mode

    @api.model
    def _pf_detect_mode(self, host):
        """Deduce el caso del ``host`` por DUCK TYPING (opt-in de ``'auto'``).

        No se acopla a modelos concretos: un host con ``focus_line_id`` es un
        PEDIDO (con venta); un host con ``product_id`` es un PRODUCTO (sin
        venta). Ante la duda cae al caso por defecto (``'order'``).
        """
        if host is None:
            return self._PF_DEFAULT_MODE
        if getattr(host, 'focus_line_id', False):
            return 'order'
        if getattr(host, 'product_id', False):
            return 'product'
        return self._PF_DEFAULT_MODE
