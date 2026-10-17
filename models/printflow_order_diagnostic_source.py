# -*- coding: utf-8 -*-
"""Interfaz/adaptador de fuente del diagnóstico de pedido (PrintFlow).

``AbstractModel`` que desacopla el diagnóstico de su origen. Hoy la única fuente
es ``printflow.order.board``, pero el wizard solo conoce:

* ``source_model`` (Char),
* ``source_res_id`` (Integer),
* ``source_label`` (Char).

El adaptador resuelve el registro fuente y le pide un **paquete normalizado**;
así el núcleo del diagnóstico no declara ningún ``Many2one`` al tablero y una
segunda fuente (POS, pedido de compra, etc.) se puede enchufar sin tocar el
wizard. Sin estado ni tabla: cero migración.

Contrato del paquete devuelto por ``_pf_get_order_inputs``::

    {
        'order': sale.order | False,
        'flags': {...},                 # banderas del pedido (health_* incluidas)
        'lines': [{'product', 'qty', 'uom', 'kind', 'parent'}, ...],
        'stock': {product_id: {...}},   # snapshot de existencia/reservas
        'production': {product_id: {'active': [mo...], 'done': [mo...]}},
        'purchase': {'incoming': {...}, 'pending_product_ids': set,
                     'has_purchase': bool},
        'design': {'pending_product_ids': set},
        'documents': {'sale', 'pickings', 'purchase_orders', 'manufactures'},
    }
"""
from odoo import api, models


class PrintflowOrderDiagnosticSource(models.AbstractModel):
    """Adaptador de fuentes del diagnóstico de pedido."""

    _name = 'printflow.order.diagnostic.source'
    _description = 'Fuente del diagnóstico de pedido (PrintFlow)'

    @api.model
    def _pf_supported_models(self):
        """Modelos fuente soportados (extensible sin tocar el wizard)."""
        return {'printflow.order.board'}

    @api.model
    def _pf_supports(self, source_model):
        """True si ``source_model`` sabe construir un paquete de diagnóstico."""
        return bool(source_model) and source_model in self._pf_supported_models()

    @api.model
    def _pf_get_order_inputs(self, source_model, source_res_id):
        """Paquete normalizado del pedido, o ``{}`` si la fuente no aplica.

        El adaptador no conoce las reglas: solo delega en el registro fuente
        (``_pf_build_order_inputs``). Así el motor de reglas y el wizard quedan
        aislados de la implementación concreta.
        """
        if not self._pf_supports(source_model) or not source_res_id:
            return {}
        record = self.env[source_model].browse(source_res_id).exists()
        builder = getattr(record, '_pf_build_order_inputs', None) if record else None
        return builder() if builder else {}
