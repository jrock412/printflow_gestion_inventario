# -*- coding: utf-8 -*-
"""Candidatos del selector de lote: ``printflow.flow.lots._pf_available_lots``.

Custodia que la LECTURA PURA de candidatos:
  * agregue por lote (una sola lectura de ``stock.quant``),
  * calcule la disponible como ``cantidad - reservado``,
  * DESCARTE los lotes sin existencia disponible,
  * ORDENE por disponible descendente,
  * respete la EXCLUSIÓN solicitada,
  * y no crezca con N (sin N+1; presupuesto de consultas).

Es de SOLO LECTURA sobre datos ajenos: crea sus propios registros y
``TransactionCase`` hace rollback al terminar.
"""
from odoo.tests.common import TransactionCase, tagged

# Delta tolerado de consultas entre un poblado con pocos y con muchos lotes.
_QUERY_DELTA = 3


@tagged('post_install', '-at_install')
class TestProductFlowLotPickerCandidates(TransactionCase):
    """``_pf_available_lots`` agrega, ordena, excluye y no crece con N."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.env.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.Lots = cls.env['printflow.flow.lots']

    # ------------------------------------------------------------------
    # Utilidades
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

    def _stock(self, product, qty, lot=None, reserved=0.0):
        self.env['stock.quant']._update_available_quantity(
            product, self.stock_location, qty, lot_id=lot,
            reserved_quantity=reserved)

    def _measure(self, product):
        """Consultas de UNA lectura de candidatos (cachés frías)."""
        self.Lots._pf_available_lots(product)  # warm-up
        self.env.flush_all()
        self.env.cr.flush()
        self.env.invalidate_all()
        start = self.cr.sql_log_count
        self.Lots._pf_available_lots(product)
        self.env.flush_all()
        self.env.cr.flush()
        return self.cr.sql_log_count - start

    # ==================================================================
    # 1) Agrega, ordena, descarta sin existencia y excluye
    # ==================================================================
    def test_available_lots_aggregates_sorts_and_excludes(self):
        product = self._product('CANDIDATOS')
        lot_a = self._lot(product, 'CAND-A')
        self._stock(product, 10.0, lot=lot_a)
        lot_b = self._lot(product, 'CAND-B')
        self._stock(product, 5.0, lot=lot_b, reserved=2.0)
        lot_c = self._lot(product, 'CAND-C')  # sin quant -> no aparece

        result = self.Lots._pf_available_lots(product)
        ids = [cand['lot_id'] for cand in result]
        self.assertIn(lot_a.id, ids)
        self.assertIn(lot_b.id, ids)
        self.assertNotIn(lot_c.id, ids)

        # Orden por disponible descendente.
        avail = [cand['available'] for cand in result]
        self.assertEqual(avail, sorted(avail, reverse=True))

        # Disponible = cantidad - reservado.
        entry_b = next(c for c in result if c['lot_id'] == lot_b.id)
        self.assertAlmostEqual(entry_b['available'], 3.0)
        self.assertAlmostEqual(entry_b['reserved'], 2.0)
        self.assertAlmostEqual(entry_b['qty_on_hand'], 5.0)
        entry_a = next(c for c in result if c['lot_id'] == lot_a.id)
        self.assertAlmostEqual(entry_a['qty_on_hand'], 10.0)
        self.assertTrue(entry_a['location_names'])

        # Exclusión explícita (p. ej. el lote propio).
        result_no_a = self.Lots._pf_available_lots(
            product, exclude_lot_ids=[lot_a.id])
        self.assertNotIn(lot_a.id, [c['lot_id'] for c in result_no_a])

    # ==================================================================
    # 1b) ``include_lot_ids``: lotes forzados aunque tengan 0 existencia
    # ==================================================================
    def test_include_lot_ids_lists_zero_lots(self):
        product = self._product('CANDIDATOS INCLUDE')
        with_stock = self._lot(product, 'CAND-INC-STOCK')
        self._stock(product, 5.0, lot=with_stock)
        empty = self._lot(product, 'CAND-INC-EMPTY')  # sin quant -> 0

        # Por defecto NO aparece.
        default_ids = [c['lot_id'] for c in self.Lots._pf_available_lots(product)]
        self.assertNotIn(empty.id, default_ids)

        # Forzado: SÍ aparece, con ceros y NO ocupado.
        forced = self.Lots._pf_available_lots(
            product, include_lot_ids=[empty.id])
        entry = next(c for c in forced if c['lot_id'] == empty.id)
        self.assertAlmostEqual(entry['available'], 0.0)
        self.assertAlmostEqual(entry['available_here'], 0.0)
        self.assertFalse(entry['is_occupied'])

    # ==================================================================
    # 2) Disponibilidad EN la ubicación + cobertura de la demanda
    # ==================================================================
    def test_available_lots_exposes_here_and_covers_demand(self):
        product = self._product('CANDIDATOS AQUI')
        lot = self._lot(product, 'CAND-AQUI')
        self._stock(product, 4.0, lot=lot)

        result = self.Lots._pf_available_lots(
            product, location_id=self.stock_location.id, demand_qty=6.0)
        entry = next(c for c in result if c['lot_id'] == lot.id)
        self.assertAlmostEqual(entry['available_here'], 4.0)
        self.assertFalse(entry['covers_demand'], '4 no cubre la demanda 6.')

        result_ok = self.Lots._pf_available_lots(
            product, location_id=self.stock_location.id, demand_qty=2.0)
        entry_ok = next(c for c in result_ok if c['lot_id'] == lot.id)
        self.assertTrue(entry_ok['covers_demand'], '4 sí cubre la demanda 2.')

    # ==================================================================
    # 3) Una lectura agregada (sin N+1): el conteo no crece con N
    # ==================================================================
    def test_available_lots_query_count_is_constant(self):
        product = self._product('CANDIDATOS PRESUPUESTO')
        for index in range(3):
            lot = self._lot(product, 'CAND-B3-%d' % index)
            self._stock(product, 5.0, lot=lot)
        q_small = self._measure(product)

        for index in range(3, 15):
            lot = self._lot(product, 'CAND-B15-%d' % index)
            self._stock(product, 5.0, lot=lot)
        q_big = self._measure(product)

        self.assertLessEqual(
            abs(q_big - q_small), _QUERY_DELTA,
            '_pf_available_lots no debe crecer con N (3->%d, 15->%d)'
            % (q_small, q_big))
