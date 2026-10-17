# -*- coding: utf-8 -*-
"""Detalle del resultado de la asignación EN BLOQUE de lote (PrintFlow).

Ventana de SOLO LECTURA que se encadena al cierre de la acción en bloque
(``printflow.flow.lot.assign.bulk.action_assign_lot_bulk``): en lugar de dejar
los motivos por destino dentro de una notificación que se trunca y desaparece,
los materializa en una fila por destino con su ``result`` y su ``result_note``.

Por qué existe (H-029)
----------------------
El operador corría la asignación en bloque, veía "1 asignada · 26 con error" y
NO tenía forma de saber POR QUÉ falló cada entrega. El modelo de línea del
contenedor YA guardaba el motivo (``result_note``); solo faltaba PINTARLO. Este
detalle lo hace: persistente, desplazable y con una fila por destino (incluidas
las OMITIDAS y las que no eran asignables).

Patrón portado (cero reinvención)
---------------------------------
Se porta el patrón EXISTENTE del motor ``x_product_dimensional_pricing``
(``printflow.delivery.bulk.result`` + su línea): cabecera con ``line_ids`` y
conteos computados. El motor del "validar entregas en lote" NO se toca.

Código sí, datos no
-------------------
Este modelo NO escribe: solo LEE los destinos del contenedor
(``bulk.line_ids``) para armar un snapshot. La ÚNICA escritura del bloque sigue
siendo la reasignación NATIVA por documento.
"""

from odoo import api, fields, models


class PrintflowFlowLotAssignBulkResult(models.TransientModel):
    """Cabecera del detalle del resultado de la asignación en bloque."""

    _name = 'printflow.flow.lot.assign.bulk.result'
    _description = 'Resultado de la asignación de lote en bloque (PrintFlow)'

    bulk_id = fields.Many2one(
        'printflow.flow.lot.assign.bulk', string='Asignación en bloque',
        readonly=True, ondelete='cascade',
        help='Contenedor del que sale este detalle (trazabilidad).')
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True,
        ondelete='cascade',
        help='Producto de la selección asignada en bloque.')
    source_label = fields.Char(
        string='Origen', readonly=True,
        help='Etiqueta legible de la selección de origen (trazabilidad).')
    line_ids = fields.One2many(
        'printflow.flow.lot.assign.bulk.result.line', 'result_id',
        string='Detalle por entrega',
        help='Una fila por destino de la asignación, con su resultado y su '
             'motivo completo.')
    assigned_count = fields.Integer(
        string='Asignadas', compute='_compute_counts',
        help='Destinos que quedaron con el lote completo.')
    partial_count = fields.Integer(
        string='Parciales', compute='_compute_counts',
        help='Destinos que solo reservaron lo disponible.')
    omitted_count = fields.Integer(
        string='Omitidas', compute='_compute_counts',
        help='Destinos que se omitieron (tipo no asignable, sin movimiento o '
             'duplicado).')
    error_count = fields.Integer(
        string='Con error', compute='_compute_counts',
        help='Destinos que fallaron al asignar el lote.')

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTOS
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('line_ids.result')
    def _compute_counts(self):
        """Cuenta las filas por resultado (resumen de la cabecera)."""
        for result in self:
            result.assigned_count = len(result.line_ids.filtered(
                lambda line: line.result == 'assigned'))
            result.partial_count = len(result.line_ids.filtered(
                lambda line: line.result == 'partial'))
            result.omitted_count = len(result.line_ids.filtered(
                lambda line: line.result == 'skipped'))
            result.error_count = len(result.line_ids.filtered(
                lambda line: line.result == 'error'))

    # ══════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN DEL SNAPSHOT
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_build_from_bulk(self, bulk):
        """Crea el detalle con UNA fila por destino del contenedor.

        Copia ``seq``/``label``/``kind``/``demand_qty``/``result``/
        ``result_note`` de TODOS los destinos (``assigned``/``partial``/
        ``skipped``/``error``/``pending``): los destinos NO asignables ya llegan
        como ``skipped`` + nota desde el poblado del contenedor, así que el
        detalle los muestra sin recalcular nada.

        :param bulk: ``printflow.flow.lot.assign.bulk`` ya ejecutado.
        :rtype: models.Model
        """
        if not bulk:
            return self.browse()
        line_vals = [(0, 0, {
            'seq': line.seq,
            'label': line.label,
            'kind': line.kind,
            'demand_qty': line.demand_qty,
            'result': line.result,
            'result_note': line.result_note,
        }) for line in bulk.line_ids]
        return self.create({
            'bulk_id': bulk.id,
            'product_id': bulk.product_id.id,
            'source_label': bulk.source_label,
            'line_ids': line_vals,
        })
