# -*- coding: utf-8 -*-
"""Asignación EN BLOQUE de lote a N entregas sin lote (PrintFlow).

``TransientModel`` CONTENEDOR que convierte la SELECCIÓN de la bandeja de lote
(``printflow.flow.lot.tray``) en una decisión masiva. Tiene DOS MODOS (``mode``):

* ``single`` (el de siempre): el operador marca N filas de entrega sin lote,
  pulsa el botón de cabecera "Asignar lote" y este wizard pregunta UN lote (con
  la tabla de candidatos: Lote · Existencia · Reservado · Disponible · Rol) y UN
  motivo, y asigna ese lote a TODOS los destinos.
* ``split`` (reparto, H-037): el operador pulsa "Repartir lotes", marca VARIOS
  lotes con la columna "Incluir" y el reparto consume esos lotes —en el orden de
  la tabla— para cubrir la demanda de los destinos, de forma ADITIVA (1
  liberación + N reservas por la vía NATIVA). Ver ``_pf_reassign_lots`` en
  ``models/stock_move.py``.

Por qué un wizard NUEVO y no reutilizar el selector
---------------------------------------------------
El selector por documento (``printflow.flow.lot.picker``) está amarrado a UN
documento por diseño (``picker_id`` obligatorio, demanda única, política de
excepción por documento) y está cubierto por tests. Forzarlo a "varios
documentos" ensuciaría su contrato. Este contenedor es más simple y limpio: N
destinos (``line_ids``) + K lotes + UN motivo. El modo NO cambia los destinos ni
los candidatos: solo el camino de DECISIÓN (un lote vs. reparto multi-lote).

Cero reinvención
----------------
Se REUTILIZAN las piezas EXISTENTES: el cálculo de candidatos
(``printflow.flow.lots._pf_available_lots``, UNA lectura de ``stock.quant``), el
modelo/vista de candidato (``printflow.flow.lot.candidate``), el ORQUESTADOR
ÚNICO de escritura ``printflow.product.flow._pf_assign_lot_to_document`` (que
despacha al protocolo NATIVO de reasignación), la guardia de permisos
``printflow.stock.remedy._pf_assert_can_clean`` y la política de excepción
(``pf_lot_assign_exception_policy``, sin hardcodeo).

Código sí, datos no
-------------------
La ÚNICA escritura del bloque es el remedio NATIVO por documento (reasignación
de reserva). No hay ``cr.execute``/``cr.commit``, ni se escribe ``stock.quant`` /
``stock.move`` a mano, ni se fuerza ningún estado. Los destinos NO asignables se
OMITEN y se reportan (nunca revientan el lote).

Contrato::

    bulk = env['printflow.flow.lot.assign.bulk']._pf_populate(product, rows)
    action = bulk.action_assign_lot_bulk()          # modo 'single'
    bulk = env['printflow.flow.lot.assign.bulk']._pf_populate(
        product, rows, mode='split')
    action = bulk.action_split_lot_bulk()           # modo 'split' (H-037)
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

# Kinds de la bandeja que SÍ se resuelven en bloque: entregas SIN lote
# (movimiento ya creado sin lote u orden de entrega pendiente sin lote). El
# resto (MO sin lote, insumos, reserva huérfana, lotes genéricos/mezclados) se
# OMITE y se reporta (D7).
_BULK_ASSIGNABLE_KINDS = ('missing_move', 'pending_order')

# Modelos con chatter propio (para el registro auditable por documento, D8).
_CHATTER_MODELS = ('stock.picking', 'mrp.production')


class PrintflowFlowLotAssignBulk(models.TransientModel):
    """Modal que asigna UN lote (con UN motivo) a N entregas sin lote."""

    _name = 'printflow.flow.lot.assign.bulk'
    _description = 'Asignación de lote en bloque (PrintFlow)'

    mode = fields.Selection(
        selection=[('single', 'Un lote (el marcado)'),
                   ('split', 'Reparto multi-lote')],
        string='Modo', default='single', readonly=True,
        help='Camino de DECISIÓN del contenedor: "single" asigna UN lote (el '
             'marcado) a toda la selección; "split" reparte la demanda entre '
             'VARIOS lotes marcados con la columna "Incluir" (H-037). El modo NO '
             'altera destinos ni candidatos, solo el camino de decisión.')
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
        help='Un destino (entrega sin lote) por fila seleccionada.')
    candidate_ids = fields.One2many(
        'printflow.flow.lot.candidate', 'bulk_id',
        string='Lotes con existencia')
    candidate_lot_ids = fields.Many2many(
        'stock.lot', 'printflow_assign_bulk_candidate_lot_rel',
        'bulk_id', 'lot_id', string='Lotes elegibles',
        compute='_compute_candidate_lot_ids',
        help='Lotes con existencia libre (> 0): los únicos elegibles en el '
             'desplegable.')
    lot_id = fields.Many2one(
        'stock.lot', string='Lote a asignar',
        domain="[('product_id', '=', product_id), "
               "('id', 'in', candidate_lot_ids)]",
        help='Lote que el operador decide asignar a TODA la selección.')
    confirm_partial = fields.Boolean(
        string='Confirmo la asignación parcial',
        help='Autoriza asignar un lote que NO cubre toda la demanda sumada; las '
             'entregas que no alcancen quedarán parciales.')
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
        help='Texto VISIBLE que declara la UNIDAD de cada fila: cada fila es una '
             'UNIDAD (un movimiento de la entrega = una línea de pedido); las '
             'cifras de demanda van en UNIDADES de producto (H-031).')
    split_note = fields.Char(
        string='Orden del reparto',
        compute='_compute_split_note', readonly=True,
        help='Plan VISIBLE del reparto multi-lote: los lotes marcados con '
             '"Incluir", en el ORDEN en que se consumen (el de la tabla) y el '
             'total disponible frente a la demanda. Es una ESTIMACIÓN de la '
             'tabla; la reserva REAL la decide la primitiva NATIVA por destino.')

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTOS
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('candidate_ids.is_elective', 'candidate_ids.lot_id')
    def _compute_candidate_lot_ids(self):
        """Lotes candidatos con existencia libre (> 0): alimentan el dominio."""
        for rec in self:
            rec.candidate_lot_ids = rec.candidate_ids.filtered(
                'is_elective').mapped('lot_id')

    @api.depends('line_ids.assignable')
    def _compute_assignable_count(self):
        """Cuenta los destinos asignables (los que sí se procesan)."""
        for rec in self:
            rec.assignable_count = len(rec.line_ids.filtered('assignable'))

    @api.depends('assignable_count', 'total_demand')
    def _compute_selection_note(self):
        """Texto VISIBLE que declara la UNIDAD de cada fila (H-031).

        Aclara que cada fila es una UNIDAD (un movimiento de la entrega = una
        línea de pedido) y que la demanda va en UNIDADES de producto: N unidades
        por asignar = M unidades a entregar. Así el operador no lee "26 vs 30"
        como una contradicción. Sin sufijos de unidad en los campos: la palabra
        "unidades" va en la oración (D3).
        """
        for rec in self:
            rec.selection_note = _(
                'Cada fila es una unidad (un movimiento de la entrega = una '
                'línea de pedido). %(n)s unidades por asignar = %(m)s unidades '
                'a entregar.') % {
                'n': rec.assignable_count or 0,
                'm': '%.2f' % (rec.total_demand or 0.0),
            }

    @api.depends('candidate_ids.is_in_split', 'candidate_ids.lot_name',
                 'candidate_ids.available_here', 'candidate_ids.available',
                 'total_demand')
    def _compute_split_note(self):
        """Plan VISIBLE del reparto (D2): lotes marcados EN ORDEN + total.

        El ORDEN es el de la tabla: ``candidate_ids.filtered('is_in_split')``
        respeta el ``_order`` del candidato (``available desc, lot_name asc``),
        así que "lo que se ve es el orden que se aplica" (determinista). La
        cifra por lote es la libre de la ubicación efectiva (``available_here``)
        o la AGREGADA (``available``) cuando hay varias ubicaciones. Es una
        estimación de la tabla, sin lecturas extra: la reserva real la decide la
        primitiva nativa por destino.
        """
        for rec in self:
            marked = rec.candidate_ids.filtered('is_in_split')
            if not marked:
                rec.split_note = _(
                    'Marca en la tabla los lotes a repartir (columna '
                    '"Incluir"): se consumen en el orden de la tabla, primero '
                    'el de más disponible.')
                continue
            free_by_cand = [
                (cand.available_here if rec.location_id else cand.available)
                for cand in marked]
            plan = ' · '.join(
                '%s) %s → %.2f' % (idx, cand.lot_name, free)
                for idx, (cand, free) in enumerate(
                    zip(marked, free_by_cand), start=1))
            rec.split_note = _(
                '%(plan)s. Total disponible: %(available)s de %(demand)s '
                'demandadas.') % {
                'plan': plan,
                'available': '%.2f' % sum(free_by_cand),
                'demand': '%.2f' % (rec.total_demand or 0.0),
            }

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, product, rows, omitted_count=0, mode='single'):
        """Crea el contenedor con sus destinos y sus candidatos.

        :param product: ``product.product`` de la selección.
        :param list[dict] rows: filas CRUDAS de la bandeja (dicts con ``kind``,
            ``res_model``, ``res_id``, ``label``, ``demand_qty``, ``location_id``,
            ``scheduled_date``, ``own_lot_name`` y opcionalmente ``move_id``).
            Cada fila es UN MOVIMIENTO (una unidad / línea de pedido).
        :param int omitted_count: filas ya descartadas por el llamador (tray).
        :param str mode: camino de decisión (``'single'`` por defecto ⇒ los
            llamadores actuales NO cambian; ``'split'`` ⇒ reparto multi-lote).
            El modo NO altera destinos ni candidatos, solo el camino de decisión
            que el operador verá en el form.
        :rtype: models.Model

        Cada línea nace con el SNAPSHOT de su unidad (``move_id``, documento,
        demanda, ``sale_line_id``/``sale_order_name``, lote propio con su
        existencia) y con el ``lot_id`` **pre-llenado** solo cuando el lote
        propio TIENE existencia efectiva (D3/CA-4); si no, queda vacío y visible.
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
            demand_qty=total_demand,
            include_lot_ids=list(own_lot_ids))
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
        # Existencia EFECTIVA por lote: la de la ubicación efectiva cuando es
        # única (``available_here``) o la AGREGADA si hay varias ubicaciones
        # (``available``), misma regla que la cobertura (D3/D4). Sale de la MISMA
        # lectura de candidatos: sin N+1. Se usa para PRE-LLENAR el lote propio
        # (D3/CA-4) y para informar su existencia en la fila.
        effective_by_lot = {
            cand['lot_id']: (
                cand['available'] if multi_location else cand['available_here'])
            for cand in candidates}
        qty_by_lot = {
            cand['lot_id']: cand['qty_on_hand'] for cand in candidates}
        # El lote propio puede NO existir como ``stock.lot``: en ese caso no hay
        # registro ni existencia (se muestra 0.00 y la fila queda SIN pre-llenar).
        lot_by_name = {
            cand['lot_name']: cand['lot_id'] for cand in candidates}
        line_vals = []
        for seq, row in enumerate(prepared, start=1):
            own_lot_id = lot_by_name.get(row['own_lot_name'] or '') or 0
            effective = (
                effective_by_lot.get(own_lot_id, 0.0) if own_lot_id else 0.0)
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
                # D3/CA-4: el lote propio se PRE-LLENA solo si tiene existencia
                # efectiva; si está vacío (0.00) la fila llega SIN lote y visible.
                'lot_id': own_lot_id if effective > _EPS else False,
            }))

        skipped = len([row for row in prepared if not row['assignable']])
        return self.create({
            'mode': mode,
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
    def _pf_selected_lot(self):
        """Lote elegido por el operador (fila marcada, o el desplegable).

        Misma semántica del selector por documento: la tabla es la fuente
        principal (fila con ``is_selected``); si no hay ninguna, cae al
        ``lot_id``. Exige selección ÚNICA (defensa: un dato cargado por fuera
        podría dejar dos marcas). :rtype: stock.lot
        """
        self.ensure_one()
        selected = self.candidate_ids.filtered('is_selected')
        if len(selected) > 1:
            raise UserError(_(
                'Hay más de un lote marcado en la tabla. Deja marcado SOLO el '
                'lote que quieres asignar.'))
        if selected:
            return selected.lot_id
        return self.lot_id

    def _pf_check_coverage(self, chosen):
        """Valida (SIN escribir) que el lote elegido sirva para la selección.

        Con ubicación efectiva: libre REAL del lote en esa ubicación. Sin ella
        (varias ubicaciones): el ``available`` AGREGADO del candidato. Bloquea
        con mensaje guía si no hay existencia o si no alcanza la demanda sumada
        (salvo que el operador confirme la parcial). D3.
        """
        self.ensure_one()
        if not chosen:
            return
        if self.location_id:
            free = self.env['stock.quant']._get_available_quantity(
                self.product_id, self.location_id, lot_id=chosen)
        else:
            candidate = self.candidate_ids.filtered(
                lambda cand: cand.lot_id == chosen)[:1]
            free = candidate.available if candidate else 0.0
        if free <= _EPS:
            raise UserError(_(
                'El lote "%s" no tiene existencia disponible para esta '
                'selección. Elige otro lote.') % chosen.name)
        demand = self.total_demand or 0.0
        if demand > _EPS and free < demand - _EPS and not self.confirm_partial:
            raise UserError(_(
                'El lote "%s" solo tiene %.2f disponible y la demanda de la '
                'selección es %.2f. Marca "Confirmo la asignación parcial" para '
                'asignar lo disponible.') % (chosen.name, free, demand))

    def _pf_split_lots(self):
        """Lotes marcados con "Incluir", EN EL ORDEN DE LA TABLA (D1/D2).

        ``candidate_ids.filtered('is_in_split')`` respeta el ``_order`` del
        candidato (``available desc, lot_name asc``) ⇒ el orden de consumo es el
        que el operador VE en la tabla. Se ignoran las filas sin ``lot_id``.

        :rtype: list[stock.lot]
        """
        self.ensure_one()
        return [
            cand.lot_id for cand in self.candidate_ids.filtered('is_in_split')
            if cand.lot_id]

    def _pf_check_split_coverage(self, lots):
        """Valida (SIN escribir) que los lotes marcados sirvan (D3).

        Con ubicación efectiva: suma la libre REAL de los lotes marcados en esa
        ubicación (una lectura por lote). Sin ella (varias ubicaciones): suma el
        ``available`` AGREGADO de los candidatos marcados (mismo aviso visible ya
        existente). Bloquea con mensaje guía si ninguno tiene existencia o si el
        total no alcanza la demanda sumada (salvo ``confirm_partial``). NO
        escribe nada: bloquea ANTES de tocar el inventario.
        """
        self.ensure_one()
        if not lots:
            raise UserError(_(
                'Marca en la tabla los lotes que quieres repartir (columna '
                '"Incluir").'))
        if self.location_id:
            free = sum(
                self.env['stock.quant']._get_available_quantity(
                    self.product_id, self.location_id, lot_id=lot)
                for lot in lots)
        else:
            free = sum(
                self.candidate_ids.filtered('is_in_split').mapped('available'))
        if free <= _EPS:
            raise UserError(_(
                'Ninguno de los lotes marcados tiene existencia disponible para '
                'esta selección. Marca lotes con Disponible.'))
        demand = self.total_demand or 0.0
        if demand > _EPS and free < demand - _EPS and not self.confirm_partial:
            raise UserError(_(
                'Los lotes marcados suman %.2f disponible y la demanda de la '
                'selección es %.2f. Marca "Confirmo la asignación parcial" para '
                'repartir lo disponible.') % (free, demand))

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
           (sin ``limit=1``), capturando el ``UserError`` POR FILA (nunca aborta
           el barrido) y clasificando el resultado (asignado/parcial/error);
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
            try:
                ProductFlow._pf_assign_lots_to_document(
                    line.kind, 'stock.move', line.move_id.id, [line.lot_id],
                    product=self.product_id)
            except UserError as err:
                line.result = 'error'
                line.result_note = str(err) or _(
                    'No se pudo asignar el lote a la unidad.')
                continue
            reserved = self._pf_line_reserved(line, line.lot_id)
            demand = line.demand_qty or 0.0
            if reserved <= _EPS:
                line.result = 'error'
                line.result_note = _(
                    'El lote no quedó reservado en la unidad.')
            elif demand > _EPS and reserved < demand - _EPS:
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

    def action_split_lot_bulk(self):
        """REPARTA varios lotes entre los destinos asignables (H-037 · modo split).

        Mismo esqueleto y mismas guardias que ``action_assign_lot_bulk`` (modo
        ``single``), pero en vez de UN lote decide con la SELECCIÓN ORDENADA de
        lotes marcados con "Incluir":

        1. guardia de permisos ``_pf_assert_can_clean`` (jefe de taller/admin);
        2. ``reason`` obligatorio y política de excepción (cero hardcodeo);
        3. validación de cobertura del plan (``_pf_check_split_coverage``,
           bloquea ANTES de escribir);
        4. por cada destino asignable (FIFO), delegar la ESCRITURA en el
           ORQUESTADOR ÚNICO del reparto ``_pf_assign_lots_to_document``
           (protocolo NATIVO ADITIVO: 1 liberación + N reservas), capturando el
           ``UserError`` POR DESTINO (nunca aborta el barrido) y marcando el
           resultado con el DESGLOSE por lote (``_pf_line_breakdown``);
        5. bitácora por documento (solo modelos con chatter) y notificación con
           los MISMOS 4 conteos, ENCADENADA al DETALLE por destino (H-029).

        Código sí, datos no: la ÚNICA escritura son las primitivas NATIVAS del
        motor disparadas por este botón; no hay ``cr.execute``/``cr.commit``.
        """
        self.ensure_one()
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        if not (self.reason or '').strip():
            raise UserError(_(
                'Debes indicar el motivo del reparto en bloque.'))
        policy = self.env['printflow.flow.lot.picker']._pf_exception_policy()
        if policy != 'warn' and not self.confirm_exception:
            raise UserError(_(
                'La política vigente exige confirmar la excepción: marca '
                '"Confirmo la excepción" para repartir los lotes.'))
        lots = self._pf_split_lots()
        if not lots:
            raise UserError(_(
                'Marca en la tabla los lotes que quieres repartir (columna '
                '"Incluir").'))
        self._pf_check_split_coverage(lots)
        ProductFlow = self.env['printflow.product.flow']
        for line in self.line_ids.filtered('assignable'):
            try:
                ProductFlow._pf_assign_lots_to_document(
                    line.kind, line.res_model, line.res_id, lots,
                    product=self.product_id)
            except UserError as err:
                line.result = 'error'
                line.result_note = str(err) or _(
                    'No se pudo repartir los lotes.')
                continue
            reserved, note = self._pf_line_breakdown(line, lots)
            demand = line.demand_qty or 0.0
            if reserved <= _EPS:
                line.result = 'error'
                line.result_note = note or _(
                    'Ningún lote del reparto quedó reservado.')
            elif demand > _EPS and reserved < demand - _EPS:
                line.result = 'partial'
                line.result_note = _('Solo se reservó lo disponible. ') + note
            else:
                line.result = 'assigned'
                line.result_note = note or _('Lotes asignados.')
            self._pf_log_split_document(line, lots, reserved)
        # H-029: mismo cierre y mismos 4 conteos; se encadena el DETALLE por
        # destino (una fila por entrega, con su desglose de reparto).
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

    def _pf_line_breakdown(self, line, lots):
        """Total reservado y DESGLOSE por lote del reparto en un destino (D5).

        Suma la cantidad de las ``stock.move.line`` del movimiento del destino
        cuyo ``lot_id`` esté entre los lotes del plan (lectura ``sudo()``) y arma
        la nota compacta: *"Reparto: 666634 → 2.00 · SN126353 → 1.00"*, con el
        aviso *"(N lotes sin existencia)"* cuando alguno no aportó. Sin ningún
        aporte ⇒ *"Ningún lote del reparto quedó reservado."*.

        :rtype: tuple[float, str]
        """
        if not line.move_id:
            return 0.0, _('Ningún lote del reparto quedó reservado.')
        lot_ids = [lot.id for lot in lots if lot]
        if not lot_ids:
            return 0.0, _('Ningún lote del reparto quedó reservado.')
        move_lines = self.env['stock.move.line'].sudo().search([
            ('move_id', '=', line.move_id.id),
            ('lot_id', 'in', lot_ids),
        ])
        per_lot = {}
        for move_line in move_lines:
            per_lot[move_line.lot_id.id] = (
                per_lot.get(move_line.lot_id.id, 0.0)
                + (move_line.quantity or 0.0))
        total = sum(per_lot.values())
        parts = []
        missing = 0
        for lot in lots:
            qty = per_lot.get(lot.id, 0.0)
            if qty > _EPS:
                parts.append('%s → %.2f' % (lot.name, qty))
            else:
                missing += 1
        if not parts:
            return total, _('Ningún lote del reparto quedó reservado.')
        note = _('Reparto: %s') % ' · '.join(parts)
        if missing:
            note += ' ' + _('(%s lotes sin existencia)') % missing
        return total, note

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

    def _pf_log_split_document(self, line, lots, reserved):
        """Registra el REPARTO en el chatter del documento (D5).

        Copia del patrón de ``_pf_log_document`` (que NO se toca): solo modelos
        con chatter (``stock.picking``/``mrp.production``); si no hay chatter, se
        omite el registro (no revienta el reparto). Lista los lotes del plan y el
        reservado REAL, con el ``reason`` común.
        """
        if line.res_model not in _CHATTER_MODELS or not line.res_id:
            return
        doc = self.env[line.res_model].sudo().browse(line.res_id).exists()
        if not doc:
            return
        doc.message_post(
            body=_('PrintFlow · Reparto de %(n)s lote(s) en bloque a %(doc)s: '
                   '%(lots)s.\nReservado: %(reserved)s\nMotivo: %(reason)s\n'
                   'Usuario: %(user)s') % {
                'n': len([lot for lot in lots if lot]),
                'doc': line.label or doc.display_name,
                'lots': ', '.join(lot.name for lot in lots if lot),
                'reserved': '%.2f' % (reserved or 0.0),
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
