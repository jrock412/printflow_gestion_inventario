# -*- coding: utf-8 -*-
"""Asignación EN BLOQUE de lote POR UNIDAD (PrintFlow).

``TransientModel`` CONTENEDOR que convierte la SELECCIÓN de la bandeja de lote
(``printflow.flow.lot.tray``) en una decisión masiva con **UNA sola acción**
("Asignar lote"): el operador marca N filas de entrega sin lote, el contenedor
abre **UNA fila por MOVIMIENTO** (una unidad = una línea de pedido) con **SU**
selector de lote, y el par caja ↔ unidad lo decide el operador, fila por fila,
en una sola pasada (H-039/H-040). La tabla de candidatos (Lote · Existencia ·
Reservado · Disponible · Rol) es **INFORMATIVA**: no se marca nada en ella.

Por qué un wizard propio y no reutilizar el selector
----------------------------------------------------
El selector por documento (``printflow.flow.lot.picker``) está amarrado a UN
documento por diseño (``picker_id`` obligatorio, demanda única, política de
excepción por documento) y está cubierto por tests. Forzarlo a "varios
documentos" ensuciaría su contrato. Este contenedor es más simple y limpio: N
unidades (``line_ids``) + UN motivo.

Cero reinvención
----------------
Se REUTILIZAN las piezas EXISTENTES: el cálculo de candidatos
(``printflow.flow.lots._pf_available_lots``, UNA lectura de ``stock.quant``), el
modelo/vista de candidato (``printflow.flow.lot.candidate``), el ORQUESTADOR
ÚNICO de escritura ``printflow.product.flow._pf_assign_lots_to_document`` (que
despacha al protocolo NATIVO **aditivo** de reasignación), la guardia de permisos
``printflow.stock.remedy._pf_assert_can_clean`` y la política de excepción
(``pf_lot_assign_exception_policy``, sin hardcodeo).

Código sí, datos no
-------------------
La ÚNICA escritura del bloque es el remedio NATIVO por movimiento (reasignación
de reserva). No hay ``cr.execute``/``cr.commit``, ni se escribe ``stock.quant`` /
``stock.move`` a mano, ni se fuerza ningún estado. Las filas NO asignables y las
que no traen lote elegido se OMITEN y se reportan (nunca revientan la corrida).

Contrato::

    bulk = env['printflow.flow.lot.assign.bulk']._pf_populate(product, rows)
    for line in bulk.line_ids:                     # una fila = un movimiento
        line.lot_id = env['stock.lot'].browse(...)  # decisión del operador
    action = bulk.action_assign_lot_bulk()
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

_logger = logging.getLogger(__name__)

# Kinds de la bandeja que SÍ se resuelven en bloque: entregas SIN lote
# (movimiento ya creado sin lote u orden de entrega pendiente sin lote). El
# resto (MO sin lote, insumos, reserva huérfana, lotes genéricos/mezclados) se
# OMITE y se reporta (D7).
_BULK_ASSIGNABLE_KINDS = ('missing_move', 'pending_order')

# Modelos con chatter propio (para el registro auditable por documento, D8).
_CHATTER_MODELS = ('stock.picking', 'mrp.production')


class PrintflowFlowLotAssignBulk(models.TransientModel):
    """Modal que asigna a CADA unidad (movimiento) su lote con UN motivo común."""

    _name = 'printflow.flow.lot.assign.bulk'
    _description = 'Asignación de lote en bloque (PrintFlow)'

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, readonly=True,
        ondelete='cascade')
    source_label = fields.Char(
        string='Origen', readonly=True,
        help='Etiqueta legible de la selección de origen (trazabilidad).')
    location_id = fields.Many2one(
        'stock.location', string='Ubicación', readonly=True,
        help='Ubicación efectiva común de los destinos. Vacía cuando hay varias '
             '(o ninguna) ubicación: entonces la disponibilidad se juzga '
             'AGREGADA (ver ``multi_location``).')
    multi_location = fields.Boolean(
        string='Varias ubicaciones', readonly=True,
        help='Verdadero si los destinos NO comparten una única ubicación: los '
             'candidatos muestran disponibilidad AGREGADA (aviso visible).')
    total_demand = fields.Float(
        string='Unidades a entregar', readonly=True,
        digits='Product Unit of Measure',
        help='Suma de la demanda de los destinos asignables, en UNIDADES de '
             'producto. Con ella se decide si el lote alcanza (o la asignación '
             'es parcial).')
    line_ids = fields.One2many(
        'printflow.flow.lot.assign.bulk.line', 'bulk_id',
        string='Destinos',
        help='Una fila por UNIDAD de la selección (cada fila es un '
             '``stock.move`` = una unidad / línea de pedido).')
    candidate_ids = fields.One2many(
        'printflow.flow.lot.candidate', 'bulk_id',
        string='Lotes con existencia')
    candidate_lot_ids = fields.Many2many(
        'stock.lot', 'printflow_assign_bulk_candidate_lot_rel',
        'bulk_id', 'lot_id', string='Lotes elegibles',
        compute='_compute_candidate_lot_ids',
        help='Lotes con existencia libre (> 0): los únicos elegibles en el '
             'desplegable de cada unidad. Alimentan el dominio del selector POR '
             'FILA (no hay un "lote de toda la selección").')
    candidate_count = fields.Integer(
        string='Lotes con existencia', compute='_compute_candidate_count',
        readonly=True,
        help='Número de lotes con existencia REAL que se pueden elegir en el '
             'desplegable de cada unidad: la señal de "¿alcanza la '
             'mercancía?".')
    confirm_exception = fields.Boolean(
        string='Confirmo la excepción',
        help='Check que exige la política de excepción configurada cuando es '
             'distinta a ``warn`` (cero hardcodeo).')
    reason = fields.Text(
        string='Motivo',
        help='Justificación COMÚN de la asignación en bloque (queda en la '
             'bitácora de cada documento).')
    omitted_count = fields.Integer(
        string='Filas omitidas', readonly=True,
        help='Filas descartadas al preparar la selección (no asignables, sin '
             'movimiento activo, duplicadas o no elegibles). No son unidades: es '
             'un conteo de FILAS.')
    assignable_count = fields.Integer(
        string='Unidades por asignar', compute='_compute_assignable_count',
        help='Número de UNIDADES (movimientos = líneas de pedido) que SÍ '
             'admiten la asignación en bloque: una entrega con N unidades '
             'produce N filas.')
    selection_note = fields.Char(
        string='Resumen de la selección',
        compute='_compute_selection_note', readonly=True,
        help='Texto VISIBLE que declara qué ES cada fila: una UNIDAD (un '
             'movimiento de la entrega = una línea de pedido). Los conteos de '
             'unidades ya van rotulados al lado (H-031).')

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTOS
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('candidate_ids.is_elective', 'candidate_ids.lot_id')
    def _compute_candidate_lot_ids(self):
        """Lotes candidatos con existencia libre (> 0): alimentan el dominio."""
        for rec in self:
            rec.candidate_lot_ids = rec.candidate_ids.filtered(
                'is_elective').mapped('lot_id')

    @api.depends('candidate_ids')
    def _compute_candidate_count(self):
        """Cuenta los lotes con existencia que pinta la cabecera (D-9)."""
        for rec in self:
            rec.candidate_count = len(rec.candidate_ids)

    @api.depends('line_ids.assignable')
    def _compute_assignable_count(self):
        """Cuenta los destinos asignables (los que sí se procesan)."""
        for rec in self:
            rec.assignable_count = len(rec.line_ids.filtered('assignable'))

    @api.depends()
    def _compute_selection_note(self):
        """Texto VISIBLE y CONSTANTE que declara qué ES cada fila (D-8).

        Aclara la UNIDAD de la fila (una unidad = un movimiento de la entrega =
        una línea de pedido) y NADA MÁS: los conteos ya están rotulados al lado
        ("Unidades por asignar" / "Unidades a entregar"), así que repetirlos en
        prosa apretaba la cabecera (H-047). Sin dependencias: el texto no varía.
        """
        for rec in self:
            rec.selection_note = _(
                'Cada fila es una unidad: un movimiento de la entrega = una '
                'línea de pedido.')

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, product, rows, omitted_count=0):
        """Crea el contenedor con sus destinos y sus candidatos.

        :param product: ``product.product`` de la selección.
        :param list[dict] rows: filas CRUDAS de la bandeja (dicts con ``kind``,
            ``res_model``, ``res_id``, ``label``, ``demand_qty``, ``location_id``,
            ``scheduled_date``, ``own_lot_name`` y opcionalmente ``move_id``).
            Cada fila es UN MOVIMIENTO (una unidad / línea de pedido).
        :param int omitted_count: filas ya descartadas por el llamador (tray).
        :rtype: models.Model

        Cada línea nace con el SNAPSHOT de su unidad (``move_id``, documento,
        demanda, ``sale_line_id``/``sale_order_name``, lote propio con su
        existencia) y con el ``lot_id`` **VACÍO** (D-1/CA-1): el operador decide
        el lote de CADA unidad; el lote propio solo se INFORMA (``own_lot_name``
        + ``own_lot_qty``), nunca se pre-llena.
        """
        product = product.exists() if product else self.env['product.product']
        if not product or not rows:
            return self.browse()
        prepared = self._pf_prepare_rows(product, rows)
        if not prepared:
            return self.browse()
        total_demand = sum(
            row['demand_qty'] for row in prepared if row['assignable'])
        location_ids = {
            row['location_id'] for row in prepared
            if row['assignable'] and row['location_id']}
        single_location = (
            next(iter(location_ids)) if len(location_ids) == 1 else False)
        multi_location = len(location_ids) != 1
        own_lot_ids = set(self._pf_own_lot_ids(product, prepared))
        candidates = self.env['printflow.flow.lots']._pf_available_lots(
            product, location_id=single_location or False,
            demand_qty=total_demand)
        cand_vals = [(0, 0, {
            'lot_id': cand['lot_id'],
            'lot_name': cand['lot_name'],
            'qty_on_hand': cand['qty_on_hand'],
            'available': cand['available'],
            'available_here': cand['available_here'],
            'covers_demand': cand['covers_demand'],
            'reserved': cand['reserved'],
            'location_names': cand['location_names'],
            'is_generic': cand['is_generic'],
            'is_occupied': cand.get('is_occupied', False),
            'holder_names': cand.get('holder_names', ''),
            'is_own_lot': cand['lot_id'] in own_lot_ids,
        }) for cand in candidates]
        # Existencia por lote EN MANO: sale de la MISMA lectura de candidatos
        # (sin N+1) y alimenta ``own_lot_qty`` de la fila (CA-2). El lote propio
        # SIN mercancía deja de ser candidato (D-2) ⇒ informa ``0.00``, que es el
        # resultado deseado, conservando su nombre visible.
        qty_by_lot = {
            cand['lot_id']: cand['qty_on_hand'] for cand in candidates}
        # El lote propio puede NO existir como ``stock.lot``: en ese caso no hay
        # registro ni existencia y la fila lo muestra en ``0.00`` con su nombre.
        lot_by_name = {
            cand['lot_name']: cand['lot_id'] for cand in candidates}
        line_vals = []
        for seq, row in enumerate(prepared, start=1):
            own_lot_id = lot_by_name.get(row['own_lot_name'] or '') or 0
            line_vals.append((0, 0, {
                'seq': seq,
                'kind': row['kind'],
                'res_model': row['res_model'],
                'res_id': row['res_id'],
                'move_id': row['move_id'] or False,
                'label': row['label'],
                'demand_qty': row['demand_qty'],
                'location_id': row['location_id'] or False,
                'scheduled_date': row['scheduled_date'] or False,
                'assignable': row['assignable'],
                'result': row['result'],
                'result_note': row['result_note'],
                'own_lot_id': own_lot_id or False,
                'own_lot_name': row['own_lot_name'] or '',
                'own_lot_qty': qty_by_lot.get(own_lot_id, 0.0),
                'sale_order_name': row.get('sale_order_name') or '',
                'sale_line_id': row.get('sale_line_id') or False,
                # D-1/CA-1: TODAS las filas nacen SIN lote elegido; el lote
                # propio solo se INFORMA (nombre + existencia), no se pre-llena.
                'lot_id': False,
            }))

        skipped = len([row for row in prepared if not row['assignable']])
        return self.create({
            'product_id': product.id,
            'source_label': self._pf_source_label(
                product, len(prepared), omitted_count),
            'location_id': single_location or False,
            'multi_location': multi_location,
            'total_demand': total_demand,
            'omitted_count': (omitted_count or 0) + skipped,
            'line_ids': line_vals,
            'candidate_ids': cand_vals,
        })

    @api.model
    def _pf_prepare_rows(self, product, rows):
        """Normaliza las filas CRUDAS a destinos ORDENADOS y DEDUPLICADOS.

        Resuelve el ``stock.move`` de cada fila (para ``pending_order``, el
        movimiento activo del albarán) con UNA lectura batch, completa la
        ubicación/fecha efectivas con UNA lectura de los movimientos resueltos
        (D2/D6), resuelve el **lote propio de cada MOVIMIENTO** con la primitiva
        del motor (sin N+1, R-4), DEDUPLICA por ``move_id`` (D5: ``missing_move``
        y ``pending_order`` pueden apuntar al MISMO albarán) y ordena FIFO por
        fecha prevista ASC + id ASC (D6). Es una traducción PURA (sin escritura).

        :rtype: list[dict]
        """
        Move = self.env['stock.move'].sudo()
        raw = []
        pending_pickings = set()
        for row in rows:
            move_id = row.get('move_id') or 0
            if hasattr(move_id, 'id'):
                move_id = move_id.id or 0
            picking_id = row.get('picking_id') or 0
            if hasattr(picking_id, 'id'):
                picking_id = picking_id.id or 0
            kind = row.get('kind') or ''
            res_model = row.get('res_model') or ''
            res_id = row.get('res_id') or 0
            if not move_id and kind == 'missing_move' and res_model == 'stock.move':
                move_id = res_id
            if not move_id and kind == 'pending_order' and res_model == 'stock.picking':
                picking_id = picking_id or res_id
                if picking_id:
                    pending_pickings.add(picking_id)
            raw.append({
                'kind': kind,
                'res_model': res_model,
                'res_id': res_id,
                'move_id': move_id,
                'picking_id': picking_id,
                'label': row.get('label') or '',
                'demand_qty': row.get('demand_qty') or 0.0,
                'location_id': row.get('location_id') or 0,
                'scheduled_date': row.get('scheduled_date') or False,
                'own_lot_name': row.get('own_lot_name') or '',
            })
        # (1) UNA lectura batch: albarán -> movimiento activo del producto.
        if pending_pickings:
            by_picking = {}
            for move in Move.search([
                ('picking_id', 'in', list(pending_pickings)),
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
            ], order='id asc'):
                by_picking.setdefault(move.picking_id.id, move.id)
            for item in raw:
                if item['picking_id'] and not item['move_id']:
                    item['move_id'] = by_picking.get(item['picking_id'], 0)
        # (2) UNA lectura batch: ubicación/fecha/venta de los movimientos resueltos.
        move_ids = {item['move_id'] for item in raw if item['move_id']}
        move_info = {}
        if move_ids:
            for data in Move.browse(list(move_ids)).read(
                    ['location_id', 'date', 'picking_id', 'product_uom_qty',
                     'sale_line_id']):
                move_info[data['id']] = data
        picking_for_date = set()
        for item in raw:
            info = move_info.get(item['move_id']) or {}
            loc_ref = info.get('location_id') or False
            item['_move_location'] = (loc_ref[0] if loc_ref else 0) or 0
            item['_move_date'] = info.get('date') or False
            pick_ref = info.get('picking_id') or False
            item['_move_picking'] = (pick_ref[0] if pick_ref else 0) or 0
            sale_ref = info.get('sale_line_id') or False
            item['_move_sale'] = (sale_ref[0] if sale_ref else 0) or 0
            item['_move_qty'] = info.get('product_uom_qty') or 0.0
            if (not item['scheduled_date'] and not item['_move_date']
                    and item['_move_picking']):
                picking_for_date.add(item['_move_picking'])
        picking_dates = {}
        if picking_for_date:
            for data in self.env['stock.picking'].sudo().browse(
                    list(picking_for_date)).read(['scheduled_date']):
                picking_dates[data['id']] = data['scheduled_date'] or False
        for item in raw:
            if not item['location_id']:
                item['location_id'] = item['_move_location']
            if not item['scheduled_date']:
                item['scheduled_date'] = (
                    item['_move_date']
                    or picking_dates.get(item['_move_picking'])
                    or False)
        # (2.b) Lote PROPIO POR MOVIMIENTO (R-4): el lote propio se resuelve por
        # UNIDAD con la MISMA primitiva del motor que usa la bandeja
        # (``sale.order.line._get_exclusive_lot_name``) sobre UNA lectura batch de
        # las líneas de pedido. El ``own_lot_name`` que trae la fila de la bandeja
        # queda como RESPALDO cuando el movimiento no tiene línea de pedido.
        sale_line_ids = {item['_move_sale'] for item in raw if item['_move_sale']}
        sale_lines = (
            self.env['sale.order.line'].sudo().browse(
                list(sale_line_ids)).exists()
            if sale_line_ids else self.env['sale.order.line'])
        sale_lines.mapped('order_id')  # precarga (1 lectura) de los pedidos
        sale_names = {
            sale_line.id: (sale_line.order_id.name or '')
            for sale_line in sale_lines}
        own_names = {
            sale_line.id: (sale_line._get_exclusive_lot_name() or '')
            for sale_line in sale_lines}
        for item in raw:
            sale_id = item['_move_sale']
            item['sale_line_id'] = sale_id or 0
            item['sale_order_name'] = sale_names.get(sale_id) or ''
            item['own_lot_name'] = (
                own_names.get(sale_id) or item['own_lot_name'])
            # La demanda de la fila ES la del movimiento (grano = MOVIMIENTO);
            # el valor de la bandeja queda como respaldo si no llega.
            if not item['demand_qty']:
                item['demand_qty'] = item['_move_qty'] or 0.0
        # (3) Orden determinista FIFO (fecha ASC, id ASC; sin fecha al final).
        raw.sort(key=lambda item: (
            not bool(item['scheduled_date']),
            item['scheduled_date'] or '',
            item['res_id'] or 0,
        ))
        # (4) Clasificación + DEDUPE por movimiento (D5/D7): el primero gana.
        seen_moves = set()
        prepared = []
        for item in raw:
            if not item['move_id']:
                item['assignable'] = False
                item['result'] = 'skipped'
                item['result_note'] = _(
                    'La entrega no resuelve un movimiento activo.')
            elif item['move_id'] in seen_moves:
                item['assignable'] = False
                item['result'] = 'skipped'
                item['result_note'] = _(
                    'Duplicado: la misma entrega ya está en la selección.')
            elif item['kind'] not in _BULK_ASSIGNABLE_KINDS:
                item['assignable'] = False
                item['result'] = 'skipped'
                item['result_note'] = _('Tipo no asignable en bloque.')
            else:
                item['assignable'] = True
                item['result'] = 'pending'
                item['result_note'] = ''
                seen_moves.add(item['move_id'])
            prepared.append(item)
        return prepared

    @api.model
    def _pf_own_lot_ids(self, product, rows):
        """Ids de los lotes PROPIOS distintos de las filas (UNA búsqueda).

        Mismo patrón de ``printflow.flow.lot.tray._pf_annotate_lot_quantities``:
        resuelve los nombres a registros ``stock.lot`` en UNA sola búsqueda.
        :rtype: list[int]
        """
        names = {
            row.get('own_lot_name') for row in rows if row.get('own_lot_name')}
        if not product or not names:
            return []
        lots = self.env['stock.lot'].sudo().search([
            ('product_id', '=', product.id),
            ('name', 'in', list(names)),
        ])
        return lots.ids

    @api.model
    def _pf_source_label(self, product, total, omitted):
        """Etiqueta legible de la selección de origen (trazabilidad)."""
        return _('Asignación en bloque: %(product)s (%(n)s entrega(s))') % {
            'product': product.display_name if product else '',
            'n': total}

    # ══════════════════════════════════════════════════════════════════════
    # ACCIÓN PRINCIPAL
    # ══════════════════════════════════════════════════════════════════════
    def action_assign_lot_bulk(self):
        """Asigna a CADA unidad el lote que el operador eligió EN SU FILA.

        Contrato NUEVO (H-039/H-040 · D1/D2): un destino = UN MOVIMIENTO (una
        unidad / línea de pedido) y cada fila lleva SU lote (``line.lot_id``):
        el operador decide el par caja ↔ unidad en una sola pasada.

        Pasos (D5/D6):
        1. guardia de permisos ``_pf_assert_can_clean`` (jefe de taller/admin);
        2. ``reason`` obligatorio y política de excepción (cero hardcodeo: la
           política sale de ``pf_lot_assign_exception_policy``);
        3. guía SIN escritura: si NINGUNA unidad asignable trae lote ⇒
           ``UserError``; las filas sin lote NO bloquean a las demás;
        4. por cada unidad asignable (FIFO), delegar la ESCRITURA en el
           ORQUESTADOR ÚNICO ``_pf_assign_lots_to_document`` (protocolo NATIVO
           ADITIVO: 1 liberación + N reservas) pasándole el MOVIMIENTO directo
           (sin ``limit=1``), dentro de un **savepoint por unidad** ("un solo
           aliento", CA-7) que captura el ``UserError`` y cualquier otro fallo
           POR FILA (nunca aborta el barrido) y clasifica el resultado
           (asignado/parcial/error);
        5. bitácora por documento (chatter: lote + motivo + usuario) y
           notificación con los conteos (CA-6), ENCADENADA al DETALLE por
           destino (H-029).

        Código sí, datos no: la ÚNICA escritura son las primitivas NATIVAS del
        motor disparadas por este botón; no hay ``cr.execute``/``cr.commit``.
        """
        self.ensure_one()
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        if not (self.reason or '').strip():
            raise UserError(_(
                'Debes indicar el motivo de la asignación en bloque.'))
        policy = self.env['printflow.flow.lot.picker']._pf_exception_policy()
        if policy != 'warn' and not self.confirm_exception:
            raise UserError(_(
                'La política vigente exige confirmar la excepción: marca '
                '"Confirmo la excepción" para asignar los lotes.'))
        assignable = self.line_ids.filtered('assignable')
        if not assignable.filtered('lot_id'):
            raise UserError(_(
                'Elige el lote de al menos una unidad: cada fila es un '
                'movimiento (una unidad / línea de pedido) de la entrega.'))
        ProductFlow = self.env['printflow.product.flow']
        for line in assignable:
            if not line.lot_id:
                line.result = 'skipped'
                line.result_note = _(
                    'Sin lote elegido: la unidad no se toca.')
                continue
            # "Un solo aliento" por unidad (CA-7): si algo falla a mitad del
            # baile, el savepoint revierte TODO y la unidad queda como estaba
            # (tachón y lote viejos), nunca destildada por accidente.
            failure_note = None
            try:
                with self.env.cr.savepoint():
                    ProductFlow._pf_assign_lots_to_document(
                        line.kind, 'stock.move', line.move_id.id,
                        [line.lot_id], product=self.product_id)
            except UserError as err:
                # Motivo de negocio, tal cual lo reporta el orquestador.
                failure_note = str(err) or _(
                    'No se pudo asignar el lote a la unidad.')
            except Exception as exc:  # noqa: BLE001  (patrón de casa)
                # El savepoint ya revirtió; se registra y NO tumba el barrido.
                _logger.warning(
                    'Asignación en bloque: fallo al asignar el lote a la '
                    'unidad %s (movimiento %s): %s',
                    line.id, line.move_id.id, exc)
                failure_note = _(
                    'No se pudo asignar el lote a la unidad.')
            # La caché del ORM NO revierte con el savepoint (C-3): se refresca
            # el tachón antes de leer/afirmar el estado real.
            line.move_id.invalidate_recordset(['picked'])
            # La clasificación se escribe FUERA del savepoint (si se escribiera
            # dentro, el rollback la borraría y la fila quedaría muda).
            if failure_note is not None:
                line.result = 'error'
                line.result_note = failure_note
                continue
            reserved = self._pf_line_reserved(line, line.lot_id)
            demand = line.demand_qty or 0.0
            if demand <= _EPS:
                line.result = 'skipped'
                line.result_note = _(
                    'La unidad no tiene demanda: nada que asignar.')
            elif reserved <= _EPS:
                line.result = 'error'
                line.result_note = _(
                    'El lote "%(lot)s" no tiene existencia disponible aquí.'
                ) % {'lot': line.lot_id.name or ''}
            elif not line.move_id._pf_unit_is_covered(reserved, demand):
                line.result = 'partial'
                line.result_note = _('Solo se reservó lo disponible.')
            else:
                line.result = 'assigned'
                line.result_note = _('Lote asignado.')
            self._pf_log_document(line, line.lot_id)
        # H-029: se materializa el motivo POR DESTINO en una ventana de solo
        # lectura y se ENCADENA a la notificación. La escritura ya terminó.
        result = self.env[
            'printflow.flow.lot.assign.bulk.result']._pf_build_from_bulk(self)
        return self._pf_result_notification(result)

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS DE ESCRITURA / BITÁCORA
    # ══════════════════════════════════════════════════════════════════════
    def _pf_line_reserved(self, line, lot):
        """Cantidad del lote ELEGIDO realmente reservada en el movimiento."""
        if not line.move_id:
            return 0.0
        move_lines = self.env['stock.move.line'].sudo().search([
            ('move_id', '=', line.move_id.id),
            ('lot_id', '=', lot.id),
        ])
        return sum(move_lines.mapped('quantity'))

    def _pf_log_document(self, line, lot):
        """Registra la asignación en el chatter del documento (D8).

        Solo en modelos con chatter (``stock.picking``/``mrp.production``); si no
        hay chatter, se omite el registro (no revienta la asignación).
        """
        if line.res_model not in _CHATTER_MODELS or not line.res_id:
            return
        doc = self.env[line.res_model].sudo().browse(line.res_id).exists()
        if not doc:
            return
        doc.message_post(
            body=_('PrintFlow · Lote "%(lot)s" asignado en bloque a %(doc)s.\n'
                   'Motivo: %(reason)s\nUsuario: %(user)s') % {
                'lot': lot.name,
                'doc': line.label or doc.display_name,
                'reason': (self.reason or '').strip() or _('(sin motivo)'),
                'user': self.env.user.display_name or '',
            },
            message_type='notification', subtype_xmlid='mail.mt_note')

    def _pf_result_notification(self, result=None):
        """Notificación con los 4 conteos (asignadas/parciales/omitidas/error).

        Conserva EXACTAMENTE el texto de cierre (contrato CA-7) y, cuando recibe
        el detalle, añade ``params['next']`` con la ventana de SOLO LECTURA
        ``printflow.flow.lot.assign.bulk.result`` (H-029): la notificación no se
        desplaza y con 26+ motivos no se alcanza a leer, así que el motivo real
        por destino se muestra en esa ventana. Sin ``result`` el comportamiento
        es el de siempre (cerrar el modal), igual que el precedente
        ``printflow_node_pending_line.action_pf_validate_selected``.
        """
        assigned = partial = error = 0
        for line in self.line_ids:
            if line.result == 'assigned':
                assigned += 1
            elif line.result == 'partial':
                partial += 1
            elif line.result == 'error':
                error += 1
        nxt = {'type': 'ir.actions.act_window_close'}
        if result:
            nxt = {
                'type': 'ir.actions.act_window',
                'name': _('Detalle de la asignación en bloque'),
                'res_model': 'printflow.flow.lot.assign.bulk.result',
                'res_id': result.id,
                'view_mode': 'form',
                # Odoo solo normaliza ``views`` en la acción de PRIMER nivel que
                # devuelve un botón; las acciones ANIDADAS en ``params['next']``
                # NO se normalizan y revientan en el cliente
                # (``action_service.js::_preprocessAction`` hace
                # ``action.views.map(...)``). Se declara la MISMA convención que
                # usa el core al normalizar: ``[(False, 'form')]`` ⇒ vista por
                # defecto del modelo.
                'views': [(False, 'form')],
                'target': 'new',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('PrintFlow'),
                'message': _(
                    '%(assigned)s asignadas · %(partial)s parciales · '
                    '%(omitted)s omitidas · %(error)s con error.') % {
                    'assigned': assigned,
                    'partial': partial,
                    'omitted': self.omitted_count or 0,
                    'error': error,
                },
                'sticky': False,
                'next': nxt,
            },
        }
