# -*- coding: utf-8 -*-
"""LÍNEA de DESTINO de la asignación EN BLOQUE de lote (PrintFlow).

``TransientModel`` que representa UN destino de la acción en bloque
(``printflow.flow.lot.assign.bulk``). El destino ya NO es "una entrega": es **UNA
UNIDAD**, es decir **un ``stock.move``** (unidad = línea de pedido) de la entrega
(H-039 / H-040 · grano por MOVIMIENTO).

Por qué existe
--------------
A diferencia del selector POR DOCUMENTO (``printflow.flow.lot.picker``), la
acción en bloque resuelve N movimientos con UN motivo. Se necesita una fila por
movimiento que guarde:

* el SNAPSHOT de la selección (tipo, modelo/id del **documento**, movimiento,
  demanda de ESA unidad, ubicación, fecha);
* el snapshot del **lote propio** de la unidad (``own_lot_name`` = ``<pedido>-
  L<línea>`` con su existencia), para que el operador VEA si la caja del pedido
  está vacía (D3/D4);
* la **decisión del operador** para ESA unidad (``lot_id``: el lote a asignar);
* el RESULTADO por fila (asignado / parcial / omitido / error), para reportar
  cuántas unidades quedaron cubiertas y cuántas no (CA-3, CA-7, CA-9).

Esta línea es SOLO un snapshot + la decisión del operador: NO escribe en
``stock.*``. La ÚNICA escritura del bloque es la reasignación NATIVA que dispara
el contenedor por el orquestador
``printflow.product.flow._pf_assign_lots_to_document``.
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
        'stock.move', string='Unidad', readonly=True,
        help='``stock.move`` que respalda esta UNIDAD de la entrega (una fila = '
             'un movimiento = una unidad / línea de pedido). Es lo único que se '
             'escribe al aplicar.')
    # El dominio del selector POR FILA usa la RUTA AL PADRE (``parent.``) para el
    # producto y los lotes elegibles: el contenedor
    # (``printflow.flow.lot.assign.bulk``) declara ``product_id`` y
    # ``candidate_lot_ids`` en su form, así el dominio resuelve en el cliente y la
    # validación de vistas de Odoo 17 lo acepta (un dominio que apunte a
    # ``bulk_id.<campo>`` obligaría a pintar ``bulk_id`` en la sub-vista y hoy
    # rompe la carga del módulo). Semántica: SOLO lotes con existencia del
    # producto (D4) MENOS el lote propio de la unidad: ``own_lot_id`` es campo de
    # ESTA línea ⇒ se referencia directo, sin ruta al padre. El lote propio NO se
    # ofrece en su propia fila (candado de DOMINIO, D-3 · prevención).
    # ⚠️ El validador de vistas de Odoo 17 (``must_have_fields``) exige que TODO
    # campo citado en un dominio esté PRESENTE en la vista: por eso la vista del
    # contenedor pinta ``own_lot_id`` con ``column_invisible="True"``. Si se
    # quita ese nodo, el módulo deja de cargar (``must be present in view``).
    lot_id = fields.Many2one(
        'stock.lot', string='Lote a asignar',
        domain="[('product_id', '=', parent.product_id), "
               "('id', 'in', parent.candidate_lot_ids), "
               "('id', '!=', own_lot_id)]",
        help='Lote que el operador decide asignar a ESTA unidad. El desplegable '
             'solo lista lotes con existencia del producto (D4) y NO ofrece el '
             'lote propio de la unidad (candado de dominio, D-3): el uso normal '
             'es elegir OTRO lote. La decisión es fila por fila, no una caja '
             'para toda la selección.')
    own_lot_id = fields.Many2one(
        'stock.lot', string='Registro del lote propio', readonly=True,
        help='Registro ``stock.lot`` del lote propio de la unidad, si existe. '
             'Puede no existir: el nombre se muestra igual (con existencia '
             '0.00) para que el operador vea que la caja del pedido está vacía.')
    own_lot_name = fields.Char(
        string='Lote propio', readonly=True,
        help='Nombre del lote propio del pedido de ESTA unidad '
             '(<pedido>-L<línea>): el que la Ley #1 espera. Es informativo: la '
             'decisión se toma en "Lote a asignar".')
    own_lot_qty = fields.Float(
        string='Existencia del lote propio', readonly=True,
        digits='Product Unit of Measure',
        help='Existencia del lote propio de la unidad. En 0.00 confirma que la '
             'caja del pedido está vacía (D4: elección consciente).')
    sale_order_name = fields.Char(
        string='Pedido', readonly=True,
        help='Nombre de la orden de venta asociada a esta unidad (trazabilidad '
             'del par caja ↔ pedido).')
    sale_line_id = fields.Many2one(
        'sale.order.line', string='Línea de pedido', readonly=True,
        help='Línea de pedido de venta que originó esta unidad (el lote propio '
             'se deriva de ella: <pedido>-L<línea>).')
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
