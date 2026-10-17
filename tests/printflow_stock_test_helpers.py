# -*- coding: utf-8 -*-
"""Utilidades compartidas para los tests de salud de inventario (PrintFlow).

No define casos de prueba: solo un mixin con helpers genéricos (sin productos ni
pedidos concretos) para no repetir el andamiaje de quants, pedidos y MO.
"""

from odoo import fields


class PrintflowStockHealthTestMixin:
    """Helpers genéricos de inventario para los tests del Bloque III/IV."""

    # Semilla del tope de productos por corrida de saneamiento (0 = sin límite).
    PF_RESERVATION_CLEANUP_LIMIT = (
        'x_product_dimensional_pricing.pf_reservation_cleanup_limit')

    # ------------------------------------------------------------------
    # Configuración de parámetros (transitoria: rollback al terminar el test)
    # ------------------------------------------------------------------
    @classmethod
    def _pf_disable_reservation_limit(cls):
        """Quita el tope de productos por corrida de saneamiento (0 = sin límite).

        La BD real puede tener más alertas que el tope (50), lo que dejaría
        fuera de ``_pf_products_in_alert`` a los productos que crea el test.
        Es transitorio: vive en la transacción del test y no persiste.
        """
        cls.env['ir.config_parameter'].sudo().set_param(
            cls.PF_RESERVATION_CLEANUP_LIMIT, '0')

    # ------------------------------------------------------------------
    # Productos y existencias
    # ------------------------------------------------------------------
    def _pf_product(self, name, **extra):
        vals = {'name': name, 'type': 'product'}
        vals.update(extra)
        return self.env['product.product'].create(vals)

    def _pf_add_stock(self, product, qty, reserved=0.0, location=None):
        self.env['stock.quant']._update_available_quantity(
            product, location or self.stock_location, qty,
            reserved_quantity=reserved)

    def _pf_extra_location(self, name='PF HEALTH EXTRA'):
        return self.env['stock.location'].create({
            'name': name,
            'location_id': self.stock_location.id,
            'usage': 'internal',
        })

    def _pf_make_bom(self, product, components):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'product_qty': 1.0,
            'bom_line_ids': [
                (0, 0, {'product_id': comp.id, 'product_qty': qty})
                for comp, qty in components
            ],
        })

    # ------------------------------------------------------------------
    # Pedidos y tablero
    # ------------------------------------------------------------------
    def _pf_force_board(self, product, qty):
        """Pedido forzado a 'sale' (sin procura) + su tarjeta."""
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.write({'state': 'sale'})
        return self.env['printflow.order.board'].create({'sale_order_id': so.id})

    def _pf_confirm_order(self, product, qty):
        so = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        so.action_confirm()
        return so

    def _pf_done_mo(self, so, product):
        """MO terminada vinculada al pedido (activa la compuerta del tablero)."""
        group = self.env['procurement.group'].create({
            'name': f'{so.name} - Inmediata',
            'sale_id': so.id,
            'partner_id': so.partner_id.id,
        })
        manu_type = self.warehouse.manu_type_id
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'origin': f'{so.name} - Inmediata',
            'picking_type_id': manu_type.id,
            'location_src_id': (
                manu_type.default_location_src_id.id or self.stock_location.id),
            'location_dest_id': (
                manu_type.default_location_dest_id.id or self.stock_location.id),
            'source_procurement_group_id': group.id,
            'procurement_group_id': group.id,
        })
        mo.write({'state': 'done'})
        return mo

    def _pf_recompute_board(self, board):
        board.mapped('sale_order_id').invalidate_model(['mrp_production_ids'])
        board.invalidate_model([
            'mrp_production_ids', 'has_production', 'pf_has_done_mo',
            'pf_any_pending_mo', 'is_stock_missing', 'production_alert',
            'procurement_type', 'state', 'health_stock', 'health_production',
            'health_severity',
        ])
        board._compute_mrp_production_ids()
        board._compute_production_status()
        board._compute_purchase_status()
        board._compute_is_stock_missing()
        board._compute_state()
        board._compute_health_flags()
        return board

    def _pf_diagnose(self, board):
        return self.env['printflow.order.diagnostic.wizard'].create(
            {'board_id': board.id})

    def _pf_line(self, wizard, product):
        return wizard.deficit_line_ids.filtered(
            lambda l: l.product_id == product)[:1]


def pf_datetime_now():
    """Atajo de ``fields.Datetime.now`` para los tests de orden."""
    return fields.Datetime.now()
