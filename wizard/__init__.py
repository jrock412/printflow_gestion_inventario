# -*- coding: utf-8 -*-
"""Asistentes (wizards) del diagnóstico PrintFlow."""

from . import printflow_product_diagnostic_wizard
from . import printflow_bom_archive_diagnostic_wizard
# Diagnóstico de PEDIDO (Niveles 2/3): la BASE antes que sus extensiones. Un
# ``_inherit`` sin ``_name`` exige que su base ya esté en el registry. Orden:
# base -> line_levels -> failure -> evidence -> levels -> resolution_plan.
from . import printflow_order_diagnostic_wizard
from . import printflow_order_diagnostic_line_levels
from . import printflow_order_diagnostic_failure
from . import printflow_order_diagnostic_evidence
from . import printflow_order_diagnostic_levels
from . import printflow_order_resolution_plan
# Fase 5: diagrama de flujo de un PRODUCTO sin venta. Consume el canvas
# compartido (``printflow.flow.canvas``) y el motor de flujo. No hereda ningún
# wizard, así que puede registrarse aquí sin dependencias de orden.
from . import printflow_product_flow
# Bandeja gestionable de lote: la abre el "Solucionar" de un hallazgo de lote.
# No hereda ningún wizard (TransientModel propio), así que no depende del orden.
from . import printflow_flow_lot_tray
# Selector de lote por DOCUMENTO (decisión consciente): la fila candidata se
# importa ANTES que el selector que la referencia (One2many).
from . import printflow_flow_lot_candidate
# Asignación EN BLOQUE de UN lote a N entregas: la LÍNEA de destino se importa
# ANTES del contenedor que la referencia (One2many). Reutiliza la fila candidata
# de arriba (``bulk_id``) y el selector por documento de abajo.
from . import printflow_flow_lot_assign_bulk_line
from . import printflow_flow_lot_assign_bulk
# DETALLE del resultado del bloque (H-029): hace LEGIBLE el motivo por destino.
# La LÍNEA se importa ANTES que la cabecera que la referencia (One2many). Va
# justo después del contenedor porque consume sus destinos (``bulk.line_ids``).
from . import printflow_flow_lot_assign_bulk_result_line
from . import printflow_flow_lot_assign_bulk_result
from . import printflow_flow_lot_picker
# Modal de AUTORIZACIÓN de un lote como excepción documentada: lo abre el botón
# de fila "Autorizar excepción" de la bandeja de lote. TransientModel propio.
from . import printflow_flow_lot_exception_authorize
# Modal de AUTORIZACIÓN EN BLOQUE (varios lotes + UN motivo): lo abre la acción
# sobre la selección de la bandeja de lote. TransientModel propio.
from . import printflow_flow_lot_exception_authorize_bulk
# EXCEPCIONES FORMALES GENÉRICAS (F4): autorización de UN hallazgo y en BLOQUE.
# La LÍNEA del bloque se importa antes del wizard que la referencia (One2many).
from . import printflow_finding_exception_authorize_line
from . import printflow_finding_exception_authorize
from . import printflow_finding_exception_authorize_bulk
# Confirmación de RIESGO (F5): las correcciones de la bandeja de lote que tocan
# inventario quedan SECUNDARIAS y exigen este aviso.
from . import printflow_lot_risk_confirm
# Bandeja gestionable de INSUMOS: la abre el "Solucionar" del hito de insumos.
# No hereda ningún wizard (TransientModel propio), así que no depende del orden.
from . import printflow_flow_supply_tray
# Bandeja GENÉRICA de fallas guiadas (Fase 1): la abre el "Solucionar" de la
# falla huérfana. Un archivo por modelo y en orden de dependencia
# (línea -> acción -> cabecera).
from . import printflow_flow_failure_tray_line
from . import printflow_flow_failure_tray_action
from . import printflow_flow_failure_tray
# Extensiones del hallazgo/evidencia: se importan DESPUÉS del wizard base para
# que ``printflow.product.diagnostic.finding``/``...evidence`` ya existan en el
# registry (un ``_inherit`` sin ``_name`` no puede adelantarse a su base).
from ..models import printflow_finding_resolution
from ..models import printflow_evidence_resolution
