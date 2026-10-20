# -*- coding: utf-8 -*-
"""Bandeja gestionable de LOTE del diagrama de PRODUCTO (PrintFlow).

``TransientModel`` de LECTURA que convierte el "Solucionar" de un hallazgo de
lote en una decisión GESTIONABLE: en vez de un one-click ciego, lista UNA fila
por ítem afectado (lote sin existencia, movimiento sin lote, quant con reserva
huérfana, lote genérico, lote mezclado o MO terminada sin lote) y ofrece DOS
vías de corrección:

* POR FILA, "Elegir lote" (``action_open_lot_picker``): abre el selector
  ``printflow.flow.lot.picker`` para que el operador VEA la existencia por lote,
  ELIJA uno con disponibilidad y lo ASIGNE (decisión consciente). NO aplica a la
  reserva huérfana (``orphan_quant``), que no admite elección de lote.
* DE CABECERA, "Corrección automática" (``action_apply_correction``): el remedio
  del motor sobre la SELECCIÓN. Es la opción automática SECUNDARIA (necesaria
  para ``lot_orphan_reservation``); no se elimina.

Por qué existe
--------------
El diseño aprobado (opción B) pide que el operador VEA qué está mal y decida.
La detección NO se reinventa: se reutiliza el motor unificado del addon principal
(``printflow.stock.health._pf_lot_state``), del que se leen EXACTAMENTE sus
claves (``no_stock_lot_ids``, ``missing_move_ids``, ``orphan_quant_ids``,
``generic_lot_ids``, ``mixed_lots``, ``unassigned_mo_ids``). La ejecución del
remedio también es única: ``printflow.product.flow._pf_execute_lot_remedy``
(con su guardia ``_pf_assert_can_clean``).

Permisos
--------
VER la bandeja: cualquier ``base.group_user`` (ACL de lectura/creación; el
poblado lo hace el wizard). APLICAR la corrección (automática o por elección de
lote): pasa por el guardia de ``printflow.stock.remedy`` (jefe de taller/admin).
Quien no lo tiene, VE la bandeja pero recibe ``UserError`` al aplicar.

Contrato::

    tray = env['printflow.flow.lot.tray']._pf_populate(product, lot_state)
    action = tray[:1].action_open()
    action = tray[:1].action_open_lot_picker()   # desde una fila con selección
    action = tray.action_apply_correction()      # sobre la selección (o todas)
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

# Tipos de fila que ADMITEN autorizar su lote como excepción documentada: son
# los estados donde el lote FORMA PARTE de la causa (existe un lote concreto que
# el operador puede declarar intencional). La reserva huérfana, el movimiento sin
# lote y la MO sin lote NO tienen un lote que autorizar.
AUTHORIZABLE_KINDS = ('mixed_lot', 'generic_lot', 'no_stock_lot')

# Tipos de fila que la ACCIÓN EN BLOQUE "Asignar lote" sabe procesar: las
# entregas SIN lote (movimiento ya creado sin lote u orden de entrega pendiente
# sin lote). El resto de tipos (MO, insumos, reserva huérfana, lotes
# genéricos/mezclados) se OMITEN y se reportan (D7).
_BULK_ASSIGNABLE_KINDS = ('missing_move', 'pending_order')

# Modelos de documento sobre los que el MOTOR evalúa la ventana de corrección.
_EDITABLE_DOC_MODELS = ('stock.move', 'stock.picking', 'mrp.production')

# Lista BLANCA de modelos que la columna "Documento" (``document_ref``) sabe
# empaquetar/mostrar. Son los ``res_model`` que produce la bandeja
# (``stock.move``, ``stock.quant``, ``mrp.production``, ``stock.lot``) más los
# documentos "de cabecera" que pueden llegar a respaldar una fila
# (``stock.picking``/``purchase.order``/``sale.order``). Debe COINCIDIR con
# ``_pf_document_ref_selection`` (la selección del campo ``Reference``).
_DOCUMENT_REF_MODELS = (
    'stock.move', 'stock.picking', 'mrp.production', 'purchase.order',
    'sale.order', 'stock.quant', 'stock.lot',
)


class PrintflowFlowLotTray(models.TransientModel):
    """Una fila por ítem afectado por el estado de lote de un producto."""

    _name = 'printflow.flow.lot.tray'
    _description = 'Bandeja gestionable de lote (PrintFlow)'
    _order = 'kind, id'

    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True,
        help='Producto cuyo lote se está gestionando.')
    lot_state = fields.Char(
        string='Estado de lote', readonly=True,
        help='Estado normalizado del motor (clave de LOT_REMEDY_BY_STATE).')
    remedy_target = fields.Char(
        string='Destino de la corrección', readonly=True,
        help='Destino del remedio del motor principal (lista blanca del wizard).')
    remedy_label = fields.Char(
        string='Corrección', readonly=True)
    kind = fields.Char(
        string='Tipo de ítem', readonly=True,
        help='Clasificación de la fila (lote, movimiento, quant, MO).')
    res_model = fields.Char(string='Modelo', readonly=True)
    res_id = fields.Integer(string='Id del registro', readonly=True)
    # Columna "Documento" legible y NAVEGABLE, agnóstica al modelo de la fila.
    # Es ADICIONAL: ``res_model``/``res_id`` se CONSERVAN (los usan
    # ``action_open``, los botones y los constructores de fila). ``document_ref``
    # solo EMPAQUETA ese mismo par como UN valor (para la vista).
    document_ref = fields.Reference(
        selection='_pf_document_ref_selection', string='Documento',
        readonly=True, compute='_compute_document_ref',
        search='_pf_search_document_ref',
        help='Par (modelo, id) del registro que respalda la fila, como un solo '
             'valor navegable. ADICIONAL a res_model/res_id (que se conservan). '
             'Agnóstico al modelo de la fila (lista blanca).')
    # Modo de resolución POR FILA: gobierna qué columnas se muestran (existencias
    # solo al ASIGNAR) y cómo se rotula ``own_lot_name`` ("sugerido" al crear,
    # "propio" al asignar).
    lot_action_mode = fields.Selection(
        selection=[
            ('create', 'Crear lote sugerido'),
            ('assign', 'Asignar/elegir lote existente'),
            ('reconcile', 'Reconciliar reserva'),
        ],
        string='Modo', compute='_compute_lot_action_mode',
        search='_pf_search_lot_action_mode',
        help='Modo de resolución de la fila, derivado de "kind" y '
             '"own_lot_name". La vista lo usa para mostrar las columnas de '
             'existencia SOLO al ASIGNAR un lote existente y para rotular el '
             'lote propio ("Lote sugerido" al crear, "Lote propio" al asignar).')
    label = fields.Char(string='Afectado', readonly=True)
    lot_name = fields.Char(string='Lote', readonly=True)
    qty = fields.Float(string='Cantidad', readonly=True)
    state_label = fields.Char(string='Estado', readonly=True)
    detail = fields.Char(string='Detalle', readonly=True)
    # Contexto para el aviso del selector de lote (solo lectura): con qué lote
    # propio cuenta el documento y qué lote tiene hoy. Vacío = no determinable
    # (el selector queda neutro, no bloquea).
    own_lot_name = fields.Char(
        string='Lote propio', readonly=True,
        help='Nombre SUGERIDO del lote exclusivo del documento, calculado '
             '(<pedido>-L<línea>); NO siempre existe como registro stock.lot '
             '(vacío si no es determinable).')
    sale_name = fields.Char(
        string='Pedido', readonly=True,
        help='Pedido de venta del documento, si se conoce.')
    lot_name_actual = fields.Char(
        string='Lote actual', readonly=True,
        help='Lote que tiene hoy el ítem afectado.')
    # ── Contexto del DOCUMENTO (la fila de un lote apunta a su stock.move) ──
    picking_id = fields.Many2one(
        'stock.picking', string='Albarán', readonly=True,
        help='Albarán del movimiento afectado (contexto de la entrega).')
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', readonly=True,
        help='Cliente de la entrega del movimiento afectado.')
    scheduled_date = fields.Datetime(
        string='Fecha prevista', readonly=True,
        help='Fecha prevista del albarán (o del movimiento).')
    location_id = fields.Many2one(
        'stock.location', string='Ubicación', readonly=True,
        help='Ubicación origen del movimiento: acota la disponibilidad real.')
    demand_qty = fields.Float(
        string='Demanda', readonly=True, digits='Product Unit of Measure',
        help='Cantidad que pide el movimiento (para el aviso de parcial).')
    can_choose_lot = fields.Boolean(
        string='Admite elegir lote', readonly=True, default=True,
        help='Falso en las filas informativas (un lote sin documento activo que '
             'lo respalde): el botón "Elegir lote" queda oculto.')
    # ── Autorización EXCEPCIÓN (lote intencional) ─────────────────────────
    lot_id = fields.Many2one(
        'stock.lot', string='Lote', readonly=True,
        help='Lote CONCRETO de la fila (vacío en las filas sin lote).')
    can_authorize = fields.Boolean(
        string='Admite autorizar', compute='_compute_can_authorize',
        help='Verdadero si la fila tiene un lote que puede declararse como '
             'excepción documentada (mezclado/genérico/sin existencia).')
    lot_is_authorized = fields.Boolean(
        string='Autorizado', compute='_compute_lot_is_authorized',
        help='Verdadero si el lote ya está autorizado como excepción '
             'documentada (deja de reportarse como mezcla).')
    can_correct_doc = fields.Boolean(
        string='Corregible', compute='_compute_can_correct_doc',
        help='Falso si el documento ya está validado (hecho): el lote no se '
             'puede corregir desde el selector.')
    # ── EXISTENCIA por fila (lote original y lote usado) ─────────────────
    own_lot_id = fields.Many2one(
        'stock.lot', string='Lote sugerido', readonly=True,
        help='Registro del lote SUGERIDO del documento, si el nombre calculado '
             '(<pedido>-L<línea>) ya existe como stock.lot; vacío si aún no '
             'existe (el nombre sugerido puede no tener registro).')
    own_lot_qty = fields.Float(
        string='Existencia sugerida', readonly=True,
        digits='Product Unit of Measure',
        help='Existencia FÍSICA del lote SUGERIDO del documento (0 si el lote '
             'aún no existe como registro).')
    used_lot_qty = fields.Float(
        string='Existencia usada', readonly=True,
        digits='Product Unit of Measure',
        help='Existencia FÍSICA del lote que el documento está usando.')
    used_lot_available = fields.Float(
        string='Disponible usado', readonly=True,
        digits='Product Unit of Measure',
        help='Disponible (existencia − reservado) del lote que se está usando.')

    # ── Autorización de EXCEPCIÓN FORMAL (F4/F5): el hallazgo de la fila se
    #    autoriza sobre su (res_model, res_id) SIN exigir lote. Es la vía
    #    PRIMARIA para la MO terminada sin lote (que NO tiene lote que autorizar).
    finding_code = fields.Char(
        string='Hallazgo', compute='_compute_finding_code',
        help='Clave del hallazgo formal de la fila (registry de GI); vacío si la '
             'fila no es un formalismo autorizable.')
    finding_is_authorized = fields.Boolean(
        string='Excepción formal', compute='_compute_finding_is_authorized',
        help='Verdadero si el hallazgo de esta fila ya está autorizado como '
             'excepción formal.')
    can_authorize_finding = fields.Boolean(
        string='Admite autorizar hallazgo',
        compute='_compute_can_authorize_finding',
        help='Verdadero si la fila porta un hallazgo formal autorizable y aún no '
             'autorizado (vía genérica, sin exigir lote).')

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTOS
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('kind', 'lot_id')
    def _compute_can_authorize(self):
        """La fila admite autorizar si tiene un lote y su tipo lo permite."""
        for rec in self:
            rec.can_authorize = bool(
                rec.lot_id and rec.kind in AUTHORIZABLE_KINDS)

    @api.depends('lot_id')
    def _compute_lot_is_authorized(self):
        """Marca las filas cuyo lote ya está autorizado (UNA consulta)."""
        authorized = self.env['printflow.stock.health']._pf_authorized_lot_ids(
            self.mapped('lot_id').ids)
        for rec in self:
            rec.lot_is_authorized = bool(
                rec.lot_id and rec.lot_id.id in authorized)

    @api.depends('res_model', 'res_id')
    def _compute_can_correct_doc(self):
        """Lee del MOTOR si el documento de la fila admite corrección."""
        for rec in self:
            doc = rec._pf_editable_doc(rec.res_model, rec.res_id)
            info = self.env[
                'printflow.stock.health']._pf_document_lot_editable(doc)
            rec.can_correct_doc = info['editable']

    @api.model
    def _pf_editable_doc(self, res_model, res_id):
        """Documento de la fila para la ventana de corrección (lista blanca)."""
        if not res_model or not res_id or res_model not in _EDITABLE_DOC_MODELS:
            return self.env['stock.move']
        return self.env[res_model].sudo().browse(res_id).exists()

    # ── Hallazgo formal de la fila (F4/F5) ────────────────────────────────
    @api.depends('kind')
    def _compute_finding_code(self):
        """Traduce el tipo de fila a su ``finding_code`` (registry, sin ``if``)."""
        Registry = self.env['printflow.finding.exception.registry']
        for rec in self:
            rec.finding_code = Registry._pf_code_for_kind(rec.kind) or False

    @api.depends('kind', 'res_model', 'res_id', 'lot_id')
    def _compute_finding_is_authorized(self):
        """Marca las filas cuyo hallazgo formal ya está autorizado (en BLOQUE).

        Se compara contra el destino FORMAL (``_pf_formal_target``), no contra el
        documento de la fila: los hallazgos de lote viven sobre el LOTE, no sobre
        el movimiento que lo usa (H-065/H-066).
        """
        Exception = self.env['printflow.finding.exception']
        targets = {}
        for rec in self:
            code = rec.finding_code
            if code and code not in targets:
                targets[code] = Exception._pf_suppressed_targets(code)
        for rec in self:
            _model, target_id = rec._pf_formal_target()
            rec.finding_is_authorized = bool(
                rec.finding_code and target_id
                and target_id in targets.get(rec.finding_code, set()))

    @api.depends('finding_code', 'res_model', 'res_id', 'lot_id',
                 'finding_is_authorized')
    def _compute_can_authorize_finding(self):
        """La fila admite autorizar su hallazgo si tiene DESTINO y no está ya.

        Un hallazgo cuyo destino es el LOTE exige que la fila traiga el lote: sin
        él no hay registro que autorizar.
        """
        for rec in self:
            _model, target_id = rec._pf_formal_target()
            rec.can_authorize_finding = bool(
                rec.finding_code and target_id
                and not rec.finding_is_authorized)

    def _pf_formal_target(self):
        """``(modelo, id)`` del registro sobre el que VIVE el hallazgo formal.

        El destino lo declara el registry (``target_model``), NO la fila: la
        bandeja pinta el DOCUMENTO que usa el lote (``stock.move``), pero
        ``lot_generic`` / ``lot_no_stock`` / ``lot_mixed`` se autorizan sobre el
        LOTE. En los demás (``lot_missing`` -> ``stock.move``,
        ``lot_unassigned_finished`` -> ``mrp.production``) el destino sigue siendo
        el documento de la fila.

        Un hallazgo de lote cuya fila no trae lote devuelve id ``0`` (= no hay
        nada que autorizar; ``can_authorize_finding`` queda en Falso).
        """
        self.ensure_one()
        Registry = self.env['printflow.finding.exception.registry']
        target_model = (
            Registry._pf_target_model(self.finding_code) or self.res_model)
        if target_model == 'stock.lot':
            if self.res_model == 'stock.lot' and self.res_id:
                return target_model, self.res_id
            return target_model, self.lot_id.id or 0
        return target_model, self.res_id or 0

    def _pf_formal_label(self):
        """Rótulo de la excepción formal, coherente con su DESTINO (H-067).

        Cuando el hallazgo vive sobre el LOTE, la etiqueta es el NOMBRE DEL LOTE
        (``SN000001``): el rótulo de la fila pinta el DOCUMENTO que lo usa
        (``Movimiento WH/MO/01584``) y hace creer al operador que autorizó el
        movimiento. En los hallazgos de movimiento/MO el rótulo no cambia.

        Se resuelve desde el MISMO destino que ``_pf_formal_target`` (una sola
        fuente de verdad), así la etiqueta no puede describir otro registro.
        """
        self.ensure_one()
        target_model, target_id = self._pf_formal_target()
        if target_model != 'stock.lot' or not target_id:
            return self.label or ''
        lot = self.lot_id
        if lot.id != target_id:
            lot = self.env['stock.lot'].sudo().browse(target_id).exists()
        return lot.name or self.label or ''

    # ── Documento (columna navegable) y modo de acción ────────────────────
    @api.depends('res_model', 'res_id')
    def _compute_document_ref(self):
        """Empaqueta el par (modelo, id) sin consultar la BD.

        Un campo ``Reference`` se lee/representa como UN solo valor navegable
        (mejor que los dos Char/Integer sueltos en la vista). Se asigna un
        recordset de ``browse`` (perezoso) en vez de la cadena ``'modelo,id'``:
        con la cadena, ``Reference.convert_to_cache`` ejecutaría un ``exists()``
        por fila (N+1); con el recordset, el cómputo queda libre de consultas y
        el valor cacheado es IDÉNTICO (``'modelo,id'``). Si el modelo no está en
        la lista blanca o no hay id, se deja vacío.
        """
        for rec in self:
            if rec.res_model in _DOCUMENT_REF_MODELS and rec.res_id:
                rec.document_ref = self.env[rec.res_model].browse(rec.res_id)
            else:
                rec.document_ref = False

    @api.model
    def _pf_document_ref_selection(self):
        """Lista blanca (modelo, etiqueta) del campo ``document_ref``.

        Debe COINCIDIR con ``_DOCUMENT_REF_MODELS``. Se declara la etiqueta para
        que el widget de referencia muestre un nombre legible del documento.
        """
        return [
            ('stock.move', _('Movimiento de stock')),
            ('stock.picking', _('Albarán')),
            ('mrp.production', _('Orden de fabricación')),
            ('purchase.order', _('Orden de compra')),
            ('sale.order', _('Pedido de venta')),
            ('stock.quant', _('Quant de stock')),
            ('stock.lot', _('Lote')),
        ]

    @api.model
    def _pf_search_document_ref(self, operator, value):
        """Traduce la búsqueda de "Documento" a las fuentes ALMACENADAS.

        ``document_ref`` es computado SIN almacenar; se busca por sus fuentes
        ``res_model``/``res_id``. Acepta ``'modelo,id'`` (operadores ``=``/``!=``)
        y, como texto (``like``/``ilike``), el NOMBRE del modelo. Un operador no
        soportado no acota (devuelve dominio vacío), nunca rompe.
        """
        if operator in ('like', 'ilike', 'not like', 'not ilike'):
            return [('res_model', operator, value or '')]
        if operator not in ('=', '!='):
            return []
        model, _sep, res_id = (value or '').partition(',')
        if not model:
            return []
        domain = [('res_model', '=', model)]
        if res_id.isdigit():
            domain.append(('res_id', '=', int(res_id)))
        return domain if operator == '=' else ['!'] + domain

    @api.depends('kind', 'own_lot_name')
    def _compute_lot_action_mode(self):
        """Modo de resolución por fila (mapa EXPLÍCITO).

        * ``unassigned_mo`` CON ``own_lot_name`` → ``create`` (crear el sugerido).
        * ``orphan_quant`` → ``reconcile`` (reconciliar la reserva).
        * ``unassigned_mo`` SIN ``own_lot_name`` → ``assign`` (emergencia).
        * ``missing_move``/``no_stock_lot``/``generic_lot``/``mixed_lot`` →
          ``assign``; ``pending_order`` (orden de entrega sin lote, P2) →
          ``assign``; default → ``assign``.
        """
        for rec in self:
            if rec.kind == 'unassigned_mo':
                rec.lot_action_mode = 'create' if rec.own_lot_name else 'assign'
            elif rec.kind == 'orphan_quant':
                rec.lot_action_mode = 'reconcile'
            elif rec.kind == 'pending_order':
                # P2: la orden pendiente se resuelve ASIGNANDO un lote existente
                # (el exclusivo del pedido o uno con existencia real).
                rec.lot_action_mode = 'assign'
            else:
                rec.lot_action_mode = 'assign'

    @api.model
    def _pf_search_lot_action_mode(self, operator, value):
        """Traduce el filtro del MODO a los campos ALMACENADOS.

        ``lot_action_mode`` es computado SIN almacenar: el ORM no puede filtrarlo
        directo (y una vista ``search`` que lo use sin ``search`` aborta al
        validarse, porque ``_check_field_paths`` exige ``_description_searchable``).
        Este método conserva el MODO como única fuente de verdad y lo traduce al
        dominio equivalente sobre ``kind``/``own_lot_name`` (ambos almacenados en
        la tabla transitoria). Un operador/valor no soportado no acota.
        """
        if operator not in ('=', '!='):
            return []
        if value == 'create':
            domain = [('kind', '=', 'unassigned_mo'),
                      ('own_lot_name', '!=', False)]
        elif value == 'reconcile':
            domain = [('kind', '=', 'orphan_quant')]
        elif value == 'assign':
            # El modo "assign" cubre los kinds de lote/movimiento y el kind
            # NUEVO ``pending_order`` (P2). Éste se añade como rama OR
            # **separada** para CONSERVAR INTACTA la tupla de kinds (candado de
            # paridad del search). Semántica (prefija Odoo):
            # Or(Or(lote/movimiento, pending_order), And(unassigned_mo, sin
            # lote sugerido)).
            domain = ['|', '|',
                ('kind', 'in', (
                    'missing_move', 'no_stock_lot', 'generic_lot', 'mixed_lot')),
                ('kind', '=', 'pending_order'),
                '&', ('kind', '=', 'unassigned_mo'),
                ('own_lot_name', '=', False),
            ]
        else:
            return []
        return domain if operator == '=' else ['!'] + domain

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, product, lot_state):
        """Reconstruye la bandeja para un producto y un estado de lote.

        Limpia las filas previas del MISMO producto y estado (el wizard es el
        dueño transitorio), lee el estado de lote del motor principal y crea una
        fila por ítem afectado. El destino/microcopy de la corrección se toma del
        plan ADAPTADO al modo PRODUCTO (``_pf_plan_for_state``), de modo que la
        cabecera ejecute exactamente lo que recomienda el motor.

        :param product: ``product.product``.
        :param str lot_state: estado de lote del hallazgo.
        :return: recordset de ``printflow.flow.lot.tray``.
        :rtype: models.Model
        """
        product = product.exists() if product else self.browse()
        if not product or not lot_state:
            return self.browse()
        self.sudo().search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ]).unlink()
        lot_info = self.env['printflow.stock.health']._pf_lot_state(product)
        # F3: resta de los hallazgos AUTORIZADOS (adaptador de GI). Las filas se
        # construyen desde el ``lot_info`` YA filtrado, así que un hallazgo
        # autorizado NO genera fila y, si era el único, la bandeja queda vacía.
        lot_info = self.env[
            'printflow.finding.exception.filter']._pf_apply_to_lot_info(
                product, lot_info)
        plan = self.env['printflow.flow.lots']._pf_plan_for_state(
            lot_state, 'product')
        solution = (plan.get('actions') or {}).get('solution') or {}
        rows = self._pf_rows_for_state(product, lot_state, lot_info)
        # Contexto de lote propio / pedido / lote actual por fila (para el aviso
        # del selector de lote). Best effort: si no es determinable queda vacío.
        for row in rows:
            row.update(self._pf_row_lot_context(
                row.get('kind'), row.get('res_model'), row.get('res_id'),
                row.get('lot_name'), product))
        # Existencia/disponible del lote original y del usado (en bloque).
        self._pf_annotate_lot_quantities(product, rows)
        vals = [dict(row, **{
            'product_id': product.id,
            'lot_state': lot_state,
            'remedy_target': solution.get('target') or '',
            'remedy_label': solution.get('label') or '',
        }) for row in rows]
        if not vals:
            return self.browse()
        return self.create(vals)

    @api.model
    def _pf_rows_for_state(self, product, lot_state, lot_info):
        """Filas CRUDAS (dicts) de un estado de lote (lista blanca explícita).

        El mapa asocia ESTADO -> constructor (función miembro), sin ``getattr``
        por convención: solo los estados listados tienen filas.
        """
        builders = {
            'lot_orphan_reservation': self._pf_rows_orphan_quants,
            'lot_missing': self._pf_rows_lot_missing,
            'lot_no_stock': self._pf_rows_no_stock_lots,
            'lot_generic': self._pf_rows_generic_lots,
            'lot_mixed': self._pf_rows_mixed_lots,
            'lot_unassigned_finished': self._pf_rows_unassigned_mos,
        }
        builder = builders.get(lot_state)
        if not builder:
            return []
        return builder(product, lot_info)

    # ══════════════════════════════════════════════════════════════════════
    # CONSTRUCTORES DE FILA (un método por tipo de ítem afectado)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_rows_orphan_quants(self, product, lot_info):
        """Quants con reserva que ningún movimiento respalda."""
        rows = []
        quants = self.env['stock.quant'].sudo().browse(
            lot_info.get('orphan_quant_ids') or []).exists()
        for quant in quants:
            rows.append({
                'kind': 'orphan_quant',
                'label': _('Reserva huérfana: %s') % (
                    quant.lot_id.name or quant.product_id.display_name),
                'lot_name': quant.lot_id.name or '',
                'qty': quant.reserved_quantity or 0.0,
                'state_label': '',
                'detail': _('Reservado sin movimiento que lo respalde en %s') % (
                    quant.location_id.display_name or ''),
                'res_model': 'stock.quant',
                'res_id': quant.id,
                'can_choose_lot': False,
                'lot_id': quant.lot_id.id or False,
            })
        return rows

    @api.model
    def _pf_rows_missing_moves(self, product, lot_info):
        """Movimientos de salida sin lote asignado."""
        rows = []
        moves = self.env['stock.move'].sudo().browse(
            lot_info.get('missing_move_ids') or []).exists()
        for move in moves:
            rows.append({
                'kind': 'missing_move',
                'label': _('Movimiento %s') % (
                    move.reference or move.name or ''),
                'lot_name': '',
                'qty': move.product_uom_qty or 0.0,
                'state_label': self._pf_state_label(move),
                'detail': _('Movimiento sin lote asignado'),
                'res_model': 'stock.move',
                'res_id': move.id,
                'can_choose_lot': True,
            })
        return rows

    @api.model
    def _pf_rows_lot_missing(self, product, lot_info):
        """Filas del estado "movimiento sin lote": SUMA, nunca reemplazo (P2).

        La bandeja CLÁSICA ya listaba el/los MOVIMIENTO(s) YA creados sin lote
        (``missing_move``); P2 le SUMA una fila por cada ORDEN de entrega
        pendiente del producto que aún NO tiene lote, para que el operador vea
        la dimensión REAL (≈28 entregas) y no solo la punta de una (D2). Se
        conservan AMBAS lecturas a propósito (O-5): el movimiento es la evidencia
        técnica y la orden es la dimensión operativa; NO se deduplican, para no
        ocultar el caso real.
        """
        return (
            self._pf_rows_missing_moves(product, lot_info)
            + self._pf_rows_pending_orders(product, lot_info)
        )

    @api.model
    def _pf_rows_pending_orders(self, product, lot_info):
        """UNA fila por ORDEN de entrega pendiente del producto SIN lote (P2).

        Fuente ÚNICA de las órdenes: ``printflow.flow.pending._pf_node_pending_rows
        ('delivery', [product.id])`` (ya lee los ``stock.move`` de salida de los
        albaranes ABIERTOS del producto). Con UNA lectura batch de ``stock.move``
        (fuente ``lot_ids``, many2many consultable en ``search_read``) se
        resuelve, por albarán, la DEMANDA del producto y si YA tiene lote
        asignado: las entregas SANAS (con lote) NO se listan.

        Solo se CONSUME el contrato existente de ``printflow.flow.lot.tray.line``:
        cada fila lleva ÚNICAMENTE campos EXISTENTES (``_pf_populate`` las crea
        con ``dict(row, ...)``). NO escribe ni valida nada por detrás.
        """
        pending = self.env[
            'printflow.flow.pending']._pf_node_pending_rows(
                'delivery', [product.id])
        picking_ids = {
            row['picking_id'][0] for row in pending if row.get('picking_id')}
        if not picking_ids:
            return []
        # UNA sola lectura batch: demanda del producto y si ya tiene lote.
        moves = self.env['stock.move'].sudo().search_read(
            [('picking_id', 'in', list(picking_ids)),
             ('product_id', '=', product.id),
             ('state', 'not in', ('done', 'cancel'))],
            ['picking_id', 'product_uom_qty', 'lot_ids'])
        demand_by_picking = {}
        pickings_with_lot = set()
        for move in moves:
            picking_ref = move.get('picking_id')
            if not picking_ref:
                continue
            picking_id = picking_ref[0]
            demand_by_picking[picking_id] = (
                demand_by_picking.get(picking_id, 0.0)
                + (move.get('product_uom_qty') or 0.0))
            if move.get('lot_ids'):
                pickings_with_lot.add(picking_id)
        pending_pickings = self.env['stock.picking'].sudo().browse(
            sorted(picking_ids - pickings_with_lot)).exists()
        rows = []
        for picking in pending_pickings:
            partner = picking.partner_id or picking.sale_id.partner_id
            demand = demand_by_picking.get(picking.id, 0.0)
            rows.append({
                'kind': 'pending_order',
                'label': _('Entrega %s') % (picking.name or ''),
                'lot_name': '',
                'qty': demand,
                'state_label': self._pf_state_label(picking),
                'detail': _('Sin lote: se espera el lote exclusivo del pedido o '
                            'su asignación (aún sin reserva).'),
                'res_model': 'stock.picking',
                'res_id': picking.id,
                'picking_id': picking.id,
                'partner_id': partner.id or False,
                'scheduled_date': picking.scheduled_date or False,
                'location_id': picking.location_id.id or False,
                'demand_qty': demand,
                'can_choose_lot': True,
                'lot_id': False,
            })
        return rows

    @api.model
    def _pf_rows_no_stock_lots(self, product, lot_info):
        """Lotes reservados sin existencia interna: UNA fila POR DOCUMENTO."""
        return self._pf_rows_lot_state(
            product, lot_info.get('no_stock_lot_ids') or [],
            'no_stock_lot', _('Lote reservado sin existencia interna'))

    @api.model
    def _pf_rows_generic_lots(self, product, lot_info):
        """Lotes genéricos en producto gestionado: UNA fila POR DOCUMENTO."""
        return self._pf_rows_lot_state(
            product, lot_info.get('generic_lot_ids') or [],
            'generic_lot', _('Lote genérico en producto gestionado'))

    @api.model
    def _pf_rows_mixed_lots(self, product, lot_info):
        """Lotes usados por pedidos/clientes distintos: UNA fila POR DOCUMENTO.

        Los nombres que trae el motor se resuelven a lotes y se delegan en el
        constructor genérico (una fila por documento que los usa).
        """
        names = [name for name in (lot_info.get('mixed_lots') or []) if name]
        if not names:
            return []
        lots = self.env['stock.lot'].sudo().search([
            ('product_id', '=', product.id),
            ('name', 'in', names),
        ])
        return self._pf_rows_lot_state(
            product, lots.ids, 'mixed_lot',
            _('Lote usado por pedidos o clientes distintos'))

    @api.model
    def _pf_rows_unassigned_mos(self, product, lot_info):
        """Órdenes de fabricación terminadas sin lote de terminado."""
        rows = []
        mos = self.env['mrp.production'].sudo().browse(
            lot_info.get('unassigned_mo_ids') or []).exists()
        for mo in mos:
            rows.append({
                'kind': 'unassigned_mo',
                'label': _('Orden de fabricación %s') % mo.name,
                'lot_name': '',
                'qty': mo.product_qty or 0.0,
                'state_label': self._pf_state_label(mo),
                'detail': _('Orden de fabricación terminada sin lote'),
                'res_model': 'mrp.production',
                'res_id': mo.id,
                'can_choose_lot': True,
            })
        return rows

    # ══════════════════════════════════════════════════════════════════════
    # CONSTRUCTOR GENÉRICO POR DOCUMENTO (Hueco 1)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_move_lines_for_lots(self, product, lot_ids):
        """Move lines ACTIVAS internas del producto con alguno de esos lotes.

        Misma búsqueda que el motor (``_pf_lot_state``): producto, estado activo,
        ``quantity > eps``, ubicación interna y lote en la lista. UNA sola lectura.
        :rtype: stock.move.line
        """
        lot_ids = [lot_id for lot_id in (lot_ids or []) if lot_id]
        if not product or not lot_ids:
            return self.env['stock.move.line']
        return self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', _EPS),
            ('location_id.usage', '=', 'internal'),
            ('lot_id', 'in', lot_ids),
        ])

    @api.model
    def _pf_rows_lot_state(self, product, lot_ids, kind, detail):
        """UNA fila por DOCUMENTO (``stock.move``) que usa los lotes indicados.

        Agrupa las move lines por movimiento y emite una fila por documento con
        ``res_model='stock.move'`` y el contexto de la entrega (albarán/cliente/
        fecha/ubicación/demanda). Si un lote detectado NO se ubica en ningún
        documento activo, emite una fila INFORMATIVA (``res_model='stock.lot'``,
        ``can_choose_lot=False``) para no perder la evidencia.
        """
        rows = []
        lines = self._pf_move_lines_for_lots(product, lot_ids)
        covered_lot_ids = set()
        by_move = {}
        for line in lines:
            covered_lot_ids.add(line.lot_id.id)
            # Primera línea de cada movimiento: identifica documento y lote.
            by_move.setdefault(line.move_id.id, line)
        for line in by_move.values():
            rows.append(self._pf_row_for_move(line, kind, detail))
        # Lotes detectados sin documento activo: fila informativa (botón oculto).
        orphan_lots = self.env['stock.lot'].sudo().browse(
            [lot_id for lot_id in (lot_ids or [])
             if lot_id and lot_id not in covered_lot_ids]).exists()
        for lot in orphan_lots:
            rows.append(self._pf_row_for_lot(lot, kind, detail))
        return rows

    @api.model
    def _pf_row_for_move(self, line, kind, detail):
        """Fila de un documento (``stock.move``) con su contexto de entrega."""
        move = line.move_id
        picking = move.picking_id
        lot = line.lot_id
        partner = picking.partner_id or picking.sale_id.partner_id
        document = picking.name or move.reference or move.name or ''
        return {
            'kind': kind,
            'label': _('Movimiento %s') % document,
            'lot_name': lot.name or '',
            'qty': move.product_uom_qty or 0.0,
            'state_label': self._pf_state_label(move),
            'detail': detail,
                'res_model': 'stock.move',
                'res_id': move.id,
                'picking_id': picking.id or False,
                'partner_id': partner.id or False,
                'scheduled_date': picking.scheduled_date or move.date or False,
                'location_id': move.location_id.id or False,
                'demand_qty': move.product_uom_qty or 0.0,
                'can_choose_lot': True,
                'lot_id': lot.id or False,
            }

    @api.model
    def _pf_row_for_lot(self, lot, kind, detail):
        """Fila INFORMATIVA de un lote sin documento activo (botón oculto)."""
        return {
            'kind': kind,
            'label': _('Lote %s') % lot.name,
            'lot_name': lot.name or '',
            'qty': 0.0,
            'state_label': '',
            'detail': detail,
            'res_model': 'stock.lot',
            'res_id': lot.id,
            'can_choose_lot': False,
            'lot_id': lot.id or False,
        }

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_state_label(self, record):
        """Etiqueta legible del ``state`` de un registro (reusa el helper)."""
        return self.env[
            'printflow.flow.strategy.product']._pf_selection_label(record)

    @api.model
    def _pf_row_lot_context(self, kind, res_model, res_id, lot_name, product):
        """Contexto de lote propio/pedido/lote actual de UNA fila (best effort).

        El lote propio sale del helper EXISTENTE del motor: para movimientos de
        venta/producción, ``sale.order.line._get_exclusive_lot_name``; para una
        MO, ``mrp.production._get_exclusive_finished_lot_name`` /
        ``_get_pf_lot_name``. Si no es determinable, se deja VACÍO: el selector
        queda neutro (no bloquea, no miente).
        """
        own = ''
        sale = ''
        move = self._pf_document_move(kind, res_model, res_id, product, lot_name)
        if move:
            sale_line = move.sale_line_id
            if sale_line:
                own = sale_line._get_exclusive_lot_name() or ''
                sale = sale_line.order_id.name or ''
        elif (kind == 'unassigned_mo' and res_model == 'mrp.production'
                and res_id):
            mo = self.env['mrp.production'].sudo().browse(res_id).exists()
            if mo:
                own = (mo._get_exclusive_finished_lot_name()
                       or mo._get_pf_lot_name() or '')
                sale = (mo.origin or '').strip()
        return {
            'own_lot_name': own or '',
            'sale_name': sale or '',
            'lot_name_actual': lot_name or '',
        }

    @api.model
    def _pf_document_move(self, kind, res_model, res_id, product, lot_name):
        """``stock.move`` que respalda la fila (o recordset vacío).

        Para ``missing_move`` es el propio movimiento. Para los estados de LOTE
        (``no_stock_lot``/``generic_lot``/``mixed_lot``) la fila apunta al lote:
        se localiza el movimiento activo interno del producto que lo usa (una
        sola búsqueda acotada con ``limit=1``). Para ``pending_order`` (P2) la
        fila apunta a la ORDEN (albarán): se resuelve el movimiento activo del
        producto en ese albarán, de modo que ``_pf_row_lot_context`` traiga el
        lote EXCLUSIVO esperado del pedido.
        """
        Move = self.env['stock.move'].sudo()
        if not res_id or not product:
            return self.env['stock.move']
        if kind == 'missing_move' and res_model == 'stock.move':
            return Move.browse(res_id).exists()
        if kind == 'pending_order' and res_model == 'stock.picking':
            return Move.search([
                ('picking_id', '=', res_id),
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
            ], limit=1)
        if kind in ('no_stock_lot', 'generic_lot', 'mixed_lot'):
            if res_model == 'stock.move':
                return Move.browse(res_id).exists()
            if res_model == 'stock.lot':
                lot = self.env['stock.lot'].sudo().browse(res_id).exists()
                if lot:
                    line = self.env['stock.move.line'].sudo().search([
                        ('product_id', '=', product.id),
                        ('lot_id', '=', lot.id),
                        ('state', 'not in', ('done', 'cancel')),
                    ], limit=1)
                    return line.move_id
        return self.env['stock.move']

    @api.model
    def _pf_annotate_lot_quantities(self, product, rows):
        """Anota existencia/disponible del lote original y del usado por fila.

        Resuelve los NOMBRES del lote original a ids (UNA búsqueda) y lee los
        quants internos de TODOS los lotes implicados (UNA lectura agregada); no
        hay N+1. Deja en cada fila: ``own_lot_id``, ``own_lot_qty`` (existencia
        del original), ``used_lot_qty`` (existencia del usado) y
        ``used_lot_available`` (disponible del usado).
        """
        if not product or not rows:
            return
        own_names = {
            row.get('own_lot_name') for row in rows if row.get('own_lot_name')}
        own_by_name = {}
        if own_names:
            own_lots = self.env['stock.lot'].sudo().search([
                ('product_id', '=', product.id),
                ('name', 'in', list(own_names)),
            ])
            own_by_name = {lot.name: lot.id for lot in own_lots}
        used_ids = {row.get('lot_id') for row in rows if row.get('lot_id')}
        totals = self._pf_lot_quant_totals(
            product, used_ids | set(own_by_name.values()))
        for row in rows:
            own_id = own_by_name.get(row.get('own_lot_name') or '')
            own_totals = totals.get(own_id) or {}
            used_totals = totals.get(row.get('lot_id')) or {}
            row['own_lot_id'] = own_id or False
            row['own_lot_qty'] = own_totals.get('qty_on_hand', 0.0)
            row['used_lot_qty'] = used_totals.get('qty_on_hand', 0.0)
            row['used_lot_available'] = used_totals.get('available', 0.0)

    @api.model
    def _pf_lot_quant_totals(self, product, lot_ids):
        """Existencia/reservado/disponible por lote (UNA lectura de quants).

        ``available = quantity - max(reservado, 0)`` (una reserva negativa no
        infla el libre). Lectura pura.
        :rtype: dict[int, dict]
        """
        totals = {}
        strong = [lot_id for lot_id in (lot_ids or []) if lot_id]
        if not product or not strong:
            return totals
        for quant in self.env['stock.quant'].sudo().search_read([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
            ('lot_id', 'in', strong),
        ], ['lot_id', 'quantity', 'reserved_quantity']):
            ref = quant['lot_id']
            if not ref:
                continue
            entry = totals.setdefault(ref[0], {
                'qty_on_hand': 0.0, 'reserved': 0.0, 'available': 0.0})
            qty = quant['quantity'] or 0.0
            res = quant['reserved_quantity'] or 0.0
            entry['qty_on_hand'] += qty
            entry['reserved'] += max(res, 0.0)
            entry['available'] += qty - max(res, 0.0)
        return totals

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES
    # ══════════════════════════════════════════════════════════════════════
    def action_open(self):
        """NAVEGA al registro real de la fila (solo lectura)."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': self.label or _('Registro'),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_lot_picker(self):
        """Abre el SELECTOR de lote del documento de ESTA fila (decisión consciente).

        Método PÚBLICO a propósito: Odoo 17 rechaza invocar privados por RPC
        (``call_button``). La reserva huérfana (``orphan_quant``) NO admite
        elección de lote: su corrección es la automática ("Corrección
        automática"). El resto delega el poblado en
        ``printflow.flow.lot.picker._pf_populate``.
        """
        self.ensure_one()
        if self.kind == 'orphan_quant':
            raise UserError(_(
                'La reserva huérfana no admite elección de lote: usa '
                '"Corrección automática".'))
        if not self.can_choose_lot:
            raise UserError(_(
                'Este ítem no admite elección de lote: no hay un documento '
                'activo que lo respalde. Usa "Corrección automática".'))
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        picker = self.env['printflow.flow.lot.picker']._pf_populate(
            self.product_id,
            self.kind,
            self.res_model,
            self.res_id,
            own_lot_name=self.own_lot_name,
            sale_name=self.sale_name,
            lot_name_actual=self.lot_name_actual or self.lot_name,
            location_id=self.location_id.id,
            demand_qty=self.demand_qty,
            current_lot_id=self.lot_id,
        )
        if not picker:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'type': 'ir.actions.act_window',
            'name': _('Elegir lote: %s') % self.product_id.display_name,
            'res_model': 'printflow.flow.lot.picker',
            'res_id': picker.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_authorize_lot(self):
        """Abre el modal para AUTORIZAR el lote de ESTA fila como excepción.

        Método PÚBLICO a propósito (Odoo 17 rechaza invocar privados por RPC).
        Solo aplica a las filas con un lote concreto y de tipo autorizable
        (mezclado/genérico/sin existencia). NO reasigna nada: el lote ya está en
        el documento; lo que se declara es que su uso es INTENCIONAL. La captura
        del motivo y la escritura viven en el wizard
        ``printflow.flow.lot.exception.authorize`` (con su guardia de permisos).
        """
        self.ensure_one()
        if not self.can_authorize:
            raise UserError(_(
                'Esta fila no tiene un lote que autorizar. Solo aplica a lotes '
                'mezclados, genéricos o sin existencia.'))
        wizard = self.env['printflow.flow.lot.exception.authorize'].create({
            'lot_id': self.lot_id.id,
            'product_id': self.product_id.id or False,
            'finding_code': self.finding_code or '',
            'source_model': self.res_model or '',
            'source_id': self.res_id or 0,
            'source_label': (
                self.picking_id.name or self.label or self.lot_id.name or ''),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Autorizar lote: %s') % self.lot_id.name,
            'res_model': 'printflow.flow.lot.exception.authorize',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _pf_authorize_selected_notification(self, message):
        """Notificación de AVISO (warning) con cierre de la bandeja.

        La usan las acciones sobre SELECCIÓN cuando no hay nada que procesar
        (autorizar, crear el lote sugerido) o cuando no queda ninguna fila
        elegible: nunca es un error.
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': _('PrintFlow'),
                'message': message,
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_authorize_selected(self):
        """AUTORIZA EN BLOQUE los lotes de las filas seleccionadas (un motivo).

        Método PÚBLICO a propósito (Odoo 17 rechaza invocar privados por RPC).

        * Toma las filas seleccionadas (``self``) o, si llega vacío, el
          ``active_domain`` del contexto (igual que ``action_apply_correction``).
        * Filtra las filas AUTORIZABLES y NO autorizadas aún (``can_authorize`` y
          ``not lot_is_authorized``) y se queda con los LOTES DISTINTOS (una
          autorización por lote; la restricción única evita duplicados).
        * Si no queda ninguno, notifica SIN abrir el wizard vacío.
        * Abre el wizard de bloque ``...authorize.bulk`` con UN motivo. La
          escritura la hace el motor, con su guardia de permisos.

        Requiere jefe de taller/administrador (``_pf_assert_can_clean``).
        """
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        records = self
        if not records:
            records = self.search(self.env.context.get('active_domain') or [])
        records = records.exists()
        if not records:
            return self._pf_authorize_selected_notification(
                _('No había lotes por autorizar.'))
        pending = records.filtered(
            lambda rec: rec.can_authorize and not rec.lot_is_authorized)
        lots = pending.mapped('lot_id')
        skipped = len(records) - len(pending)
        if not lots:
            return self._pf_authorize_selected_notification(_(
                'No había lotes por autorizar: ya estaban autorizados o no son '
                'autorizables.'))
        product = records[:1].product_id
        source_label = _(
            'Autorización en bloque: %(product)s (%(n)s lote(s))') % {
                'product': product.display_name if product else '',
                'n': len(lots)}
        # El wizard escribe UNA excepción formal por lote con UN código: solo se
        # declara si la selección es homogénea (la bandeja se puebla por producto
        # + estado). Con tipos mezclados no se inventa destino (conejera CT-3).
        codes = {rec.finding_code for rec in pending if rec.finding_code}
        wizard = self.env[
            'printflow.flow.lot.exception.authorize.bulk'].create({
                'lot_ids': [(6, 0, lots.ids)],
                'skipped': skipped,
                'finding_code': codes.pop() if len(codes) == 1 else '',
                'source_label': source_label,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Autorizar excepciones en bloque'),
            'res_model': 'printflow.flow.lot.exception.authorize.bulk',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── ASIGNACIÓN DE LOTE EN BLOQUE (acción sobre la SELECCIÓN) ──────────
    def action_assign_lot_bulk(self):
        """Abre el contenedor que asigna a CADA unidad su lote (grano = MOVIMIENTO).

        Método PÚBLICO a propósito (Odoo 17 rechaza invocar privados por RPC).
        Toma las filas seleccionadas (``self``) o, si llega vacío, el
        ``active_domain`` del contexto —igual que ``action_authorize_selected``.

        Flujo (D2/D5/D7):
        1. guardia de permisos ``_pf_assert_can_clean`` (jefe de taller/admin);
        2. delega la traducción de la selección a filas en el helper COMPARTIDO
           ``_pf_bulk_rows`` (filtra las asignables; el resto se OMITE y se
           cuenta; EXPANDE cada entrega en UNA fila por movimiento activo del
           producto —H-034/D1—, DESCARTA lo que no resuelve movimiento y
           DEDUPLICA por ``move.id``, D5);
        3. delega la construcción del contenedor en
           ``printflow.flow.lot.assign.bulk._pf_populate`` (que reutiliza el
           cálculo de candidatos y la dedupe/orden) y abre su form a
           ``target='new'``.

        NO escribe nada: el wizard es quien ejecuta el remedio NATIVO con su
        guardia y su motivo.
        """
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        records = self
        if not records:
            records = self.search(self.env.context.get('active_domain') or [])
        records = records.exists()
        if not records:
            return self._pf_authorize_selected_notification(
                _('Selecciona al menos una entrega sin lote para asignar.'))
        product, rows, omitted = self._pf_bulk_rows(records)
        if not product:
            return self._pf_authorize_selected_notification(_(
                'No había entregas sin lote asignables en la selección: se '
                'omiten los ítems que no admiten elegir lote.'))
        if not rows:
            return self._pf_authorize_selected_notification(_(
                'No había entregas con un movimiento activo en la selección.'))
        bulk = self.env['printflow.flow.lot.assign.bulk']._pf_populate(
            product, rows, omitted_count=omitted)
        if not bulk:
            return self._pf_authorize_selected_notification(_(
                'No se pudo preparar la asignación en bloque.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asignar lote en bloque'),
            'res_model': 'printflow.flow.lot.assign.bulk',
            'res_id': bulk.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'dialog_size': 'extra-large'},
        }

    @api.model
    def _pf_bulk_rows(self, records):
        """Prepara ``(product, rows, omitted)`` de una selección (SIN efectos).

        Traduce la selección a las filas CRUDAS que consume
        ``printflow.flow.lot.assign.bulk._pf_populate``. NO notifica ni escribe.
        Filtra las filas ASIGNABLES (``can_choose_lot`` y kind de entrega sin lote
        con producto); el resto se OMITE y se cuenta.

        GRANO = MOVIMIENTO (H-034/D1): cada fila ``pending_order`` (que apunta al
        ALBARÁN) se EXPANDE en UNA fila por ``stock.move`` ACTIVO del producto en
        ese albarán, con UNA sola búsqueda batch para todos los albaranes de la
        selección (sin N+1). Las filas ``missing_move`` conservan su movimiento y
        su documento. En las filas expandidas ``res_model``/``res_id`` siguen
        siendo el DOCUMENTO (``stock.picking``), porque es lo que usa la bitácora
        (``_pf_log_document``); el movimiento exacto viaja en ``move_id`` y es lo
        único que se escribe (R-3).

        Se DESCARTA lo que no resuelve movimiento y se DEDUPLICA por ``move.id``
        (D5/R-2: ``missing_move`` y ``pending_order`` pueden apuntar al MISMO
        movimiento). ``omitted`` cuenta las filas descartadas.

        Devuelve ``product`` VACÍO si no hay ninguna fila asignable, para que el
        llamador distinga ese caso del de "asignables pero sin movimiento".

        :param records: filas de la bandeja ya resueltas/``exists()``.
        :rtype: tuple[product.product, list[dict], int]
        """
        candidates = records.filtered(
            lambda rec: rec.can_choose_lot
            and rec.kind in _BULK_ASSIGNABLE_KINDS
            and rec.product_id)
        omitted = len(records) - len(candidates)
        if not candidates:
            return self.env['product.product'], [], omitted
        product = candidates[:1].product_id
        # (1) UNA sola búsqueda batch: movimientos ACTIVOS del producto en los
        # albaranes de las filas ``pending_order`` (grano = MOVIMIENTO).
        picking_ids = {
            rec.res_id for rec in candidates
            if rec.kind == 'pending_order'
            and rec.res_model == 'stock.picking' and rec.res_id}
        moves_by_picking = {}
        if picking_ids:
            for move in self.env['stock.move'].sudo().search([
                ('picking_id', 'in', list(picking_ids)),
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel')),
            ], order='id asc'):
                moves_by_picking.setdefault(
                    move.picking_id.id, []).append(move)
        rows = []
        seen_moves = set()
        for rec in candidates:
            if rec.kind == 'pending_order' and rec.res_model == 'stock.picking':
                moves = moves_by_picking.get(rec.res_id) or []
            else:
                moves = self._pf_document_move(
                    rec.kind, rec.res_model, rec.res_id, product,
                    rec.lot_name)[:1]
            if not moves:
                omitted += 1
                continue
            for move in moves:
                if move.id in seen_moves:
                    omitted += 1
                    continue
                seen_moves.add(move.id)
                sale_line = move.sale_line_id
                rows.append({
                    'kind': rec.kind,
                    'res_model': rec.res_model,
                    'res_id': rec.res_id,
                    'picking_id': (
                        rec.picking_id.id or move.picking_id.id or 0),
                    'move_id': move.id,
                    'label': rec.label or '',
                    'demand_qty': move.product_uom_qty or 0.0,
                    'location_id': rec.location_id.id or 0,
                    'scheduled_date': rec.scheduled_date or False,
                    'own_lot_name': (
                        (sale_line._get_exclusive_lot_name() or '')
                        if sale_line else (rec.own_lot_name or '')),
                    'sale_order_name': (
                        (sale_line.order_id.name or '') if sale_line else ''),
                })
        return product, rows, omitted

    # ── Excepción FORMAL de la fila (F4/F5): vía genérica, sin exigir lote ──
    def action_authorize_finding(self):
        """Abre el modal para AUTORIZAR el hallazgo de ESTA fila como excepción.

        Es la vía PRIMARIA para la MO terminada sin lote (``unassigned_mo``), que
        NO tiene lote que autorizar. Método PÚBLICO a propósito (Odoo 17 rechaza
        invocar privados por RPC). NO toca inventario: solo crea/reusa el registro
        de excepción.
        """
        self.ensure_one()
        if not self.can_authorize_finding:
            raise UserError(_(
                'Esta fila no tiene un hallazgo autorizable (o ya está '
                'autorizado).'))
        target_model, target_id = self._pf_formal_target()
        return self.env['printflow.finding.exception']._pf_authorize_action(
            self.finding_code,
            target_model,
            target_id,
            target_label=self._pf_formal_label(),
            lot_id=self.lot_id.id or False,
            source_model='printflow.flow.lot.tray',
            source_id=self.id,
            source_label=self.picking_id.name or self.label or '')

    def action_authorize_selected_findings(self):
        """AUTORIZA EN BLOQUE los hallazgos formales de las filas seleccionadas.

        Método PÚBLICO a propósito (Odoo 17 rechaza invocar privados por RPC).
        Toma las filas seleccionadas (``self``) o, si llega vacío, el
        ``active_domain`` del contexto. Abre el wizard de bloque con UNA línea por
        hallazgo elegible. Requiere jefe de taller/administrador.
        """
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        records = self
        if not records:
            records = self.search(self.env.context.get('active_domain') or [])
        records = records.exists()
        pending = records.filtered(lambda rec: rec.can_authorize_finding)
        if not pending:
            return self._pf_authorize_selected_notification(_(
                'No había hallazgos por autorizar: ya estaban autorizados o no '
                'son autorizables.'))
        lines = []
        for row in pending:
            target_model, target_id = row._pf_formal_target()
            lines.append((0, 0, {
                'finding_code': row.finding_code,
                'target_model': target_model,
                'target_id': target_id,
                'target_label': row._pf_formal_label(),
                'lot_id': row.lot_id.id or False,
            }))
        wizard = self.env[
            'printflow.finding.exception.authorize.bulk'].create({
                'line_ids': lines,
                'source_label': _(
                    'Autorización en bloque desde la bandeja de lote'),
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Autorizar excepciones formales en bloque'),
            'res_model': 'printflow.finding.exception.authorize.bulk',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── Confirmación de RIESGO (F5): las correcciones que tocan inventario ──
    def _pf_first_row(self):
        """Primera fila efectiva de la acción (``self`` o el ``active_domain``)."""
        records = self or self.search(self.env.context.get('active_domain') or [])
        return records.exists()[:1]

    def action_confirm_create_suggested_lots(self):
        """Abre la CONFIRMACIÓN de "Crear lote sugerido" (SECUNDARIA, toca stock)."""
        first = self._pf_first_row()
        if not first:
            return self._pf_authorize_selected_notification(
                _('No había filas seleccionadas.'))
        return self.env['printflow.lot.risk.confirm']._pf_open(
            'create_suggested_lots', first)

    def action_confirm_apply_correction(self):
        """Abre la CONFIRMACIÓN de "Corrección automática" (SECUNDARIA, toca stock)."""
        first = self._pf_first_row()
        if not first:
            return self._pf_authorize_selected_notification(
                _('No había filas por corregir.'))
        return self.env['printflow.lot.risk.confirm']._pf_open(
            'apply_correction', first)

    def action_create_suggested_lots(self):
        """Crea/asigna el lote SUGERIDO en las filas SELECCIONADAS (OF sin lote).

        A DIFERENCIA de ``action_apply_correction`` (que trabaja sobre TODO el
        producto: usa ``first.product_id`` e ignora la selección), esta acción
        actúa SOLO sobre la SELECCIÓN: por cada fila elegible crea/recupera el
        lote sugerido del pedido y lo asigna al terminado de ESA orden.

        * Toma las filas seleccionadas (``self``) o, si llega vacío, el
          ``active_domain`` del contexto (mismo patrón que
          ``action_apply_correction`` / ``action_authorize_selected``).
        * Filtra SOLO las elegibles: ``kind == 'unassigned_mo'`` y
          ``res_model == 'mrp.production'`` y ``res_id`` y ``own_lot_name`` (lote
          sugerido determinable). Las demás se OMITEN sin error.
        * NO reimplementa la creación del lote: delega en la PRIMITIVA ÚNICA del
          motor ``mrp.production.printflow_repair_lot`` (crea/recupera el lote
          exclusivo del pedido, lo asigna a ``lot_producing_id`` y re-reserva la
          entrega). Cada llamada va en ``try/except``: una fila que falle NO
          tumba el barrido; se cuentan ``creadas`` y ``fallidas``.

        Requiere jefe de taller/administrador (``_pf_assert_can_clean``).
        """
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        records = self
        if not records:
            records = self.search(self.env.context.get('active_domain') or [])
        records = records.exists()
        if not records:
            return self._pf_authorize_selected_notification(
                _('No había filas seleccionadas.'))
        eligible = records.filtered(
            lambda rec: rec.kind == 'unassigned_mo'
            and rec.res_model == 'mrp.production'
            and bool(rec.res_id)
            and bool(rec.own_lot_name))
        if not eligible:
            return self._pf_authorize_selected_notification(_(
                'No había filas de OF sin lote con lote sugerido entre las '
                'seleccionadas.'))
        omitted = len(records) - len(eligible)
        Production = self.env['mrp.production']
        created = 0
        failed = 0
        for row in eligible:
            try:
                Production.printflow_repair_lot(row.res_id)
                created += 1
            except Exception:  # noqa: BLE001 - una fila no tumba el barrido
                failed += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('PrintFlow'),
                'message': _(
                    'Lotes sugeridos creados: %s. Omitidas: %s. Fallidas: %s.'
                ) % (created, omitted, failed),
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_apply_correction(self):
        """Aplica la corrección del motor sobre la SELECCIÓN (o todas las filas).

        El botón de cabecera llega con las filas seleccionadas en ``self``. Sin
        selección, se toman TODAS las filas de la bandeja actual vía
        ``active_domain`` (la bandeja ya está acotada a un producto y un estado).
        La ejecución pasa por ``printflow.product.flow._pf_execute_lot_remedy``,
        que aplica el guardia de permisos (jefe de taller/admin → ``UserError``).
        """
        records = self
        if not records:
            records = self.search(self.env.context.get('active_domain') or [])
        records = records.exists()
        if not records:
            return {'type': 'ir.actions.act_window_close'}
        first = records[:1]
        message = self.env[
            'printflow.product.flow']._pf_execute_lot_remedy(
                first.product_id, first.remedy_target)
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
