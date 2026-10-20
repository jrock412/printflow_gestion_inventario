# -*- coding: utf-8 -*-
"""Excepción FORMAL genérica autorizada (PrintFlow · GI).

Generaliza el patrón de "lote autorizado" (que hoy vive en el motor
``x_product_dimensional_pricing`` como ``printflow.lot.exception``) a CUALQUIER
hallazgo formal sobre CUALQUIER documento: "para el hallazgo formal X, sobre el
registro Y (modelo + id), existe una excepción autorizada".

Regla dura (skill ``regla-trabajo-odoo-17-ce``): autorizar una excepción es SOLO
crear/archivar un registro de ESTA tabla (y, como bitácora secundaria, dejar una
nota ``message_post``). **Nunca** toca ``stock.quant``, ``stock.move``,
``stock.move.line``, ``stock.lot`` ni ningún documento de negocio: es una decisión
consciente que "silencia" un hallazgo FORMAL. La válvula de escape existe para
que un requisito formal (p. ej. "toda MO debe tener lote") NUNCA fuerce a escribir
inventario.

Revocar = ARCHIVAR (``active = False``): la historia se conserva y re-autorizar el
mismo hallazgo REUSA el registro archivado (restricción única por
``finding_code`` + ``target_model`` + ``target_id`` + ``company_id``).

Contrato::

    exc = env['printflow.finding.exception']._pf_authorize(
        'lot_unassigned_finished', 'mrp.production', mo.id, reason='...')
    ids = env['printflow.finding.exception']._pf_suppressed_targets(
        'lot_unassigned_finished')
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PrintflowFindingException(models.Model):
    """Excepción autorizada de un hallazgo formal sobre un registro dado."""

    _name = 'printflow.finding.exception'
    _description = 'Excepción formal autorizada (PrintFlow)'
    _order = 'authorized_date desc, id desc'

    finding_code = fields.Char(
        string='Hallazgo', required=True, index=True,
        help='Clave del hallazgo formal autorizado (lista blanca del registry '
             '``printflow.finding.exception.registry``). El "qué".')
    target_model = fields.Char(
        string='Modelo destino', required=True, index=True,
        help='Modelo del registro afectado (p. ej. ``mrp.production``).')
    target_id = fields.Integer(
        string='Id destino', required=True, index=True,
        help='Id del registro afectado.')
    target_label = fields.Char(
        string='Registro afectado',
        help='Etiqueta legible del registro afectado (nombre de la MO, etc.).')
    lot_id = fields.Many2one(
        'stock.lot', string='Lote', ondelete='set null', index=True,
        help='Lote del hallazgo (solo para hallazgos basados en lote; puente con '
             'el patrón de excepciones de lote).')
    product_id = fields.Many2one(
        'product.product', string='Producto', compute='_compute_product_id',
        store=True, readonly=True, index=True,
        help='Producto del registro afectado (derivado; para agrupar/filtrar).')
    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True,
        default=lambda self: self.env.company)
    reason = fields.Text(
        string='Motivo',
        help='Justificación por la que se autoriza el hallazgo como excepción.')
    authorized_by_id = fields.Many2one(
        'res.users', string='Autorizado por', readonly=True,
        default=lambda self: self.env.user,
        help='Usuario que autorizó la excepción (se fija al autorizar).')
    authorized_date = fields.Datetime(
        string='Autorizado el', readonly=True, default=fields.Datetime.now,
        help='Momento en que se autorizó la excepción.')
    active = fields.Boolean(
        string='Activa', default=True,
        help='Desmarca (archiva) para REVOCAR la autorización. La historia se '
             'conserva: re-autorizar el mismo hallazgo reusa este registro.')
    source_model = fields.Char(
        string='Modelo origen', readonly=True,
        help='Modelo del documento desde el que se autorizó (trazabilidad).')
    source_id = fields.Integer(
        string='Id origen', readonly=True,
        help='Id del documento desde el que se autorizó (trazabilidad).')
    source_label = fields.Char(
        string='Documento origen', readonly=True,
        help='Etiqueta legible del documento de origen (trazabilidad).')

    _sql_constraints = [
        ('pf_finding_exception_uniq',
         'unique(finding_code, target_model, target_id, company_id)',
         'Ya existe una autorización para este hallazgo en este registro y '
         'compañía.'),
    ]

    # ══════════════════════════════════════════════════════════════════════
    # CÓMPUTO / VALIDACIÓN
    # ══════════════════════════════════════════════════════════════════════
    @api.depends('lot_id', 'target_model', 'target_id')
    def _compute_product_id(self):
        """Deriva el producto del registro afectado (mejor esfuerzo, sin error)."""
        for rec in self:
            product = rec.lot_id.product_id
            if not product:
                product = rec._pf_target_product()
            rec.product_id = product

    def _pf_target_product(self):
        """``product.product`` del registro afectado (o vacío si no es derivable).

        Solo LEE: busca ``product_id`` en el modelo destino si ese modelo lo
        expone. Un modelo desconocido, un id inexistente o un modelo sin
        ``product_id`` devuelven el recordset vacío sin romper.
        """
        self.ensure_one()
        model_name = self.target_model or ''
        if not model_name or not self.target_id:
            return self.env['product.product']
        try:
            Model = self.env[model_name].sudo()
        except KeyError:
            return self.env['product.product']
        if 'product_id' not in Model._fields:
            return self.env['product.product']
        target = Model.browse(self.target_id).exists()
        return target.product_id if target else self.env['product.product']

    @api.constrains('finding_code')
    def _pf_check_finding_code(self):
        """El hallazgo debe estar en la lista blanca del registry."""
        Registry = self.env['printflow.finding.exception.registry']
        supported = Registry._pf_supported()
        for rec in self:
            if rec.finding_code and rec.finding_code not in supported:
                raise ValidationError(_(
                    'El hallazgo "%s" no admite autorización como excepción.')
                    % rec.finding_code)

    # ══════════════════════════════════════════════════════════════════════
    # CONSULTA (la usa el adaptador de filtrado)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_suppressed_targets(self, finding_code, company=None):
        """Set de ids de destino autorizados para un hallazgo (UNA consulta).

        Se acota por el ``target_model`` que declara el registry: los ids de
        ``stock.move`` y de ``stock.lot`` son secuencias distintas, así que sin
        este filtro un id de movimiento apagaría el lote equivocado (H-066).

        La búsqueda por defecto excluye las archivadas (``active = False``), así
        que solo devuelve las autorizaciones VIGENTES.

        :rtype: set[int]
        """
        if not finding_code:
            return set()
        target_model = self.env[
            'printflow.finding.exception.registry']._pf_target_model(
                finding_code)
        if not target_model:
            return set()
        company = company or self.env.company
        exceptions = self.sudo().search([
            ('finding_code', '=', finding_code),
            ('target_model', '=', target_model),
            ('company_id', '=', company.id),
        ])
        return set(exceptions.mapped('target_id'))

    @api.model
    def _pf_is_suppressed(self, finding_code, target_model, target_id,
                          company=None):
        """¿Está autorizado (activo) ese hallazgo sobre ese registro?"""
        if not (finding_code and target_model and target_id):
            return False
        company = company or self.env.company
        return bool(self.sudo().search_count([
            ('finding_code', '=', finding_code),
            ('target_model', '=', target_model),
            ('target_id', '=', target_id),
            ('company_id', '=', company.id),
        ]))

    # ══════════════════════════════════════════════════════════════════════
    # AUTORIZACIÓN (una sola vía, varias superficies)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_authorize(self, finding_code, target_model, target_id, reason=None,
                      target_label=None, lot_id=None, source_model=None,
                      source_id=None, source_label=None):
        """Crea o REUSA la excepción activa de un hallazgo (no duplica).

        Pasa por el guardia ``printflow.stock.remedy._pf_assert_can_clean()``
        (jefe de taller/admin). Deja una nota (``message_post``) en el documento
        afectado como bitácora SECUNDARIA (best effort). NO toca inventario.

        :return: la excepción activa (``printflow.finding.exception``).
        """
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        if not finding_code or not target_model or not target_id:
            return self.browse()
        if finding_code not in self.env[
                'printflow.finding.exception.registry']._pf_supported():
            raise ValidationError(_(
                'El hallazgo "%s" no admite autorización como excepción.')
                % finding_code)
        Exception = self.sudo().with_context(active_test=False)
        existing = Exception.search([
            ('finding_code', '=', finding_code),
            ('target_model', '=', target_model),
            ('target_id', '=', target_id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        vals = {
            'reason': (reason or '').strip(),
            'target_label': target_label or '',
            'lot_id': lot_id or False,
            'authorized_by_id': self.env.user.id,
            'authorized_date': fields.Datetime.now(),
            'source_model': source_model or '',
            'source_id': source_id or 0,
            'source_label': source_label or '',
            'active': True,
        }
        if existing:
            existing.write(vals)
            record = existing
        else:
            vals.update({
                'finding_code': finding_code,
                'target_model': target_model,
                'target_id': target_id,
                'company_id': self.env.company.id,
            })
            record = Exception.create(vals)
        record._pf_post_audit_note()
        return record

    @api.model
    def _pf_authorize_lot_finding(self, finding_code, lot, reason=None,
                                  source_model=None, source_id=None,
                                  source_label=None):
        """Autoriza el hallazgo FORMAL de un lote, si su destino es el lote.

        Es la puerta ÚNICA de la vía "Autorizar lote" (la del operador). El
        registry declara que ``lot_generic`` / ``lot_no_stock`` / ``lot_mixed``
        viven sobre ``stock.lot``; sin esta autorización, la escritura en
        ``printflow.lot.exception`` (que apaga la MEZCLA en el motor) NO apaga el
        hallazgo y el nodo Entrega sigue pintado (H-065).

        Si no hay código, no hay lote, o el destino declarado NO es el lote, no
        hace nada: el comportamiento anterior queda intacto.

        :return: la excepción formal (recordset vacío si no aplica).
        """
        if not (finding_code and lot):
            return self.browse()
        lot.ensure_one()
        Registry = self.env['printflow.finding.exception.registry']
        if Registry._pf_target_model(finding_code) != 'stock.lot':
            return self.browse()
        return self._pf_authorize(
            finding_code, 'stock.lot', lot.id, reason=reason,
            target_label=lot.name, lot_id=lot.id, source_model=source_model,
            source_id=source_id, source_label=source_label)

    def _pf_post_audit_note(self):
        """Bitácora SECUNDARIA en el documento afectado (best effort).

        Es una NOTA (``mail.mt_note``), no un cambio de campos de negocio. Si el
        destino no admite ``message_post``, se omite sin error.
        """
        self.ensure_one()
        try:
            Model = self.env[self.target_model].sudo()
        except KeyError:
            return
        target = Model.browse(self.target_id).exists() if self.target_id else Model
        if not target or not hasattr(target, 'message_post'):
            return
        target.message_post(
            body=_(
                'PrintFlow: hallazgo "%(label)s" autorizado como excepción por '
                '%(user)s. Motivo: %(reason)s') % {
                    'label': self._pf_registry_label(),
                    'user': self.authorized_by_id.display_name or '',
                    'reason': self.reason or _('(sin motivo)'),
                },
            message_type='notification',
            subtype_xmlid='mail.mt_note')

    def _pf_registry_label(self):
        """Etiqueta legible del hallazgo (según el registry)."""
        self.ensure_one()
        return self.env[
            'printflow.finding.exception.registry']._pf_label(self.finding_code)

    # ══════════════════════════════════════════════════════════════════════
    # REVOCAR / REACTIVAR
    # ══════════════════════════════════════════════════════════════════════
    def action_pf_revoke(self):
        """Archiva (REVOCA) la autorización. Requiere jefe de taller/admin."""
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        self.write({'active': False})
        return True

    def action_pf_reactivate(self):
        """Reactiva (desarchiva) la autorización. Requiere jefe de taller/admin."""
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        self.write({'active': True})
        return True

    # ══════════════════════════════════════════════════════════════════════
    # ENTRADA GENÉRICA (la abre cualquier superficie de GI)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_authorize_action(self, finding_code, target_model, target_id,
                             target_label=None, lot_id=None,
                             source_model=None, source_id=None,
                             source_label=None):
        """Abre el modal de autorización prellenado (devuelve ``act_window``)."""
        wizard = self.env['printflow.finding.exception.authorize'].create({
            'finding_code': finding_code or '',
            'target_model': target_model or '',
            'target_id': target_id or 0,
            'target_label': target_label or '',
            'lot_id': lot_id or False,
            'source_model': source_model or '',
            'source_id': source_id or 0,
            'source_label': source_label or '',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Autorizar excepción'),
            'res_model': 'printflow.finding.exception.authorize',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
