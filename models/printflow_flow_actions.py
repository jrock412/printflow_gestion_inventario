# -*- coding: utf-8 -*-
"""Kit de acciones y shapes del canvas de flujo (PrintFlow).

Servicio ``AbstractModel`` sin tabla que concentra la FÁBRICA de acciones del
popover y las fábricas de SHAPE de fila (panel/tray), además de la acción de
"Ver pendientes (N)". Garantiza que el PEDIDO y el PRODUCTO emitan exactamente
el MISMO contrato de acción y el MISMO shape de fila (paridad de claves).

Se EXTRAJO del servicio ``printflow.flow.canvas`` (Fase 2 del refactor OOP,
``docs/plan_fases_orquestador_oop_v2.md``) SIN cambiar comportamiento: la
fábrica ``_pf_action`` se movió TAL CUAL y el canvas DELEGA en este objeto. No
toca la base de datos ni el motor de reglas: es una hoja de presentación pura
que solo arma dicts a partir de valores ya resueltos por el host del canvas.

Contrato::

    env['printflow.flow.actions']._pf_action(key, label, ...) -> dict
    env['printflow.flow.actions']._pf_pending_action(host, node_key, count) -> dict
    env['printflow.flow.actions']._pf_panel_row(shape) -> dict
    env['printflow.flow.actions']._pf_tray_row(shape) -> dict
"""

from odoo import _, api, models


class PrintflowFlowActions(models.AbstractModel):
    """Kit de acciones y shapes de fila del canvas de flujo."""

    _name = 'printflow.flow.actions'
    _description = 'Kit de acciones y shapes del canvas de flujo (PrintFlow)'

    # Grupos con permiso para el saneamiento de reservas (mismos que la vista).
    # Constante PURA de acciones: la consume el chequeo del canvas.
    _PF_CLEAN_GROUP_XMLIDS = ('mrp.group_mrp_manager', 'base.group_system')

    # ══════════════════════════════════════════════════════════════════════
    # ACCIONES DEL POPOVER
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_action(self, key, label, kind='navigate', failure_id=None,
                   res_model=None, res_id=None, method=None, enabled=True,
                   target_key=None, args=None, primary=False, sublabel=None):
        """Contrato de una acción del popover."""
        action = {
            'key': key,
            'label': label or '',
            'enabled': bool(enabled),
            'kind': kind or 'navigate',
            'failure_id': failure_id,
            'res_model': res_model,
            'res_id': res_id,
            'method': method,
        }
        if args:
            action['args'] = list(args)
        if target_key:
            action['target_key'] = target_key
        if primary:
            action['primary'] = True
        if sublabel:
            action['sublabel'] = sublabel
        return action

    @api.model
    def _pf_pending_action(self, host, node_key, count):
        """Shape de acción "Ver pendientes (N)" de un hito del canvas.

        Mismo contrato para pedido y producto: navega al listado de pendientes
        del nodo mediante el método público ``action_open_node_pending`` del
        host (por duck typing, sin importar el modelo).
        """
        return self._pf_action(
            'pending', _('Ver pendientes (%s)') % count,
            kind='navigate',
            res_model=host._name, res_id=host.id,
            method='action_open_node_pending', args=[node_key])

    # ══════════════════════════════════════════════════════════════════════
    # SHAPES DE FILA (panel y tray)
    # ══════════════════════════════════════════════════════════════════════
    @api.model
    def _pf_panel_row(self, shape):
        """Shape CANÓNICO de una fila del panel (pedido y producto).

        Recibe los valores ya resueltos (registro o dict) y devuelve el MISMO
        conjunto y orden de claves para ambos casos, de modo que la fila del
        panel no pueda divergir entre pedido y producto.
        """
        return {
            'failure_id': shape.get('failure_id'),
            'label': shape.get('label'),
            'detail': shape.get('detail'),
            'origin': shape.get('origin'),
            'origin_kind': shape.get('origin_kind'),
            'chain_note': shape.get('chain_note'),
            'plan_summary': shape.get('plan_summary'),
            'role': shape.get('role'),
            'tone': shape.get('tone'),
            'is_consequence': shape.get('is_consequence'),
            'problem_available': shape.get('problem_available'),
            'solution_available': shape.get('solution_available'),
            'collect_available': shape.get('collect_available'),
            'actions': shape.get('actions'),
        }

    @api.model
    def _pf_tray_row(self, shape):
        """Shape CANÓNICO de una fila del tray (pedido y producto).

        Normaliza los valores ya resueltos al MISMO conjunto de claves y con los
        mismos respaldos (``''`` para texto, ``False`` para ``res_id``) que el
        canvas histórico, para no cambiar el payload.
        """
        return {
            'label': shape.get('label') or '',
            'detail': shape.get('detail') or '',
            'ref_name': shape.get('ref_name') or '',
            'state_label': shape.get('state_label') or '',
            'res_model': shape.get('res_model') or '',
            'res_id': shape.get('res_id') or False,
        }
