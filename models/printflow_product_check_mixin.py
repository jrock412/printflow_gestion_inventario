# -*- coding: utf-8 -*-
"""Motor extensible de chequeos de producto (PrintFlow Diagnostic - FASE 2).

Este AbstractModel es el CORAZÓN del diagnóstico de producto. NO contiene
chequeos: solo define el contrato y las utilidades compartidas.

Contrato para agregar un chequeo nuevo (SIN tocar el motor ni otros chequeos):

    class PrintflowProductCheckXxx(models.AbstractModel):
        _inherit = 'printflow.product.check.mixin'

        @api.model
        def _pf_get_checks(self):
            return super()._pf_get_checks() + [{
                'code': 'xxx',
                'area': 'inventory',  # ver AREA_SELECTION
                'sequence': 10,
                'method': self._pf_check_xxx,
            }]

        def _pf_check_xxx(self, ctx):
            # Devuelve una lista de dicts construidos con self._pf_finding(...)
            return []

El barrido lo ejecuta ``printflow.product.diagnostic.wizard._pf_run_checks``,
que ordena por ``(area, sequence)`` y aísla cada chequeo con try/except.

Vocabulario de ``nav_kind`` (campo del hallazgo y de la evidencia). Es la
ÚNICA fuente de verdad de la navegación y se resuelve en un solo lugar:
``printflow.product.diagnostic.finding.action_open`` (y su espejo
``...evidence.action_open``). Un chequeo NUNCA construye la acción a mano,
solo declara el ``nav_kind`` y la referencia (recordset) que lo acompaña:

  * ``none``        -> sin navegación (hallazgo puramente informativo).
  * ``product``     -> ficha del producto (``product_id``).
  * ``quants``      -> existencias internas del producto (``product_id``).
  * ``bom``         -> una BOM concreta (``bom``).
  * ``bom_list``    -> lista de BOM de la plantilla del producto (``product_id``).
  * ``sale_order``  -> un pedido concreto (``sale_order``).
  * ``sale_lines``  -> líneas de venta confirmadas del producto (``product_id``).
  * ``sale_orders`` -> lista de pedidos bloqueantes/pendientes; el domain se
                       arma con los ``sale_order`` de las evidencias + el
                       ``sale_order`` del propio hallazgo.
  * ``orderpoint``  -> regla de reorden (``orderpoint``).
  * ``mo``          -> una Orden de Fabricación concreta (``mo``).
  * ``mo_list``     -> lista de Órdenes de Fabricación tomadas de los ``mo`` de
                       las evidencias del hallazgo.

Los ``nav_kind`` de lista (``sale_orders``, ``mo_list``) y el resto de destinos
complejos (``quants``, ``bom_list``, ``sale_lines``) se resuelven SIEMPRE con
``target='current'``: la resolución reemplaza la pantalla del escáner (no anida
diálogos) y nunca modifica datos.
"""

from collections import defaultdict

from odoo import _, api, models

# Margen para comparaciones de Float (evita ruido por redondeo).
EPS = 1e-6

# Áreas del diagnóstico. Fuente única de verdad para los chequeos y las vistas.
AREA_SELECTION = [
    ('inventory', 'Inventario'),
    ('kit', 'Kit'),
    ('bom', 'Lista de materiales'),
    ('orderpoint', 'Reglas de reorden'),
    ('uom', 'Unidades de medida'),
    ('routing', 'Rutas / abastecimiento'),
    ('sales', 'Ventas'),
    ('manufacturing', 'Fabricación'),
    ('record', 'Ficha del producto'),
    ('flow', 'Flujo unificado'),
]

# Severidades de un hallazgo y del resultado global.
SEVERITY_SELECTION = [
    ('info', 'Informativo'),
    ('ok', 'Correcto'),
    ('warning', 'Advertencia'),
    ('error', 'Error'),
]

# Naturaleza del registro culpable de un hallazgo. Fuente única de verdad de la
# Bandeja de Resolución (v1, solo lectura): la usan las evidencias recolectables.
CAUSANTE_TYPE_SELECTION = [
    ('sale_order', _('Pedido')),
    ('sale_line', _('Línea de pedido')),
    ('bom', _('Lista de materiales')),
    ('orderpoint', _('Regla de reorden')),
    ('mo', _('Orden de fabricación')),
    ('product', _('Producto')),
    ('component', _('Componente')),
    ('quant', _('Existencia')),
    ('purchase_order', _('Orden de compra')),
    ('picking', _('Albarán')),
    ('order_portion', _('Porción por pedido')),
    ('other', _('Otro')),
]

# Slot de acción de la bandeja. En v1 SOLO existe la navegación: ninguna
# acción modifica datos. Reservado para fases futuras.
ACTION_KIND_SELECTION = [
    ('none', _('Solo navegación')),
]


class PrintflowProductCheckMixin(models.AbstractModel):
    """Contrato y utilidades compartidas del motor de chequeos."""

    _name = 'printflow.product.check.mixin'
    _description = 'Motor extensible de chequeos de producto (PrintFlow)'

    # ------------------------------------------------------------------
    # CONTRATO
    # ------------------------------------------------------------------
    @api.model
    def _pf_get_checks(self):
        """Devuelve la lista de chequeos registrados.

        Cada elemento es ``{'code', 'area', 'sequence', 'method'}``. La base
        devuelve vacío; cada archivo de ``models/checks/`` agrega el suyo con
        ``super()``. Agregar un chequeo NUNCA obliga a tocar los existentes.

        :rtype: list[dict]
        """
        return []

    # ------------------------------------------------------------------
    # UTILIDADES DE CONSTRUCCIÓN (evitan repetir el esquema en cada chequeo)
    # ------------------------------------------------------------------
    @api.model
    def _pf_finding(self, code, area, severity, title, detail='', *,
                    product=False, highlighted=False, record_count=0,
                    nav_kind='none', res_model=False, res_id=False,
                    bom=False, sale_order=False, orderpoint=False, mo=False,
                    evidences=None, sequence=0, action_hint=''):
        """Construye los ``vals`` de un ``printflow.product.diagnostic.finding``.

        Las referencias se pasan como recordsets (no ids) para que quien escribe
        el chequeo no tenga que preocuparse por campos vacíos: aquí se traduce
        a id o ``False``.

        :param action_hint: texto corto y accionable ("Dónde corregir") que se
            muestra en la columna del mismo nombre. Ej: ``'Pedidos bloqueantes
            (2)'``. Es opcional.
        :param nav_kind: vocabulario documentado en el docstring del módulo;
            lo resuelve ``finding.action_open()``.
        """
        return {
            'sequence': sequence,
            'check_code': code,
            'area': area,
            'severity': severity,
            'title': title,
            'detail': detail,
            'action_hint': action_hint,
            'highlighted': highlighted,
            'record_count': record_count,
            'product_id': product.id if product else False,
            'nav_kind': nav_kind,
            'res_model': res_model or False,
            'res_id': res_id or False,
            'bom_id': bom.id if bom else False,
            'sale_order_id': sale_order.id if sale_order else False,
            'orderpoint_id': orderpoint.id if orderpoint else False,
            'mo_id': mo.id if mo else False,
            'evidence_ids': [(0, 0, e) for e in (evidences or [])],
        }

    @api.model
    def _pf_evidence(self, label, detail='', *, sequence=0, nav_kind='none',
                     res_model=False, res_id=False, product=False,
                     sale_order=False, bom=False, orderpoint=False, mo=False,
                     causante_type='other', collectible=False, ref_name='',
                     partner_name='', qty=0.0, qty_secondary=0.0,
                     state_label='', date_ref=False, action_kind='none'):
        """Construye los ``vals`` de un ``printflow.product.diagnostic.evidence``.

        Los parámetros de "causante" son OPCIONALES: omitirlos reproduce el
        comportamiento previo (evidencia de contexto, no recolectable).

        Contrato de causante (Bandeja de Resolución v1, SOLO LECTURA):

        :param causante_type: naturaleza del registro culpable; ver
            ``CAUSANTE_TYPE_SELECTION`` (``sale_order``, ``bom``, ``component``,
            ``quant``, ``orderpoint``, ``mo``, ``product``, ``other``...).
        :param collectible: ``True`` si el registro entra en la bandeja
            agregada; ``False`` para evidencias que solo aportan contexto.
        :param ref_name: referencia principal legible (nº de pedido, BOM, MO...).
        :param partner_name: cliente/proveedor/almacén según el tipo.
        :param qty: cantidad principal (pedida/mín/requerida).
        :param qty_secondary: cantidad secundaria (entregado/máx/libre).
        :param state_label: estado legible (facturación, tipo de BOM, MO...).
        :param date_ref: fecha de referencia del causante.
        :param action_kind: slot de acción; en v1 SIEMPRE ``'none'`` (la bandeja
            únicamente navega, nunca modifica datos).
        """
        return {
            'sequence': sequence,
            'label': label,
            'detail': detail,
            'nav_kind': nav_kind,
            'res_model': res_model or False,
            'res_id': res_id or False,
            'product_id': product.id if product else False,
            'sale_order_id': sale_order.id if sale_order else False,
            'bom_id': bom.id if bom else False,
            'orderpoint_id': orderpoint.id if orderpoint else False,
            'mo_id': mo.id if mo else False,
            'causante_type': causante_type or 'other',
            'collectible': bool(collectible),
            'ref_name': ref_name or '',
            'partner_name': partner_name or '',
            'qty': qty or 0.0,
            'qty_secondary': qty_secondary or 0.0,
            'state_label': state_label or '',
            'date_ref': date_ref or False,
            'action_kind': action_kind or 'none',
        }

    # ------------------------------------------------------------------
    # UTILIDADES DE DOMINIO (compartidas por varios chequeos)
    # ------------------------------------------------------------------
    @api.model
    def _pf_boms_for_product(self, product, bom_type=None):
        """BOM activas que aplican a una variante concreta.

        Recoge las BOM de la plantilla del producto y descarta las BOM de
        variante que apunten a OTRA variante (una BOM con ``product_id`` solo
        aplica a esa variante).

        :param product: ``product.product``.
        :param bom_type: filtra por tipo ('normal'/'phantom'/'subcontract').
        :rtype: mrp.bom recordset
        """
        domain = [
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('active', '=', True),
        ]
        if bom_type:
            domain.append(('type', '=', bom_type))
        boms = self.env['mrp.bom'].search(domain)
        return boms.filtered(lambda bom: not bom.product_id or bom.product_id == product)

    @api.model
    def _pf_group_boms_by_type(self, boms):
        """Agrupa un recordset de BOM por tipo, preservando el recordset.

        :rtype: dict[str, mrp.bom]
        """
        grouped = defaultdict(lambda: self.env['mrp.bom'])
        for bom in boms:
            grouped[bom.type] |= bom
        return grouped

    @api.model
    def _pf_quants_for_product(self, product, limit=50):
        """Quants internos (existencias por ubicación) de un producto."""
        return self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
        ], limit=limit)

    @api.model
    def _pf_quant_evidences(self, product, limit=20):
        """Evidencias navegables de las ubicaciones con existencia del producto.

        Cada quant es un causante recolectable (``causante_type='quant'``) para
        la Bandeja de Resolución: ``ref_name`` es la ubicación, ``qty`` la
        cantidad disponible y ``qty_secondary`` la reservada.
        """
        evidences = []
        for quant in self._pf_quants_for_product(product, limit=limit):
            evidences.append(self._pf_evidence(
                quant.location_id.display_name,
                detail=self._pf_quant_detail(quant),
                product=product,
                nav_kind='quants',
                res_model='stock.quant',
                res_id=quant.id,
                causante_type='quant',
                collectible=True,
                ref_name=quant.location_id.display_name,
                qty=quant.available_quantity,
                qty_secondary=quant.reserved_quantity,
            ))
        if not evidences:
            evidences.append(self._pf_evidence(
                _('Sin existencias en ubicaciones internas'),
                product=product,
                nav_kind='product',
                res_model='product.product',
                res_id=product.id,
                causante_type='product',
                collectible=False,
            ))
        return evidences

    @api.model
    def _pf_quant_detail(self, quant):
        """Texto legible de un quant (cantidad y reservado) en su UdM."""
        uom_name = quant.product_uom_id.name if 'product_uom_id' in quant._fields else ''
        return '%s: %s | %s: %s %s' % (
            'Disponible', quant.available_quantity,
            'Reservado', quant.reserved_quantity, uom_name,
        )

    @api.model
    def _pf_selection_label(self, record, field_name):
        """Etiqueta legible del valor de un campo Selection.

        Cae al valor crudo si el campo no es Selection o no tiene etiqueta.
        Se comparte entre chequeos para no repetir el mapeo.

        :rtype: str
        """
        field = record._fields.get(field_name)
        selection = getattr(field, 'selection', None)
        if not selection or not isinstance(selection, (list, tuple)):
            return record[field_name] or ''
        value = record[field_name]
        return dict(selection).get(value, value or '')
