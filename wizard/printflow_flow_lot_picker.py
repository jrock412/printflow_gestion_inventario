# -*- coding: utf-8 -*-
"""Selector de LOTE por documento (PrintFlow · decisión consciente).

``TransientModel`` que convierte la fila de la bandeja gestionable
(``printflow.flow.lot.tray``) en un selector POR DOCUMENTO: muestra el lote
propio, el lote actual, los lotes con existencia y deja que el operador ELIJA
uno y lo ASIGNE. NO es automático ni ciego.

Por qué existe
--------------
Los productos son PERSONALIZADOS (el lote es del cliente/venta), pero el negocio
admite excepciones legítimas (el cliente rechaza el trabajo y se revende; sobró
stock de una fabricación/compra). El operador debe poder VER la existencia por
lote, ELEGIR uno con disponibilidad y ASIGNARLO como decisión de la empresa.

Excepción consciente y auditable
--------------------------------
``is_exception`` es ``True`` cuando se elige un lote distinto al PROPIO del
documento. Si el lote propio no es determinable, el selector queda NEUTRO (no
bloquea, no miente). La política es configurable (cero hardcodeo):
``x_product_dimensional_pricing.pf_lot_assign_exception_policy`` con ``warn``
(solo aviso), ``confirm`` (exige el check) y ``confirm_reason`` (exige
confirmación + motivo, por DEFECTO). El operador SIEMPRE puede elegir; la
política solo agrega fricción y registro (``message_post`` en el chatter del
documento, o su albarán/OF; si no hay, ``_logger.info``).

Contrato::

    picker = env['printflow.flow.lot.picker']._pf_populate(
        product, target_kind, res_model, res_id,
        own_lot_name=..., sale_name=..., lot_name_actual=...)
    action = picker.action_assign_lot()   # guardia + política + escritura + bitácora

La ESCRITURA no vive aquí: el orquestador ÚNICO es
``printflow.product.flow._pf_assign_lot_to_document`` (despacho por lista blanca
y guardia ``_pf_assert_can_clean``).
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.printflow_flow_lots import (
    DEFAULT_EXCEPTION_POLICY,
    EXCEPTION_POLICY_SELECTION,
    PARAM_LOT_ASSIGN_EXCEPTION_POLICY,
)

_logger = logging.getLogger(__name__)

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

# Modelos de "documento" que el selector sabe etiquetar/localizar (lista blanca
# explícita; NUNCA ``getattr`` por convención).
_DOCUMENT_MODELS = ('stock.move', 'stock.lot', 'mrp.production', 'stock.quant')

# Modelos con chatter propio (para el registro auditable).
_CHATTER_MODELS = ('stock.picking', 'mrp.production')


class PrintflowFlowLotPicker(models.TransientModel):
    """Selector de lote de un documento concreto (bandeja gestionable)."""

    _name = 'printflow.flow.lot.picker'
    _description = 'Selector de lote por documento (PrintFlow)'

    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, readonly=True,
        ondelete='cascade')
    target_kind = fields.Char(
        string='Tipo de ítem', readonly=True,
        help='Tipo de ítem afectado (mapa/lista blanca del orquestador).')
    res_model = fields.Char(string='Modelo', readonly=True)
    res_id = fields.Integer(string='Id del registro', readonly=True)
    doc_label = fields.Char(
        string='Documento', readonly=True,
        help='Etiqueta legible del documento afectado.')
    own_lot_name = fields.Char(
        string='Lote propio', readonly=True,
        help='Lote exclusivo del documento. Vacío si NO es determinable '
             '(el selector queda neutro).')
    sale_name = fields.Char(
        string='Pedido', readonly=True,
        help='Pedido de venta del documento, si se conoce.')
    lot_name_actual = fields.Char(
        string='Lote actual', readonly=True,
        help='Lote que tiene hoy el ítem afectado.')
    location_id = fields.Many2one(
        'stock.location', string='Ubicación', readonly=True,
        help='Ubicación del documento (origen). Acota la disponibilidad real '
             'del lote para ESTA entrega.')
    demand_qty = fields.Float(
        string='Demanda', readonly=True, digits='Product Unit of Measure',
        help='Cantidad que pide el documento; con ella se decide si el lote '
             'cubre la demanda o la entrega queda parcial.')
    lot_id = fields.Many2one(
        'stock.lot', string='Lote a asignar',
        domain="[('product_id', '=', product_id), "
               "('id', 'in', candidate_lot_ids)]",
        help='Lote que el operador decide asignar al documento. Solo se ofrecen '
             'lotes con existencia EN la ubicación del documento.')
    candidate_lot_ids = fields.Many2many(
        'stock.lot', 'printflow_picker_candidate_lot_rel',
        'picker_id', 'lot_id', string='Lotes con existencia aquí',
        compute='_compute_candidate_lot_ids',
        help='Lotes con existencia libre (> 0) en la ubicación del documento: '
             'los únicos elegibles en el desplegable.')
    confirm_partial = fields.Boolean(
        string='Confirmo la asignación parcial',
        help='Autoriza asignar un lote que NO cubre toda la demanda; la entrega '
             'quedará parcialmente disponible.')
    is_exception = fields.Boolean(
        string='Es una excepción', compute='_compute_is_exception',
        help='Verdadero si el lote elegido NO es el lote propio del documento.')
    is_current_selection = fields.Boolean(
        string='Es el lote actual', compute='_compute_is_current_selection',
        help='Verdadero si el lote elegido ES el que el documento ya tiene. Con '
             'el check de autorización se declara intencional sin reasignar.')
    exception_policy = fields.Selection(
        EXCEPTION_POLICY_SELECTION, string='Política de excepción',
        compute='_compute_exception_policy', readonly=True)
    exception_reason = fields.Text(
        string='Motivo de la excepción',
        help='Justificación que exige la política ``confirm_reason``.')
    confirm_exception = fields.Boolean(
        string='Confirmo la excepción',
        help='Check que exigen las políticas ``confirm``/``confirm_reason``.')
    authorize_shared_lot = fields.Boolean(
        string='Autorizar este lote como excepción documentada',
        help='Acción EXPLÍCITA del operador: con el motivo y quién lo autoriza '
             'guardados juntos, el lote dejará de reportarse como "lotes '
             'mezclados" en el inventario. Nunca se autoriza solo.')
    # ── UX del selector: resumen del documento + ventana de corrección ───
    own_lot_id = fields.Many2one(
        'stock.lot', string='Lote propio', readonly=True,
        help='Lote propio del documento resuelto a registro (para el resumen).')
    current_lot_id = fields.Many2one(
        'stock.lot', string='Lote actual', readonly=True,
        help='Lote que el documento tiene HOY resuelto a registro.')
    own_lot_summary = fields.Char(
        string='Lote propio', compute='_compute_lot_summaries',
        help='Libre total / libre aquí / reservado del lote propio.')
    current_lot_summary = fields.Char(
        string='Lote actual', compute='_compute_lot_summaries',
        help='Libre total / libre aquí / reservado del lote actual.')
    current_lot_is_authorized = fields.Boolean(
        string='Lote actual autorizado',
        compute='_compute_current_lot_is_authorized',
        help='Verdadero si el lote ACTUAL del documento ya está autorizado como '
             'excepción documentada.')
    is_correction = fields.Boolean(
        string='Es una corrección', compute='_compute_is_correction',
        help='Verdadero si el lote elegido es DISTINTO al que el documento ya '
             'tiene: es una CORRECCIÓN, no una simple asignación.')
    can_correct = fields.Boolean(
        string='Se puede corregir', compute='_compute_correction_window',
        help='Falso si el documento ya está validado (hecho): el lote no se '
             'puede cambiar. El candado real es del servidor.')
    correction_block_reason = fields.Char(
        string='Motivo del bloqueo', compute='_compute_correction_window')
    correction_summary = fields.Char(
        string='Resumen de la corrección', compute='_compute_correction_summary',
        help='Texto "de <actual> a <nuevo>" para el aviso de corrección.')
    document_in_progress = fields.Boolean(
        string='Validación en curso', compute='_compute_correction_window',
        help='Verdadero si la validación ya empezó (movimientos "picked"): '
             'corregir exige confirmación + motivo.')
    confirm_correction = fields.Boolean(
        string='Confirmo la corrección',
        help='Cuando la validación está en curso, hay que confirmar el cambio de '
             'lote y dejar el motivo.')
    revoke_prior_authorization = fields.Boolean(
        string='Revocar la autorización del lote anterior',
        help='Si el lote ACTUAL estaba autorizado como excepción y se corrige a '
             'otro, marca esto para revocar esa autorización anterior.')
    candidate_ids = fields.One2many(
        'printflow.flow.lot.candidate', 'picker_id',
        string='Lotes con existencia')

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTOS
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('own_lot_name', 'lot_name_actual', 'lot_id')
    def _compute_is_exception(self):
        """Marca la excepción si el lote elegido NO es el esperado.

        "Esperado" = lote PROPIO del documento o, si no es determinable, el lote
        ACTUAL del ítem. Si el documento NO tenía lote (ni propio ni actual), la
        asignación es NEUTRA: no es excepción y no pide motivo (decisión 5).
        """
        for rec in self:
            expected = (rec.own_lot_name or '').strip() or (
                rec.lot_name_actual or '').strip()
            rec.is_exception = bool(
                rec.lot_id and expected and rec.lot_id.name != expected)

    @api.depends('lot_name_actual', 'lot_id')
    def _compute_is_current_selection(self):
        """Marca si el lote elegido ES el que el documento ya tiene."""
        for rec in self:
            actual = (rec.lot_name_actual or '').strip()
            rec.is_current_selection = bool(
                rec.lot_id and actual and rec.lot_id.name == actual)

    @api.depends('own_lot_id', 'current_lot_id', 'candidate_ids.lot_id',
                 'candidate_ids.qty_on_hand', 'candidate_ids.available',
                 'candidate_ids.available_here', 'candidate_ids.reserved')
    def _compute_lot_summaries(self):
        """Resumen de existencia del lote propio/actual (de sus propias filas)."""
        for rec in self:
            rec.own_lot_summary = rec._pf_candidate_summary(rec.own_lot_id)
            rec.current_lot_summary = rec._pf_candidate_summary(
                rec.current_lot_id)

    def _pf_candidate_summary(self, lot):
        """Texto de existencia de un lote: existencia · reservado · disponible."""
        if not lot:
            return _('No determinable')
        cand = self.candidate_ids.filtered(lambda c: c.lot_id == lot)[:1]
        if not cand:
            return _('Sin existencia')
        return _(
            'Existencia %(qty).2f · reservado %(res).2f · disponible %(free).2f'
        ) % {
            'qty': cand.qty_on_hand,
            'res': cand.reserved,
            'free': cand.available,
        }

    @api.depends('current_lot_id')
    def _compute_current_lot_is_authorized(self):
        """Marca si el lote ACTUAL ya está autorizado (UNA consulta)."""
        authorized = self.env['printflow.stock.health']._pf_authorized_lot_ids(
            self.mapped('current_lot_id').ids)
        for rec in self:
            rec.current_lot_is_authorized = bool(
                rec.current_lot_id and rec.current_lot_id.id in authorized)

    @api.depends('lot_id', 'lot_name_actual')
    def _compute_is_correction(self):
        """Corrección = el lote elegido NO es el que el documento ya tiene."""
        for rec in self:
            actual = (rec.lot_name_actual or '').strip()
            rec.is_correction = bool(
                rec.lot_id and actual and rec.lot_id.name != actual)

    @api.depends('res_model', 'res_id')
    def _compute_correction_window(self):
        """Lee del MOTOR si el documento admite corrección (solo lectura)."""
        for rec in self:
            doc = rec._pf_document()
            info = self.env[
                'printflow.stock.health']._pf_document_lot_editable(doc)
            rec.can_correct = info['editable']
            rec.correction_block_reason = info['reason']
            rec.document_in_progress = info['in_progress']

    @api.depends('lot_id', 'lot_name_actual')
    def _compute_correction_summary(self):
        """Texto "de <actual> a <nuevo>" (vacío si no es corrección)."""
        for rec in self:
            if rec.is_correction:
                rec.correction_summary = _('de "%(from)s" a "%(to)s"') % {
                    'from': rec.lot_name_actual or '',
                    'to': rec.lot_id.name or '',
                }
            else:
                rec.correction_summary = ''

    @api.depends('candidate_ids.available_here', 'candidate_ids.lot_id')
    def _compute_candidate_lot_ids(self):
        """Lotes candidatos con existencia EN la ubicación del documento (> 0).

        Alimenta el dominio del desplegable "Lote a asignar": solo se ofrecen
        lotes que sirven para ESTA entrega (no los que solo tienen stock en otra
        ubicación).
        """
        for rec in self:
            rec.candidate_lot_ids = rec.candidate_ids.filtered(
                lambda cand: cand.available_here > _EPS).mapped('lot_id')

    @api.depends()
    def _compute_exception_policy(self):
        """Política vigente leída del parámetro (cero hardcodeo)."""
        policy = self._pf_exception_policy()
        for rec in self:
            rec.exception_policy = policy

    @api.model
    def _pf_exception_policy(self):
        """Política configurada de asignación por excepción (default configurable)."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_LOT_ASSIGN_EXCEPTION_POLICY, DEFAULT_EXCEPTION_POLICY)
        value = (raw or '').strip()
        allowed = {key for key, _label in EXCEPTION_POLICY_SELECTION}
        return value if value in allowed else DEFAULT_EXCEPTION_POLICY

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, product, target_kind, res_model, res_id,
                     own_lot_name=None, sale_name=None, lot_name_actual=None,
                     location_id=None, demand_qty=None, current_lot_id=None):
        """Crea el selector con los datos del documento y sus candidatos.

        Puebla los candidatos con ``printflow.flow.lots._pf_available_lots``
        (UNA sola lectura de ``stock.quant``) y marca ``is_own_lot`` en la línea
        del lote propio. El lote PROPIO y el ACTUAL se FUERZAN a la tabla con
        ``include_lot_ids`` (aunque tengan 0 existencia) para que el operador
        SIEMPRE los vea en el resumen y en la lista. Devuelve el registro
        transitorio (lo abre el llamador).

        :param product: ``product.product`` del documento.
        :param str target_kind: tipo de ítem (lista blanca del orquestador).
        :param str res_model: modelo del documento.
        :param int res_id: id del documento.
        :param str own_lot_name: lote propio (vacío = no determinable).
        :param str sale_name: nombre del pedido (opcional).
        :param str lot_name_actual: lote que tiene hoy el ítem.
        :param location_id: ubicación del documento (id) para el aviso de
            disponibilidad (Hueco 3).
        :param float demand_qty: demanda del documento.
        :param current_lot_id: lote ACTUAL del documento (registro o id); si no
            llega, se resuelve por ``lot_name_actual``.
        :rtype: models.Model
        """
        product = product.exists() if product else self.env['product.product']
        if not product:
            return self.browse()
        own = (own_lot_name or '').strip()
        actual_name = (lot_name_actual or '').strip()
        own_lot = self._pf_lot_by_name(product, own)
        current_lot = self._pf_resolve_lot(current_lot_id)
        if not current_lot and actual_name:
            current_lot = self._pf_lot_by_name(product, actual_name)
        if location_id and hasattr(location_id, 'id'):
            location_ident = location_id.id or False
        else:
            location_ident = location_id or False
        demand = demand_qty or 0.0
        candidates = self.env['printflow.flow.lots']._pf_available_lots(
            product, location_id=location_ident, demand_qty=demand,
            include_lot_ids=[own_lot.id, current_lot.id])
        cand_vals = []
        for cand in candidates:
            cand_vals.append((0, 0, {
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
                'is_own_lot': bool(own_lot) and cand['lot_id'] == own_lot.id,
            }))
        return self.create({
            'product_id': product.id,
            'target_kind': target_kind or '',
            'res_model': res_model or '',
            'res_id': res_id or 0,
            'doc_label': self._pf_doc_label(res_model, res_id),
            'own_lot_name': own,
            'own_lot_id': own_lot.id or False,
            'sale_name': sale_name or '',
            'lot_name_actual': lot_name_actual or '',
            'current_lot_id': current_lot.id or False,
            'location_id': location_ident,
            'demand_qty': demand,
            'candidate_ids': cand_vals,
        })

    @api.model
    def _pf_lot_by_name(self, product, name):
        """``stock.lot`` del producto por nombre (o recordset vacío)."""
        if not product or not name:
            return self.env['stock.lot']
        return self.env['stock.lot'].sudo().search([
            ('product_id', '=', product.id),
            ('name', '=', name),
        ], limit=1)

    @api.model
    def _pf_resolve_lot(self, value):
        """Resuelve un lote desde un registro, id o ``False``."""
        if not value:
            return self.env['stock.lot']
        if hasattr(value, 'id'):
            return value if value.id else self.env['stock.lot']
        return self.env['stock.lot'].sudo().browse(int(value)).exists()

    # ══════════════════════════════════════════════════════════════════════
    # ACCIÓN PRINCIPAL
    # ══════════════════════════════════════════════════════════════════════
    def _pf_selected_lot(self):
        """Lote elegido por el operador (fila marcada, o el desplegable).

        La tabla es la fuente principal: devuelve el lote de la fila con
        ``is_selected``; si no hay ninguna marcada, cae al ``lot_id`` del
        desplegable. Exige selección ÚNICA (defensa: aunque el modelo ya
        desmarca hermanas, un dato cargado por fuera podría dejar dos marcas).

        :rtype: stock.lot
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

    def action_assign_lot(self):
        """Asigna el lote ELEGIDO al documento (guardia + política + bitácora).

        Pasa por el guardia de permisos ``_pf_assert_can_clean`` (jefe de
        taller/admin), resuelve el lote desde la SELECCIÓN (check de la tabla;
        respaldo al desplegable), valida la política de excepción, delega la
        ESCRITURA en ``printflow.product.flow._pf_assign_lot_to_document`` y
        registra el hecho en el chatter del documento. Devuelve
        ``display_notification``.
        """
        self.ensure_one()
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        chosen = self._pf_selected_lot()
        if not chosen:
            raise UserError(_(
                'Elige un lote con existencia antes de asignarlo: marca la '
                'casilla de la fila en la tabla ("Elegir") o usa el '
                'desplegable "Lote a asignar".'))
        # Espejo: deja el desplegable y el resto de la lógica (política de
        # excepción, bitácora) coherentes con la fila marcada.
        self.lot_id = chosen
        # (1)(2) VENTANA de corrección: si el lote elegido es DISTINTO al actual,
        # es una corrección y el documento debe admitirla (abierto). Si la
        # validación está en curso (picked), exige confirmación + motivo.
        self._pf_check_correction_window()
        # Vía SOLO-AUTORIZAR: el lote elegido ES el que el documento ya tiene y
        # el operador marcó el check -> NO se reasigna: solo se autoriza la
        # asignación ACTUAL como excepción documentada (motivo + autorizador).
        if self.authorize_shared_lot and self._pf_is_current_lot(chosen):
            self._pf_check_authorization()
            self.env['printflow.stock.health']._pf_authorize_lot_exception(
                self.lot_id,
                reason=self.exception_reason,
                source_model=self.res_model,
                source_id=self.res_id,
                source_label=self.doc_label)
            self._pf_log_assignment(self._pf_chatter_target(), assigned=False)
            return self._pf_assign_notification(_(
                'Lote "%s" autorizado como excepción documentada.') % (
                    chosen.name))
        # Vía REASIGNAR (comportamiento histórico + autorización opcional).
        self._pf_check_availability(chosen)
        self._pf_check_exception_policy()
        self._pf_check_authorization()
        # El chatter se resuelve ANTES de escribir: tras la reasignación, el
        # vínculo con el lote anterior puede desaparecer.
        chatter = self._pf_chatter_target()
        message = self.env[
            'printflow.product.flow']._pf_assign_lot_to_document(
                self.target_kind, self.res_model, self.res_id, self.lot_id,
                product=self.product_id)
        # (3) Revocar la autorización del lote ANTERIOR si el operador lo pidió
        # (el lote actual estaba autorizado y se está corrigiendo a otro).
        revoked = False
        if self.revoke_prior_authorization and self.current_lot_id:
            revoked = self.env[
                'printflow.stock.health']._pf_revoke_lot_exception(
                    self.current_lot_id)
        # Autorización PERSISTENTE (excepción documentada): SOLO si el operador
        # la marcó explícitamente y tras escribir con éxito el lote. Deja el
        # motivo + autorizador guardados juntos; el detector de mezcla deja de
        # reportar el lote.
        if self.is_exception and self.authorize_shared_lot:
            self.env['printflow.stock.health']._pf_authorize_lot_exception(
                self.lot_id,
                reason=self.exception_reason,
                source_model=self.res_model,
                source_id=self.res_id,
                source_label=self.doc_label)
        self._pf_log_assignment(chatter, revoked=revoked)
        return self._pf_assign_notification(message)

    def _pf_check_correction_window(self):
        """Bloquea/exige fricción si la asignación es una CORRECCIÓN.

        * Documento validado (``can_correct`` False) -> ``UserError`` guía.
        * Validación en curso (``picked``) -> exige ``confirm_correction`` + motivo.
        """
        self.ensure_one()
        if not self.is_correction:
            return
        if not self.can_correct:
            raise UserError(self.correction_block_reason or _(
                'No se puede corregir el lote de este documento.'))
        if self.document_in_progress:
            if not self.confirm_correction:
                raise UserError(_(
                    'La validación de este documento ya comenzó: marca '
                    '"Confirmo la corrección" para cambiar el lote.'))
            if not (self.exception_reason or '').strip():
                raise UserError(_(
                    'Indica el motivo de la corrección del lote.'))

    def _pf_is_current_lot(self, chosen):
        """True si ``chosen`` ES el lote que el documento ya tiene."""
        if not chosen:
            return False
        actual = (self.lot_name_actual or '').strip()
        return bool(actual and chosen.name == actual)

    def _pf_assign_notification(self, message):
        """Notificación estándar de resultado de la asignación/autorización."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('PrintFlow'),
                'message': message,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ══════════════════════════════════════════════════════════════════════
    # AVISO DE DISPONIBILIDAD (Hueco 3)
    # ══════════════════════════════════════════════════════════════════════
    def _pf_check_availability(self, chosen):
        """Valida la disponibilidad REAL del lote elegido en la ubicación.

        Con la semántica aprobada: "lote con existencia" = libre > 0 en la
        ubicación del documento. NO exige cubrir toda la demanda:
          * si el lote elegido es el que el documento YA tiene -> avisa "no
            cambió" (nada que reasignar);
          * si la libre en la ubicación es 0 (o menos) -> ``UserError`` (bloqueo);
          * si ``0 < libre < demanda`` y no se marcó ``confirm_partial`` ->
            ``UserError`` pidiendo el check (la entrega quedaría parcial);
          * si alcanza la demanda -> sigue.
        Sin ``location_id`` (p. ej. MO) la comprobación no aplica: se conserva el
        comportamiento del documento.
        """
        self.ensure_one()
        if not chosen:
            return
        # GUARDIA de RESERVA NEGATIVA: un lote con un quant de reserva negativa
        # es inventario fantasma; NUNCA se ofrece ni se acepta. Debe corregirse
        # con "Corrección automática" antes de asignarlo.
        negative = self.env['stock.quant'].sudo().search_count([
            ('product_id', '=', self.product_id.id),
            ('lot_id', '=', chosen.id),
            ('location_id.usage', 'in', ('internal', 'transit')),
            ('reserved_quantity', '<', -_EPS),
        ])
        if negative:
            raise UserError(_(
                'El lote "%s" tiene una reserva NEGATIVA (inventario fantasma): '
                'no se puede asignar. Corrígelo primero con "Corrección '
                'automática" en la bandeja de lote.') % chosen.name)
        actual = (self.lot_name_actual or '').strip()
        if actual and chosen.name == actual and not self.authorize_shared_lot:
            raise UserError(_(
                'El lote "%s" es el que el documento ya tiene: no hay cambios '
                'que aplicar.') % chosen.name)
        if not self.location_id:
            return
        product = self.product_id
        free_here = self.env['stock.quant']._get_available_quantity(
            product, self.location_id, lot_id=chosen)
        if free_here <= _EPS:
            raise UserError(_(
                'El lote "%s" no tiene existencia disponible en la ubicación '
                'del documento (%s). Elige un lote con existencia allí.') % (
                    chosen.name, self.location_id.display_name))
        demand = self.demand_qty or 0.0
        if demand > _EPS and free_here < demand - _EPS and not self.confirm_partial:
            raise UserError(_(
                'El lote "%s" solo tiene %.2f disponible en la ubicación del '
                'documento y la demanda es %.2f. Marca "Confirmo la asignación '
                'parcial" para asignar lo disponible (la entrega quedará '
                'parcial).') % (chosen.name, free_here, demand))

    # ══════════════════════════════════════════════════════════════════════
    # POLÍTICA DE EXCEPCIÓN
    # ══════════════════════════════════════════════════════════════════════
    def _pf_check_exception_policy(self):
        """Aplica la fricción configurada cuando el lote elegido NO es el propio."""
        self.ensure_one()
        if not self.is_exception:
            return
        policy = self.exception_policy or DEFAULT_EXCEPTION_POLICY
        if policy == 'warn':
            return
        if not self.confirm_exception:
            raise UserError(_(
                'Para asignar un lote que no es el del documento debes marcar '
                '"Confirmo la excepción".'))
        if policy == 'confirm_reason' and not (
                self.exception_reason or '').strip():
            raise UserError(_(
                'Para asignar un lote que no es el del documento debes indicar '
                'el motivo de la excepción.'))

    def _pf_check_authorization(self):
        """La autorización explícita de lote compartido exige su motivo.

        Un check sin motivo no deja una excepción AUDITABLE: el negocio pide
        "el motivo y quién autoriza guardados juntos". Bloquea antes de escribir.
        """
        self.ensure_one()
        if self.authorize_shared_lot and not (
                self.exception_reason or '').strip():
            raise UserError(_(
                'Para autorizar este lote como excepción documentada debes '
                'indicar el motivo (queda guardado junto con quién lo autoriza).'))

    # ══════════════════════════════════════════════════════════════════════
    # BITÁCORA AUDITABLE
    # ══════════════════════════════════════════════════════════════════════
    def _pf_log_assignment(self, chatter=None, assigned=True, revoked=False):
        """Registra lote anterior/nuevo, lote propio, motivo y usuario.

        Si el documento (o su albarán/OF) tiene chatter, publica ahí; si no,
        deja constancia en el log. Nunca revienta la asignación por no poder
        registrar. ``assigned=False`` se usa cuando SOLO se autorizó el lote
        actual (no hubo reasignación); ``revoked`` marca si se revocó la
        autorización del lote anterior.
        """
        self.ensure_one()
        expected = (self.own_lot_name or '').strip() or (
            self.lot_name_actual or '').strip()
        title = _(
            'PrintFlow · Lote reasignado (decisión del operador)') if assigned \
            else _('PrintFlow · Lote autorizado (decisión del operador)')
        body = _(
            '%s\n'
            'Lote anterior: %s\nLote nuevo: %s\nLote propio: %s\n'
            'Lote esperado: %s\nEs excepción: %s\n¿Corrección?: %s\n'
            'Motivo: %s\nAutorizado como excepción de lote compartido: %s\n'
            'Autorización anterior revocada: %s\nUsuario: %s'
        ) % (
            title,
            self.lot_name_actual or _('(sin lote)'),
            self.lot_id.name or '',
            self.own_lot_name or _('(no determinable)'),
            expected or _('(no determinable)'),
            _('Sí') if self.is_exception else _('No'),
            _('Sí') if self.is_correction else _('No'),
            (self.exception_reason or '').strip() or _('(sin motivo)'),
            _('Sí') if self.authorize_shared_lot else _('No'),
            _('Sí') if revoked else _('No'),
            self.env.user.display_name or '',
        )
        target = chatter if chatter is not None else self._pf_chatter_target()
        if target:
            target.message_post(
                body=body, message_type='notification',
                subtype_xmlid='mail.mt_note')
        else:
            _logger.info('PrintFlow (sin chatter para registrar): %s', body)

    def _pf_chatter_target(self):
        """Registro con chatter donde publicar el hecho (o ``False``)."""
        self.ensure_one()
        doc = self._pf_document()
        if doc and doc._name in _CHATTER_MODELS:
            return doc
        if doc and doc._name == 'stock.move':
            return (doc.picking_id or doc.raw_material_production_id
                    or doc.production_id or False)
        if doc and doc._name == 'stock.lot':
            line = self.env['stock.move.line'].sudo().search([
                ('product_id', '=', self.product_id.id),
                ('lot_id', '=', doc.id),
                ('state', 'not in', ('done', 'cancel')),
            ], limit=1)
            if line:
                return (line.picking_id
                        or line.move_id.raw_material_production_id
                        or line.move_id.production_id or False)
        return False

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS DEL DOCUMENTO
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_document(self, res_model=None, res_id=None):
        """Registro del documento de la fila (lista blanca) o recordset vacío."""
        model = res_model if res_model is not None else self.res_model
        ident = res_id if res_id is not None else self.res_id
        if not model or not ident or model not in _DOCUMENT_MODELS:
            return self.env['stock.move']
        return self.env[model].sudo().browse(ident).exists()

    @api.model
    def _pf_doc_label(self, res_model, res_id):
        """Etiqueta legible del documento (o vacío si no se puede resolver)."""
        doc = self._pf_document(res_model, res_id)
        return doc.display_name if doc else ''
