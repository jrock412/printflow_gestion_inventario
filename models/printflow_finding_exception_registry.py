# -*- coding: utf-8 -*-
"""Registry de hallazgos FORMALES autorizables (PrintFlow · GI).

Servicio ``AbstractModel`` sin tabla que declara la **lista blanca** de hallazgos
que admiten autorizarse como excepción formal, y —para cada uno— sobre qué
modelo destino vive y en qué lista del ``lot_info`` del motor se resta.

Es el PUNTO DE EXTENSIÓN: agregar un formalismo nuevo = UNA fila en
``_pf_registry`` (y, si aplica, su resta automática en el adaptador
``printflow.finding.exception.filter``). NO se toca la bandeja ni los wizards.

Queda EXCLUIDO de autorización (no es formalismo, hay inconsistencia real de
datos): ``lot_orphan_reservation`` (reserva huérfana) y las reservas/quant
negativos. Esos SÍ exigen remedio real; el botón de autorización no los cubre.

Contrato::

    supported = env['printflow.finding.exception.registry']._pf_supported()
    shape = env['printflow.finding.exception.registry']._pf_shape('lot_missing')
"""

from odoo import _, api, models


class PrintflowFindingExceptionRegistry(models.AbstractModel):
    """Registry: ``finding_code -> {target_model, label, list_key, kind, state}``."""

    _name = 'printflow.finding.exception.registry'
    _description = 'Registry de hallazgos autorizables (PrintFlow)'

    @api.model
    def _pf_registry(self):
        """Mapa de hallazgos autorizables (punto de extensión).

        Claves por hallazgo:

        * ``target_model``: modelo del registro afectado (el ``res_model``).
        * ``label``: etiqueta legible del hallazgo.
        * ``list_key``: clave del ``lot_info`` del motor que el adaptador RESTA.
        * ``kind``: clasificación de la fila de la bandeja de lote (si aplica).
        * ``state``: estado de lote del motor asociado (si aplica).

        El valor de ``label`` se evalúa con ``_()`` en cada llamada (traducible).
        """
        return {
            'lot_unassigned_finished': {
                'target_model': 'mrp.production',
                'label': _('MO terminada sin lote'),
                'list_key': 'unassigned_mo_ids',
                'kind': 'unassigned_mo',
                'state': 'lot_unassigned_finished',
            },
            'lot_missing': {
                'target_model': 'stock.move',
                'label': _('Movimiento de salida sin lote'),
                'list_key': 'missing_move_ids',
                'kind': 'missing_move',
                'state': 'lot_missing',
            },
            'lot_no_stock': {
                'target_model': 'stock.lot',
                'label': _('Lote reservado sin existencia interna'),
                'list_key': 'no_stock_lot_ids',
                'kind': 'no_stock_lot',
                'state': 'lot_no_stock',
            },
            'lot_generic': {
                'target_model': 'stock.lot',
                'label': _('Lote genérico en producto gestionado'),
                'list_key': 'generic_lot_ids',
                'kind': 'generic_lot',
                'state': 'lot_generic',
            },
            'lot_mixed': {
                'target_model': 'stock.lot',
                'label': _('Lote compartido entre pedidos'),
                'list_key': 'mixed_lots',
                'kind': 'mixed_lot',
                'state': 'lot_mixed',
            },
        }

    @api.model
    def _pf_supported(self):
        """Códigos de hallazgo SOPORTADOS por el registry."""
        return list(self._pf_registry())

    @api.model
    def _pf_shape(self, code):
        """Dict de forma de un código (o ``None`` si no es autorizable)."""
        return self._pf_registry().get(code or '')

    @api.model
    def _pf_is_supported(self, code):
        """¿El código admite autorización?"""
        return bool(code) and code in self._pf_registry()

    @api.model
    def _pf_label(self, code):
        """Etiqueta legible del hallazgo (o el propio código si es desconocido)."""
        shape = self._pf_shape(code)
        return shape['label'] if shape else (code or '')

    @api.model
    def _pf_target_model(self, code):
        """Modelo destino del hallazgo (o ``''`` si es desconocido)."""
        shape = self._pf_shape(code)
        return shape['target_model'] if shape else ''

    @api.model
    def _pf_code_for_kind(self, kind):
        """``finding_code`` cuyo ``kind`` de bandeja coincide (o ``''``).

        Inversa inversa usada por la bandeja de lote para mapear una fila a su
        hallazgo formal sin ``if tipo == ...`` dispersos.
        """
        for code, shape in self._pf_registry().items():
            if shape.get('kind') == kind:
                return code
        return ''

    @api.model
    def _pf_codes_for_list_key(self, list_key):
        """Códigos que restan de una MISMA clave del ``lot_info``."""
        return [
            code for code, shape in self._pf_registry().items()
            if shape.get('list_key') == list_key
        ]
