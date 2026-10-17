# -*- coding: utf-8 -*-
"""Tests del addon `printflow_gestion_inventario` (diagnostico + Salud de Inventario).

Movidos desde `x_product_dimensional_pricing/tests/`. Los tests que prueban el
cerebro de reglas (health engine / stock.health / stock.remedy) permanecen en el
addon principal.
"""

from . import test_cleanup_permissions
from . import test_cleanup_permissions_generic
from . import test_cleanup_surface_when_board_ok
from . import test_diagnostic_auto_focus_single_product
from . import test_diagnostic_backlog_routing
from . import test_diagnostic_backlog_threshold
from . import test_diagnostic_bom_archive
from . import test_diagnostic_bom_estimate
from . import test_diagnostic_buy_components_identifies
from . import test_diagnostic_chain_no_duplicate_solution
from . import test_diagnostic_collect_grouped_po_labels
from . import test_diagnostic_consumable_not_stock
from . import test_diagnostic_contention_offers_supply
from . import test_diagnostic_delivered_lines
from . import test_diagnostic_delivery_node
from . import test_diagnostic_delivery_node_consolidation
from . import test_diagnostic_delivery_orders
from . import test_diagnostic_demand_uom
from . import test_diagnostic_display_delivered_lines
from . import test_diagnostic_failure_chain
from . import test_diagnostic_flow_engine_parity
from . import test_diagnostic_flow_geometry
from . import test_diagnostic_flow_rollup
from . import test_diagnostic_grouped_claim_own_portion
from . import test_diagnostic_grouped_po_own_portion
from . import test_diagnostic_incoming_map
from . import test_diagnostic_kit_components
from . import test_diagnostic_levels
from . import test_diagnostic_manufacturable
from . import test_diagnostic_manufacture_no_mo
from . import test_diagnostic_mo_draft_to_launch
from . import test_diagnostic_mo_stuck_prioritize
from . import test_diagnostic_node_actions
from . import test_diagnostic_node_anomaly_action
from . import test_diagnostic_node_navigation
from . import test_diagnostic_node_summary
from . import test_diagnostic_order_collect_tray
from . import test_diagnostic_order_nav_targets
from . import test_diagnostic_order_vs_global_reservation
from . import test_diagnostic_own_supply_by_sale_line
from . import test_diagnostic_own_supply_prorated
from . import test_diagnostic_pending_delivery_orders
from . import test_diagnostic_personalized_not_stolen_when_own_reserved
from . import test_diagnostic_personalized_purchase
from . import test_diagnostic_product_flow_check
from . import test_diagnostic_product_scanner
from . import test_diagnostic_recalculate
from . import test_diagnostic_recalculate_health_refresh
from . import test_diagnostic_remedy_blocking
from . import test_diagnostic_resolution_plan
from . import test_diagnostic_resolution_tray
from . import test_diagnostic_root_node_alignment
from . import test_diagnostic_routes
from . import test_diagnostic_selector_multiple_products
from . import test_diagnostic_selector_view
from . import test_diagnostic_single_product_no_back_button
from . import test_diagnostic_stock_consistency
from . import test_diagnostic_stock_failure_physical_cause
from . import test_diagnostic_supply_root
from . import test_diagnostic_supply_status_decoupled
from . import test_diagnostic_timeline_payload
from . import test_diagnostic_unified_solution
from . import test_diagnostic_ux_links_log
from . import test_diagnostic_wizard_board_consistency
from . import test_diagnostic_wizard_motor_parity
from . import test_flow_canvas_parity
from . import test_flow_canvas_lot_parity
# Magnitud del déficit en el nodo COMPRAS + resolución que guía a comprarlo
# (badge aditivo `shortfall_*`; CA-1..CA-5).
from . import test_flow_compras_deficit_magnitude
# Fotografía real de Compras/Recepción: OC sin confirmar + albaranes reales
# (+ insumos de la BOM) + badges explícitos por nodo (CA-1..CA-6).
from . import test_flow_compras_recepcion_snapshot
# Faltante REAL y "pedidos por comprar": descuenta las OC sin confirmar, congela
# la cantidad de la Compra Rápida e importa los pedidos que requieren compra
# (CA-1..CA-6).
from . import test_flow_compras_por_comprar
# Lote de la Compra Rápida: se persiste en la OC (`pf_lot_name`) y viaja
# PRE-RELLENADO al albarán de entrada (sin validarlo); la compra rápida normal
# y la recepción automática quedan intactas (CA-1..CA-4).
from . import test_quick_purchase_lot_tracking
# Candado de fichas terminales al recibir/entregar: la whitelist del candado se
# amplía de forma ADITIVA con el campo computado `is_partial_fabrication`, de
# modo que el recálculo del motor no bloquea la validación del albarán (CA-1..CA-4).
from . import test_technical_sheet_terminal_lock
# Fase 1 del patrón de fallas guiadas: registry + falla huérfana + bandeja
# genérica + guardia por riesgo.
from . import test_product_flow_failure_registry
from . import test_product_flow_failure_orphan_reconcile
from . import test_product_flow_failure_negative_reserved
from . import test_product_flow_failure_tray_generic
from . import test_product_flow_failure_permissions_split
# Reserva colgada REAL vs existencia negativa + bandeja guiada de saneo.
from . import test_product_flow_failure_over_reservation
# Lote reservado SIN existencia (`lot_no_stock`) en la bandeja GUIADA: el
# "Solucionar" con el producto explícito abre `printflow.flow.failure.tray`
# (una fila por lote + saneo `reassign`); la clásica sigue como fallback
# (CA-1..CA-4).
from . import test_product_flow_failure_lot_no_stock
from . import test_flow_explain
from . import test_flow_explain_delivery
from . import test_health_center_retired
from . import test_inventory_catalog_drilldown
from . import test_inventory_catalog_surface
# Rendimiento: el poblado del catálogo no crece con N (sin N+1).
from . import test_inventory_catalog_query_budget
# F7: el drill-down del catálogo se cablea por clic en `product_id` (widget).
from . import test_catalog_list_drilldown_widget
from . import test_catalog_reuses_manufacturable
from . import test_inventory_health_surface
from . import test_lot_management
from . import test_node_pending_enumeration
from . import test_pending_list_surface
from . import test_pending_native_validate
from . import test_phase7_board_permissions
from . import test_phase7_settings_config
from . import test_product_flow_actions
from . import test_product_flow_canvas
from . import test_product_flow_canvas_controls
# P1/CA-1: la entrega "sin lote" y la reserva colgada del inventario son UNA
# sola falla (cadena invertida raíz=Entrega → consecuencia=Inventario).
from . import test_product_flow_lot_coupled_chain
from . import test_product_flow_lot_actions
from . import test_product_flow_lot_picker
from . import test_product_flow_lot_picker_candidates
from . import test_product_flow_lot_picker_component
from . import test_product_flow_lot_picker_exception
from . import test_product_flow_lot_picker_exception_authorized
from . import test_product_flow_lot_picker_negative_reserved
from . import test_product_flow_lot_reassign_per_document
from . import test_product_flow_lot_remedy_permissions
from . import test_product_flow_lot_semaphore
from . import test_product_flow_lot_tray
from . import test_product_flow_lot_tray_authorize
from . import test_product_flow_lot_tray_authorize_bulk
# Bloque V: UX del selector + corrección de lote equivocado + UX de bandeja.
from . import test_product_flow_lot_picker_ux
from . import test_product_flow_lot_correction
from . import test_product_flow_lot_tray_ux
# CRÍTICO: asignar/corregir el lote de un terminado NO mueve existencia
# (niega si el cajón sin lote no alcanza; el movimiento físico nunca queda negativo).
from . import test_lot_assignment_no_stock_delta
# Bandeja de lote: columna "Documento" agnóstica + existencias condicionales.
from . import test_product_flow_lot_tray_document
# P2/P3: el "Solucionar" de Entrega (``lot_missing``) SUMA una fila por ORDEN
# pendiente sin lote (la SANA no aparece; modo ``assign``) y el botón "Ver
# existencias por lote" es honesto con su destino ``quants`` (CA-2/CA-3).
from . import test_product_flow_lot_tray_orders
# Bloque: ASIGNACIÓN DE LOTE EN BLOQUE desde la bandeja (H-021/H-026). El wizard
# asigna UN lote (con un motivo) a la SELECCIÓN de entregas sin lote, con
# parcial/omitidas/permisos/dedupe (CA-2..CA-9) y la vía POR FILA de una orden
# pendiente deja de lanzar UserError (CA-1).
from . import test_product_flow_lot_assign_bulk
from . import test_product_flow_lot_pending_order_assign
# P4/CA-4: "Liberar y re-reservar" (reserva colgada) sanea ACOTADO: NO des-asigna
# una entrega SANA de la misma ubicación (solo suelta las líneas sin lote o con
# lote sin existencia, y re-reserva por las reglas NATIVAS de Odoo).
from . import test_product_flow_over_reservation_scoped
from . import test_product_flow_panel
from . import test_product_flow_parity_panel
from . import test_product_flow_payload_parity
# CA-1/CA-2: la estrategia del producto lee la OF real y arma la cadena de fallas.
from . import test_product_flow_production_signals
# Botón "Recalcular" en el diagrama del PRODUCTO (paridad de UX): recarga el
# MISMO wizard y refresca los compute con los datos actuales (CA-1..CA-4).
from . import test_product_flow_recalculate
from . import test_product_flow_solution_single
from . import test_product_flow_supply_tray
from . import test_stock_remedy
# Excepciones FORMALES genéricas (F1–F5): modelo + registry + adaptador de
# filtrado + wizard + inventario intacto (CA-1..CA-12).
from . import test_finding_exception_formal
