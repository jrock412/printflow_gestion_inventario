# -*- coding: utf-8 -*-
"""LÍNEA del DETALLE del resultado de la asignación EN BLOQUE de lote (PrintFlow).

``TransientModel`` que representa UN destino del resultado de la acción en bloque
(``printflow.flow.lot.assign.bulk``): una entrega de la selección con su
resultado (asignado / parcial / omitido / con error) y su ``result_note``
COMPLETO.

Por qué existe (H-029)
----------------------
El motivo del fallo por destino SÍ se calculaba y SÍ se guardaba
(``printflow.flow.lot.assign.bulk.line.result_note``), pero NO se mostraba: la
acción terminaba en una notificación emergente que se trunca y desaparece. Con
26+ motivos el operador no los puede leer. Esta línea materializa ese detalle en
una ventana desplazable y persistente, UNA fila por destino.

Es SOLO LECTURA (snapshot del resultado por destino): NO escribe ``stock.*``. La
puebla ``printflow.flow.lot.assign.bulk.result._pf_build_from_bulk`` copiando los
destinos del contenedor, sin recalcular nada.
"""

from odoo import fields, models

# Mismos 5 códigos de resultado que ``printflow.flow.lot.assign.bulk.line``: el
# detalle es un ESPEJO del estado real del destino (cero traducción de códigos).
RESULT_SELECTION = [
    ('pending', 'Pendiente'),
    ('assigned', 'Asignado'),
    ('partial', 'Parcial'),
    ('skipped', 'Omitido'),
    ('error', 'Con error'),
]


class PrintflowFlowLotAssignBulkResultLine(models.TransientModel):
    """Una fila del detalle: un destino con su resultado y su motivo."""

    _name = 'printflow.flow.lot.assign.bulk.result.line'
    _description = 'Línea del detalle de la asignación de lote en bloque (PrintFlow)'
    _order = 'seq asc, id asc'

    result_id = fields.Many2one(
        'printflow.flow.lot.assign.bulk.result',
        string='Detalle de la asignación',
        required=True, ondelete='cascade', index=True,
        help='Cabecera del detalle a la que pertenece esta fila.')
    seq = fields.Integer(
        string='Orden', readonly=True,
        help='Orden determinista del destino (el mismo con que se procesó).')
    label = fields.Char(
        string='Entrega', readonly=True,
        help='Etiqueta legible del destino (albarán/entrega).')
    kind = fields.Char(
        string='Tipo', readonly=True,
        help='Tipo de ítem del destino (lista blanca del orquestador).')
    demand_qty = fields.Float(
        string='Demanda', digits='Product Unit of Measure', readonly=True,
        help='Cantidad que pedía el destino.')
    result = fields.Selection(
        selection=RESULT_SELECTION,
        string='Resultado', readonly=True,
        help='Resultado de la asignación para ESTE destino.')
    result_note = fields.Char(
        string='Motivo', readonly=True,
        help='Motivo COMPLETO del resultado (por qué se omitió o falló).')
