# -*- coding: utf-8 -*-
"""Lote CANDIDATO del selector de lote por documento (PrintFlow).

``TransientModel`` que representa UNA línea del selector
(``printflow.flow.lot.picker``): un lote del producto con su existencia interna
disponible, su reservado, las ubicaciones donde vive y si es genérico o el lote
propio del documento. El operador ve la disponibilidad real y decide qué lote
asignar marcando el check ``is_selected`` de la fila (selección ÚNICA); la
escritura final la dispara el selector.

Por qué existe
--------------
El negocio pide que la elección de lote sea CONSCIENTE (ver existencia, elegir,
asignar), no ciega. Esta fila es la evidencia que se muestra antes de decidir.
Los valores los puebla el selector en UNA sola lectura de ``stock.quant``
(``printflow.flow.lots._pf_available_lots``), sin N+1.

La MISMA fila se reutiliza en la asignación EN BLOQUE
(``printflow.flow.lot.assign.bulk``): en vez de colgar del selector por
documento (``picker_id``), cuelga del contenedor en bloque (``bulk_id``). El
"padre" por documento sigue siendo ``picker_id`` (el único que espeja y desmarca
la selección ÚNICA).

La fila sirve a DOS superficies: el selector por documento (decisión con
``is_selected``, selección ÚNICA) y la tabla **INFORMATIVA** del contenedor en
bloque (Lote · Existencia · Reservado · Disponible · Rol: allí NO se marca nada,
la decisión se toma en cada unidad del contenedor).

Contrato::

    picker = env['printflow.flow.lot.picker']._pf_populate(product, ...)
    for cand in picker.candidate_ids:
        cand.lot_name, cand.available, cand.is_own_lot
    cand.is_selected = True   # elige esta fila (desmarca las demás)
"""

from odoo import _, api, fields, models

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6


class PrintflowFlowLotCandidate(models.TransientModel):
    """Un lote candidato (con existencia) dentro del selector de lote."""

    _name = 'printflow.flow.lot.candidate'
    _description = 'Lote candidato del selector de lote (PrintFlow)'
    _order = 'available desc, lot_name asc'

    picker_id = fields.Many2one(
        'printflow.flow.lot.picker', string='Selector',
        ondelete='cascade', help='Selector al que pertenece este candidato.')
    bulk_id = fields.Many2one(
        'printflow.flow.lot.assign.bulk', string='Asignación en bloque',
        ondelete='cascade', index=True,
        help='Asignación en bloque a la que pertenece este candidato. Es la '
             'ALTERNATIVA al selector por documento: un candidato cuelga de UNO '
             'u OTRO padre, nunca de ambos.')
    lot_id = fields.Many2one(
        'stock.lot', string='Lote', required=True, ondelete='cascade')
    lot_name = fields.Char(
        string='Lote', readonly=True,
        help='Nombre del lote (copiado de ``stock.lot.name``).')
    qty_on_hand = fields.Float(
        string='Existencia', readonly=True, digits='Product Unit of Measure',
        help='Cantidad FÍSICA total del lote (suma de quants internos).')
    available = fields.Float(
        string='Disponible', readonly=True, digits='Product Unit of Measure',
        help='Existencia interna disponible: cantidad menos reservado.')
    available_here = fields.Float(
        string='Disponible aquí', readonly=True,
        digits='Product Unit of Measure',
        help='Existencia interna libre SOLO en la ubicación del documento (y su '
             'subárbol). Es la cifra que decide si el lote sirve para ESTA '
             'entrega.')
    covers_demand = fields.Boolean(
        string='Cubre la demanda', readonly=True,
        help='Verdadero si la libre en la ubicación del documento alcanza la '
             'demanda pedida. Si no, la asignación queda parcial.')
    reserved = fields.Float(
        string='Reservado', readonly=True, digits='Product Unit of Measure',
        help='Cantidad reservada del lote (acotada a >= 0: sin negativos).')
    location_names = fields.Char(
        string='Ubicaciones', readonly=True,
        help='Ubicaciones internas donde vive el lote.')
    is_generic = fields.Boolean(
        string='Genérico', readonly=True,
        help='Lote no exclusivo según el criterio único del motor.')
    is_occupied = fields.Boolean(
        string='Ocupado', readonly=True,
        help='Lote con libre 0 pero con reserva de OTROS: se muestra para '
             'informar quién lo retiene, pero NO es elegible todavía.')
    holder_names = fields.Char(
        string='Lo retiene', readonly=True,
        help='Documentos/pedidos que hoy reservan este lote.')
    is_own_lot = fields.Boolean(
        string='Lote propio', readonly=True,
        help='Marca el lote propio del documento (el exclusivo del pedido).')
    is_selected = fields.Boolean(
        string='Elegir',
        help='Marca ESTA fila como el lote que el operador decide asignar en el '
             'selector POR DOCUMENTO. La selección es ÚNICA: al marcar una fila '
             'se desmarcan las demás y se espeja en el campo "Lote a asignar" del '
             'selector.')
    is_picked = fields.Boolean(
        string='Elegido', compute='_compute_is_picked',
        help='Resaltado SOLO en el candidato marcado (espejo de la selección).')
    # ── Señales de EXPERIENCIA (UX del selector) ─────────────────────────
    is_current_lot = fields.Boolean(
        string='Lote actual', compute='_compute_is_current_lot',
        help='Verdadero si ESTE lote es el que el documento ya tiene.')
    is_authorized = fields.Boolean(
        string='Autorizado', compute='_compute_is_authorized',
        help='Verdadero si el lote ya está autorizado como excepción '
             'documentada.')
    is_elective = fields.Boolean(
        string='Elegible', compute='_compute_is_elective',
        help='Verdadero si el lote tiene existencia libre EN la ubicación del '
             'documento (> 0): solo estos se pueden marcar/asignar.')
    is_recommended = fields.Boolean(
        string='Sugerido', compute='_compute_is_recommended',
        help='Sugerencia del selector: a lo sumo UNA fila por documento (el lote '
             'propio si cubre la demanda; si no, el de mayor libre que cubra; si '
             'ninguno cubre, el de mayor libre).')
    hint = fields.Char(
        string='Señal', compute='_compute_hint',
        help='Pista corta sobre la fila: Tu lote / Lote actual / Ocupado / '
             'Genérico.')
    role_label = fields.Char(
        string='Rol', compute='_compute_role_label',
        help='Rol del lote en el documento: "Lote original del pedido" o '
             '"Lote que está usando". Vacío para el resto.')

    # ══════════════════════════════════════════════════════════════════════
    # PADRE POR DOCUMENTO (el único que espeja la selección; el bloque es
    # informativo) + demanda del padre (para la sugerencia)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_parent_demand(self, parent):
        """Demanda del padre (para la sugerencia): ``picker.demand_qty`` o
        ``bulk.total_demand``. Sin padre -> 0.0."""
        if not parent:
            return 0.0
        if parent._name == 'printflow.flow.lot.picker':
            return parent.demand_qty or 0.0
        if parent._name == 'printflow.flow.lot.assign.bulk':
            return parent.total_demand or 0.0
        return 0.0

    # ══════════════════════════════════════════════════════════════════════
    # SELECCIÓN DESDE LA TABLA (check de fila, selección ÚNICA)
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('picker_id.lot_id', 'lot_id')
    def _compute_is_picked(self):
        """Marca el candidato cuyo lote es el ELEGIDO en el selector."""
        for rec in self:
            chosen = rec.picker_id.lot_id
            rec.is_picked = bool(chosen and chosen == rec.lot_id)

    @api.depends('picker_id.lot_name_actual', 'lot_name')
    def _compute_is_current_lot(self):
        """Marca el candidato que ES el lote actual del documento."""
        for rec in self:
            actual = (rec.picker_id.lot_name_actual or '').strip() \
                if rec.picker_id else ''
            rec.is_current_lot = bool(actual and rec.lot_name == actual)

    @api.depends('lot_id')
    def _compute_is_authorized(self):
        """Marca los candidatos cuyo lote ya está autorizado (UNA consulta)."""
        authorized = self.env['printflow.stock.health']._pf_authorized_lot_ids(
            self.mapped('lot_id').ids)
        for rec in self:
            rec.is_authorized = bool(
                rec.lot_id and rec.lot_id.id in authorized)

    @api.depends('available_here')
    def _compute_is_elective(self):
        """Elegible = tiene libre EN la ubicación del documento (> 0)."""
        for rec in self:
            rec.is_elective = rec.available_here > _EPS

    @api.depends('is_own_lot', 'is_current_lot', 'is_occupied', 'is_generic',
                 'available_here')
    def _compute_hint(self):
        """Pista corta (una sola por fila, en orden de prioridad)."""
        for rec in self:
            if rec.is_own_lot:
                rec.hint = _('Tu lote') if rec.available_here > _EPS else _(
                    'Tu lote (sin existencia)')
            elif rec.is_current_lot:
                rec.hint = _('Lote actual')
            elif rec.is_occupied:
                rec.hint = _('Ocupado por otro pedido')
            elif rec.is_generic:
                rec.hint = _('Genérico')
            else:
                rec.hint = ''

    @api.depends('is_own_lot', 'is_current_lot')
    def _compute_role_label(self):
        """Rol legible de la fila (Original del pedido / En uso / vacío)."""
        for rec in self:
            if rec.is_own_lot:
                rec.role_label = _('Lote original del pedido')
            elif rec.is_current_lot:
                rec.role_label = _('Lote que está usando')
            else:
                rec.role_label = ''

    @api.depends('available_here', 'is_own_lot', 'picker_id.demand_qty',
                 'bulk_id.total_demand')
    def _compute_is_recommended(self):
        """Sugerencia: a lo sumo UNA fila por PADRE (documento o bloque).

        * el lote propio si cubre la demanda (> 0);
        * si no, el de mayor ``available_here`` que cubra;
        * si ninguno cubre, el de mayor ``available_here``.

        La demanda sale del padre: ``picker_id.demand_qty`` (documento) o
        ``bulk_id.total_demand`` (bloque). Sin padre no se sugiere nada. Los
        padres se agrupan POR MODELO (un candidato cuelga de UNO u OTRO, nunca
        de ambos): mezclar el selector y el bloque en un mismo recordset es
        inválido en el ORM.
        """
        self.is_recommended = False
        for parent in self.mapped('picker_id'):
            self._pf_recommend_for_parent(
                parent, self.filtered(lambda cand: cand.picker_id == parent))
        for parent in self.mapped('bulk_id'):
            self._pf_recommend_for_parent(
                parent, self.filtered(lambda cand: cand.bulk_id == parent))

    def _pf_recommend_for_parent(self, parent, cands):
        """Marca la fila sugerida de UN padre (a lo sumo UNA).

        :param parent: selector por documento o asignación en bloque.
        :param models.Model cands: candidatos de ESE padre.
        """
        if not cands:
            return
        demand = self._pf_parent_demand(parent)
        own = cands.filtered('is_own_lot')[:1]
        best = False
        if own and demand > _EPS and own.available_here >= demand - _EPS:
            best = own
        else:
            covering = cands.filtered(
                lambda cand: demand > _EPS
                and cand.available_here >= demand - _EPS)
            pool = covering or cands
            best = pool.sorted(
                key=lambda cand: cand.available_here, reverse=True)[:1]
        if best:
            best.is_recommended = True

    def write(self, vals):
        """Persiste el check y mantiene la selección ÚNICA tras cada escritura.

        El checkbox del tree editable escribe ``is_selected`` aquí; tras guardar
        desmarcamos las filas hermanas y espejamos el lote elegido en
        ``picker_id.lot_id`` (lo que usan la política de excepción y la bitácora).
        """
        res = super().write(vals)
        if 'is_selected' in vals:
            self._pf_enforce_single_selection()
        return res

    def _pf_enforce_single_selection(self):
        """Deja SOLO la última fila marcada y espeja el lote en el selector.

        Se ejecuta por cada fila tocada: si la fila queda marcada, desmarca sus
        hermanas del MISMO selector por documento y copia su lote a su
        ``lot_id``; si queda desmarcada, limpia el espejo solo si apuntaba a su
        lote. El contenedor en bloque NO espeja nada: su tabla de candidatos es
        INFORMATIVA (la decisión se toma en cada unidad).
        """
        for rec in self:
            parent = rec.picker_id
            if not parent:
                continue
            if rec.is_selected:
                siblings = (parent.candidate_ids - rec).filtered(
                    'is_selected')
                if siblings:
                    siblings.write({'is_selected': False})
                parent.lot_id = rec.lot_id
            elif parent.lot_id == rec.lot_id:
                parent.lot_id = False
