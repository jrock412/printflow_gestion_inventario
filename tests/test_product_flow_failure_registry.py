# -*- coding: utf-8 -*-
"""Registry de fallas guiadas (PrintFlow · Fase 1).

Candado del SELECTOR de fallas (``printflow.flow.failure.registry``):
  * resuelve un código CONOCIDO al modelo de la falla correcta;
  * un código DESCONOCIDO (o vacío) cae a la falla GENÉRICA
    (``printflow.flow.failure.generic``) y NUNCA devuelve vacío;
  * ``_pf_supported`` expone los códigos mapeados (vocabulario existente,
    reutilizado: ``lot_orphan_reservation``).

Es de solo lectura: no crea registros.
"""
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductFlowFailureRegistry(TransactionCase):
    """El registry resuelve por código y nunca devuelve vacío."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Registry = cls.env['printflow.flow.failure.registry']

    def test_known_code_resolves_to_failure_model(self):
        failure = self.Registry._pf_failure_for('lot_orphan_reservation')
        self.assertEqual(failure._name, 'printflow.flow.failure.lot.orphan')
        self.assertEqual(failure._pf_fault_code(), 'lot_orphan_reservation')

    def test_supported_codes_include_orphan(self):
        self.assertIn('lot_orphan_reservation', self.Registry._pf_supported())

    def test_unknown_code_falls_back_to_generic(self):
        failure = self.Registry._pf_failure_for('no_existe_esta_falla')
        self.assertEqual(failure._name, 'printflow.flow.failure.generic')
        self.assertEqual(failure._pf_fault_code(), 'generic')

    def test_empty_code_falls_back_to_generic(self):
        for code in (None, '', False):
            failure = self.Registry._pf_failure_for(code)
            self.assertEqual(failure._name, 'printflow.flow.failure.generic')
