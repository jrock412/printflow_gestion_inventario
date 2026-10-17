# -*- coding: utf-8 -*-
"""Lista "quién me bloquea" — SIEMPRE por ENTREGA/ALBARÁN (PrintFlow).

TransientModel de SOLO LECTURA. La unidad de la lista es el **albarán de
entrega** (``stock.picking`` outgoing), no el pedido: así entran las ventas de
POS, que reservan stock sin tener ``sale.order``. Si la entrega sí tiene pedido,
se muestra además.

Se puebla BAJO DEMANDA (al pulsar "Ver quién me bloquea"), nunca en un compute.
Al ser transitorio no genera migración.

Orden (decisión cerrada):
  1. Fecha comprometida de entrega ascendente (lo más urgente primero).
  2. Sin fecha comprometida: antigüedad del pedido ascendente (el que lleva más
     tiempo reteniendo la reserva primero). Se cuenta desde la fecha del pedido
     (confirmación) y, si no la hay, desde la creación del albarán.
"""

from datetime import datetime

from odoo import _, api, fields, models

_EPS = 1e-6
_DATETIME_MAX = datetime.max


class PrintflowOrderBlockingReservation(models.TransientModel):
    """Una fila por albarán de entrega que retiene reserva del producto."""

    _name = 'printflow.order.blocking.reservation'
    _description = 'Reserva bloqueante por entrega (PrintFlow)'
    # PostgreSQL ordena NULL al final en ASC: primero las entregas CON fecha
    # comprometida, luego las que solo tienen antigüedad.
    _order = 'commitment_date asc, age_date asc, id'

    wizard_id = fields.Many2one(
        'printflow.order.diagnostic.wizard', string='Diagnóstico',
        required=False, ondelete='cascade',
    )
    product_flow_id = fields.Many2one(
        'printflow.product.flow', string='Diagrama de producto',
        required=False, ondelete='cascade',
        help='Wizard del diagrama de PRODUCTO sin venta que abrió esta lista.',
    )
    product_id = fields.Many2one(
        'product.product', string='Producto', required=True,
    )
    picking_id = fields.Many2one(
        'stock.picking', string='Entrega / Albarán', required=True,
    )
    picking_name = fields.Char(
        related='picking_id.name', string='Albarán', readonly=True,
    )
    operation_type = fields.Char(
        related='picking_id.picking_type_id.name', string='Tipo de operación',
        readonly=True,
    )
    picking_state = fields.Selection(
        related='picking_id.state', string='Estado albarán', readonly=True,
    )
    scheduled_date = fields.Datetime(
        related='picking_id.scheduled_date', string='Fecha programada',
        readonly=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Pedido', readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', readonly=True,
    )
    commitment_date = fields.Datetime(
        string='Fecha comprometida',
        help='Fecha comprometida de entrega: la del pedido si existe; si no, '
             'la programada del albarán. Manda en el orden de la lista.',
    )
    age_date = fields.Datetime(
        string='Antigüedad',
        help='Desde cuándo retiene la reserva: fecha del pedido (confirmación) '
             'o, si es una entrega sin pedido, su fecha de creación.',
    )
    reserved_qty = fields.Float(
        string='Cantidad reservada',
        help='Cantidad del producto inmovilizada por esta entrega.',
    )
    uom_id = fields.Many2one('uom.uom', string='UdM', readonly=True)
    order_state = fields.Char(string='Estado pedido', readonly=True)
    is_pos = fields.Boolean(
        string='Sin pedido (POS)',
        help='True si la entrega no tiene pedido de venta asociado (p. ej. POS).',
    )
    source_label = fields.Char(
        string='Origen', compute='_compute_source_label',
    )

    @api.depends('picking_name', 'sale_order_id', 'is_pos')
    def _compute_source_label(self):
        for rec in self:
            if rec.sale_order_id:
                rec.source_label = _('Entrega %(picking)s · Pedido %(order)s') % {
                    'picking': rec.picking_name or '',
                    'order': rec.sale_order_id.name or '',
                }
            else:
                rec.source_label = _('Entrega %s (sin pedido / POS)') % (
                    rec.picking_name or '')

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate_for_product(
            self, product, wizard=None, product_flow_id=None,
            exclude_picking_ids=None):
        """Crea las filas de la lista para un producto y su diagnóstico.

        Acepta el wizard de PEDIDO (``wizard``) o el wizard del diagrama de
        PRODUCTO (``product_flow_id``): ambos son el 'dueño' transitorio de la
        lista, cuya limpieza queda acotada a ese dueño.

        Reutiliza el ancla de ``stock.move.line`` (las RESERVAS): incluye los
        albaranes del POS cuyo ``sale_id`` es False. Excluye los albaranes ya
        entregados o cancelados (decisión 5) y los del propio pedido.

        :return: recordset de ``printflow.order.blocking.reservation`` recién
            poblado (y limpio de las filas previas del mismo producto).
        """
        if not product or (not wizard and not product_flow_id):
            return self.browse()
        exclude_picking_ids = set(exclude_picking_ids or [])
        move_lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
        ])
        # Agrupa por albarán y suma la cantidad reservada.
        by_picking = {}
        for move_line in move_lines:
            picking = move_line.picking_id
            if not picking or picking.state in ('done', 'cancel'):
                continue
            if picking.id in exclude_picking_ids:
                continue
            entry = by_picking.setdefault(
                picking, {'qty': 0.0, 'uom': move_line.product_uom_id})
            entry['qty'] += move_line.quantity_product_uom or 0.0
        # Limpia las filas previas de este producto en este diagnóstico.
        cleanup_domain = [('product_id', '=', product.id)]
        if wizard:
            cleanup_domain.append(('wizard_id', '=', wizard.id))
        else:
            cleanup_domain.append(('product_flow_id', '=', product_flow_id))
        self.sudo().search(cleanup_domain).unlink()
        records = self.browse()
        for picking, data in by_picking.items():
            so = picking.sale_id or picking.move_line_ids[:1].move_id.sale_line_id.order_id
            if so and so.state == 'cancel':
                continue
            commitment = (
                so.commitment_date if so and so.commitment_date
                else picking.scheduled_date
            )
            age = (so.date_order if so else False) or picking.create_date
            vals = {
                'product_id': product.id,
                'picking_id': picking.id,
                'sale_order_id': so.id if so else False,
                'partner_id': (so.partner_id if so else picking.partner_id).id,
                'commitment_date': commitment,
                'age_date': age,
                'reserved_qty': data['qty'],
                'uom_id': data['uom'].id if data['uom'] else False,
                'order_state': so.state if so else '',
                'is_pos': not bool(so),
            }
            if wizard:
                vals['wizard_id'] = wizard.id
            else:
                vals['product_flow_id'] = product_flow_id
            records |= self.create(vals)
        return records.sorted(
            lambda rec: (
                rec.commitment_date or _DATETIME_MAX,
                rec.age_date or _DATETIME_MAX,
            ))

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES (resolver la RAÍZ del bloqueante; nunca despojar)
    # ══════════════════════════════════════════════════════════════════════
    def action_open_picking(self):
        """Abre el albarán de entrega bloqueante."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.picking_name or _('Entrega bloqueante'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_root(self):
        """Guía a la RAÍZ del bloqueante: su diagnóstico de pedido o su ficha.

        Regla de oro: no se libera ni recorta la reserva ajena. Se lleva al
        operador al **Nivel 1 de ESE pedido** para resolver allí la causa raíz
        (generar su OF, corregir su BOM, comprar su insumo...).
        """
        self.ensure_one()
        if self.sale_order_id:
            board = self.env['printflow.order.board'].search(
                [('sale_order_id', '=', self.sale_order_id.id)], limit=1)
            if board:
                return board.action_open_diagnostic_wizard()
            return {
                'type': 'ir.actions.act_window',
                'name': self.sale_order_id.name,
                'res_model': 'sale.order',
                'res_id': self.sale_order_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        # Entrega sin pedido (POS): se abre el escáner del producto.
        wizard = self.env['printflow.product.diagnostic.wizard'].create({
            'product_id': self.product_id.id,
            'origin': 'order',
            'origin_model': 'stock.picking',
            'origin_res_id': self.picking_id.id,
            'origin_label': self.picking_name or '',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Diagnóstico de Producto'),
            'res_model': 'printflow.product.diagnostic.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }
