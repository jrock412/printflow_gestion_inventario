# PLAN — Excepciones formales genéricas (en GI) + UX de "fila clicable"

> **Autor:** odoo-planificador · **Fecha:** 2026-10-15 (rev. 2)
> **Estado:** DISEÑO (no se ha escrito una sola línea de código)
> **Addon DUEÑO del código:** diagnóstico `printflow_gestion_inventario` (GI).
> **Addon motor:** `x_product_dimensional_pricing` (x) — solo LECTURA por defecto.
> **Rev. 2:** incorpora las decisiones del dueño (D1–D6). Cambia la ubicación del
> código: TODO vive en GI; la detección del motor **no se toca** por defecto.

---

## 0. Ficha de trabajo y ubicación del código (contexto obligatorio)

| Dato | Valor |
|---|---|
| Servidor / BD | MCP `odoo-impreven` / BD **"Ciber Estudios 2015 RESTAURADA"** |
| Addon DUEÑO del código (modelo + registry + wizard + botón + filtrado) | `C:\odoo_custom\printflow_gestion_inventario` (GI) |
| Addon motor (cerebro de reglas / detección) | `C:\odoo_custom\x_product_dimensional_pricing` (x) |
| Dirección de dependencia | GI **depende de** x (GI→x). x funciona sin GI. |
| Versión | Odoo 17 CE |
| Regla de trabajo vigente | **CÓDIGO sí, DATOS no** (skill `regla-trabajo-odoo-17-ce`) |

### Decisión de ubicación (D1 — dueño)

- **TODO el código nuevo de este pedido vive en GI.** El modelo de excepción, el
  registry, el botón/wizard y el **filtrado de las superficies** son de GI.
- **El motor `x` NO se modifica por defecto.** La detección
  (`printflow.stock.health._pf_lot_state` / `_pf_lot_states_map` /
  `_pf_lot_state_from_rows`) se sigue llamando **tal cual**; el "silencio" del
  hallazgo autorizado se logra **excluyendo el hallazgo en las superficies de GI**
  (ver §2.4), no en el motor.
- **Excepción justificada (no norma):** solo si una superficie **del motor `x`**
  pintara el hallazgo autorizado, se evalúa un cambio **mínimo y justificado** en
  `x`. Se documenta como excepción en §9. No se asume de entrada.

**Regla dura de este plan:** autorizar una excepción es SOLO crear/archivar un
registro de excepción (una tabla propia de GI) y, como bitácora secundaria, un
`message_post` (una nota). **Nunca** toca `stock.quant`, `stock.move`,
`stock.move.line`, `stock.lot`, `mrp.production.lot_producing_id` ni ningún
documento de negocio. Es una decisión consciente del usuario que "silencia" un
hallazgo **formal**.

**Mecanismo = válvula de escape (D3):** existe por el incidente real (un código
creó un `stock.quant` sin autorización, el **-229 FONDO NEGRO**). La excepción es
la vía para que un requisito formal (p. ej. "toda MO debe tener lote") **NUNCA**
fuerce a tocar datos de inventario.

---

## 1. Diagnóstico del patrón que ya existe (base a generalizar)

### 1.1 Excepción de LOTE (vive en el motor `x`) — patrón a GENERALIZAR

El patrón de "un lote autorizado" YA existe, pero vive en el motor:

- **Modelo persistente:** `printflow.lot.exception`
  (`x_product_dimensional_pricing/models/printflow_lot_exception.py`).
  Campos: `lot_id`, `product_id` (related store), `company_id`, `reason`,
  `active` (archivar = revocar), `authorized_by_id`, `authorized_date`,
  `source_model/source_id/source_label`. Único `unique(lot_id, company_id)`.
  Revocar/Reactivar pasan por el guardia `printflow.stock.remedy._pf_assert_can_clean()`.
- **Métodos del motor:** `printflow.stock.health._pf_authorize_lot_exception`,
  `_pf_revoke_lot_exception`, `_pf_authorized_lot_ids` (consulta EN LOTE).
- **Cómo excluye la detección:** `_pf_lot_state_from_rows(...)` recibe
  `authorized_lot_ids`; los lotes autorizados NO cuentan como `mixed_lots`, pasan
  a `authorized_lots` (informativo).
- **Superficie de gestión (GI):** `views/printflow_lot_exception_views.xml`
  (lista/form/búsqueda/menú "Excepciones de lote").
- **Autorización desde la bandeja de lote (GI):**
  `wizard/printflow_flow_lot_exception_authorize.py` (unitario) y
  `..._bulk.py` (en bloque); botón de fila "Autorizar excepción"
  (`printflow.flow.lot.tray.action_authorize_lot`) y acción de selección
  (`action_authorize_selected`).

> Punto clave: este patrón **solo cubre LOTES y solo el código `lot_mixed`**. Es
> lo que hay que **generalizar** a "cualquier hallazgo formal sobre cualquier
> documento".

### 1.2 El hueco real (Pedido 1)

En `wizard/printflow_flow_lot_tray.py`:

```
AUTHORIZABLE_KINDS = ('mixed_lot', 'generic_lot', 'no_stock_lot')
```

**Falta `unassigned_mo`** (y cualquier otro formalismo). Por eso una MO `done` sin
lote (`lot_unassigned_finished`) NO se puede autorizar hoy: `can_authorize` exige
`lot_id` y esa fila no tiene lote (justamente el problema). La única salida actual
es `action_create_suggested_lots` / `action_apply_correction` →
`repair_finished_lot` → `mrp.production.printflow_repair_lot` → **re-etiqueta
quants**. Eso produjo el incidente `-229` y está **PROHIBIDO** por la regla de
trabajo.

### 1.3 Detección de "MO terminada sin lote" y otras (motor `x`)

- `_pf_lot_state(product)` / `_pf_lot_states_map(products)` en
  `x/models/printflow_stock_health.py` calculan, entre otras claves:
  `unassigned_mo_ids` (MO `done` sin `lot_producing_id`), `missing_move_ids`,
  `no_stock_lot_ids`, `generic_lot_ids`, `mixed_lots`, `orphan_quant_ids`,
  `negative_reserved_quant_ids`.
- Precedencia en `_pf_lot_state_from_rows(...)`: huérfana > sin lote > sin
  existencia > genérico > mezcla > **terminado sin lote** > ok.
- Esos estados los consumen **superficies de GI**: la bandeja de lote
  (`wizard/printflow_flow_lot_tray.py`), el diagrama de flujo del producto
  (`models/printflow_flow_lots.py::_pf_prepare`), la Salud de inventario
  (`models/printflow_inventory_health.py`), el catálogo
  (`models/printflow_inventory_catalog.py`), la explicación
  (`models/printflow_flow_explain.py`), el diagnóstico
  (`wizard/printflow_order_diagnostic_failure.py`,
  `models/printflow_finding_resolution.py`) y la falla huérfana
  (`models/printflow_flow_failure_lot_orphan.py`).

> **Consecuencia de D1:** como **no** filtramos en el motor, el filtrado debe
> ocurrir en **CADA superficie de GI** que consume el estado. Para no dispersar
> `if tipo == ...` por 10 archivos, se centraliza en **un solo adaptador de GI**
> (§2.4) que TODAS las superficies llaman después de leer del motor.

---
## 2. DISEÑO — Excepciones formales genéricas (TODO en GI)

### 2.1 Idea central

Convertir "un lote autorizado" en un patrón **genérico**: *"para el hallazgo
formal X, sobre el registro Y (modelo + id), existe una excepción autorizada en
GI"*. El modelo de excepción vive en GI; **las superficies de GI restan** los
registros autorizados antes de pintar. Revocar = archivar; la próxima lectura
vuelve a pintar el hallazgo. **Cero inventario tocado.**

Alcance **genérico** (D2): el botón autoriza un hallazgo sobre **cualquier**
`res_model` + `res_id` (`mrp.production`, `stock.move`, `stock.lot`,
`stock.picking`, `sale.order`, etc.), no solo MO sin lote. Aplica a **cualquier
movimiento/documento con una falla que NO genere daño al inventario** (formalismo
puro).

**Queda EXCLUIDO de autorización** (no es formalismo: hay inconsistencia real de
datos): `lot_orphan_reservation` (reserva huérfana) y las reservas/quant
negativos. Esos SÍ exigen remedio real; el botón de autorización no los cubre.

### 2.2 Modelo nuevo: `printflow.finding.exception` (tabla persistente, en GI)

Archivo nuevo (una clase por archivo, clean architecture):
`models/printflow_finding_exception.py`.

| Campo | Tipo | Propósito |
|---|---|---|
| `finding_code` | Char (lista blanca por registry) | Clave del hallazgo (p. ej. `lot_unassigned_finished`). El "qué". |
| `target_model` | Char | Modelo del registro afectado (p. ej. `mrp.production`). |
| `target_id` | Integer | Id del registro afectado. |
| `target_label` | Char | Etiqueta legible (nombre de la MO/picking) para mostrar. |
| `lot_id` | Many2one `stock.lot` (opcional) | Solo para hallazgos basados en lote (puente con el patrón de lotes). |
| `product_id` | Many2one `product.product` (compute store) | Agrupar/filtrar y para la Salud de inventario. |
| `company_id` | Many2one `res.company` | Multi-compañía + regla de registro. |
| `reason` | Text (requerido en la práctica) | Motivo de la autorización (lo captura el wizard). |
| `authorized_by_id` | Many2one `res.users` (readonly) | Quién autoriza (usuario actual al confirmar). |
| `authorized_date` | Datetime (readonly) | Cuándo se autorizó. |
| `active` | Boolean (default True) | **Revocar = archivar** (`active=False`); la historia se conserva. |
| `source_model` / `source_id` / `source_label` | Char / Integer / Char | Desde dónde se autorizó (bandeja, modal, acción masiva). |

**Restricción única:** `unique(finding_code, target_model, target_id, company_id)`
→ una excepción por hallazgo+registro+compañía; re-autorizar REUSA el registro
archivado (no duplica).

**Métodos del modelo** (espejo del patrón de lotes, pero en GI):
`action_pf_revoke` / `action_pf_reactivate` (archivan/desarchivan con el guardia
`_pf_assert_can_clean`), y los de consulta usados por el filtrado (§2.4):
`_pf_suppressed_targets(finding_code, company=None)` → `set[int]` (una consulta).

### 2.3 Registry de hallazgos autorizables (punto de extensión, en GI)

Servicio `AbstractModel` **sin tabla** `printflow.finding.exception.registry`
(espejo de `printflow.flow.failure.registry`), archivo nuevo
`models/printflow_finding_exception_registry.py`, con un mapa
`finding_code -> {target_model, label, surface}`:

| `finding_code` | `target_model` | Significado |
|---|---|---|
| `lot_unassigned_finished` | `mrp.production` | MO terminada sin lote (caso real del pedido). |
| `lot_missing` | `stock.move` | Movimiento de salida sin lote. |
| `lot_generic` | `stock.lot` | Lote genérico en producto gestionado. |
| `lot_no_stock` | `stock.lot` | Lote reservado sin existencia interna. |
| `lot_mixed` | `stock.lot` | Lote compartido entre pedidos (puente al patrón de x). |

- El registry **no restringe** el `res_model`+`res_id` que el wizard puede
  autorizar (D2); sirve para **etiquetar** la fila y para saber **en qué
  superficies** el filtro debe restar el target.
- Expone `_pf_supported()` y `_pf_shape(code)` (modelo destino + etiqueta + rol)
  para que las superficies sepan cómo etiquetar sin `if tipo == ...` dispersos.
- Añadir un formalismo NUEVO = **una fila en este mapa + (si aplica) su resta en
  el adaptador de §2.4**. No se toca la bandeja ni los wizards.

### 2.4 Filtrado en las SUPERFICIES de GI (adaptador central) — D1

Como el motor NO se toca, la exclusión se hace en GI. Para evitar duplicar lógica
en 10 archivos, se crea **UN** adaptador:

- Archivo nuevo: `models/printflow_finding_exception_filter.py`
  (`AbstractModel` sin tabla `printflow.finding.exception.filter`).
- API (contrato):
  - `_pf_apply_to_lot_info(product, lot_info)` → devuelve una **copia** del
    diccionario del motor con las listas ya filtradas y el `state`/remedios
    **recalculados**.
  - `_pf_apply_to_lot_map(products, lot_map)` → la misma operación en lote
    (una sola consulta de supresiones por código).
- **Cómo filtra:** para cada `finding_code` de la lista blanca, resta del
  `lot_info` los targets autorizados:
  - `unassigned_mo_ids` contra los `mrp.production` autorizados
    (`lot_unassigned_finished`);
  - `missing_move_ids` contra los `stock.move` autorizados (`lot_missing`);
  - `no_stock_lot_ids` / `generic_lot_ids` contra los `stock.lot` autorizados;
  - `mixed_lots` (nombres) contra los `stock.lot` autorizados (`lot_mixed`).
- **Recalculo del estado:** tras la resta, se recalcula el `state` reaplicando la
  **misma precedencia** del motor (huérfana > sin lote > sin existencia >
  genérico > mezcla > terminado sin lote > ok) sobre las listas ya filtradas, y
  el remedio con `LOT_REMEDY_BY_STATE` (constante que GI YA importa de x).
  - Con supresiones vacías, el resultado es **idéntico** al del motor (garantía
    de no-regresión, CA-12).
  - El adaptador vive en GI y **solo se apoya en las claves que el motor ya
    devuelve** (`unassigned_mo_ids`, `missing_move_ids`, ...): **no re-lee** la
    base ni reimplementa la detección, solo la **reclasifica**.
- **Superficies que llaman al adaptador** (parche quirúrgico, ninguna toca el motor):
  1. `wizard/printflow_flow_lot_tray.py::_pf_populate` (unitario) — y **omite**
     construir filas cuyo `(res_model, res_id)` esté autorizado.
  2. `models/printflow_flow_lots.py::_pf_prepare` (diagrama, en lote).
  3. `models/printflow_inventory_health.py::_pf_populate` (salud, `lot_state`).
  4. `models/printflow_inventory_catalog.py::_pf_populate` (catálogo, `lot_state`).
  5. `models/printflow_flow_explain.py` (explicación por nodo).
  6. `wizard/printflow_order_diagnostic_failure.py` y
     `models/printflow_finding_resolution.py` (diagnóstico).
  7. `models/printflow_flow_failure_lot_orphan.py` (falla huérfana).
  8. `wizard/printflow_flow_lot_picker.py` / `..._candidate.py` (puente con el
     patrón de lotes: ya consultan `_pf_authorized_lot_ids`).
- **Camino alternativo (si el recálculo en GI resultara frágil):** una **adición
  mínima** en el motor `x` (pasar más conjuntos autorizados a
  `_pf_lot_state_from_rows`). Queda como **excepción justificada** (§9), no como
  norma.

### 2.5 Autorización / Revocación (semántica y permisos) — D4/D5

- **Autorizar** (una sola vía, varias superficies): wizard genérico
  `printflow.finding.exception.authorize` (archivo
  `wizard/printflow_finding_exception_authorize.py`) que captura
  `finding_code` + `target_model` + `target_id` + `reason`, pasa por el guardia
  `_pf_assert_can_clean()` y crea/reusa el registro. Devuelve notificación y cierra.
  - **Botón genérico (D2):** entrada reutilizable
    `printflow.finding.exception._pf_authorize_action(finding_code, target_model,
    target_id, source_*)` que cualquier superficie de GI puede abrir (bandeja de
    lote, bandeja genérica de fallas, etc.).
  - El wizard de lote actual (`printflow.flow.lot.exception.authorize`, de GI) se
    conserva para no romper; opcionalmente delega en el genérico (mismo destino).
- **Autorización en bloque:** `printflow.finding.exception.authorize.bulk`
  (archivo `wizard/printflow_finding_exception_authorize_bulk.py`) sobre la
  selección de una bandeja.
- **Revocar / Reactivar:** botones en el registro (archivan/desarchivan), con el
  mismo guardia.
- **Permisos (D5):** idéntico al patrón de lotes.
  - VER = `base.group_user`.
  - CREAR/REVOCAR = jefe de taller/administrador
    (`mrp.group_mrp_manager` / `base.group_system`, vía `_pf_assert_can_clean`).
  - ACL en `security/ir.model.access.csv` (filas nuevas) + regla de compañía
    `ir.rule` en **archivo nuevo** `security/printflow_finding_exception_security.xml`
    (hoy GI no tiene XML de seguridad), espejo de
    `x/security/printflow_lot_exception_security.xml`.

### 2.6 Bitácora (D4)

- **Primaria (obligatoria y suficiente):** el propio registro de excepción
  conserva `reason` + `authorized_by_id` + `authorized_date` + `source_*`. Es la
  bitácora autoritativa y NO toca datos de negocio.
- **Secundaria (aprobada):** `message_post` (nota) en el documento afectado
  (MO / documento), igual que hoy hace la falla "reserva huérfana". Es un mensaje,
  **no** un cambio de campos de negocio. Best-effort: si el target no admite
  `message_post`, se omite sin error.

### 2.7 Convivencia con `printflow.lot.exception` (de x) — D4

- **No se migra ni se borra** la tabla existente de x (la regla prohíbe tocar
  datos y D1 prohíbe tocar el motor).
- **Coexistencia aditiva:** el nuevo modelo de GI cubre los formalismos nuevos
  (empezando por MO-sin-lote); para `lot_mixed`, el filtrado de GI consulta la
  **UNIÓN** `printflow.lot.exception` (x, solo lectura) ∪
  `printflow.finding.exception` (`finding_code='lot_mixed'`, GI).
- Consolidación futura (opcional, fuera del mínimo): re-apuntar el wizard de lote
  al motor genérico manteniendo la tabla vieja como "espejo". Se decide después.

### 2.8 Radiografía de impacto (qué apaga autorizar una MO sin lote)

Con el adaptador de GI aplicado en las superficies (motor intacto):

| Superficie | Archivo (GI) | Efecto esperado |
|---|---|---|
| Bandeja de lote | `wizard/printflow_flow_lot_tray.py` + `_views.xml` | Las filas `unassigned_mo` autorizadas desaparecen. |
| Diagrama de flujo del producto | `models/printflow_flow_lots.py` | El nodo deja de pintarse como "Terminado sin lote". |
| Salud de inventario | `models/printflow_inventory_health.py` | `lot_state` deja de ser el hallazgo; si era el único, sale de alerta. |
| Catálogo de productos | `models/printflow_inventory_catalog.py` | El semáforo de lote deja de ser `warning`. |
| Explicación / diagnóstico | `models/printflow_flow_explain.py`, `wizard/printflow_order_diagnostic_failure.py` | La falla de lote deja de listarse. |
| Falla huérfana | `models/printflow_flow_failure_lot_orphan.py` | No aplica a MO sin lote (es otra falla). |

---
## 3. DISEÑO — Convención UX de "fila clicable" (Pedido 2)

### 3.1 Principio rector

> **El gesto natural abre; el botón explícito EJECUTA (o navega a OTRA cosa).**
> - **Abrir el documento de la fila = clic en la fila / en su columna-documento.**
> - **Botón explícito = acción con efecto o navegación a un destino DISTINTO** del
>   documento de la fila (remediar, sanear, purgar, trasladar, comprar, ajustar,
>   elegir/autorizar lote, "ver quién me bloquea", "ver diagrama", "ver alertas").

### 3.2 Cómo se implementa "clic en la fila" en Odoo 17

- **Columnas relacionales (Many2one / Reference):** en Odoo 17 sus celdas son
  enlaces nativos que abren el registro relacionado. La bandeja de lote ya tiene
  `document_ref` (`Reference` con `_pf_document_ref_selection` +
  `_compute_document_ref`). **Receta:** exponer esa columna `Reference`/m2o y
  **eliminar el botón "Abrir".**
- **Filas cuyo destino ES el propio registro** (evidencia → quant, pendiente →
  documento): se abren desde la columna identificadora; se elimina el botón "Abrir".
- **NO se fuerzan "row-click" genéricos sobre TransientModel** (clicar la fila
  abre el form de la propia línea transitoria, no el documento destino). El enlace
  vive en una columna relacional/`Reference`, que es el idiom nativo.

### 3.3 Inventario de botones "Abrir / Ir / Gestionar" (GI) y veredicto

| # | Archivo | Vista / widget | Botón (método) | Destino | Veredicto | Razón |
|---|---|---|---|---|---|---|
| 1 | `wizard/printflow_flow_lot_tray_views.xml` | tree (L133) | `action_open` "Abrir documento" | MO / documento de la fila | **REEMPLAZAR** por clic en `document_ref` | Columna ya existe. |
| 2 | idem | form (L172) | `action_open` "Ir al registro real" | idem | **CONSERVAR** (renombrar) | Un form no tiene "fila". |
| 3 | `wizard/printflow_flow_supply_tray_views.xml` | tree (L57) | `action_open` "Ir" | registro del insumo | **REEMPLAZAR** (columna `Reference`/m2o) | Abrir el mismo registro = gesto natural. |
| 4 | idem | form (L87) | `action_open` "Ir al registro real" | idem | **CONSERVAR** | Form. |
| 5 | `views/printflow_node_pending_views.xml` | list (L32) | `action_pf_dispatch` "Abrir" | documento pendiente | **REEMPLAZAR** por clic en la columna-documento | Ejemplo "clic en la MISMA LÍNEA". |
| 6 | idem | form (L47) | `action_pf_dispatch` "Abrir documento" | idem | **CONSERVAR** | Form. |
| 7 | `wizard/printflow_order_diagnostic_evidence_views.xml` | tree (L20) | `action_open` "Abrir" | registro de la evidencia | **REEMPLAZAR** | Igual que #5. |
| 8 | `views/printflow_inventory_health_views.xml` | tree (L78) | `action_open_product` "Producto" | ficha del producto | **REEMPLAZAR** por clic en `product_id` | La fila ES el producto. |
| 9 | `views/printflow_inventory_catalog_views.xml` | tree (L43) | `action_open_flow` "Ver diagrama" | diagrama del producto | **REEMPLAZAR** por clic en `product_id` (drill-down) | Catálogo = índice. |
| 10 | idem | tree (L47) | `action_open_alerts` "Ver alertas" | bandeja de alertas | **CONSERVAR** | Navega a OTRA superficie. |
| 11 | idem | tree (L52) | `action_open_product` "Producto" | ficha del producto | **CONSERVAR** (secundario) | Destino distinto del drill-down. |
| 12 | `wizard/printflow_product_resolution_tray_views.xml` | header (L21) | `action_open_selected` "Abrir seleccionados" | lista de seleccionados | **CONSERVAR** | Acción masiva, no "abrir fila". |
| 13 | idem | tree (L54) | `action_open` "Ir" | causante real | **REEMPLAZAR** | Igual que #5/#7. |
| 14 | `wizard/printflow_product_diagnostic_views.xml` | tree (L135) | `action_open` "Ir" | evidencia | **REEMPLAZAR** | Igual. |
| 15 | `wizard/printflow_product_finding_views.xml` | tree | "Abrir SÍNTOMA / RAÍZ / RAÍZ EN CONJUNTO" | 3 destinos distintos | **CONSERVAR** | No es "abrir la fila". |
| 16 | `views/printflow_order_blocking_reservation_views.xml` | tree (L32) | `action_open_picking` "Abrir entrega" | albarán de la fila | **REEMPLAZAR** | Registro de la fila. |
| 17 | `wizard/printflow_flow_failure_tray_views.xml` | tree evidencia (L30) | `action_open` "Gestionar" | form de detalle + acciones | **CONSERVAR** ("Gestionar") | No abre el documento; abre el detalle. |
| 18 | idem | tree acción (L53/L103) | `action_run` "Abrir" (kind=`navigate`) | lista/registro indicado | **CONSERVAR** | UNA acción guiada entre varias. |
| 19 | `wizard/printflow_bom_archive_diagnostic_views.xml` | tree (L108) | `action_open_sale_order` "Abrir el pedido real" | pedido de la fila | **REEMPLAZAR** | Registro de la fila. |
| 20 | `wizard/printflow_product_flow_views.xml` | form button-box | `action_open_product` "Producto" | ficha del producto | **CONSERVAR** | Botón de caja del form del diagrama. |
| 21 | `wizard/printflow_order_diagnostic_line_levels.py` / `_levels.py` / `_failure.py` | varios | `action_open_product` / `action_open_line_delivery` / etc. | destinos variados | **REVISAR CASO A CASO** | Navegaciones contextuales. |
| 22 | `models/printflow_evidence_resolution.py`, `printflow_finding_resolution.py` | varios | `action_open` | detalle/plan | **REVISAR** | Distinguir "abrir fila" vs "abrir detalle/plan". |

### 3.4 Botones "abrir" del MOTOR `x` (D6 — se PLANIFICAN, no se tocan ahora)

Por decisión D6, la normalización de "clic en fila vs botón Abrir" **también
aplica** a los botones del motor `x` que sean de "abrir" (p. ej.
`printflow_order_board_views.xml`, `mrp_technical_sheet_views.xml`,
`mrp_produce_wizard_views.xml`). **No se toca `x` en esta fase**: se
**inventarían y planifican** aquí para una normalización posterior acordada.

| Archivo (x) | Botón observado | Veredicto tentativo |
|---|---|---|
| `views/printflow_order_board_views.xml` | "Abrir OF/CO/Compra" | **REVISAR** → probable reemplazo por columna-enlace |
| `views/mrp_technical_sheet_views.xml` | "Abrir ..." | **REVISAR** |
| `wizard/mrp_produce_wizard_views.xml` | "Abrir ..." | **REVISAR** |

> Ejecutar esta normalización en `x` = cambio en el MOTOR. Solo se autoriza si el
> dueño lo pide explícitamente (ver §9). Mientras tanto, queda inventariado.

### 3.5 Diagrama de flujo (panel/popover)

- El nodo YA es clicable y abre el panel (`onNodeClick`); se mantiene.
- Las acciones del panel y los ítems de tray que navegan a un causante concreto se
  conservan (no hay "fila" en un panel).
- Sin cambios de JS obligatorios por Pedido 2.

### 3.6 Archivos XML afectados por Pedido 2 (resumen)

- `wizard/printflow_flow_lot_tray_views.xml` (quitar botón L133/L137).
- `wizard/printflow_flow_supply_tray_views.xml` (quitar "Ir" L57; columna-enlace).
- `views/printflow_node_pending_views.xml` (quitar "Abrir" L32).
- `wizard/printflow_order_diagnostic_evidence_views.xml` (quitar "Abrir" L20).
- `views/printflow_inventory_health_views.xml` ("Producto" → clic en `product_id`).
- `views/printflow_inventory_catalog_views.xml` ("Ver diagrama" → clic en `product_id`).
- `wizard/printflow_product_resolution_tray_views.xml` (quitar "Ir" L54).
- `wizard/printflow_product_diagnostic_views.xml` (quitar "Ir" L135).
- `views/printflow_order_blocking_reservation_views.xml` (quitar "Abrir entrega" L32).
- `wizard/printflow_bom_archive_diagnostic_views.xml` (quitar "Abrir el pedido real" L108).

**Python (soporte mínimo):** exponer/verificar campos `Reference`/`m2o` de enlace
en las bandejas sin columna-documento (mismo patrón de `document_ref`).

**JS:** ninguno obligatorio.

---
## 4. Criterios de aceptación verificables

### 4.1 Pedido 1 — Excepción formal genérica (en GI)

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA-1 | Autorizar una MO sin lote crea **1** registro `printflow.finding.exception` activo (`finding_code=lot_unassigned_finished`, `target_model=mrp.production`, `target_id=MO`). | `search_read` tras confirmar. |
| CA-2 | **El registro se creó en GI** (modelo de GI), no en `x`. | `ir.model` / módulo dueño del modelo. |
| CA-3 | **La MO no se altera:** `mrp.production.lot_producing_id` sigue `False`. | `read` antes/después. |
| CA-4 | **Ninguna acción de autorización modifica `stock.quant`/`stock.move`/`stock.lot`.** | Snapshot de conteos+sumas ANTES y DESPUÉS → idénticos (test). |
| CA-5 | Tras autorizar, la **superficie de GI** deja de reportar el hallazgo: la bandeja de lote no lista la fila; el `lot_state` del catálogo/salud/diagrama deja de ser el hallazgo (si era el único). | Poblar bandeja / snapshot de salud / catálogo. |
| CA-6 | **Revocar** (archivar) hace reaparecer el hallazgo. | `action_pf_revoke` + re-lectura. |
| CA-7 | Idempotencia: autorizar dos veces el mismo target REUSA el registro (no duplica) por la restricción única. | Crear 2 veces y contar. |
| CA-8 | Permisos: un `base.group_user` sin rol de jefe de taller/admin NO puede autorizar (UserError del guardia). | Test de acceso. |
| CA-9 | Bitácora: el registro trae `authorized_by_id`, `authorized_date`, `reason`, `source_*`, **y** se dejó una nota (`message_post`) en el documento. | Lectura del registro + `message_ids`. |
| CA-10 | **Genericidad (D2):** se puede autorizar un hallazgo sobre otro `res_model`+`res_id` (p. ej. `stock.move`) sin crear código nuevo por tipo; solo el registry + su resta. | Test con dos modelos distintos. |
| CA-11 | Extensibilidad: agregar un `finding_code` nuevo NO obliga a tocar la bandeja ni los wizards (registry + resta del adaptador). | Revisión + test `_pf_supported()`. |
| CA-12 | No-regresión (clave por D1): con supresiones vacías, **cada superficie de GI** devuelve EXACTAMENTE lo que devolvía antes (el adaptador no altera el `lot_info`/`lot_state`). | Test de paridad superficie por superficie. |
| CA-13 | El filtrado NO cambia el motor: `x` no tiene archivos nuevos por este pedido. | `git status` de `x` limpio. |

### 4.2 Pedido 2 — UX de fila clicable

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA-14 | En la bandeja de lote, clic en la columna Documento abre la MO/albarán; NO existe "Abrir documento". | Inspección + prueba manual. |
| CA-15 | En Pendientes, clic en la fila/columna-documento abre el documento; NO existe "Abrir". | Idem. |
| CA-16 | Los botones que QUEDAN son sólo acciones (ejecutar/navegar a otro destino). | Inventario §3.3 como checklist. |
| CA-17 | Formularios (sin fila) conservan sus botones de navegación. | Inspección. |
| CA-18 | Los botones "abrir" del motor `x` quedan **inventariados/planificados** (§3.4) sin haberse modificado. | Revisión de `git status` de `x`. |

---

## 5. Fases / orden de implementación (TODO en GI)

| Fase | Contenido | Addon | Depende de |
|---|---|---|---|
| **F0** | Confirmar versión/estructura y ubicación (hecho: D1). Nombre del modelo (`printflow.finding.exception`). | — | — |
| **F1** | GI: modelo `printflow.finding.exception` + registry `printflow.finding.exception.registry` + seguridad (ACL + `ir.rule` por compañía). | GI | F0 |
| **F2** | GI: adaptador `printflow.finding.exception.filter` (`_pf_apply_to_lot_info` / `_pf_apply_to_lot_map`) + **prueba de paridad** (supresiones vacías = salida histórica). | GI | F1 |
| **F3** | GI: aplicar el adaptador en las superficies (§2.4 lista 1–8) para `lot_unassigned_finished`. | GI | F2 |
| **F4** | GI: wizard genérico `printflow.finding.exception.authorize` (+ botón/entrada genérica) y `...authorize.bulk`; gestión/revocación (lista/form/menú) + `message_post`. | GI | F2 |
| **F5** | GI: bandeja de lote — botón "Autorizar excepción" como vía **PRIMARIA** para MO-sin-lote; degradar "Crear lote sugerido"/"Corrección automática" a **SECUNDARIA con aviso** (D5/Q4). | GI | F4 |
| **F6** | GI: extender registry a los demás formalismos (`lot_missing`, `lot_generic`, `lot_no_stock`) y puentear `lot_mixed` con la tabla de x (unión, solo lectura). | GI | F2 |
| **F7** | GI: UX Pedido 2 — quitar botones "Abrir/Ir" y exponer columnas-enlace (§3.3/§3.6). | GI | F4 |
| **F8** | Tests de aceptación (CA-1..CA-18) y verificación de la regla "inventario intacto". | GI | F1–F7 |

**Orden:** F1→F2 (modelo + adaptador) **antes** de F3 (superficies) y F4 (botones):
primero debe existir el mecanismo de supresión y su paridad, y **después** la
superficie que autoriza; así nunca hay un estado intermedio donde la UI autorice y
el diagrama siga pintando el hallazgo. **El motor `x` no aparece en ninguna fase.**

---

## 6. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Recalcular el `state` en GI duplica la precedencia del motor (drift si x cambia) | Medio | Precedencia en UNA constante de GI + **test de paridad** (CA-12) contra la salida del motor con supresiones vacías. |
| Dispersar el filtrado en las superficies | Medio | **Un solo adaptador** (§2.4); las superficies solo lo llaman. |
| Confundir "autorizar" con "reparar el lote" | Crítico (inventario) | La autorización NO llama a `printflow_repair_lot` ni a nada que escriba quants; test CA-4. |
| `message_post` visto como "tocar datos" | Bajo | Es una nota, no campos de negocio; bitácora primaria en el registro de excepción. |
| Duplicar la excepción de lotes (x vs GI) | Medio | Coexistencia aditiva documentada (§2.7); `lot_mixed` se unifica por UNIÓN de solo lectura. |
| Quitar un botón que sí era una ACCIÓN | Medio | Inventario con veredicto (§3.3); los dudosos van a "REVISAR". |
| Autores del "-229" vuelven por la vía automática | Crítico | "Crear lote sugerido"/"Corrección automática" pasan a **SECUNDARIAS con aviso** (F5). |
| Que alguna superficie del motor `x` muestre el hallazgo autorizado | Medio | Revisión en F3; si ocurre, **excepción justificada mínima en x** (§9), no norma. |

---
## 7. Decisiones resueltas (antes eran preguntas abiertas Q1–Q6)

- **Q1 (ubicación) → RESUELTA (D1):** TODO el código (modelo, registry, botón,
  wizard, filtrado) vive en **GI**. El motor `x` **no se toca** por defecto; la
  exclusión se hace **filtrando en las superficies de GI**.
- **Q2 (modelo) → RESUELTA (D4):** modelo **NUEVO aditivo**
  `printflow.finding.exception` (en GI). **No** se toca ni renombra el
  `printflow.lot.exception` de `x`.
- **Q3 (bitácora) → RESUELTA (D4):** sí, `message_post` como bitácora
  **secundaria** (no toca inventario); la primaria es el registro.
- **Q4 (botones MO-sin-lote) → RESUELTA (D5):** "Crear lote sugerido" y
  "Corrección automática" se **conservan como SECUNDARIAS con aviso**; la vía
  PRIMARIA es "Autorizar excepción".
- **Q5 (permiso) → RESUELTA (D4):** mismo guardia que hoy (jefe de taller / admin).
- **Q6 (botones "abrir" de `x`) → RESUELTA (D6):** la normalización de UX
  **también aplica** a los botones "abrir" del motor, pero **no se toca `x` ahora**:
  se **inventarían y planifican** (§3.4).

---

## 8. Observaciones (fuera del alcance pedido)

- El botón `action_create_suggested_lots` / `action_apply_correction` (que
  disparan `repair_finished_lot` → `printflow_repair_lot` → re-etiqueta de quants)
  es la causa histórica del `-229`. **No** se elimina aquí; queda como SECUNDARIA
  con aviso.
- GI hoy **no tiene** archivo de seguridad XML; este pedido agrega el primero
  (`security/printflow_finding_exception_security.xml`) y debe declararse en el
  `__manifest__.py` (después del CSV).
- Nuevos archivos de GI a registrar en `models/__init__.py` y/o `wizard/__init__.py`
  y en la lista `data` del manifest (clean architecture).
- Posible bump de versión del manifest de GI (`17.0.1.2.5` → `17.0.1.3.0`).

---

## 9. Qué requeriría tocar `x` (excepción justificada, NO norma)

Por D1, `x` no se modifica. Solo se evaluaría un cambio **mínimo y justificado**
en `x` si se diera **alguno** de estos casos:

1. **Una superficie del motor `x` pinta el hallazgo autorizado.** Ej.: el tablero
   de pedidos (`x/models/printflow_order_board.py`,
   `x/views/printflow_order_board_views.xml`) o el tablero de salud del motor
   (`x/models/printflow_board_health.py`). Si el conteo de lote/`unassigned_mo`
   se mostrara allí, el "silencio" exigiría una **adición mínima** en x
   (p. ej. pasar más conjuntos autorizados a `_pf_lot_state_from_rows`).
2. **El recálculo en GI se vuelve frágil** (drift de precedencia). La alternativa
   limpia sería extender `_pf_lot_state_from_rows` en x para aceptar exclusiones
   genéricas; se documenta como plan B.
3. **Aprobación explícita del dueño** para la normalización UX (§3.4) de los
   botones "abrir" del motor.

En cualquier caso: cambio **aditivo**, **justificado** y **con prueba de paridad**
(supresiones vacías ⇒ salida histórica). Se documenta caso por caso; **no** se
asume de entrada.

---

> **Este documento es un DISEÑO.** No contiene código de implementación. Queda
> listo para ser ejecutado por el agente `odoo-dev`, fase por fase, empezando por
> F0/F1 — **todo dentro de `printflow_gestion_inventario` (GI)**, sin tocar el
> motor `x` por defecto.