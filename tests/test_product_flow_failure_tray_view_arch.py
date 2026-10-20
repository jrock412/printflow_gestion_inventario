# -*- coding: utf-8 -*-
"""§3.U · T4 (Lote 2 `[pantalla]`): el contrato de la BANDEJA DE FALLAS vive en la VISTA.

Custodia el arch del form `printflow.flow.failure.tray` (§3.U · H-062 · H-064):
la zona de evidencias es UNA lista de 7 columnas (ya no la tarjeta kanban), el
documento se enlaza con la REFERENCIA nativa `document_ref`, cada fila declara su
acción principal (▶) y el saneo masivo ("SANEAR TODAS") solo existe para la
reserva colgada (`code == 'data_anomaly'`).

SON DE SOLO LECTURA: se inspecciona `view.arch_db`; el `TransactionCase` hace
rollback al terminar, así que NO se escribe ningún dato.
"""
from lxml import etree

from odoo.tests.common import TransactionCase, tagged

# Orden EXACTO de las 7 columnas de la lista de evidencias (decisión del dueño).
EVIDENCE_COLUMNS = [
    ('location_id', 'Ubicación'),
    ('lot_name', 'Lote'),
    ('physical_qty', 'A mano'),
    ('reserved_qty', 'Reservado'),
    ('delta_qty', 'Libre'),
    ('document_ref', 'Documento'),
    ('line_qty', 'Cantidad'),
]
# Rótulo técnico del botón por fila (columna invisible: no se pinta).
HIDDEN_LABEL = 'primary_label'


@tagged('post_install', '-at_install')
class TestProductFlowFailureTrayViewArch(TransactionCase):

    def _arch_root(self, xml_id):
        view = self.env.ref('printflow_gestion_inventario.' + xml_id)
        arch = view.arch_db
        if not isinstance(arch, (bytes, str)):
            arch = str(arch)
        if isinstance(arch, str):
            arch = arch.encode('utf-8')
        return etree.fromstring(arch)

    def _tray_form(self):
        return self._arch_root('printflow_flow_failure_tray_view_form')

    def _evidence_list(self):
        """La ÚNICA lista embebida de `line_ids` (sin kanban, sin dos formas)."""
        fields = self._tray_form().xpath("//field[@name='line_ids']")
        self.assertEqual(
            len(fields), 1, 'El form del tray declara `line_ids` una sola vez.')
        self.assertFalse(
            fields[0].xpath('.//kanban'),
            'H-062/H-064: la zona de evidencias ya NO es tarjeta (kanban).')
        trees = fields[0].xpath('./tree')
        self.assertEqual(
            len(trees), 1,
            'Debe haber UNA sola lista de evidencias (sustitución, no acumulación).')
        return trees[0]

    def test_evidence_list_replaces_the_kanban_card(self):
        tree = self._evidence_list()
        self.assertEqual(tree.get('create'), 'false')
        self.assertEqual(tree.get('delete'), 'false')
        self.assertEqual(
            tree.get('decoration-danger'), 'delta_qty < 0',
            'La fila colgada (Libre < 0) se pinta en rojo.')

    def test_evidence_list_declares_the_seven_columns_in_order(self):
        tree = self._evidence_list()
        declared = [el.get('name') for el in tree if el.tag == 'field']
        self.assertEqual(
            declared,
            [name for name, _label in EVIDENCE_COLUMNS] + [HIDDEN_LABEL],
            'Las 7 columnas acordadas, en su orden, + el rótulo del botón.')
        labels = [(el.get('name'), el.get('string'))
                  for el in tree if el.tag == 'field']
        for name, label in EVIDENCE_COLUMNS:
            self.assertIn(
                (name, label), labels,
                'La columna %s se rotula «%s».' % (name, label))

    def test_row_offers_the_principal_action_only(self):
        tree = self._evidence_list()
        buttons = tree.xpath("./button[@name='action_run_primary']")
        self.assertEqual(
            len(buttons), 1, 'Cada fila ofrece su acción principal (▶).')
        self.assertEqual(
            buttons[0].get('invisible'), 'not primary_label',
            'Sin acción principal declarada, la fila no muestra el botón.')
        self.assertFalse(
            tree.xpath("./button[@name='action_open']"),
            'El botón de la llave (H-064) se retiró: la fila se abre al tocarla.')

    def test_cleanup_all_exists_only_for_the_hanging_reservation(self):
        headers = self._tray_form().xpath('//header')
        self.assertEqual(len(headers), 1, 'El form del tray tiene UNA cabecera.')
        buttons = headers[0].xpath("./button[@name='action_cleanup_all']")
        self.assertEqual(
            len(buttons), 1, 'La cabecera declara el saneo masivo ("SANEAR TODAS").')
        self.assertEqual(buttons[0].get('string'), 'SANEAR TODAS')
        self.assertEqual(
            buttons[0].get('invisible'), "code != 'data_anomaly'",
            'CA-4: el masivo solo existe para la reserva colgada (las otras '
            'dos fallas no lo ven).')
