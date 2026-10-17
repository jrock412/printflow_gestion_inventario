# -*- coding: utf-8 -*-
"""Bandeja gestionable de INSUMOS del diagrama de PRODUCTO (PrintFlow).

``TransientModel`` de LECTURA que convierte el "Solucionar" del hito ALMACÉN
DE INSUMOS en una decisión GESTIONABLE: en vez de un one-click ciego, lista UNA
fila por INSUMO/ALMACÉN afectado (el componente de la BOM está reservado de más,
sin existencia, apartado por otros pedidos o sin forma de reponer) y ofrece TRES
vías de solución ABIERTAS al operador:

* **Traslado** (``action_transfer``): crea un ``stock.picking`` interno en
  BORRADOR con un ``stock.move`` del insumo (origen = ubicación en negativo,
  destino = interno por defecto) y lo ABRE. NO valida: el operador decide.
* **Compra** (``action_buy``): abre la Compra Rápida (``mrp.quick.purchase.wizard``)
  prellenada con el insumo, SIN pedido de venta.
* **Ajuste** (``action_adjust``): abre las existencias del insumo en modo
  ``inventory_mode``.

La decisión AUTOMÁTICA (``action_apply_correction``) es SECUNDARIA y conserva el
guardia de permisos ``printflow.stock.remedy._pf_assert_can_clean()`` (jefe de
taller/admin): el resto de botones quedan abiertos al operador (ACL nativa).

Por qué existe
--------------
El diseño aprobado pide que el operador VEA qué insumo está mal y decida. La
detección NO se reinventa: la resuelve el colaborador ``printflow.flow.supply``
(``_pf_supply_rows``), que reutiliza el snapshot del motor. La ejecución del
remedio automático también es única:
``printflow.stock.remedy._pf_cleanup_product_reservations`` (con su guardia).

Contrato::

    tray = env['printflow.flow.supply.tray']._pf_populate(flow_product)
    action = tray[:1].action_open()
    action = tray[:1].action_transfer()
    action = tray[:1].action_buy()
    action = tray[:1].action_adjust()
    action = tray.action_apply_correction()   # guardia de permisos
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PrintflowFlowSupplyTray(models.TransientModel):
    """Una fila por insumo/almacén del hito ALMACÉN DE INSUMOS."""

    _name = 'printflow.flow.supply.tray'
    _description = 'Bandeja gestionable de insumos (PrintFlow)'
    _order = 'state, component_id, location_id'

    product_id = fields.Many2one(
        'product.product', string='Producto', readonly=True,
        help='Producto terminado cuyo almacén de insumos se está gestionando.')
    component_id = fields.Many2one(
        'product.product', string='Insumo', readonly=True,
        help='Componente de la BOM afectado.')
    component_name = fields.Char(string='Insumo', readonly=True)
    location_id = fields.Many2one(
        'stock.location', string='Almacén', readonly=True,
        help='Ubicación interna donde vive el insumo (origen sugerido).')
    location_name = fields.Char(string='Almacén', readonly=True)
    on_hand = fields.Float(
        string='Existencia', readonly=True, digits='Product Unit of Measure')
    reserved = fields.Float(
        string='Reservado', readonly=True, digits='Product Unit of Measure')
    free = fields.Float(
        string='Libre', readonly=True, digits='Product Unit of Measure')
    need = fields.Float(
        string='Necesario', readonly=True, digits='Product Unit of Measure')
    state = fields.Char(
        string='Estado', readonly=True,
        help='Token normalizado del snapshot del motor.')
    state_label = fields.Char(string='Estado', readonly=True)
    res_model = fields.Char(string='Modelo', readonly=True)
    res_id = fields.Integer(string='Id del registro', readonly=True)

    # ══════════════════════════════════════════════════════════════════════
    # POBLADO BAJO DEMANDA
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_populate(self, flow_product):
        """Reconstruye la bandeja de un producto (una fila por insumo/almacén).

        Limpia las filas previas del MISMO producto (el wizard es el dueño
        transitorio), pide las filas al colaborador ``printflow.flow.supply`` y
        las crea. Devuelve el recordset creado (lo abre el llamador).
        """
        flow_product = (
            flow_product.exists() if flow_product else self.browse())
        if not flow_product:
            return self.browse()
        self.sudo().search([('product_id', '=', flow_product.id)]).unlink()
        rows = self.env[
            'printflow.flow.supply']._pf_supply_rows(flow_product)
        if not rows:
            return self.browse()
        vals = [dict(row, product_id=flow_product.id) for row in rows]
        return self.create(vals)

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
            'name': self.component_name or _('Insumo'),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_transfer(self):
        """Crea un traslado interno BORRADOR del insumo y lo abre (no valida).

        Origen = la ubicación en negativo de la fila (o el stock por defecto),
        destino = la ubicación interna por defecto del almacén. NO se valida: el
        operador decide si el traslado procede.
        """
        self.ensure_one()
        component = self.component_id
        if not component:
            return {'type': 'ir.actions.act_window_close'}
        warehouse = self._pf_warehouse()
        if not warehouse:
            return {'type': 'ir.actions.act_window_close'}
        src = self.location_id or warehouse.lot_stock_id
        dest = warehouse.lot_stock_id
        picking = self.env['stock.picking'].create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'origin': _('PrintFlow · Reposición de insumos'),
            'move_ids': [(0, 0, {
                'name': component.display_name,
                'product_id': component.id,
                'product_uom_qty': self.need or 1.0,
                'product_uom': component.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
            })],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Traslado de insumo: %s') % component.display_name,
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_buy(self):
        """Abre la Compra Rápida prellenada con el insumo (sin pedido de venta)."""
        self.ensure_one()
        component = self.component_id
        if not component:
            return {'type': 'ir.actions.act_window_close'}
        vals = {
            'product_id': component.id,
            'product_qty': self.need or 1.0,
            'product_uom_id': component.uom_id.id,
            # No forzamos recepción: solo se genera la OC.
            'material_received': False,
        }
        if component.seller_ids:
            vals['partner_id'] = component.seller_ids[0].partner_id.id
        wizard = self.env['mrp.quick.purchase.wizard'].create({
            'sale_order_id': False,
            'purchase_line_ids': [(0, 0, vals)],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compra Rápida (insumo)'),
            'res_model': 'mrp.quick.purchase.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_adjust(self):
        """Abre las existencias del insumo en modo AJUSTE (sugiere lo necesario)."""
        self.ensure_one()
        component = self.component_id
        if not component:
            return {'type': 'ir.actions.act_window_close'}
        suggested = self.need or 0.0
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ajuste de insumo: %s (sugerido: %.2f)') % (
                component.display_name, suggested),
            'res_model': 'stock.quant',
            'view_mode': 'tree,form',
            'domain': [
                ('product_id', '=', component.id),
                ('location_id.usage', '=', 'internal'),
            ],
            'context': {
                'inventory_mode': True,
                'search_default_product_id': component.id,
                'default_inventory_quantity': suggested,
                'pf_suggested_qty': suggested,
            },
            'target': 'current',
        }

    def action_apply_correction(self):
        """Aplica la corrección AUTOMÁTICA del motor sobre la SELECCIÓN.

        El botón de cabecera llega con las filas seleccionadas en ``self``; sin
        selección, se toman TODAS las filas de la bandeja actual vía
        ``active_domain``. Es la opción SECUNDARIA y pasa por el guardia de
        permisos ``_pf_assert_can_clean`` (jefe de taller/admin): quien no lo
        tiene, ve la bandeja pero recibe ``UserError`` al aplicar. Reutiliza el
        remedio ya probado ``_pf_cleanup_product_reservations`` por cada insumo
        afectado.
        """
        records = self
        if not records:
            records = self.search(self.env.context.get('active_domain') or [])
        records = records.exists()
        if not records:
            return {'type': 'ir.actions.act_window_close'}
        Remedy = self.env['printflow.stock.remedy']
        Remedy._pf_assert_can_clean()
        cleaned = 0
        for component in records.mapped('component_id'):
            result = Remedy._pf_cleanup_product_reservations(component)
            cleaned += len(result.get('cleaned_pickings') or [])
        if cleaned:
            message = _(
                'Reservas de insumos reajustadas al stock real: %s '
                'albarán(es).') % cleaned
            ntype = 'success'
        else:
            message = _('No había reservas colgadas que sanear en los insumos.')
            ntype = 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': ntype,
                'title': _('PrintFlow'),
                'message': message,
                'sticky': ntype == 'warning',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_warehouse(self):
        """Almacén por defecto de la compañía (o recordset vacío)."""
        return self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
