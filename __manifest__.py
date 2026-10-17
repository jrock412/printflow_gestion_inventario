# -*- coding: utf-8 -*-
{
    'name': 'PrintFlow: Gestión de Inventario',
    'version': '17.0.1.3.0',
    'category': 'Inventory',
    'summary': 'Diagnóstico de pedido/producto y Salud de Inventario de la suite PrintFlow',
    'description': """
PrintFlow: Gestión de Inventario
================================

Addon de la suite PrintFlow que **se conecta** al addon principal
``x_product_dimensional_pricing`` (tablero, motor de salud y servicios de
stock).

* **Diagnóstico de PRODUCTO**: escáner extensible de chequeos (inventario, kit,
  BOM duplicada/bloqueada, reglas de reorden, UdM, rutas, ventas, fabricación,
  flujo) con evidencias navegables, bandeja de resolución y archivado de BOM kit.
* **Diagnóstico de PEDIDO (Niveles 2/3)**: wizard "Diagnóstico y Ruta de
  Solución" con la línea de tiempo OWL (diagrama de flujo) y el detalle de área,
  fallas, evidencias y plan de resolución, más la lista "quién me bloquea".
* **Salud de Inventario**: bandeja de alertas, catálogo de Productos, lista de
  Pendientes y mantenimiento (purga de huérfanos / saneamiento).

Dirección de dependencia: este addon DEPENDE de ``x_product_dimensional_pricing``
y solo LEE su cerebro de reglas (health engine / stock.health / stock.remedy).
""",
    'author': 'IMPREVEN / PrintFlow',
    'license': 'LGPL-3',
    'depends': ['x_product_dimensional_pricing'],
    'data': [
        # Seguridad primero (incluye las 13 filas del diagnóstico + las 3 de las
        # superficies parkeadas: inventory.health, inventory.catalog,
        # node.pending.line).
        'security/ir.model.access.csv',
        # Regla de compañía de las excepciones formales (F1). Va DESPUÉS del CSV
        # y requiere que el modelo `printflow.finding.exception` ya exista.
        'security/printflow_finding_exception_security.xml',
        # --- PRODUCTO: las bases antes que sus herencias ---
        'wizard/printflow_product_diagnostic_views.xml',
        'wizard/printflow_product_finding_views.xml',
        'wizard/printflow_product_resolution_tray_views.xml',
        'wizard/printflow_bom_archive_diagnostic_views.xml',
        'views/mrp_bom_views.xml',
        'views/product_views.xml',
        # Heredan la bandeja de resolución del producto: van al final.
        'wizard/printflow_product_resolution_plan_views.xml',
        # --- PEDIDO (Niveles 2/3): la base antes que sus herencias ---
        'wizard/printflow_order_diagnostic_wizard_views.xml',
        'wizard/printflow_order_diagnostic_levels_views.xml',
        'wizard/printflow_order_diagnostic_evidence_views.xml',
        'views/printflow_order_blocking_reservation_views.xml',
        'wizard/printflow_order_resolution_plan_views.xml',
        # Diagrama de flujo de un PRODUCTO (mismo widget OWL del pedido).
        'wizard/printflow_product_flow_views.xml',
        # Vista HEREDADA de la Compra Rápida (motor x_product_dimensional_pricing):
        # botón "Traer pedidos que requieren compra" + contexto "número − cliente"
        # del selector. Va DESPUÉS de la vista base del wizard (dependencia).
        'views/printflow_quick_purchase_views.xml',
        # Bandeja gestionable de lote (la abre el "Solucionar" de un hallazgo
        # de lote del diagrama de producto).
        'wizard/printflow_flow_lot_tray_views.xml',
        # Selector de lote por documento (lo abre el botón de fila "Elegir
        # lote" de la bandeja). Tree de candidato + form del selector. Va ANTES
        # del form del bloque: este REUTILIZA su tree de candidato.
        'wizard/printflow_flow_lot_picker_views.xml',
        # Modal de ASIGNACIÓN DE UN LOTE EN BLOQUE (lo abre la acción sobre la
        # SELECCIÓN de la bandeja): candidatos + destinos + un motivo.
        'wizard/printflow_flow_lot_assign_bulk_views.xml',
        # Modal para AUTORIZAR el lote de una fila como excepción documentada
        # (lo abre el botón de fila "Autorizar excepción" de la bandeja).
        'wizard/printflow_flow_lot_exception_authorize_views.xml',
        # Modal para AUTORIZAR EN BLOQUE varios lotes con un motivo (lo abre la
        # acción sobre la selección de la bandeja).
        'wizard/printflow_flow_lot_exception_authorize_bulk_views.xml',
        # EXCEPCIONES FORMALES GENÉRICAS (F4): modales de autorización (unitario
        # y en bloque) del wizard `printflow.finding.exception.authorize*`.
        'wizard/printflow_finding_exception_authorize_views.xml',
        # Confirmación de RIESGO (F5) de las correcciones de la bandeja de lote
        # que tocan inventario ("Crear lote sugerido" / "Corrección automática").
        'wizard/printflow_lot_risk_confirm_views.xml',
        # Bandeja gestionable de INSUMOS (la abre el "Solucionar" del hito
        # ALMACÉN DE INSUMOS del diagrama de producto).
        'wizard/printflow_flow_supply_tray_views.xml',
        # --- SALUD DE INVENTARIO (superficies parkeadas) ---
        # `printflow_inventory_health_views.xml` define la app raíz
        # `menu_printflow_health_app` ("Salud de Inventario"); los otros dos la
        # usan, por eso van DESPUÉS.
        'views/printflow_inventory_health_views.xml',
        # Bandeja GENÉRICA de fallas guiadas (Fase 1). Va DESPUÉS de
        # `printflow_inventory_health_views.xml` porque su menú cuelga de
        # `menu_printflow_health_app`.
        'wizard/printflow_flow_failure_tray_views.xml',
        'views/printflow_node_pending_views.xml',
        'views/printflow_inventory_catalog_views.xml',
        # Gestión de las excepciones PERSISTENTES de lote compartido (modelo del
        # addon principal). Va DESPUÉS de `printflow_inventory_health_views.xml`,
        # que define `menu_printflow_health_app` (padre del menú).
        'views/printflow_lot_exception_views.xml',
        # Gestión de las excepciones FORMALES de GI (F4). Va DESPUÉS de
        # `printflow_inventory_health_views.xml` (padre del menú).
        'views/printflow_finding_exception_views.xml',
        # --- Configuración de GI (campos pf_node_pending_* / pf_catalog_limit) ---
        'views/res_config_settings_views.xml',
        'data/ir_config_parameter_data.xml',
        # Server action "Ver diagrama de flujo" en la ficha del producto.
        'data/printflow_product_flow_server_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # SCSS del diagrama + timeline OWL (Nivel 1 del producto clickeable
            # y Nivel 2 diagrama de flujo). Odoo 17 SOLO resuelve assets bajo
            # `<módulo>/static/...`.
            'printflow_gestion_inventario/static/src/scss/printflow_diagnostic.scss',
            'printflow_gestion_inventario/static/src/js/printflow_open_timeline.js',
            'printflow_gestion_inventario/static/src/xml/printflow_open_timeline.xml',
            'printflow_gestion_inventario/static/src/js/printflow_order_timeline.js',
            'printflow_gestion_inventario/static/src/xml/printflow_order_timeline.xml',
        ],
    },
    'installable': True,
    'application': True,
}
