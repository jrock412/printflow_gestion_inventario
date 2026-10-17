# -*- coding: utf-8 -*-
"""FASE 2 — Escáner de diagnóstico de producto.

Cubre:
  (a) el escáner corre sobre una variante y produce hallazgos;
  (b) ``bom_archive_blocked`` detecta la línea bloqueante y EXCLUYE una línea
      'invoiced';
  (c) extensibilidad: un chequeo INYECTADO desde el test (sin tocar el motor ni
      los chequeos existentes) aparece en el barrido.

Nota técnica (c): Odoo no registra automáticamente los modelos que se definen a
nivel de módulo dentro de `tests/` (la registry ya se construyó). Por eso la
extensibilidad se demuestra inyectando el chequeo con `mock.patch` sobre el
método `_pf_get_checks`: el motor lo consume igual que a los chequeos reales.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiagnosticProductScanner(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Cliente Escaner Diagnostico',
        })
        cls.Scanner = cls.env['printflow.product.diagnostic.wizard']

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _make_product(self, name):
        return self.env['product.product'].create({
            'name': name,
            'type': 'product',
        })

    def _make_phantom_bom(self, product):
        return self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'type': 'phantom',
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
        })

    def _make_sale_line(self, product, qty=1.0, invoice_status=None):
        """Pedido forzado a 'sale' con una línea del producto (patrón FASE 1).

        Una venta confirmada REAL siempre tiene movimientos de stock. El core
        (``_ensure_bom_is_free``) exige que exista al menos uno NO cancelado
        (``move_ids.state != 'cancel'``), por lo que aquí se crea uno en
        borrador vinculado a la línea: así el escenario reproduce producción sin
        disparar la cadena de entrega/fabricación.
        """
        sale_order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom': product.uom_id.id,
            })],
        })
        sale_order.write({'state': 'sale'})
        line = sale_order.order_line[:1]
        self.env['stock.move'].create({
            'name': product.display_name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'sale_line_id': line.id,
            'location_id': self.env['stock.location'].search(
                [('usage', '=', 'internal')], limit=1).id,
            'location_dest_id': self.env['stock.location'].search(
                [('usage', '=', 'customer')], limit=1).id,
        })
        if invoice_status:
            line.write({'invoice_status': invoice_status})
        return line

    def _finding(self, wizard, code):
        return wizard.finding_ids.filtered(lambda f: f.check_code == code)

    # ------------------------------------------------------------------
    # (a) El escáner corre y produce hallazgos
    # ------------------------------------------------------------------
    def test_scanner_runs_on_variant(self):
        product = self._make_product('ESCANER BASICO (DIAG)')
        wizard = self.Scanner.create({'product_id': product.id})

        self.assertTrue(
            wizard.finding_ids,
            'El escáner debe producir hallazgos para una variante.',
        )
        self.assertGreaterEqual(
            wizard.check_total, 10,
            'Debe ejecutar al menos los 10 chequeos del motor.',
        )
        self.assertIn(
            wizard.overall_severity, ('ok', 'warning', 'error'),
            'El resultado global debe ser un valor válido.',
        )
        self.assertEqual(wizard.product_id, product)
        self.assertTrue(
            self._finding(wizard, 'record_state'),
            'El chequeo de ficha (record_state) debe aparecer en el barrido.',
        )

    # ------------------------------------------------------------------
    # (b) bom_archive_blocked: detecta bloqueante y excluye 'invoiced'
    # ------------------------------------------------------------------
    def test_bom_archive_blocked_detects_blocking_and_skips_invoiced(self):
        product = self._make_product('KIT BLOQUEADO ESCANER (DIAG)')
        self._make_phantom_bom(product)

        blocking_line = self._make_sale_line(product)  # queda 'to invoice'
        invoiced_line = self._make_sale_line(product, invoice_status='invoiced')
        self.assertEqual(blocking_line.invoice_status, 'to invoice')
        self.assertEqual(invoiced_line.invoice_status, 'invoiced')

        wizard = self.Scanner.create({'product_id': product.id})
        findings = self._finding(wizard, 'bom_archive_blocked')

        self.assertTrue(findings, 'Debe reportar el bloqueo de archivado.')
        finding = findings[:1]
        self.assertEqual(finding.severity, 'error')

        blocking_orders = finding.evidence_ids.mapped('sale_order_id')
        self.assertIn(
            blocking_line.order_id, blocking_orders,
            'La línea a facturar debe figurar como evidencia bloqueante.',
        )
        self.assertNotIn(
            invoiced_line.order_id, blocking_orders,
            'Una línea ya facturada NUNCA debe aparecer como bloqueante.',
        )

        # La resolución abre el registro real a pantalla completa.
        action = finding.action_open()
        self.assertEqual(action.get('target'), 'current')

    # ------------------------------------------------------------------
    # (d) Navegación de lista: sale_orders / mo_list
    # ------------------------------------------------------------------
    def test_action_open_sale_orders_lists_blocking_orders(self):
        """El error de archivado debe abrir EN 1 CLIC la lista de pedidos."""
        product = self._make_product('KIT SALE ORDERS (DIAG)')
        self._make_phantom_bom(product)
        blocking_line = self._make_sale_line(product)

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'bom_archive_blocked')[:1]

        self.assertEqual(
            finding.nav_kind, 'sale_orders',
            'El bloqueo de archivado debe navegar a la lista de pedidos.',
        )
        self.assertTrue(
            finding.action_hint,
            'El hallazgo debe exponer una pista "Dónde corregir".',
        )
        action = finding.action_open_solution()
        self.assertEqual(action['res_model'], 'sale.order')
        self.assertEqual(action['view_mode'], 'tree,form')
        self.assertEqual(action['target'], 'current')
        self.assertIn(
            blocking_line.order_id.id, action['domain'][0][2],
            'El pedido bloqueante debe estar en el dominio de la lista.',
        )

    def test_action_open_mo_list_lists_productions(self):
        """Las MO activas deben abrirse como lista de órdenes de fabricación."""
        product = self._make_product('MO LIST (DIAG)')
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': product.product_tmpl_id.id,
            'type': 'normal',
            'product_qty': 1.0,
            'product_uom_id': product.uom_id.id,
        })
        mo = self.env['mrp.production'].create({
            'product_id': product.id,
            'product_qty': 1.0,
            'bom_id': bom.id,
        })

        wizard = self.Scanner.create({'product_id': product.id})
        finding = self._finding(wizard, 'active_mo')[:1]

        self.assertEqual(
            finding.nav_kind, 'mo_list',
            'Las MO activas deben navegar a una lista de órdenes de fabricación.',
        )
        action = finding.action_open_problem()
        self.assertEqual(action['res_model'], 'mrp.production')
        self.assertEqual(action['view_mode'], 'tree,form')
        self.assertEqual(action['target'], 'current')
        self.assertIn(
            mo.id, action['domain'][0][2],
            'La MO activa debe estar en el dominio de la lista.',
        )

    # ------------------------------------------------------------------
    # (e) Presentación legible: _rec_name y orden por severidad
    # ------------------------------------------------------------------
    def test_rec_names_are_human_readable(self):
        """Ningún registro debe mostrarse como "ID n"."""
        product = self._make_product('RECNAME (DIAG)')
        wizard = self.Scanner.create({'product_id': product.id})
        finding = wizard.finding_ids[:1]
        self.assertEqual(
            finding.display_name, finding.title,
            'El hallazgo debe tener el título como nombre legible.',
        )

        evidence = self.env['printflow.product.diagnostic.evidence'].create({
            'finding_id': finding.id,
            'label': 'Evidencia legible (DIAG)',
        })
        self.assertEqual(
            evidence.display_name, 'Evidencia legible (DIAG)',
            'La evidencia debe usar su etiqueta como nombre legible.',
        )

    def test_findings_are_ordered_errors_first(self):
        """La prioridad derivada de la severidad deja los errores arriba."""
        product = self._make_product('KIT RANK (DIAG)')
        self._make_phantom_bom(product)
        self._make_sale_line(product)

        wizard = self.Scanner.create({'product_id': product.id})
        # Se lee con un search explícito: el one2many recién creado puede venir
        # en orden de caché, pero el `_order` del modelo (que aplica la UI al
        # recargar) sí debe dejar los errores primero.
        Finding = self.env['printflow.product.diagnostic.finding']
        ordered = Finding.search([('wizard_id', '=', wizard.id)])
        ranks = ordered.mapped('severity_rank')
        self.assertEqual(
            ranks, sorted(ranks),
            'Los hallazgos deben venir ordenados por prioridad (error primero).',
        )
        errors = ordered.filtered(lambda f: f.severity == 'error')
        if errors:
            self.assertEqual(errors[:1].severity_rank, 0)

    # ------------------------------------------------------------------
    # (c) Extensibilidad: un chequeo externo aparece en el barrido
    # ------------------------------------------------------------------
    def test_new_check_appears_without_touching_existing_ones(self):
        mixin_model = type(self.env['printflow.product.check.mixin'])
        original_get_checks = mixin_model._pf_get_checks

        def extended_get_checks(self):
            return original_get_checks(self) + [{
                'code': 'test_extensible',
                'area': 'record',
                'sequence': 999,
                'method': self._pf_check_test_extensible_external,
            }]

        def _pf_check_test_extensible_external(self, ctx):
            return [self._pf_finding(
                'test_extensible', 'record', 'info',
                'Chequeo de prueba (extensibilidad)',
                detail='Hallazgo inyectado sin tocar el motor ni los chequeos existentes.',
            )]

        product = self._make_product('ESCANER EXTENSIBLE (DIAG)')
        with patch.object(mixin_model, '_pf_get_checks', extended_get_checks), \
                patch.object(
                    mixin_model,
                    '_pf_check_test_extensible_external',
                    _pf_check_test_extensible_external,
                    create=True,
                ):
            wizard = self.Scanner.create({'product_id': product.id})

        self.assertTrue(
            self._finding(wizard, 'test_extensible'),
            'Un chequeo inyectado debe aparecer en el barrido como cualquier otro.',
        )
