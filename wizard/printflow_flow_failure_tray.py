# -*- coding: utf-8 -*-
"""Bandeja GENÉRICA de fallas guiadas del diagrama (PrintFlow · Fase 1).

``TransientModel`` de cabecera/contexto: convierte el "Solucionar" de una falla
en una decisión GESTIONABLE. NO conoce las fallas concretas: le pide a la
**falla** (resuelta por ``printflow.flow.failure.registry``) la severidad, el
resumen, los pasos, las EVIDENCIAS (una fila por ítem afectado) y las ACCIONES
por fila, y las materializa. Así una falla nueva NO toca esta superficie.

Diseño (OOP):
  * ``_pf_populate(host, code, product)``: puebla la bandeja bajo demanda;
  * ``action_run(line_id, action_key)``: despacha por LISTA BLANCA la acción de
    la fila (solo ``execute``/``navigate``/``close`` declarados por la falla);
  * ``action_cleanup_all()``: "SANEAR TODAS" — delega en el saneo que ya existe
    y REABRE la bandeja con el resumen del después;
  * las acciones con EFECTO las ejecuta la falla (``_pf_fault_execute``); las de
    ``navigate`` las resuelve aquí; ``close`` cierra.

Permisos
--------
VER la bandeja: cualquier ``base.group_user`` (ACL de lectura/creación; la
puebla el llamador). Las acciones con EFECTO pasan por el guardia que declara la
PROPIA falla (reconciliar = guardia configurable): quien no lo tiene, VE la
bandeja pero recibe ``UserError``.

Contrato::

    tray = env['printflow.flow.failure.tray']._pf_populate(host, code, product)
    action = tray.action_run(line_id, 'reconcile')
    action = tray.action_run(line_id, 'view_quant')
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Umbral de comparación de cantidades (mismo que el motor y el tablero).
_EPS = 1e-6

SEVERITY_SELECTION = [
    ('ok', 'Sano'),
    ('warning', 'Atención'),
    ('danger', 'Crítico'),
]


class PrintflowFlowFailureTray(models.TransientModel):
    """Cabecera/contexto de la bandeja genérica de fallas."""

    _name = 'printflow.flow.failure.tray'
    _description = 'Bandeja genérica de fallas guiadas (PrintFlow)'

    code = fields.Char(
        string='Falla', readonly=True,
        help='Código de la falla (clave del registry, p. ej. '
             '"lot_orphan_reservation").')
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True)
    severity = fields.Selection(
        SEVERITY_SELECTION, string='Semáforo', readonly=True)
    summary = fields.Char(string='Resumen', readonly=True)
    steps = fields.Text(string='Pasos', readonly=True)
    host_model = fields.Char(string='Modelo origen', readonly=True)
    host_res_id = fields.Integer(string='Id del origen', readonly=True)
    line_ids = fields.One2many(
        'printflow.flow.failure.tray.line', 'tray_id',
        string='Evidencias', readonly=True)

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, host, code=None, product=None):
        """Puebla la bandeja a partir de la FALLA del código indicado.

        Resuelve la falla por el registry (nunca vacío), le pide la observación,
        el encabezado, las evidencias y las acciones, y materializa una cabecera
        + una línea por evidencia + una acción por (línea, acción). Limpia las
        bandejas previas del MISMO host/código/producto (el wizard es el dueño
        transitorio).

        :param host: host del diagrama (p. ej. ``printflow.product.flow``).
        :param str code: código de la falla (``pf_cause``).
        :param product: ``product.product`` del hallazgo (o se deduce del host).
        :return: recordset de ``printflow.flow.failure.tray``.
        """
        Registry = self.env['printflow.flow.failure.registry']
        code = code or Registry._PF_FALLBACK_CODE
        failure = Registry._pf_failure_for(code)
        resolved = failure._pf_fault_code()
        if product is None and host is not None and 'product_id' in host._fields:
            product = host.product_id
        product = product.exists() if product else self.env['product.product']

        ctx = {'host': host, 'product': product, 'code': resolved}
        observation = failure._pf_fault_detect(host, ctx)
        ctx['observation'] = observation
        if isinstance(observation, dict) and observation.get('product'):
            ctx['product'] = observation['product']
        product = ctx.get('product') or self.env['product.product']

        host_model = host._name if host is not None else ''
        host_res_id = host.id if host is not None else 0
        # Limpieza idempotente: una sola bandeja viva por host/código/producto.
        self.sudo().search([
            ('code', '=', resolved),
            ('product_id', '=', product.id or False),
            ('host_model', '=', host_model),
            ('host_res_id', '=', host_res_id),
        ]).unlink()

        tray = self.create({
            'code': resolved,
            'product_id': product.id or False,
            'severity': failure._pf_fault_severity(ctx),
            'summary': failure._pf_fault_summary(ctx),
            'steps': '\n'.join(failure._pf_fault_steps(ctx) or []),
            'host_model': host_model,
            'host_res_id': host_res_id,
        })
        evidences = failure._pf_fault_evidences(ctx) or []
        action_tmpl = failure._pf_fault_actions(ctx) or []
        for index, row in enumerate(evidences, start=1):
            line = self.env['printflow.flow.failure.tray.line'].create(
                dict(row, tray_id=tray.id,
                     sequence=row.get('sequence', index)))
            for action in action_tmpl:
                self.env['printflow.flow.failure.tray.action'].create({
                    'line_id': line.id,
                    'key': action.get('key') or '',
                    'label': action.get('label') or '',
                    'kind': action.get('kind') or 'execute',
                    'enabled': action.get('enabled', True),
                    'primary': action.get('primary', False),
                    'sequence': action.get('sequence', 10),
                })
        return tray

    # ══════════════════════════════════════════════════════════════════════
    # DESPACHO (lista blanca)
    # ══════════════════════════════════════════════════════════════════════
    def action_run(self, line_id=None, action_key=None):
        """Despacha la acción de la fila (LISTA BLANCA). Método PÚBLICO.

        Solo despacha claves que EXISTAN como acción de la fila (las declaró la
        falla): cualquier otra clave NO se ejecuta (cierra). Nunca usa ``getattr``
        por convención ni cadenas de ``if tipo == ...`` sobre la falla: la rama
        la decide ``kind``.
        """
        self.ensure_one()
        line = self._pf_line(line_id)
        if not line:
            return {'type': 'ir.actions.act_window_close'}
        action = line.action_ids.filtered(
            lambda act: act.key == action_key)[:1]
        if not action or not action.enabled:
            # Clave fuera de la lista blanca: no se despacha.
            return {'type': 'ir.actions.act_window_close'}
        if action.kind == 'close':
            return {'type': 'ir.actions.act_window_close'}
        if action.kind == 'navigate':
            return self._pf_nav_action(line, action.key)
        # kind == 'execute': la ejecuta la falla (con su guardia interna).
        message = self._pf_failure()._pf_fault_execute(
            action.key, self._pf_build_ctx(line))
        return self._pf_refresh(message or _('Acción aplicada.'))

    def action_cleanup_all(self):
        """Sanea (suelta + re-reserva) TODAS las reservas colgadas del producto.

        Método PÚBLICO (botón de cabecera "SANEAR TODAS", solo en ``data_anomaly``).
        NO reinventa el saneo: llama a la MISMA puerta que la fila de salud
        (``printflow.stock.health._pf_cleanup_products``) detrás del MISMO guardia
        (``_pf_assert_can_clean``). Después REPUEBLA la bandeja en el sitio y
        devuelve el resumen en palabras de cuántos documentos quedan colgados
        (H-062: el operador no pierde la ventana ni rearma el camino).
        """
        self.ensure_one()
        if self.code != 'data_anomaly':
            # La vista esconde el botón (3 fallas comparten pantalla): el método
            # NO se fía de la vista y revalida el código.
            raise UserError(_('Este saneo es de la reserva colgada.'))
        self.env['printflow.stock.remedy']._pf_assert_can_clean()
        before = len(self.line_ids)
        result = self.env['printflow.stock.health']._pf_cleanup_products(
            self.product_id)
        tray, next_action = self._pf_reopen()
        if not tray:
            # Sin host no hay bandeja que repoblar: cierra con el aviso de hoy.
            cleaned = result['pickings']
            return self._pf_notify(
                _('Saneamiento: %(pickings)s albarán(es) re-asignado(s).')
                % {'pickings': cleaned},
                'success' if cleaned else 'warning',
                {'type': 'ir.actions.act_window_close'})
        left = len(tray.line_ids)
        if left == 0:
            message = _(
                'Reserva colgada saneada: el producto quedó limpio '
                '(0 documentos colgados; %(pickings)s albarán(es) '
                're-asignado(s)).') % {'pickings': result['pickings']}
            ntype = 'success'
        elif left < before:
            message = _(
                'Saneo parcial: quedan %(left)s documento(s) colgado(s) de '
                '%(before)s.') % {'left': left, 'before': before}
            ntype = 'warning'
        else:
            message = _(
                'No se pudo soltar ninguna reserva: siguen %(left)s '
                'documento(s) colgados.') % {'left': left}
            ntype = 'warning'
        return self._pf_notify(message, ntype, next_action)

    def action_close(self):
        """Cierra la bandeja (acción de cabecera)."""
        return {'type': 'ir.actions.act_window_close'}

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════
    def _pf_line(self, line_id):
        """Línea de evidencia a despachar (máximo una; vacío si es ambiguo)."""
        self.ensure_one()
        if line_id:
            return self.line_ids.filtered(lambda l: l.id == line_id)[:1]
        if len(self.line_ids) == 1:
            return self.line_ids[:1]
        return self.env['printflow.flow.failure.tray.line']

    def _pf_failure(self):
        """Falla (recordset) de esta bandeja, resuelta por el registry."""
        self.ensure_one()
        return self.env[
            'printflow.flow.failure.registry']._pf_failure_for(self.code)

    def _pf_host(self):
        """Host de origen (recordset) o ``None``."""
        self.ensure_one()
        if not self.host_model or not self.host_res_id:
            return None
        return self.env[self.host_model].browse(self.host_res_id).exists() or None

    def _pf_build_ctx(self, line):
        """Contexto para ``_pf_fault_execute`` (reconstruye la observación)."""
        self.ensure_one()
        ctx = {
            'host': self._pf_host(),
            'product': self.product_id,
            'code': self.code,
            'tray': self,
            'line': line,
        }
        failure = self._pf_failure()
        observation = failure._pf_fault_detect(ctx.get('host'), ctx)
        ctx['observation'] = observation
        if isinstance(observation, dict) and observation.get('product'):
            ctx['product'] = observation['product']
        return ctx

    def _pf_nav_action(self, line, action_key):
        """Acciones de navegación que resuelve la bandeja (solo lectura)."""
        self.ensure_one()
        if action_key == 'view_quant':
            if not line.res_id:
                return {'type': 'ir.actions.act_window_close'}
            return {
                'type': 'ir.actions.act_window',
                'name': line.lot_name or line.product_id.display_name or _('Quant'),
                'res_model': 'stock.quant',
                'res_id': line.res_id,
                'view_mode': 'form',
                'target': 'current',
            }
        if action_key == 'view_document':
            # §3.S: navega al DOCUMENTO de la fila (albarán u OF, solo lectura).
            model = line.document_model
            res_id = line.document_res_id
            if not model or not res_id:
                model, res_id = self._pf_resolve_document(line)
            if not model or not res_id:
                return {'type': 'ir.actions.act_window_close'}
            return {
                'type': 'ir.actions.act_window',
                'name': (line.document_name
                         or line.product_id.display_name
                         or _('Documento')),
                'res_model': model,
                'res_id': res_id,
                'view_mode': 'form',
                'target': 'current',
            }
        if action_key == 'view_supporting_moves':
            domain = [
                ('product_id', '=', line.product_id.id),
                ('state', 'not in', ('done', 'cancel')),
                ('quantity', '>', _EPS),
                ('location_id.usage', 'in', ('internal', 'transit')),
            ]
            if line.lot_id:
                domain.append(('lot_id', '=', line.lot_id.id))
            if line.location_id:
                domain.append(('location_id', '=', line.location_id.id))
            return {
                'type': 'ir.actions.act_window',
                'name': _('Movimientos que la respaldan'),
                'res_model': 'stock.move.line',
                'view_mode': 'tree,form',
                'domain': domain,
                'target': 'current',
            }
        return {'type': 'ir.actions.act_window_close'}

    def _pf_resolve_document(self, line):
        """Resuelve el documento desde la línea de evidencia (fallback §3.S).

        Si el ``document_model``/``document_res_id`` vinieron vacíos, se
        deducen desde la ``stock.move.line`` de la fila: su albarán
        (``picking_id``) o la OF del movimiento
        (``production_id``/``raw_material_production_id``).
        """
        self.ensure_one()
        if line.res_model != 'stock.move.line' or not line.res_id:
            return '', 0
        move_line = self.env['stock.move.line'].sudo().browse(
            line.res_id).exists()
        if not move_line:
            return '', 0
        picking = move_line.picking_id
        if picking:
            return 'stock.picking', picking.id
        production = (
            move_line.move_id.production_id
            or move_line.move_id.raw_material_production_id)
        if production:
            return 'mrp.production', production.id
        return '', 0

    def _pf_reopen(self):
        """REPUEBLA la bandeja en el sitio y devuelve ``(bandeja, acción)``.

        Captura ``code``/``product`` ANTES de llamar a ``_pf_populate`` porque
        ese poblado BORRA la bandeja vieja (es el dueño transitorio) y con ella
        ``self``. Sin host de origen no hay diagrama que repoblar: devuelve
        ``(vacío, None)`` y el llamador cae al comportamiento de siempre.
        """
        self.ensure_one()
        host = self._pf_host()
        if host is None:
            return self.env['printflow.flow.failure.tray'], None
        code = self.code
        product = self.product_id
        tray = self.env['printflow.flow.failure.tray']._pf_populate(
            host, code, product)
        return tray, {
            'type': 'ir.actions.act_window',
            'name': _('Bandeja de fallas'),
            'res_model': 'printflow.flow.failure.tray',
            'res_id': tray.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _pf_refresh(self, message, ntype='success'):
        """Avisa el resultado y REABRE la bandeja repoblada (H-062).

        Antes la bandeja se cerraba tras accionar: el operador quedaba sin el
        "después" ni el resumen. Ahora el aviso ENCADENA la bandeja nueva; si no
        hay host que repoblar, se conserva el respaldo de siempre (``reload``).
        """
        self.ensure_one()
        _tray, next_action = self._pf_reopen()
        return self._pf_notify(message, ntype, next_action)

    def _pf_notify(self, message, ntype='success', next_action=None):
        """Notificación estándar del resultado de una acción con efecto.

        ``next_action`` es lo que el cliente ejecuta al cerrar el aviso; por
        defecto RECARGA la vista (comportamiento histórico de la casa).
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': ntype, 'title': _('PrintFlow'), 'message': message,
                'sticky': False,
                'next': next_action or {'type': 'ir.actions.client',
                                        'tag': 'reload'},
            },
        }
