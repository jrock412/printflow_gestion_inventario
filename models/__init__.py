# -*- coding: utf-8 -*-
# Orden de carga por CAPAS (OOP) + superficies del tablero de Salud de
# Inventario. Se conserva el orden original de `diagnostic/models/__init__.py`
# y se anexan, al final, las superficies que viajaron desde `models/` del
# addon principal.
#
# 1) Motor de chequeos (mixin) y presentación pura del canvas.
from . import printflow_product_check_mixin
from . import printflow_flow_presentation
# 2) Kit de acciones y shapes de fila (panel/tray) del canvas.
from . import printflow_flow_actions
# 2b) Colaborador HOJA de lotes del canvas (AbstractModel PURO, sin tabla). Se
#     registra DESPUÉS del kit de acciones y ANTES de las estrategias: la
#     estrategia del producto lo consume para inyectar la falla normalizada de
#     lote por los canales EXISTENTES (panel/summary/actions/explain).
from . import printflow_flow_lots
# 2c) Colaborador HOJA de INSUMOS del canvas (AbstractModel PURO, sin tabla). Se
#     registra junto al de lotes: la estrategia del producto lo consume para
#     inyectar la falla normalizada de insumos y habilitar su bandeja.
from . import printflow_flow_supply
# 2d) PATRÓN DE FALLAS GUIADAS (Fase 1): contrato base + registry + fallas
#     concretas (AbstractModels PUROS, sin tabla). El CONTRATO base se importa
#     ANTES de sus subclases (un `_inherit` exige la base en el registry), y el
#     registry va entre el contrato y las fallas (resuelve por NOMBRE).
from . import printflow_flow_failure
from . import printflow_flow_failure_registry
from . import printflow_flow_failure_generic
from . import printflow_flow_failure_lot_orphan
#     Falla de RESERVA COLGADA (causa ``data_anomaly``): separa "reserva colgada
#     real" (reserva > físico) de "existencia negativa" (que NO es esta falla).
from . import printflow_flow_failure_over_reservation
#     Falla de LOTE SIN EXISTENCIA (causa ``lot_no_stock``): un lote asignado en
#     una ``stock.move.line`` activa sin stock del lote. Su "Solucionar" abre la
#     bandeja guiada (una fila por lote + saneo ``reassign``). La falla la
#     resuelve el registry por NOMBRE en runtime.
from . import printflow_flow_failure_lot_no_stock
# 3) INTERFAZ de la estrategia + adaptadores por caso (pedido / producto).
from . import printflow_flow_strategy
from . import printflow_flow_strategy_order
from . import printflow_flow_strategy_product
# 4) BUILDER ÚNICO del payload.
from . import printflow_flow_payload_builder
# 5) SELECTOR / Factory del canvas (resuelve `mode` -> estrategia por NOMBRE).
from . import printflow_flow_registry
# 6) ORQUESTADOR delgado.
from . import printflow_flow_canvas
# 7) Esquema compartido de causantes + chequeos + BOM y playbook.
from . import printflow_diagnostic_causante_mixin
from . import checks
from . import mrp_bom
from . import printflow_resolution_playbook
# Capa de EXPLICACIÓN por nodo (AbstractModel PURO, sin tabla). Consume el
# playbook y el estado de lote de `stock.health`; la usa el builder del canvas.
from . import printflow_flow_explain
# 8) Motor UNIFICADO de causa-raíz por flujo y fuente del diagnóstico.
from . import printflow_flow_diagnostic
from . import printflow_order_diagnostic_source
from . import printflow_order_blocking_reservation
# 9) Lanzadores de la ficha de producto (escáner + archivado de BOM kit).
from . import product_template
# 10) Enganche del Tablero: sobreescribe el hook `_pf_diagnostic_action`.
from . import printflow_order_board_diagnostic
# 11) SUPERFICIES del tablero de Salud de Inventario (movidas desde `models/`).
#     `printflow.flow.pending` es el motor de pendientes (AbstractModel).
from . import printflow_flow_pending
#     Bandeja de salud (TransientModel, importa selecciones del principal).
from . import printflow_inventory_health
#     Línea de pendientes (TransientModel; define PENDING_NODE_SELECTION).
from . import printflow_node_pending_line
#     Catálogo de productos (TransientModel). Importa la selección de nodos de
#     la línea, por eso va DESPUÉS de `printflow_node_pending_line`.
from . import printflow_inventory_catalog
#     Override del catálogo (drill-down al diagrama de flujo). Debe ir DESPUÉS
#     del modelo base para que `_inherit` encuentre la clase registrada.
from . import printflow_inventory_catalog_flow
# 12) Configuración de GI (pf_node_pending_* + pf_catalog_limit). Importa las
#     constantes del motor de pendientes, por eso va al final.
from . import res_config_settings
# 13) EXCEPCIONES FORMALES GENÉRICAS (F1/F2): registry (lista blanca, sin tabla)
#     + modelo persistente + adaptador de filtrado. El registry se importa ANTES
#     del modelo y del adaptador (ambos lo resuelven por NOMBRE en runtime). El
#     adaptador solo lo consumen las superficies existentes (parche quirúrgico).
from . import printflow_finding_exception_registry
from . import printflow_finding_exception
from . import printflow_finding_exception_filter
# 14) BRIDGE de la Compra Rápida (``mrp.quick.purchase.wizard``): enganche
#     ADITIVO que agrega ``pf_freeze_qty`` (cantidad congelada del faltante real,
#     D3) SIN tocar el motor externo ``x_product_dimensional_pricing``. Va al
#     final para que el modelo heredado ya esté cargado en el registry.
from . import printflow_quick_purchase_bridge
# 15) PRESENTACIÓN del pedido en el selector de la Compra Rápida (D5): hereda
#     ``sale.order`` para mostrar "número − cliente" SOLO bajo el contexto
#     ``pf_purchase_partner_label`` que activa la vista heredada del wizard.
#     Sin ese contexto, el ``display_name`` del pedido queda INTACTO.
from . import printflow_sale_order_display
# 16) LOTE PREVISTO en la Orden de Compra (D1/D2): hereda ``purchase.order`` para
#     persistir ``pf_lot_name`` y, al confirmar, PRELLENAR el lote del albarán de
#     entrada abierto (``_inherit`` + ``super()``; reutiliza el helper canónico
#     ``mrp.production._get_or_create_lot``). Campo + prellenado, cambios ADITIVOS:
#     no toca el motor ``x_product_dimensional_pricing`` ni la Compra Rápida normal.
from . import purchase_order
# 17) CANDADO DE FICHAS TERMINALES (H-013): hereda ``mrp.technical.sheet`` para
#     EXTENDER de forma ADITIVA la whitelist del candado con el campo computado
#     ``is_partial_fabrication`` (que ``_compute_state_from_docs`` asigna TAMBIÉN
#     a las fichas archivadas y que, al no estar en la whitelist, impedía validar
#     el albarán de entrada). Sobrescribe el método-seam
#     ``_printflow_skip_terminal_write_lock`` con ``super()``; NO toca el motor
#     ``x_product_dimensional_pricing`` ni su constante de whitelist.
from . import mrp_technical_sheet
# 18) SANEO ACOTADO de la reserva colgada (H-022 · D4): hereda ``printflow.stock.remedy``
#     (del motor) para AGREGAR ``_pf_release_hanging_lot_reservation``, que suelta SOLO
#     las líneas que apuntan al quant colgado (misma ubicación+lote) y NUNCA una entrega
#     sana con su lote y existencia. El método global del motor queda INTACTO; se hereda,
#     no se edita (motor ``x_product_dimensional_pricing`` SIN CAMBIOS).
from . import printflow_stock_remedy
# 19) PRESERVACIÓN de la reserva de lote EXCEPTUADA al re-asignar (H-030): hereda
#     ``stock.move`` para sobrescribir con ``super()`` el seam ``_assign_exclusive_lot``
#     y aplicar a la rama EXCLUSIVA del motor la regla del propio core ("ya reservado ⇒
#     no se toca"). Solo PRESERVA (no escribe inventario); el motor
#     ``x_product_dimensional_pricing`` queda INTACTO.
from . import stock_move
