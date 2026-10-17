# -*- coding: utf-8 -*-
"""Bridge PrintFlow sobre la Compra Rápida (``mrp.quick.purchase.wizard``).

Extiende el asistente de Compra Rápida del motor
``x_product_dimensional_pricing`` SIN tocarlo (``_inherit`` + ``super()``): el
módulo externo NO se modifica; el enganche es ADITIVO.

Aporta las piezas de esta fase:
- (D3) ``pf_freeze_qty``, una MARCA de cantidad CONGELADA. Cuando está activa, la
  Compra Rápida NO recalcula la cantidad con la lista de pedidos agrupados (el
  faltante real lo fijó la resolución del nodo Compras) -> se devuelve ``0.0``
  desde ``_demand_for_product`` para que ningún consumidor
  (``_onchange_recompute_qty``, el ``_onchange_product_id`` de la línea y
  ``_create_purchase_order``) pise el valor prellenado. La Compra Rápida NORMAL
  (sin la marca) llama a ``super()`` y conserva INTACTO su comportamiento.
- (D4) ``action_pf_import_requiring_orders``, el botón "Traer pedidos que
  requieren compra": importa a "Agrupar pedidos" SOLO los pedidos con entrega
  pendiente del producto y SIN compra en trámite (filtro del motor de pendientes).
- (D1/T2) ``mrp.quick.purchase.wizard.line::_create_purchase_order``: persiste el
  ``lot_name`` de la línea en ``purchase.order.pf_lot_name`` (SOLO con el GATE
  ``pf_freeze_qty``), para que el lote no se pierda al abrir la OC de PrintFlow.

Dirección de dependencias: vive en ``models/`` del addon PrintFlow; NO importa
``wizard/``. Solo se LEE/ENGANCHA (regla "código sí, datos no"); la importación
escribe únicamente en el TRANSIENT del wizard ("abrir ≠ ejecutar").
"""

from odoo import _, fields, models


class MrpQuickPurchaseWizard(models.TransientModel):
    """Compra Rápida (PrintFlow): cantidad congelable por el faltante real."""

    _inherit = 'mrp.quick.purchase.wizard'

    pf_freeze_qty = fields.Boolean(
        string='Cantidad congelada (faltante real)',
        help='Si está activo, la cantidad de la compra NO se recalcula con los '
             'pedidos agrupados: se respeta el faltante real fijado por la '
             'resolución del nodo Compras. La Compra Rápida normal (sin la '
             'marca) conserva su cálculo habitual.')

    def action_pf_import_requiring_orders(self):
        """Trae a "Agrupar pedidos" los pedidos que REQUIEREN compra (D4).

        Importa los pedidos con ENTREGA PENDIENTE del producto de referencia que
        NO tienen una compra en trámite (filtro de la FUENTE ÚNICA
        ``printflow.flow.pending._pf_sale_orders_requiring_purchase``). Es
        IDEMPOTENTE: solo crea las filas que FALTAN (no duplica las ya
        agrupadas). Solo escribe en el TRANSIENT del wizard ("abrir ≠ ejecutar":
        NO crea OC ni mueve stock) y devuelve la acción que RECARGA el wizard
        para que el operador vea los pedidos importados.
        """
        self.ensure_one()
        product = self.purchase_line_ids[:1].product_id or self.product_id
        if product:
            requiring = self.env[
                'printflow.flow.pending'
            ]._pf_sale_orders_requiring_purchase(product)
            already = self.order_line_ids.mapped('sale_order_id')
            OrderLine = self.env['mrp.quick.purchase.wizard.order']
            for sale_order in requiring - already:
                OrderLine.create({
                    'wizard_id': self.id,
                    'sale_order_id': sale_order.id,
                })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compra Rápida'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _demand_for_product(self, product):
        """Demanda del producto usada para recalcular la cantidad (D3).

        Con ``pf_freeze_qty`` la cantidad está CONGELADA: se devuelve ``0.0``
        para que los consumidores NO pisen el faltante real prellenado (su
        contrato es "solo cambian la cantidad si la demanda es > 0"). Sin la
        marca se delega en ``super()`` (compra rápida normal INTACTA).
        """
        self.ensure_one()
        if self.pf_freeze_qty:
            return 0.0
        return super()._demand_for_product(product)


class MrpQuickPurchaseWizardLine(models.TransientModel):
    """Línea de la Compra Rápida (PrintFlow): persiste el lote en la OC (T2).

    Hereda ``mrp.quick.purchase.wizard.line`` del motor ``x_product_dimensional_pricing``
    SIN tocarlo (``_inherit`` + ``super()``). Aporta (D1) la PERSISTENCIA del lote
    de la línea en la OC recién creada: así el nombre del lote queda recuperable por
    el lado de COMPRA/ENTRADA antes de que ``purchase.order.button_confirm`` lo
    prellene en el albarán.
    """

    _inherit = 'mrp.quick.purchase.wizard.line'

    def _create_purchase_order(self, orders):
        """Crea la OC de esta línea y le persiste el lote previsto (D1).

        Delega en ``super()`` la creación NATIVA de la OC y, SOLO cuando la Compra
        Rápida viene de PrintFlow (GATE ``pf_freeze_qty``, D5) y el producto va por
        lote con un ``lot_name`` indicado, escribe el nombre del lote en
        ``po.pf_lot_name``. La Compra Rápida NORMAL (sin la marca) queda INTACTA.
        """
        po = super()._create_purchase_order(orders)
        if (self.wizard_id.pf_freeze_qty
                and self.product_id.tracking == 'lot'
                and self.lot_name):
            po.pf_lot_name = self.lot_name
        return po
