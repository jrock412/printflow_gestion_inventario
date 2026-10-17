# -*- coding: utf-8 -*-
"""Asignación EN BLOQUE de UN lote a N entregas sin lote (PrintFlow).

``TransientModel`` CONTENEDOR que convierte la SELECCIÓN de la bandeja de lote
(``printflow.flow.lot.tray``) en una decisión masiva: el operador marca N filas
de entrega sin lote, pulsa el botón de cabecera "Asignar lote" y este wizard
pregunta UN lote (con la tabla de candidatos: Lote · Existencia · Reservado ·
Disponible · Rol) y UN motivo, y asigna ese lote a TODOS los destinos.

Por qué un wizard NUEVO y no reutilizar el selector
---------------------------------------------------
El selector por documento (``printflow.flow.lot.picker``) está amarrado a UN
documento por diseño (``picker_id`` obligatorio, demanda única, política de
excepción por documento) y está cubierto por tests. Forzarlo a "varios
documentos" ensuciaría su contrato. Este contenedor es más simple y limpio: N
destinos (``line_ids``) + UN lote + UN motivo.

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
    action = bulk.action_assign_lot_bulk()
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
        string='Entregas omitidas', readonly=True,
        help='Filas seleccionadas (ENTREGAS) que NO se asignan (no asignables, '
             'sin movimiento, duplicadas o no elegibles).')
    assignable_count = fields.Integer(
        string='Entregas por asignar', compute='_compute_assignable_count',
        help='Número de destinos (ENTREGAS = albaranes de salida) que SÍ '
             'admiten la asignación en bloque. Es una cuenta de FILAS, no de '
             'unidades.')
    selection_note = fields.Char(
        string='Resumen de la selección',
        compute='_compute_selection_note', readonly=True,
        help='Texto VISIBLE que declara la UNIDAD de cada ranura: cada fila es '
             'una ENTREGA (albarán de salida); las cifras de demanda van en '
             'UNIDADES de producto (H-031).')

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
        """Texto VISIBLE que declara la UNIDAD de cada ranura (H-031).

        Aclara que cada fila es una ENTREGA (albarán de salida) y que la demanda
        va en UNIDADES de producto: N entregas por asignar = M unidades. Así el
        operador no lee "26 vs 30" como una contradicción. Sin sufijos de unidad
        en los campos: la palabra "unidades" va en la oración (D3).
        """
        for rec in self:
            rec.selection_note = _(
                'Cada fila es una entrega (albarán de salida). %(n)s entregas '
                'por asignar = %(m)s unidades a entregar.') % {
                'n': rec.assignable_count or 0,
                'm': '%.2f' % (rec.total_demand or 0.0),
            }

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
        :param int omitted_count: filas ya descartadas por el llamador (tray).
        :rtype: models.Model
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
        line_vals = [(0, 0, {
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
        }) for seq, row in enumerate(prepared, start=1)]
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
        (D2/D6), DEDUPLICA por ``move_id`` (D5: ``missing_move`` y
        ``pending_order`` pueden apuntar al MISMO albarán) y ordena FIFO por
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
        # (2) UNA lectura batch: ubicación/fecha de los movimientos resueltos.
        move_ids = {item['move_id'] for item in raw if item['move_id']}
        move_info = {}
        if move_ids:
            for data in Move.browse(list(move_ids)).read(
                    ['location_id', 'date', 'picking_id']):
                move_info[data['id']] = data
        picking_for_date = set()
        for item in raw:
            info = move_info.get(item['move_id']) or {}
            loc_ref = info.get('location_id') or False
            item['_move_location'] = (loc_ref[0] if loc_ref else 0) or 0
            item['_move_date'] = info.get('date') or False
            pick_ref = info.get('picking_id') or False
            item['_move_picking'] = (pick_ref[0] if pick_ref else 0) or 0
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

    def action_assign_lot_bulk(self):
        """Asigna el lote ELEGIDO a los destinos asignables (guardia + motivo).

        Pasos (D3/D8):
        1. guardia de permisos ``_pf_assert_can_clean`` (jefe de taller/admin);
        2. ``reason`` obligatorio y política de excepción (cero hardcodeo);
        3. validación de cobertura (bloquea ANTES de escribir);
        4. por cada destino asignable (FIFO), delegar la ESCRITURA en el
           ORQUESTADOR ÚNICO ``_pf_assign_lot_to_document`` (protocolo NATIVO de
           reserva), capturando el ``UserError`` POR DESTINO (nunca aborta el
           barrido) y marcando el resultado (asignado/parcial/error);
        5. bitácora por documento (solo modelos con chatter) y notificación con
           los conteos (CA-7), ENCADENADA al DETALLE por destino (H-029).
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
                '"Confirmo la excepción" para asignar el lote a la selección.'))
        chosen = self._pf_selected_lot()
        if not chosen:
            raise UserError(_(
                'Elige un lote con existencia antes de asignarlo: marca la '
                'casilla de la fila en la tabla ("Elegir") o usa el '
                'desplegable "Lote a asignar".'))
        self.lot_id = chosen
        self._pf_check_coverage(chosen)
        ProductFlow = self.env['printflow.product.flow']
        for line in self.line_ids.filtered('assignable'):
            try:
                ProductFlow._pf_assign_lot_to_document(
                    line.kind, line.res_model, line.res_id, chosen,
                    product=self.product_id)
            except UserError as err:
                line.result = 'error'
                line.result_note = str(err) or _(
                    'No se pudo asignar el lote.')
                continue
            reserved = self._pf_line_reserved(line, chosen)
            demand = line.demand_qty or 0.0
            if reserved <= _EPS:
                line.result = 'error'
                line.result_note = _(
                    'El lote no quedó reservado en el documento.')
            elif demand > _EPS and reserved < demand - _EPS:
                line.result = 'partial'
                line.result_note = _('Solo se reservó lo disponible.')
            else:
                line.result = 'assigned'
                line.result_note = _('Lote asignado.')
            self._pf_log_document(line, chosen)
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
