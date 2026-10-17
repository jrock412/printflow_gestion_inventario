# -*- coding: utf-8 -*-
"""Línea de pendientes por DOCUMENTO — lista REAL (PrintFlow · Fase 4b).

Una fila por documento pendiente (albarán, OF, compra o venta). Es un
``TransientModel`` (cero migración) que NO reimplementa el motor: su contenido
lo generan ``printflow.flow.pending._pf_pending_document_lines`` al poblar.

Rediseño v2: se ABRE COMO LISTA REAL (``ir.actions.act_window`` + ``<search>``),
con SELECCIÓN NATIVA de Odoo. La validación masiva de entregas vive en una
server action NATIVA (``binding_model_id`` + ``binding_view_types='list'``); se
eliminaron el booleano ``pf_selected`` y el ``center_id`` del Centro de Salud.

Regla Q11: ``sudo()`` SOLO para leer/verificar el documento al navegar y para
limpiar el tablero transitorio propio; la validación de negocio corre sin
``sudo`` (permisos del usuario).
"""

from odoo import _, api, fields, models

# Nodos del flujo con documento propio. Se reutiliza como selección de la vista
# para no duplicar etiquetas (ver ``printflow.flow.pending``).
PENDING_NODE_SELECTION = [
    ('purchase', 'Compras'),
    ('receipt', 'Recepciones'),
    ('production', 'Fabricación'),
    ('delivery', 'Entregas'),
    ('sale', 'Ventas'),
]


class PrintflowNodePendingLine(models.TransientModel):
    """Una fila por documento pendiente por nodo (lista real)."""

    _name = 'printflow.node.pending.line'
    _description = 'Documento pendiente por nodo (PrintFlow)'
    _order = 'node_key, scheduled_date, id'

    node_key = fields.Selection(
        PENDING_NODE_SELECTION, string='Nodo', required=True, readonly=True)
    res_model = fields.Char(string='Modelo', readonly=True)
    res_id = fields.Integer(string='Id del documento', readonly=True)
    name = fields.Char(string='Documento', readonly=True)
    state_label = fields.Char(string='Estado', readonly=True)
    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True)
    scheduled_date = fields.Datetime(
        string='Fecha programada', readonly=True)
    bulk_action_xmlid = fields.Char(string='Acción masiva', readonly=True)
    is_bulk = fields.Boolean(
        string='Validable', compute='_compute_is_bulk', store=True,
        help='La fila tiene una acción masiva asociada (Fase 4b: solo entregas).')
    # F7: columna "Documento" navegable (par modelo+id como UN valor). El gesto
    # natural de abrir el documento de la fila es el clic aquí; por eso la vista
    # ya NO lleva el botón "Abrir". ADICIONAL a ``name``/``res_model``/``res_id``.
    document_ref = fields.Reference(
        selection='_pf_document_ref_selection', string='Documento',
        compute='_compute_document_ref', search='_pf_search_document_ref',
        readonly=True,
        help='Documento pendiente de la fila como un solo valor navegable.')

    @api.depends('bulk_action_xmlid')
    def _compute_is_bulk(self):
        """La fila es validable en lote solo si tiene acción masiva."""
        for line in self:
            line.is_bulk = bool(line.bulk_action_xmlid)

    @api.model
    def _pf_document_ref_selection(self):
        """Lista blanca (modelo, etiqueta) del campo ``document_ref``."""
        return [
            ('stock.picking', _('Albarán')),
            ('mrp.production', _('Orden de fabricación')),
            ('purchase.order', _('Orden de compra')),
            ('sale.order', _('Pedido de venta')),
        ]

    @api.depends('res_model', 'res_id')
    def _compute_document_ref(self):
        """Empaqueta el par (modelo, id) sin consultar la BD (recordset lazy)."""
        allowed = {model for model, _label in self._pf_document_ref_selection()}
        for line in self:
            if line.res_model in allowed and line.res_id:
                line.document_ref = self.env[line.res_model].browse(line.res_id)
            else:
                line.document_ref = False

    @api.model
    def _pf_search_document_ref(self, operator, value):
        """Traduce la búsqueda de "Documento" a las fuentes almacenadas."""
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

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA (aislado por usuario)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, product_ids=None, node_keys=None, board=None,
                     limit=None):
        """Reconstruye la lista con los documentos pendientes (sin N+1).

        Descarta SOLO las filas del usuario actual (``create_uid``), de modo que
        dos usuarios no se pisen el tablero transitorio. El resto del trabajo lo
        hace el motor ``printflow.flow.pending`` (una ``search_read`` por nodo).

        :param list product_ids: filtro opcional de ``product.product``.
        :param list node_keys: nodos a enumerar (``None`` = todos los habilitados).
        :param board: ``printflow.order.board`` opcional (exclusión Q9).
        :param int limit: tope de filas POR NODO (``None`` = parámetro del motor).
        :rtype: printflow.node.pending.line
        """
        pending = self.env['printflow.flow.pending']
        if limit is None:
            limit = pending._pf_node_pending_limit()
        self.sudo().search([('create_uid', '=', self.env.uid)]).unlink()
        vals_list = pending._pf_pending_document_lines(
            product_ids=product_ids, node_keys=node_keys, board=board,
            limit=limit)
        if not vals_list:
            return self.browse()
        return self.create(vals_list)

    @api.model
    def action_open_pending(self, node_key=None, product_id=None):
        """Entry point: puebla y abre la lista REAL de pendientes.

        :param str node_key: nodo opcional por el que arrancar filtrado (vacío =
            TODOS los nodos, según decisión del plan).
        :param int product_id: producto opcional del que acotar los pendientes.
        """
        self._pf_populate(
            product_ids=[product_id] if product_id else None,
            node_keys=[node_key] if node_key else None)
        context = {}
        if node_key:
            context['search_default_filter_%s' % node_key] = 1
        search_view = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_node_pending_line_view_search')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pendientes'),
            'res_model': self._name,
            'view_mode': 'list',
            'target': 'current',
            'search_view_id': search_view.id,
            'domain': [('create_uid', '=', self.env.uid)],
            'context': context,
        }

    # ══════════════════════════════════════════════════════════════════════
    # DISPATCHER Y VALIDACIÓN MASIVA
    # ══════════════════════════════════════════════════════════════════════
    def action_pf_dispatch(self):
        """Abre el DOCUMENTO de la fila (o cae al ruteo por nodo).

        ``sudo()`` SOLO para leer/verificar que el documento existe y navegar
        (Q11); nunca escribe. Si el documento desapareció (fue validado o
        cancelado), cae al ruteo por nodo de ``printflow.flow.pending``.
        """
        self.ensure_one()
        if self.res_model and self.res_id:
            record = self.env[self.res_model].sudo().browse(
                self.res_id).exists()
            if record:
                return {
                    'type': 'ir.actions.act_window',
                    'name': record.display_name,
                    'res_model': self.res_model,
                    'res_id': self.res_id,
                    'view_mode': 'form',
                    'target': 'current',
                }
        return self.env['printflow.flow.pending']._pf_node_pending_action(
            self.node_key, self.product_id)

    @api.model
    def action_pf_validate_selected(self):
        """Valida la SELECCIÓN NATIVA de entregas (server action de lista).

        Sin booleano ni centro: resuelve la selección nativa (``active_ids``),
        separa las ENTREGAS (con acción masiva) del resto y reutiliza la ventana
        única ``printflow.delivery.bulk.result`` del motor existente
        ``stock.picking.action_pf_bulk_validate_deliveries`` (savepoint por
        albarán). Las filas no entregables SOLO avisan; nunca tumban el lote.
        ``sudo()`` NUNCA se usa para la validación (Q11): corre con los permisos
        del usuario.
        """
        active_ids = self.env.context.get('active_ids')
        lines = self.browse(active_ids).exists() if active_ids else self
        deliverables = lines.filtered(
            lambda l: l.node_key == 'delivery' and l.bulk_action_xmlid)
        others = lines - deliverables
        if not deliverables and not others:
            return self._pf_notify(
                _('Selecciona al menos una entrega para validar.'), 'warning')

        result = False
        if deliverables:
            picking_ids = deliverables.mapped('res_id')
            # Se PISA ``active_ids`` para que la acción masiva trabaje sobre las
            # entregas seleccionadas; se pasa ``active_domain`` vacío para no
            # heredar un filtro de la lista.
            result = self.env['stock.picking'].with_context(
                active_ids=picking_ids, active_domain=[],
            ).action_pf_bulk_validate_deliveries()

        if others:
            message = _('Se omiten %(n)s fila(s) no entregables: %(nodes)s.') % {
                'n': len(others),
                'nodes': ', '.join(sorted(set(others.mapped('node_key')))),
            }
            if result and result.get('type') == 'ir.actions.act_window':
                # Aviso + ventana única del resultado existente (encadenada).
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('PrintFlow'),
                        'message': message,
                        'type': 'warning',
                        'sticky': False,
                        'next': result,
                    },
                }
            return self._pf_notify(message, 'warning')
        if result:
            return result
        return self._pf_notify(
            _('No hay entregas seleccionadas.'), 'warning')

    @api.model
    def _pf_notify(self, message, ntype='info'):
        """Notificación estándar de la lista de pendientes."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PrintFlow'),
                'message': message,
                'type': ntype,
                'sticky': bool(message),
            },
        }
