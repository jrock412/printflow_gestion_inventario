# -*- coding: utf-8 -*-
"""Registry / Factory de fallas guiadas del diagrama (PrintFlow · Fase 1).

Servicio ``AbstractModel`` sin tabla que resuelve el CÓDIGO de una falla
(``pf_cause`` del vocabulario existente) al **NOMBRE del modelo** de la falla
correspondiente y devuelve el recordset. Es el **punto de extensión** del
patrón: agregar una falla nueva (p. ej. lote genérico, insumos) **NO** toca la
bandeja ni el diagrama; basta con mapear el código aquí (o con un ``_inherit``
que fusione el mapa) y crear el modelo.

Espejo del patrón ya usado en ``printflow.flow.registry`` (estrategias del
canvas): resuelve por NOMBRE con ``self.env[...]``, sin importar las clases
concretas, y ``_pf_failure_for`` **NUNCA** devuelve vacío: ante un código
desconocido cae a la falla GENÉRICA ``printflow.flow.failure.generic``.

Contrato::

    failure = env['printflow.flow.failure.registry']._pf_failure_for(code)
    codes = env['printflow.flow.failure.registry']._pf_supported()
"""

from odoo import api, models

# Clave del parámetro que FUERZA la superficie guiada (cero hardcodeo). Por
# defecto está apagado: el diagrama usa la bandeja guiada para la falla huérfana
# cuando la fila trae el producto explícito (ver ``printflow.product.flow``);
# este parámetro permite forzarla también en llamadas sin ese contexto.
PARAM_GUIDED_TRAY = 'x_product_dimensional_pricing.pf_failure_guided_tray'


class PrintflowFlowFailureRegistry(models.AbstractModel):
    """Selector de fallas guiadas: ``código -> falla``."""

    _name = 'printflow.flow.failure.registry'
    _description = 'Registry de fallas guiadas (PrintFlow)'

    # Fallback: código desconocido -> falla genérica (mínima).
    _PF_FALLBACK_CODE = 'generic'
    _PF_FALLBACK_MODEL = 'printflow.flow.failure.generic'

    # ══════════════════════════════════════════════════════════════════════
    # MAPA DE FALLAS (punto de extensión)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_registry(self):
        """Mapa ``código de falla -> nombre de modelo`` (punto de extensión).

        Los códigos reutilizan el VOCABULARIO EXISTENTE del motor (los mismos
        ``pf_cause`` de lote/insumos): NO se crean estados nuevos. El valor se
        resuelve en tiempo de ejecución con ``self.env[...]`` (sin import duro),
        de modo que una falla nueva se agrega aquí sin editar la bandeja.
        """
        return {
            'lot_orphan_reservation': 'printflow.flow.failure.lot.orphan',
            # Reserva colgada REAL (reserva > físico). Su "Solucionar" abre la
            # bandeja guiada con una fila por quant y la acción de saneo.
            'data_anomaly': 'printflow.flow.failure.over.reservation',
            # Lote asignado en una ``stock.move.line`` activa SIN stock del lote
            # (``no_stock_lot_ids``). Abre la bandeja guiada con UNA fila por lote
            # y el saneo ``reassign`` (re-asigna la reserva por lote). Es un caso
            # PRIMO de la reserva colgada pero distinto (ver D1 del plan).
            'lot_no_stock': 'printflow.flow.failure.lot.no.stock',
        }

    @api.model
    def _pf_supported(self):
        """Códigos de falla SOPORTADOS por el registry (sin el fallback)."""
        return list(self._pf_registry())

    # ══════════════════════════════════════════════════════════════════════
    # RESOLUCIÓN DE LA FALLA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_failure_for(self, code):
        """Devuelve la FALLA (recordset) del código indicado. Nunca vacío.

        Si el código no está mapeado (o llega vacío), cae a la falla GENÉRICA
        ``printflow.flow.failure.generic``: la bandeja siempre tiene algo que
        mostrar y nunca revienta por un código inesperado.
        """
        name = self._pf_registry().get(code or '') or self._PF_FALLBACK_MODEL
        return self.env[name]

    @api.model
    def _pf_guided_tray_forced(self):
        """¿La configuración FUERZA la superficie guiada? (default: no)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_GUIDED_TRAY, '0')
        return str(raw).lower() in ('1', 'true', 'yes', 't')
