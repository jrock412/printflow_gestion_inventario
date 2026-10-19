# -*- coding: utf-8 -*-
"""Candados del REDISEÑO del contenedor "Asignar lote en bloque" (PrintFlow).

Custodia los criterios de aceptación NUEVOS del rediseño de la pantalla y de la
limpieza del wizard (§3.P · **H-043 · H-044 · H-045 · H-046 · H-047**): el
contenedor ``printflow.flow.lot.assign.bulk`` deja de **decidir por el
operador** y de ofrecer información que **engaña**.

* **CA-1** — **ninguna** fila llega pre-llenada: ``line.lot_id`` queda **VACÍO**
  al abrir el contenedor, **aun cuando el lote propio de la unidad TENGA
  existencia** (se retiró el pre-llenado: D-1).
* **CA-3** — la tabla de lotes (``candidate_ids``) lista **solo lotes con
  existencia REAL**: el lote propio **SIN** mercancía deja de aparecer (se
  retiró ``include_lot_ids`` de la llamada del contenedor: D-2).
* **CA-4** — el desplegable "Lote a asignar" de cada fila **excluye su propio
  lote**: el ``domain`` del campo declara el candado (D-3 · prevención). Se
  candadea el ``domain`` **literal** del campo, **sin navegador**.
* **CA-5** — la tabla de lotes pinta **"Disponible aquí"** (``available_here``,
  la cifra que DECIDE) y **no** la disponibilidad global (``available``): el
  candado lee el ``arch`` del modal, sin navegador.
* **CA-6** — la tabla "Lotes con existencia" sigue **en el modal** (siempre
  visible, D-6).
* **CA-7** — la fila de unidades muestra **6** columnas a la vista
  (*# · Entrega · Pedido · Lote propio · Existencia · Lote a asignar*) y las
  piezas de trazabilidad (``move_id`` / ``sale_line_id`` / ``demand_qty`` /
  ``result`` / ``result_note``) quedan **recuperables** (``optional="hide"``),
  nunca borradas del modelo.
* **CA-8** — la cabecera tiene su señal: ``candidate_count`` = número de
  ``candidate_ids``, rotulado *"Lotes con existencia"* (D-9); ``source_label``
  deja de pintarse y ``confirm_exception`` se CONSERVA (T10 de §3.O).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios productos/albaranes y
``TransactionCase`` hace rollback al terminar. Abrir el contenedor **no escribe
nada** (CA-9): el ``lot_id`` de la fila es la decisión del operador, no un
efecto de abrir.
"""

import os

from lxml import etree

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase, tagged

# Configuración de nodos de pendientes (0 = sin tope): hace DETERMINISTA el
# número de filas ``pending_order`` que la bandeja produce.
PARAM_NODE_PENDING_LIMIT = (
    'x_product_dimensional_pricing.pf_node_pending_limit')
PARAM_NODE_PENDING_ENABLED = (
    'x_product_dimensional_pricing.pf_node_pending_enabled')
PARAM_NODE_PENDING_NODES = (
    'x_product_dimensional_pricing.pf_node_pending_nodes')
# Política de asignación por excepción (cero hardcodeo): se fija en ``warn``
# para que abrir el contenedor no tenga fricción en estos candados.
PARAM_EXCEPTION_POLICY = (
    'x_product_dimensional_pricing.pf_lot_assign_exception_policy')

# Candado (§0.2): el candado mira el CÓDIGO del módulo, NUNCA a este propio
# archivo de test (auditarse a sí mismo lo delataría por las agujas literales).
_MODULE = 'printflow_gestion_inventario'
_TOUCHED_FILES = (
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk.py'),
    os.path.join('wizard', 'printflow_flow_lot_assign_bulk_line.py'),
)

# El candado del candado (§3.P): el dominio del selector POR FILA declara que el
# lote propio NO se ofrece en su propia fila. Se compara el TEXTO del dominio
# (sin navegador) normalizando espacios: si alguien retira el candado, este
# candado cae.
_OWN_LOT_LOCK = "('id', '!=', own_lot_id)"


@tagged('post_install', '-at_install')
class TestProductFlowLotAssignBulkRedesign(TransactionCase):
    """El contenedor NO decide por el operador: filas vacías y lotes reales."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create(
            {'name': 'Cliente Rediseno Bulk'})
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.Flow = cls.env['printflow.product.flow']
        cls.Tray = cls.env['printflow.flow.lot.tray']
        cls.Bulk = cls.env['printflow.flow.lot.assign.bulk']
        cls.Line = cls.env['printflow.flow.lot.assign.bulk.line']
        cls.ICP = cls.env['ir.config_parameter'].sudo()
        # Determinismo de la bandeja (transitorio: vive en la transacción).
        cls.ICP.set_param(PARAM_NODE_PENDING_ENABLED, '1')
        cls.ICP.set_param(PARAM_NODE_PENDING_NODES,
                          'purchase,receipt,production,delivery,sale')
        cls.ICP.set_param(PARAM_NODE_PENDING_LIMIT, '0')
        cls.ICP.set_param(PARAM_EXCEPTION_POLICY, 'warn')

    # ------------------------------------------------------------------
    # Utilidades (mismas primitivas NATIVAS que usa la bandeja)
    # ------------------------------------------------------------------
    def _product(self, name):
        product = self.env['product.product'].create({
            'name': name, 'type': 'product', 'tracking': 'lot',
            'x_is_printflow_managed': True,
        })
        product.product_tmpl_id.route_ids = [(5, 0, 0)]
        return product

    def _lot(self, product, name):
        return self.env['stock.lot'].create(
            {'name': name, 'product_id': product.id})

    def _stock(self, product, qty, lot=None):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot)

    def _sale_lines(self, product, count=1):
        """Líneas de pedido (SIN confirmar) para darle lote propio a la unidad.

        El nombre del lote propio sale de la MISMA primitiva del motor que usa la
        bandeja (``sale.order.line._get_exclusive_lot_name``): el test lo lee de
        allí, no lo re-calcula.
        """
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [
                (0, 0, {'product_id': product.id, 'product_uom_qty': 1.0})
                for _index in range(count)],
        })
        return order, order.order_line[:count]

    def _outgoing(self, product, qtys=(1.0,), sale_lines=None):
        """Albarán de salida confirmado con UN movimiento por cantidad.

        Se confirma ANTES de que exista existencia (Odoo no reserva por su
        cuenta) y SIN ``move_line``: los movimientos quedan SIN reserva ⇒ la
        bandeja produce la fila ``pending_order`` de la ORDEN (que se EXPANDE a
        una fila por movimiento en el contenedor).
        """
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.warehouse.out_type_id.id,
            'location_id': self.stock_location.id,
            'location_dest_id': self.customer_location.id,
            'partner_id': self.customer.id,
        })
        moves = self.env['stock.move']
        for index, qty in enumerate(qtys):
            sale_line = (sale_lines or [])[index] if sale_lines else None
            moves |= self.env['stock.move'].create({
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
                'picking_id': picking.id,
                'location_id': self.stock_location.id,
                'location_dest_id': self.customer_location.id,
                'sale_line_id': sale_line.id if sale_line else False,
            })
        moves._action_confirm()
        return picking, moves

    def _open_tray(self, product, lot_state='lot_missing'):
        """Abre la bandeja por el dispatcher (misma ruta que el operador)."""
        action = self.Flow.action_open_product_flow(product.id)
        wizard = self.Flow.browse(action['res_id'])
        wizard.action_run_pf_plan(lot_state, 'solution')
        return self.Tray.search([
            ('product_id', '=', product.id),
            ('lot_state', '=', lot_state),
        ])

    def _wizard_for(self, selection):
        """Abre el contenedor desde la acción sobre la SELECCIÓN."""
        action = selection.action_assign_lot_bulk()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'printflow.flow.lot.assign.bulk')
        self.assertEqual(action['target'], 'new')
        return self.Bulk.browse(action['res_id'])

    def _pending_row(self, tray):
        """Fila ``pending_order`` de la bandeja (la dimensión OPERATIVA)."""
        rows = tray.filtered(lambda rec: rec.kind == 'pending_order')
        self.assertTrue(rows, 'La bandeja debe listar la entrega sin lote.')
        return rows

    def _line_for(self, bulk, move):
        """Fila del contenedor que corresponde a UN movimiento."""
        line = bulk.line_ids.filtered(lambda rec: rec.move_id == move)[:1]
        self.assertTrue(
            line, 'Cada movimiento debe tener SU fila en el contenedor.')
        return line

    def _bulk_with_two_units(self, tag, own_lot_stock_a=True,
                             own_lot_b_exists=True, real_lot_qty=0.0):
        """Arma un contenedor de 2 unidades y devuelve su contexto.

        Todo el montaje de existencias ocurre ANTES de abrir la bandeja (ese es
        el orden real del operador: primero hay mercancía, después decide).

        :param bool own_lot_stock_a: si el lote propio de la 1.ª unidad tiene
            mercancía (1 u) o no.
        :param bool own_lot_b_exists: si el lote propio de la 2.ª unidad existe
            como ``stock.lot`` (siempre SIN mercancía).
        :param float real_lot_qty: existencia de un lote REAL ajeno a los lotes
            propios (0.0 = no se crea).
        :rtype: dict
        """
        product = self._product(tag)
        order, sale_lines = self._sale_lines(product, count=2)
        _pick, moves = self._outgoing(
            product, qtys=(1.0, 1.0), sale_lines=sale_lines)
        own_name_a = sale_lines[0]._get_exclusive_lot_name()
        own_name_b = sale_lines[1]._get_exclusive_lot_name()
        self.assertNotEqual(own_name_a, own_name_b)
        # El lote propio de la 1.ª unidad EXISTE (con mercancía según el caso).
        lot_a = self._lot(product, own_name_a)
        if own_lot_stock_a:
            self._stock(product, 1.0, lot=lot_a)
        if own_lot_b_exists:
            self._lot(product, own_name_b)
        real_lot = self.env['stock.lot']
        if real_lot_qty > 0.0:
            real_lot = self._lot(product, '%s-REAL' % tag)
            self._stock(product, real_lot_qty, lot=real_lot)

        tray = self._open_tray(product)
        bulk = self._wizard_for(self._pending_row(tray))
        return {
            'product': product,
            'order': order,
            'sale_lines': sale_lines,
            'moves': moves,
            'own_name_a': own_name_a,
            'own_name_b': own_name_b,
            'own_lot_a': lot_a,
            'real_lot': real_lot,
            'bulk': bulk,
        }

    # ==================================================================
    # CA-1 — NINGUNA fila llega pre-llenada (ni con el lote propio con stock)
    # ==================================================================
    def test_ca1_no_row_arrives_prefilled(self):
        ctx = self._bulk_with_two_units('BULK REDISENO CA1')
        bulk = ctx['bulk']
        self.assertEqual(len(bulk.line_ids), 2)

        # El lote propio de la 1.ª unidad TIENE existencia (es el cebo del
        # pre-llenado retirado): el operador igual decide.
        self.assertEqual(
            self._line_for(bulk, ctx['moves'][0]).own_lot_qty, 1.0)

        for line in bulk.line_ids:
            self.assertFalse(
                line.lot_id,
                'Ninguna fila se pre-llena: el lote propio solo INFORMA (D-1).')
            self.assertEqual(line.result, 'pending')

    # ==================================================================
    # CA-3 — la tabla lista SOLO lotes con existencia REAL (fuera el propio en 0)
    # ==================================================================
    def test_ca3_candidates_are_only_real_stock_lots(self):
        ctx = self._bulk_with_two_units(
            'BULK REDISENO CA3', own_lot_stock_a=False, own_lot_b_exists=True,
            real_lot_qty=1.0)
        bulk = ctx['bulk']
        own_lot = ctx['own_lot_a']
        real_lot = ctx['real_lot']

        self.assertIn(
            real_lot, bulk.candidate_ids.mapped('lot_id'),
            'El lote REAL con existencia debe listarse.')
        self.assertNotIn(
            own_lot, bulk.candidate_ids.mapped('lot_id'),
            'El lote propio SIN mercancía no se lista (D-2).')
        # Ningún candidato forzado en cero: la tabla es de "dónde hay mercancía".
        self.assertFalse(
            [cand for cand in bulk.candidate_ids if cand.qty_on_hand <= 0.0],
            'La tabla no lista lotes en 0.00.')
        # El nombre del lote propio sigue VISIBLE, con su existencia en 0.00.
        line_own = self._line_for(bulk, ctx['moves'][0])
        self.assertEqual(line_own.own_lot_name, ctx['own_name_a'])
        self.assertEqual(line_own.own_lot_qty, 0.0)

    # ==================================================================
    # CA-4 — el candado del lote propio vive en el DOMINIO (sin navegador)
    # ==================================================================
    def test_ca4_selector_domain_excludes_own_lot(self):
        domain = ' '.join(str(self.Line._fields['lot_id'].domain).split())
        self.assertIn(
            _OWN_LOT_LOCK, domain,
            'El desplegable por fila debe EXCLUIR el lote propio (D-3).')
        # El candado no cambia la semántica: sigue siendo solo lotes con
        # existencia del producto y del contenedor.
        self.assertIn("('product_id', '=', parent.product_id)", domain)
        self.assertIn("('id', 'in', parent.candidate_lot_ids)", domain)

    # ==================================================================
    # CA-8 — la cabecera tiene su señal: candidate_count rotulado
    # ==================================================================
    def test_ca8_candidate_count_and_label(self):
        ctx = self._bulk_with_two_units('BULK REDISENO CA8')
        bulk = ctx['bulk']
        self.assertEqual(
            bulk.candidate_count, len(bulk.candidate_ids),
            'candidate_count es el número de lotes con existencia (D-9).')
        self.assertTrue(bulk.candidate_ids)
        self.assertEqual(
            bulk.fields_get(['candidate_count'])['candidate_count']['string'],
            'Lotes con existencia')

    # ==================================================================
    # CA-5 · CA-6 · CA-7 · CA-8 — el `arch` del modal declara la pantalla
    # ==================================================================
    def _modal_arch(self):
        """``arch`` del modal "Asignar lote en bloque" (solo lectura).

        Se lee el ``arch`` COMBINADO de la vista (el contrato que el Lote 4
        dejó pintado): así el candado NO necesita navegador.
        """
        view = self.env.ref(
            'printflow_gestion_inventario.'
            'printflow_flow_lot_assign_bulk_view_form')
        arch = view.arch
        return arch if isinstance(arch, str) else str(arch)

    def test_view_arch_locks_ca5_to_ca8(self):
        """El ``arch`` del modal candadea CA-5/CA-6/CA-7/CA-8 sin navegador."""
        arch = self._modal_arch()
        root = etree.fromstring(arch.encode('utf-8'))

        # CA-5 — se pinta "Disponible aquí" (la cifra que DECIDE) y la
        # disponibilidad GLOBAL queda fuera de la vista (no engaña, D-4).
        here = root.xpath("//field[@name='available_here']")
        self.assertTrue(here, 'La tabla debe pintar available_here (D-4).')
        self.assertEqual(here[0].get('string'), 'Disponible aquí')
        global_available = root.xpath("//field[@name='available']")
        self.assertTrue(global_available, 'available sigue en el arch.')
        self.assertEqual(
            global_available[0].get('column_invisible'), 'True',
            'La disponibilidad global NO se pinta (D-4).')

        # CA-6 — la tabla de lotes sigue presente en el modal (D-6).
        self.assertTrue(
            root.xpath("//field[@name='candidate_ids']"),
            'La tabla "Lotes con existencia" sigue en el modal (D-6).')

        # CA-7 — la fila de unidades muestra 6 columnas, A LA VISTA...
        visible = ('seq', 'label', 'sale_order_name', 'own_lot_name',
                   'own_lot_qty', 'lot_id')
        for name in visible:
            node = root.xpath(
                "//field[@name='line_ids']//field[@name='%s']" % name)
            self.assertTrue(node, 'Falta la columna visible "%s".' % name)
            self.assertNotEqual(
                node[0].get('optional'), 'hide',
                '"%s" debe quedar A LA VISTA (CA-7).' % name)
        positions = [arch.index('name="%s"' % name) for name in visible]
        self.assertEqual(
            positions, sorted(positions),
            'Las columnas visibles salen en el orden de CA-7.')

        # ...y las piezas de trazabilidad quedan RECUPERABLES, no borradas.
        hidden = ('move_id', 'sale_line_id', 'demand_qty', 'result',
                  'result_note')
        for name in hidden:
            node = root.xpath(
                "//field[@name='line_ids']//field[@name='%s']" % name)
            self.assertTrue(node, '"%s" sigue en el arch.' % name)
            self.assertEqual(
                node[0].get('optional'), 'hide',
                '"%s" queda fuera de la vista por defecto (CA-7).' % name)

        # CA-8 — la cabecera declara su contador, deja de pintar el rótulo
        # fuente y CONSERVA el check de excepción (§3.O · T10).
        self.assertTrue(
            root.xpath("//field[@name='candidate_count']"),
            'La cabecera declara "Lotes con existencia" (D-9).')
        source = root.xpath("//field[@name='source_label']")
        self.assertTrue(source, 'source_label sigue en el arch.')
        self.assertEqual(source[0].get('invisible'), '1')
        self.assertTrue(
            root.xpath("//field[@name='confirm_exception']"),
            'confirm_exception se CONSERVA (T10 de §3.O).')

    # ==================================================================
    # Candado — el código tocado no usa SQL crudo (§0.2)
    # ==================================================================
    def test_touched_files_have_no_raw_sql(self):
        module_path = get_module_path(_MODULE)
        for relative in _TOUCHED_FILES:
            target = os.path.join(module_path, relative)
            with open(target, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('cr.execute(', source, relative)
            self.assertNotIn('cr.commit(', source, relative)
