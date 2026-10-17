# -*- coding: utf-8 -*-
"""LÍNEA de DESTINO de la asignación EN BLOQUE de lote (PrintFlow).

``TransientModel`` que representa UN destino de la acción en bloque
(``printflow.flow.lot.assign.bulk``): una entrega SIN lote (``missing_move`` /
``pending_order``) a la que el operador quiere asignar el lote elegido.

Por qué existe
--------------
A diferencia del selector POR DOCUMENTO (``printflow.flow.lot.picker``), la
acción en bloque resuelve N documentos con UN motivo. Se necesita una fila por
destino que guarde el SNAPSHOT de la selección (tipo, modelo/id, movimiento,
demanda, ubicación, fecha) y el RESULTADO por destino (asignado / parcial /
omitido / error), para poder reportar cuántas quedaron cubiertas y cuántas no
(CA-3, CA-7, CA-9).

Esta línea es SOLO un snapshot de LECTURA: NO escribe en ``stock.*``. La ÚNICA
escritura del bloque es la reasignación NATIVA que dispara el contenedor por el
orquestador ``printflow.product.flow._pf_assign_lot_to_document``.
"""

from odoo import fields, models


class PrintflowFlowLotAssignBulkLine(models.TransientModel):
    """Un destino de la asignación en bloque (snapshot + resultado)."""

    _name = 'printflow.flow.lot.assign.bulk.line'
    _description = 'Destino de asignación de lote en bloque (PrintFlow)'
    _order = 'seq asc, id asc'

    bulk_id = fields.Many2one(
        'printflow.flow.lot.assign.bulk', string='Asignación en bloque',
        required=True, ondelete='cascade', index=True,
        help='Contenedor al que pertenece este destino.')
    seq = fields.Integer(
        string='Orden',
        help='Orden determinista de procesamiento (FIFO por fecha prevista): '
             'define el reparto reproducible cuando el lote es escaso.')
    kind = fields.Char(
        string='Tipo de ítem',
        help='Tipo de ítem de la fila original (lista blanca del orquestador).')
    res_model = fields.Char(string='Modelo')
    res_id = fields.Integer(string='Id del registro')
    move_id = fields.Many2one(
        'stock.move', string='Movimiento', readonly=True,
        help='``stock.move`` que respalda la entrega (se usa para reasignar).')
    label = fields.Char(
        string='Destino', readonly=True,
        help='Etiqueta legible del destino (albarán/entrega).')
    demand_qty = fields.Float(
        string='Demanda', digits='Product Unit of Measure',
        help='Cantidad que pide el destino (suma para la demanda total).')
    location_id = fields.Many2one(
        'stock.location', string='Ubicación', readonly=True,
        help='Ubicación efectiva del destino (para juzgar la disponibilidad).')
    scheduled_date = fields.Datetime(
        string='Fecha prevista', readonly=True,
        help='Fecha prevista del destino (criterio FIFO).')
    assignable = fields.Boolean(
        string='Asignable', readonly=True,
        help='Verdadero si el destino admite la asignación en bloque (entrega '
             'sin lote que resuelve a un movimiento). Los no asignables se '
             'OMITEN y se reportan.')
    result = fields.Selection(
        selection=[
            ('pending', 'Pendiente'),
            ('assigned', 'Asignado'),
            ('partial', 'Parcial'),
            ('skipped', 'Omitido'),
            ('error', 'Con error'),
        ],
        string='Resultado', default='pending',
        help='Resultado de la asignación para ESTE destino.')
    result_note = fields.Char(
        string='Nota del resultado', readonly=True,
        help='Detalle del resultado (motivo de la omisión o del error).')
