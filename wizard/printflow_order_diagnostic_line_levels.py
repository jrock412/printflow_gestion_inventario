# -*- coding: utf-8 -*-
"""Jerarquía y semáforo por línea del diagnóstico de pedido (PrintFlow).

Extiende ``printflow.order.diagnostic.wizard.line`` (TransientModel) de forma
ADITIVA y sin campos almacenados en modelos persistentes:

  * ``parent_line_id`` / ``child_line_ids``: cuelgan cada componente de su
    producto PRIMARIO (primer terminado que lo consume). Un componente
    compartido por varios terminados NO genera M2m: se cuelga del primero.
  * ``severity`` y los estados de nodo (venta / inventario / compras /
    fabricación): semáforo por producto/componente, calculado en el snapshot.
  * ``failure_ids``: una fila por nodo roto (ver
    ``printflow.order.diagnostic.failure``).

No toca la detección ni agrega columnas: todo vive en el modelo transitorio.
"""

from odoo import _, api, fields, models


class PrintflowOrderDiagnosticWizardLine(models.TransientModel):
    """Detalle por producto/componente con jerarquía y semáforo por nodo."""

    _inherit = 'printflow.order.diagnostic.wizard.line'

    # MEJORA A: primero las líneas con necesidad REAL, y al final las de solo
    # display (producto ya entregado), que van siempre sanas.
    _order = 'is_display_only asc, deficit_qty desc, is_over_reserved desc, id'

    # ── Jerarquía (producto terminado -> componentes) ───────────────────
    parent_line_id = fields.Many2one(
        'printflow.order.diagnostic.wizard.line',
        string='Producto primario',
        ondelete='cascade',
        help='Producto terminado del que cuelga este componente. El componente '
             'compartido se cuelga del PRIMER terminado que lo consume.',
    )
    child_line_ids = fields.One2many(
        'printflow.order.diagnostic.wizard.line',
        'parent_line_id',
        string='Componentes',
        domain=[('line_kind', 'in', ['component', 'estimated'])],
    )

    # ── Semáforo por línea ──────────────────────────────────────────────
    severity = fields.Selection(
        [('ok', 'Saludable'), ('warning', 'Atención'), ('danger', 'Crítico')],
        string='Semáforo',
        help='Peor caso de los nodos del producto/componente (mismo umbral que '
             'la salud del tablero).',
    )
    sale_status = fields.Selection(
        [('ok', 'OK'), ('pending', 'BORRADOR'), ('error', 'CANCELADO'), ('na', 'N/A')],
        string='Venta',
    )
    stock_status = fields.Selection(
        [('ok', 'OK'), ('deficit', 'SIN STOCK'), ('over', 'SOBREPEDIDO'), ('na', 'N/A')],
        string='Inventario',
    )
    purchase_status = fields.Selection(
        [('ok', 'OK'), ('missing', 'FALTA COMPRAR'), ('pending', 'POR RECIBIR'), ('na', 'N/A')],
        string='Compras',
    )
    production_status = fields.Selection(
        [('ok', 'OK'), ('design', 'ARTE PENDIENTE'), ('no_mo', 'SIN ORDEN'),
         ('material', 'FALTA MATERIAL'), ('late', 'RETRASO'),
         ('to_launch', 'SIN LANZAR'), ('no_supply', 'SIN INSUMOS'),
         ('in_progress', 'EN PROCESO'),
         ('na', 'N/A')],
        string='Fabricación',
    )
    # Entrega: alimentada por el MISMO snapshot que usa el tablero. Para
    # componentes/estimados siempre 'na'; para terminados, ok/pending/partial.
    delivery_status = fields.Selection(
        [('ok', 'ENTREGADO'), ('pending', 'PENDIENTE'),
         ('partial', 'PARCIAL'), ('na', 'N/A')],
        string='Entrega',
    )
    root_cause_node = fields.Selection(
        [('sale', 'Venta / POS'), ('stock', 'Inventario'),
         ('supply', 'Almacén insumos'), ('purchase', 'Compras'),
         ('production', 'Fabricación'), ('delivery', 'Entrega')],
        string='Nodo de quiebre',
    )
    failed_node_count = fields.Integer(string='Nodos rotos')
    failure_summary = fields.Char(string='Qué pasa')

    # ── Componentes ─────────────────────────────────────────────────────
    has_components = fields.Boolean(string='Tiene componentes')
    component_count = fields.Integer(string='Componentes')

    # ── Aviso informativo: órdenes de entrega pendientes ────────────────
    # NO es una falla ni toca el motor de salud: solo informa cuántos
    # albaranes de entrega AJENOS (no done/cancel) esperan este producto. Lo
    # llena el snapshot por LOTE; los componentes quedan en 0. Es aditivo y
    # vive en el modelo transitorio: cero migración.
    pending_delivery_order_count = fields.Integer(
        string='Órdenes de entrega pendientes',
        default=0,
        help='Albaranes de entrega (outgoing, no done/cancel) de OTROS orígenes '
             'que contienen este producto en sus movimientos. Es un aviso '
             'informativo, nunca una falla.',
    )
    has_pending_delivery_orders = fields.Boolean(
        string='Tiene órdenes de entrega pendientes',
        compute='_compute_has_pending_delivery_orders',
        help='True cuando el producto tiene al menos un albarán de entrega ajeno '
             'pendiente. Solo alimenta la vista: no genera fallas.',
    )

    @api.depends('pending_delivery_order_count')
    def _compute_has_pending_delivery_orders(self):
        """Bandera de pantalla derivada del conteo (no almacena nada nuevo)."""
        for line in self:
            line.has_pending_delivery_orders = (
                line.pending_delivery_order_count > 0)

    # ── Atribución por PORCIÓN de la compra agrupada (1 OC = N pedidos) ──
    # Todos son campos del modelo TRANSITORIO: cero migración. ``incoming_qty``
    # (heredado) pasa a ser la porción PROPIA del pedido; el global queda como
    # contexto para la etiqueta "porción por pedido".
    incoming_global_qty = fields.Float(string='En camino (global)')
    own_supply_qty = fields.Float(string='Compra propia')
    own_received_qty = fields.Float(string='Recibido propio')
    incoming_own = fields.Float(string='En camino propio')
    own_reserved_qty = fields.Float(string='Reservado propio')
    own_portion_kind = fields.Selection(
        [('none', 'Sin porción'), ('sale_line', 'Línea de venta'),
         ('linked', 'Compra vinculada'), ('prorated', 'Prorrateada')],
        string='Tipo de porción', default='none',
    )
    origin_group = fields.Char(
        string='Grupo de origen',
        help='Pedidos que comparten la misma OC (origen agrupado).',
    )

    # ── Fallas por nodo (una fila por nodo roto) ────────────────────────
    failure_ids = fields.One2many(
        'printflow.order.diagnostic.failure', 'line_id', string='Fallas',
    )

    # ── Fabricabilidad y ROLL-UP del subárbol (Nivel 1 / línea de tiempo) ─
    # Todos son campos del modelo TRANSITORIO: cero columnas persistentes.
    # ``is_manufacturable`` lo decide el motor (BoM o ruta de fabricación).
    is_manufacturable = fields.Boolean(string='Fabricable')
    # Para las líneas NO terminadas, los ``flow_*`` son sus propios ``*``.
    # Para el terminado, son el peor caso (roll-up) de su subárbol.
    flow_sale_status = fields.Selection(
        [('ok', 'OK'), ('pending', 'BORRADOR'), ('error', 'CANCELADO'), ('na', 'N/A')],
        string='Venta (flujo)',
    )
    flow_stock_status = fields.Selection(
        [('ok', 'OK'), ('deficit', 'SIN STOCK'), ('over', 'SOBREPEDIDO'), ('na', 'N/A')],
        string='Inventario (flujo)',
    )
    flow_purchase_status = fields.Selection(
        [('ok', 'OK'), ('missing', 'FALTA COMPRAR'), ('pending', 'POR RECIBIR'), ('na', 'N/A')],
        string='Compras (flujo)',
    )
    flow_production_status = fields.Selection(
        [('ok', 'OK'), ('design', 'ARTE PENDIENTE'), ('no_mo', 'SIN ORDEN'),
         ('material', 'FALTA MATERIAL'), ('late', 'RETRASO'),
         ('to_launch', 'SIN LANZAR'), ('no_supply', 'SIN INSUMOS'),
         ('in_progress', 'EN PROCESO'),
         ('na', 'N/A')],
        string='Fabricación (flujo)',
    )
    flow_delivery_status = fields.Selection(
        [('ok', 'ENTREGADO'), ('pending', 'PENDIENTE'),
         ('partial', 'PARCIAL'), ('na', 'N/A')],
        string='Entrega (flujo)',
    )
    # Almacén insumos (flujo): veredicto del motor por línea terminada. Es
    # 'no_supply' cuando la OF no tiene insumos cargados y, si no, el peor stock
    # de los componentes. Desacopla INSUMOS de FABRICACIÓN en el canvas.
    flow_supply_status = fields.Selection(
        [('ok', 'OK'), ('over', 'SOBREPEDIDO'), ('deficit', 'SIN STOCK'),
         ('no_supply', 'SIN INSUMOS'), ('na', 'N/A')],
        string='Almacén insumos (flujo)',
    )
    # Bandera del producto terminado: su OF existe pero no tiene insumos
    # definidos (``move_raw_ids`` vacío y BoM sin líneas). Alimenta el veredicto
    # de ``flow_supply_status`` en el roll-up.
    has_mo_without_materials = fields.Boolean(
        string='OF sin insumos', default=False,
    )
    flow_severity = fields.Selection(
        [('ok', 'Saludable'), ('warning', 'Atención'), ('danger', 'Crítico')],
        string='Semáforo (flujo)',
    )
    flow_failure_summary = fields.Char(string='Qué pasa (flujo)')
    flow_failed_node_count = fields.Integer(string='Nodos rotos (flujo)')

    # ── MEJORA A: producto ya entregado (fila de solo display) ──────────
    # Una línea sin demanda pendiente no genera falla, pero debe seguir
    # viéndose. La marca la pone el snapshot; el motor no se consulta por ella.
    is_display_only = fields.Boolean(
        string='Producto entregado',
        help='Fila informativa de un producto del pedido sin demanda pendiente '
             '(ya entregado): no genera fallas ni consulta existencias.',
    )
    # Texto de la columna "Qué pasa": usa el resumen del flujo cuando hay fallas
    # y un mensaje "Todo en orden" cuando no; distingue los ya entregados.
    status_note = fields.Char(
        string='Qué pasa', compute='_compute_status_note',
        help='Resumen de fallas del flujo o mensaje "Todo en orden" cuando no '
             'hay ninguna. Distingue los productos ya entregados.',
    )

    @api.depends('flow_failure_summary', 'is_display_only')
    def _compute_status_note(self):
        for line in self:
            if line.flow_failure_summary:
                line.status_note = line.flow_failure_summary
            elif line.is_display_only:
                line.status_note = _('Todo en orden (producto entregado)')
            else:
                line.status_note = _('Todo en orden')
    # Fallas de TODO el subárbol, sin duplicar registros: el terminado agrega
    # sus propias fallas más las de sus componentes (recursivo).
    flow_failure_ids = fields.One2many(
        'printflow.order.diagnostic.failure',
        compute='_compute_flow_failure_ids',
        string='Fallas del flujo',
    )

    @api.depends('failure_ids', 'child_line_ids')
    def _compute_flow_failure_ids(self):
        """Une las fallas propias con las de los componentes (recursivo)."""
        for line in self:
            line.flow_failure_ids = (
                line.failure_ids
                | line.child_line_ids.mapped('flow_failure_ids')
            )

    # ══════════════════════════════════════════════════════════════════════
    # NAVEGACIÓN DE NIVELES (botones de fila)
    # ══════════════════════════════════════════════════════════════════════
    def action_open_product(self):
        """Entra a la LÍNEA DE TIEMPO enfocando esta línea (producto terminado).

        El estado de navegación es ``focus_line_id``; el Nivel 3 se eliminó
        (su contenido vive en el popover de cada nodo).
        """
        self.ensure_one()
        wizard = self.wizard_id
        wizard.write({'focus_line_id': self.id})
        return wizard._pf_reload_action()

    def action_open_line_delivery(self):
        """Abre la entrega de ESTE producto (misma acción que la falla).

        Reutiliza ``printflow.order.board.action_open_product_delivery`` para que
        el botón de fila y el plan de la falla naveguen exactamente al mismo
        albarán del propio pedido.
        """
        self.ensure_one()
        board = self.wizard_id.board_id
        if not board:
            return {'type': 'ir.actions.act_window_close'}
        return board.action_open_product_delivery(self.product_id)
