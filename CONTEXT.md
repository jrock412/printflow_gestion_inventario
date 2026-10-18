# CONTEXT.md - Módulo: printflow_gestion_inventario

## 1. Ficha Actual y Estado de Ejecución
- Entorno: Odoo v17 Community
- Servidor Odoo: odoo-impreven / http://localhost:8071
- Base de Datos: Ciber Estudios 2015 RESTAURADA
- Tipo de BD: **PRUEBA** (copia restaurada) — lo confirmó el usuario: **SÍ (2026-10-17)**
  → en lotes `[pantalla]` el verificador puede **abrir** la pantalla (acción de lectura), pero **nunca
  acciona** botones con efecto (Confirmar/Guardar/Validar/Publicar). Receta: `VIEW-LIVE-CHECK.md`
  (skill `odoo-view-design`). *Si este campo se borra o queda sin confirmar, se lee como PRODUCCIÓN.*
- Ruta del Módulo: C:\odoo_custom\printflow_gestion_inventario
- Registro de Hallazgos: [`HALLAZGOS.md`](HALLAZGOS.md) — **13 abiertos** (compañero del CONTEXT.md; ver skill §2.2).
  **17/10-d:** se ABREN **H-039** (el modo `single` es un subconjunto **estricto** del `split` ⇒ duplicidad +
  premisa equivocada: "UN lote para TODA la selección") y **H-040** (el eje de decisión está centrado en el
  **LOTE**, no en la **ORDEN/UNIDAD**; la fila `pending_order` **suma** la demanda). **H-034 pasa a `en tarea`**
  (lo cierra la tarea §3.O). Los tres entran al plan de **§3.O**.
  **Cierre 17/10 · reparto multi-lote (verificado `cumple`): H-036 y H-037 pasan a `resuelto`** → **11 abiertos**.
  **17/10-c (Lote 1 · aviso fuera de alcance):** se ABRE **H-038** (el repo del **MOTOR**
  `x_product_dimensional_pricing` tiene **143 entradas sin commitear** en `main`; riesgo de proceso, NO del módulo
  — se reporta al dueño, no se toca desde aquí).
  **17/10-c (3.ª ronda · TAREA ABIERTA):** se ABRE **H-037** (el wizard en bloque **no tiene capacidad de
  REPARTO multi-lote**: su contrato declarado es "UN lote → N entregas" y el protocolo NATIVO del motor no es
  aditivo ⇒ llamar dos veces borra el primer lote). El dueño pide revisar el wizard; **tarea GRANDE abierta en
  la Sección 3** (Analista → Planificador).
  **17/10-c (2.ª ronda):** se ABRE **H-036** (el check "Asignar" de la tabla de candidatos parece multiselección
  pero es de **selección ÚNICA**: gana el último tick ⇒ se asigna **un solo lote por corrida**; evidencia: bulk id 4).
  **17/10-c:** se ABREN **H-034** (el bloque resuelve UN solo movimiento por albarán) y **H-035** (reservas
  colgadas sin lote actuales), del análisis de la 3.ª incidencia de lote (ver NOTA de abajo).
  **Cierre 17/10-bis: H-032 y H-033 pasan a `resuelto`** (T1–T3 en 1 lote; `odoo-verificador` = `cumple`).
  **Cierre 17/10: H-029, H-030 y H-031 pasan a `resuelto`** (T1–T9 en 3 lotes; `odoo-verificador` = `cumple`).
  Del cierre anterior: **H-021** y **H-026** `resuelto`; **H-027** `descartado` (intencional);
  **H-028** `abierto` (baja, deuda de nomenclatura — no se toca).
- **NOTA DE INCIDENCIA (ABIERTA — 17/10/2026-c · turno Analista):** el dueño reporta **por 3.ª vez** *"asigno un
  lote y al validar me pide el número de lote"* en **IMPRESION BANNER** (producto 13571), y sospecha que hay que
  **reservar primero** y asignar el lote después. Diagnóstico con evidencia (fuente `odoo-impreven` / BD
  `Ciber Estudios 2015 RESTAURADA`):
  1. **La hipótesis del dueño NO es la causa.** En este módulo "Asignar lote" **NO es solo lote: ES la reserva**
     (`_pf_reassign_move_lot` → `_pf_reassign_lot` → `_update_reserved_quantity(lot)`). No hay un "paso antes":
     el lote elegido es el que se reserva. Evidencia: **WH/OUT/02994** quedó `assigned` con el lote `SN126353`
     (move.line 94879) y **se validó** (`done`, 15:06:44).
  2. **Causa real de los 3 intentos: los lotes elegidos estaban (casi) VACÍOS.** `bulk` id 1 (04:52) con lote
     `8763` (**3 u**, consumidas por el 1.er destino FIFO) y `bulk` id 4 (13:25) con lote `SN126353` (**1 u**):
     **1 asignada / 25-26 con error** *"El lote X no tiene existencia disponible…"*; los `bulk` id 2 y 3
     (05:34/06:41) se abrieron **sin lote** ⇒ 26 filas en `pending`, **nada escrito**. En la tabla de candidatos
     SÍ se veía que el recomendado era `666634` (**23 u disponibles**).
  3. **Las 23 entregas sin reserva y las 2 con reserva SIN lote son causa DATO** (**H-018**): el producto es de
     **entrega exclusiva por lote** y el lote exclusivo de cada pedido (`S…-L…`) está **vacío**; la mercancía
     entró en lotes **genéricos** (`666634` = 23 u + 6 lotes de 1 u = **29 u** para ~**34 u** de demanda).
  4. **Quien pide el lote al validar es el chequeo NATIVO de Odoo** (`tracking='lot'`), no el módulo: la línea
     no lleva lote porque **no se escribió nada** (o se tecleó la cantidad a mano).
  5. **HALLAZGO NUEVO (H-034, código):** el bloque resuelve **UN solo `stock.move` por albarán** (`limit=1`) ⇒
     las entregas con **2 movimientos del mismo producto** (**WH/OUT/05608** y **WH/OUT/06483**) quedan a medias
     y al validar siguen pidiendo el lote; el 2.º movimiento **no aparece en ninguna superficie** de la bandeja.
     **Requiere tarea de código PROPIA** (queda FUERA de esta tarea: §3.4 · D-B / §3.10 · O-1; espera la decisión del dueño).
  6. **HALLAZGO NUEVO (H-036, UX/contrato — 2.ª ronda):** el check **"Asignar"** de la tabla de candidatos es de
     **selección ÚNICA** (gana el **último** tick; el wizard asigna **UN** lote por corrida, **no** reparte la
     demanda entre varios). Evidencia: en la corrida **bulk id 4** (13:25) la única fila marcada fue `SN126353`
     (**1 u**), aunque el recomendado de 23 u (`666634`) seguía visible con `is_recommended=True` ⇒ `bulk.lot_id`
     = `SN126353` ⇒ **1 asignada / 25 con error**. La lectura del dueño ("marqué el 23 + los de 1 u") es correcta
     como gesto, pero el diseño asigna un lote por corrida. **RESUELTO por el Planificador:** el modo `single` declara en pantalla que asigna UN lote por corrida (D6) y el camino de reparto es el botón "Repartir lotes" (D1/§3.11).
   **Hallazgo nuevo de DATOS:** **H-035** (reservas colgadas sin lote en WH/OUT/03009 y WH/OUT/03120; quant
   **15219** con disponible **−2**). **Acción de DATOS del dueño:** asignar desde la bandeja con un lote **CON
   existencia** (`666634` = 23 u) y luego con los lotes de 1 u; **no** teclear cantidades a mano.
  7. **HALLAZGO NUEVO (H-037, diseño/capacidad — 3.ª ronda):** el dueño pide revisar el wizard porque "ese
     wizard en específico es para poder asignar VARIOS lotes". **Confirmado y matizado:** la selección única
     **NO** viene de "reutilizar la lógica del selector por documento" — es el **contrato declarado** del
     contenedor (`lot_id` único; docstring *"UN lote a N entregas"*). Lo que falta es una **capacidad NUEVA**
     (reparto multi-lote). Agravante: la primitiva NATIVA `stock.move._pf_reassign_lot` **libera la reserva
     entera y luego reserva** ⇒ **no es aditiva** (dos llamadas con dos lotes borran el primero). **Se abre tarea
     de código GRANDE** — ver **Sección 3** (Analista → Planificador; **plan CERRADO**, §3.4–§3.11); el Analista **recomienda** conservar el
     contenedor y añadirle un camino de reparto (opción **B**), con **H-034** fuera de esta tarea. **PLAN CERRADO en §3.4–§3.11:** D-A = Opción B · D-B = H-034 FUERA · D-C = camino NATIVO ADITIVO.
- **NOTA DE INCIDENCIA (RESUELTA — 17/10/2026 · turno Analista):** el dueño reporta *"asigné el lote y al validar
  me pide el número de lote"* en **WH/OUT/02994** (picking 23057, S03281). Diagnóstico con evidencia
  (fuente `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA`):
  1. La asignación en bloque **SÍ corrió** (`printflow.flow.lot.assign.bulk` id 1, 27 destinos, demanda
     33) pero con el lote **`8763` (solo 3 u)**: **1 asignada** (WH/OUT/02988) y **26 con error**
     "sin existencia disponible" — **02994 quedó en error** (ver **H-029**).
  2. Después, en el formulario del albarán se escribió la **cantidad a mano** (04:55:14): eso creó la
     `stock.move.line` **94877** (`quantity=1`, **`lot_id=false`**) ⇒ el bloqueo al validar es el
     chequeo **NATIVO** de Odoo (`stock/models/stock_move_line.py` L637), no del módulo.
  3. El botón "validar entregas en lote" del motor omitió **28/28** ("Sin stock reservado") — **H-030**.
  **Acción de datos (la ejecuta el dueño, no el agente):** en la bandeja "Asignar lote" elegir un lote
  **con existencia** (`666634` = 23 u; quedan 30 u en total para 30 u de demanda) y volver a validar.
  **Acción de código RESUELTA (17/10 · ciclo T1–T9):** mostrar el motivo por destino (**H-029**), no
  des-reservar la excepción al validar en lote (**H-030**) y los rótulos "Entregas/Unidades" (**H-031**).
  Los TRES pasan a `resuelto` en `HALLAZGOS.md` (verificado por el `odoo-verificador`: `cumple`).
- **⚠️ TAREA ABIERTA (17/10-d · GRANDE · turno 1/5):** **asignación de lote POR ORDEN (eje en las órdenes)**.
  El operador decide **qué caja (`stock.lot`) va a qué movimiento/unidad** de la entrega, en una sola pasada.
  Ataca **H-039** (el modo `single` es subconjunto estricto del `split` ⇒ duplicidad + premisa equivocada) y
  **H-040** (eje centrado en el LOTE, no en la ORDEN/UNIDAD), y **CIERRA H-034** (una entrega con 2 unidades = 2
  filas). **Decidido por el dueño (D1/D2):** grano = **MOVIMIENTO** · se **retiran los DOS modos** y queda **UNA**
  acción **"Asignar lote"**. Ver **§3.O** (contrato §3.3 completo + CA-1…CA-11 + qué se retira).
- Tarea Activa: **§3.O — plan COMPLETO** escrito y **revisado** en **§3.7 (9 tareas · 4 lotes)**.
  **Lote 1 (T1–T3) `[motor]` ✅ CERRADO** (dev: T1–T3 `[x]`; 41/41 candados de bandeja/pending/**picker** verdes).
  **Lote 2 (T4–T5) `[pantalla]` ✅ CERRADO** (vistas: 1 solo form por unidad, form del reparto borrado, botón
  re-rotulado; **sin verificación en vivo todavía** — la hace el Verificador al final).
  **Lote 3 (T6–T8) `[motor]` ✅ CERRADO** (residuo **0** de los símbolos retirados; el test del `split`
  **borrado**; `test_product_flow_lot_assign_bulk.py` adaptado; test NUEVO por unidad **8/8** con **regresión
  real** probada: revertir T3 ⇒ `test_ca2` falla con 1 fila; revertir T2 ⇒ `test_ca5` falla). Lote en curso:
  **Lote 4 (T9) `[motor]` ✅ CERRADO** (detalle `..._assign_bulk_result.py` al grano **por unidad** **4/4**;
  `..._pending_order_assign.py` **sin cambios** —usa el selector por documento—; candados de bandeja/picker
  **delta = NINGUNO**; pasada de **110** tests ⇒ **1 rojo pre-existente B1/H-002**, ajeno). Lote en curso:
  **Lote 5 (T10) `[pantalla]` ✅ CERRADO** (restituido `confirm_exception` en el form del contenedor: **+1 campo**,
  cirugía mínima; XML OK; **1** sola ocurrencia). **CICLO DE LOTES COMPLETO (1–5)** ⇒ turno al **Verificador**
  (una sola pasada, al final).
  Añadida **T10 `[pantalla]` (Lote 5)** por **regresión de T4** (se perdió el campo `confirm_exception`, que
  `action_assign_lot_bulk` exige con política ≠ `warn` ⇒ callejón sin salida; ver §3.7).
  Orden del ciclo: **ADD (Lote 1) → REPINTAR (Lote 2) → BORRAR (Lote 3) → adaptar (Lote 4) → T10 (Lote 5)**.
- ✅ **INCIDENCIA DE PROCESO RESUELTA (17/10-d · corte de red):** la **1.ª sesión del Lote 3** se cortó por red y
  dejó trabajo parcial en disco; se aseguró en un commit `wip`, se anotó aquí su estado exacto y el lote se
  **relanzó en sesión NUEVA**, que lo **completó y verificó** (T6–T8 `[x]`). **Sin pendientes de esa incidencia.**
- **Ratificación del Analista — DEV-1 (desviación declarada del Lote 3):** el dominio del selector **por fila**
  pasó de `bulk_id.` a **`parent.`** (`wizard/printflow_flow_lot_assign_bulk_line.py`) porque con `bulk_id.` el
  módulo **no cargaba** (`Field 'bulk_id' … must be present in view`); `parent.` es el patrón **NATIVO** del core
  para un campo de una línea y la **semántica no cambia** (mismo producto + lotes con existencia = **D4**).
  **RATIFICADO.** *(El `odoo-vistas` solo lo mira si vuelve a tocar ese archivo.)*
- ⚠️ **OBSERVACIÓN PARA EL CIERRE (le importa al Verificador):** en la **BD de PRUEBA** el módulo **no está
  actualizado** (el último `-u` no completó ⇒ el esquema del contenedor arrastra el viejo). El Lote 3 verificó en
  un **clon temporal** (`pf_lote3_verif`, creado con `pg_dump`/`pg_restore` y **eliminado** al terminar): `-u`
  **OK** y **19/19** del lote **verdes**. ⇒ **Antes del informe de mirada hay que actualizar el módulo en 8071**.
  El único rojo de esa pasada es **B1 pre-existente** (`test_product_flow_lot_picker_ux.py:143`, ya en **H-002**),
  **ajeno** a §3.O.
- **Autorización: SÍ (2026-10-17)** — el dueño: *"aplica las acciones recomendadas"* ⇒ compuerta §4.0 superada.
- Responsable Activo (Turno): **Odoo Verificador** (paso 5 · **una sola pasada al final**). **Lotes 1–5
  cerrados.** **Bloqueo declarado para la verificación EN VIVO:** el módulo **no está actualizado en la BD de
  PRUEBA** (ver la observación de cierre más arriba) ⇒ el *informe de mirada* necesita el **`-u`** previo. El
  **motor `x_product_dimensional_pricing` sigue SOLO LECTURA** (sin diff).
- (Historial · turno previo) Responsable Activo (Turno): **NINGUNO — TAREA CERRADA** (17/10 · ciclo **H-037/H-036**). `odoo-verificador` =
  **`cumple`** (una sola pasada, **sin hallazgos**). Los **3 lotes** (`T1–T8`) quedaron **COMPLETOS** y asegurados
  en git; test nuevo `TestProductFlowLotAssignBulkSplit` **8/8 verde** y **regresión real de T1** comprobada
  (revertir el patrón aditivo ⇒ **CA-1 falla**). Verificación del Analista en el punto crítico: `_pf_reserve_lot`
  delega en `stock.move._update_reserved_quantity` (primitiva **NATIVA**, **ADITIVA**, no libera) ⇒ el patrón
  "1 liberación + N reservas" de `_pf_reassign_lots` **SÍ** es aditivo y el diseño se sostiene.
  **Pendiente del DUEÑO (funcional):** recargar el módulo (`-u printflow_gestion_inventario`) en el servidor 8071
  y probar el botón **"Repartir lotes"** (ver §3.N · pendiente del dueño).
  (Nota: **H-034** queda FUERA de esta tarea — §3.10 · O-1.) Ciclo anterior: **T1–T3**
  verificados, **0 pendientes**; `odoo-verificador` = `cumple`.
- Tarea (CERRADA · **NORMAL** · ciclo 17/10-bis): **fix del crash al abrir el detalle del bloque**.
  Atacó **H-032** (la acción `act_window` anidada en `params['next']` iba **sin `views`** ⇒
  `TypeError: Cannot read properties of undefined (reading 'map')` en `_preprocessAction`) y **H-033**
  (el MISMO defecto en el precedente `printflow_node_pending_line.action_pf_validate_selected`, rama `others`).
  Fix: `'views': [(False, 'form')]` en la acción anidada. 3 archivos, 1 lote (**T1–T3**), motor
  `x_product_dimensional_pricing` **SIN CAMBIOS**. Ver **Sección 3**; el ciclo anterior queda como anexo **3.L**.
  **Pendiente del dueño:** recargar el módulo (`-u printflow_gestion_inventario`) y reprobar el botón.
- Tarea (CERRADA · **GRANDE** · ciclo 17/10): **incidencias del wizard de asignación en bloque y del
  "validar entregas en lote"**. Ataca **H-029** (el motivo del fallo por destino no se veía), **H-030** (el
  "validar entregas en lote" des-reservaba la excepción y omitía el 100%) y **H-031** (los rótulos
  "Asignables" vs "Demanda total" confundían FILAS con UNIDADES). Diseño **D1–D7**: **D1** wizard de detalle
  portado de `printflow.delivery.bulk.result` · **D2** guardián ADITIVO en `stock.move._assign_exclusive_lot`
  (motor `x_product_dimensional_pricing` **SIN CAMBIOS**; PrintFlow solo hace `_inherit` + `super()`) ·
  **D3** rótulos "**Entregas por asignar**" / "**Unidades a entregar**" / "**Entregas omitidas**" +
  `selection_note` VISIBLE. Ver **Sección 3** (§3.5 D1–D7 · §3.6 archivos · §3.12 **T1–T9** en 3 lotes).
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`).
  **Pendiente de DATOS (no código):** asignar lote a las 26 entregas desde la bandeja con un lote **con
  existencia** (**H-018**).
- Tarea (CERRADA · **GRANDE** · ciclo anterior): **ASIGNACIÓN DE LOTE EN BLOQUE desde la bandeja** (acción sobre la SELECCIÓN).
  Decidido con el dueño: **(a)** acción en bloque sobre las filas seleccionadas (no el refactor del selector);
  **(b)** si el lote no cubre la demanda sumada ⇒ **asignar lo disponible (parcial)** con confirmación; **(c)** alcance
  **SOLO entregas sin lote** (`pending_order`/movimientos); el resto se OMITE y se reporta. Botón de cabecera
  "Asignar lote" (`display="selection"`), wizard NUEVO `printflow.flow.lot.assign.bulk` con las piezas reutilizadas
  (candidato, `_pf_available_lots`, orquestador nativo) y el **handler `pending_order`** que cierra **H-026**.
  Resuelve **H-021** (ya existe acción masiva) y **H-026**. Ver **Sección 3**.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`).
- Ciclo ANTERIOR: **CERRADO** — "Gestión del error de lote en el diagrama de producto (nodos Entrega e Inventario)"
  (T1–T9 en 3 lotes; `odoo-verificador` = `cumple`; H-020/H-022/H-023/H-024 `resuelto`; H-025 `descartado`).
  Conservado como anexo **3.J**.

> Nota de contexto: el módulo SOLO está instalado en la BD
> `Ciber Estudios 2015 RESTAURADA` (odoo-impreven). En `odoo-produccion`
> (`Ciber Estudios 2015`) el módulo NO está instalado. Confirmar con el dueño si
> la verificación debe hacerse en otra BD.

### Backlog (pendientes para PRÓXIMAS SESIONES · aún sin planificar)
> Anotados por el Analista al cerrar la tarea de Compras/Recepción. NO forman parte de
> la tarea cerrada; se abordan en una sesión aparte, empezando por el **Analista** (paso 1).
- **B1 (ANALIZAR) — 8 rojos de la suite completa, ajenos al cambio de Compras/Recepción.**
  - `test_node_pending_enumeration.test_limit_is_per_node`: el límite `pf_node_pending_limit`
    se aplica en el CALLER (`models/printflow_node_pending_line.py` L121-122), no en el motor
    `printflow.flow.pending`; el test asume lo segundo. Pre-existente.
  - 7 failed + 1 error en áreas de entregas/lotes/phase7: `test_diagnostic_delivery_orders.py:200`,
    `test_phase7_board_permissions.py:162`, `test_product_flow_failure_negative_reserved.py:97`,
    `test_product_flow_lot_picker_ux.py:143`, `test_product_flow_lot_tray_ux.py:149` (tree 4!=3),
    `test_product_flow_solution_single.py:139`.
  - **Objetivo de la sesión:** obtener un **baseline** (el repo git no tiene commits ⇒ hoy no hay
    diff de referencia), separar pre-existentes de reales, y planificar la corrección.
  - **Tamaño:** por clasificar (probable Normal/Grande según cuántos sean reales).
- **B2 (CERRADO · no es pendiente) — Alinear los listados informativos de OC del producto.**
  Cerrado en la tarea del "faltante real" (anexo **3.C**, decisión D3 / hallazgo H-003):
  `wizard/printflow_product_flow.py::_pf_open_purchase_orders` y
  `models/printflow_flow_strategy_product.py::_pf_root_tray` ya listan **solo OC sin confirmar**
  (fuente única `printflow.flow.pending`). Se conserva la fila por trazabilidad.
- **Otros pendientes VIVOS = hallazgos abiertos** (ver [`HALLAZGOS.md`](HALLAZGOS.md)): **H-021**
  (fase 2: "Autorizar excepción" ≠ "Asignar lote" + saneo por documento), **H-016** (el botón
  `_pf_open_delivery_orders` del nodo Entrega muestra 1 vs badge 28), **H-018** (asignación REAL
  de lotes a las 26 entregas = **datos**, no código) y **H-015** (nodo Compras sin cifra cuando el
  faltante real es 0); más H-001/H-002/H-005/H-006 (baja/media). Se priorizan en sesión aparte.

## 2. Mapa Estructural

### A. Árbol de Directorios Permitido
```
printflow_gestion_inventario/
├── __manifest__.py            # orden de carga de vistas/acciones + assets
├── __init__.py
├── CONTEXT.md
├── HALLAZGOS.md               # bitácora de fallos (compañero del CONTEXT.md)
├── data/
│   ├── ir_config_parameter_data.xml
│   └── printflow_product_flow_server_action.xml   # server action "Ver diagrama de flujo"
├── docs/
│   ├── PLAN_excepciones_formales_y_ux_filas.md    # §3.3 UX de "fila clicable"
│   └── diagramas/                                 # diagrama de partes (fuente + imagen)
│       ├── printflow_gestion_inventario.mermaid   # fuente editable del diagrama §2.B
│       └── printflow_gestion_inventario.png       # imagen renderizada (se re-genera)
├── models/                    # lógica (NUNCA importa wizard/)
│   ├── printflow_inventory_catalog.py         # action_open_flow / action_open_product (stub hook)
│   ├── printflow_inventory_catalog_flow.py    # override del hook -> printflow.product.flow
│   ├── printflow_flow_*.py                    # motor de flujo / diagnóstico
│   ├── product_template.py                    # botones de la ficha (diagnóstico)
│   └── checks/                                # chequeos del escáner
├── security/
├── static/src/
│   ├── js/printflow_open_timeline.js          # WIDGET clave: m2o -> enlace que abre acción
│   ├── xml/printflow_open_timeline.xml        # plantilla del widget
│   ├── js/printflow_order_timeline.js         # widget del canvas (diagrama)
│   ├── xml/printflow_order_timeline.xml
│   └── scss/printflow_diagnostic.scss
├── views/
│   ├── printflow_inventory_catalog_views.xml  # <-- TARJETA ACTUAL (tree L29/L47/L52)
│   ├── printflow_inventory_health_views.xml
│   └── ...
├── wizard/                   # wizards transitorios (product.flow, diagnostic, trays)
│   ├── printflow_product_flow.py / _views.xml # el DIAGRAMA (printflow.product.flow)
│   └── printflow_order_diagnostic_wizard_views.xml  # usa el widget en product_id (L144)
└── tests/
```

### B. Diagrama de Partes (Mermaid) — convención "metáfora del carro"

> **Regla:** el diagrama se dibuja por **capas y roles**, no como cajas sueltas. El **MOTOR**
> arriba (núcleo, `NO SE TOCA`), luego la **TRANSMISIÓN** (adapta y propaga) y abajo las
> **RUEDAS** (piezas intercambiables). Las flechas son los **cables** (conectores), rotuladas
> con su nombre. Para corregir: se cambia una rueda o se re-cablea; el motor solo se toca si de
> verdad hay que cambiar el motor.
>
> **Imagen (generada y versionada):** [`docs/diagramas/printflow_gestion_inventario.png`](docs/diagramas/printflow_gestion_inventario.png)
> **Fuente editable:** [`docs/diagramas/printflow_gestion_inventario.mermaid`](docs/diagramas/printflow_gestion_inventario.mermaid)
> (si cambia la estructura, se actualiza el `.mermaid` **y** se re-renderiza el `.png` en el mismo turno).

```mermaid
flowchart TD
    subgraph MOTOR["MOTOR - nucleo, NO SE TOCA"]
      direction LR
      ENGINE{{"x_product_dimensional_pricing<br/>motor de salud (externo)"}}
      FLOW{{"models/printflow_flow_*.py<br/>motor de flujo y diagnostico"}}
    end
    subgraph TRANS["TRANSMISION - adapta y propaga"]
      direction LR
      CAT["printflow_inventory_catalog.py<br/>hook action_open_flow"]
      HOOK["printflow_inventory_catalog_flow.py<br/>override _pf_product_flow_action"]
    end
    subgraph RUEDAS["RUEDAS - piezas intercambiables"]
      direction LR
      WIDGET(["printflow_open_timeline.js<br/>widget m2o"])
      VSTA(["views/printflow_inventory_catalog_views.xml<br/>lista + kanban"])
      WIZ(["wizard/printflow.product.flow<br/>diagrama OWL"])
    end

    MOTOR ~~~ TRANS ~~~ RUEDAS

    ENGINE ==>|"solo lectura"| FLOW
    FLOW ==>|"diagnostico / payload"| WIZ
    CAT ==>|"super() override"| HOOK
    HOOK ==>|"action_open_product_flow"| WIZ
    CAT ==>|"action_open_flow"| WIDGET
    CAT ==>|"action_open_flow"| VSTA

    classDef motor fill:#1f4e79,stroke:#0d2b45,color:#ffffff,stroke-width:2px;
    classDef trans fill:#c55a11,stroke:#7f3a0b,color:#ffffff;
    classDef rueda fill:#548235,stroke:#2f4a1c,color:#ffffff;
    class ENGINE,FLOW motor;
    class CAT,HOOK trans;
    class WIDGET,VSTA,WIZ rueda;
```

**Leyenda de colores:**

| Color | Capa | Significado | ¿Se toca? |
|---|---|---|---|
| 🔵 Azul | MOTOR | Núcleo/dominio: la lógica que mueve todo | **No** (salvo cambio de motor real) |
| 🟠 Naranja | TRANSMISIÓN | Adaptadores/hooks (`_inherit` + `super()`) que propagan | Sí, con cuidado |
| 🟢 Verde | RUEDAS | Piezas intercambiables (widgets, vistas, options) | Sí, es lo normal |
| ✏️ Aristas | CABLES | Conectores (acciones, xmlids, `doActionButton`) | Sí, al re-cablear |

## 3.O (TAREA ABIERTA) — Asignación de lote POR ORDEN: el operador decide qué caja va a qué unidad (H-039 · H-040 · cierra H-034)

> **Turno:** Odoo Analista (apertura · paso 1) → **Odoo Planificador** (paso 2: plan COMPLETO por lotes) ✅
> **Estado:** ⏳ **ABIERTA** — **plan COMPLETO escrito** en §3.7 (`T1..Tn` = **9 tareas · 4 lotes**; listo para el
> primer lote `[motor]` → `odoo-dev`). **Autorización del dueño: SÍ (2026-10-17)** —
> *"aplica las acciones recomendadas"* (D1 = grano por MOVIMIENTO · D2 = retirar los dos modos y dejar UNA sola
> acción centrada en las órdenes).
> **Tarea GRANDE** (toca el **flujo NATIVO de reserva de entregas** ⇒ SIEMPRE Grande: Analista → Planificador →
> Analista → Agente del lote → Verificador → Analista).
> **Fuente:** `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA`.
> **Dónde:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: **aquí se escribe**) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA — NO se edita**).
> **Qué (objeto concreto):** el contenedor `printflow.flow.lot.assign.bulk` (+ su `.line`, su candidato
> `printflow.flow.lot.candidate`, sus vistas y los botones de cabecera de `printflow.flow.lot.tray`).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`).
> **Hallazgos que ataca:** **H-039** (el modo `single` es un **subconjunto estricto** del `split`) · **H-040** (el
> eje de decisión está centrado en el **LOTE**, no en la **ORDEN/UNIDAD**) · **H-034** (pasa a `en tarea`: una
> entrega con **2 unidades** son **2 filas**, una por movimiento).

### 3.1 Problema (evidencia)

El dueño pregunta *"¿por qué se llama REPARTIR lotes si lo que queremos es ASIGNAR un lote a una orden?"* y pide
que **el operador decida qué lote va a qué OC**. El análisis (**solo lectura**) confirma que el eje está invertido:

| # | Hecho | Evidencia |
|---|---|---|
| **P1** | La paridad del negocio es **1 unidad = 1 `stock.move` = 1 línea de pedido = 1 lote `<pedido>-L<línea>`**. Una entrega con **N unidades** tiene **N movimientos/líneas** ⇒ **N decisiones**, no una. | `stock.move.sale_line_id` en los 5 movimientos pendientes (109861→línea **10430** · 120603→**12141** · 120604→**12142** · 122295→**14496** · 127869→**11419**) · motor `sale_order_line.py` L160 ⇒ `'%s-L%s' % (order.name, self.id)` · la reserva vive en `stock.move.line.lot_id` (move 109861 → move line **94907**, `SN0001`, 1 u) |
| **P2** | En el contenedor el eje es **el LOTE**: el operador marca **cajas** (`is_in_split`) y **la máquina** reparte las entregas **en el orden de la tabla**. | `wizard/printflow_flow_lot_assign_bulk.py` L499-511 (`_pf_split_lots` = `candidate_ids.filtered('is_in_split')`, en `_order`) · `wizard/printflow_flow_lot_candidate.py` L48 (`_order = 'available desc, lot_name asc'`) · `models/stock_move.py` L167-171 (`_pf_reassign_lots`: recorre el plan y llena la demanda de **esa** entrega) |
| **P3** | El modo **`single`** es un **subconjunto estricto** del `split` ⇒ **dos botones que hacen lo mismo**. | L547-607 (`action_assign_lot_bulk`: `for line in …: _pf_assign_lot_to_document(..., chosen)`) vs L609-675 (`action_split_lot_bulk`: `… _pf_assign_lots_to_document(..., lots)`) — con **UN lote marcado**, el resultado es idéntico (mismos destinos, mismo lote, misma guarda) |
| **P4** | La fila de entrega **suma** la demanda: un albarán con **2 movimientos** del producto se ve como **UNA** fila de `demand_qty=2`, y la escritura resuelve **1 solo** movimiento. | `wizard/printflow_flow_lot_tray.py` L563-598 (`demand_by_picking[picking_id] += product_uom_qty`) vs L498-516 (`missing_move`: **UNA fila por `stock.move`**) · `wizard/printflow_product_flow.py` L1118-1123 (`limit=1`) · BD: bloque id **8**, fila picking **36004** (WH/OUT/06483) `demand_qty=2` |
| **P5** | El caso real del dueño queda **explicado al 100 %** por P3 + P4. | bloque id **8** (17:48) — 4 destinos, demanda **5** = 1 + 1 + **2** + 1, lote `SN0001` (**1 u**): WH/OUT/10857 `assigned`; WH/OUT/10859 / WH/OUT/06483 / WH/OUT/07271 en `error` *"El lote \"SN0001\" no tiene existencia disponible…"* |

### 3.2 Objetivo (acotado)

Que el operador, en **una sola pasada**, **asigne a cada movimiento (unidad/línea) su caja**, eligiéndola él.
**Qué SÍ:** una fila por movimiento, un selector de lote por fila, pre-llenado con el lote propio del pedido
cuando tenga existencia, un motivo y un aplicar. **Qué NO:** no se rediseña la bandeja ni el motor, no se
tocan datos y no se crean lotes automáticamente.

### 3.3 Contrato (§3.3 del método — los 7 puntos)

1. **Dónde.** `Fuente: odoo-impreven / Ciber Estudios 2015 RESTAURADA`. Ruta de escritura:
   `C:\odoo_custom\printflow_gestion_inventario`. El motor `C:\odoo_custom\x_product_dimensional_pricing`
   es **SOLO LECTURA**.
2. **Qué.** `printflow.flow.lot.assign.bulk` (un solo camino de decisión, centrado en las órdenes) + su
   `.line` + la tabla de candidatos (queda **INFORMATIVA**) + las vistas del contenedor + los botones de
   cabecera de `printflow.flow.lot.tray`.
3. **Objetivo acotado.** Una **única** acción en bloque ("Asignar lote") donde **cada fila es un movimiento**
   y cada fila tiene **su** selector de lote; el operador decide el par **caja ↔ orden/unidad**.
4. **Definición de terminado.** Ver §3.5 (CA-1…CA-11), todos verificables en pantalla y en la BD (solo lectura).
5. **Restricciones duras** (+ **conejeras**, dentro del alcance, se usan con cuidado):
   - **No forzar ni reemplazar flujos NATIVOS**: `_inherit` + `super()`; prohibido escribir
     `stock.quant` / `stock.move` / `stock.move.line` a mano, tocar estados (`state`, `quantity`, `qty_done`),
     `cr.execute` de escritura o `cr.commit()`.
   - **Código sí, datos no** (`regla-trabajo-odoo-17-ce`).
   - **Convenciones OCA** (skill `odoo-17-clean-architecture` §2.5).
   - ⚠️ **Conejera (H-034 · `limit=1` es CONTEXTO, no el bug):** `_pf_document_move`
     (`printflow_flow_lot_tray.py` L786-820) usa `limit=1` **a propósito** para traer el **contexto** del lote
     exclusivo esperado. Ese `limit=1` **NO se toca**; lo que cambia es el **grano de la fila** y el **alcance de
     la ESCRITURA**.
   - ⚠️ **Conejera (`_pf_reassign_move_lot` NO es aditiva):** en el motor, `_pf_reassign_lot` **libera la reserva
     entera y luego reserva** ⇒ **dos llamadas con dos lotes borran el primero**. Para escribir por fila, usar el
     camino **aditivo** que ya existe (`_pf_reassign_lots`: **1 liberación + N reservas**) — **NO** llamar dos
     veces al camino no-aditivo.
   - ⚠️ **Conejera (retirar sin dejar residuo ni tests rotos):** el modo `single` tiene contrato **H-021** y
     tests propios, y `is_selected` / `_pf_enforce_single_selection` los usa **también el selector por
     documento**: se retira **solo el uso en el contenedor**; el `picker` se queda intacto.
   - ⚠️ **Conejera (pre-llenado sin reinventar):** el lote propio de la línea **ya viene resuelto en la fila**
     (`own_lot_name`): reutilizarlo (una lectura, **sin N+1**), no recalcular el lote exclusivo por otra vía.
   - **Registro de conejeras** (`C:\odoo_custom\CONEJERAS.md`): **consultado — vacío** (`n/a`): las de arriba
     nacen del análisis de esta tarea.
6. **Qué se RETIRA** (sustitución, no acumulación — se borra en el mismo lote, sin dejar residuo):
   - El **modo `single`**: `action_assign_lot_bulk`, su valor en `mode`, el botón de cabecera **"Asignar lote"**
     actual, el campo `lot_id` del contenedor y `_pf_check_coverage` (guarda de cobertura del lote único).
   - El **modo `split`** como **superficie**: el botón **"Repartir lotes"**, `action_split_lot_bulk`,
     `is_in_split`, `_pf_split_lots`, `_pf_check_split_coverage` y `_pf_log_split_document`.
   - Las **marcas** de la tabla de candidatos **en el contenedor** (`is_selected` / `is_in_split` como eje de
     decisión): la tabla queda **INFORMATIVA** (Lote · Existencia · Reservado · Disponible · Rol).
   - Los **tests** de los modos retirados: se **retiran o adaptan** (nunca se dejan en rojo).
   - **SE CONSERVA** (no es residuo, es la pieza que escribe bien por unidad): el motor de escritura aditivo
     `_pf_assign_lots_to_document` / `stock.move._pf_reassign_lots` y el registro por chatter.
7. **Fuera de alcance** (lo que el dueño dijo que **NO** y lo que **no** se decide por cuenta propia):
   - ❌ **Ninguna pantalla nueva**: se reutiliza el contenedor existente (el dueño rechazó expresamente una
     "interfaz distinta").
   - ❌ **No** se toca el **selector por documento** `printflow.flow.lot.picker` ni `is_selected` /
     `_pf_enforce_single_selection` (los usa el picker), ni su vista/acciones.
   - ❌ **No** se cambia **qué** lista la bandeja ni su clasificación de `kind`s (solo el **grano** de la fila
     de entrega).
   - ❌ **No** se toca el **MOTOR** `x_product_dimensional_pricing` (si algo pareciera faltar allí, se
     **reporta**, no se edita).
   - ❌ **Ningún DATO**: ni re-etiquetar las **18 u sin lote**, ni los **31 lotes de pedido con 0 existencia**,
     ni lotes con nombre basura (`dwqdqwd`, `6265`), ni las **5 compras canceladas** (P00303/P00320/P00333/
     P00334/P00373), ni las **reservas colgadas** de **H-035** (move lines 94880/94881). Eso es **DATO**
     (operación aparte, consciente y autorizada), **no** código.
   - ❌ **No** se tipifica ni se categoriza el **motivo**: sigue siendo **texto libre obligatorio** en el
     chatter (el dueño lo decidió así: *"es responsabilidad del operador decir por qué"*).
   - ❌ **No** se crean lotes automáticamente (eso es el botón "Crear lote sugerido", ajeno a esta tarea).
   - ❌ **No** se revisa el desfase de `pf_lot_name = 'LOTE-000001'` repitido en todos los pedidos (frente
     propio, sin tarea).

### 3.4 Decisiones de diseño CERRADAS por el dueño (17/10/2026)

| # | Decisión | Razón |
|---|---|---|
| **D1** | **El grano de la fila es el MOVIMIENTO** (`stock.move` = unidad = línea de pedido): una entrega con N unidades produce **N filas**. | Es la paridad del negocio (P1) y **cierra H-034 por construcción** (la segunda unidad deja de ser inalcanzable). |
| **D2** | **Se retiran los DOS modos** (`single` y `split`) y queda **UNA sola** acción en bloque llamada **"Asignar lote"**, con el eje en **las órdenes**. | El `single` está duplicado (P3) y su premisa ("un lote para todas") es la que produce los errores masivos; el `split` decide por la máquina (P2). |
| **D3** | **Pre-llenado**: cada fila llega con el **lote propio de su línea** (`<pedido>-L<línea>`) **si ese lote tiene existencia**; si no, queda **vacía** y visible. | La Ley #1 ("cada lote nace atado a su pedido") se cumple **sola** en el camino normal; la excepción la hace el operador. |
| **D4** | El desplegable **"Lote a asignar"** lista **solo lotes con existencia**; el **lote propio** va en **columna informativa** con su existencia (`0.00` visible). | El operador **ve** que la caja del pedido está vacía y por eso elige otra: elección consciente, no a ciegas. |
| **D5** | El **motivo** sigue siendo **obligatorio** y se registra en el **chatter** del documento (lote + motivo + usuario). | Ya funciona y el dueño lo aceptó como suficiente. |
| **D6** | La **escritura** sigue siendo el **protocolo NATIVO** (reserva), con el **motor sin cambios**. | `regla-trabajo-odoo-17-ce` + cero reinvención. |

### 3.5 Criterios de aceptación (verificables)

- **CA-1** — La bandeja ofrece **UNA** acción de lote en bloque (la nueva **"Asignar lote"**); **"Repartir lotes"**
  y el modo `single` **no existen** (ni botón, ni acción, ni valor de `mode`).
- **CA-2** — El contenedor lista **UNA fila por movimiento** del producto: para **WH/OUT/06483** ⇒ **2 filas**
  (líneas **12141** y **12142**), no una de demanda 2.
- **CA-3** — Cada fila muestra **OC/entrega · línea de pedido · unidad · lote propio (con su existencia)** y un
  **selector de lote** con **solo lotes con existencia**.
- **CA-4** — Las filas llegan **pre-llenadas** con el lote propio cuando su existencia > 0; **vacías** si es 0.
- **CA-5** — Al aplicar, cada fila con lote queda en **`assigned`** con el `stock.move.line.lot_id` correcto, y
  una entrega con **2 unidades se cubre COMPLETA (2/2)** ⇒ **H-034 cerrado**.
- **CA-6** — Cada documento afectado recibe su mensaje de **chatter** con **lote + motivo + usuario**; el motivo
  es obligatorio (vacío ⇒ `UserError`).
- **CA-7** — Una fila cuyo lote no cubra la demanda queda **`partial`** y **no revienta** las demás (captura por
  fila) y el resultado se ve en la ventana de detalle (H-029).
- **CA-8** — El **selector por documento** (`printflow.flow.lot.picker`) sigue funcionando **igual** (sus tests
  verdes).
- **CA-9** — El **motor** `x_product_dimensional_pricing` **sin cambios** (sin diff en ese repo).
- **CA-10** — **Código sí, datos no**: abrir/cerrar el contenedor **no** modifica `stock.quant` / `stock.lot` /
  `stock.move`; solo la escritura NATIVA de las filas aplicadas.
- **CA-11** — Tests relevantes **N/N verdes** (`--test-tags /printflow_gestion_inventario`); los tests de los
  modos retirados quedan **retirados o adaptados**, nunca en rojo.

### 3.6 Contratos que NO deben romperse

| Contrato | Pieza |
|---|---|
| Selector por documento | `printflow.flow.lot.picker` + `is_selected` / `_pf_enforce_single_selection` + su vista |
| Bandeja de lote | `printflow.flow.lot.tray` y su clasificación de `kind`s (qué se lista) |
| Registro auditable | `_pf_log_document` (chatter: lote + motivo + usuario) |
| Detalle por destino (H-029) | `printflow.flow.lot.assign.bulk.result` y sus vistas/test |
| Primitivas del MOTOR | `_pf_reassign_lots`, `_pf_unassign_reservation`, `_pf_reserve_lot` (SIN cambios) |
| Escritura NATIVA | `_update_reserved_quantity` / protocolo de reserva (no se escribe a mano) |

### 3.7 Plan de ejecución (checklist por LOTES de máximo 3) — LO ESCRIBE EL PLANIFICADOR

> El **Odoo Planificador** escribe aquí el plan **COMPLETO** (`T1..Tn`), **ordenado por dependencia** (**motor
> antes que pantalla**) y con el **dueño** de cada tarea: `[motor]` (`odoo-dev`) o `[pantalla]` (`odoo-vistas`).
> Un lote = ≤3 tareas **sin mezclar dueños**. El agente marca `[x]`; **la marca ES el estado**.

> **Plan COMPLETO · 9 tareas · 4 lotes** (máx. 3 por lote; **sin mezclar dueños**). Cada lote es **UNA sesión
> NUEVA** del agente que diga su etiqueta (`[motor]` → `odoo-dev`, `[pantalla]` → `odoo-vistas`), nunca se retoma
> la anterior. El agente marca `- [x]` **solo lo hecho** y deja su **bitácora** para el lote siguiente.
> **Fuente:** `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: **aquí se escribe**) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA — NO se edita**).
> **Regla vigente: código sí, datos no** (`regla-trabajo-odoo-17-ce`). PROHIBIDO `cr.execute` de escritura y
> `cr.commit()`.
> **NO forzar ni reemplazar flujos nativos; código sí, datos no.** La ÚNICA escritura sigue siendo la reserva
> NATIVA (primitivas del motor `_pf_unreserve_reservation` / `_pf_reserve_lot`, consumidas por
> `stock.move._pf_reassign_lots`).
> **Convenciones OCA §2.5** (un archivo por modelo, orden del modelo, `snake_case`, campos `*_ids` para x2many,
> `xml_id` con prefijo `printflow_`, nodo raíz `<odoo>`). **Cero modelos nuevos ⇒ sin filas de ACL y sin `data`
> nueva en el manifest.**

**Cómo queda el diseño (una línea).** El contenedor `printflow.flow.lot.assign.bulk` queda con **UNA sola acción**
"**Asignar lote**", **un destino = UN MOVIMIENTO** (`stock.move` = unidad = línea de pedido) y **un selector de lote
POR FILA**: el operador decide la caja de cada unidad en una sola pasada. La tabla de candidatos queda
**INFORMATIVA**. Desaparecen el modo `single` (un lote para todo) y el modo `split` (la máquina reparte). La
escritura de cada fila reutiliza el camino **NATIVO ADITIVO** que ya existe
(`_pf_assign_lots_to_document` → `stock.move._pf_reassign_lots`) con **un** lote por movimiento.

> ⚠️ **Orden de los lotes — ADD → REPINTAR → BORRAR (obligatorio, o el módulo no carga).**
> 1. **Lote 1 (`[motor]`)**: se **AGREGA** todo lo que la decisión por fila necesita (campos de la línea,
>    orquestación por fila, expansión del grano en el contenedor). **No se retira nada todavía**: los forms viejos
>    (`single` y `split`) siguen cargando porque sus campos (`mode`, `split_note`, `lot_id` del contenedor,
>    `is_in_split`) **siguen existiendo**.
> 2. **Lote 2 (`[pantalla]`)**: se **REPINTA** la pantalla (un solo form con el selector por fila) y se **borran
>    las superficies viejas** (el form del reparto y el botón "Repartir lotes").
> 3. **Lote 3 (`[motor]`)**: se **BORRAN los campos/métodos** que ya nadie referencia (si se borraran antes, los
>    forms viejos romperían la carga por campo inexistente).
> La regla "motor antes que pantalla" se cumple donde manda su razón: **el form nuevo solo pinta campos que T1/T2
> ya crearon**. Lo que se borra (el form del reparto) se borra **antes** de que T6 borre sus campos.
> ⚠️ **Estado intermedio declarado:** entre el cierre del Lote 1 y el cierre del Lote 2 la pantalla NO se usa
> (el motor ya es por fila y el form viejo todavía no tiene el selector por fila).
> ⚠️ **ROJOS ESPERADOS entre lotes (NO perseguir — es el orden ADD→REPINTAR→BORRAR):**
> `TestProductFlowLotAssignBulkSplit` (usa `action_split_lot_bulk`, retirado en el **Lote 1** ⇒ lo retira **T8**) y
> `TestProductFlowLotAssignBulkResult` (guarda por fila + el rótulo "Unidades por asignar" ⇒ lo adapta **T9**).
> Los candados de **bandeja / pending_order / picker** quedan **VERDES** (verificado en el Lote 1: 41/41).

#### Lote 1 (T1–T3) — `[motor]` · Motor de la decisión POR UNIDAD/MOVIMIENTO (aditivo)

- [x] **T1 — `wizard/printflow_flow_lot_assign_bulk_line.py`: campos del destino por UNIDAD (grano = MOVIMIENTO).**
  - Agregar los campos (respetando el orden OCA: atributos → campos), con `help` en cada uno:
    - `lot_id = fields.Many2one('stock.lot', string='Lote a asignar', help=...)` con
      `domain="[('product_id', '=', bulk_id.product_id), ('id', 'in', bulk_id.candidate_lot_ids)]"`
      ⇒ **el selector de lote DE ESTA FILA** (D4: solo lotes con existencia; `no_create` en la vista).
      *Si el cliente no resolviera el dominio con la ruta al padre, la salida es declarar en la línea dos campos
      `related` de solo lectura (`bulk_product_id` ← `bulk_id.product_id`, `bulk_candidate_lot_ids` ←
      `bulk_id.candidate_lot_ids`, sin `store`) y usar ESOS en el dominio. No cambiar la semántica: el desplegable
      lista **solo lotes con existencia** del producto.*
    - `own_lot_id = fields.Many2one('stock.lot', string='Registro del lote propio', readonly=True)`.
    - `own_lot_name = fields.Char(string='Lote propio', readonly=True)` (nombre calculado `<pedido>-L<línea>`;
      **puede no existir como `stock.lot`** ⇒ se muestra con existencia `0.00`, D4).
    - `own_lot_qty = fields.Float(string='Existencia del lote propio', readonly=True, digits='Product Unit of Measure')`.
    - `sale_order_name = fields.Char(string='Pedido', readonly=True)`.
    - `sale_line_id = fields.Many2one('sale.order.line', string='Línea de pedido', readonly=True)`.
    - Cambiar el `string` de `move_id` a **`'Unidad'`** (la fila ES el movimiento; CA-3).
  - Extender el docstring del módulo: la línea ya **no** es "una entrega" sino **UNA UNIDAD (un `stock.move`)** y
    guarda la **decisión del operador** (`lot_id`) además del snapshot y el resultado.
  - **NO** tocar `bulk_id`, `seq`, `kind`, `res_model`, `res_id`, `label`, `demand_qty`, `location_id`,
    `scheduled_date`, `assignable`, `result`, `result_note` (contrato del detalle H-029).
  - **Verificación:** `python -m py_compile wizard/printflow_flow_lot_assign_bulk_line.py` OK; `-u
    printflow_gestion_inventario` sin error; `fields_get('printflow.flow.lot.assign.bulk.line')` incluye `lot_id`,
    `own_lot_id`, `own_lot_name`, `own_lot_qty`, `sale_order_name`, `sale_line_id` y `move_id` con
    `string='Unidad'`.

- [x] **T2 — `wizard/printflow_flow_lot_assign_bulk.py`: decisión POR FILA (una sola acción centrada en las órdenes).**
  - **`_pf_prepare_rows`**: enriquecer cada fila con el **lote propio POR MOVIMIENTO**. Con la MISMA lectura batch
    de movimientos que ya hace (agregar `sale_line_id`, `product_uom_qty`, `picking_id`), resolver
    `own_lot_name` con la **misma primitiva del motor** que usa la bandeja
    (`sale.order.line._get_exclusive_lot_name()`), y dejar `sale_order_name` / `sale_line_id`. **Sin N+1**.
    El `own_lot_name` que trae la fila de la bandeja queda como **respaldo** cuando el movimiento no tiene línea
    de pedido. **NO** tocar el orden FIFO (`scheduled_date ASC, res_id ASC`) ni el **dedupe por `move_id`**.
  - **`_pf_populate`**: escribir en `line_vals` las claves nuevas (`own_lot_id`, `own_lot_name`, `own_lot_qty`,
    `sale_order_name`, `sale_line_id`) y **pre-llenar** `lot_id` (D3/CA-4): si el lote propio **existe** y su
    candidato tiene **existencia efectiva** (`available_here` si hay ubicación única; `available` si es
    `multi_location`) `> _EPS` ⇒ `lot_id` = ese lote; si no ⇒ **vacío y visible**. Se resuelve con el mapa de
    candidatos ya calculado (`_pf_available_lots(..., include_lot_ids=own_lot_ids)`): **una lectura, sin N+1**.
    **Mantener** el argumento `mode='single'` de la firma (lo usa el reparto, que todavía existe hasta T6).
  - **REESCRIBIR `action_assign_lot_bulk`** (la ÚNICA acción; mismo nombre, misma ruta desde el botón de cabecera):
    1. `self.ensure_one()`; `self.env['printflow.stock.remedy']._pf_assert_can_clean()`;
    2. `reason` obligatorio ⇒ `UserError` (CA-6);
    3. política (`self.env['printflow.flow.lot.picker']._pf_exception_policy()`; si ≠ `'warn'` exige
       `confirm_exception` ⇒ `UserError`) — cero hardcodeo;
    4. **guía sin escritura**: si **ninguna** fila `assignable` tiene `lot_id` ⇒ `UserError`
       ("Elige el lote de al menos una unidad…"); las filas sin lote **no bloquean** a las demás;
    5. por cada `line in self.line_ids.filtered('assignable')`:
       - sin `line.lot_id` ⇒ `line.result='skipped'` + `result_note` ("Sin lote elegido: la unidad no se toca."),
         `continue`;
       - `try: ProductFlow._pf_assign_lots_to_document(line.kind, 'stock.move', line.move_id.id, [line.lot_id],
         product=self.product_id)` (camino **NATIVO ADITIVO**; el MOVIMIENTO se pasa **directo**, sin `limit=1`)
         `except UserError as err:` ⇒ `line.result='error'` + `result_note=str(err)`, `continue`;
       - `reserved = self._pf_line_reserved(line, line.lot_id)`; clasificar como hoy
         (`<= _EPS` ⇒ `error`; `< demand` ⇒ `partial`; si no ⇒ `assigned`) y `self._pf_log_document(line,
         line.lot_id)` (**mismo** message_post: lote + motivo + usuario; **NO** se toca `_pf_log_document`);
    6. `<result> = self.env['printflow.flow.lot.assign.bulk.result']._pf_build_from_bulk(self)` y
       `return self._pf_result_notification(result)` (**mismo cierre, mismos 4 conteos y mismo `params['next']`**,
       D5/CA-6 sin regresión).
  - **Ajustar los textos al nuevo grano** (consecuencia declarada de **D1**, no es alcance nuevo; evita repetir
    el error de H-031): `assignable_count` ⇒ `string='Unidades por asignar'`; `omitted_count` ⇒
    `string='Filas omitidas'` (cuenta **filas de origen** descartadas, no movimientos);
    `_compute_selection_note` ⇒ declarar que **cada fila es una UNIDAD (un movimiento de la entrega)** y que las
    cifras van en unidades.
  - **NO retirar todavía** (lo hace T6, cuando las superficies viejas ya no existan): `mode`, `split_note`,
    `_compute_split_note`, `lot_id` (del contenedor), `_pf_selected_lot`, `_pf_check_coverage`, `_pf_split_lots`,
    `_pf_check_split_coverage`, `_pf_log_split_document`, `action_split_lot_bulk`, `confirm_partial`.
  - **NO** tocar `_pf_prepare_rows` en su dedupe/orden, `_pf_result_notification`, `_pf_line_reserved`,
    `_pf_log_document`, `_pf_own_lot_ids`, `candidate_lot_ids`/`_compute_candidate_lot_ids` (sigue siendo el
    dominio del selector por fila), `_compute_assignable_count`, el modelo de resultado ni `_pf_build_from_bulk`.
  - **Verificación:** `py_compile` OK; `-u` sin error; los candados
    `test_product_flow_lot_assign_bulk_result.py`, `test_product_flow_lot_assign_bulk_split.py` y
    `test_product_flow_lot_pending_order_assign.py` siguen **verdes** (el reparto y el camino por documento no se
    tocaron en este lote). En shell: `bulk.line_ids` trae `own_lot_name`/`sale_line_id` y, cuando el lote propio
    tiene existencia, `lot_id` pre-llenado; cuando no, `lot_id` vacío.

- [x] **T3 — `wizard/printflow_flow_lot_tray.py`: grano de la fila del contenedor = MOVIMIENTO (cierra H-034) +
      retiro de la entrada del reparto.**
  - **`_pf_bulk_rows`**: **expandir** cada fila `pending_order` (que apunta al ALBARÁN) en **UNA fila por
    `stock.move` ACTIVO del producto en ese albarán** (`state not in ('done','cancel')`), con **UNA sola
    búsqueda batch** para todos los albaranes de la selección (**sin N+1**). Cada fila expandida lleva:
    `move_id` (el movimiento exacto), `res_model`/`res_id` = **el DOCUMENTO** (el `stock.picking`, para la
    bitácora de `_pf_log_document`), `demand_qty = move.product_uom_qty`, `picking_id`, `label` (el de la
    entrega) y `own_lot_name`/`sale_order_name` **del movimiento** (`move.sale_line_id`). Las filas
    `missing_move` conservan su movimiento y su documento (`move.picking_id` si lo tiene).
    **Mantener intactos**: el filtro de asignables (`can_choose_lot` + kinds), el **descarte** de las que no
    resuelven movimiento, el **dedupe por `move.id`** y el conteo de `omitted` (ahora cuenta **filas de ORIGEN**
    descartadas).
  - **RETIRAR** `action_split_lot_bulk` de la bandeja (método completo). **SE RETIRA del ciclo §3.N** (T5/T7 del
    anexo): la superficie "Repartir lotes" deja de existir; su botón se borra en **T5**.
  - **NO** tocar `_pf_document_move` (su `limit=1` es **CONTEXTO**, no el bug — §3.3 · conejera H-034), ni
    `_pf_rows_*` (lo que LISTA la bandeja no cambia), ni `action_assign_lot_bulk` (sigue abriendo el MISMO
    contenedor, sin `mode`), ni `_pf_annotate_lot_quantities`, ni `_pf_row_lot_context`.
  - **Verificación:** `py_compile` OK; `hasattr(env['printflow.flow.lot.tray'], 'action_split_lot_bulk') is False`;
    con un albarán de **2 movimientos del producto** (patrón WH/OUT/06483: 2 × `product_uom_qty=1`, líneas 12141 y
    12142) la selección de su fila `pending_order` produce **2 filas / 2 `move_id` distintos** ⇒ el contenedor
    abre con **2 `line_ids`** (CA-2); los candados de bandeja (`test_product_flow_lot_tray*.py`) **verdes**
    (la bandeja no cambió su grano).

#### Lote 2 (T4–T5) — `[pantalla]` · Una sola pantalla de decisión por unidad + retiro de las superficies viejas

- [x] **T4 — `wizard/printflow_flow_lot_assign_bulk_views.xml`: UN form (decisión lote ↔ unidad) y retiro del form
      del reparto.**
  - **REESCRIBIR** el record `printflow_flow_lot_assign_bulk_view_form`
    (`printflow.flow.lot.assign.bulk.form`), `create="false" delete="false"`, con **una sola decisión** por
    pantalla (skill `odoo-view-design`):
    1. campos técnicos ocultos: `candidate_lot_ids`, `multi_location`;
    2. `<group string="Selección">` con **los mismos rótulos** ya acordados: `product_id`, `source_label`,
       `total_demand`, `location_id`, `assignable_count`, `omitted_count`, `selection_note` (visible);
    3. el aviso `alert-warning` de `multi_location` (**sin cambios**);
    4. `<group string="Unidades de la entrega" col="1">` con el texto guía *"Elige el lote de CADA unidad: cada
       fila es un movimiento (una unidad / línea de pedido) de la entrega."* y
       `<field name="line_ids" nolabel="1">` con un **`<tree editable="bottom" create="false" delete="false">`**
       con las columnas: `seq` (`#`), `label` (**Entrega**), `sale_order_name` (**Pedido**, `optional="hide"`),
       `sale_line_id` (**Línea de pedido**), `move_id` (**Unidad**), `own_lot_name` (**Lote propio**),
       `own_lot_qty` (**Existencia**), `lot_id` (**Lote a asignar**, `options="{'no_create': True,
       'no_open': True}"`, `readonly="not assignable"`), `demand_qty` (**Demanda**), `result` (**Resultado**),
       `result_note` (**Nota**, `optional="show"`) y ocultos `kind`, `res_model`, `res_id`, `assignable`,
       `location_id`; decoraciones `success` (`assigned`), `warning` (`partial`), `muted` (`skipped`), `danger`
       (`error`);
    5. `<group string="Lotes con existencia" col="1">` con un texto corto *"Informativo: lotes con existencia del
       producto. La decisión se toma arriba, en cada unidad."* y `<field name="candidate_ids" nolabel="1">` con un
       **`<tree>` INLINE de SOLO LECTURA** (`create="false" delete="false" editable="false"`) con
       **Lote · Existencia · Reservado · Disponible · Rol** (`lot_name`, `qty_on_hand`, `reserved`, `available`,
       `role_label`) + `is_own_lot`/`is_elective`/`is_occupied` con `column_invisible="True"`. **NO** se pone
       ninguna columna de marca (`is_selected`): la tabla es **INFORMATIVA** (§3.3 · punto 6);
    6. `<group string="Motivo de la asignación" col="1">` con `reason` **required** + microcopy (el motivo es
       obligatorio y queda en la bitácora de cada documento; requiere jefe de taller/administrador y ESCRIBE
       inventario por la vía NATIVA);
    7. `<footer>` con `<button name="action_assign_lot_bulk" type="object" string="Asignar lote"
       class="btn-primary" icon="fa-tags" title="..."/>` y "Cancelar" (`special="cancel"`).
  - **BORRAR el record** `printflow_flow_lot_assign_bulk_view_form_split`
    (`printflow.flow.lot.assign.bulk.form.split`) completo. **SE RETIRA del ciclo §3.N** (T6 del anexo).
  - **NO** tocar el tree COMPARTIDO `printflow_flow_lot_candidate_view_tree` (lo usan el selector por documento y
    los candados de C4), ni `__manifest__.py` (el archivo ya está en `data`).
  - **Verificación:** `-u printflow_gestion_inventario` sin error; desde la bandeja (acción de **lectura**) el
    contenedor abre con **una fila por movimiento**, un selector de lote por fila, la tabla informativa y el
    motivo; `env.ref('printflow_gestion_inventario.printflow_flow_lot_assign_bulk_view_form_split')` **ya no
    existe**. No se acciona el botón (BD de PRUEBA: solo abrir/leer).

- [x] **T5 — `wizard/printflow_flow_lot_tray_views.xml`: re-rotular "Asignar lote" (el borrado del botón YA está hecho).**
  - ✅ **BORRAR el `<button name="action_split_lot_bulk" … string="Repartir lotes">`: HECHO en el Lote 1** por
    **desviación declarada D-1** — sin ese borrado el módulo **no carga** (`ParseError: action_split_lot_bulk is not
    a valid action on printflow.flow.lot.tray`). Queda **UNA** sola acción de lote en bloque (CA-1).
  - ⏳ **PENDIENTE (este lote):** actualizar el `title` del botón `action_assign_lot_bulk` para declarar el contrato
    nuevo: *"Elige el lote de CADA unidad (cada fila es un movimiento de la entrega). ESCRIBE inventario por la vía
    NATIVA (reserva). Requiere jefe de taller/administrador"*.
  - **NO** tocar los demás botones de cabecera ni las columnas del tree (H-029/H-031/H-032 intactos).
  - **Verificación:** `-u` sin error; con filas seleccionadas en la bandeja aparece **solo** "Asignar lote"
    (además de las acciones de autorización/confirmación ya existentes); "Repartir lotes" **no existe**.

#### Lote 3 (T6–T8) — `[motor]` · Retiro del residuo (sin residuo ni tests rotos) + test del camino nuevo

- [x] **T6 — Retiro COMPLETO del modo retirado: `wizard/printflow_flow_lot_assign_bulk.py` +
      `wizard/printflow_flow_lot_candidate.py`.**
  - `printflow_flow_lot_assign_bulk.py`: **BORRAR** `mode` (campo y valor), `split_note`, `_compute_split_note`,
    `lot_id` (del contenedor), `_pf_selected_lot`, `_pf_check_coverage`, `_pf_split_lots`,
    `_pf_check_split_coverage`, `_pf_log_split_document`, `action_split_lot_bulk` y `confirm_partial`
    (**consecuencia declarada de CA-7**: con la decisión por fila la parcial se reporta **por fila** y no se
    bloquea en bloque ⇒ el check queda sin función). Quitar `mode` de la firma de `_pf_populate` (y de su
    `create({...})`) y **actualizar el docstring** (una sola acción, un destino = un movimiento). **Conservar**
    `candidate_lot_ids` + `_compute_candidate_lot_ids` (dominio del selector por fila), `confirm_exception`,
    `total_demand`, `assignable_count`, `omitted_count`, `selection_note`, `source_label`, `location_id`,
    `multi_location`, `line_ids`, `candidate_ids`, `reason`.
  - `printflow_flow_lot_candidate.py`: **BORRAR** `is_in_split` (la columna del reparto);
    `_compute_is_picked` pasa a depender de `picker_id.lot_id` + `lot_id` (**sin** `bulk_id.lot_id`, que ya no
    existe) y `_pf_enforce_single_selection` **solo** espeja/desmarca sobre el **padre selector**
    (`picker_id`), nunca sobre el contenedor; actualizar el docstring (la fila sirve a **dos** superficies:
    selector por documento + tabla informativa del contenedor). **Conservar** `is_selected`,
    `_compute_is_elective`, `_compute_is_recommended`, `_compute_role_label`, `write` y el tree compartido.
  - **NO** tocar `models/` (el motor `x_product_dimensional_pricing` **SIN CAMBIOS**; `_pf_reassign_lots` y
    `_pf_assign_lots_to_document` se **consumen** tal cual), ni `security/ir.model.access.csv` (**sin modelos
    nuevos**), ni `__manifest__.py`.
  - **Verificación:** `-u` sin error; `fields_get` del contenedor **sin** `mode`, `split_note` ni `lot_id`;
    `fields_get` del candidato **sin** `is_in_split`; `hasattr(bulk, 'action_split_lot_bulk') is False`;
    `grep -E "is_in_split|split_note|action_split_lot_bulk|_pf_split_|_pf_check_coverage|_pf_selected_lot|_pf_log_split_document"` sobre `wizard/` y `views/` ⇒ **0** resultados; tests del
    selector por documento (`test_product_flow_lot_picker*.py`) **verdes** (CA-8) y `git diff` de
    `C:\odoo_custom\x_product_dimensional_pricing` **vacío** (CA-9).

- [x] **T7 — Test NUEVO del camino por unidad: `tests/test_product_flow_lot_assign_bulk_per_move.py` (+
      `tests/__init__.py`).**
  - Partir de la MISMA base/helpers de `tests/test_product_flow_lot_assign_bulk.py` (`TransactionCase`;
    `@tagged('post_install', '-at_install')`; `_product`, `_lot`, `_stock`, `_outgoing`, `_open_tray`, `_user`,
    `_manager`; `PARAM_EXCEPTION_POLICY='warn'` en `setUpClass`) y agregar `_wizard_for(selection)` (usa
    `selection.action_assign_lot_bulk()`; aserta `res_model == 'printflow.flow.lot.assign.bulk'`,
    `target == 'new'`).
  - Casos (nombres obligatorios):
    * `test_ca1_only_one_bulk_action_exists` (**CA-1**): `hasattr(tray, 'action_split_lot_bulk') is False`;
      `'mode' not in bulk._fields`; `'split_note' not in bulk._fields`.
    * `test_ca2_two_moves_of_one_delivery_are_two_rows` (**CA-2 · cierra H-034**): un albarán con **2
      movimientos** del producto (2 × 1 u, líneas de pedido distintas) ⇒ el contenedor trae **2 `line_ids`** con
      **2 `move_id` distintos** y `demand_qty = 1` cada una (no una de 2).
    * `test_ca3_each_row_shows_own_lot_and_selector` (**CA-3/CA-4**): cada línea trae `own_lot_name`
      (`<pedido>-L<línea>`) + `own_lot_qty`; el lote propio **con** existencia llega **pre-llenado** en `lot_id`;
      con existencia **0** llega **vacío** y visible (`0.00`).
    * `test_ca5_per_row_lots_cover_both_moves` (**CA-5**): 2 movimientos con **2 lotes de 1 u** elegidos **uno por
      fila** ⇒ tras `action_assign_lot_bulk()` cada `stock.move` tiene **su** `move_line` con **su** lote y las 2
      filas quedan `assigned` (la entrega se cubre **completa 2/2**).
    * `test_ca6_reason_policy_and_permissions` (**CA-6**): sin jefe de taller/administrador ⇒ `UserError`; sin
      `reason` ⇒ `UserError`; política ≠ `warn` sin `confirm_exception` ⇒ `UserError`.
    * `test_ca7_partial_row_does_not_break_the_rest` (**CA-7**): una fila con un lote que **no cubre** queda
      `partial` (o `error` si reserva 0) con nota, y la **otra** fila queda `assigned` (captura por fila).
    * `test_ca7_row_without_lot_is_skipped` : una fila sin `lot_id` queda `skipped`, **no se escribe** en su
      movimiento y **no** bloquea a las demás.
    * `test_ca10_opening_writes_nothing` (**CA-10**): abrir/poblar el contenedor **no** altera
      `stock.quant`/`stock.lot`/`stock.move` (comparar antes/después).
    * Candado: el archivo **NO** contiene `cr.execute(` ni `cr.commit(`.
  - `tests/__init__.py`: registrar `from . import test_product_flow_lot_assign_bulk_per_move` junto al bloque de
    lote, con comentario del motivo (**H-039/H-040 · cierre H-034**).
  - **Verificación:** el archivo pasa **en verde**; **regresión real, no decorativa:** si se revierte T3
    (sin expandir a movimientos) `test_ca2` **falla** con 1 fila en vez de 2; si se revierte T2 (sin selector por
    fila) `test_ca5` **falla**. Dejarlo escrito en la bitácora.

- [x] **T8 — Retiro/adaptación de los tests de los modos retirados (parte 1).**
  - **RETIRAR** `tests/test_product_flow_lot_assign_bulk_split.py` (el modo `split` ya no existe) y su import en
    `tests/__init__.py`. **SE RETIRA del ciclo §3.N** (T8 del anexo).
  - **ADAPTAR** `tests/test_product_flow_lot_assign_bulk.py` al contrato por fila: sustituir
    `bulk.lot_id = lot.id` por `line.lot_id` **por fila**; `test_ca2_bulk_assigns_lot_to_all_destinations` pasa a
    asignar el **mismo lote a cada fila** (equivalente al gesto "una caja para todas", pero decidido fila por
    fila); `test_ca4_partial_requires_confirmation` se **reemplaza** por el caso de **parcial por fila**
    (CA-7: ya no hay check global de parcial) y `test_ca4_scarce_lot_reports_error_on_starved_destination` se
    adapta a la clasificación por fila (`partial`/`error` con nota).
  - **NO** dejar ningún test en rojo ni "saltado" (`skip`) para tapar el hueco.
  - **Verificación:** `test_product_flow_lot_assign_bulk.py` **verde**; `grep -E "is_in_split|action_split_lot_bulk|split_note"` sobre `tests/` ⇒ **0** resultados.

#### Lote 4 (T9) — `[motor]` · Retiro/adaptación de los tests de los modos retirados (parte 2)

- [x] **T9 — Adaptación del detalle y del camino `pending_order`.**
  - **ADAPTAR** `tests/test_product_flow_lot_assign_bulk_result.py` al detalle por **movimiento**: los conteos
    (asignadas/parciales/omitidas/error) son por **unidad**, y el `params['next']` sigue apuntando a
    `printflow.flow.lot.assign.bulk.result` con **una fila por destino** (H-029 intacto).
  - **REVISAR/ADAPTAR** `tests/test_product_flow_lot_pending_order_assign.py`: la fila `pending_order` de la
    **bandeja** sigue apuntando al **albarán** (`res_model='stock.picking'` — la bandeja NO cambia su grano); solo
    adaptar si algún conteo/rótulo se movió por el nuevo grano del **contenedor**.
  - **REVISAR** los candados de bandeja (`test_product_flow_lot_tray.py`, `..._tray_orders.py`,
    `..._tray_document.py`, `..._tray_authorize*.py`, `..._lot_picker*.py`, `test_lot_management.py`,
    `test_pf_bulk_validate_preserves_lot.py`) y **reportar el delta**; **no** perseguir los **8 rojos
    pre-existentes (B1/O-5)**.
  - **Verificación:** suite de lote/bandeja **verde** (delta reportado en bitácora); `grep` de los símbolos
    retirados sobre `tests/` ⇒ **0**; el archivo NO contiene `cr.execute(`/`cr.commit(`.

#### Lote 5 (T10) — `[pantalla]` · **Camino rápido (§4.1)**: restituir la confirmación de excepción (regresión de T4)

- [x] **T10 — `wizard/printflow_flow_lot_assign_bulk_views.xml`: restituir el campo `confirm_exception`.**
  - **Motivo (gap reportado por el Lote 2, verificado por el Analista):** el form **anterior** traía
    `confirm_exception` (junto a `lot_id` y `confirm_partial`); el form **nuevo** de T4 **no lo pinta**, pero
    `action_assign_lot_bulk` (T2) lo **exige** cuando la política de excepción ≠ `'warn'` (CA-6) ⇒ con una política
    estricta el operador **no tiene cómo confirmar** desde la UI (**callejón sin salida**). `confirm_exception`
    **NO** está en la lista de retiro (§3.3 · punto 6: se retira `confirm_partial`, no la confirmación de
    excepción) ⇒ es una **regresión**: se restituye.
  - **Qué:** dentro del `<group string="Motivo de la asignación" col="1">`, añadir
    `<field name="confirm_exception"/>` **después** de `reason`, con `help` breve (*"La política vigente exige
    confirmar la excepción."*). **Nada más**: no se toca ningún otro campo, grupo ni el `<footer>`.
  - **NO** tocar `confirm_partial` (retirado **a propósito**: la parcial se reporta **por fila** y no se bloquea en
    bloque; ver T6 y CA-7).
  - **Verificación:** `xml.dom.minidom.parse` OK; `grep confirm_exception` sobre la vista ⇒ **1** ocurrencia;
    `-u printflow_gestion_inventario` sin error; la casilla visible en el grupo "Motivo".
  - **Camino rápido (§4.1):** **1 archivo, sin decisión de diseño** ⇒ se delega **directo** a `odoo-vistas` (sin
    Planificador); el `odoo-verificador` lo mira al cerrar el ciclo, junto con **CA-6**.

> **Riesgos y mitigaciones (de este plan).**
> | # | Riesgo | Mitigación |
> |---|---|---|
> | **R-1** | Borrar `mode`/`split_note`/`is_in_split`/`lot_id` **antes** de repintar rompe la carga (campo inexistente en el form). | Orden **ADD (Lote 1) → REPINTAR (Lote 2) → BORRAR (Lote 3)**, declarado arriba. |
> | **R-2** | La expansión por movimiento duplica filas (una `pending_order` + una `missing_move` del mismo movimiento). | Se conserva el **dedupe por `move.id`** en `_pf_bulk_rows` y en `_pf_prepare_rows` (el primero gana). |
> | **R-3** | La bitácora se pierde al pasar el destino a `stock.move`. | La línea conserva el **DOCUMENTO** (`res_model`/`res_id` = albarán) para `_pf_log_document`; el **movimiento** viaja aparte en `move_id` y es lo único que se escribe. |
> | **R-4** | El lote propio del 2.º movimiento se toma del 1.º (el `limit=1` de `_pf_document_move`). | El lote propio se resuelve **por movimiento** en `_pf_prepare_rows` (misma primitiva `_get_exclusive_lot_name`, lectura batch). El `limit=1` de `_pf_document_move` **no se toca** (es CONTEXTO). |
> | **R-5** | Sobre-reserva por escribir la misma unidad dos veces. | Cada fila es **un** movimiento y se escribe **una** vez; `_pf_reassign_lots` libera 1 vez y reserva **1** lote por fila. |
> | **R-6** | Regresión del selector por documento. | `is_selected`/`_pf_enforce_single_selection` **se conservan** para el picker; solo se retira su uso en el contenedor. Test de picker **verde** (CA-8). |
> | **R-7** | Los 8 rojos de la suite completa (B1). | El Dev corre **solo** los tests de lote/bandeja afectados y **reporta el delta**; **no** los persigue (O-5). |

**Verificación (turno del `odoo-verificador`, fuera del dev).** Leer §3.O completo y los archivos tocados; correr
`--test-tags` sobre `/printflow_gestion_inventario:TestProductFlowLotAssignBulkPerMove` (nuevo) y, sin regresión,
`...:TestProductFlowLotAssignBulk`, `...:TestProductFlowLotAssignBulkResult`,
`...:TestProductFlowLotPendingOrderAssign`, `...:TestProductFlowLotTray`, `...:TestProductFlowLotTrayOrders`,
`...:TestProductFlowLotTrayDocument`, `...:TestProductFlowLotTrayAuthorize`,
`...:TestProductFlowLotPicker`, `...:TestProductFlowLotPickerUX`, `...:TestProductFlowLotCoupledChain`,
`...:TestLotManagement`, `...:TestPfBulkValidatePreservesLot`. Veredicto de CA-1…CA-11 (§3.5) y de que **no** se
forzó ningún flujo nativo (`grep cr.execute|cr.commit`; `git diff` del motor **vacío**).

## 3.N (ANEXO · TAREA CERRADA) — Reparto multi-lote en bloque (H-037 · H-036)

> **Turno:** Odoo Analista (CIERRE; paso 5). **Estado:** ✅ **TAREA CERRADA** — `T1–T8` en **3 lotes**
> **COMPLETOS** y **verificado** por el `odoo-verificador` = **`cumple`** (una sola pasada, sin hallazgos).
> **Cierre 17/10:** **H-036** y **H-037** → `resuelto`; **H-034** FUERA (O-1) y **H-038** sigue `abierto`
> (riesgo de proceso del repo del MOTOR, ajeno a este módulo).
> **Tarea GRANDE** (toca el FLUJO NATIVO de reserva de entregas ⇒ **SIEMPRE Grande**: Analista → Planificador →
> Analista → Dev por lotes → Verificador → Analista).
> **Fuente:** `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA`.
> **Dónde:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: **aquí se escribe**) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA — NO se edita**).
> **Qué (objeto concreto):** `printflow.flow.lot.assign.bulk` (+ su `.line`, su candidato
> `printflow.flow.lot.candidate`, sus vistas y la acción "Asignar lote" de `printflow.flow.lot.tray`).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`).
> **Hallazgos que ataca:** **H-037** (sin capacidad de REPARTO multi-lote) · **H-036** (el check "Asignar" de la
> tabla parece multiselección pero es de selección ÚNICA). **Vecino a EVALUAR (no necesariamente dentro):**
> **H-034** (el bloque resuelve UN solo `stock.move` por albarán).

### 3.1 Problema (evidencia)

El dueño pide que el wizard en bloque permita **asignar VARIOS lotes** de una sola pasada (p. ej. `666634` de
23 u **más** los lotes de 1 u) para cubrir la demanda de las entregas sin lote. Hoy **no se puede**:

| # | Hecho | Evidencia |
|---|---|---|
| **P1** | El contenedor asigna **UN** lote a **N** entregas: es su **contrato declarado**, NO un accidente de reutilización. | `wizard/printflow_flow_lot_assign_bulk.py` L2-8 (docstring *"Asignación EN BLOQUE de UN lote a N entregas"*), L97-101 (`lot_id` `Many2one` único), L384-400 (`_pf_selected_lot` devuelve UNO; `UserError` si hay >1), L455-468 (pasa el mismo `chosen` a todos los destinos). |
| **P2** | El check **"Asignar"** de la tabla de candidatos PARECE multiselección pero es de **selección ÚNICA** (gana el último tick). | `wizard/printflow_flow_lot_candidate.py` L263-294 (`write` → `_pf_enforce_single_selection`), L94-98 (`is_selected` único) · `wizard/printflow_flow_lot_picker_views.xml` L32-33 (`editable="bottom"`, `string="Asignar"`) · BD: bulk id **4**, única fila marcada `SN126353` (1 u) con `666634` (23 u) sin marcar. |
| **P3** | El protocolo NATIVO disponible **no sabe SUMAR lotes a un movimiento**: `_pf_reassign_lot` **libera la reserva entera** y luego reserva el nuevo lote ⇒ llamarlo 2 veces borra el 1.º. | `x_product_dimensional_pricing/models/stock_move.py` L152-192 (`_pf_unreserve_reservation()` + `_pf_reserve_lot`), L10-33 (`_is_exclusive_delivery`), L194-204 (`_assign_exclusive_lot`: reserva UN lote). |
| **P4** | Consecuencia ya medida: no existe **ninguna** corrida con el lote de 23 u; las únicas con lote fueron `8763` (3 u) y `SN126353` (1 u) ⇒ **1 asignada / 25-26 con error**. | BD: `printflow.flow.lot.assign.bulk` id **1** y **4**; candidatos del bulk 4 (`666634` 23 u `is_recommended=true`, NO marcado). |

### 3.2 Objetivo (acotado)

**SÍ:** que el operador pueda resolver desde la bandeja las entregas sin lote usando **VARIOS lotes con
existencia** (reparto), reutilizando el contenedor `printflow.flow.lot.assign.bulk` y el protocolo NATIVO de
reserva.
**NO:** reinventar el flujo de reserva (nada de escribir `stock.quant`/`stock.move` a mano); NO tocar el motor
(**solo lectura**); NO tocar datos; NO cambiar el contrato del **selector por documento**
(`printflow.flow.lot.picker`, "un lote por documento").

**Definición de TERMINADO:** el operador marca **2+ lotes** con `Disponible > 0` en la bandeja, pulsa asignar
una sola vez, y **todos** los lotes quedan reservados por la vía NATIVA en las entregas (sin perder ninguno),
con el reporte por destino y el motivo intactos; el selector por documento sigue igual; los tests del módulo
pasan en verde.

### 3.3 Contrato funcional (qué debe quedar) — decisiones RESUELTAS en §3.4

**Decisión D-A (arquitectura) — RESUELTA por el Planificador: OPCIÓN B** (se conserva el contenedor y gana un MODO de reparto; ver §3.4 · D-A).

- **Opción A:** un **wizard NUEVO** solo para el reparto multi-lote.
- **Opción B (recomendada por el Analista):** **conservar** `printflow.flow.lot.assign.bulk` y añadirle un
  **camino/modo de REPARTO** (otra acción + otra estructura de selección **ordenada** de lotes) que reutilice
  `_pf_prepare_rows`, `_pf_populate`/tabla de candidatos, `_pf_check_coverage`, el captura-de-error por destino,
  la bitácora y el wizard de resultado.

> **Por qué B:** el contenedor **YA** es el sitio correcto ("N destinos + K lotes + 1 motivo"); solo su etapa de
> DECISIÓN es de un lote. Un wizard nuevo **duplicaría** seis piezas (`_pf_prepare_rows`, dedupe, candidatos,
> cobertura, captura por destino, bitácora + resultado) y sus tests.

**Comportamiento requerido (vale para A y B):**

| # | Debe quedar |
|---|---|
| **C1** | El operador puede marcar **varios lotes** con `Disponible > 0` y la asignación los aplica a la selección **sin perder ninguno** (hoy el 2.º tick pisa al 1.º). |
| **C2** | El reparto es **determinista y auditable**: el orden de lotes y de destinos queda DECLARADO (el Planificador lo fija) y el **motivo** sigue siendo obligatorio (bitácora por documento). |
| **C3** | **Cero escritura forzada:** todo lote se reserva por el protocolo NATIVO; **prohibido** `cr.execute` de escritura, `cr.commit()`, `unlink()`+`create()` a mano, y escribir `stock.quant`/`stock.move`/`quantity`/`state` directamente. |
| **C4** | El **selector por documento** (`printflow.flow.lot.picker`) queda **INTACTO** (su contrato es un lote por documento y está cubierto por tests). |
| **C5** | Se conserva el **reporte por destino** (asignado / parcial / omitido / error) y el detalle (H-029) **sin regresión**. |
| **C6** | La **excepción de lote** y la política (`pf_lot_assign_exception_policy`) siguen gobernando (cero hardcodeo). |

**PREGUNTA TÉCNICA BLOQUEANTE — RESUELTA por el Planificador: CAMINO NATIVO ADITIVO (i)** (ver §3.4 · D-C: `_update_reserved_quantity` SUMA a la línea del mismo lote, no reemplaza).
Un mismo `stock.move` puede necesitar **2+ lotes** (p. ej. demanda 2 u con lotes de 1 u). El camino actual (`_pf_reassign_move_lot` → `_pf_reassign_lot`)
**libera** la reserva antes de reservar ⇒ **NO es aditivo** (P3). Dos salidas posibles: (i) hallar el camino
**NATIVO ADITIVO** (reserva acumulativa vía `_update_reserved_quantity` sobre el movimiento respetando la
excepción de lote), o (ii) **acotar el alcance** a "**un lote por movimiento/destino**" y declararlo explícito.
Debe quedar escrito cuál se elige y por qué.

**Decisión D-B (alcance) — RESUELTA por el Planificador: H-034 queda FUERA** (declarado en §3.10 · O-1).
Si **H-034** (un solo `stock.move` por albarán) entra en esta tarea o se deja FUERA (declarado en "Observaciones fuera de alcance").

### 3.4 Decisiones de diseño CERRADAS (D-A · D-B · D-C · D1–D6)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` · Rutas:
> `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: aquí se escribe) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA — NO se edita**).
> Regla vigente: **código sí, datos no** (`regla-trabajo-odoo-17-ce`); cadena: Analista → **Planificador** →
> Analista → Dev (por lotes, máx. 3) → Verificador → Analista.
> **No se reinventa ni se fuerza ningún flujo nativo:** toda reserva sigue pasando por las PRIMITIVAS NATIVAS
> (`stock.move._do_unreserve` / `stock.move._update_reserved_quantity`, que el motor expone como
> `_pf_unreserve_reservation` / `_pf_reserve_lot`). El diseño **ENGANCHA** el protocolo existente y le añade el
> ÚNICO eslabón que faltaba: reservar **N lotes de forma ADITIVA** sobre el MISMO movimiento (hoy la primitiva
> del motor es "liberar TODO y reservar UNO").
> **Trazabilidad:** D-A → decide arquitectura · D-B → decide alcance · D-C → **responde la pregunta
> bloqueante** · D1–D6 → diseño de detalle.

**D-A — Arquitectura: OPCIÓN B (CERRADA · el contenedor gana un MODO de reparto).**
- Se **CONSERVA** `printflow.flow.lot.assign.bulk` (TransientModel: destinos `line_ids`, candidatos
  `candidate_ids`, `reason`, política, cobertura, captura de error por destino, bitácora y el detalle
  `printflow.flow.lot.assign.bulk.result`) y se le añade un **MODO**: `mode = 'single' | 'split'`.
- `mode='single'` es el de HOY, **sin cambios observables**: mismo `action_assign_lot_bulk`, mismos 4 conteos,
  mismo encadenado del detalle (**H-029**), misma cobertura, mismo escritor.
- `mode='split'` es el **REPARTO multi-lote** (H-037).
- **Por qué NO un wizard nuevo (Opción A):** duplicaría las SEIS piezas que el contenedor ya tiene
  (`_pf_prepare_rows` + dedupe, tabla de candidatos, `_pf_check_coverage`, captura por destino, bitácora y
  wizard de resultado) y sus tests; y el contenedor **YA** es el sitio correcto ("N destinos + K lotes +
  1 motivo"). **Por qué NO tocar el selector por documento:** su contrato es UN lote por documento y está
  cubierto por tests (**C4**).
- **Entrada nueva (acción sobre la SELECCIÓN):** botón de cabecera **"Repartir lotes"**
  (`action_split_lot_bulk`) en la bandeja `printflow.flow.lot.tray`, HERMANO de "Asignar lote"; abre el MISMO
  contenedor en `mode='split'`.

**D-B — Alcance: H-034 (multi-MOVIMIENTO) queda FUERA de esta tarea (CERRADA).**
- Esta tarea es **multi-LOTE**; **H-034** es **multi-MOVIMIENTO** (un albarán con 2+ movimientos del mismo
  producto: `_pf_rows_pending_orders` produce UNA fila por ORDEN y la resolución usa `limit=1`).
- Se **declara** en §3.10 (**O-1**) con su evidencia y se deja para una tarea propia (requiere cambiar la
  ENUMERACIÓN de filas de la bandeja y la resolución a N movimientos por albarán: otra superficie, otro riesgo y
  otra decisión del dueño). **NO** se toca el `limit=1` de `_pf_document_move` ni el de
  `_pf_assign_lot_on_pending_order_doc`.
- **Consecuencia asumida (declarada):** en un albarán con 2 movimientos del producto el reparto resuelve **UN**
  movimiento (igual que hoy); el segundo sigue apareciendo al validar (H-034) y **no empeora** por esta tarea.

**D-C — RESPUESTA A LA PREGUNTA BLOQUEANTE: camino NATIVO ADITIVO (i) (CERRADA).**
- **Hecho verificado en el fuente INSTALADO del core**
  (`C:\Program Files\Odoo 17.0.20250124\server\odoo\addons\stock\models\stock_move.py`, L1505-1559,
  `_update_reserved_quantity`): la primitiva nativa **NO reemplaza** la reserva: busca la `stock.move.line` cuya
  clave `(location, lot, package, owner)` coincide y **SUMA** a su `quantity`; si no existe, **CREA** una línea
  nueva. **Nunca borra las líneas de OTROS lotes** ⇒ llamada N veces con N lotes distintos, la reserva es
  **ACUMULATIVA** (N líneas, un lote cada una, con la cantidad acotada por lo disponible).
- **Por qué HOY no era aditiva (P3):** porque el camino actual (`_pf_reassign_move_lot` → motor
  `_pf_reassign_lot`) ejecuta `_pf_unreserve_reservation()` (libera TODO el movimiento) **antes** de reservar
  ⇒ dos llamadas ⇒ la segunda borra la primera. El defecto **no** está en la primitiva: está en **encadenar dos
  "liberar y reservar"**.
- **Diseño elegido:** **UNA** liberación por destino (primitiva del motor) + **N** reservas **ADITIVAS** en el
  orden del plan (`_pf_reserve_lot` por lote, acotando por la demanda que falta). **Nada nuevo contra la base de
  datos:** son las MISMAS primitivas que el camino de un lote (D5 del anexo 3.K respetado: un solo módulo
  escritor, mismo protocolo). Lo único que cambia es el **patrón de llamadas** (1 liberar + N sumar, en vez de
  1 liberar + 1 sumar).
- **Consecuencia inmediata (el pedido del dueño se cumple):** un mismo `stock.move` puede quedar con **2+ lotes
  con existencia** (p. ej. `666634` de 23 u **más** los lotes de 1 u) — exactamente lo que el wizard no podía
  hacer (H-037) y la razón de que el 2.º tick pisara al 1.º (H-036).
**D1 — SELECCIÓN multi-lote: una columna NUEVA en el candidato, SIN tocar la selección única.**
- `printflow.flow.lot.candidate` gana `is_in_split` (Boolean, `string='Incluir'`, help del reparto). **NO** entra
  en `_pf_enforce_single_selection` (el hook `write` del candidato solo reacciona a `'is_selected'`) ⇒ se pueden
  marcar VARIOS lotes a la vez sin que se desmarquen (**contraste directo con H-036**).
- `is_selected` y su semántica **ÚNICA** quedan **INTACTOS** (modo `single` y selector por documento).
- La tabla del reparto se define **INLINE en el form del modo reparto**
  (`<field name="candidate_ids">` con un `<tree>` EMBEBIDO) ⇒ **NO** se toca el tree compartido
  `printflow_flow_lot_candidate_view_tree` (que sigue sirviendo al selector por documento y al modo `single`,
  **C4/C5**).

**D2 — ORDEN del reparto: DECLARADO, el de la tabla tal como se ve (determinista y reproducible).**
- Orden de **LOTES** = el de la tabla de candidatos (`printflow.flow.lot.candidate._order =
  'available desc, lot_name asc'`): **primero el lote con más disponible**; a igualdad, por nombre ascendente.
- Orden de **DESTINOS** = `seq` de `line_ids` (FIFO por fecha prevista ASC + id ASC, ya declarado en D6 del
  anexo 3.K). No hay reglas escondidas: **lo que se ve en pantalla es el orden que se aplica**.
- El reparto es **AVARO por destino** (el 1.º destino se cubre con los primeros lotes; luego el 2.º, etc.), con
  la misma semántica FIFO de la escasez que ya rige la acción en bloque.
- `split_note` (Char, computado, **VISIBLE**) muestra el plan: "1) 666634 → 23.00 · 2) SN126353 → 1.00 …" con
  el total disponible frente a la demanda. Es una **estimación de la tabla** (sin lecturas extra); la reserva
  REAL la decide la primitiva nativa por destino.

**D3 — COBERTURA: misma regla que el modo `single`, calculada sobre el plan.**
- Con ubicación efectiva: `libre = Σ stock.quant._get_available_quantity(product, location_id, lot_id=lot)`
  (una lectura por lote marcado; acotada a la selección del operador). Sin ubicación única (`multi_location`):
  `Σ available` **AGREGADO** de los candidatos marcados (aviso visible ya existente).
- `Σ libre <= _EPS` ⇒ `UserError` guía ("Ninguno de los lotes marcados tiene existencia…"). **NO escribe nada.**
- `Σ libre < total_demand` sin `confirm_partial` ⇒ `UserError` guía (mismo check y misma familia de texto que el
  modo `single`); con el check ⇒ se reparte **lo que hay** y los destinos que no alcancen quedan `partial`.

**D4 — ESCRITURA: un solo módulo escritor, N reservas ADITIVAS (código sí, datos no).**
- Primitiva NUEVA en PrintFlow `models/stock_move.py` (**ya existe** el archivo con el guardián de H-030;
  `_inherit = 'stock.move'`): `_pf_reassign_lots(self, lots)` = **una** `self._pf_unreserve_reservation()`
  (primitiva del MOTOR, sin tocarla) + **N** `self._pf_reserve_lot(lot, remaining)` (primitiva del MOTOR,
  ADITIVA por construcción) en el orden del plan, acotando por `product_uom_qty` del movimiento.
- **Guardián propio** (espeja el filtro del core y el de `_pf_unreserve_reservation`): si el movimiento está
  `picked` o en `('done', 'cancel')` ⇒ devuelve `0.0` (no se apilan reservas sobre lo ya en curso; el destino se
  reporta con error honesto).
- **Orquestador** (mismo módulo escritor): `printflow.product.flow._pf_assign_lots_to_document(kind,
  res_model, res_id, lots, product)` — misma guardia `_pf_assert_can_clean`, **lista blanca explícita** de kinds
  `('missing_move', 'pending_order')` (constante local `_SPLIT_KINDS`; **NUNCA `getattr`**), mismo camino de
  resolución del movimiento que `_pf_assign_lot_on_pending_order_doc` (resolver PRIVADO propio del reparto: el
  handler existente **no se toca**).
- El motor `x_product_dimensional_pricing` queda **SIN CAMBIOS**: solo se **consumen** sus primitivas.

**D5 — REPORTE por destino y bitácora (H-029 / H-031 SIN regresión).**
- Se conservan el modelo de línea (`result` + `result_note`), el detalle
  `printflow.flow.lot.assign.bulk.result` (una fila por destino, incluidas las omitidas y las no asignables) y el
  **mismo** cierre de la acción (`display_notification` con el **MISMO** texto de los 4 conteos + `params['next']`
  al detalle) ⇒ **cero regresión** de H-029/H-031/H-032.
- En reparto, `result_note` = **desglose por lote** ("Reparto: 666634 → 2.00 · SN126353 → 1.00 (1 lote sin
  existencia)"), acotado y compacto (Char). La clasificación es la MISMA de hoy: `reserved <= _EPS` ⇒ `error`;
  `reserved < demand - _EPS` ⇒ `partial`; si no ⇒ `assigned`.
- Bitácora: se agrega `_pf_log_split_document` (**NO** se toca `_pf_log_document`): mismo `message_post` por
  documento en modelos con chatter, listando los lotes del plan y el reservado real, con el `reason` común.

**D6 — H-036 (contrato UX del check "Asignar"): se corrige EN PANTALLA, sin cambiar la selección única.**
- La selección ÚNICA del modo `single` es **deliberada** (H-036) ⇒ **NO** se cambia; se **declara en pantalla**:
  el texto de la ranura "Lotes" del form del modo `single` dice explícitamente que **se asigna UN lote por
  corrida** (el marcado) y **apunta al camino nuevo** ("Repartir lotes") para repartir la demanda entre varios.
  Es exactamente el arreglo que H-036 prescribe ("decirlo en pantalla y ofrecer el camino para los demás").
- En el modo reparto, la columna del candidato se rotula **"Incluir"** (multi-tick) ⇒ el gesto deja de
  confundirse con el del modo `single`.
- **NO** se renombra la columna del tree **COMPARTIDO** (`string="Asignar"`): se evita tocar una superficie del
  selector por documento y sus candados (**C4**).

### 3.5 Archivos

**NUEVO**
- `tests/test_product_flow_lot_assign_bulk_split.py` — CA-1..CA-7 del reparto (T8).

**MODIFICADOS**
- `models/stock_move.py` — primitiva ADITIVA `_pf_reassign_lots` (+ docstring del módulo). (T1)
- `wizard/printflow_product_flow.py` — `_SPLIT_KINDS` + `_pf_assign_lots_to_document` + resolver privado. (T2)
- `wizard/printflow_flow_lot_candidate.py` — campo `is_in_split`. (T3)
- `wizard/printflow_flow_lot_assign_bulk.py` — `mode`, `split_note`, `_pf_split_lots`,
  `_pf_check_split_coverage`, `_pf_line_breakdown`, `_pf_log_split_document`, `action_split_lot_bulk`,
  `_pf_populate(..., mode=...)`. (T4)
- `wizard/printflow_flow_lot_tray.py` — `action_split_lot_bulk` + helper compartido `_pf_bulk_rows`. (T5)
- `wizard/printflow_flow_lot_assign_bulk_views.xml` — form NUEVO del modo reparto (tree inline con "Incluir") +
  microcopy de H-036 en el form del modo `single`. (T6)
- `wizard/printflow_flow_lot_tray_views.xml` — botón de cabecera "Repartir lotes". (T7)
- `tests/__init__.py` — registro del test nuevo. (T8)

**SIN CAMBIOS (contrato):** `security/ir.model.access.csv` (**NO hay modelos nuevos ⇒ sin filas nuevas**),
`__manifest__.py` (la vista nueva es un `<record>` dentro de un archivo YA declarado en `data`), el motor
`x_product_dimensional_pricing` (**SOLO LECTURA**), `wizard/printflow_flow_lot_picker*`,
`printflow_flow_lot_candidate_view_tree` (tree compartido), `models/printflow_flow_lots.py`
(`_pf_available_lots`), `wizard/printflow_flow_lot_assign_bulk_result*`, `printflow.flow.lot.tray`
(`action_assign_lot_bulk`, `_pf_document_move`, `_pf_rows_*`).

### 3.6 Restricciones duras

1. **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): el Dev **NO** toca registros de la BD; solo código.
2. **No forzar ni reemplazar flujos nativos.** PROHIBIDO `cr.execute` de escritura, `cr.commit()`, escribir
   `stock.quant` / `stock.move` / `stock.move.line` a mano, forzar `state` / `quantity` / `qty_done`,
   `unlink()`+`create()` a mano, `button_validate` / `_action_done` por detrás. La ÚNICA escritura son las
   primitivas del MOTOR (`_pf_unreserve_reservation`, `_pf_reserve_lot`) sobre el movimiento del destino,
   disparadas por el **operador** desde el botón.
3. El motor `x_product_dimensional_pricing` **NO se edita** (sus primitivas se **consumen** tal cual).
4. **Sin modelos nuevos** ⇒ sin filas de ACL y sin `data` nueva en el manifest.
5. **Cero hardcodeo:** todos los textos por `_()`; la política sale de `ir.config_parameter`
   (`pf_lot_assign_exception_policy`).
6. **Convenciones OCA** (`odoo-17-clean-architecture` §2.5): un archivo por modelo, orden del modelo
   (atributos → campos → computes → CRUD → acciones → negocio), `snake_case`, campos `*_ids` para x2many,
   `xml_id` con prefijo `printflow_`, nodo raíz `<odoo>`.
7. **Un solo módulo escritor** (`printflow.product.flow`) con **lista blanca explícita** de kinds
   (**NUNCA `getattr`**).
8. **NO romper:** modo `single`, selector por documento, bandeja clásica, autorización en bloque, dedupe FIFO ni
   el detalle H-029.

### 3.7 Criterios de aceptación (verificables)

| # | Criterio | Verificación |
|---|---|---|
| **CA-1** (**reparto multi-lote**) | Con **2+ lotes marcados** en la columna "Incluir" (todos con `Disponible > 0`), UNA sola corrida deja **TODOS** los lotes reservados por la vía NATIVA en las entregas **sin perder ninguno**: un destino cuya demanda exige 2 lotes queda con **2 `stock.move.line`** (una por lote) y con la reserva completa. | Test T8: destinos con demanda 2 u y dos lotes de 1 u ⇒ tras `action_split_lot_bulk()` el movimiento tiene 2 líneas (lotes distintos) y la fila del destino queda `assigned`. |
| **CA-2** (**H-036 · multi-tick**) | Marcar varios lotes en la tabla del reparto **NO se desmarca entre sí** (`is_in_split` es independiente por fila); y la selección **ÚNICA** de `is_selected` sigue intacta. | Test T8: `write({'is_in_split': True})` en 2 candidatos ⇒ los 2 quedan `True`; `write({'is_selected': True})` en 2 ⇒ solo 1 queda `True`. |
| **CA-3** (**parcial**) | Si `Σ libre del plan < total_demand` y NO se marcó "Confirmo la asignación parcial" ⇒ `UserError` guía **sin escribir nada**; con el check ⇒ se reparte lo disponible **en el orden declarado** y los destinos que no alcancen quedan `partial` con el desglose en `result_note`. | Test T8: demanda 3 u con lotes de 1+1 ⇒ `UserError` y 0 `move_line`; con `confirm_partial=True` ⇒ 2 u repartidas, fila `partial`, `result_note` con los 2 lotes. |
| **CA-4** (**orden declarado**) | El orden del reparto es el declarado: **lotes** por el orden de la tabla (`available desc, lot_name asc`) y **destinos** por `seq` (FIFO). El `split_note` es VISIBLE y coincide con el orden aplicado. | Test T8: lotes de 1 u y 3 u con demanda 2 ⇒ el plan empieza por el de 3 u (`split_note`) y la reserva consume primero ese lote. |
| **CA-5** (**reporte intacto**) | La acción de reparto conserva los **4 conteos**, el `display_notification` y el `params['next']` al detalle `printflow.flow.lot.assign.bulk.result` (una fila por destino, con `result` y `result_note`), igual que el modo `single` (H-029/H-031 sin regresión). | Test T8: mismo bloque de aserciones del detalle que `test_product_flow_lot_assign_bulk.py`/`..._result.py`, pero ejecutado desde `action_split_lot_bulk`. |
| **CA-6** (**guardia · motivo · política**) | Sin jefe de taller/administrador, ABRIR y EJECUTAR lanzan `UserError`; sin `reason` ⇒ `UserError`; con política ≠ `warn` sin `confirm_exception` ⇒ `UserError`. | Test T8 (mismos escenarios de CA-5/CA-6 del modo `single`). |
| **CA-7** (**cero regresión**) | El modo `single` (`action_assign_lot_bulk`) y el selector por documento conservan su comportamiento; el motor **SIN CAMBIOS**; `_pf_available_lots` con firma y retorno intactos; el tree compartido de candidatos intacto. | Suite citada abajo en verde; `git diff` vacío en `x_product_dimensional_pricing`; sin `cr.execute(`/`cr.commit(` en los archivos tocados. |
| **CA-8** (**no apilar sobre lo en curso**) | Un movimiento `picked` o en `('done','cancel')` **no recibe** reservas nuevas: `_pf_reassign_lots` devuelve `0.0` y el destino se reporta con error honesto. | Test T8: movimiento `done`/`picked` ⇒ `result == 'error'` y `result_note` explica, sin tocar sus líneas. |
| **CA-9** (**superficies**) | El botón de cabecera "Repartir lotes" abre el form del MODO REPARTO (no el del modo `single`) y el form del modo `single` **no cambia** su comportamiento. | Verificación de T6/T7 con `-u printflow_gestion_inventario` + el test de CA-5 (el `act_window` apunta a la vista del reparto). |

### 3.8 Riesgos

| # | Riesgo | Impacto | Mitigación |
|---|---|---|---|
| **R-1** | Volver a "perder" un lote (el bug que se quiere cerrar). | Alto | `_pf_reassign_lots` libera **UNA** vez y luego **SUMA**; entre reservas no hay ninguna liberación. CA-1 lo fija con 2 lotes reales. |
| **R-2** | Sobre-reserva si se llama dos veces a `_update_reserved_quantity` con el **mismo** lote para el mismo movimiento. | Medio | Cada lote del plan se procesa **una sola vez** por destino y se acota por `remaining = need - taken`, con corte en `<= _EPS`. CA-1 (cantidad total == demanda) y CA-3 lo vigilan. |
| **R-3** | El motor "exclusivo por lote" reescribe el reparto en un `action_assign` posterior (p. ej. "validar entregas en lote"). | Medio | El guardián **H-030** ya instalado en `models/stock_move.py` (`_pf_keep_current_lot_reservation`) **preserva** la reserva cuando el lote exclusivo del pedido **no** tiene existencia (el caso real del banner). Si el lote exclusivo **SÍ** tiene existencia, gana la regla de negocio del lote exclusivo (igual que hoy con un lote: **no** se cambia esa regla). Se declara en §3.9. |
| **R-4** | La estimación del `split_note` (tabla) difiere de la reserva real en modo `multi_location`. | Bajo | El aviso **VISIBLE** de `multi_location` ya existe; la reserva REAL la decide la primitiva nativa por destino y el `confirm_partial` cubre el faltante. El `split_note` se declara como **estimación**. |
| **R-5** | Tocar el tree COMPARTIDO de candidatos rompe el selector por documento y sus candados. | Alto | La tabla del reparto es un `<tree>` **INLINE** en el form nuevo; el tree compartido **no se edita** (D1/D6). |
| **R-6** | El helper `_pf_bulk_rows` (extracción del preparado de filas) altera el modo `single`. | Medio | La extracción es **behavior-preserving**: `action_assign_lot_bulk` conserva su retorno y sus mensajes; los candados `test_product_flow_lot_assign_bulk.py`, `..._pending_order_assign.py`, `..._tray*` deben seguir **verdes** (CA-7). |
| **R-7** | La suite completa tiene **8 rojos pre-existentes (B1)** ajenos. | Bajo | El Dev corre SOLO los tests de lote/bandeja afectados y **reporta el delta**; NO persigue B1. |

### 3.9 Contratos que NO deben romperse

- **CA-1..CA-9** de §3.7.
- `printflow.flow.lot.assign.bulk.action_assign_lot_bulk` (**modo `single`**): guardia `_pf_assert_can_clean()`,
  `reason` obligatorio, política de excepción, `_pf_check_coverage`, bucle FIFO con captura de `UserError` por
  destino, `message_post` por documento, **texto exacto de los 4 conteos** y `params['next']` al detalle: **SIN
  CAMBIOS observables**.
- `printflow.flow.lot.picker` + `_pf_populate`/`_pf_selected_lot`/`action_assign_lot`: **INTACTOS**.
- `printflow.flow.lot.candidate`: `is_selected`, `_pf_enforce_single_selection`, `_compute_is_picked`,
  `_compute_is_recommended` y su **tree compartido**: **INTACTOS** (solo se AGREGA un campo).
- `printflow.product.flow._pf_assign_lot_to_document`, el mapa `handlers` (lista blanca, nunca `getattr`) y
  `_pf_reassign_move_lot`: **INTACTOS** (el reparto entra por un método NUEVO del MISMO módulo).
- `stock.move._pf_reassign_lot`, `_pf_unreserve_reservation`, `_pf_reserve_lot`, `_assign_exclusive_lot` y
  `_action_assign` del **motor**: **INTACTOS** (solo se consumen).
- `models/stock_move.py` de PrintFlow: `_pf_keep_current_lot_reservation` y el override de
  `_assign_exclusive_lot` (**H-030**): **INTACTOS**.
- `printflow.flow.lot.tray._pf_populate`, `_pf_document_move`, `_pf_rows_*` y su tree (botón de cabecera
  "Asignar lote" y columnas): **INTACTOS** (solo se AGREGA un método y un botón).
- `models/printflow_flow_lots.py::_pf_available_lots`: firma y dict de retorno **INTACTOS**.
- `models/` **nunca** importa `wizard/`. Sin `cr.execute` de escritura. Sin `cr.commit()`.

### 3.10 Observaciones (FUERA de alcance — NO implementar aquí)

- **O-1 · H-034 (multi-MOVIMIENTO): FUERA (D-B).** El `limit=1` de la resolución (`_pf_document_move`,
  `_pf_assign_lot_on_pending_order_doc`) y la enumeración de UNA fila por ORDEN
  (`_pf_rows_pending_orders`) **no se tocan**. Evidencia: `wizard/printflow_product_flow.py` L970-982 ·
  `wizard/printflow_flow_lot_tray.py` L786-820 y L536-599 · BD: `stock.move` 109860/109861 (WH/OUT/05608) y
  120603/120604 (WH/OUT/06483). Requiere tarea propia (y decisión del dueño, según H-034).
- **O-2** La asignación **REAL** de lotes a las 26 entregas del banner es **DATOS** (**H-018**); la ejecuta el
  dueño desde la bandeja. El código **muestra** y **facilita**, no asigna por su cuenta.
- **O-3** Las reservas colgadas **sin lote** (**H-035**, `quant` 15219 con disponible −2) son **DATO**; se
  resuelven asignando un lote con existencia desde la bandeja (no tecleando cantidades a mano).
- **O-4** El refactor del **selector por documento** a multiselección ("propuesta 2") sigue en backlog.
- **O-5** Los **8 rojos** de la suite (**B1**, p. ej. `test_diagnostic_delivery_orders.py`,
  `test_product_flow_lot_tray_ux.py`, `test_node_pending_enumeration`) siguen abiertos y son ajenos; el Dev
  **reporta el delta** si cambia por esta tarea y **no** los persigue.
- **O-6** **H-021** (fase 2: "Autorizar excepción" ≠ "Asignar lote"), **H-016** y **H-015** siguen fuera de
  alcance.
- **O-7** Autorizar la **excepción de lote compartido** en bloque **NO** entra: el reparto escribe por el
  protocolo NATIVO (no crea `printflow.lot.exception`); la autorización se hace por fila, como hoy.

### 3.11 Plan de ejecución atómico y secuencial (T1–T8 · 3 lotes)

> **8 tareas · 3 lotes** (máx. 3 por lote; cada lote = **UNA sesión NUEVA de `odoo-dev`**, nunca se retoma la
> anterior). El Dev marca `- [x]` SOLO lo hecho y deja su **bitácora** para el lote siguiente.
> **Fuente:** `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: aquí se escribe) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA**, NO se edita).
> **Regla vigente: código sí, datos no.** PROHIBIDO `cr.execute` de escritura y `cr.commit()`.
> **No forzar ni reemplazar flujos nativos; código sí, datos no.**
> Convenciones OCA §2.5 (un archivo por modelo, orden del modelo, `snake_case`, `xml_id` con prefijo
> `printflow_`, nodo raíz `<odoo>`).

#### Lote 1 (T1–T3) — Núcleo: primitiva ADITIVA + orquestador + campo del candidato

- [x] **T1 — `models/stock_move.py`: primitiva ADITIVA `_pf_reassign_lots` (H-037).**
  - Extender el docstring del módulo (hoy documenta H-030) con un 2.º bloque: *"Reparto ADITIVO multi-lote
    (H-037): una liberación + N reservas"* y por qué el camino del motor no era aditivo (`_pf_reassign_lot`
    libera ANTES de reservar).
  - Agregar el método (después del guardián de H-030, sin tocar `_pf_keep_current_lot_reservation` ni
    `_assign_exclusive_lot`):
    `def _pf_reassign_lots(self, lots):`
    1. `self.ensure_one()`; `if not lots or self.product_id.tracking != 'lot': return 0.0`;
    2. **guardián**: `if self.picked or self.state in ('done', 'cancel'): return 0.0` (mismo criterio que el
       filtro de `_pf_unreserve_reservation` del motor: si no se puede liberar, no se apila);
    3. `need = self.product_uom_qty or 0.0`; `if need <= _EPS: return 0.0`;
    4. `self._pf_unreserve_reservation()` — **UNA** vez (primitiva del MOTOR);
    5. `taken = 0.0`; `for lot in lots:` → `remaining = need - taken`; `if remaining <= _EPS: break`;
       `taken += self._pf_reserve_lot(lot, remaining) or 0.0` (primitiva del MOTOR, **ADITIVA**);
    6. `return taken`.
  - Docstring del método: NO borra los lotes ya reservados entre llamadas; el 1.er destino/lote que no tenga
    existencia devuelve `0.0` y el bucle **continúa** con el siguiente lote del plan.
  - **NO** tocar `x_product_dimensional_pricing`; **NO** `cr.execute`/`cr.commit`; **NO** escribir
    `stock.quant`/`stock.move`.
  - **Verificación:** `python -m py_compile models/stock_move.py` OK; en el shell,
    `type(env['stock.move']).mro()` contiene la clase de PrintFlow y `hasattr(env['stock.move'],
    '_pf_reassign_lots')` es `True`; `git diff` de `C:\odoo_custom\x_product_dimensional_pricing` **vacío**.
- [x] **T2 — `wizard/printflow_product_flow.py`: orquestador del reparto (D4).**
  - Constante de módulo `_SPLIT_KINDS = ('missing_move', 'pending_order')` (lista blanca explícita del reparto,
    espejo del alcance de la bandeja; comentario del por qué).
  - Nuevo `@api.model def _pf_assign_lots_to_document(self, target_kind, res_model, res_id, lots, product=None)`:
    1. `self.env['printflow.stock.remedy']._pf_assert_can_clean()`;
    2. `if not lots: raise UserError(_('No se indicaron lotes para el reparto.'))`;
    3. `if (target_kind or '') not in _SPLIT_KINDS: return 0.0`;
    4. resolver el movimiento con un **resolver PRIVADO del reparto** `@api.model _pf_split_target_move(self,
       res_model, res_id, product)` (mismo camino que `_pf_assign_lot_on_pending_order_doc`:
       `res_model == 'stock.move'` ⇒ `browse(res_id).exists()`; `res_model == 'stock.picking'` ⇒
       `search([('picking_id','=',res_id),('product_id','=',product.id),('state','not in',('done','cancel'))],
       limit=1)`; cualquier otro ⇒ recordset vacío);
    5. `if not move: return 0.0`;
    6. `return move._pf_reassign_lots(list(lots))` (**siempre `float`**; `list(...)` para fijar el ORDEN del
       plan sin ambigüedad del ORM).
  - **NO** tocar `_pf_assign_lot_to_document`, `handlers`, `_pf_assign_lot_on_*` ni `_pf_reassign_move_lot`
    (el modo `single` debe quedar **byte a byte**).
  - **Verificación:** `py_compile` OK; `hasattr(env['printflow.product.flow'],
    '_pf_assign_lots_to_document')`; tests de lote existentes sin cambios de resultado.
- [x] **T3 — `wizard/printflow_flow_lot_candidate.py`: campo `is_in_split` (D1).**
  - Agregar `is_in_split = fields.Boolean(string='Incluir', help='Marca ESTE lote para el REPARTO multi-lote
    (botón "Repartir lotes"). A diferencia de "Elegir" (selección ÚNICA), "Incluir" admite VARIAS filas: el
    reparto consume los lotes marcados en el orden de la tabla. Solo se puede marcar si el lote tiene
    Disponible.')` junto a `is_selected` (mismo bloque de campos).
  - **NO** tocar `write`, `_pf_enforce_single_selection`, `_pf_parent`, `_compute_is_picked`,
    `_compute_is_recommended`, `_compute_is_elective`. Extender el docstring del módulo 2 líneas (la fila ahora
    sirve a TRES superficies: selector por documento, modo `single` y modo `split`).
  - **Verificación:** `fields_get('printflow.flow.lot.candidate')` incluye `is_in_split` con `string='Incluir'`;
    `tests/test_product_flow_lot_picker.py` + `..._picker_candidates.py` verdes.

#### Lote 2 (T4–T6) — Contenedor en modo reparto · bandeja · vistas

- [x] **T4 — `wizard/printflow_flow_lot_assign_bulk.py`: MODO reparto (D1/D2/D3/D5).**
  - Campos NUEVOS: `mode = fields.Selection([('single', 'Un lote (el marcado)'), ('split', 'Reparto
    multi-lote')], string='Modo', default='single', readonly=True, help=...)` y
    `split_note = fields.Char(string='Orden del reparto', compute='_compute_split_note', readonly=True, help=...)`.
  - `_compute_split_note` (`@api.depends('candidate_ids.is_in_split', 'candidate_ids.lot_name',
    'candidate_ids.available_here', 'candidate_ids.available', 'total_demand')`): si NO hay marcados ⇒ texto
    guía ("Marca en la tabla los lotes a repartir…"); si hay ⇒ `"1) LOTE → X.XX · 2) LOTE → Y.YY. Total
    disponible: A de B demandadas."` con `_()` y `%.2f` (sin sufijos de unidad). Usar
    `rec.candidate_ids.filtered('is_in_split')` (**el orden del recordset = el de la tabla**, D2).
  - `_pf_populate(self, product, rows, omitted_count=0, mode='single')`: **argumento NUEVO con default** ⇒ los
    llamadores actuales no cambian de comportamiento; agregar `'mode': mode` al `create({...})`. Docstring: el
    modo NO altera destinos ni candidatos, solo el camino de decisión.
  - `_pf_split_lots(self)`: devuelve una **lista ordenada** de `stock.lot` (`[cand.lot_id for cand in
    self.candidate_ids.filtered('is_in_split')]`; ignorar filas sin `lot_id`).
  - `_pf_check_split_coverage(self, lots)` (D3): con `self.location_id` ⇒
    `Σ self.env['stock.quant']._get_available_quantity(self.product_id, self.location_id, lot_id=lot)`;
    sin ubicación ⇒ `Σ candidate.available` de los marcados. `<= _EPS` ⇒ `UserError` guía; `< total_demand`
    sin `confirm_partial` ⇒ `UserError` guía (familia de texto del modo `single`).
  - `_pf_line_breakdown(self, line, lots)` → `(total, note)`: suma `line.move_id.move_line_ids` cuyo `lot_id`
    esté en `lots` (lectura `sudo()`), `note` = `_('Reparto: %s') % ' · '.join('%s → %.2f' % (lot.name, qty))`
    + `_(' (%s lotes sin existencia)') % n` cuando alguno no aportó; sin aportes ⇒
    `_('Ningún lote del reparto quedó reservado.')`. **NO** tocar `_pf_line_reserved` (camino `single`).
  - `_pf_log_split_document(self, line, lots, reserved)` (D5): copia del patrón de `_pf_log_document`
    (**sin tocarlo**), con `message_post` que lista los lotes y el reservado real + el `reason` común.
  - `action_split_lot_bulk(self)` (**MODO reparto**, mismo esqueleto del `single`):
    1. `self.ensure_one()`; `self.env['printflow.stock.remedy']._pf_assert_can_clean()`;
    2. `reason` obligatorio ⇒ `UserError`;
    3. política (`self.env['printflow.flow.lot.picker']._pf_exception_policy()`; si ≠ `'warn'` exige
       `confirm_exception` ⇒ `UserError`);
    4. `lots = self._pf_split_lots()`; si vacío ⇒ `UserError` guía ("Marca en la tabla los lotes que quieres
       repartir (columna 'Incluir')");
    5. `self._pf_check_split_coverage(lots)` (**bloquea ANTES de escribir**);
    6. `ProductFlow = self.env['printflow.product.flow']`;
       `for line in self.line_ids.filtered('assignable'):` → `try: ProductFlow._pf_assign_lots_to_document(
       line.kind, line.res_model, line.res_id, lots, product=self.product_id) except UserError as err:`
       ⇒ `line.result='error'` + `result_note=str(err)`, `continue`; luego `reserved, note =
       self._pf_line_breakdown(line, lots)`; clasificar (`<= _EPS` ⇒ `error`; `< demand` ⇒ `partial` con
       prefijo `_('Solo se reservó lo disponible. ')`; si no ⇒ `assigned`) y `self._pf_log_split_document(...)`;
    7. `result = self.env['printflow.flow.lot.assign.bulk.result']._pf_build_from_bulk(self)` y
       `return self._pf_result_notification(result)` (**mismo cierre y mismos 4 conteos**, D5).
  - **NO** tocar `action_assign_lot_bulk`, `_pf_selected_lot`, `_pf_check_coverage`, `_pf_log_document`,
    `_pf_result_notification` ni `_pf_line_reserved`. Extender el docstring del módulo (dos modos).
  - **Verificación:** `py_compile` OK; `-u printflow_gestion_inventario` sin error; `fields_get` del contenedor
    devuelve `mode` y `split_note`; los candados `test_product_flow_lot_assign_bulk.py`,
    `test_product_flow_lot_assign_bulk_result.py`, `test_product_flow_lot_pending_order_assign.py` siguen
    **verdes** (reportar en bitácora).
- [x] **T5 — `wizard/printflow_flow_lot_tray.py`: acción "Repartir lotes" + helper compartido.**
  - Extraer del cuerpo de `action_assign_lot_bulk` un helper privado `_pf_bulk_rows(self, records)` que devuelve
    `(product, rows, omitted)` **SIN efectos secundarios ni notificaciones** (la construcción de `rows` con
    `_pf_document_move`, el descarte de las que no resuelven y el **dedupe por `move.id`** se mueven tal cual).
  - `action_assign_lot_bulk` **queda con el mismo comportamiento observable** (mismos mensajes de vacío, mismo
    `act_window` a `printflow.flow.lot.assign.bulk`) ⇒ llamar al helper y conservar el resto **idéntico**.
  - Nuevo `action_split_lot_bulk(self)` (**público**: Odoo 17 rechaza privados por RPC):
    1. `self.env['printflow.stock.remedy']._pf_assert_can_clean()`;
    2. `records = self or self.search(self.env.context.get('active_domain') or [])`, `exists()`;
       vacío ⇒ `self._pf_authorize_selected_notification(_('Selecciona al menos una entrega sin lote para
       repartir los lotes.'))`;
    3. candidatas = `records.filtered(lambda rec: rec.can_choose_lot and rec.kind in _BULK_ASSIGNABLE_KINDS and
       rec.product_id)`; ninguna ⇒ notificación guía;
    4. `product, rows, omitted = self._pf_bulk_rows(candidates)`; sin filas ⇒ notificación guía;
    5. `bulk = self.env['printflow.flow.lot.assign.bulk']._pf_populate(product, rows, omitted_count=omitted,
       mode='split')`; si vacío ⇒ notificación;
    6. `return {'type': 'ir.actions.act_window', 'name': _('Repartir lotes en bloque'), 'res_model':
       'printflow.flow.lot.assign.bulk', 'res_id': bulk.id, 'view_mode': 'form', 'views':
       [(self.env.ref('printflow_gestion_inventario.printflow_flow_lot_assign_bulk_view_form_split').id,
       'form')], 'target': 'new'}` (en primer nivel los `views` se normalizan; se pasan explícitos para abrir
       **el form del MODO reparto**).
  - **Verificación:** `py_compile` OK; `hasattr(env['printflow.flow.lot.tray'], 'action_split_lot_bulk')`; los
    candados de bandeja (`test_product_flow_lot_tray*.py`) **verdes** (la extracción del helper no cambia el
    modo `single`).
- [x] **T6 — `wizard/printflow_flow_lot_assign_bulk_views.xml`: form del MODO reparto + microcopy de H-036.**
  - **AGREGAR** `<record id="printflow_flow_lot_assign_bulk_view_form_split" model="ir.ui.view">` (`name` =
    `printflow.flow.lot.assign.bulk.form.split`, `model` = `printflow.flow.lot.assign.bulk`): `<form
    string="Repartir lotes en bloque" create="false" delete="false">` con
    1. campos técnicos ocultos: `mode`, `multi_location`;
    2. `<group string="Selección">` igual que el form `single` (producto, `source_label`, `total_demand`,
       `location_id`, `assignable_count`, `omitted_count`, `selection_note`) — **mismos rótulos** (H-031);
    3. el aviso `alert-warning` de `multi_location` (**sin cambios**);
    4. `<group string="Reparto">` con `split_note` **VISIBLE** (`readonly="1" nolabel="1" colspan="2"`),
       `confirm_partial` y `confirm_exception` + su microcopy (mismo patrón del form `single`);
    5. `<group string="Lotes" col="1">` con `<field name="candidate_ids" nolabel="1">` y un **`<tree>`
       INLINE** (`create="false" delete="false" editable="bottom"`) con las MISMAS decoraciones del tree
       compartido y las columnas: `is_in_split` (`string="Incluir"`, `readonly="not is_elective"`),
       `lot_name`, `qty_on_hand`, `reserved`, `available`, `role_label` (+ los secundarios `available_here`,
       `covers_demand`, `holder_names`, `location_names`, `hint`, `is_recommended` con `optional="hide"`) y los
       de apoyo con `column_invisible="True"` (`is_own_lot`, `is_current_lot`, `is_elective`, `is_occupied`,
       `is_picked`, `lot_id`, `is_authorized`). Texto guía: *"Marca "Incluir" en TODOS los lotes que quieras
       repartir: se consumen en el orden de la tabla (primero el de más disponible) para cubrir las entregas de
       arriba hacia abajo."*
    6. `<group string="Destinos" col="1">` con el **MISMO** tree de `line_ids` del form `single` (readonly);
    7. `<group string="Motivo de la asignación" col="1">` con `reason` **required**;
    8. `<footer>` con `<button name="action_split_lot_bulk" type="object" string="Repartir lotes"
       class="btn-primary" icon="fa-random" title="..."/>` y "Cancelar" (`special="cancel"`).
  - **AGREGAR** al form del modo `single` (mismo archivo) SOLO una frase al `<div class="text-muted">` de la
    ranura "Lotes" (D6/**H-036**): *"La casilla elige **UN** solo lote por corrida (el último marcado queda).
    Para repartir la demanda entre **VARIOS** lotes usa el botón "Repartir lotes" de la bandeja."* —
    **solo se AGREGA texto; no se reemplaza ni se quita nada**.
  - **NO** tocar `__manifest__.py` (el archivo ya está en `data`) ni el tree compartido
    `printflow_flow_lot_candidate_view_tree`.
  - **Verificación:** `-u printflow_gestion_inventario` sin error; el form `split` abre con el plan visible y la
    columna "Incluir"; el form `single` se ve igual + la frase nueva.

#### Lote 3 (T7–T8) — Botón de cabecera + test del reparto

- [x] **T7 — `wizard/printflow_flow_lot_tray_views.xml`: botón "Repartir lotes" (D-A).**
  - En el `<header>` (L28-63), **HERMANO** de "Asignar lote" y con el MISMO `display="selection"`:
    `<button name="action_split_lot_bulk" type="object" string="Repartir lotes" class="btn-secondary"
    icon="fa-random" display="selection" title="Reparte la demanda de las entregas sin lote seleccionadas entre
    VARIOS lotes con existencia (en el orden de la tabla: primero el de más disponible). ESCRIBE inventario por
    la vía NATIVA (reserva ADITIVA). Requiere jefe de taller/administrador"/>`
  - **NO** tocar los botones existentes ni las columnas del tree (H-029/H-031/H-032 intactos).
  - **Verificación:** `-u printflow_gestion_inventario` sin error; con filas seleccionadas en la bandeja aparece
    el botón y abre el form del MODO reparto.
- [x] **T8 — Test del reparto: `tests/test_product_flow_lot_assign_bulk_split.py` (+ `tests/__init__.py`).**
  - **CREAR** el archivo partiendo de la MISMA base/helpers de `tests/test_product_flow_lot_assign_bulk.py`
    (`TransactionCase`; `@tagged('post_install', '-at_install')`; `_product`, `_lot`, `_stock`, `_outgoing`,
    `_open_tray`, `_user`, `_manager`; `PARAM_EXCEPTION_POLICY='warn'` en `setUpClass`) y agregar
    `_wizard_for_split(selection)` (usa `selection.action_split_lot_bulk()` y asertar
    `res_model == 'printflow.flow.lot.assign.bulk'`, `target == 'new'` y que los `views` apuntan a
    `printflow_flow_lot_assign_bulk_view_form_split`).
  - Casos (nombres obligatorios):
    * `test_ca1_split_reserves_all_marked_lots` (**CA-1**): 2 lotes con 1 u cada uno + 1 entrega con demanda 2 u
      (sin reserva) ⇒ marcar `is_in_split=True` en los 2 candidatos, `bulk.action_split_lot_bulk()` ⇒ el
      `stock.move` queda con **2 `move_line`** (lotes distintos), `sum(quantity) == 2.0` y la fila del destino
      `result == 'assigned'`.
    * `test_ca2_multi_tick_is_independent_and_single_selection_kept` (**CA-2**): `write({'is_in_split': True})`
      en 2 candidatos ⇒ los 2 quedan `True`; `write({'is_selected': True})` en 2 ⇒ **solo 1** se queda marcado
      (contraste con H-036).
    * `test_ca3_partial_requires_confirmation` (**CA-3**): demanda 3 u con lotes de 1+1 u ⇒ sin
      `confirm_partial` lanza `UserError` y el movimiento queda **sin** `move_line`; con `confirm_partial=True`
      ⇒ 2 u repartidas entre los 2 lotes, fila `partial` y `result_note` con los **nombres de los 2 lotes**.
    * `test_ca4_declared_order_biggest_lot_first` (**CA-4**): lotes de 1 u y 3 u con demanda 2 u ⇒ el
      `split_note` empieza por el lote de 3 u y la reserva consume primero ese lote.
    * `test_ca5_report_and_detail_are_kept` (**CA-5**): el retorno sigue siendo `display_notification` con los
      **mismos 4 conteos** y `params['next']['res_model'] == 'printflow.flow.lot.assign.bulk.result'`; el
      detalle trae **una fila por destino** y las filas `error`/`skipped` con `result_note` NO vacío.
    * `test_ca6_guardian_reason_and_policy` (**CA-6**): usuario sin jefe de taller ⇒ `UserError` al ejecutar;
      sin `reason` ⇒ `UserError`; política ≠ `warn` sin `confirm_exception` ⇒ `UserError`.
    * `test_ca8_does_not_stack_on_picked_move` (**CA-8**): movimiento `picked`/`done` ⇒ `result == 'error'` y
      `result_note` con motivo, **sin** tocar sus `move_line`.
    * Candado: el archivo NO contiene `cr.execute(` ni `cr.commit(`.
  - `tests/__init__.py`: registrar `from . import test_product_flow_lot_assign_bulk_split` al final del bloque de
    lote (junto a `test_product_flow_lot_assign_bulk_result`), con comentario del motivo (H-037/H-036).
  - **Verificación:** el archivo nuevo pasa **en verde**; además verdes:
    `test_product_flow_lot_assign_bulk.py`, `test_product_flow_lot_assign_bulk_result.py`,
    `test_product_flow_lot_pending_order_assign.py`, `test_product_flow_lot_tray.py`,
    `test_product_flow_lot_tray_orders.py`, `test_product_flow_lot_tray_document.py`,
    `test_product_flow_lot_tray_authorize.py`, `test_product_flow_lot_picker.py`,
    `test_product_flow_lot_picker_candidates.py`, `test_product_flow_lot_picker_ux.py`,
    `test_product_flow_lot_coupled_chain.py`, `test_lot_management.py`,
    `test_pf_bulk_validate_preserves_lot.py` y `test_product_flow_over_reservation_scoped.py`.
    **Regresión real, no decorativa:** el test de CA-1 DEBE fallar si se revierte T1 (sin la reserva aditiva el
    2.º lote pisa al 1.º) — el Dev lo comprueba y lo deja escrito en su bitácora.

**Verificación (turno del Verificador, fuera del dev).** `--test-tags` sobre
`/printflow_gestion_inventario:TestProductFlowLotAssignBulkSplit` (nuevo) y, sin regresión,
`/printflow_gestion_inventario:TestProductFlowLotAssignBulk`,
`...:TestProductFlowLotAssignBulkResult`, `...:TestProductFlowLotPendingOrderAssign`,
`...:TestProductFlowLotTray`, `...:TestProductFlowLotTrayOrders`, `...:TestProductFlowLotTrayDocument`,
`...:TestProductFlowLotTrayAuthorize`, `...:TestProductFlowLotPicker`, `...:TestProductFlowLotPickerUX`,
`...:TestProductFlowLotCoupledChain`, `...:TestLotManagement`, `...:TestPfBulkValidatePreservesLot` y
`...:TestProductFlowOverReservationScoped`. Al hilo solo vuelve el exit code, N/N y, si falla, la aserción + cola
del traceback. **Los 8 rojos de B1 NO cuentan como fallo de esta tarea**, pero el Dev **reporta** si su delta
cambió por T1/T2 (O-5).

### 3.12 Pendiente del dueño

1. **Recargar el módulo** (`-u printflow_gestion_inventario`) en el servidor 8071.
2. **Probar el camino nuevo (código):** en la bandeja de `IMPRESION BANNER ` seleccionar las entregas sin lote,
   pulsar **"Repartir lotes"**, marcar **"Incluir"** en varios lotes con existencia (p. ej. `666634` de 23 u
   **más** los de 1 u) y confirmar con un motivo. Debe quedar todo reservado **de una sola pasada**, sin perder
   ningún lote, con el detalle por destino.
3. **Datos (lo ejecuta el dueño, no el agente):** la asignación real de lotes a las 26 entregas del banner
   (**H-018**) y la de las reservas sin lote (**H-035**); **no** teclear cantidades a mano.
4. **Decidir** si **H-034** (un solo MOVIMIENTO por albarán) se abre como tarea propia: aquí queda **FUERA**
   (D-B / O-1).

---
## 3.M (ANEXO · TAREA CERRADA) — Regresión de la ventana de detalle del bloque (H-032 · H-033)

> **Turno:** Odoo Analista (APERTURA de la regresión; paso 1). **Estado:** **contrato redactado, listo para
> `odoo-dev`** (UN lote: T1–T3). Tarea **NORMAL** (2 archivos de código + 1 de test, SIN diseño de flujo:
> se toca el cableado de una ACCIÓN, no el flujo de inventario).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: aquí van los 3 archivos) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA — no se edita**).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`).
> **Hallazgos que ataca:** **H-032** (regresión de H-029/H-030/H-031) · **H-033** (mismo defecto latente
> en un archivo hermano, descubierto al auditar el precedente).

### 3.1 Problema (evidencia)

El dueño abre la bandeja, selecciona entregas, pulsa **"Asignar lote"** (wizard
`printflow.flow.lot.assign.bulk`) y ejecuta. El navegador revienta:

```
UncaughtPromiseError > TypeError
Cannot read properties of undefined (reading 'map')
  at _preprocessAction (web.assets_web.min.js:10274:73)
  at doAction (…:10354:170)  →  doActionButton (…:10362:196)
```

**Causa raíz (verificada en el código de Odoo 17 y en el nuestro).** `_preprocessAction`
(`addons/web/static/src/webclient/actions/action_service.js`) hace, para **TODA** acción
`ir.actions.act_window`:

```js
action.views = [...action.views.map((v) => [v[0], v[1] === "tree" ? "list" : v[1]])];
```

⇒ si `views` viene `undefined`, revienta con **ese** mensaje. Y aquí está el detalle que importa:

- El servidor Odoo **normaliza/agrega `views` SOLO a la acción de PRIMER nivel** que devuelve un botón.
- Las acciones **ANIDADAS** dentro de `params['next']` de un `display_notification` **NO** se normalizan.

La **T6** del ciclo anterior (H-029) puso la ventana de detalle dentro de `params['next']`
**sin `views`** ⇒ crash al abrirla.

**Prueba de que el primer nivel SÍ se normaliza:** el camino DIRECTO del motor
(`_pf_bulk_build_result_wizard`) devuelve el **mismo dict sin `views`** y **funciona** — el dueño alcanzó a
ver las 28 filas del `printflow.delivery.bulk.result` id **158** — porque ahí la acción es de **primer nivel**.

| # | Sub-problema | Hallazgo | Evidencia |
|---|---|---|---|
| **P1** | La acción `act_window` anidada en `params['next']` va **sin `views`**. | **H-032** | `wizard/printflow_flow_lot_assign_bulk.py` L546-555 (dict `nxt`, sin `views`) y L571 (`'next': nxt`) · `action_service.js::_preprocessAction` (`action.views.map`) · error del navegador (arriba) · contraste: `x_product_dimensional_pricing/models/printflow_stock_picking_bulk.py` L129-136 (mismo dict, primer nivel ⇒ funciona) |
| **P2** | **MISMO defecto** en el precedente que se copió, en su rama `others`. | **H-033** | `models/printflow_node_pending_line.py` L216-234 (`'next': result`) · `x_product_dimensional_pricing/models/printflow_stock_picking_bulk.py` L124-136 (`_pf_bulk_build_result_wizard`, sin `views`) |

**Impacto:** el operador NO ve el detalle del motivo (**H-029 vuelve a quedar invisible**) y encima ve un
error de JS. La asignación en sí **SÍ se ejecutó** (la escritura es server-side): lo que falla es solo la
apertura del detalle.

### 3.2 Objetivo

**SÍ:** que la ventana de detalle del bloque **abra sin crash** (P1) y que el precedente hermano **no
reviente** en su rama `others` (P2).
**NO:** cambiar la lógica de conteo ni el flujo de reserva/validación; NO tocar el motor; NO tocar datos.

### 3.3 Contrato funcional (qué debe quedar)

| Superficie | Debe quedar |
|---|---|
| Acción anidada del detalle (H-032) | Incluye `'views': [(False, 'form')]`; conserva `type='ir.actions.act_window'`, `name`, `res_model`, `res_id`, `view_mode='form'`, `target='new'`. |
| Precedente `action_pf_validate_selected` (H-033) | Su rama `others` también entrega `'views': [(False, 'form')]`. |
| Texto de cierre (CA-7) | **Intacto** (los 4 conteos, igual). |

> **Por qué `[(False, 'form')]` y no el dict cargado de la BD:** es la MISMA convención que el core de Odoo
> usa al normalizar acciones de primer nivel (`[[False, 'form']]`), es una sola línea y no crea
> dependencia con un xmlid inexistente. `False` como id = "carga la vista por defecto del modelo".

### 3.4 Restricciones duras

1. **Código sí, datos no** (`regla-trabajo-odoo-17-ce`).
2. Solo se editan estos 3 archivos: `wizard/printflow_flow_lot_assign_bulk.py`,
   `models/printflow_node_pending_line.py`, `tests/test_product_flow_lot_assign_bulk_result.py`.
   El motor `x_product_dimensional_pricing` **NO se edita** (solo lectura).
3. **Cero cambio de lógica:** nada de tocar conteos, `result_note`, `state`, `quantity`, `_action_assign`
   ni el motor. PROHIBIDO `cr.execute` de escritura y `cr.commit()`.
4. **No forzar ni reemplazar flujos nativos.**
5. Convenciones OCA (`odoo-17-clean-architecture` §2.5).

### 3.5 Plan (T1–T3 · UN lote)

- [x] **T1 — `wizard/printflow_flow_lot_assign_bulk.py` (H-032).** En `_pf_result_notification`, agregar
  `'views': [(False, 'form')]` al dict `nxt` que se pasa en `params['next']` (L546-555). Nada más.
- [x] **T2 — `models/printflow_node_pending_line.py` (H-033).** En `action_pf_validate_selected`, rama
  `others` (L221-233), agregar `'views': [(False, 'form')]` a la acción anidada en `'next'`.
- [x] **T3 — `tests/test_product_flow_lot_assign_bulk_result.py`.** Añadir/extender un caso que fije
  **CA-1**: `params['next']['views'] == [(False, 'form')]` (y sigue el `res_model`/`res_id`).

### 3.6 Criterios de aceptación

- **CA-1:** `action_assign_lot_bulk()` devuelve `params['next']['views'] == [(False, 'form')]` (test).
- **CA-2:** `TestProductFlowLotAssignBulkResult` (T9 del ciclo anterior) sigue **verde**; `TestProductFlowLotAssignBulk` sigue **verde**.
- **CA-3:** cero regresión: motor intacto, sin SQL crudo, sin tocar `stock.*` en escritura.
- **CA-4:** `python -m py_compile` OK en los 2 archivos de código.

### 3.7 Pendiente del dueño

**Recargar el módulo** (`-u printflow_gestion_inventario`) en el servidor 8071 y volver a pulsar
**"Asignar lote"**: debe abrir el detalle **sin error** y mostrar el motivo por entrega.

---

## 3.L (ANEXO · TAREA CERRADA) — Incidencias del wizard de asignación en bloque y del "validar entregas en lote" (H-029 · H-030 · H-031)

> **Turno:** Odoo Analista (APERTURA de la incidencia; cierra el paso 1 → pasa al **paso 2: `odoo-planificador`**).
> **Estado:** **contrato redactado, SIN plan todavía**. Tarea **GRANDE** (toca el flujo NATIVO de
> reserva/validación de entregas ⇒ SIEMPRE Grande).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: el wizard vive aquí) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor del "validar entregas en lote"; **SOLO LECTURA**,
> se hereda/extiende desde PrintFlow).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`).
> **Cadena:** Analista → Planificador → Analista → Dev (por lotes, máx. 3) → Verificador → Analista.
> **Hallazgos que ataca:** **H-029** · **H-030** · **H-031** — los TRES viven en el MISMO flujo de
> asignación/validación en bloque de entregas.

### 3.1 Problema (evidencia en la BD y en el código)

**Caso real (BD `Ciber Estudios 2015 RESTAURADA`, 17/10):** el dueño corrió la asignación en bloque
(`printflow.flow.lot.assign.bulk` id **1**, 27 destinos, demanda **33 u**) eligiendo el lote **`8763`**
(id 2891) — un lote **VACÍO** (`product_qty = 0`; solo tenía 3 u y se las llevó la entrega más antigua
WH/OUT/02988). Resultado real: **1 asignada · 26 con error** y el wizard cerró **sin decir POR QUÉ**
(**H-029**). Después, el "validar entregas en lote" del motor omitió **28/28** (**H-030**), y en la
segunda pasada el dueño leyó, confundido, **"Asignables 26 / Demanda total 30"** (**H-031**).

| # | Sub-problema | Hallazgo | Evidencia |
|---|---|---|---|
| **P1** | El motivo del fallo **por destino** SÍ se calcula y SÍ se guarda, pero **NO se muestra**: la acción termina en `display_notification` con 4 conteos y `act_window_close`. | H-029 | `wizard/printflow_flow_lot_assign_bulk.py` L438-461 (`line.result_note = str(err)`) y L497-524 (`_pf_result_notification` → `'next': act_window_close`) · BD: `...assign.bulk` id **1** + 27 líneas con `result_note` (26 = *"El lote "8763" no tiene existencia disponible…"*) |
| **P2** | El "validar entregas en lote" hace `picking.action_assign()` **ANTES** de validar; en producto de **entrega exclusiva por lote** ese `action_assign` **des-reserva la excepción** (libera el lote asignado a mano) ⇒ `state != 'assigned'` ⇒ `_PfBulkSkip` ⇒ **28/28 omitidas** con *"Sin stock reservado"*. | H-030 | `x_product_dimensional_pricing/models/printflow_stock_picking_bulk.py` L72-96 (L74 `action_assign`, L75-78 el skip) · override `stock_move.py` L57-89, L194-217 · BD: `printflow.delivery.bulk.result` id **158** (28 líneas `skipped`) |
| **P3** | Los rótulos **no declaran su unidad**: **"Asignables" = 26** son **FILAS/ENTREGAS** y **"Demanda total" = 30** son **UNIDADES**; nada dice que cada fila es un **albarán de ENTREGA** (el dueño lo leyó como "la OC"). | H-031 | `wizard/printflow_flow_lot_assign_bulk_views.xml` L39 (`total_demand`), L43 (`assignable_count`) · `wizard/printflow_flow_lot_assign_bulk.py` L78-82, L117-119, L132-135 |

### 3.2 Objetivo (acotado)

**SÍ:**
1. **P1 (H-029):** que el operador **VE A el motivo por destino** al terminar la asignación en bloque,
   sin perder el cierre de la bandeja ni los 4 conteos.
2. **P2 (H-030):** que "validar entregas en lote" **NO des-reserve** la reserva por excepción ya
   existente; que valide lo que de verdad está reservado, o que **omita con motivo HONESTO** en vez de
   `"Sin stock reservado"`.
3. **P3 (H-031) — RÓTULOS YA DECIDIDOS CON EL DUEÑO:** `Asignables` → **"Entregas por asignar"**;
   `Demanda total` → **"Unidades a entregar"**; `Filas omitidas` → **"Entregas omitidas"**; + **texto
   aclaratorio VISIBLE** bajo "Selección": *"Cada fila es una entrega (albarán de salida). N entregas = M unidades."*

**NO:**
- NO cambiar la **lógica de cálculo**: 26 y 30 son **CORRECTOS** (26 filas = 22×1 u + 4×2 u = 30 u).
  Solo rótulos y texto.
- NO tocar el motor `x_product_dimensional_pricing` a mano: se **hereda/extiende con `_inherit` + `super()`**
  desde PrintFlow (cambio directo en el motor ⇒ **solo con autorización del dueño**).
- NO forzar flujos nativos: prohibido `cr.execute` de escritura, `cr.commit()`, escribir
  `stock.quant`/`stock.move` a mano, forzar `state`/`quantity`.
- NO resolver por DATOS el caso del dueño (asignar lotes a las 26 entregas = **H-018**; lo ejecuta él).
- NO romper: selector por documento, bandeja clásica, autorización en bloque, ni el dedupe FIFO.

### 3.3 Contrato funcional

| Superficie | Debe quedar |
|---|---|
| Fin de `action_assign_lot_bulk` | Conserva los **4 conteos** y ADEMÁS deja **visible el motivo por destino** (los destinos `error`/`partial` con su `result_note`, p. ej. vía un wizard de detalle o en la propia notificación). La bandeja **se sigue cerrando**. |
| "Validar entregas en lote" | Un albarán que **YA tiene reserva con lote** (excepción del operador) **NO se des-reserva**: se valida, o se omite con el **motivo REAL**. El savepoint por albarán se mantiene. |
| Ranura "Selección" del wizard | **"Entregas por asignar"** = 26 · **"Unidades a entregar"** = 30 · **"Entregas omitidas"** = 0 + **texto aclaratorio visible**. |
| Motor `x_product_dimensional_pricing` | **SIN CAMBIOS** (se hereda/extiende desde PrintFlow); cambio directo ⇒ autorización del dueño. |

### 3.4 Fuente ÚNICA / patrones a reutilizar (cero reinvención)

- **Patrón "resultado con detalle por documento" (para H-029):** el wizard de resultado del bulk-validate
  del motor (`printflow.delivery.bulk.result` + su `_views.xml`) YA pinta **una fila por albarán con
  `status` y `reason`** (`printflow_stock_picking_bulk.py` L104-106 y `_pf_bulk_build_result_wizard`).
  Es el patrón a copiar/portar a PrintFlow.
- **Modelo de línea que YA guarda el detalle:** `printflow.flow.lot.assign.bulk.line`
  (`result`, `result_note`) — de la tarea del anexo **3.K**. Solo falta **pintarlo**.
- **Guardia de permisos:** `printflow.stock.remedy._pf_assert_can_clean()`.
- **Política/motivo:** `printflow.flow.lot.picker._pf_exception_policy` (ya integrado).
- **Nativo de reserva (SOLO lectura, para entender el des-reserve):**
  `stock.move._pf_unreserve_reservation` / `_pf_reassign_lot` / `_is_exclusive_delivery`.

### 3.5 Decisiones de diseño cerradas (D1–D7)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` · Rutas:
> `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow: aquí viven el wizard del bloque y la bandeja) ·
> `C:\odoo_custom\x_product_dimensional_pricing` (motor del "validar entregas en lote"; **SOLO LECTURA**, NO se edita).
> Regla vigente: **código sí, datos no**. El diseño **ENGANCHA** los flujos existentes (`_inherit` + `super()`) y
> **NO reemplaza ni fuerza ningún flujo nativo**: la ÚNICA escritura sigue siendo la de hoy (la reasignación NATIVA
> de reserva del remedio por documento) y la validación de albaranes que **dispara el operador**.
> **Trazabilidad de obstáculos:** **O-1 → D2** · **O-2 → D1** · **O-3 → D3**.

**D1 — H-029: DÓNDE y CÓMO se ve el motivo por destino (CERRADA · wizard de DETALLE, patrón del motor).**
- Se **PORTA a PrintFlow** el patrón del motor `printflow.delivery.bulk.result` (+ su línea y su vista): se crean
  `printflow.flow.lot.assign.bulk.result` (TransientModel con `line_ids` y los 4 conteos computados) y
  `printflow.flow.lot.assign.bulk.result.line` (`seq` · `label` · `kind` · `demand_qty` · `result` · `result_note`).
- `printflow.flow.lot.assign.bulk.action_assign_lot_bulk` **CONSERVA la notificación** con los 4 conteos y le
  **encadena** el detalle con `params['next']` = `ir.actions.act_window` (`target='new'`) al wizard de resultado.
  **Precedente EXACTO ya en uso en PrintFlow** (`models/printflow_node_pending_line.py::action_pf_validate_selected`,
  L221-233: notificación + `next` = ventana de resultado) ⇒ **cero reinvención** del mecanismo de encadenado.
- **Por qué NO volcar los motivos en la notificación:** la notificación no se desplaza, se trunca y desaparece; con
  26+ motivos el operador no los puede leer — que es EXACTAMENTE la queja **H-029**. El detalle es una ventana de
  SOLO LECTURA, persistente y desplazable, con **una fila por destino** (incluidas las OMITIDAS y las que no son
  asignables) y su `result_note` completo.
- **Por qué NO se rompe el cierre:** la notificación sigue siendo el retorno del botón (mismos 4 conteos, mismo
  texto) y su `next` **ABRE** el detalle; al cerrar el detalle se vuelve a la bandeja de origen — el mismo
  comportamiento de hoy (el modal del bloque se cierra y la bandeja queda como estaba; al reabrirla, las órdenes
  resueltas ya no se listan, CA-8). El detalle **no escribe nada**: solo lee `bulk.line_ids`.

**D2 — H-030: DÓNDE se corrige el des-reserve (CERRADA · override ADITIVO del seam `_assign_exclusive_lot`).**
- **Causa exacta (verificada en el fuente INSTALADO de Odoo 17, no de memoria):** el NATIVO
  `addons/stock/models/stock_move.py::_action_assign` (L1650-1664) **filtra** los movimientos que ya están
  reservados (`moves_to_assign.filtered(lambda m: not m.picked and m.state in ['confirmed','waiting','partially_available'])`
  y luego `if missing <= 0: assigned_moves_ids.add(move.id); continue`) ⇒ **un movimiento ya reservado NO se
  re-asigna y su reserva se respeta**. El motor `x_product_dimensional_pricing/models/stock_move.py::_action_assign`
  (L206-217) intercepta y, para los movimientos de **entrega EXCLUSIVA por lote** (`_is_exclusive_delivery()`),
  llama **SIEMPRE** a `_assign_exclusive_lot()` **sin ese filtro** ⇒ `_pf_reassign_lot()` **LIBERA** la reserva
  actual (`_pf_unreserve_reservation`) y reserva el **lote exclusivo del pedido** (`S…-Lyyy`) que está **VACÍO**
  ⇒ reserva 0 ⇒ el albarán pierde la excepción de lote, queda `state != 'assigned'` y el motor del bulk lo OMITE
  con *"Sin stock reservado."* (BD: `printflow.delivery.bulk.result` id **158**, 28/28 `skipped`).
- **DÓNDE:** PrintFlow **hereda** `stock.move` (**CREAR** `models/stock_move.py`, `_inherit = 'stock.move'`) y
  **sobrescribe el seam** `_assign_exclusive_lot()` con `super()` + un guardián de PRESERVACIÓN:

  ```python
  def _assign_exclusive_lot(self):
      if self._pf_keep_current_lot_reservation():
          self._recompute_state()
          return True                      # se CONSERVA la reserva del operador
      return super()._assign_exclusive_lot()   # motor INTACTO (comportamiento actual)
  ```
  El guardián `_pf_keep_current_lot_reservation()` (`ensure_one`) devuelve `True` SOLO si:
  1. `product_id.tracking == 'lot'`; **y**
  2. el movimiento **YA reserva un lote** (existe línea activa con `lot_id`, `not picked`, `quantity > _EPS`); **y**
  3. `_get_exclusive_delivery_lot()` devuelve un lote **que existe pero NO tiene disponible** en la ubicación del
     movimiento (`env['stock.quant']._get_available_quantity(product, move.location_id, lot_id=lot) <= _EPS`).
  En cualquier otro caso ⇒ `super()`. **Espeja la regla del propio core** ("si ya está reservado, no se toca"):
  no se inventa una regla nueva, solo se le aplica a la rama EXCLUSIVA del motor la regla que el nativo ya aplica.
- **Por qué ahí y no en el motor:** es el **seam MÁS PEQUEÑO** que arregla el caso: toca **solo** el camino
  exclusivo por lote. **NO** se reimplementa `_action_assign`, ni `button_validate`, ni
  `printflow_stock_picking_bulk.py` (el motor queda **INTACTO** ⇒ **sin autorización del dueño**).
- **Demostración de "flujo nativo intacto":** (a) **sin** reserva previa ⇒ `super()` (comportamiento del motor sin
  cambios); (b) con el **lote exclusivo CON existencia** ⇒ `super()` (el motor sigue re-alineando al lote
  exclusivo: no se altera la regla de negocio del lote exclusivo por pedido); (c) producto **NO** exclusivo ⇒ el
  motor ni entra aquí (rama `normal` → FIFO NATIVO); (d) el lote exclusivo **NO existe** ⇒ el motor ya retorna
  temprano sin tocar nada (no hace falta el guardián). El ÚNICO caso que cambia es la **excepción del operador**,
  que es el objetivo declarado. **CA-1/CA-2 lo fijan (T8).**
- **El razón-texto `"Sin stock reservado."` del motor NO se toca:** con este arreglo, un albarán **CON** reserva ya
  no cae en el skip (se valida ⇒ `done`), y para un albarán **sin** reserva ni existencia el texto es **HONESTO**
  (no hay reserva). Así se cumple "valida lo reservado **o** omite con motivo honesto" **sin** tocar el motor.

**D3 — H-031: rótulos y texto aclaratorio (CERRADA · ya decidido con el dueño).**
- Strings: `total_demand` → **"Unidades a entregar"**; `assignable_count` → **"Entregas por asignar"**;
  `omitted_count` → **"Entregas omitidas"** (se corrige TAMBIÉN el `string="Filas omitidas"` que hoy fuerza la VISTA).
- **Campo NUEVO computado** `selection_note` (Char, readonly) con el texto **VISIBLE**: *"Cada fila es una entrega
  (albarán de salida). N entregas por asignar = M unidades a entregar."* (N = `assignable_count`, M = `total_demand`;
  todo por `_()` ⇒ traducible). Se pinta en la ranura **"Selección"**, como texto visible (NO en un tooltip).
- `total_demand` **CONSERVA** `digits='Product Unit of Measure'`; **NO** se inventan sufijos de unidad (la palabra
  "unidades" va en la oración, como decidió el dueño). **NO** se toca la lógica de cálculo: 26 filas = 22×1 u + 4×2 u
  = 30 u es CORRECTO.

**D4 — Alcance de la acción en bloque (CERRADA · SIN cambios respecto al anexo 3.K).**
- Sigue siendo SOLO `missing_move` + `pending_order` (entregas sin lote). Se OMITEN y se REPORTAN: `unassigned_mo`,
  `orphan_quant`, `no_stock_lot`, `generic_lot`, `mixed_lot`, las filas con `can_choose_lot = False` y las que no
  resuelven movimiento. La acción sobre la SELECCIÓN, el handler `pending_order`, el dedupe por `stock.move.id`, el
  orden FIFO, la guardia `_pf_assert_can_clean`, el `reason` obligatorio y la política
  (`pf_lot_assign_exception_policy`) **NO se tocan**.

**D5 — Un solo escritor (CERRADA).**
- La ÚNICA escritura sigue siendo `printflow.product.flow._pf_assign_lot_to_document` →
  `_pf_reassign_move_lot` → `stock.move._pf_reassign_lot` (protocolo NATIVO del motor). El detalle de H-029
  (solo lectura) y el guardián de H-030 (preserva, no escribe) **NO abren** caminos de escritura nuevos.
  PROHIBIDO: `unlink()`+`create()` a mano, `cr.execute` de escritura, `cr.commit()`, forzar `state`/`quantity`/
  `qty_done`, `button_validate` por detrás.

**D6 — Infraestructura nueva (CERRADA).**
- 2 TransientModel nuevos (resultado + su línea) ⇒ **2 filas** `base.group_user,1,1,1,1` en
  `security/ir.model.access.csv`, y **1 vista** nueva en `__manifest__.py` (DESPUÉS de la del wizard del bloque,
  que define el tree de candidato que se REUTILIZA y NO se toca).
- El override de `stock.move` **NO** es modelo nuevo (es `_inherit`) ⇒ **sin fila de ACL**; se carga por
  `models/__init__.py`.

**D7 — Impacto en tests/candados (CERRADA · verificado por lectura de las aserciones reales).**
- **Siguen VERDES y no se tocan:** `test_product_flow_lot_assign_bulk.py` (CA-7: el retorno sigue siendo
  `display_notification` con el **MISMO** texto de los 4 conteos; solo se le agrega `next`),
  `test_product_flow_lot_pending_order_assign.py`, `test_product_flow_lot_picker*.py`,
  `test_product_flow_lot_tray*`, `test_product_flow_lot_coupled_chain.py`,
  `test_product_flow_over_reservation_scoped.py` (3.J: el guardián de D2 **refuerza** "no des-asignar la entrega
  sana"), `test_lot_management.py`, `test_flow_canvas_parity.py`, `test_product_flow_payload_parity.py`
  (no hay claves nuevas de payload: todo es wizard/vista).
- **A VIGILAR (baseline ajeno B1):** `tests/test_diagnostic_delivery_orders.py` y
  `tests/test_pending_native_validate.py` del motor usan `action_pf_bulk_validate_deliveries`. El Dev los corre y
  **reporta el DELTA** en su bitácora; si el delta es consecuencia DIRECTA del arreglo (más `done`, menos
  `skipped` con reserva), se documenta y se deja el listón al Verificador. **B1 no se persigue.**
- **CREAR 2 tests nuevos** (H-030 y H-029/H-031) y registrarlos en `tests/__init__.py`.
  **NINGÚN** candado existente se modifica.

### 3.6 Archivos (confirmados por el Planificador)

**NUEVOS**
- `wizard/printflow_flow_lot_assign_bulk_result_line.py` — línea del detalle (`printflow.flow.lot.assign.bulk.result.line`). (T1)
- `wizard/printflow_flow_lot_assign_bulk_result.py` — cabecera del detalle (`printflow.flow.lot.assign.bulk.result`) + `_pf_build_from_bulk`. (T2)
- `wizard/printflow_flow_lot_assign_bulk_result_views.xml` — form readonly del detalle. (T5)
- `models/stock_move.py` — `_inherit='stock.move'` + guardián + `_assign_exclusive_lot` (H-030). (T7)
- `tests/test_pf_bulk_validate_preserves_lot.py` — H-030 (T8).
- `tests/test_product_flow_lot_assign_bulk_result.py` — H-029/H-031 (T9).

**MODIFICADOS**
- `wizard/printflow_flow_lot_assign_bulk.py` — H-031 (strings de los 3 campos + `selection_note`) y H-029
  (`action_assign_lot_bulk` encadena el detalle; `_pf_result_notification` acepta el resultado). (T4/T6)
- `wizard/printflow_flow_lot_assign_bulk_views.xml` — H-031 (rótulos + `selection_note` VISIBLE; quitar el
  `string="Filas omitidas"`). (T5)
- `wizard/__init__.py` — 2 imports (línea → cabecera), DESPUÉS de `printflow_flow_lot_assign_bulk`. (T3)
- `security/ir.model.access.csv` — 2 filas `base.group_user,1,1,1,1`. (T3)
- `__manifest__.py` — la vista del detalle en `data`, DESPUÉS de `printflow_flow_lot_assign_bulk_views.xml`. (T5)
- `models/__init__.py` — importar `stock_move` (sección de extensiones del motor heredadas). (T7)
- `tests/__init__.py` — registro de los 2 tests nuevos. (T8/T9)

**NO SE TOCA (solo se consume o se hereda):** el motor `x_product_dimensional_pricing`
(`printflow_stock_picking_bulk.py`, `stock_move.py` y `stock_picking.py` quedan **INTACTOS**);
`wizard/printflow_flow_lot_candidate.py` (+ su tree); `wizard/printflow_flow_lot_picker*`;
`wizard/printflow_flow_lot_tray.py` (`action_assign_lot_bulk` que ABRE el bloque, `_pf_document_move`,
`_pf_rows_*`) y su vista; `wizard/printflow_product_flow.py` (`_pf_assign_lot_to_document`,
`_pf_reassign_move_lot`, mapa `handlers`); `models/printflow_flow_lots.py` (`_pf_available_lots`);
`models/printflow_node_pending_line.py` (solo CONSUME el bulk del motor).

### 3.7 Restricciones duras

1. **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): el Dev **NO** toca registros de la BD; solo código.
2. **No forzar ni reemplazar flujos nativos.** Ninguna escritura nueva por fuera de los remedios EXISTENTES; el
   "validar entregas en lote" es un flujo de Odoo que el **operador** dispara. Prohibido `cr.execute` de escritura,
   `cr.commit()`, escribir `stock.quant`/`stock.move` a mano y forzar `state`/`quantity`/`qty_done`.
3. **`_inherit` + `super()`** para extender el motor desde PrintFlow; **`x_product_dimensional_pricing` NO se
   edita** (queda **SIN CAMBIOS** ⇒ sin autorización del dueño).
4. **Cero hardcodeo:** todo texto por `_()`; lo configurable por `ir.config_parameter`.
5. **Convenciones OCA** (`odoo-17-clean-architecture` §2.5): un archivo por modelo, `__init__` por archivo, orden
   del modelo (atributos → campos → constraints → default → compute → onchange → CRUD → acciones → negocio),
   `snake_case`, campos `*_id`/`*_ids` y `xml_id` con prefijo `printflow_`.
6. **Un solo escritor:** no abrir un segundo camino de escritura de lote.
7. **Ya reservado ⇒ no se toca:** el guardián de H-030 **solo PRESERVA**; nunca reserva, nunca suelta y nunca deja
   el inventario peor de lo que estaba.

### 3.8 Criterios de aceptación verificables

| # | Criterio | Verificación |
|---|---|---|
| **CA-1** (**H-030**) | Un albarán de entrega con **reserva de lote EXCEPTUADA** por el operador, procesado por "validar entregas en lote", **NO pierde su lote**: ningún `action_assign()` intermedio lo des-reserva. | Test T8: tras `picking.action_assign()` el movimiento **sigue** reservando el lote elegido y el albarán queda `assigned`. |
| **CA-2** (**H-030**) | Ese albarán **se valida** (`done`) y **ya NO** reporta *"Sin stock reservado."* habiendo reserva. Un albarán **sin** reserva ni existencia **sí** se omite con *"Sin stock reservado."* (motivo HONESTO). | Test T8: `action_pf_bulk_validate_deliveries` → fila `result='done'` y `picking.state='done'`; segunda entrega sin reserva → `skipped` + motivo. |
| **CA-3** (**H-029**) | Tras una asignación en bloque con errores/omisiones, el operador **LEE el motivo por destino** (una fila por destino, con `result` y `result_note`), sin perder la notificación de los 4 conteos ni el cierre del modal. | Test T9: la acción devuelve `display_notification` (4 conteos) con `params['next']` = `act_window` a `printflow.flow.lot.assign.bulk.result`; el detalle trae **una fila por destino** (incluidas omitidas) y `result_note` NO vacío en `error`/`skipped`. |
| **CA-4** (**H-031**) | La ranura "Selección" dice **"Entregas por asignar"** / **"Unidades a entregar"** / **"Entregas omitidas"** y el **texto aclaratorio es VISIBLE** (sin abrir el tooltip): *"Cada fila es una entrega (albarán de salida). N entregas por asignar = M unidades a entregar."* | Test T9: `fields_get('printflow.flow.lot.assign.bulk')` devuelve los 3 strings nuevos; `selection_note` contiene "entrega" y las cifras N/M; `total_demand` conserva `digits='Product Unit of Measure'`. |
| **CA-5** (no regresión) | Las entregas **SIN** excepción conservan el flujo NATIVO: sin reserva previa ⇒ motor sin cambios; con el **lote exclusivo CON existencia** ⇒ reserva el lote exclusivo. Selector por documento, bandeja clásica, autorización en bloque, dedupe FIFO y `_pf_available_lots` **intactos**. Motor `x_product_dimensional_pricing` **SIN CAMBIOS**. | Tests T8 (CA-5) + los candados citados en D7; motor intacto (solo se hereda). Los 8 rojos de **B1** son PRE-EXISTENTES y ajenos. |

### 3.9 Riesgos

| # | Riesgo | Impacto | Mitigación |
|---|---|---|---|
| R-1 | El override de `_assign_exclusive_lot` cambia el flujo de **TODAS** las entregas exclusivas. | Alto | Es un **seam acotado** + guardián de 3 condiciones; sin reserva previa o con lote exclusivo con existencia ⇒ `super()` (motor). Condición (3) exige que el lote exclusivo **NO** tenga disponible ⇒ nunca "tapa" una re-alineación real. CA-5 con los 2 casos. |
| R-2 | Preservar una reserva **fantasma** (lote sin físico) dejaría validar un albarán sin existencia. | Medio | En la práctica una reserva de **lote** solo nace del remedio NATIVO (`_pf_reserve_lot` con `strict=True`), que **solo reserva lo disponible**; el teclado manual crea líneas **sin** lote (`lot_id=False`, ver H-029 nota 2) que no entran en la condición (2). Los casos sin físico siguen el camino actual (skip honesto). |
| R-3 | La condición (3) hace **1 lectura** de quant por movimiento exclusivo dentro del bucle del bulk. | Bajo | Lectura ACOTADA (1 por albarán) dentro de un bucle que ya hace savepoint + `action_assign` + `button_validate` por albarán (no es ruta caliente ni un listado). Se documenta y no se agrega ninguna lectura a la bandeja ni al poblado. |
| R-4 | El detalle nuevo abre un wizard "de más" y rompe el cierre del modal. | Medio | Mismo patrón ya en producción (`printflow_node_pending_line.action_pf_validate_selected`: notificación + `next`); el detalle es de SOLO LECTURA y su footer "Cerrar" (`special="cancel"`) devuelve a la bandeja. |
| R-5 | Cambiar el label `omitted_count` en el MODELO no se ve (la VISTA fuerza `string="Filas omitidas"`). | Bajo | T5 quita el `string` de la vista para que gobierne el del modelo; CA-4 se verifica en el modelo (`fields_get`) y la vista queda coherente. |
| R-6 | Un candado text-based del bulk se rompe por la cadena nueva. | Bajo | D7: el texto de la notificación **no cambia**; solo se agrega `next`. Los 2 tests nuevos fijan el resto. |

### 3.10 Contratos que NO deben romperse

- **CA-1..CA-5** de 3.8.
- `printflow.flow.lot.assign.bulk.action_assign_lot_bulk`: **conserva** la guardia `_pf_assert_can_clean()`, el
  `reason` obligatorio, la política de excepción, `_pf_check_coverage`, el bucle FIFO con captura de `UserError`
  **por destino**, el `message_post` por documento y el **texto exacto** de los 4 conteos.
- El **recorrido de escritura** `_pf_assign_lot_to_document` → `_pf_reassign_move_lot` →
  `stock.move._pf_reassign_lot` y el mapa `handlers` (lista blanca explícita, NUNCA `getattr`): **SIN cambios**.
- `printflow.flow.lot.candidate` (+ `bulk_id`) y su tree `printflow_flow_lot_candidate_view_tree`: **SIN cambios**
  (se reutiliza tal cual).
- `printflow.flow.lot.tray` (bandeja clásica: `_pf_populate`, `_pf_document_move`, `_pf_rows_*`,
  `action_assign_lot_bulk` de la SELECCIÓN) y su tree (botón de cabecera "Asignar lote"): **SIN cambios**.
- `models/printflow_flow_lots.py::_pf_available_lots`: firma y dict de retorno **INTACTOS**.
- Motor `x_product_dimensional_pricing`: **SIN CAMBIOS** (solo se **hereda** `stock.move` y se **lee**
  `printflow.delivery.bulk.result` como patrón). `_action_assign`, `_assign_exclusive_lot`, `_pf_reassign_lot`,
  `_pf_unreserve_reservation` y `action_pf_bulk_validate_deliveries` del motor quedan **intactos**.
- `models/` **nunca** importa `wizard/`. Sin `cr.execute` de escritura. Sin `cr.commit()`.

### 3.11 Observaciones (FUERA de alcance — NO implementar aquí)

- **O-a** La asignación **REAL** de lotes a las 26 entregas del banner es **DATOS** (**H-018**); la ejecuta el
  dueño. El código **muestra** y **facilita**, no asigna por su cuenta.
- **O-b** El texto `"Sin stock reservado."` del motor **no se cambia** (D2): con el arreglo ya no cubre un caso
  con reserva, y para el caso sin reserva es honesto.
- **O-c** El camino **FIFO NATIVO** de las entregas **NO exclusivas** (producto sin `x_is_printflow_managed` ni
  `pf_purchase_on_order`) queda **fuera de alcance**: el core ya preserva lo ya reservado y NO se toca.
- **O-d** Los 8 rojos de la suite (**B1**) siguen abiertos y son ajenos; el Dev solo corre los tests afectados y
  **reporta el delta** de `test_diagnostic_delivery_orders.py` / `test_pending_native_validate.py` si aparece.
- **O-e** La fila del MOVIMIENTO sin lote y las filas por ORDEN del mismo albarán siguen SIN deduplicar (D4/3.K
  O-5): se conservan a propósito.
- **O-f** **H-021** (fase 2 "Autorizar excepción" ≠ "Asignar lote") y **H-016** siguen fuera de alcance.

### 3.12 Plan de ejecución atómico y secuencial (T1–T9)

> **9 tareas · 3 lotes** (máx. 3 por lote; cada lote = **UNA sesión NUEVA de `odoo-dev`**).
> Convenciones OCA (`odoo-17-clean-architecture` §2.5): un archivo por modelo, `__init__` por archivo, orden del
> modelo (atributos → campos → constraints → default → compute → onchange → CRUD → acciones → negocio),
> `snake_case`, `xml_id` con prefijo `printflow_`, nodo raíz `<odoo>`.
> **Regla: código sí, datos no.** PROHIBIDO `cr.execute` de escritura y `cr.commit()`.
> **No forzar ni reemplazar flujos nativos; código sí, datos no.**
> **Fuente:** `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow) · `C:\odoo_custom\x_product_dimensional_pricing` (motor; SOLO LECTURA).
> El Dev marca `- [x]` SOLO lo hecho y deja su bitácora para el lote siguiente.

#### Lote 1 (T1–T3) — Detalle del resultado (H-029 · modelos + registro)

- [x] **T1 — CREAR `wizard/printflow_flow_lot_assign_bulk_result_line.py`.**
  - `class PrintflowFlowLotAssignBulkResultLine(models.TransientModel)` con
    `_name = 'printflow.flow.lot.assign.bulk.result.line'`, `_description = 'Línea del detalle de la asignación de lote en bloque (PrintFlow)'`,
    `_order = 'seq asc, id asc'`. Docstring: es SOLO LECTURA (snapshot del resultado por destino); NO escribe `stock.*`.
  - Campos (todos `readonly=True` salvo la FK): `result_id` (m2o `printflow.flow.lot.assign.bulk.result`, `required=True`,
    `ondelete='cascade'`, `index=True`), `seq` (Integer), `label` (Char), `kind` (Char), `demand_qty` (Float
    `digits='Product Unit of Measure'`), `result` (Selection **con los MISMOS 5 códigos** de
    `printflow.flow.lot.assign.bulk.line.result`: `pending/assigned/partial/skipped/error`), `result_note` (Char).
  - **Verificación:** `fields_get('printflow.flow.lot.assign.bulk.result.line')` devuelve los 7 campos.
- [x] **T2 — CREAR `wizard/printflow_flow_lot_assign_bulk_result.py`.**
  - `class PrintflowFlowLotAssignBulkResult(models.TransientModel)` con `_name = 'printflow.flow.lot.assign.bulk.result'`,
    `_description = 'Resultado de la asignación de lote en bloque (PrintFlow)'`. Docstring del "por qué" (H-029: hacer
    LEGIBLE el motivo por destino; patrón portado de `printflow.delivery.bulk.result` del motor).
  - Campos: `bulk_id` (m2o `printflow.flow.lot.assign.bulk`, `readonly=True`, `ondelete='cascade'`), `product_id`
    (m2o `product.product`, `readonly=True`), `source_label` (Char readonly), `line_ids` (o2m al modelo de T1),
    `assigned_count` / `partial_count` / `omitted_count` / `error_count` (Integer, `compute='_compute_counts'`).
  - `_compute_counts` con `@api.depends('line_ids.result')`: cuenta por `line_ids.filtered(lambda l: l.result == …)`.
  - `@api.model _pf_build_from_bulk(self, bulk)`: crea el registro con `bulk_id`, `product_id`, `source_label` y
    `line_ids` = **UNA fila por `bulk.line_ids`** (TODAS: `assigned/partial/skipped/error/pending`) copiando
    `seq/label/kind/demand_qty/result/result_note` (los destinos NO asignables ya llegan como `skipped` + nota desde
    `_pf_prepare_rows`, así que el detalle los muestra sin recalcular nada); devuelve el recordset creado.
  - **Verificación:** `_pf_build_from_bulk` sobre un `bulk` con N destinos devuelve un registro con N líneas y los
    conteos coherentes; `fields_get` responde.
- [x] **T3 — Registro de los 2 modelos.**
  - `wizard/__init__.py`: `from . import printflow_flow_lot_assign_bulk_result_line` y luego
    `from . import printflow_flow_lot_assign_bulk_result`, **DESPUÉS** de `printflow_flow_lot_assign_bulk` (L29) y
    ANTES de `printflow_flow_lot_picker`, con comentario del motivo.
  - `security/ir.model.access.csv`: 2 filas al final
    (`access_printflow_flow_lot_assign_bulk_result` / `access_printflow_flow_lot_assign_bulk_result_line`) con
    `base.group_user,1,1,1,1` y `model_id:id` `model_printflow_flow_lot_assign_bulk_result` /
    `model_printflow_flow_lot_assign_bulk_result_line`.
  - **Verificación:** `-u printflow_gestion_inventario` sin error; `ir.model` registra los 2 modelos; el tree nuevo carga.

#### Lote 2 (T4–T6) — H-031 (rótulos) + superficie del detalle + encadenado (H-029)

- [x] **T4 — `wizard/printflow_flow_lot_assign_bulk.py`: rótulos + `selection_note` (H-031).**
  - Cambiar el `string` de: `total_demand` → `'Unidades a entregar'`; `assignable_count` → `'Entregas por asignar'`;
    `omitted_count` → `'Entregas omitidas'`. **NO** cambiar `digits`, `compute` ni la lógica.
  - Agregar `selection_note = fields.Char(string='Resumen de la selección', compute='_compute_selection_note', readonly=True)`
    y su `_compute_selection_note` con `@api.depends('assignable_count', 'total_demand')`:
    `rec.selection_note = _('Cada fila es una entrega (albarán de salida). %(n)s entregas por asignar = %(m)s unidades a entregar.') % {'n': rec.assignable_count or 0, 'm': rec.total_demand or 0.0}`
    (el número M con el MISMO formato que ya usa `_pf_check_coverage`, p. ej. `%.2f`; **sin** sufijos de unidad).
  - **Verificación:** `fields_get('printflow.flow.lot.assign.bulk')` devuelve los 3 strings nuevos; un bulk poblado
    trae `selection_note` con "entrega" y las cifras.
- [x] **T5 — Superficie: vista del bloque (H-031) + vista NUEVA del detalle + `__manifest__.py`.**
  - `wizard/printflow_flow_lot_assign_bulk_views.xml`: en el `<group string="Selección">` dejar
    `<field name="omitted_count" readonly="1"/>` **SIN** el `string="Filas omitidas"` (para que gobierne el del
    modelo) y añadir, como texto **VISIBLE** (no tooltip, no `invisible`), la línea de `selection_note`
    (p. ej. `<field name="selection_note" readonly="1" nolabel="1" colspan="2"/>` o dentro de un
    `<div class="text-muted">`). **NO** tocar el resto del form (candidatos, destinos, `reason`, footer).
  - **CREAR** `wizard/printflow_flow_lot_assign_bulk_result_views.xml`: form
    `create="false" edit="false" delete="false"`, `xml_id = printflow_flow_lot_assign_bulk_result_view_form`, con
    un `<div class="alert alert-info">` ("Motivo por destino de la asignación en bloque: revisa abajo cada entrega."),
    un `<group string="Resumen">` con los 4 conteos, el `<field name="line_ids" readonly="1">` con `<tree create="false" edit="false" delete="false">`
    (`decoration-success="result == 'assigned'"`, `decoration-warning="result == 'partial'"`,
    `decoration-muted="result == 'skipped'"`, `decoration-danger="result == 'error'"`) y las columnas
    `seq` (#) · `label` (Entrega) · `kind` (Tipo) · `demand_qty` (Demanda) · `result` (Resultado) · `result_note` (Motivo);
    y un `<footer>` con **"Cerrar"** (`special="cancel"`).
  - `__manifest__.py`: agregar `'wizard/printflow_flow_lot_assign_bulk_result_views.xml'` en `data`, **DESPUÉS** de
    `'wizard/printflow_flow_lot_assign_bulk_views.xml'`.
  - **Verificación:** `-u` sin error; el form del detalle abre con el resumen y la tabla de motivos.
- [x] **T6 — `wizard/printflow_flow_lot_assign_bulk.py`: encadenar el detalle en `action_assign_lot_bulk` (H-029).**
  - `_pf_result_notification(self, result=None)`: **conservar** el `display_notification` con el **mismo texto** de
    los 4 conteos y agregar `params['next']`: si `result` ⇒
    `{'type': 'ir.actions.act_window', 'name': _('Detalle de la asignación en bloque'), 'res_model': 'printflow.flow.lot.assign.bulk.result', 'res_id': result.id, 'view_mode': 'form', 'target': 'new'}`;
    si no ⇒ se mantiene `{'type': 'ir.actions.act_window_close'}` (retro-compatible).
  - Al final de `action_assign_lot_bulk` (hoy `return self._pf_result_notification()`): construir
    `result = self.env['printflow.flow.lot.assign.bulk.result']._pf_build_from_bulk(self)` y
    `return self._pf_result_notification(result)`.
  - **NO** cambiar el bucle de escritura, la guardia, el motivo, la política ni los conteos.
  - **Verificación:** la notificación conserva el texto y ahora `params['next']['res_model'] ==
    'printflow.flow.lot.assign.bulk.result'`.

#### Lote 3 (T7–T9) — H-030 (preservar la reserva por excepción) + tests

- [x] **T7 — CREAR `models/stock_move.py` + registrar en `models/__init__.py` (H-030).**
  - **CREAR** `models/stock_move.py`: `_EPS = 1e-6`; `class StockMove(models.Model): _inherit = 'stock.move'`; docstring
    del "por qué" (H-030: el nativo `_action_assign` NO re-asigna un movimiento ya reservado, pero la rama EXCLUSIVA
    del motor sí ⇒ perdía la excepción; este guardián aplica la regla del core a esa rama. Motor SIN CAMBIOS).
  - `_pf_keep_current_lot_reservation(self)` (`ensure_one`): `False` si `self.product_id.tracking != 'lot'`; `False`
    si no hay línea activa con lote (`self.move_line_ids.filtered(lambda ml: ml.lot_id and not ml.picked and ml.quantity > _EPS)`);
    `lot = self._get_exclusive_delivery_lot()`; `False` si no hay lote exclusivo (el motor ya no toca nada);
    `free = self.env['stock.quant']._get_available_quantity(self.product_id, self.location_id, lot_id=lot)`;
    `return free <= _EPS`. Docstring explicando que "ya reservado ⇒ no se toca" es la regla del propio core.
  - `_assign_exclusive_lot(self)`: si `self._pf_keep_current_lot_reservation()` ⇒ `self._recompute_state(); return True`;
    si no ⇒ `return super()._assign_exclusive_lot()`.
  - `models/__init__.py`: agregar `from . import stock_move` en la sección de extensiones del motor heredadas (junto a
    `mrp_technical_sheet` / `printflow_stock_remedy`), con comentario del motivo.
  - **NO** tocar `x_product_dimensional_pricing`; **NO** `cr.execute`/`cr.commit`.
  - **Verificación:** `type(env['stock.move']).mro()` contiene la clase de PrintFlow; `-u` sin error; el fuente del
    motor sin cambios (git diff vacío en esa ruta).
- [x] **T8 — Test de H-030: `tests/test_pf_bulk_validate_preserves_lot.py` (+ `tests/__init__.py`).**
  - **CREAR** el archivo (`TransactionCase`, rollback; sellado `@tagged('post_install', '-at_install')` como los vecinos).
    Escenario: producto `type='product'`, `tracking='lot'`, `x_is_printflow_managed=True` (+ `pf_purchase_on_order=True`),
    **SO confirmado** con una línea del producto (⇒ `move.sale_line_id` existe ⇒ `_is_exclusive_delivery()` = `True`)
    y su **lote exclusivo** (`<SO>-L<línea>`) **creado y VACÍO**; la mercancía real en un **lote GENÉRICO** con
    existencia en la ubicación de origen.
  - **CA-1/CA-2a (preserva):** reservar el lote GENÉRICO en el movimiento de salida con el protocolo NATIVO
    (`move._pf_reassign_lot(generic_lot, move.product_uom_qty)`); luego `picking.action_assign()` ⇒ asertar que
    `move.move_line_ids.mapped('lot_id') == generic_lot` (la excepción SOBREVIVE) y `picking.state == 'assigned'`.
  - **CA-2b (valida):** `env['stock.picking'].with_context(active_ids=[picking.id], active_domain=[]).action_pf_bulk_validate_deliveries()`
    ⇒ la ventana `printflow.delivery.bulk.result` trae la fila con `result == 'done'`, `reason` vacío y
    `picking.state == 'done'`; y **NO** aparece `reason == 'Sin stock reservado.'`.
  - **CA-2c (honesto, no regresión):** una SEGUNDA entrega del mismo producto **sin** reserva y **sin** existencia ⇒
    sigue `result == 'skipped'` con *"Sin stock reservado."*.
  - **CA-5 (motor intacto):** una TERCERA entrega **con** el lote exclusivo **CON existencia**, sin reserva previa ⇒
    `action_assign()` reserva el **lote EXCLUSIVO** (comportamiento del motor sin cambios).
  - Candado: el archivo nuevo no contiene `cr.execute(`/`cr.commit(`; el motor no se modificó.
  - Registrar en `tests/__init__.py` al final del bloque de lote.
  - **Verificación:** el test pasa con el arreglo de T7 y **falla sin él** (regresión real, no decorativa).
- [x] **T9 — Test de H-029/H-031: `tests/test_product_flow_lot_assign_bulk_result.py` (+ `tests/__init__.py`).**
  - **CREAR** el archivo (misma base y helpers que `tests/test_product_flow_lot_assign_bulk.py`).
  - **CA-3 (H-029):** poblar un `bulk` con al menos 2 destinos, uno asignable con `result` `error`/`partial`
    (p. ej. lote elegido que no cubre) y uno NO asignable (`skipped` con nota); tras `bulk.action_assign_lot_bulk()`
    asertar que la acción es `display_notification` con el **MISMO** texto de los 4 conteos y que
    `params['next']['res_model'] == 'printflow.flow.lot.assign.bulk.result'`; que el detalle
    (`result.line_ids`) trae **una fila por destino** (mismo número que `bulk.line_ids`) y que las filas
    `error`/`skipped` tienen `result_note` NO vacío.
  - **CA-4 (H-031):** `fields_get('printflow.flow.lot.assign.bulk')` devuelve `'Unidades a entregar'`,
    `'Entregas por asignar'` y `'Entregas omitidas'`; `bulk.selection_note` contiene `'entrega'` y las cifras.
  - Candado: sin `cr.execute(`/`cr.commit(`.
  - Registrar en `tests/__init__.py`.
  - **Verificación:** los 2 tests nuevos verdes + `test_product_flow_lot_assign_bulk.py`,
    `test_product_flow_lot_pending_order_assign.py`, `test_product_flow_lot_tray*`,
    `test_product_flow_lot_picker*` y `test_product_flow_over_reservation_scoped.py` verdes.

**Verificación (turno del Verificador, fuera del dev).** `--test-tags` sobre
`/printflow_gestion_inventario:TestPfBulkValidatePreservesLot`,
`/printflow_gestion_inventario:TestProductFlowLotAssignBulkResult`,
`...:TestProductFlowLotAssignBulk`, `...:TestProductFlowLotPendingOrderAssign`, `...:TestProductFlowLotTray`,
`...:TestProductFlowLotTrayOrders`, `...:TestProductFlowLotTrayDocument`, `...:TestProductFlowLotTrayAuthorize`,
`...:TestProductFlowLotPicker`, `...:TestProductFlowLotPickerUX`, `...:TestProductFlowOverReservationScoped`,
`...:TestProductFlowLotCoupledChain` y `...:TestLotManagement`. Al hilo solo vuelve el exit code, N/N y, si falla,
la aserción + cola del traceback. **Los 8 rojos de B1 (p. ej. `test_diagnostic_delivery_orders.py`,
`test_product_flow_lot_tray_ux.py`, `test_node_pending_enumeration`) NO cuentan como fallo de esta tarea**, pero
el Dev **reporta** si su delta cambió por el arreglo de T7.

### 3.13 Contratos que NO deben romperse (resumen de cierre)

- **CA-1..CA-5** de 3.8 y los contratos de 3.10.
- Motor `x_product_dimensional_pricing`: **SIN CAMBIOS**; PrintFlow solo **hereda** `stock.move`.
- Un solo escritor (D5); cero `cr.execute` de escritura / `cr.commit()`; `models/` nunca importa `wizard/`.
- La bandeja clásica, el selector por documento, la autorización en bloque y el dedupe FIFO: **intactos**.

## 3.K (ANEXO · TAREA CERRADA) — Asignación de lote en bloque desde la bandeja

> **Turno:** Odoo Analista (revisión del PLAN del Planificador; paso 3 -> **`odoo-dev`**). **Estado:** **PLAN
> COMPLETO** (D1–D9 cerradas por el **Odoo Planificador**; T1–T8 en 3 lotes). Tarea **GRANDE** (toca el flujo de
> inventario/entregas). **Plan listo para `odoo-dev` (Lote 1: T1–T3).**
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow) · `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA**).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Cadena: Analista → Planificador → Analista → Dev (por lotes) → Verificador → Analista.
> **Hallazgos que ataca:** **H-021** (no existía acción masiva) · **H-026** (prerrequisito: `pending_order` sin escritor) · alivia **H-024**.

### 3.1 Problema (evidencia en el código y en la BD)

El dueño tiene la **lista de entregas pendientes por asignar lote** (bandeja `printflow.flow.lot.tray`, producto
`IMPRESION BANNER ` id 13571, **28 órdenes**; cada fila es `kind='pending_order'`, `res_model='stock.picking'`).
Resolverlas **una por una** es insostenible (28 ciclos de elegir lote + motivo) y, además, **la vía por fila HOY no cierra**:

| # | Sub-problema | Hallazgo | Evidencia |
|---|---|---|---|
| **P1** | **No hay acción masiva.** Cada entrega se resuelve desde su fila ("Elegir lote" → selector por documento). Para 28 órdenes = 28 ciclos completos. | H-021 | `wizard/printflow_flow_lot_tray.py` (cabecera solo tiene AUTORIZAR/crear) · `wizard/printflow_flow_lot_picker.py` (por documento) |
| **P2** | **La vía por fila está cortada.** En una fila `pending_order` el botón "Elegir lote" se muestra y el selector abre, pero "Asignar lote" lanza `UserError('Este ítem no permite elegir un lote (tipo: pending_order)')`: la lista blanca de escritura no conoce ese tipo. | **H-026** (alta) | `wizard/printflow_product_flow.py::_pf_assign_lot_to_document` L924-936 (handlers sin `pending_order`) · `wizard/printflow_flow_lot_tray.py` L576-592 (`kind='pending_order'`, `can_choose_lot=True`) |
| **P3** | **No se ve la disponibilidad AGREGADA.** El selector por documento compara UN lote contra UNA demanda; al asignar a N órdenes hay que saber si el lote **alcanza** para la demanda SUMADA. | — | `printflow.flow.lots._pf_available_lots` (motor, solo lectura) |

Datos de contexto (BD `Ciber Estudios 2015 RESTAURADA`): 28 entregas de salida abiertas del producto; la mercancía real
está en lotes **genéricos** (`666634` = 24, entre otros) mientras el **lote exclusivo por pedido** está vacío (H-018).

### 3.2 Objetivo (acotado)

**SÍ:**
1. **Acción en bloque sobre la SELECCIÓN** de la bandeja: marcar N filas → **un** botón de cabecera → **un** wizard que
   pregunte **cuál lote** y **muestre la info de cada lote** (Lote · Existencia · Reservado · **Disponible** · Rol) →
   asigne el lote elegido a **TODAS** las filas seleccionadas, con **UN motivo**.
2. **Prerrequisito H-026:** que `_pf_assign_lot_to_document` **soporte `pending_order`** (resolver el albarán → su
   `stock.move` activo → protocolo NATIVO de reasignación). Esto arregla también el "Elegir lote" por fila.
3. **Parcial (decidido con el dueño):** si el lote elegido NO cubre la demanda SUMADA de la selección ⇒ asignar **lo
   disponible** con confirmación explícita, y reportar cuántas quedaron cubiertas y cuántas no.
4. **Alcance (decidido con el dueño):** la acción aplica **SOLO a entregas sin lote** (`pending_order` y movimientos de
   entrega). Las demás filas (OF/MO, insumos, reserva huérfana) se **OMITEN y se reportan** (no revientan el lote).

**NO:**
- NO escribir datos por fuera de la vía existente: la escritura es el **remedio NATIVO** (`_pf_reassign_move_lot` →
  `stock.move._pf_reassign_lot`), con **guardia** `_pf_assert_can_clean` (jefe de taller/admin) y **motivo**.
- NO tocar el motor `x_product_dimensional_pricing` (SOLO LECTURA/reutilización).
- NO forzar flujos nativos (sin `cr.execute` de escritura, sin `cr.commit()`, sin escribir `stock.quant`/`stock.move` a mano,
  sin `button_validate` por detrás).
- NO refactorizar el selector por documento (la **propuesta 2** queda en el backlog, fuera de alcance).
- NO romper: selector por documento, bandeja clásica, autorización en bloque, ni el listado/búsqueda de `pending_order`.

### 3.3 Contrato funcional

| Superficie | Debe quedar |
|---|---|
| Bandeja `printflow.flow.lot.tray` (tree) | Botón de cabecera NUEVO "Asignar lote" con `display="selection"` (hermano de "Autorizar excepción"); exige permiso (jefe de taller/admin). |
| Wizard NUEVO (bulk) | Pregunta **un lote** (tabla de candidatos con Existencia · Reservado · Disponible · Rol) + **un motivo** + check de **parcial**. Muestra la **demanda sumada** de la selección y si el lote alcanza. |
| Escritura | `_pf_assign_lot_to_document` extendido con `pending_order`. Reutiliza `_pf_reassign_move_lot` (protocolo nativo). |
| Resultado | Notificación "N asignadas · M omitidas (no asignables) · K parciales/sin existencia". Al repoblar, las filas resueltas **desaparecen** de la bandeja. |
| H-026 | El "Elegir lote" de fila `pending_order` **funciona** (deja de lanzar `UserError`). |

### 3.4 Fuente ÚNICA / patrón a reutilizar (cero reinvención)

- **Patrón de acción sobre la selección + motivo único:** `wizard/printflow_flow_lot_exception_authorize_bulk.py` (+ su `_views.xml`) y su precedente declarado ("por qué un wizard nuevo y no reutilizar el unitario").
- **Tabla de info de lotes (la que pide el dueño):** modelo `printflow.flow.lot.candidate` + su tree (`wizard/printflow_flow_lot_picker_views.xml` L15-62).
- **Cálculo de candidatos:** `printflow.flow.lots._pf_available_lots` (motor; UNA lectura de `stock.quant`).
- **Escritura por documento:** `printflow.product.flow._pf_assign_lot_to_document` / `_pf_reassign_move_lot` (motor de reserva).
- **Resolución albarán → movimiento:** `printflow.flow.lot.tray._pf_document_move` (YA soporta `pending_order`, L796-801).
- **Guardia de permisos:** `printflow.stock.remedy._pf_assert_can_clean()`.
- **Filas ORDER de la bandeja:** `printflow.flow.lot.tray._pf_rows_pending_orders` (L529-593) y `_pf_row_lot_context` (L748-777).

### 3.5 Decisiones de diseño cerradas (D1–D9)

> **Cerradas por el `odoo-planificador`** (esta sección REEMPLAZA la versión con D2/D3 "ABIERTA"). Todas se apoyan en
> piezas EXISTENTES: el diseño **ENGANCHA** el flujo nativo, no lo reemplaza.

- **D1 - Envase NUEVO (`printflow.flow.lot.assign.bulk`), piezas REUTILIZADAS.** Se crea un TransientModel CONTENEDOR
  nuevo (`wizard/printflow_flow_lot_assign_bulk.py`) + un modelo de LÍNEA de destino nuevo
  (`wizard/printflow_flow_lot_assign_bulk_line.py`). **NO** se extiende `printflow.flow.lot.picker` (amarrado a UN
  documento por diseño y cubierto por tests). Se REUTILIZAN: el modelo/vista `printflow.flow.lot.candidate` (con un
  cambio ADITIVO, D2-bis), `_pf_available_lots`, `_pf_assign_lot_to_document`, `_pf_reassign_move_lot`,
  `_pf_document_move`, `_pf_assert_can_clean`, la semántica de `_pf_selected_lot` y el patrón del
  `printflow.flow.lot.exception.authorize.bulk` (N destinos + UN motivo).
- **D2 - Ubicación EFECTIVA por destino y disponibilidad.** Cada destino resuelve su ubicación efectiva: `tray_row.location_id`
  si viene; si NO (las filas `missing_move` NO la traen: `_pf_rows_missing_moves` L492-510 solo setea kind/label/qty/
  state_label/detail/res_model/res_id/can_choose_lot), la del `stock.move` resuelto con **UNA** lectura batch
  (`stock.move.search_read` sobre los ids de esos movimientos). Si TODOS comparten UNA ubicación ⇒ `location_id` = esa
  (candidatos contra ella). Si hay VARIAS (o ninguna determinable) ⇒ `location_id = False` + `multi_location = True`:
  los candidatos se piden con `location_id=False` y `_pf_available_lots` devuelve `available_here == available`
  (disponibilidad **AGREGADA**), con aviso VISIBLE. **NO** se toca `_pf_available_lots`.
- **D2-bis - Cambio ADITIVO en `printflow.flow.lot.candidate`.** Se agrega `bulk_id` (Many2one a
  `printflow.flow.lot.assign.bulk`, `ondelete='cascade'`, indexado); se QUITA el `required=True` de `picker_id`; y se
  GENERALIZA el "padre" (`picker_id` **o** `bulk_id`) en `_compute_is_picked`, `_pf_enforce_single_selection` (espejo
  `parent.lot_id = rec.lot_id`) y `_compute_is_recommended` (demanda del padre = `picker_id.demand_qty` o
  `bulk_id.total_demand`). El contrato del selector por documento queda IDÉNTICO.
- **D3 - Semántica del PARCIAL.** `total_demand` = Σ `demand_qty` de los destinos asignables. Se reutiliza el check
  `confirm_partial` del selector: si la libre del lote para la ubicación efectiva es `< total_demand` y NO está marcado
  ⇒ `UserError` guía (NO escribe nada); con el check ⇒ se asigna **lo disponible** con el protocolo NATIVO, ordenado
  FIFO, y las órdenes que no alcanzan quedan **parciales/pendientes** (NUNCA se fuerzan ni se revientan).
- **D4 - Handler `pending_order` (resuelve H-026).** Se agrega `'pending_order'` al mapa `handlers` de
  `_pf_assign_lot_to_document` + el handler `_pf_assign_lot_on_pending_order_doc`: resuelve el albarán
  (`stock.picking`) -> su `stock.move` activo del producto (`limit=1`, `state not in ('done','cancel')`) ->
  `_pf_reassign_move_lot` (mismo camino que la resolución ya existente de `_pf_document_move` L796-801). Si no hay
  movimiento activo o la reserva da 0 ⇒ devuelve `0` (el orquestador lanza su `UserError`, que el bloque captura por
  destino).
- **D5 - Idempotencia y deduplicación.** La idempotencia viene HEREDADA de `_pf_reassign_move_lot` (L1017-1020: si el
  movimiento YA reserva el lote elegido y ningún otro, es no-op). En la SELECCIÓN se DEDUPLICA por `stock.move.id`
  resuelto (`_pf_document_move`), porque `missing_move` y `pending_order` pueden apuntar al MISMO albarán (O-5, S03275):
  se conserva el primer destino y el duplicado se REPORTA como omitido.
- **D6 - Orden determinista (FIFO de la escasez).** Los destinos se procesan por `scheduled_date` ASC y luego `id` ASC
  (las filas sin fecha la resuelven del movimiento/albarán en la MISMA lectura batch de D2). Un lote escaso se reparte
  SIEMPRE igual (reproducible), sin reglas escondidas.
- **D7 - Alcance de la acción.** Asignables: `kind in ('missing_move', 'pending_order')` (entregas sin lote). Se OMITEN
  y se REPORTAN: `unassigned_mo`, `orphan_quant`, `no_stock_lot`, `generic_lot`, `mixed_lot`, las filas con
  `can_choose_lot = False` y las que no resuelven movimiento.
- **D8 - Guardias, motivo y política (cero autorizaciones fantasma).** `_pf_assert_can_clean()` al ABRIR **y** al
  EJECUTAR; `reason` OBLIGATORIO; se honra la política vigente (`pf_lot_assign_exception_policy`, reutilizando
  `printflow.flow.lot.picker._pf_exception_policy`): si NO es `warn`, exige el check `confirm_exception`. **NO** se
  autoriza lote compartido en bloque (NO se crean `printflow.lot.exception`; `authorize_shared_lot` NO existe aquí) y
  **NO** se usa `printflow.lot.risk.confirm` (el bloque no escribe `stock.quant` a mano: la escritura es la
  reasignación NATIVA). Se hace `message_post` por documento (solo modelos con chatter: `stock.picking`/
  `mrp.production`).
- **D9 - H-026 se resuelve DOS veces con el MISMO escritor.** El handler `pending_order` (D4) arregla la vía POR FILA
  ("Elegir lote" en una fila `pending_order`) y la vía EN BLOQUE. Un solo escritor, dos superficies.

### 3.6 Archivos (confirmados por el Planificador)

**NUEVOS**
- `wizard/printflow_flow_lot_assign_bulk_line.py` - modelo de LÍNEA de destino (`printflow.flow.lot.assign.bulk.line`).
- `wizard/printflow_flow_lot_assign_bulk.py` - TransientModel contenedor (`printflow.flow.lot.assign.bulk`) con
  `_pf_populate`, `_pf_selected_lot`, `_pf_check_coverage`, `action_assign_lot_bulk`.
- `wizard/printflow_flow_lot_assign_bulk_views.xml` - form del wizard (candidatos + destinos + motivo + parcial).
- `tests/test_product_flow_lot_assign_bulk.py` - test del flujo EN BLOQUE.
- `tests/test_product_flow_lot_pending_order_assign.py` - test del handler `pending_order` (H-026, vía por fila).

**MODIFICADOS**
- `wizard/printflow_flow_lot_candidate.py` - `bulk_id` + padre generalizado (D2-bis).
- `wizard/printflow_product_flow.py` - `'pending_order'` en `handlers` + `_pf_assign_lot_on_pending_order_doc` (D4).
- `wizard/printflow_flow_lot_tray.py` - `action_assign_lot_bulk` (acción sobre la SELECCIÓN).
- `wizard/printflow_flow_lot_tray_views.xml` - botón de cabecera "Asignar lote" (`display="selection"`).
- `wizard/__init__.py` - 2 imports (línea -> contenedor), DESPUÉS de `printflow_flow_lot_candidate`.
- `__manifest__.py` - `data`: la vista nueva, DESPUÉS de `wizard/printflow_flow_lot_picker_views.xml`.
- `security/ir.model.access.csv` - 2 filas (`base.group_user,1,1,1,1`) para los 2 TransientModel nuevos.
- `tests/__init__.py` - registro de los 2 tests nuevos.

**NO SE TOCA (solo se consume):** `wizard/printflow_flow_lot_picker.py`, `wizard/printflow_flow_lot_picker_views.xml`,
`wizard/printflow_flow_lot_exception_authorize_bulk*.py/xml`, `models/printflow_flow_lots.py` (`_pf_available_lots`) y
TODO `x_product_dimensional_pricing` (**SOLO LECTURA**).

### 3.7 Restricciones duras

1. **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): el Dev NO toca registros de la BD; solo código. Nada de
   `cr.execute` de escritura, nada de `cr.commit()`, nada de escribir `stock.quant`/`stock.move` a mano.
2. **No forzar ni reemplazar flujos nativos; código sí, datos no.** La ÚNICA escritura es el **remedio NATIVO**
   `_pf_assign_lot_to_document` -> `_pf_reassign_move_lot` -> `stock.move._pf_reassign_lot` (protocolo de reserva del
   motor). PROHIBIDO: `button_validate`, `do_unreserve()` del albarán completo, `unlink()`+`create()` a mano, forzar
   `state`/`quantity`/`qty_done`.
3. **`_inherit` + `super()`** donde se extienda; el motor `x_product_dimensional_pricing` es **SOLO LECTURA**.
4. **Guardia + motivo**: `_pf_assert_can_clean()` (jefe de taller/admin) al abrir y al ejecutar; `reason` obligatorio.
5. **Cero hardcodeo**: la política sale de `ir.config_parameter` (`pf_lot_assign_exception_policy`).
6. **Convenciones OCA** (`odoo-17-clean-architecture` §2.5): un archivo por modelo, `__init__` por archivo, orden del
   modelo (comentario -> `_name` -> `_description` -> `_order` -> campos -> computes -> CRUD -> acciones) e `xml_id`
   con prefijo `printflow_`.
7. **Un solo escritor**: la acción en bloque REUTILIZA el orquestador; NO abre un segundo camino de escritura.

### 3.8 Criterios de aceptación verificables

- **CA-1 (H-026, vía por fila).** En una fila `pending_order`, "Elegir lote" -> "Asignar lote" **asigna SIN
  `UserError`** y el movimiento del albarán queda reservado con el lote elegido.
- **CA-2 (bloque).** Con N filas `pending_order`/`missing_move` seleccionadas, el botón de cabecera "Asignar lote"
  abre UN wizard que muestra producto, demanda SUMADA, la tabla de candidatos (Lote · Existencia · Reservado ·
  Disponible · Rol) y la lista de destinos; al ejecutar con UN motivo, TODOS los destinos asignables quedan con el lote.
- **CA-3 (alcance).** Las filas no asignables (MO/insumos/reserva huérfana/sin `can_choose_lot`) se OMITEN y su conteo se
  reporta; NO abortan el resto.
- **CA-4 (parcial).** Si `libre < total_demand` y NO se marcó "Confirmo la asignación parcial" ⇒ bloquea con mensaje
  guía y NO escribe. Con el check ⇒ asigna lo disponible y reporta asignadas/parciales/sin existencia.
- **CA-5 (permisos).** Sin jefe de taller/administrador, ABRIR y EJECUTAR lanzan `UserError` (`_pf_assert_can_clean`).
- **CA-6 (motivo/política).** Sin `reason`, ejecutar lanza `UserError`; con política ≠ `warn`, sin `confirm_exception`
  ⇒ `UserError`.
- **CA-7 (resultado).** La notificación informa "N asignadas · P parciales · K omitidas · E con error" y al REABRIR la
  bandeja (`_pf_populate`) las órdenes resueltas YA NO se listan.
- **CA-8 (cero regresión).** Selector por documento, autorización en bloque, bandeja clásica y listado de
  `pending_order` siguen funcionando; `_pf_available_lots` conserva firma y dict de retorno; la suite de lote/bandeja
  pasa (los 8 rojos de **B1** son PRE-EXISTENTES y ajenos).
- **CA-9 (dedupe).** Dos filas de la MISMA entrega (`missing_move` + `pending_order`) producen UNA sola asignación y el
  duplicado se reporta como omitido.

### 3.9 Riesgos

| # | Riesgo | Mitigación |
|---|---|---|
| R-1 | Con `location_id=False` la disponibilidad es AGREGADA y puede "prometer" más de lo que hay en la ubicación de UN documento. | `multi_location=True` VISIBLE + validación NATIVA por documento (la reserva real la decide el motor); el destino que no alcanza queda `skipped` (nunca forzado). |
| R-2 | Un lote escaso se agota tras las primeras N asignaciones y el handler devuelve 0 ⇒ `UserError`. | El bloque captura el `UserError` POR DESTINO (no aborta), lo cuenta y lo reporta; orden FIFO determinista (D6). |
| R-3 | El dedupe por `stock.move.id` (D5) podría ocultar un segundo documento real. | El destino duplicado se REPORTA como omitido (no se pierde de vista). |
| R-4 | El check de la tabla escribe `bulk_id.lot_id`; una doble marca dejaría dos lotes. | `_pf_selected_lot` conserva la defensa (>1 marcado ⇒ `UserError` guía) y el `write` desmarca hermanas. |
| R-5 | `message_post` en un modelo sin chatter. | Restringir a `stock.picking`/`mrp.production` (patrón `_CHATTER_MODELS` del selector). |
| R-6 | La suite completa tiene 8 rojos pre-existentes (**B1**). | El Dev corre SOLO los tests de lote/bandeja afectados; NO persigue B1. |

### 3.10 Observaciones (FUERA de alcance — NO implementar aquí)

- **O-1** `_pf_rows_missing_moves` (bandeja clásica) NO pobla `location_id`/`demand_qty`/`picking_id`/`scheduled_date`;
  el bloque lo resuelve LOCALMENTE con UNA lectura batch (D2/D6). Poblar la fila = cambio en la bandeja clásica con
  riesgo de regresión (`test_product_flow_lot_tray_ux.py`) ⇒ **fuera de alcance**.
- **O-2** La "propuesta 2" (refactor del selector por documento a multiselección) sigue en backlog.
- **O-3** Autorizar la excepción desde el bloque (crear `printflow.lot.exception` por lote) ⇒ **NO**; se hace por fila.
- **O-4** Los 8 rojos de la suite (backlog **B1**) siguen abiertos y son ajenos a esta tarea.
  **Confirmado en el Lote 1:** al correr los tests del selector por documento siguió rojo
  `tests/test_product_flow_lot_picker_ux.py:143` (`test_own_and_current_lots_are_listed_and_labeled`,
  `assertAlmostEqual(cur_cand.available, 8.0)` → `6.0`): la reserva del movimiento del escenario
  (2 u) NO está descontada en la expectativa del test (aritmética del propio test sobre
  existencias/reservas). **Ajeno a T1/T2/T3** (la asignación en bloque no toca cantidades).
- **O-5** **H-016** (el botón del nodo Entrega muestra 1 vs badge 28) y **H-018** (asignar lotes REALES = DATOS) siguen
  fuera de alcance.
- **O-6 (Lote 2)** Al cargar el módulo (`-u`) persisten los avisos **pre-existentes** de carga (ya documentados en
  bitácoras anteriores), ajenos a T4–T6: labels duplicados en campos de varios wizards y
  `Skipping deletion for missing XML ID` de `x_product_dimensional_pricing.menu_printflow_dashboards` /
  `printflow_health_center_*`. La vista nueva del tree de la bandeja carga sin error
  (`loading …/wizard/printflow_flow_lot_tray_views.xml`). **NO** se tocan (fuera de alcance).

### 3.11 Plan de ejecución atómico y secuencial (T1–T8)

> **8 tareas · 3 lotes** (máx. 3 por lote; cada lote = UNA sesión NUEVA de `odoo-dev`).
> El Dev marca `- [x]` SOLO lo hecho y deja su bitácora para el lote siguiente.

#### Lote 1 (T1–T3) — Modelos (Python): candidato + línea + contenedor

- [x] **T1 - `wizard/printflow_flow_lot_candidate.py`: padre generalizado (D2-bis).**
  - Agregar `bulk_id = fields.Many2one('printflow.flow.lot.assign.bulk', string='Asignación en bloque', ondelete='cascade', index=True)`.
  - QUITAR `required=True` de `picker_id` (conserva `string`/`ondelete='cascade'`).
  - Helper `_pf_parent()` -> `self.picker_id or self.bulk_id`.
  - `_compute_is_picked` (L119-124): `chosen = parent.lot_id if parent else False`.
  - `_pf_enforce_single_selection` (L217-235): operar sobre `parent = rec._pf_parent()`; hermanas = `parent.candidate_ids - rec`; espejo `parent.lot_id = rec.lot_id` (y limpiar si `parent.lot_id == rec.lot_id`).
  - `_compute_is_recommended` (L177-203): agrupar por `_pf_parent()` y usar `parent.demand_qty` (picker) o `parent.total_demand` (bulk); añadir `bulk_id.total_demand` a `@api.depends`.
  - **Verificación:** `fields_get('printflow.flow.lot.candidate')` muestra `bulk_id` y `picker_id` SIN `required`; `tests/test_product_flow_lot_picker.py` sigue verde.
- [x] **T2 - NUEVO `wizard/printflow_flow_lot_assign_bulk_line.py` (D5/D7).**
  - `_name = 'printflow.flow.lot.assign.bulk.line'`, `_description`, `_order = 'seq asc, id asc'`.
  - Campos: `bulk_id` (m2o required ondelete cascade index), `seq` (Integer), `kind` (Char), `res_model` (Char), `res_id` (Integer), `move_id` (m2o `stock.move` readonly), `label` (Char readonly), `demand_qty` (Float `digits='Product Unit of Measure'`), `location_id` (m2o `stock.location` readonly), `scheduled_date` (Datetime readonly), `assignable` (Boolean readonly), `result` (Selection `pending/assigned/partial/skipped/error`, default `pending`), `result_note` (Char readonly).
  - Es un SNAPSHOT de la selección: no escribe en `stock.*`.
  - **Verificación:** `fields_get` del modelo nuevo devuelve los 12 campos.
- [x] **T3 - NUEVO `wizard/printflow_flow_lot_assign_bulk.py` + registro (D1/D2/D3/D8).**
  - `_name = 'printflow.flow.lot.assign.bulk'` (TransientModel), `_EPS = 1e-6`. Campos: `product_id` (m2o required readonly), `source_label` (Char readonly), `location_id` (m2o readonly), `multi_location` (Boolean readonly), `total_demand` (Float readonly), `line_ids` (o2m al modelo de T2), `candidate_ids` (o2m a `printflow.flow.lot.candidate`, inverse `bulk_id`), `candidate_lot_ids` (m2m compute de los candidatos `is_elective`), `lot_id` (m2o `stock.lot` con `domain="[('product_id','=',product_id),('id','in',candidate_lot_ids)]"`), `confirm_partial` (Boolean), `confirm_exception` (Boolean), `reason` (Text), `omitted_count` (Integer readonly), `assignable_count` (Integer compute).
  - `_pf_populate(product, rows)` (`@api.model`): construye los destinos (T2); resuelve ubicación efectiva + fecha con **UNA** `stock.move.search_read` sobre los ids de los movimientos de las filas que NO traen ubicación (D2/D6); deduplica por `move_id` (D5); calcula `total_demand`, `location_id`/`multi_location`; crea los candidatos con `_pf_available_lots(product, location_id=<efectiva o False>, demand_qty=total_demand, include_lot_ids=<lotes propios distintos resueltos por nombre>)` (mismo patrón de UNA búsqueda de `stock.lot` que `_pf_annotate_lot_quantities` L828-836) y los vuelca con los MISMOS `vals` que `printflow.flow.lot.picker._pf_populate` (L347-377) + `bulk_id`.
  - `_pf_selected_lot()`: misma semántica del selector (fila `is_selected`; si hay >1 ⇒ `UserError` guía; respaldo `lot_id`).
  - `_pf_check_coverage(chosen)` (D3): `libre = stock.quant._get_available_quantity(product, location_id, lot_id=chosen)` si hay ubicación; si no, `available` del candidato. `libre <= _EPS` ⇒ `UserError`; `libre < total_demand - _EPS` sin `confirm_partial` ⇒ `UserError` guía.
  - `action_assign_lot_bulk()`: `ensure_one`; `_pf_assert_can_clean()`; `reason` obligatorio; política (`printflow.flow.lot.picker._pf_exception_policy()`: si ≠ `warn` exige `confirm_exception`); `_pf_check_coverage`; iterar `line_ids.filtered('assignable')` en orden FIFO -> `try: env['printflow.product.flow']._pf_assign_lot_to_document(line.kind, line.res_model, line.res_id, chosen, product=self.product_id) except UserError as err: line.result='error'/'skipped'` -> contar lo reservado por destino (lectura de las `stock.move.line` del lote en el movimiento) ⇒ `assigned`/`partial` -> `message_post` por documento con chatter (D8); devolver `display_notification` con los 4 conteos (CA-7).
  - `wizard/__init__.py`: agregar `from . import printflow_flow_lot_assign_bulk_line` y luego `from . import printflow_flow_lot_assign_bulk` DESPUÉS de la línea de `printflow_flow_lot_candidate` (L24).
  - `security/ir.model.access.csv`: 2 filas `base.group_user,1,1,1,1` para `printflow.flow.lot.assign.bulk` y `printflow.flow.lot.assign.bulk.line`.
  - **Verificación:** `ir.model` registra los 2 modelos; `-u` instala sin error; `fields_get` del contenedor responde.

#### Lote 2 (T4–T6) — Cableado: handler nativo + acción de bandeja + botón

- [x] **T4 - `wizard/printflow_product_flow.py`: handler `pending_order` (D4, resuelve H-026).**
  - En `handlers` (L924-931) agregar `'pending_order': self._pf_assign_lot_on_pending_order_doc,`.
  - Nuevo `@api.model def _pf_assign_lot_on_pending_order_doc(self, res_model, res_id, lot, product)`: si `res_model == 'stock.picking'` y `res_id` ⇒ `Move.search([('picking_id','=',res_id),('product_id','=',product.id),('state','not in',('done','cancel'))], limit=1)`; si `res_model == 'stock.move'` ⇒ `browse(res_id)`; devolver `1 if self._pf_reassign_move_lot(move, lot, product) else 0`.
  - **Verificación:** CA-1 por la vía por fila (`action_open_lot_picker` con `target_kind='pending_order'`).
- [x] **T5 - `wizard/printflow_flow_lot_tray.py`: `action_assign_lot_bulk` (D2/D5/D7).**
  - Método PÚBLICO (Odoo 17 rechaza privados por RPC); `_pf_assert_can_clean()`; `records = self or self.search(active_domain)` (igual que `action_authorize_selected` L1005-1009).
  - `assignable = records.filtered(can_choose_lot y kind in ('missing_move','pending_order') y product_id)`; `omitted = len(records) - len(assignable)`; si no hay asignables ⇒ `_pf_authorize_selected_notification(...)` (sin abrir wizard).
  - Resolver el movimiento de cada fila con `_pf_document_move` (YA soporta `pending_order`), descartar las que no resuelven y DEDUPLICAR por `move.id` (D5).
  - `bulk = env['printflow.flow.lot.assign.bulk']._pf_populate(product, filas)` pasando `omitted_count`; devolver `act_window` (`target='new'`) sobre el wizard.
- [x] **T6 - `wizard/printflow_flow_lot_tray_views.xml`: botón de cabecera.**
  - En `<header>` (L28-54) agregar, HERMANO de "Autorizar excepción":
    `<button name="action_assign_lot_bulk" type="object" string="Asignar lote" class="btn-primary" icon="fa-tags" display="selection" title="Asigna UN lote (con un motivo) a las entregas sin lote seleccionadas. ESCRIBE inventario por la vía NATIVA (reserva). Requiere jefe de taller/administrador"/>`
  - NO tocar los botones existentes ni las columnas del tree.

#### Lote 3 (T7–T8) — Superficie + registro + tests

- [x] **T7 - NUEVO `wizard/printflow_flow_lot_assign_bulk_views.xml` + `__manifest__.py`.**
  - Form (`create="false" delete="false"`) con: cabecera (producto, `source_label`, `total_demand`, aviso VISIBLE si `multi_location`), `lot_id`, `confirm_partial`, `confirm_exception`, `reason` (required), `candidate_ids` (reutiliza el tree `printflow_flow_lot_candidate_view_tree`), `line_ids` (tree readonly: `seq`, `label`, `kind`, `demand_qty`, `location_id`, `result`) y `<footer>` con "Asignar lote" (`action_assign_lot_bulk`, `btn-primary`) + "Cancelar" (`special="cancel"`).
  - `__manifest__.py`: agregar `'wizard/printflow_flow_lot_assign_bulk_views.xml'` en `data`, DESPUÉS de `'wizard/printflow_flow_lot_picker_views.xml'` (reutiliza su tree).
  - **Verificación:** `-u` sin error; el wizard abre y muestra candidatos y destinos.
- [x] **T8 - Tests + registro.**
  - NUEVO `tests/test_product_flow_lot_assign_bulk.py`: cubre CA-2/CA-3/CA-4/CA-5/CA-6/CA-7/CA-9 (bloque, parcial, omitidas, permisos, motivo, dedupe) con producto `tracking='lot'` y un albarán de salida sin lote (patrón de `tests/test_product_flow_lot_tray_orders.py`).
  - NUEVO `tests/test_product_flow_lot_pending_order_assign.py`: cubre CA-1 (H-026: `target_kind='pending_order'`, `res_model='stock.picking'` asigna SIN `UserError`).
  - `tests/__init__.py`: registrar los 2 archivos al final del bloque de lote.
  - **Verificación:** los 2 tests nuevos verdes + los de lote/bandeja relacionados verdes.

### 3.12 Contratos que NO deben romperse

- `models/printflow_flow_lots.py::_pf_available_lots`: firma y dict de retorno INTACTOS (solo se agrega un consumidor).
- `printflow.flow.lot.picker` + `_pf_populate`/`_pf_selected_lot`/`action_assign_lot`: contrato INTACTO; el candidato
  sigue funcionando con `picker_id` (el selector SIEMPRE lo setea).
- `printflow.product.flow::_pf_assign_lot_to_document`: sigue lanzando `UserError` cuando el handler devuelve 0 (el
  bloque lo captura por destino) y el mapa sigue siendo lista blanca explícita (NUNCA `getattr`).
- `printflow.product.flow::_pf_reassign_move_lot` y el motor `stock.move._pf_reassign_lot`: SIN cambios.
- `printflow.flow.lot.tray::_pf_document_move`/`_pf_populate`/`_pf_rows_*`: SIN cambios; la bandeja clásica lee lo mismo.
- Tree de `printflow.flow.lot.candidate` (`printflow_flow_lot_candidate_view_tree`): SIN cambios (se reutiliza tal cual).
- Botones y columnas actuales de `printflow_flow_lot_tray_view_tree`: SIN cambios (solo se AGREGA un botón).

## 3.J (ANEXO · TAREA CERRADA) — El error de lote en el diagrama de producto (nodos Entrega e Inventario)

> **Turno:** Odoo Analista (revisión del PLAN del Planificador; paso 3 → **`odoo-dev`**). **Estado:** **PLAN
> COMPLETO** (D1–D6 cerradas por el **Odoo Planificador**; T1–T9 en 3 lotes). Tarea **GRANDE** (toca el flujo de
> inventario/entregas). **Plan listo para `odoo-dev` (Lote 1: T1–T3).**
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow) · `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA**).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Cadena: Analista → Planificador → Analista → Dev (por lotes) → Verificador → Analista.

### 3.1 Problema (evidencia en la BD y en el código)

El diagrama de flujo del PRODUCTO `IMPRESION BANNER ` (id 13571; `tracking='lot'`; `x_is_printflow_managed=True`;
`pf_purchase_on_order=True`) pinta **DOS fallas marcadas "Independiente"** que en realidad son **UN MISMO hecho**, y
las dos superficies de resolución desorientan al operador:

| # | Sub-problema | Hallazgo | Evidencia |
|---|---|---|---|
| **P1** | **Dos fallas que son UNA.** Nodo **Entrega** = "1 movimiento(s) sin lote" (`lot_missing`) y nodo **Inventario** = "Reserva colgada (saneable)" (`data_anomaly`), ambos con badge **"Independiente"** (sin cadena raíz→consecuencia). Es la MISMA causa: la entrega **reservó sin lote** y deja el reservado colgado. | H-020 | `move.line` **94875** (picking 23013 / **WH/OUT/02988** / **S03275**, `lot_id=false`, qty 3) · `stock.quant` **15219** (`quantity=0`, `reserved=3`, sin lote) · lote exclusivo `S03275-L5356` (id 2234) **vacío** |
| **P2** | **El "Solucionar" no lista las órdenes pendientes.** Abre `printflow.flow.lot.tray` poblada con `missing_move_ids` del motor = **movimientos YA creados** sin lote ⇒ hoy **1 fila**; las **26** entregas sin reserva (sin `move_line`) NO aparecen. El operador ve "1" y cree que es todo. | H-024 | `wizard/printflow_product_flow.py::_pf_open_lot_tray` L293-316 · `wizard/printflow_flow_lot_tray.py::_pf_rows_for_state`/`_pf_rows_missing_moves` L434-499 · BD: 28 pickings salida abiertos (26 sin `move_line`) |
| **P3** | **El botón "Ver movimientos sin lote" miente.** El playbook del estado `lot_missing` lo declara `('navigate','quants')` ⇒ abre la vista de **EXISTENCIAS (quants)**, no los movimientos. | H-023 | `models/printflow_resolution_playbook.py::_pf_plan_lot_missing` L919-920 |
| **P4** | **"Liberar y re-reservar" suelta TODA la ubicación.** `_pf_cleanup_product_reservations` suelta + re-asigna **todas** las `stock.move.line` cuya ubicación tiene reserva colgada; como el producto es de entrega **exclusiva por lote** (`_is_exclusive_delivery()`), la entrega **SANA** (WH/OUT/02974 con el lote 666634) también se re-asigna contra su lote exclusivo **vacío** ⇒ queda **sin lote** (se pierde la excepción). No descuadra el FÍSICO, pero empeora una entrega correcta. | H-022 | `x_product_dimensional_pricing/models/printflow_stock_remedy.py::_pf_cleanup_product_reservations` L616-670 · `x_product_dimensional_pricing/models/stock_move.py` L10-46, L206-217, L57-89 |

Datos de contexto (BD `Ciber Estudios 2015 RESTAURADA`, producto 13571): físico **34** / reservado **4** / libre **30**.
28 entregas de salida abiertas: **1** con lote (02974→666634, excepción del operador), **1** sin lote (02988), **26**
en `confirmed` sin `move_line`. Lotes exclusivos `S03253-L5316` (2233) y `S03275-L5356` (2234) **existen pero vacíos**.

> **Fuera de alcance de esta tarea (datos, no código):** la asignación REAL de lotes a las 26 entregas (H-018) y la
> corrección del `dwqdqwd` (H-017, ya resuelta por el operador). El código **muestra** y **facilita**, no asigna por su cuenta.

### 3.2 Objetivo (acotado)

**SÍ:**
1. **P1** — Que el diagrama (o su texto de cadena/causa) **explique** que Entrega "sin lote" e Inventario "reserva
   colgada" son **la misma falla**, e indique la **causa raíz** ("falta el lote exclusivo del pedido `S…-Lyyy`, que
   está vacío") y el **paso correcto**.
2. **P2** — Que el "Solucionar" del nodo Entrega liste **TODAS las órdenes de entrega pendientes sin lote** (las 28),
   no solo el movimiento ya creado, para que el operador vea la dimensión real y pueda resolver en bloque.
3. **P3** — Corregir el botón **"Ver movimientos sin lote"**: que abra los **movimientos** reales (o se **renombre**
   honestamente a "Ver existencias por lote" si el destino sigue siendo `quants`).
4. **P4** — Que **"Liberar y re-reservar"** NO des-asigne una entrega **sana**: acotar el saneo a las líneas que
   apuntan al quant con reserva colgada (o dejar intacta la reserva respaldada de la misma ubicación).

**NO:**
- NO tocar el motor `x_product_dimensional_pricing` (SOLO LECTURA/reutilización; si P4 exigiera tocar el motor, se
  hace un **override desde PrintFlow** o se pide autorización al dueño — decisión del Planificador).
- NO escribir datos: P1/P2/P3 son presentación/navegación (solo lectura); P4 reutiliza el saneo EXISTENTE con su
  guardia `_pf_assert_can_clean` (jefe de taller/admin).
- NO forzar ni reinventar flujos nativos (sin `cr.execute` / `cr.commit`; sin `button_validate` por detrás).
- NO romper la paridad del diagrama de PEDIDO, la bandeja clásica de lote, la bandeja guiada (`lot_no_stock`, H-019)
  ni los casos ya soportados.

### 3.3 Contrato funcional

| Superficie | Debe quedar |
|---|---|
| Nodo **Entrega** "sin lote" + Nodo **Inventario** "reserva colgada" | Se presentan como **una misma falla** con **causa raíz explícita** (lote exclusivo del pedido vacío) y cadena raíz→consecuencia (o texto equivalente). |
| "Solucionar" del nodo Entrega | Lista **las 28 órdenes pendientes** (no solo el movimiento ya creado); cada fila con su orden, lote esperado, estado y existencia. |
| Botón "Ver movimientos sin lote" | Abre los **movimientos** reales **o** se renombra a "Ver existencias por lote" (coherente con su destino `quants`). |
| "Liberar y re-reservar" (reserva colgada) | Saneo **acotado**: NO altera la reserva de entregas sanas de la misma ubicación. |
| Diagrama de PEDIDO / bandeja clásica / `lot_no_stock` (H-019) | **Intactos** (paridad). |
| Motor `x_product_dimensional_pricing` | **SIN CAMBIOS** (o cambio solo si el dueño lo autoriza). |

### 3.4 Fuente ÚNICA / patrón a reutilizar (cero reinvención)

- **Estado de lote (motor, solo lectura):** `printflow.stock.health._pf_lot_state` → `missing_move_ids`, `no_stock_lot_ids`, etc.
- **Bandeja clásica de lote:** `wizard/printflow_flow_lot_tray.py` (`_pf_populate`, `_pf_rows_for_state`, `_pf_rows_missing_moves`) + su vista `printflow_flow_lot_tray_views.xml` (ya tiene filtro "Movimientos sin lote").
- **Poblado del "Solucionar":** `wizard/printflow_product_flow.py::_pf_open_lot_tray` (L293-316).
- **Playbook del nodo:** `models/printflow_resolution_playbook.py::_pf_plan_lot_missing` (L909-923).
- **Roles/cadena:** `printflow.flow.strategy._pf_slot_chain_roles` / `_pf_broken_slots` y `models/printflow_flow_lots.py` (`_LOT_NODE_BY_KEY`, `_pf_failure_dict`).
- **Órdenes pendientes de entrega:** `printflow.flow.pending._pf_node_pending_rows('delivery', …)` y `wizard/printflow_product_flow.py::_pf_open_delivery_orders` (L640-660).
- **Saneo de reserva colgada:** `printflow.stock.remedy._pf_cleanup_product_reservations` (motor) y la falla `printflow.flow.failure.over.reservation` (`models/printflow_flow_failure_over_reservation.py`).
- **Lote exclusivo del pedido:** `stock.move._get_exclusive_delivery_lot` / `sale.order.line._get_exclusive_lot_name`.
- **Guardia de permisos:** `printflow.stock.remedy._pf_assert_can_clean()` (jefe de taller/admin).

### 3.5 Decisiones de diseño cerradas (D1–D6)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` · Ruta
> `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no** (SOLO LECTURA:
> `search`/`read`; la ÚNICA escritura es el saneo EXISTENTE con su guardia, y es un flujo de Odoo que el
> operador dispara). El diseño se **engancha** a lo ya existente (motor de lote `printflow.stock.health`,
> bandeja clásica `printflow.flow.lot.tray`, motor de pendientes `printflow.flow.pending`, playbook y la falla
> `printflow.flow.failure.over.reservation`) y **NO toca** el motor `x_product_dimensional_pricing`: lo
> **hereda/extiende** desde PrintFlow (`_inherit` + `super()`), igual que el anexo 3.H (`mrp.technical.sheet`).
> **Ningún flujo nativo se reemplaza ni se fuerza; código sí, datos no.**

**D1 — P1 (las DOS fallas son UNA, con causa raíz explícita) (CERRADA · sin claves nuevas en el payload).**
- **Por qué hoy salen "Independiente":** el caso es una cadena **INVERTIDA** respecto a `PF_CHAIN_SLOTS`
  (que va compras → … → inventario → **entrega**). Aquí la **RAÍZ es la ENTREGA** (reservó sin lote) y la
  **CONSECUENCIA es el INVENTARIO** (reserva colgada). `printflow.flow.presentation._pf_flow_edges` toma
  `root_slot = _PF_NODE_META[root_canvas_key]['chain']` y marca `consequence` SOLO a los slots **posteriores**
  al root ⇒ nunca hay consecuencia "hacia atrás" ⇒ ambos nodos quedan `independiente`.
- **Qué se hace (aditivo):** nuevo helper en `models/printflow_flow_strategy_product.py`
  `_pf_lot_coupled_roles(self, roles, statuses)` que, **solo** cuando se cumple el acoplamiento (abajo),
  devuelve los roles ajustados: `roles['delivery'] = 'root'` y `roles['inventory'] = 'consequence'`
  (limpiando el `root`/`independiente` previo de esos dos slots). Se aplica en `_pf_with_derived` **después**
  del cálculo normal de `roles`/`broken_slots`, sobre el MISMO dict (si no hay acoplamiento, **no hace nada** ⇒
  comportamiento actual intacto). El `root_slot` que consume la cabecera (`root_cause_node`) pasa a apuntar al
  nodo **Entrega** y `chain_summary` (`printflow.flow.canvas._pf_chain_summary`) se arma con la cadena ya
  invertida: *"Entrega (origen) → Inventario (consecuencia)"*, que es el texto que **YA pinta** la franja de
  cadena de la vista del producto (anexo 3.A / T6).
- **Condición de acoplamiento (sin hardcode):** el producto (u orden enfocada) tiene a la vez
  (1) estado de lote `lot_missing` en el nodo **Entrega** y (2) `data_anomaly` (reserva colgada) en el nodo
  **Inventario**, y el quant colgado está **sin lote** (`lot_id = False`) o su lote coincide con el **lote
  exclusivo esperado** del pedido. Se determina reutilizando `printflow.stock.health._pf_lot_state` y el
  helper PURO del motor `pf_quant_is_hanging_reservation` (cero reinvención, sin N+1: datos que el contexto de
  lote YA leyó).
- **Causa raíz EXPLÍCITA (texto):** dos puntos, ambos SIN claves nuevas de payload:
  1. `models/printflow_resolution_playbook.py::_pf_plan_lot_missing` → `summary`/`steps` dicen la causa y el
     paso correcto (p. ej. *"Sin lote: falta el lote exclusivo del pedido (S03275-L5356), que está vacío"*).
  2. `models/printflow_flow_lots.py` → el `summary` de la falla del nodo Entrega incorpora el **nombre del
     lote exclusivo esperado**, tomado del helper EXISTENTE del motor
     (`sale.order.line._get_exclusive_lot_name` / `stock.move._get_exclusive_delivery_lot`) vía las filas del
     tray (`_pf_row_lot_context`). Si no es determinable, el texto queda sin el nombre (neutro, no miente).
- **NO se añaden claves al nodo del payload** (`cause_note` descartado): el widget
  (`printflow_order_timeline.*`), `BASE_NODE_KEYS` (`test_product_flow_payload_parity.py`) y los candados de
  paridad quedan **INTACTOS**. La "causa raíz" viaja por `chain_summary` (ya pintado) + el texto del playbook.

**D2 — P2 (la bandeja lista TODAS las órdenes) (CERRADA · ADITIVO, CA-2 fija la superficie).**
- CA-2 ancla la verificación a `_pf_open_lot_tray` ⇒ se **extiende la bandeja CLÁSICA**, NO se abre una vista
  alterna. Se **AÑADE** (jamás se reemplaza) un constructor `_pf_rows_pending_orders(product, lot_info)` y se
  **suma** al resultado de `lot_missing` en `_pf_rows_for_state` (el mapa explícito `builders` sigue sin
  `getattr`; para `lot_missing` devuelve `_pf_rows_missing_moves(...) + _pf_rows_pending_orders(...)`).
- **Fuente ÚNICA de las órdenes:** `printflow.flow.pending._pf_node_pending_rows('delivery', [product.id])`
  (ya lee los `stock.move` de salida de los pickings ABIERTOS del producto; UNA sola lectura ⇒ sin N+1).
- **Una fila por ORDEN (picking) SIN lote asignado** en el producto. Las entregas SANAS (con lote, p. ej.
  WH/OUT/02974) **NO** se listan. En la BD real: 26 órdenes sin reserva + 1 con movimiento sin lote = **27
  filas nuevas** (se suman a la fila del movimiento ya creado que la bandeja ya producía, así el operador ve la
  dimensión completa ≈ los "28" del badge de H-016; ver O-5).
- **Fila (SOLO campos EXISTENTES del contrato `printflow.flow.lot.tray.line`):** `kind = 'pending_order'`
  (kind NUEVO), `label = _('Entrega %s') % picking.name`, `lot_name` = lote actual ('' si falta),
  `qty` = cantidad demandada, `state_label` = estado del picking (`_pf_state_label`), `detail` = "Sin lote: se
  espera el lote exclusivo del pedido (<pedido>-L<línea>) / sin reserva", `res_model='stock.picking'`
  (ya está en `_DOCUMENT_REF_MODELS`), `res_id=picking.id`, `picking_id`, `partner_id`, `scheduled_date`,
  `location_id`, `demand_qty`, `can_choose_lot=True`, `lot_id=False`.
- **Cableado explícito del nuevo kind** (sin `getattr`, con lista blanca):
  - `_compute_lot_action_mode`: `kind == 'pending_order'` → `'assign'` (rama EXPLÍCITA).
  - `_pf_search_lot_action_mode`: añadir `'pending_order'` a la lista del modo `assign` (para que el filtro de
    la vista no lo pierda).
  - `_pf_document_move(kind, res_model, res_id, …)`: para `pending_order` con `res_model='stock.picking'`,
    resolver el `stock.move` del picking (UNA búsqueda acotada `limit=1`) ⇒ `_pf_row_lot_context` trae el
    **lote exclusivo esperado** (`own_lot_name`) y el pedido. `_pf_annotate_lot_quantities` NO cambia.
- **La acción de la CABECERA no cambia** (sigue siendo el remedio EXISTENTE del estado `lot_missing`,
  `printflow.product.flow._pf_execute_lot_remedio`) y **por fila** se ofrece el selector de lote EXISTENTE
  (`action_open_lot_picker`, por documento). **NO** se escribe ni se valida nada por detrás.

**D3 — P3 (botón honesto) (CERRADA · renombrar, mínimo cambio).**
- El ítem que señala `lot_missing` es un **MOVIMIENTO**, pero el target `quants` abre **EXISTENCIAS**. Se
  **RENOMBRA** la etiqueta del "problem" en `_pf_plan_lot_missing` a **"Ver existencias por lote"** (coherente
  con el destino `quants`; es el MISMO rótulo que ya usa `_pf_plan_lot_no_stock`). **NO** se crea un target de
  navegación nuevo ⇒ `_pf_action`/`_pf_run_action`, el vocabulario del widget y el contrato del payload quedan
  **intactos**. CA-3 admite explícitamente esta vía.

**D4 — P4 (saneo ACOTADO) (CERRADA · desde PrintFlow, motor INTACTO ⇒ sin autorización del dueño).**
- **El problema:** `x_product_dimensional_pricing::printflow.stock.remedy._pf_cleanup_product_reservations`
  localiza las **ubicaciones** con reserva colgada y suelta **TODOS** los `move_ids` de los pickings que
  reservan ahí (`_pf_unreserve_reservation()` + `action_assign()`). Como el producto es de entrega EXCLUSIVA
  por lote, la entrega SANA (02974 con el lote 666634) comparte ubicación (WH/Stock) ⇒ se re-asigna contra su
  lote exclusivo vacío y **queda sin lote** (H-022).
- **Qué se hace:** **CREAR** en PrintFlow `models/printflow_stock_remedy.py` con
  `_inherit = 'printflow.stock.remedy'` (mismo patrón ADITIVO del anexo 3.H: la clase del motor queda
  intacta; PrintFlow solo agrega un método) y un método NUEVO
  `_pf_release_hanging_lot_reservation(self, product)` que:
  1. `self._pf_assert_can_clean()` — **guardia EXISTENTE** (jefe de taller/admin), sin excepción.
  2. Localiza los quants colgados del producto con el helper PURO del motor
     `pf_quant_is_hanging_reservation(quantity, reserved_quantity)` (UNA `search_read` de `stock.quant`
     internos del producto).
  3. Selecciona SOLO las `stock.move.line` activas del producto (`state not in ('done','cancel')`,
     `quantity > _EPS`) cuya **ubicación** es de un quant colgado **y** cuyo **lote coincide** con el del quant
     colgado (`lot_id` igual, `False` incluido ⇒ el caso real: quant sin lote).
  4. **GUARDIA anti-entrega-sana:** sólo se sueltan líneas **sin lote** (`lot_id = False`) o cuyo lote **NO
     tiene existencia** (`< _EPS`). Una línea respaldada por stock real de un lote con existencia **NUNCA** se
     suelta ⇒ la entrega sana con su excepción queda intacta (CA-4).
  5. Suelta esas líneas con la primitiva EXISTENTE `stock.move._pf_unreserve_reservation()` y **re-reserva por
     las reglas NATIVAS de Odoo** (`picking.action_assign()`) — nada de reservar a mano.
  6. Devuelve el **MISMO contrato** del motor (`{'cleaned_pickings': [...], 'still_negative': bool}`) + bitácora
     (`message_post`), para que la falla lo consuma sin cambiar su forma.
- **La falla** `models/printflow_flow_failure_over_reservation.py` apunta su acción `release_reservation` al
  método ACOTADO; el resto de su contrato (evidencias/acciones `view_quant`/`leave`/guardia) **NO** cambia.
- **El método del MOTOR queda INTACTO** (lo siguen usando el cron/otros llamadores) ⇒ **cero cambios en
  `x_product_dimensional_pricing`** ⇒ **NO requiere autorización del dueño** (la regla "motor SOLO LECTURA"
  se respeta: se hereda, no se edita).

**D5 — Impacto en tests/candados (CERRADA · cambios DELIBERADOS, verificados por lectura).**
- **SIN CAMBIOS y siguen VERDES** (leyendo las aserciones reales):
  - `test_product_flow_lot_tray.py` (`test_other_kinds_keep_choose_lot`: usa `assertTrue(missing)` y
    `all(can_choose_lot)` ⇒ tolera filas nuevas con `can_choose_lot=True`).
  - `test_product_flow_lot_tray_document.py` (filtra por `res_model`/`res_id` con `_row_for` ⇒ tolera filas
    nuevas; `lot_action_mode == {'assign'}` se conserva porque `pending_order` también es `assign`).
  - `test_product_flow_lot_reassign_per_document.py`, `test_product_flow_lot_tray_authorize.py`,
    `test_product_flow_lot_picker*.py`, `test_product_flow_lot_remedy_permissions.py`,
    `test_finding_exception_formal.py`, `test_lot_management.py`, `test_flow_canvas_parity.py`,
    `test_product_flow_payload_parity.py` (SIN claves nuevas), `test_diagnostic_*`.
- **CREAR** (y registrar en `tests/__init__.py`): `tests/test_product_flow_lot_coupled_chain.py` (P1),
  `tests/test_product_flow_lot_tray_orders.py` (P2 + P3), `tests/test_product_flow_over_reservation_scoped.py`
  (P4).
- Si algún candado **text-based** del `summary`/`chain_summary` resultara afectado, se actualiza de forma
  DELIBERADA y se documenta en la bitácora del Dev.
- **B1 (rojos pre-existentes: `test_product_flow_lot_tray_ux` [4≠3], `test_diagnostic_delivery_orders`,
  `test_node_pending_enumeration.test_limit_is_per_node`, etc.) NO se toca**: es baseline ajeno; el Dev deja
  constancia de que su lote no los altera (no debería tocarlos).

**D6 — Alcance del P2 (CERRADA · solo LISTAR/decidir, NO aplicar en bloque).**
- El "resolver en bloque" del P2 se ACOTA a: (a) **ver** la dimensión real (una fila por orden) y (b) **decidir
  por fila** (abrir el selector de lote EXISTENTE, que ya trabaja por documento). **NO** se aplica lote a varias
  órdenes de un solo golpe: la asignación REAL de lotes es **DATOS** (O-1/H-018) y el código solo muestra y
  facilita. Ningún remedio asigna a un pedido el lote de otro cliente (los lotes nunca se mezclan).

### 3.6 Archivos (confirmados por el Planificador)

| Acción | Archivo | Qué se cambia |
|---|---|---|
| MODIFICAR | `models/printflow_flow_strategy_product.py` | **P1:** helper `_pf_lot_coupled_roles` + cableado en `_pf_with_derived` (RAÍZ=Entrega → CONSECUENCIA=Inventario). (T1) |
| MODIFICAR | `models/printflow_flow_lots.py` | **P1:** `summary` de la falla del nodo Entrega con el lote exclusivo esperado. (T2) |
| MODIFICAR | `models/printflow_resolution_playbook.py` | **P1:** `summary`/`steps` de `_pf_plan_lot_missing` con la causa raíz. **P3:** rótulo del "problem" → "Ver existencias por lote". (T2/T4) |
| MODIFICAR | `wizard/printflow_flow_lot_tray.py` | **P2:** constructor `_pf_rows_pending_orders`, unión en `_pf_rows_for_state` y cableado del kind `pending_order` (`_compute_lot_action_mode`, `_pf_search_lot_action_mode`, `_pf_document_move`). (T5) |
| MODIFICAR (si aplica) | `wizard/printflow_flow_lot_tray_views.xml` | **P2:** solo si la vista debe conocer el kind nuevo (filtro/columna). Mínimo; probablemente **SIN CAMBIOS**. (T5) |
| CREAR | `models/printflow_stock_remedy.py` | **P4:** `_inherit='printflow.stock.remedy'` + `_pf_release_hanging_lot_reservation` (saneo ACOTADO). (T7) |
| MODIFICAR | `models/printflow_flow_failure_over_reservation.py` | **P4:** `release_reservation` → método acotado. (T8) |
| MODIFICAR | `models/__init__.py` | Importar `printflow_stock_remedy`. (T8) |
| CREAR | `tests/test_product_flow_lot_coupled_chain.py` · `tests/test_product_flow_lot_tray_orders.py` · `tests/test_product_flow_over_reservation_scoped.py` (+ `tests/__init__.py`) | Fijan CA-1..CA-4. (T3/T6/T9) |

**SIN CAMBIOS (a propósito):** motor `x_product_dimensional_pricing` (**INTACTO**: solo se hereda
`printflow.stock.remedy` y se leen `printflow.stock.health` y sus helpers puros); bandeja GUIADA
(`printflow.flow.failure.tray`, contrato/vistas/widget); widget `printflow_order_timeline.*` y el builder
(no hay claves nuevas de payload); casos `lot_orphan_reservation`/`data_anomaly`/`lot_no_stock` (H-019);
`printflow.flow.pending` (solo se CONSUME); `__manifest__.py` y `security/` (los modelos nuevos son
`AbstractModel`/`_inherit` sin tabla propia ⇒ sin filas de ACL).

### 3.7 Restricciones duras

- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): PROHIBIDO `cr.execute` de escritura / `cr.commit()`.
- **No forzar ni reinventar flujos nativos** (entrega/reserva de lote): se **reutiliza** el saneo EXISTENTE con su guardia.
- **NO tocar el motor** `x_product_dimensional_pricing` (SOLO LECTURA/reutilización; **D4 CERRADA**: el saneo acotado se hace por `_inherit` desde PrintFlow ⇒ **sin cambios en el motor** y **sin autorización del dueño**).
- **NO romper** la paridad del PEDIDO, la bandeja clásica, `lot_no_stock` (H-019) ni los casos `data_anomaly`/`lot_orphan_reservation`.
- Convenciones OCA (`odoo-17-clean-architecture` §2.5). **`models/` nunca importa `wizard/`.** **Sin N+1.**

### 3.8 Criterios de aceptación verificables

| # | Criterio | Verificación |
|---|---|---|
| CA-1 | **P1:** el diagrama del producto muestra Entrega + Inventario como **una misma falla** (cadena RAÍZ=Entrega → CONSECUENCIA=Inventario) con **causa raíz** explícita (lote exclusivo vacío) en el `summary`/`chain_summary`. | Test (T3): con un caso acoplado (movimiento sin lote + quant colgado sin lote del MISMO producto) → `payload['global']['chain_summary']` nombra ambas etiquetas y el nodo `stock` sale `consequence` (no `independiente`); el `summary` del nodo Entrega nombra el lote esperado. **Caso NO acoplado → todo igual que hoy.** |
| CA-2 | **P2:** el "Solucionar" del nodo Entrega lista las **órdenes pendientes** (una fila por orden sin lote, incluidas las que NO tienen `move_line`), no solo 1. | Test (T6): `_pf_open_lot_tray(product,'lot_missing')` → hay **≥1 fila `kind='pending_order'` con `res_model='stock.picking'`** por cada entrega pendiente sin lote; la entrega SANA (con lote) NO aparece; el nº de filas ≫ 1. |
| CA-3 | **P3:** el rótulo del botón coincide con su destino (`quants`). | Test (T6): el "problem" de `_pf_plan_lot_missing` se llama **"Ver existencias por lote"** y su `target` sigue `quants`. |
| CA-4 | **P4:** "Liberar y re-reservar" NO altera la reserva de una entrega SANA de la misma ubicación. | Test (T9): escenario con 2 líneas (una SANA con lote CON existencia + una colgada sin lote) → tras el saneo acotado, la línea sana conserva su lote y su `reserved`; solo se libera la colgada. |
| CA-5 | Paridad del PEDIDO + bandeja clásica + bandeja guiada + `lot_no_stock` intactas; SOLO LECTURA (salvo el saneo EXISTENTE con guardia). | `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; motor `x_product_dimensional_pricing` sin cambios; candados verdes. |

### 3.9 Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| P1 rompe el contrato del payload/widget | Alto | Cambios **aditivos** (SIN claves nuevas); la causa viaja por `chain_summary` ya pintado; candados de paridad (`test_product_flow_payload_parity`, `test_flow_canvas_parity`). |
| P1 marca "acoplada" una cadena que NO lo es (falso positivo) | Medio | Condición estricta (movimiento sin lote **+** quant colgado del MISMO producto y sin lote/lote esperado); CA-1 exige que el caso NO acoplado quede igual. |
| P2 rompe la bandeja clásica y sus tests | Alto | **Extender** (sumar filas), nunca reemplazar; `kind` nuevo a listas blancas; candados `test_product_flow_lot_tray*` verificados por aserción (D5). |
| P4 toca el motor sin autorización | Alto | D4: `_inherit` desde PrintFlow; `_pf_cleanup_product_reservations` del motor **intacto** ⇒ sin autorización. |
| P4 deja "colgada" una reserva que sí había que soltar | Medio | Guardia anti-entrega-sana solo excluye líneas con lote CON existencia; CA-4 con 2 líneas lo fija. |
| P2 introduce N+1 (28 órdenes) | Medio | UNA lectura batch de `printflow.flow.pending._pf_node_pending_rows('delivery', …)`. |
| Tocar datos al "resolver" | Crítico | Solo LECTURA; la ÚNICA escritura es el saneo EXISTENTE con guardia; `TransactionCase`. |
| Renombrar P3 rompe un candado de texto | Bajo | Verificado: la cadena "Ver movimientos sin lote" solo vive en el playbook (L920) y en docs; ningún test la fija. |

### 3.10 Observaciones (fuera de alcance)

- **O-1:** la asignación REAL de lotes a las 26 entregas es **datos** (H-018); el código solo muestra/facilita.
- **O-2:** H-021 ("Autorizar excepción" ≠ "Asignar lote" y saneo por documento) queda como **fase 2**.
- **O-3:** H-017 (`dwqdqwd`) ya lo resolvió el operador por datos; no se toca.
- **O-4:** H-016 (badge 28 vs lista 1) es el mismo eje que P2; se resuelve de la mano: tras T5 la bandeja lista
  las órdenes, así el conteo del badge (28 movimientos) y las filas (~28) quedan alineados en magnitud.
- **O-5:** la fila del MOVIMIENTO sin lote (1) y las filas por ORDEN (27) pueden solaparse conceptualmente en la
  misma entrega (S03275). Se conservan AMBAS a propósito (el movimiento es la evidencia técnica; la orden es la
  dimensión operativa) y **no se deduplican**, para no romper candados ni ocultar el caso real.

### 3.11 Plan de ejecución atómico y secuencial (T1–T9)

> **Ejecución por LOTES de máximo 3 tareas; cada lote = una sesión NUEVA de `odoo-dev`.** El plan es
> **COMPLETO** (todo lo que hay que hacer sale de aquí). Convenciones OCA (`odoo-17-clean-architecture` §2.5):
> un archivo por modelo, métodos `_pf_*`, `snake_case`, imports por bloques, orden del modelo
> (atributos → campos → constraints → default → compute → onchange → CRUD → acciones → negocio), nodo `<odoo>`.
> Regla: **código sí, datos no**; PROHIBIDO `cr.execute` de escritura y `cr.commit()`. **No forzar ni
> reemplazar flujos nativos; código sí, datos no.** El Dev marca `[x]` al cerrar cada tarea y deja bitácora.

#### Lote 1 (T1–T3) — P1: las dos fallas como UNA, con causa raíz

- [x] **T1 — Cadena invertida en la estrategia del PRODUCTO.**
  - Archivo: `models/printflow_flow_strategy_product.py`.
  - Añadir el helper `_pf_lot_coupled_roles(self, roles, statuses)` (sección de helpers del producto, junto a
    `_pf_lot_failures`): devuelve una COPIA de `roles` con `delivery='root'` e `inventory='consequence'` SOLO
    si se cumple el acoplamiento (D1); si no, devuelve `roles` sin tocar.
  - Detección del acoplamiento reutilizando SOLO lo ya leído: `statuses` con Entrega en falla y `stock` en
    `data_anomaly` + el quant colgado **sin lote** (`lot_id=False`) o con el lote esperado, vía el helper PURO
    `pf_quant_is_hanging_reservation` (importado del motor). SIN lecturas nuevas (nada de N+1).
  - Cablear en `_pf_with_derived`: tras calcular `roles`/`broken_slots`,
    `roles = self._pf_lot_coupled_roles(roles, statuses)` y recalcular `root_slot` con el criterio EXISTENTE
    (el slot `root`), para que `root_cause_node` apunte a **Entrega**.
  - NO tocar `_pf_flow_edges`, `PF_CHAIN_SLOTS` ni la estrategia del PEDIDO.
- [x] **T2 — Causa raíz explícita (texto).**
  - Archivos: `models/printflow_flow_lots.py` y `models/printflow_resolution_playbook.py`.
  - `printflow_flow_lots.py`: en el `summary` de la falla del nodo **Entrega** (estado `lot_missing`), añadir
    el **lote exclusivo esperado** cuando sea determinable, reutilizando el helper del motor
    `sale.order.line._get_exclusive_lot_name` / `stock.move._get_exclusive_delivery_lot` sobre los datos que
    `_pf_row_lot_context` YA tiene (el pedido/línea de las filas del tray). Sin lecturas nuevas ni N+1; si no
    es determinable, texto neutro (no inventar).
  - `printflow_resolution_playbook.py::_pf_plan_lot_missing`: `summary` y `steps` explican que Entrega e
    Inventario son **la MISMA falla** (raíz = entrega reservada sin lote; consecuencia = reserva colgada) y el
    paso correcto (asignar el lote exclusivo del pedido / liberar la reserva colgada). SIN tocar los `target`
    de las acciones (eso es T4).
- [x] **T3 — Test CA-1.**
  - **CREAR** `tests/test_product_flow_lot_coupled_chain.py` y registrarlo en `tests/__init__.py`
    (`TransactionCase`; rollback). Escenario: producto `tracking='lot'` `x_is_printflow_managed=True` con un
    albarán de salida que reserva SIN lote (movimiento sin lote) + quant colgado sin lote del MISMO producto
    (patrón de `test_product_flow_failure_over_reservation.py` / `test_product_flow_lot_actions.py`).
    - CA-1a (acoplado): `payload = _pf_build_payload(wizard, 'product')` →
      `payload['global']['chain_summary']` nombra **Entrega** y **Inventario**; el nodo `stock` trae
      `chain == 'consequence'` (no `independiente`) y el nodo `delivery` `chain == 'root'`.
    - CA-1b (NO acoplado): sin el quant colgado (o con la reserva sana) → los roles quedan como HOY
      (no se inventa cadena) — candado de no-regresión.
    - CA-1c: el `summary` del nodo Entrega menciona el lote esperado cuando el helper lo puede determinar.
  - Solo LECTURA; sin `cr.execute`/`cr.commit`.

#### Lote 2 (T4–T6) — P2 + P3: la bandeja lista las órdenes + botón honesto

- [x] **T4 — P3: renombrar el botón.**
  - Archivo: `models/printflow_resolution_playbook.py`, `_pf_plan_lot_missing`.
  - Cambiar la etiqueta del ítem "problem" de `_('Ver movimientos sin lote')` a
    `_('Ver existencias por lote')`. El `target` sigue `'quants'`. NO se toca `_pf_action`/`_pf_run_action`.
- [x] **T5 — P2: filas por ORDEN pendiente en la bandeja clásica.**
  - Archivo: `wizard/printflow_flow_lot_tray.py`.
  - Nuevo constructor `_pf_rows_pending_orders(self, product, lot_info)`: UNA lectura
    `printflow.flow.pending._pf_node_pending_rows('delivery', [product.id])`; por cada orden (picking) del
    producto **SIN lote asignado**, construir la fila `kind='pending_order'` con SOLO los campos EXISTENTES del
    contrato `printflow.flow.lot.tray.line` (ver D2). Excluir las entregas que YA tienen lote.
  - `_pf_rows_for_state` (mapa `builders`, `lot_missing`): devolver
    `self._pf_rows_missing_moves(...) + self._pf_rows_pending_orders(product, lot_info)` (SUMA, no reemplazo).
  - Cableado del kind nuevo en las 3 funciones con lista blanca: `_compute_lot_action_mode` (→ `'assign'`
    explícito), `_pf_search_lot_action_mode` (añadirlo al modo `assign`) y `_pf_document_move`
    (`res_model='stock.picking'` → resolver el `stock.move` del picking con `limit=1`).
  - `wizard/printflow_flow_lot_tray_views.xml`: solo si hace falta (filtro/columna). **Preferible SIN CAMBIOS.**
  - NO escribir/validar por detrás; NO tocar `action_open_lot_picker`/`action_apply_correction` ni el remedio.
- [x] **T6 — Test CA-2 + CA-3.**
  - **CREAR** `tests/test_product_flow_lot_tray_orders.py` y registrarlo en `tests/__init__.py`.
    - CA-2: producto con N entregas de salida pendientes SIN lote (una con `move_line` sin lote, varias sin
      `move_line`) + UNA entrega SANA con lote con existencia →
      `wizard.action_run_pf_plan('lot_missing', 'solution', product.id)` abre `printflow.flow.lot.tray` y
      `tray.line_ids` contiene **≥1 fila `kind='pending_order'` con `res_model='stock.picking'`** por cada
      orden sin lote; la SANA **no** aparece; esas filas resuelven a modo `assign`.
    - CA-3: el "problem" de `_pf_plan_lot_missing` es **"Ver existencias por lote"** y su `target` es `quants`.
    - Candado de no-regresión: la bandeja sigue trayendo la fila del MOVIMIENTO sin lote que ya traía.

#### Lote 3 (T7–T9) — P4: saneo acotado

- [x] **T7 — CREAR el saneo acotado en PrintFlow.**
  - Archivo: **CREAR** `models/printflow_stock_remedy.py` (`_inherit = 'printflow.stock.remedy'`; docstring del
    "por qué": acotar el saneo para no des-asignar entregas sanas de la misma ubicación).
  - Método `_pf_release_hanging_lot_reservation(self, product)` según D4: guardia `_pf_assert_can_clean`;
    localizar quants colgados con `pf_quant_is_hanging_reservation`; seleccionar SOLO las move lines de esos
    quants con lote coincidente; **guardia anti-entrega-sana** (solo sin lote o con lote sin existencia);
    `_pf_unreserve_reservation()` + `picking.action_assign()`; devolver el MISMO contrato del motor +
    `message_post`.
  - Reutilizar las primitivas EXISTENTES del motor (`pf_quant_is_hanging_reservation`,
    `stock.move._pf_unreserve_reservation`, `_pf_assert_can_clean`); NO reimplementar; NO `cr.execute`/`cr.commit`;
    sin N+1 (una `search_read` de quants + una búsqueda de move lines).
- [x] **T8 — Apuntar la falla al método acotado + registrar el modelo.**
  - Archivos: `models/printflow_flow_failure_over_reservation.py` y `models/__init__.py`.
  - `release_reservation`: sustituir la llamada al motor `_pf_cleanup_product_reservations` por
    `self.env['printflow.stock.remedy']._pf_release_hanging_lot_reservation(product)` (MISMO contrato de
    retorno). NO cambiar evidencias/acciones/guardia.
  - `models/__init__.py`: importar `printflow_stock_remedy` (sección de modelos del motor heredados), con
    comentario del motivo. `models/` no importa `wizard/`.
- [x] **T9 — Test CA-4.**
  - **CREAR** `tests/test_product_flow_over_reservation_scoped.py` y registrarlo en `tests/__init__.py`.
    - CA-4: producto `tracking='lot'`; escenario con **2 entregas de salida en la MISMA ubicación**: (a) SANA
      con su lote exclusivo CON existencia reservada; (b) COLGADA sin lote (quant con `reserved > 0` y
      `quantity = 0`). Ejecutar la acción `release_reservation` de la falla `data_anomaly` →
      (a) conserva `lot_id` y su `reserved`; (b) se libera/re-asigna por reglas NATIVAS. El retorno trae
      `cleaned_pickings` con la colgada y NO altera la sana.
    - Candado: el método del MOTOR sigue existiendo/intacto (no se reemplazó; solo se heredó).
    - `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`.

**Verificación (turno del Verificador, fuera del dev).** `--test-tags` sobre
`/printflow_gestion_inventario:TestProductFlowLotCoupledChain`, `...:TestProductFlowLotTrayOrders`,
`...:TestProductFlowOverReservationScoped` y los candados `...:TestProductFlowLotTray`,
`...:TestProductFlowLotTrayDocument`, `...:TestProductFlowLotTrayAuthorize`, `...:TestProductFlowLotActions`,
`...:TestProductFlowLotRemedyPermissions`, `...:TestFlowCanvasParity`, `...:TestProductFlowPayloadParity`,
`...:TestDiagnosticTimelinePayload`, `...:TestFindingExceptionFormal`. Al hilo solo vuelve el exit code, N/N y,
si falla, la aserción + cola del traceback. **B1 (rojos pre-existentes) NO cuenta como fallo de esta tarea.**

### 3.12 Contratos que NO deben romperse

- CA-1..CA-5 de 3.8.
- Firma/forma de `printflow.flow.canvas._pf_build_payload(host, mode)` y del builder
  (`printflow_flow_payload_builder.py`): **SIN claves nuevas** por nodo (`BASE_NODE_KEYS` intacto).
- Widget `printflow_order_timeline.*` y `printflow_open_timeline.*`: **SIN cambios**.
- Contrato de la bandeja clásica `printflow.flow.lot.tray.line` (`_pf_populate`, `action_run`,
  `_pf_rows_for_state`, `_compute_lot_action_mode`, `_pf_search_lot_action_mode`, `_pf_document_move`): solo se
  **AÑADE** un `kind` (`pending_order`) y un constructor; el resto de kinds/columnas/acciones quedan igual.
- `printflow.flow.pending._pf_node_pending_rows` y `PURCHASE_UNCONFIRMED_STATES`: **SIN cambios** (solo se
  consumen).
- Playbook: solo cambian el `summary`/`steps` de `_pf_plan_lot_missing` y el rótulo de su "problem"; los
  `target`/`kind` y el resto de planes quedan **intactos**.
- Falla `printflow.flow.failure.over.reservation`: evidencias/acciones (`view_quant`/`leave`)/guardia
  **intactas**; solo cambia el DESTINO de `release_reservation` (método acotado, MISMO contrato de retorno).
- Guardias de permisos: `printflow.stock.remedy._pf_assert_can_clean` / `_pf_assert_can_reconcile` **intactas**
  y **obligatorias** antes de cualquier escritura.
- Motor `x_product_dimensional_pricing`: **SIN CAMBIOS** (se hereda `printflow.stock.remedy`; se leen
  `printflow.stock.health` y helpers puros). `_pf_cleanup_product_reservations` **intacto**.
- Paridad del PEDIDO, bandeja guiada (`printflow.flow.failure.tray`) y casos
  `lot_orphan_reservation`/`data_anomaly`/`lot_no_stock`: **intactos**.
- `models/` nunca importa `wizard/`. Sin `cr.execute`/`cr.commit`. Sin N+1.

---

## 3.I (ANEXO · TAREA CERRADA) — La bandeja guiada de fallas no cubría `lot_no_stock`

> **Turno:** Odoo Analista (cierre de ciclo). **Estado:** CERRADA (Verificador: `cumple`; Dev exit 0, **41/41 verdes** + corrida acotada `20/20`; hallazgo **H-019** resuelto). PLAN COMPLETO (D1-D6; T1-T4 en 2 lotes, todos `[x]`).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow) · `C:\odoo_custom\x_product_dimensional_pricing` (motor; **SOLO LECTURA**).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **GRANDE** (toca el flujo de
> inventario/entregas). Cadena: Analista → Planificador → Analista → Dev (por lotes) → Verificador → Analista.

### 3.1 Problema (evidencia en el código y en la BD)
La **bandeja GUIADA de fallas** (`printflow.flow.failure.tray`, menú "Bandejas de fallas"; el dueño la usó con
**FONDO NEGRO**) NO se activa para el producto `IMPRESION BANNER ` (id 13571): el nodo **Entrega** está en estado
**"Lote sin existencia"** (`lot_no_stock`) y al pulsar **"Solucionar"** el sistema NO abre esa bandeja, sino la
**bandeja CLÁSICA** de lote (`printflow.flow.lot.tray`).

Causa raíz (código):
1. `printflow_product_flow.action_run_pf_plan(which='solution')` (L269-291): si la causa es de lote, decide entre la
   **bandeja guiada** y la **clásica** con `_pf_use_guided_failure_tray(cause, product_id)`.
2. `_pf_use_guided_failure_tray` (L318-336) exige `cause in Registry._pf_supported()`; si no, devuelve `False` ⇒ clásica.
3. `printflow.flow.failure.registry._pf_registry()` (L45-58) mapea **SOLO DOS** códigos:
   - `'lot_orphan_reservation'` → `printflow.flow.failure.lot.orphan`
   - `'data_anomaly'` → `printflow.flow.failure.over.reservation` ← **caso FONDO NEGRO** (reserva colgada)
4. La causa del banner es **`lot_no_stock`** (lote reservado SIN existencia) ⇒ **no está en el mapa** ⇒ nunca abre la guiada.

Evidencia:
| Dato | Valor |
|---|---|
| Causa del nodo Entrega del banner | **`lot_no_stock`** ("Lote sin existencia"; `HALLAZGOS.md` H-018) |
| Registro de fallas hoy | `['lot_orphan_reservation', 'data_anomaly']` |
| FONDO NEGRO | `data_anomaly` (reserva colgada) — product **13058**, quant **15197**; `tests/test_product_flow_failure_over_reservation.py` |
| Interruptor `x_product_dimensional_pricing.pf_failure_guided_tray` | **NO definido** ⇒ default `0` (apagado) |
| Aviso `x_product_dimensional_pricing.pf_lot_missing_action` | **NO definido** ⇒ default `warn` (solo log) |

### 3.2 Objetivo (acotado)
**SÍ:**
1. Que el caso **`lot_no_stock`** (y los estados de lote que el Planificador cierre como "gestionables") abran la
   **bandeja GUIADA de fallas** al pulsar "Solucionar", con evidencias + acciones guiadas (mismo patrón que FONDO NEGRO).
2. Que las acciones guiadas de esa falla resuelvan la causa reutilizando el saneo EXISTENTE (`assign_lot` /
   `reconcile_lot_reservation`, ver 3.4) **sin inventar** correcciones nuevas.
3. Conservar INTACTOS los 2 casos ya funcionando (`lot_orphan_reservation`, `data_anomaly` / FONDO NEGRO).

**NO:**
- NO tocar el motor `x_product_dimensional_pricing` (SOLO LECTURA; se hereda/reutiliza).
- NO escribir datos: la bandeja solo LISTA/navega; la escritura vive en las acciones con su guardia de permisos
  (como hoy). Es tarea de diseño+registro, NO de saneamiento por datos.
- NO forzar ni reinventar flujos nativos (sin `cr.execute`/`cr.commit`).
- NO romper la bandeja clásica de lote (sigue siendo el fallback).

### 3.3 Contrato funcional
| Superficie | Debe quedar |
|---|---|
| "Solucionar" de una fila con causa `lot_no_stock` (diagrama de PRODUCTO) | Abre la **bandeja guiada** (`printflow.flow.failure.tray`) con evidencias + acciones. |
| Registro de fallas | `lot_no_stock` **mapeado** (modelo de falla nuevo o reutilización del de reserva colgada; lo cierra el Planificador). |
| Casos ya soportados | `lot_orphan_reservation` y `data_anomaly` **INTACTOS**. |
| Bandeja clásica de lote | Sigue disponible como fallback (no se elimina). |
| Diagrama de PEDIDO | No debe romperse (paridad). |
| Motor `x_product_dimensional_pricing` | **SIN CAMBIOS**. |

### 3.4 Fuente ÚNICA / patrón a reutilizar (cero reinvención)
- Bandeja guiada: `wizard/printflow_flow_failure_tray*.py|xml` y contrato `models/printflow_flow_failure.py`.
- Fallas existentes (modelos): `printflow.flow.failure.lot.orphan`, `printflow.flow.failure.over.reservation`,
  `printflow.flow.failure.generic`.
- Registro (punto de extensión): `models/printflow_flow_failure_registry.py::_pf_registry`.
- Saneos EXISTENTES: `printflow.stock.remedy` (`_pf_reassign_by_lot`, `_pf_replace_generic_lot`,
  `_pf_repair_finished_lot`), `printflow.inventory.health._pf_assign_lots_to_moves`,
  `stock.move._pf_auto_assign_lot` (motor, SOLO uso), `printflow.product.flow._pf_assign_lot_to_document`
  (selector de lote por documento, `wizard/printflow_flow_lot_picker.py::action_assign_lot`).
- Vocabulario/estados de lote: `models/printflow_flow_lots.py::LOT_PRODUCT_FALLBACK`, `_LOT_STATE_SEVERITY`.

### 3.5 Decisiones de diseño cerradas (D1-D6)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` · Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no** (SOLO LECTURA: `search`/`read`). El diseño se **engancha** al patrón de fallas guiadas YA EXISTENTE (`printflow.flow.failure.registry` + `printflow.flow.failure.*` + `printflow.flow.failure.tray`) y **NO toca** el motor `x_product_dimensional_pricing` (solo lo lee/reutiliza). **Sin cambios a la estructura de la bandeja** (contrato, vistas y widget INTACTOS): solo se AÑADE una falla al punto de extensión y se MAPEA el código.

**D1 - Modelo NUEVO (CERRADA · crear `printflow.flow.failure.lot.no.stock`).**
- Se crea una falla NUEVA; **NO** se reutiliza `printflow.flow.failure.over.reservation` (reserva colgada).
- Fundamento: `lot_no_stock` y `data_anomaly` son PRIMOS pero NO iguales. El motor los separa como estados distintos (`printflow.stock.health._pf_lot_state_from_rows`; precedencia: huérfana > sin lote > **sin existencia** > genérico > mezcla > terminado sin lote). `data_anomaly` = quant con `reservado > físico` (reserva colgada); `lot_no_stock` = `no_stock_lot_ids` (lote asignado en una `stock.move.line` activa cuyo stock total del lote es `<= _EPS`). Evidencia distinta => evidencias y ejecución distintas. Reutilizar la de reserva colgada obligaría a ramificar su `_pf_fault_detect`/`_pf_fault_evidences`/`_pf_fault_execute` por el `code`, violando "una falla = un modelo". El propio contrato (`models/printflow_flow_failure.py`) dice: *"agregar una falla nueva NO toca la bandeja ni el diagrama; basta con mapear el código aquí y crear el modelo"*.

**D2 - Alcance: SOLO `lot_no_stock` (CERRADA).**
- Se mapea **ÚNICAMENTE** `lot_no_stock`. Los demás estados (`lot_missing`, `lot_generic`, `lot_mixed`, `lot_unassigned_finished`) **conservan INTACTA la bandeja clásica de lote** (`printflow.flow.lot.tray`), que ya ofrece elegir lote y corrección automática.
- Por qué: CA-1..CA-4 solo exigen `lot_no_stock`; mapear de más multiplicaría el riesgo y exigiría decidir un saneo por estado. Queda como EXTENSIÓN FUTURA (cada estado "gestionable" se agrega con el MISMO molde: modelo + línea en el mapa).
- El fallback se preserva por construcción: `_pf_use_guided_failure_tray` devuelve `False` para cualquier código NO mapeado, y `_pf_open_failure_tray` cae a la bandeja clásica si la falla no está presente (sin evidencias). La paridad del PEDIDO NO cambia: `printflow_order_diagnostic_failure._pf_open_registered_failure_tray` EXCLUYE explícitamente las causas de lote (`_pf_is_lot_cause`).

**D3 - Acciones guiadas por fila y evidencias (CERRADA · reutiliza saneo EXISTENTE).**
- **Evidencias: UNA fila por LOTE afectado** (`no_stock_lot_ids`), con lote, ubicación(es) con reserva, físico/reservado/respaldo y los DOCUMENTOS que lo retienen. Se leen del MISMO motor que usa la bandeja clásica (cero reinvención): `printflow.stock.health._pf_lot_state` -> `no_stock_lot_ids`, aplicando el filtro de excepciones AUTORIZADAS (`printflow.finding.exception.filter._pf_apply_to_lot_info`) para no pintar lo ya declarado intencional (mismo criterio de la clásica).
- **Acciones** (solo las que la bandeja ya despacha; `kind` en `execute`/`navigate`/`close`):
  - `reassign` (**PRINCIPAL**, `execute`): reutiliza la primitiva EXISTENTE `printflow.stock.health._pf_reassign_by_lot(product)` -- la MISMA que ejecuta el remedio `reconcile_lot_reservation` del motor (`_pf_execute_lot_remedy`). Suelta y re-reserva por las reglas de Odoo; **NUNCA reserva un lote vacío** => resuelve la causa. Guardia EXISTENTE `printflow.stock.remedy._pf_assert_can_clean()` (jefe de taller/admin). Etiqueta reutilizada del mapa de remedios (`_pf_remedy_meta('reconcile_lot_reservation')`).
  - `view_supporting_moves` (`navigate`): abre las `stock.move.line` que retienen el lote (lo resuelve la bandeja con la fila; SOLO LECTURA).
  - `leave` (`close`): cierra.
- **NO** se inventa corrección: la única acción con EFECTO es el saneo EXISTENTE, con su guardia. NO se ofrece `view_quant` (la fila apunta al LOTE, no a un quant; un lote sin existencia puede no tener quant, y `_pf_nav_action` de la bandeja solo conoce `view_quant`/`view_supporting_moves`).

**D4 - Parámetro `pf_failure_guided_tray` (CERRADA · NO se activa).**
- **NO** se crea ni se activa. Basta la clave con `product_id` EXPLÍCITO: la fila del panel YA envía el 3er argumento (`origin_product_id`; ver `printflow_flow_strategy_product._pf_product_failure_row_actions` -> `args=[cause, 'solution', failure.get('origin_product_id')]`), y `_pf_use_guided_failure_tray` abre la guiada cuando `bool(product_id)`. El parámetro queda como override opcional (intacto).

**D5 - `pf_lot_missing_action` (CERRADA · FUERA de alcance).**
- NO se toca (hoy `warn`/default). Pertenece al estado `lot_missing` (movimiento SIN lote), que NO es esta tarea (D2). Se documenta como observación.

**D6 - Impacto en tests/candados (CERRADA · SIN modificar candados; 1 test NUEVO).**
- **SIN CAMBIOS y siguen VERDES** (verificado por lectura): los candados de la bandeja CLÁSICA la abren con la llamada de **2 argumentos** (sin `product_id`), que NO cambia: `test_product_flow_lot_tray.py`, `test_product_flow_lot_tray_ux.py`, `test_product_flow_lot_tray_document.py`, `test_product_flow_lot_tray_authorize.py`, `test_product_flow_lot_picker.py`, `test_product_flow_lot_picker_exception.py`, `test_product_flow_lot_picker_exception_authorized.py`, `test_product_flow_lot_reassign_per_document.py`, `test_product_flow_lot_remedy_permissions.py`.
- `test_product_flow_lot_actions.py` (última aserción con 2 args) y `test_product_flow_supply_tray.py::test_lot_tray_still_opens` (2 args): INTACTOS (siguen abriendo `printflow.flow.lot.tray`).
- `test_product_flow_failure_registry.py` (solo `assertIn`) y los candados de huérfana/`data_anomaly` (`test_product_flow_failure_tray_generic.py`, `test_product_flow_failure_over_reservation.py`): INTACTOS.
- `test_lot_management.py`, `test_flow_explain_delivery.py`, `test_flow_canvas_lot_parity.py`, `test_finding_exception_formal.py`: usan estados/playbook/registry de HALLAZGOS, NO el registry de FALLAS => intactos.
- **CREAR** `tests/test_product_flow_failure_lot_no_stock.py` (CA-1..CA-4) y registrarlo en `tests/__init__.py`. **Ningún** test existente se modifica.

### 3.6 Archivos (confirmados por el Planificador)

| Acción | Archivo | Qué se cambia |
|---|---|---|
| **CREAR** | `models/printflow_flow_failure_lot_no_stock.py` | `_name = 'printflow.flow.failure.lot.no.stock'`, `_inherit = 'printflow.flow.failure'`: detect / presentación / evidencias / acciones / ejecución + helpers de lectura (T1). |
| **MODIFICAR** | `models/printflow_flow_failure_registry.py` | Añadir al mapa `_pf_registry`: `'lot_no_stock': 'printflow.flow.failure.lot.no.stock'` (T2). |
| **MODIFICAR** | `models/__init__.py` | Importar `printflow_flow_failure_lot_no_stock` en la sección 2d, tras `printflow_flow_failure_over_reservation` (T3). |
| **CREAR** | `tests/test_product_flow_failure_lot_no_stock.py` (+ registrar en `tests/__init__.py`) | Fijan CA-1..CA-4 (T4). |

**SIN CAMBIOS (a propósito):** motor `x_product_dimensional_pricing` (solo LECTURA); `wizard/printflow_flow_failure_tray*.py|xml` (estructura, contrato, vistas y widget de la bandeja guiada, INTACTOS); bandeja clásica de lote (`printflow.flow.lot.tray` + vistas); casos `lot_orphan_reservation`/`data_anomaly`; `printflow_product_flow.action_run_pf_plan` / `_pf_use_guided_failure_tray` / `_pf_open_failure_tray` (ya soportan un código nuevo del registro); registro de fallas del PEDIDO (`printflow_order_diagnostic_failure._pf_open_registered_failure_tray`, excluye lote); `__manifest__.py` y `security/ir.model.access.csv` (el AbstractModel se carga por `models/__init__.py` y NO lleva fila de ACL).

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): PROHIBIDO `cr.execute` de escritura / `cr.commit()`.
- **No forzar ni reinventar flujos nativos** (entrega/reserva de lote): se **reutiliza** el saneo EXISTENTE
  (`_pf_reassign_by_lot` + guardia `_pf_assert_can_clean`); la bandeja **solo lista/navega** (no escribe).
- **NO tocar el motor** `x_product_dimensional_pricing` (SOLO LECTURA/reutilización de `printflow.stock.health` /
  `printflow.stock.remedy`).
- **NO romper** los 2 casos soportados (`lot_orphan_reservation`, `data_anomaly`), la bandeja clásica ni la paridad
  del PEDIDO.
- Convenciones OCA (`odoo-17-clean-architecture` §2.5). **`models/` nunca importa `wizard/`.** **Sin N+1.**

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | "Solucionar" con causa `lot_no_stock` (producto, **3 args**) abre la bandeja **GUIADA**; la MISMA llamada de **2 args** sigue abriendo la **clásica** (fallback). | Test (T4). |
| CA-2 | La bandeja guiada trae evidencias (una fila por lote) + acciones `reassign` (execute) y `view_supporting_moves` (navigate); `res_model='stock.lot'`. | Test (T4). |
| CA-3 | Los 2 casos previos siguen INTACTOS (`lot_orphan_reservation`→`...lot.orphan`, `data_anomaly`→`...over.reservation`); `_pf_supported()` contiene los **3** códigos. | Test (T4). |
| CA-4 | Solo LECTURA al abrir la bandeja; **motor intacto**; sin SQL crudo. | `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`. |

### 3.11 Plan de ejecución atómico y secuencial (T1-T4)

> **Ejecución por LOTES de máximo 3 tareas; cada lote = una sesión NUEVA de `odoo-dev`.**
> Convenciones OCA (`odoo-17-clean-architecture` §2.5): un archivo por modelo, métodos `_pf_*`, `snake_case`, imports por bloques, orden del modelo (atributos -> campos -> constraints -> default -> compute -> onchange -> CRUD -> acciones -> negocio). Regla: **código sí, datos no**; prohibido `cr.execute` de escritura y `cr.commit()`. La falla es `AbstractModel` (sin tabla, sin fila en `security/ir.model.access.csv`), igual que el contrato base y las fallas existentes.

#### Lote 1 (T1-T3) — Falla nueva + registro

- [x] **T1 — CREAR la falla `printflow.flow.failure.lot.no.stock`.**
  - Archivo: **CREAR** `models/printflow_flow_failure_lot_no_stock.py` (docstring de módulo explicando el "por qué", espejo de `printflow_flow_failure_lot_orphan.py` / `printflow_flow_failure_over_reservation.py`).
  - `class PrintflowFlowFailureLotNoStock(models.AbstractModel)` con `_name = 'printflow.flow.failure.lot.no.stock'`, `_inherit = 'printflow.flow.failure'`, `_description = 'Falla: lote reservado sin existencia (PrintFlow)'`.
  - **IDENTIDAD Y DETECCIÓN**
    - `_pf_fault_code(self)` -> `return 'lot_no_stock'`.
    - `_pf_fault_detect(self, host, ctx=None)`: `product = (ctx or {}).get('product')`; si no hay producto o `product.tracking != 'lot'` -> `return False`. `lot_info = self.env['printflow.stock.health']._pf_lot_state(product)`; `lot_info = self.env['printflow.finding.exception.filter']._pf_apply_to_lot_info(product, lot_info)` (resta hallazgos AUTORIZADOS; mismo criterio de la bandeja clásica). Si `lot_info.get('state') != 'lot_no_stock'` -> `return False`. Devuelve `{'product': product, 'lot_info': lot_info}`.
  - **PRESENTACIÓN**
    - `_pf_fault_severity(self, ctx)` -> `'danger'` (coincide con `_LOT_STATE_SEVERITY['lot_no_stock']`).
    - `_pf_fault_summary(self, ctx)` -> `_('%s lote(s) reservado(s) sin existencia interna: el documento retiene un lote que no tiene stock. Se corrige re-asignando la reserva por lote; no hay que ajustar el físico.') % <nº de lotes>`.
    - `_pf_fault_steps(self, ctx)` -> lista de 2-3 pasos: revisar las filas (lote + documentos que lo retienen); pulsar "Reasignar la reserva por lote" (suelta y re-asigna por reglas de Odoo, nunca un lote vacío); recalcular el diagnóstico para confirmar.
  - **EVIDENCIAS** — `_pf_fault_evidences(self, ctx)`: UNA fila por lote de `no_stock_lot_ids` (leyendo `ctx['observation']['lot_info']` o recalculando con el helper). Cada fila usa SOLO campos del contrato de la línea (`product_id`, `lot_id`, `lot_name`, `location_id`, `physical_qty`, `reserved_qty`, `support_qty`, `delta_qty`, `support_label`, `detail`, `res_model`, `res_id`) — **OJO: `printflow.flow.failure.tray._pf_populate` crea la línea con `dict(row, …)`, así que claves fuera de esos campos romperían el `create`**. `res_model='stock.lot'`, `res_id=lot.id`. `physical_qty` = físico total del lote (0 en este estado); `reserved_qty` = reservado del lote; `support_qty` = cantidad de las `stock.move.line` activas que lo retienen; `delta_qty = support_qty - physical_qty` (lo retenido sin respaldo físico); `support_label` = documentos (`picking`/`move`) que lo retienen; `detail` = texto legible ("Lote X sin existencia; lo retiene WH/OUT/…"). Cálculos en UNA sola lectura de move lines y UNA de quants (helpers `_pf_move_lines_for_lots` + `_pf_lot_facts`), SIN N+1.
  - **ACCIONES** — `_pf_fault_actions(self, ctx)` (lista blanca explícita, sin `getattr`):
    - `{'key': 'reassign', 'label': _('Reasignar la reserva por lote'), 'kind': 'execute', 'enabled': True, 'primary': True, 'sequence': 10}`
    - `{'key': 'view_supporting_moves', 'label': _('Ver quién la retiene'), 'kind': 'navigate', 'enabled': True, 'sequence': 20}`
    - `{'key': 'leave', 'label': _('Cerrar'), 'kind': 'close', 'enabled': True, 'sequence': 30}`
  - **EJECUCIÓN** — `_pf_fault_execute(self, action_key, ctx)`: `product = (ctx or {}).get('product')`; si no -> `''`. Si `action_key == 'reassign'`: `Remedy = self.env['printflow.stock.remedy']; Remedy._pf_assert_can_clean()`; `result = self.env['printflow.stock.health']._pf_reassign_by_lot(product)`; `self._pf_log(product, _('PrintFlow: reserva de lote sin existencia reasignada desde la bandeja de fallas del diagrama (albaranes re-asignados: %s).') % len(result.get('cleaned_pickings') or []))`; si `result.get('still_negative')` -> mensaje de aviso ("aún falta stock físico"); si no -> mensaje de éxito con el nº de albaranes. Las claves `navigate`/`close` las resuelve la bandeja -> `return ''`.
  - **HELPERS** (puros, solo lectura): `_pf_no_stock_lot_ids(ctx)` (lee `lot_info['no_stock_lot_ids']`); `_pf_move_lines_for_lots(product, lot_ids)` (UNA búsqueda de `stock.move.line` activas internas del producto con esos lotes; mismo dominio que la bandeja clásica); `_pf_lot_facts(product, lot_ids)` (UNA `search_read` de quants internos -> físico/reservado por lote); `_pf_log(product, body)` (`message_post`, igual que las fallas hermanas). Sin `getattr`; sin `cr.execute`/`cr.commit`.
- [x] **T2 — Mapear el código en el registry.**
  - Archivo: `models/printflow_flow_failure_registry.py`, método `_pf_registry()`.
  - Añadir la entrada `'lot_no_stock': 'printflow.flow.failure.lot.no.stock'` (comentario: lote asignado en una `stock.move.line` activa sin stock del lote; abre la guiada con una fila por lote y el saneo `reassign`). El resto del mapa y `_pf_failure_for`/`_pf_supported`/`_pf_guided_tray_forced` quedan INTACTOS.
- [x] **T3 — Registrar la falla en `models/__init__.py`.**
  - Archivo: `models/__init__.py`, sección 2d.
  - Añadir `from . import printflow_flow_failure_lot_no_stock` TRAS `from . import printflow_flow_failure_over_reservation`, con un comentario del motivo (falla de lote sin existencia; el registry la resuelve por NOMBRE en runtime).
  - `models/` NO importa `wizard/`.

#### Lote 2 (T4) — Test

- [x] **T4 — Test que fija CA-1..CA-4.**
  - **CREAR** `tests/test_product_flow_failure_lot_no_stock.py` y registrarlo en `tests/__init__.py`. `TransactionCase` (rollback); helpers: producto `tracking='lot'` `x_is_printflow_managed=True` con un lote REAL con stock (para evitar el déficit/consecuencia) + un albarán de salida que reserva un lote FANTASMA sin existencia (`lot_no_stock`), patrón de `test_product_flow_lot_actions.py`.
    - **CA-1**: `wizard.action_run_pf_plan('lot_no_stock', 'solution', product.id)` (3 args) -> `action['res_model'] == 'printflow.flow.failure.tray'`; y la MISMA llamada de **2 args** (`action_run_pf_plan('lot_no_stock', 'solution')`) -> sigue abriendo `printflow.flow.lot.tray` (fallback clásico INTACTO).
    - **CA-2**: `Tray._pf_populate(None, 'lot_no_stock', product)` -> `tray.line_ids` NO vacías; `line.action_ids.mapped('key')` incluye `reassign` (execute) y `view_supporting_moves` (navigate); `line.res_model == 'stock.lot'`. `tray.action_run(line.id, 'reassign')` devuelve `display_notification` (saneo EXISTENTE, sin excepción); una clave desconocida cierra.
    - **CA-3**: el registry sigue resolviendo `lot_orphan_reservation` -> `printflow.flow.failure.lot.orphan` y `data_anomaly` -> `printflow.flow.failure.over.reservation`; `_pf_supported()` contiene los TRES códigos; la guiada de huérfana sigue abriendo (llamada 3 args con `product.id`).
    - **CA-4**: `TransactionCase` (rollback); el archivo nuevo no contiene `cr.execute(`/`cr.commit(`; motor externo intacto (la falla solo usa `printflow.stock.health._pf_reassign_by_lot` / `printflow.stock.remedy._pf_assert_can_clean`).
  - **NO se modifican** los candados existentes (D6).

**Verificación (turno del Verificador, fuera del dev).** `--test-tags` sobre
`/printflow_gestion_inventario:TestProductFlowFailureLotNoStock`,
`...:TestProductFlowFailureRegistry`, `...:TestProductFlowFailureTrayGeneric`,
`...:TestProductFlowFailureOverReservation`, `...:TestProductFlowLotActions`,
`...:TestProductFlowLotTray` y `...:TestProductFlowSupplyTray` (paridad clásica/pedido). Al hilo solo
vuelve el exit code, N/N y, si falla, la aserción + cola del traceback.

### 3.12 Contratos que NO deben romperse

- CA-1..CA-4 de 3.8.
- Firma/forma del contrato base `models/printflow_flow_failure.py` (los 7 métodos) y de la bandeja `printflow.flow.failure.tray` (`_pf_populate`, `action_run`, `_pf_nav_action`): **SIN cambios**.
- `models/printflow_flow_failure_registry.py::_pf_failure_for` (nunca vacío; fallback `generic`) y `_pf_supported` (ahora incluye `lot_no_stock`): el resto del mapa INTACTO.
- Casos `lot_orphan_reservation` -> `printflow.flow.failure.lot.orphan` y `data_anomaly` -> `printflow.flow.failure.over.reservation`: INTACTOS.
- `printflow_product_flow.action_run_pf_plan` / `_pf_use_guided_failure_tray` / `_pf_open_failure_tray`: **SIN cambios** (ya soportan un código nuevo del registro y el fallback a la clásica).
- Bandeja clásica `printflow.flow.lot.tray` (+ vistas) y el estado de lote del motor: **SIN cambios**.
- Motor `x_product_dimensional_pricing`: **SIN CAMBIOS** (solo se leen `printflow.stock.health` / `printflow.stock.remedy`).
- `printflow_order_diagnostic_failure._pf_open_registered_failure_tray`: **SIN cambios** (excluye lote => paridad del PEDIDO).
- `__manifest__.py` y `security/ir.model.access.csv`: **SIN cambios**.
- `models/` nunca importa `wizard/`.

### 3.13 Observaciones (fuera de alcance)

- **O-1**: `pf_lot_missing_action` (hoy `warn`) y el interruptor `pf_failure_guided_tray` (hoy `0`) quedan como están (D4/D5).
- **O-2**: la bandeja clásica de lote se conserva como fallback (no se retira).
- **O-3**: la causa viene del nodo Entrega del producto (H-018); el caso de insumos/lotes de componente queda fuera.
- **O-4**: solo `lot_no_stock` entra a la guiada en esta tarea; los demás estados de lote quedan como extensión futura (D2, mismo molde: modelo + línea en el mapa).

---

## 3.H (ANEXO · TAREA CERRADA) — El albarán de entrada no se podía validar (candado de fichas al recibir)

> **Turno:** Odoo Analista (cierre). **Estado:** CERRADA (Verificador: `cumple`; Dev exit 0, **11/11 verdes**;
> hallazgo **H-013** resuelto).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow) · `C:\odoo_custom\x_product_dimensional_pricing` (motor; aquí vivía el bug).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **GRANDE**. Cadena:
> Analista → Planificador → Analista → Dev (un lote) → Verificador → Analista.

### 3.1 Problema (evidencia en el log y en la BD)
El albarán de entrada **WH/IN/00578** (picking 40565, de la OC **P01807**) **NO se puede validar**: al
procesar la orden parcial salta *"Operación no válida — No se puede modificar una ficha finalizada,
cancelada o archivada."*

Evidencia (log del servidor + BD `Ciber Estudios 2015 RESTAURADA`):

| Momento | Dato |
|---|---|
| 07:26:59 | `POST .../stock.backorder.confirmation/web_save` |
| **07:27:00** | `WARNING odoo.http: No se puede modificar una ficha finalizada, cancelada o archivada.` |
| 07:27:00 | `POST /web/dataset/call_button` (la validación) |
| OC P01807 (id 1818) | `origin` = **32 pedidos S…** (S09337…S00550) |
| Fichas del producto 13571 en estado **terminal** | **S03349** (sheet id **1000**, `archived_delivered`) y **S06581** (id **2033**, `archived_delivered`) — **ambas en el `origin`** |
| Línea del albarán 94862 | `lot_name="12569"` (**tecleado** por uid 2 a las 07:25:13), `quantity=1`, `picked=True` |

**Causa raíz (código del MOTOR):**
1. `stock.picking.button_validate` (motor, `x_product_dimensional_pricing/models/stock_picking.py` L14-21)
   llama a `_technical_sheet_invalidate_on_receive()` tras el `super()`.
2. Esa función (L95-127) busca las **fichas técnicas** de los pedidos del `origin` de la OC + el producto, y
   ejecuta `sheets._compute_state_from_docs()` **SIN** el contexto `bypass_sheet_write_lock`/`printflow_sync`
   (a diferencia de `printflow_recompute_states`, que SÍ lo pasa).
3. `_compute_state_from_docs` (`mrp_technical_sheet_state.py` L293-299) asigna `is_partial_fabrication`
   (campo `compute + store`, L26-32) a **todas** las fichas, incluidas las **bloqueadas** (el `continue` de
   las archivadas ocurre **después** de asignar ese campo).
4. `is_partial_fabrication` **NO** está en `_PRINTFLOW_TECHNICAL_WRITE_FIELDS` (`mrp_technical_sheet.py`
   L19-39) ⇒ el candado de `write()` (`mrp_technical_sheet_crud.py` L90-92) lanza el `UserError`.

⇒ Bloquea **cualquier recepción** cuyo `origin` referencie pedidos con ficha en estado terminal del producto.
**Pre-existente** (`stock_picking.py` mtime 02/10/2026); **no lo causó** el fix del lote (que no toca el motor).

### 3.2 Objetivo (acotado)
**SÍ:**
1. Que el albarán de entrada de una OC (agrupada o no) **se pueda validar** aunque sus pedidos tengan fichas
   en estado terminal.
2. Que el recálculo de fichas al recibir **respete el candado** de las fichas finalizadas (no las escriba).
3. Conservar el comportamiento de las fichas no bloqueadas y del resto del flujo.

**NO:**
- NO escribir datos existentes (regla `código sí, datos no`).
- NO forzar ni reinventar la recepción nativa (sin `cr.execute`/`cr.commit`, sin validar por detrás).
- NO romper el candado: editar fichas finalizadas **a mano** sigue prohibido.

### 3.3 Contrato funcional
| Superficie | Debe quedar |
|---|---|
| Validación del albarán de entrada | **Funciona** (sin el `UserError`), aunque el `origin` traiga pedidos con fichas terminales. |
| Fichas en estado terminal | **No se escriben** (el cómputo las omite o usa el bypass de sistema). |
| Fichas no terminales | Se recalculan igual que hoy. |
| Candado de edición manual de fichas | **Intacto**. |

### 3.4 Fuente ÚNICA / patrón a reutilizar
- **Bypass de sistema que YA EXISTE:** `printflow_recompute_states` (`mrp_technical_sheet_state.py` L128-137)
  ejecuta el cómputo con `with_context(bypass_sheet_write_lock=True, printflow_sync=True)`; mismo patrón en
  `mrp_technical_sheet_crud.py` L46-55.
- **Candado:** `mrp_technical_sheet_crud.write()` L90-92 + `_printflow_skip_terminal_write_lock` L58-66.
- **Whitelist:** `_PRINTFLOW_TECHNICAL_WRITE_FIELDS` (`mrp_technical_sheet.py` L19-39).

### 3.5 Decisiones de diseño cerradas (D1–D5)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` · Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no**. El diseño se **engancha** al candado ya existente y **NO toca** el motor `x_product_dimensional_pricing` (solo lo hereda/extiende desde PrintFlow).

**D1 — DÓNDE y CÓMO arreglar (CERRADA · opción c: 100 % PrintFlow).**
- Se elige la opción **(c)**: **extender la whitelist del candado DESDE PrintFlow**, sin tocar el motor.
- Fundamento: la whitelist `_PRINTFLOW_TECHNICAL_WRITE_FIELDS` existe EXACTAMENTE para los campos que el **cómputo** escribe en fichas bloqueadas (el propio `state` —asignado por el MISMO `_compute_state_from_docs`— YA está en ella). `is_partial_fabrication` es un campo **compute + store readonly** que ese cómputo asigna a TODAS las fichas; quedó **fuera** de la whitelist por omisión. El arreglo correcto y mínimo es **completar la whitelist**, no aflojar el candado.
- Mecanismo: clase PrintFlow `_inherit = 'mrp.technical.sheet'` que **sobrescribe el método-seam** `_printflow_skip_terminal_write_lock(self, vals)` (el que consulta la whitelist dentro de `mrp_technical_sheet_crud.write()`) con `super()` + un **set aditivo PROPIO**. Se sobrescribe el MÉTODO (no el atributo del motor) para **no hardcodear** la lista: `super()` conserva la whitelist original y el set propio añade SOLO el campo nuevo.
- Por qué NO la opción (a): tocar el motor (`stock_picking.py` con `with_context(bypass_sheet_write_lock=True, printflow_sync=True)`) exige autorización del dueño (D2) y abre el candado a TODO el cómputo por contexto.
- Por qué NO la opción (b): ampliar la whitelist EN el motor = tocar el motor (prohibido sin autorización).

**D2 — AUTORIZACIÓN (CERRADA · no aplica).**
- El fix es **100 % PrintFlow** (`_inherit` + `super()`); **NO** se modifica ningún archivo de `x_product_dimensional_pricing`. Por tanto **no** se requiere autorización del dueño: la regla "motor externo SOLO LECTURA" se mantiene intacta.

**D3 — Alcance del candado (CERRADA).**
- La whitelist extendida abre la escritura de **UN campo**: `is_partial_fabrication` (compute + store `readonly` ⇒ **no editable desde la UI**, no aparece en ningún formulario). Por tanto la **edición manual** de una ficha finalizada/cancelada/archivada sigue **imposible**: cualquier campo de negocio (`name`, `dim_width`, `manual_done`, …) sigue fuera de la whitelist y dispara el `UserError` de `write()`.
- **NO** se usa `bypass_sheet_write_lock` ni contexto de sistema: el candado sigue siendo **estricto por campo** (se conserva el comportamiento del motor para todo lo demás). Un test lo fija (CA-2).

**D4 — Paridad delivery/receive (CERRADA · se sanea el bug LATENTE en la MISMA tarea).**
- El hook gemelo `_technical_sheet_invalidate_on_delivery` (L70-93) llama al **MISMO** `_compute_state_from_docs()` ⇒ sufría el **mismo** bug latente. Al corregirse en el **nivel del campo** (whitelist), el arreglo cubre **AMBOS** hooks (recepción y entrega) con **un solo** cambio, sin duplicar nada ni tocar el motor. Se fija con **CA-3**.

**D5 — Candados de test (CERRADA).**
- **Cambios ADITIVOS**: la sobrescritura del método preserva el resultado de `x_product_dimensional_pricing/tests/test_technical_sheet_refactor_parity.py::test_terminal_write_lock_whitelist` (verificado por lectura: `{'production_id'}` → True; `{'dim_width'}` → False; con contexto de sistema → True).
- **SIN CAMBIOS** (siguen verdes): `test_technical_sheet_refactor_parity.py` y el resto de la suite del motor.
- **CREAR** `tests/test_technical_sheet_terminal_lock.py` (CA-1..CA-4) y registrarlo en `tests/__init__.py`.

### 3.6 Archivos (confirmados por el Planificador)

| Acción | Archivo | Qué se cambia |
|---|---|---|
| **CREAR** | `printflow_gestion_inventario/models/mrp_technical_sheet.py` | `_inherit = 'mrp.technical.sheet'`: set aditivo propio + override `_printflow_skip_terminal_write_lock` con `super()` (**T1**). |
| **MODIFICAR** | `printflow_gestion_inventario/models/__init__.py` | Importar `mrp_technical_sheet` (sección 17) (**T2**). |
| **CREAR** | `printflow_gestion_inventario/tests/test_technical_sheet_terminal_lock.py` (+ registrar en `tests/__init__.py`) | Fijan CA-1..CA-4 (**T3**). |

**SIN CAMBIOS (a propósito):** motor `x_product_dimensional_pricing` (SOLO LECTURA/herencia; `stock_picking.py`, `mrp_technical_sheet.py`, `mrp_technical_sheet_state.py` y `mrp_technical_sheet_crud.py` intactos); builder/widget/payload; wizards; `__manifest__.py` (sin datos/assets nuevos; el modelo se carga por `models/__init__.py`).

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): PROHIBIDO `cr.execute` de escritura / `cr.commit()`.
- **No forzar ni reemplazar flujos nativos; código sí, datos no.** El albarán se valida SOLO por su botón nativo; el fix **NO** llama `button_validate`/`_action_done` por detrás ni escribe estados/movimientos/quants.
- **NO tocar el motor** `x_product_dimensional_pricing` (se hereda `mrp.technical.sheet` desde PrintFlow).
- **NO romper el candado**: la edición manual de fichas finalizadas/canceladas/archivadas sigue prohibida (solo se habilita el campo computado `is_partial_fabrication`, readonly en UI).
- **NO romper** los candados de test del motor ni la suite de PrintFlow.
- **`models/` nunca importa `wizard/`.**

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | Un albarán de entrada cuyo `origin` referencia pedidos con ficha terminal **se valida** sin `UserError`. | Test: ficha `archived_delivered` (mismo SO/producto del picking) → `picking.button_validate()` sin error; el albarán queda `done`. |
| CA-2 | Las fichas terminales **no se alteran** ni se desbloquean; las no terminales sí se recalculan. | Test: la ficha bloqueada conserva `state='archived_delivered'`; una ficha NO bloqueada del mismo documento se recomputa; `write({'dim_width': …})` sobre la bloqueada **sigue** lanzando `UserError`. |
| CA-3 | El hook gemelo de ENTREGA queda saneado con el MISMO arreglo (D4). | Test: validar un albarán de salida cuyo `sale_order_line` tenga ficha terminal → sin `UserError`. |
| CA-4 | Solo LECTURA + escritura propia del cómputo; **motor intacto**; sin SQL crudo. | `TransactionCase` (rollback); el archivo nuevo sin `cr.execute(`/`cr.commit(`; la clase de PrintFlow está en `type(Sheet).mro()`; motor sin cambios. |

### 3.9 Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Ampliar la whitelist abre de más el candado | Alto | D3: solo `is_partial_fabrication` (compute readonly); los campos de negocio siguen bloqueados; test CA-2. |
| El override no se resuelve en el MRO del motor | Alto | Precedente 3.G (PrintFlow ya sobrescribe métodos del motor); CA-1/CA-3 lo ejercen por el `write()` real. |
| Romper el candado de test del motor | Medio | D5: sobrescritura aditiva con `super()`; mismo resultado para `{'production_id'}` / `{'dim_width'}`. |
| Tocar el motor sin autorización | Alto | D2: fix 100 % PrintFlow; motor intacto. |
| Dato ya inconsistente (WH/IN/00578) | Bajo | Guía operativa; NO corregir por datos. |

### 3.10 Observaciones (fuera de alcance)
- **O-1**: `lot_name="12569"` de la línea 94862 lo tecleó el usuario (uid 2); el sistema **no** genera lotes aleatorios.
- **O-2**: el bug era **latente también en la entrega** (hook gemelo); se sanea con el mismo cambio (D4).
- **O-3**: el albarán quedó con 1 unidad y `picked=True` por la edición manual; tras el fix el operador decide cuánto recibir.
- **O-4**: el fix NO borra ni "repara" el estado de las fichas ya archivadas; solo permite reanudar el cómputo (que a las archivadas las deja como están, vía `rec._origin.state`).

### 3.11 Plan de ejecución atómico y secuencial (T1–T3)

> **Un solo lote (el plan tiene ≤3 tareas); cada lote = una sesión NUEVA de `odoo-dev`.**
> Convenciones OCA (`odoo-17-clean-architecture` §2.5): un archivo por modelo, métodos `_pf_*`, `snake_case`, imports por bloques, orden del modelo (atributos → campos → constraints → default → compute → onchange → CRUD → acciones → negocio), nodo `<odoo>`. Regla: **código sí, datos no**; prohibido `cr.execute` de escritura y `cr.commit()`.

#### Lote 1 (T1–T3) — Extensión del candado + registro + test

- [x] **T1 — Extender la whitelist del candado desde PrintFlow.**
  - Archivo: **CREAR** `models/mrp_technical_sheet.py`.
  - `class MrpTechnicalSheet(models.Model)` con `_inherit = 'mrp.technical.sheet'`.
  - **Atributo** (sección ATRIBUTOS): `_PF_TERMINAL_EXTRA_WRITE_FIELDS = frozenset({'is_partial_fabrication'})` (comentario: campo compute+store que el recálculo asigna a TODAS las fichas, incluidas las bloqueadas; readonly en UI).
  - **Override** del método-seam (sección de métodos técnicos/negocio `_pf_*`):
    ```python
    def _printflow_skip_terminal_write_lock(self, vals):
        if super()._printflow_skip_terminal_write_lock(vals):
            return True
        return bool(vals) and set(vals).issubset(
            self._PF_TERMINAL_EXTRA_WRITE_FIELDS)
    ```
  - `super()` conserva el comportamiento del motor (contextos de sistema + whitelist original); el set propio añade SOLO `is_partial_fabrication`. **NO** se reimplementa `write` ni el cómputo; **NO** se toca el motor. Se respeta el orden OCA (atributos → campos → … → métodos).
- [x] **T2 — Registrar el modelo en `models/__init__.py`.**
  - Archivo: `models/__init__.py`.
  - Añadir, al final (sección 17), `from . import mrp_technical_sheet` con comentario del motivo (extiende la whitelist del candado de fichas terminales para el campo computado `is_partial_fabrication`, enganche ADITIVO desde PrintFlow; sin tocar el motor).
  - `models/` NO importa `wizard/`.
- [x] **T3 — Test que fija CA-1..CA-4.**
  - **CREAR** `tests/test_technical_sheet_terminal_lock.py` y registrarlo en `tests/__init__.py`.
    - **CA-1 (recepción)**: producto `type='product'`; SO confirmado con una línea del producto; `mrp.technical.sheet` con `sale_line_id` de esa línea forzado a `state='archived_delivered'` (vía `with_context(bypass_sheet_write_lock=True).write(...)` + `flush_all()`); OC del producto con `origin = SO.name`, confirmada (genera el albarán de entrada con `origin = PO.name`); asegurar recepción COMPLETA (sin backorder: `move_line.picked = True` / `quantity = demand`) y llamar `picking.button_validate()` **sin** `UserError`; `picking.state == 'done'`.
    - **CA-2 (candado)**: tras validar, la ficha bloqueada conserva `state == 'archived_delivered'`; una ficha NO bloqueada (misma búsqueda: SO/producto) se recomputa; `sheet.write({'name': 'x'})` sobre la bloqueada **lanza** `UserError`.
    - **CA-3 (entrega)**: albarán de SALIDA cuyo `sale_order_line` tenga ficha terminal (misma técnica) → `button_validate()` sin `UserError` (mismo arreglo, D4).
    - **CA-4 (solo lectura / motor intacto)**: `TransactionCase` (rollback); el archivo nuevo sin `cr.execute(`/`cr.commit(`; la clase de PrintFlow presente en `type(Sheet).mro()` (queda registrada la extensión).
  - **NO se modifican** los candados existentes (D5).

**Verificación (turno del Verificador, fuera del dev).** `--test-tags` sobre
`/printflow_gestion_inventario:TestTechnicalSheetTerminalLock` y el candado del motor
`/x_product_dimensional_pricing:TestTechnicalSheetRefactorParity`. Al hilo solo vuelve el exit code, N/N y, si falla, la aserción + cola del traceback.

### 3.12 Contratos que NO deben romperse
- CA-1..CA-4 de 3.8.
- `mrp.technical.sheet.write()` y el candado de estados terminales: `write` sigue siendo el del motor (`MrpTechnicalSheetCrud`); solo se EXTIENDE su método-seam de whitelist.
- `_PRINTFLOW_TECHNICAL_WRITE_FIELDS` del motor: **intacta** (PrintFlow no la redefine; añade un set PROPIO aparte).
- `_compute_state_from_docs` (motor): **intacto** (no se reimplementa).
- Edición manual de fichas finalizadas/canceladas/archivadas: **sigue prohibida**.
- Motor `x_product_dimensional_pricing`: **SIN CAMBIOS** (solo se hereda).
- `__manifest__.py`: **SIN cambios**.

---

## 3.G (ANEXO · TAREA CERRADA) — El lote de la Compra Rápida no viaja a la OC ni al albarán

> **Turno:** Odoo Analista (revisión del PLAN del Planificador; paso 3 → **`odoo-dev`**). **Estado:**
> **PLAN COMPLETO** (D1–D6 cerradas por el **Odoo Planificador**; T1–T4 en 2 lotes).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA`.
> **Rutas:** `C:\odoo_custom\printflow_gestion_inventario` (PrintFlow) · `C:\odoo_custom\x_product_dimensional_pricing` (motor de la Compra Rápida; **SOLO LECTURA** para PrintFlow).
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **GRANDE** (toca el
> flujo de Compras/Recepción). Cadena: Analista → Planificador → Analista → Dev (por lotes) →
> Verificador → Analista.

### 3.1 Problema (evidencia en la BD)
El **lote indicado en la Compra Rápida NO viaja a la Orden de Compra ni al albarán de entrada**. Al
validar el albarán, Odoo pide el lote (producto `tracking='lot'`) y está **vacío**, obligando a
teclearlo de nuevo.

Evidencia (producto `IMPRESION BANNER ` id 13571, `tracking='lot'`; proveedor AREA GRAPHIX; OC **P01807**
id 1818 creada 2026-10-16 06:34:54 por Jonathan Romero desde la resolución del nodo **Compras** del
diagrama de producto):

| Eslabón | Dato real |
|---|---|
| Wizard Compra Rápida (`mrp.quick.purchase.wizard` id **638**) | `material_received=True` (default del **header**, legacy) · `pf_freeze_qty=True` |
| Línea del wizard (`...wizard.line` id **762**) | `lot_name="LOTE-000001"` · **`material_received=False`** · `product_qty=25` |
| OC (**P01807** id 1818) | `state=purchase` · `origin` = 32 pedidos S… · **sin campo de lote** |
| Albarán (**WH/IN/00578** picking 40565) | `state=assigned` (pendiente) · tipo incoming `use_create_lots=True` |
| Movimiento (`stock.move` 127860) | `lot_ids=[]` · `purchase_line_id=2612` |
| Línea de movimiento (`stock.move.line` 94861) | `lot_id=false` · `quantity=25` |
| `stock.lot` "LOTE-000001" | **NO existe** (búsqueda vacía) |
| Único rastro persistente | `pf_lot_name="LOTE-000001"` en los **32 `sale.order`** (lado venta) |

**Causa raíz (código):** el nombre del lote vive SOLO en la **línea del wizard** (transient). El ÚNICO
punto que crea el `stock.lot` y lo pega a las líneas del albarán es
`x_product_dimensional_pricing/wizard/mrp_quick_purchase_wizard.py::_validate_incoming_pickings()`
(L703-719), invocado desde `action_confirm()` (L419-420) **solo si `line.material_received == True`**
(recepción automática). Como PrintFlow abre la Compra Rápida con **`material_received=False` a propósito**
("abrir ≠ ejecutar": solo crea la OC, no fuerza la recepción; ver
`printflow_gestion_inventario/wizard/printflow_product_flow.py::_pf_open_quick_purchase` L741-773, L761),
el albarán queda abierto y el lote **nunca se materializa** (no se crea `stock.lot`, no se asigna al
move). El `pf_lot_name` solo se escribe en los `sale.order` (L416-418), **no en la OC ni en la entrada**.

> Nota: `LOTE-000001` es el **correlativo automático** de `_default_lot_name()` (L124-139), usado cuando
> el wizard NO tiene pedido de venta (`sale_order_id=False`, caso PrintFlow). El operador lo ve
> pre-cargado.

### 3.2 Objetivo (acotado)
**SÍ:**
1. Que el **lote indicado en la Compra Rápida NO se pierda** al crear la OC: debe quedar persistido de
   forma recuperable por el lado de **compra/entrada**.
2. Que al **validar manualmente** el albarán de entrada, el lote previsto esté **pre-cargado**
   (sin volver a teclearlo).
3. Conservar el comportamiento actual cuando la recepción **sí** es automática (`material_received=True`)
   y en la Compra Rápida **normal** (sin PrintFlow).

**NO:**
- NO escribir datos existentes por script/consola (regla `código sí, datos no`); la corrección es **de código**.
- NO forzar ni reinventar el flujo nativo de compras/recepción (nada de `cr.execute`, `cr.commit()`, ni
  validar albaranes por detrás).
- NO romper la trazabilidad del lado **venta** (`sale.order.pf_lot_name`, reserva exclusiva por pedido).
- NO tocar el motor de salud/diagnóstico ni el widget del diagrama.

### 3.3 Contrato funcional (dónde y qué)
| Superficie | Debe quedar |
|---|---|
| Compra Rápida → "Confirmar" con lote | El lote de la línea se **persiste** en el documento de compra/entrada (no solo en el `sale.order`). |
| Albarán de entrada generado | Sus `stock.move.line` llevan el lote **previsto** (o el lote queda disponible para prellenar la validación manual). |
| Validación manual del albarán | El lote aparece **pre-cargado**; el operador NO lo teclea de nuevo. |
| Recepción automática (`material_received=True`) y Compra Rápida normal | **Sin cambios** de comportamiento. |
| Lado venta (`pf_lot_name` en `sale.order`, reserva exclusiva) | **Intacto**. |

### 3.4 Fuente ÚNICA / patrón a reutilizar (cero reinvención)
- **Materialización del lote (YA EXISTE):** `mrp.production._get_or_create_lot(product, lot_name)` — el
  helper canónico que ya usa `stock_move._pf_ensure_exclusive_lot` (`x_product_dimensional_pricing/models/stock_move.py`
  L241) y `mrp_production._assign_lots`; idempotente (busca por `(name, product_id)` y crea si falta).
  La variante del wizard (`mrp_quick_purchase_wizard.py::_get_or_create_lot`, L691-701) es un envoltorio de
  `self.lot_name`; el prellenado de la OC usa el canónico de `mrp.production`.
- **Prellenado sin validar (YA EXISTE, patrón):** `mrp_quick_purchase_wizard.py::_validate_incoming_pickings`
  (L703-719): `picking.action_assign()` → escribir `lot_id` en las `stock.move.line` del move por lote.
  PrintFlow reutiliza EXACTAMENTE ese patrón, pero **SIN** `button_validate`.
- **Persistencia del lote (YA EXISTE, lado venta):** `orders.write({'pf_lot_name': ...})` (L416-418) y
  `sale.order.pf_lot_name` (`x_product_dimensional_pricing/models/sale_order.py` L22). Se REPLICA en
  `purchase.order` con un campo homónimo ADITIVO.
- **Etiqueta del lote en venta:** `sale_order_line._get_exclusive_lot_name` (`models/sale_order_line.py` L172-173).
- **Apertura de la Compra Rápida desde PrintFlow:** `wizard/printflow_product_flow.py::_pf_open_quick_purchase`
  (L741-773, `pf_freeze_qty=True`, `material_received=False`) y
  `wizard/printflow_order_diagnostic_failure.py::_pf_open_quick_purchase` (L1092-1136).
- **Bridge existente de la Compra Rápida:** `models/printflow_quick_purchase_bridge.py`
  (`_inherit = 'mrp.quick.purchase.wizard'`, `pf_freeze_qty`, `_demand_for_product`, `action_pf_import_requiring_orders`).

### 3.5 Decisiones de diseño cerradas (D1–D6)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` ·
> Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no**. El diseño
> se **engancha** al patrón ya existente (`button_confirm`, `action_assign`, `_get_or_create_lot`) y
> **NO toca** el motor `x_product_dimensional_pricing` (solo lo hereda/reutiliza).

**D1 — DÓNDE persistir el lote (CERRADA).**
- Se persiste el **NOMBRE** en un campo NUEVO y ADITIVO de PrintFlow en `purchase.order`: `pf_lot_name`
  (Char), **espejo exacto** de `sale.order.pf_lot_name`. Es la **OC** quien lo guarda (documento de compra
  estable: el albarán puede regenerarse/partirse por _backorders_).
- El `stock.lot` **NO** se crea al confirmar "por si acaso": se materializa **idempotentemente** cuando se
  **prellena la entrada** (D2), reutilizando `mrp.production._get_or_create_lot`. Así el lote queda
  recuperable en la **entrada** (en las `stock.move.line`) además de en la OC.
- Mientras el albarán siga **abierto**, el lote vive en la OC (`pf_lot_name`) **y** en la move line
  (`lot_id`/`lot_name`); al **validar**, el lote queda en el `stock.lot` + las move lines (flujo nativo).

**D2 — QUIÉN lo prellena (CERRADA · mecanismo NATIVO).**
- En la **CONFIRMACIÓN de la OC** (`purchase.order.button_confirm`, `_inherit` + `super()`), PrintFlow
  prellena el albarán de **entrada** abierto del PO:
  1. `picking.action_assign()` — primitiva NATIVA que Odoo ya usa para crear/actualizar las move lines
     (idempotente; en las entradas es un no-op si ya están asignadas, y crea la move line si faltara).
  2. Escribir `lot_id` **y** `lot_name` en las `stock.move.line` del **producto por lote** del move
     (mismo patrón de `_validate_incoming_pickings`, pero **SIN** validar).
- **NO** se llama `button_validate`: "abrir ≠ ejecutar". El operador valida cuando quiere, con el lote ya
  cargado.
- Por qué `lot_id` (lote creado) y no solo `lot_name`: el tipo de albarán `incoming` de la BD tiene
  `use_create_lots=True` (`stock.picking.type` ids 1 y 13), así que ambas vías mostrarían el lote; escribir
  `lot_id` (lote EXISTENTE) es **robusto ante cualquier** combinación `use_create_lots`/`use_existing_lots`
  y garantiza que la validación **no** reclame el lote.
- **NO** se usan `default_get` ni dominio/contexto: no hay forma nativa fiable de inyectar el lote por
  contexto en move lines que Odoo crea internamente; el enganche en `button_confirm` es el punto nativo y
  determinista.

**D3 — MÓDULO donde vive el fix (CERRADA · 100 % PrintFlow).**
- El arreglo vive **ENTERO en PrintFlow** con `_inherit` + `super()`; se heredan DOS modelos y se
  **reutiliza** (sin tocar) el helper del motor:
  - `purchase.order` (campo + `button_confirm` + prellenado) — desde PrintFlow.
  - `mrp.quick.purchase.wizard.line` (persistir el lote al crear la OC) — desde PrintFlow.
  - `mrp.production._get_or_create_lot` — **reutilizado** (SOLO LECTURA/uso del motor).
- ⇒ **NO** se modifica `x_product_dimensional_pricing`; la regla "motor externo SOLO LECTURA" se mantiene y
  **no** hace falta autorización del dueño para tocar el motor. El wizard `mrp.quick.purchase.wizard` del
  motor tampoco se modifica (solo se **hereda** la línea).

**D4 — Multi-línea / multi-producto (CERRADA).**
- Una línea del wizard = **una** OC = **un** lote: el motor (`_create_purchase_order`) crea UNA
  `purchase.order` por línea, con UNA línea de pedido y UN producto. El prellenado es **por-OC / por-producto**
  ⇒ cero contaminación cruzada.
- **Sin N+1**: una pasada por OC recién confirmada sobre sus propias `picking_ids`/`move_ids` (el PO recién
  creado tiene 1 albarán). Cada `_get_or_create_lot` es una búsqueda/index por producto.

**D5 — Compatibilidad y candados (CERRADA · cambios ADITIVOS).**
- **GATE único**: solo se persiste/prellena cuando el wizard es **de PrintFlow**. La marca que PrintFlow fija
  en `_pf_open_quick_purchase` es **`pf_freeze_qty=True`** (el campo ya existe, lo añadió la tarea
  "faltante real", anexo 3.D). ⇒ se reutiliza esa marca como señal "origen PrintFlow".
  - Compra Rápida **NORMAL** (`pf_freeze_qty` ausente) ⇒ **no** se escribe `pf_lot_name` ⇒ el override de
    `button_confirm` es un **no-op** ⇒ comportamiento **intacto**.
  - Recepción **AUTOMÁTICA** (`material_received=True`) ⇒ en flujo normal/sin PrintFlow no hay `pf_lot_name`
    ⇒ intacto; y el motor sigue validando el albarán como antes.
- Campo `pf_lot_name` en `purchase.order`: **ADITIVO** (no toca campos ni métodos existentes del motor;
  el motor ya tiene su clase `PurchaseOrder` en `sale_order_line.py` L317 y este `_inherit` se apila).
- **CREAR** `tests/test_quick_purchase_lot_tracking.py` (CA-1..CA-4).
- **Candados que deben seguir VERDES** (sin tocar): `test_quick_purchase_grouping`,
  `test_quick_purchase_without_sale_order`, `test_quick_purchase_multi`,
  `test_flow_compras_por_comprar`, `test_flow_compras_deficit_magnitude`, `test_flow_compras_recepcion_snapshot`.
- `test_diagnostic_routes` (L108, `all(not line.material_received ...)`): NO se toca ni el wizard del motor
  ni PrintFlow cambia `material_received` ⇒ intacto.

**D6 — Dato ya inconsistente (CERRADA · opcional).**
- La OC **P01807** y el albarán **WH/IN/00578** quedaron **sin lote**. **NO** se corrigen por datos (regla
  vigente). **Guía operativa** para el dueño: el lote previsto era **`LOTE-000001`**; al validar el albarán,
  el operador puede teclearlo/crearlo **una sola vez** a mano. Queda como validación manual.

### 3.6 Archivos (confirmados por el Planificador)

| Acción | Archivo | Qué se cambia |
|---|---|---|
| **CREAR** | `models/purchase_order.py` | `_inherit = 'purchase.order'`: campo `pf_lot_name` + override `button_confirm` + `_pf_prefill_incoming_lot` (**T1**). |
| **MODIFICAR** | `models/printflow_quick_purchase_bridge.py` | Clase NUEVA `_inherit = 'mrp.quick.purchase.wizard.line'` con override `_create_purchase_order` (persiste `po.pf_lot_name`, **gate** `pf_freeze_qty`) (**T2**). |
| **MODIFICAR** | `models/__init__.py` | Importar `purchase_order` (sección 16, tras el bridge) (**T3**). |
| **CREAR** | `tests/test_quick_purchase_lot_tracking.py` (+ registrar en `tests/__init__.py`) | Fijan CA-1..CA-4 (**T4**). |

**SIN CAMBIOS (a propósito):** motor `x_product_dimensional_pricing` (solo LECTURA/herencia);
`wizard/printflow_product_flow.py` y `wizard/printflow_order_diagnostic_failure.py` (ya abren la Compra
Rápida con `material_received=False` + `pf_freeze_qty=True`); vista/widget del diagrama; `wizard/printflow_quick_purchase_views.xml`;
`__manifest__.py` (no hay datos/assets nuevos; el modelo nuevo se carga por `models/__init__.py`).

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): PROHIBIDO `cr.execute` de escritura / `cr.commit()`.
- **No forzar ni reemplazar flujos nativos; código sí, datos no.** Se engancha con `_inherit` + `super()`;
  el albarán se suelta SOLO por el botón nativo "Validar" del operador, **nunca** por detrás (PROHIBIDO
  `button_validate`/`_action_done` desde el fix).
- **NO tocar el motor** `x_product_dimensional_pricing` (se hereda `purchase.order` y la línea del wizard
  desde PrintFlow; se reutiliza `_get_or_create_lot`).
- **NO romper** la trazabilidad de venta (`sale.order.pf_lot_name`) ni la Compra Rápida **normal** ni la
  recepción **automática**.
- **`models/` nunca importa `wizard/`.** **Sin N+1.**
- Las escrituras permitidas son las **propias del flujo**: crear el `stock.lot` pedido y prellenar el lote
  de las move lines del albarán (datos que el operador teclearía). PROHIBIDO escribir en `stock.quant` /
  movimientos ya hechos / estados.

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | Al confirmar la Compra Rápida con `material_received=False` y lote indicado, el lote queda **persistido** en el documento de compra/entrada. | Test: wizard PrintFlow (`pf_freeze_qty=True`) con lote → `action_confirm()` → la OC creada trae `pf_lot_name` == lote. |
| CA-2 | Al **validar** el albarán, el lote previsto está **pre-cargado** (no vacío). | Test: la `stock.move.line` de la entrada trae `lot_id`/`lot_name` == lote previsto (y el `stock.lot` existe). |
| CA-3 | La recepción **automática** (`material_received=True`) y la Compra Rápida **normal** quedan intactas. | `test_quick_purchase_grouping`, `test_quick_purchase_without_sale_order`, `test_quick_purchase_multi` verdes; PO sin `pf_lot_name` en el flujo normal. |
| CA-4 | Solo LECTURA de lo existente + la escritura propia del flujo (crear lote/albarán/línea). Sin tocar el motor. | `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; `git status` acotado a PrintFlow. |

### 3.9 Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Prellenar el lote rompe la validación nativa | Alto | D2: `lot_id` (lote existente) + patrón ya probado del motor; NO se valida por detrás. |
| Afectar la Compra Rápida normal / recepción automática | Alto | D5: **GATE** `pf_freeze_qty`; cambios ADITIVOS; candados `test_quick_purchase_*`. |
| Crear `stock.lot` "de más" al confirmar sin validar | Medio | D1/D2: idempotente (`_get_or_create_lot`); lote sin stock es inofensivo (Odoo lo permite). |
| Tocar el motor `x_product_dimensional_pricing` | Alto | D3: fix 100 % en PrintFlow (`_inherit` + `super()`); motor intacto. |
| N+1 al prellenar multi-línea | Bajo | D4: una pasada por OC sobre su propio albarán. |
| Dato inconsistente ya creado (P01807) | Bajo | D6: guía operativa; NO corregir por datos. |

### 3.10 Observaciones (fuera de alcance)
- **O-1**: el header del wizard muestra `material_received=True` (default) aunque la **línea** vaya en
  `False`; es un campo "legacy" que solo aplica cuando NO hay grid. Puede confundir al operador. Se reporta.
- **O-2**: `LOTE-000001` es un correlativo genérico (sin pedido de venta); varios productos sueltos
  podrían chocar con el mismo nombre. Se reporta por si el dueño quiere un criterio de nombre.
- **O-3**: el rastro en `sale.order.pf_lot_name` (32 pedidos) quedó escrito; NO se toca.
- **O-4**: se reutiliza `pf_freeze_qty` como señal "origen PrintFlow"; es una sobrecarga semántica leve del
  campo (que significa "cantidad congelada"), pero es la marca que PrintFlow ya fija en toda Compra Rápida
  de la resolución. Si el dueño quisiera una marca dedicada, se decide en sesión aparte.
- **O-5**: una OC del motor tiene UN solo producto ⇒ `pf_lot_name` (uno por OC) es suficiente; no hay caso
  multi-producto por OC (D4).

### 3.11 Plan de ejecución atómico y secuencial (T1–T4)

> **Ejecución por LOTES de máximo 3 tareas; cada lote = una sesión NUEVA de `odoo-dev`.**
> Convenciones OCA (`odoo-17-clean-architecture` §2.5): un archivo por modelo, métodos `_pf_*`, `snake_case`,
> imports por bloques, orden del modelo (atributos → campos → constraints → default → compute → onchange →
> CRUD → acciones → negocio), nodo `<odoo>`. Regla: **código sí, datos no**; prohibido `cr.execute` de
> escritura y `cr.commit()`.

#### Lote 1 (T1–T3) — Persistencia + prellenado (`models/`)

- [x] **T1 — Campo `pf_lot_name` + prellenado de la entrada en `purchase.order`.**
  - Archivo: **CREAR** `models/purchase_order.py`.
  - `class PurchaseOrder(models.Model)` con `_inherit = 'purchase.order'`.
  - **Campo** (sección CAMPOS, tras los atributos privados): `pf_lot_name = fields.Char(string='Lote previsto',
    help='Nombre del lote indicado en la Compra Rápida; se prellena en el albarán de entrada y se materializa
    como stock.lot al validar.')`.
  - **Override `button_confirm(self)`** (sección ACCIONES, OCA): `res = super().button_confirm(); self._pf_prefill_incoming_lot(); return res`.
  - **`_pf_prefill_incoming_lot(self)`** (método de negocio, `_pf_*`): para `po in self.filtered(lambda p: p.pf_lot_name)`:
    1. `pickings = po.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel') and getattr(p.picking_type_id, 'code', '') == 'incoming')`.
    2. Por cada `picking`: `picking.action_assign()` (nativo; crea/actualiza las move lines).
    3. Por cada `move in picking.move_ids` con `move.product_id.tracking == 'lot'` y `state not in ('done','cancel')`:
       `lot = self.env['mrp.production']._get_or_create_lot(move.product_id, po.pf_lot_name)` (idempotente).
    4. Escribir `{'lot_id': lot.id, 'lot_name': lot.name}` en las `move.move_line_ids` **sin** lote
       (`.filtered(lambda ml: not ml.lot_id)`). NO crear move lines a mano; NO `button_validate`.
  - **NO** se añade ningún helper de negocio nuevo ni se toca el motor.
- [x] **T2 — Persistir el lote al crear la OC (línea del wizard).**
  - Archivo: **MODIFICAR** `models/printflow_quick_purchase_bridge.py`.
  - Añadir una **clase NUEVA** al final del archivo: `class MrpQuickPurchaseWizardLine(models.TransientModel)`
    con `_inherit = 'mrp.quick.purchase.wizard.line'`.
  - Override `_create_purchase_order(self, orders)`: `po = super()._create_purchase_order(orders)`; **si**
    `self.wizard_id.pf_freeze_qty` **y** `self.product_id.tracking == 'lot'` **y** `self.lot_name` →
    `po.pf_lot_name = self.lot_name`. Devolver `po`.
  - **GATE (D5)**: la condición `pf_freeze_qty` deja INTACTA la Compra Rápida normal (que NO fija esa marca).
  - Docstring del "por qué" (persistir el lote de la Compra Rápida de PrintFlow en la OC).
- [x] **T3 — Registrar el modelo en `models/__init__.py`.**
  - Archivo: `models/__init__.py`.
  - Añadir, al final (sección 16), `from . import purchase_order` con un comentario del motivo (campo
    `pf_lot_name` + prellenado del lote de la entrada desde la OC confirmada).
  - `models/` NO importa `wizard/`.

#### Lote 2 (T4) — Test

- [x] **T4 — Test que fija CA-1..CA-4.**
  - **CREAR** `tests/test_quick_purchase_lot_tracking.py` y registrarlo en `tests/__init__.py`.
    - **CA-1 + CA-2**: crear un producto `tracking='lot'` con proveedor (`seller_ids`); abrir la Compra
      Rápida estilo PrintFlow (wizard con `pf_freeze_qty=True` y una línea `material_received=False`,
      `lot_name='LOTE-TEST'`, `product_qty>0`); `action_confirm()` → la OC creada tiene
      `pf_lot_name == 'LOTE-TEST'`; y su albarán de entrada (`picking_type_id.code == 'incoming'`, abierto)
      tiene su `stock.move.line` con `lot_id.name == 'LOTE-TEST'` (y el `stock.lot` existe).
    - **CA-3**: (a) Compra Rápida **normal**: wizard SIN `pf_freeze_qty` (o `False`) con lote → `action_confirm()`
      → la OC queda con `pf_lot_name == False` y sus move lines de entrada **sin** lote prefijado (intacto);
      (b) recepción **automática**: línea con `material_received=True` (wizard normal) → el albarán se valida
      como antes (`state == 'done'`) y la OC no lleva `pf_lot_name`.
    - **CA-4**: `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; motor externo intacto.
  - **NO se modifican** los candados existentes (D5). El archivo usa `TransactionCase` y el helper nativo
    `purchase.order.button_confirm` (no se validan albaranes por detrás).

**Verificación (turno del Verificador, fuera del dev).** `--test-tags` sobre
`/printflow_gestion_inventario:TestQuickPurchaseLotTracking`,
`...:TestFlowComprasPorComprar`, `...:TestFlowComprasDeficitMagnitude`,
`...:TestFlowComprasRecepcionSnapshot`, `/x_product_dimensional_pricing:TestQuickPurchaseGrouping`,
`/x_product_dimensional_pricing:TestQuickPurchaseWithoutSaleOrder`. Al hilo solo vuelve el exit code,
N/N y, si falla, la aserción + cola del traceback.

### 3.12 Contratos que NO deben romperse

- CA-1..CA-4 de 3.8.
- Firma/forma del wizard del motor `mrp.quick.purchase.wizard` / `.line` / `.order`: solo se **AÑADEN** los
  overrides de PrintFlow (`_create_purchase_order` en la línea) y el campo `pf_lot_name` en `purchase.order`;
  `default_get`, `action_confirm`, `_create_purchase_order` (base), `_demand_for_product`, `_validate_incoming_pickings`
  quedan **intactos**.
- `sale.order.pf_lot_name` y el `orders.write({'pf_lot_name': ...})` del engine (L416-418): **intactos**.
- `mrp.quick.purchase.wizard.pf_freeze_qty` (bridge PrintFlow) y `_demand_for_product`: **intactos**.
- `mrp.production._get_or_create_lot`: **reutilizado tal cual** (motor SOLO LECTURA/uso).
- Motor `x_product_dimensional_pricing`: **SIN CAMBIOS** (se hereda/usa desde PrintFlow).
- Compra Rápida **normal** y recepción **automática**: **intactas** (GATE `pf_freeze_qty`).
- `wizard/printflow_product_flow.py` · `wizard/printflow_order_diagnostic_failure.py` · `wizard/printflow_quick_purchase_views.xml`
  · widget `printflow_order_timeline` · `__manifest__.py`: **SIN cambios**.
- `models/` nunca importa `wizard/`.

---

## 3.F (ANEXO · TAREA CERRADA) — Botón "Recalcular" en el diagrama de flujo del producto (paridad de UX)

> **Turno:** Odoo Analista (paso 3: revisar el plan y delegar el Lote 1 a `odoo-dev`). **Estado:** PLAN COMPLETO (D1-D6 cerradas; T1-T4 en 2 lotes).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA` · **Ruta:** `C:\odoo_custom\printflow_gestion_inventario`
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **NORMAL**
> (2 archivos: 1 vista + 1 método de wizard; NO toca ningún flujo nativo). Cadena:
> Analista → Planificador → Analista → Dev → Verificador → Analista.

### 3.1 Problema (evidencia en la vista y en la BD)
El **diagrama de flujo del PRODUCTO** (`printflow.product.flow`, vista `printflow.product.flow.form`,
id **12715** en BD) NO tiene botón **"Recalcular"**, mientras que sus dos pantallas hermanas —que
pintan el MISMO widget OWL `printflow_order_timeline`— SÍ lo tienen:

- **Diagnóstico del PEDIDO** (`printflow.order.diagnostic.wizard`): `action_recalculate` en el
  `<footer>` (`wizard/printflow_order_diagnostic_wizard_views.xml` L231).
- **Diagnóstico/Escáner de PRODUCTO** (`printflow.product.diagnostic.wizard`): `action_recalculate`
  en el `<header>` (`wizard/printflow_product_diagnostic_views.xml` L18).

Evidencia:
- La vista del diagrama de producto (arch REAL leída de la BD, id **12715**) es un
  `<form create="false" edit="false" delete="false">` que **NO tiene `<header>` ni `<footer>`**: solo un
  `button_box` con el botón "Producto". Sin `<header>`/`<footer>` no hay dónde pintar el botón.
- `action_recalculate` existe en el código SOLO en 3 vistas: pedido, escáner de producto y
  diagnóstico de BOM kit. En el diagrama de producto, NO existe.
- Solo DOS vistas usan el widget `printflow_order_timeline`: el PEDIDO y el PRODUCTO (por eso "se ven
  iguales"; son pantallas distintas, no la misma).
- El diagrama del producto se abre desde: (a) Salud de Inventario → Productos (catálogo) → clic en el
  producto (`printflow.inventory.catalog.action_open_flow` → hook `_pf_product_flow_action` →
  `printflow.product.flow.action_open_product_flow`); (b) acción de servidor "Ver diagrama de flujo
  (PrintFlow)" de la ficha del producto (`data/printflow_product_flow_server_action.xml`).

Consecuencia: tras validar/confirmar algo en OTRA pestaña (una OC, una recepción, una reserva), el
diagrama del producto muestra datos **viejos** (caché de los campos compute `timeline_json`,
`severity`, `root_cause_node`, `chain_summary`) y el operador debe **cerrar y volver a abrir** para
ver los cambios. El botón "Recalcular" cierra esa brecha.

### 3.2 Objetivo (acotado)
**SÍ:**
1. Añadir el botón **"Recalcular"** al diagrama de flujo del PRODUCTO, con el mismo look & feel de sus
   hermanas (`class="btn-secondary" icon="fa-refresh"`, title "Volver a calcular…").
2. Su acción debe **re-ejecutar el barrido con los datos actuales** y refrescar el diagrama **SIN
   recrear el wizard** (mismo registro), replicando el patrón ya existente.
3. **Sin escribir datos** persistentes (SOLO LECTURA; se invalida caché y se recalcula).

**NO:**
- NO tocar el motor externo `x_product_dimensional_pricing` (solo LECTURA).
- NO tocar el builder (`printflow.flow.payload.builder`), el widget (`printflow_order_timeline.*`) ni
  el contrato del payload del canvas (SIN claves nuevas).
- NO tocar el diagrama del PEDIDO ni el escáner (paridad intacta).
- NO escribir datos (prohibido `cr.execute` de escritura / `cr.commit()`).

### 3.3 Contrato funcional (objetivo de la vista)
| Superficie | Debe quedar |
|---|---|
| Botón "Recalcular" | Visible en el diagrama del producto; texto "Recalcular"; `icon="fa-refresh"`; `class="btn-secondary"`; title "Volver a calcular el diagnóstico con los datos actuales". Vive en el `<header>` (statusbar) o `<footer>` del form (lo cierra el Planificador, D1; recomendado `<header>`: el `<footer>` solo se renderiza en diálogo). |
| Acción `action_recalculate()` | Método PÚBLICO en `printflow.product.flow`: invalida la caché de las fuentes y **devuelve una acción que recarga el wizard** (`res_model=self._name`, `res_id=self.id`, `view_mode='form'`, `target='current'`), espejo del escáner (`printflow_product_diagnostic_wizard.py` L306-313). |
| Diagrama y cabecera | Tras pulsar: `timeline_json`, `severity`, `root_cause_node`, `flow_type` y `chain_summary` se recalculan FRESCOS. |
| Resto del diagrama (leyenda, franja de cadena, botón "Producto") | **Sin cambios**. |
| Contrato del payload / widget | **Sin cambios** (SIN claves nuevas; solo se refresca). |

### 3.4 Fuente ÚNICA / patrón a reutilizar (cero reinvención)
- **Patrón del botón y su acción:** `wizard/printflow_product_diagnostic_wizard.py::action_recalculate`
  (L290-313) y `wizard/printflow_order_diagnostic_wizard.py::action_recalculate` (L1680).
- **Cómputo del diagrama (YA EXISTE):** `printflow.product.flow._compute_timeline_json`
  (`printflow.flow.canvas._pf_build_payload(rec, 'product')`) y `_compute_header_fields`.
- **Frescura de datos:** mismo cuidado que `tests/test_diagnostic_recalculate_health_refresh.py` (los
  almacenados pueden quedar viejos). Usar `invalidate_model`/`invalidate_recordset` de las FUENTES
  (producto y motores), NUNCA escribir.
- **Sin helpers nuevos de negocio:** la lógica ya vive en el canvas/estrategia; el botón SOLO fuerza el
  recómputo.

### 3.5 Decisiones de diseño cerradas (D1–D5)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` ·
> Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no**
> (SOLO LECTURA; se invalida la caché del ORM, jamás se escribe en la BD). El diseño se **engancha** al
> patrón ya existente del escáner/pedido y **NO toca** el motor `x_product_dimensional_pricing`, el
> builder ni el widget/payload.

**D1 — Ubicación del botón: `<header>` (CERRADA).**
- El botón se pinta en el `<header>` (barra de estado, `o_form_statusbar`), como PRIMER hijo de
  `<form>`, antes de `<sheet>`. **NO** en `<footer>`.
- Por qué: el `<footer>` solo se renderiza cuando `env.inDialog`; el diagrama del producto se abre
  SIEMPRE a pantalla completa (`printflow.product.flow.action_open_product_flow` devuelve
  `target='current'`, y TODOS sus llamadores —catálogo y server action— pasan por ahí) ⇒ un `<footer>`
  no se vería. Es EXACTAMENTE el criterio documentado en la vista del escáner de producto
  (`printflow_product_diagnostic_views.xml` L12-16), que usa `<header>` por el mismo motivo.

**D2 — Qué invalida "Recalcular" (CERRADA).**
- Los compute del wizard (`_compute_header_fields`, `_compute_timeline_json`) dependen SOLO de
  `product_id`; como el botón NO cambia `product_id`, hay que forzar el recómputo soltando la caché del
  ORM (sin escribir nada).
- Lista EXACTA a invalidar:
  1. **Fuentes del producto** (las que lee `printflow.flow.strategy.product._pf_flow_context`):
     `self.env['product.product'].invalidate_model(['qty_available', 'outgoing_qty', 'incoming_qty',
     'free_qty', 'virtual_available'])` — la familia de cantidades computadas del producto (mismas
     fuentes: movimientos/quants). Operación de CACHÉ, no de BD.
  2. **Compute del wizard**: `self.invalidate_recordset()` (suelta `name`, `flow_type`, `severity`,
     `root_cause_node`, `chain_summary`, `timeline_json`).
- **NO** hacen falta `clear_caches`: verificado por búsqueda — ni `printflow_gestion_inventario/models/`
  ni el motor externo `x_product_dimensional_pricing` usan `@tools.ormcache`/`clear_caches`. Tampoco se
  tocan `printflow.flow.pending` ni `printflow.order.health.engine`: leen por `search`/`read` en vivo
  (sin caché propia).
- **SIN escritura**: prohibido `cr.execute`/`cr.commit`; `invalidate_*` solo suelta la caché en memoria.

**D3 — Recrear vs recargar: recargar el MISMO registro (CERRADA).**
- `action_recalculate()` devuelve un `ir.actions.act_window` con `res_model=self._name`,
  `res_id=self.id`, `view_mode='form'`, `target='current'`. **NO** recrea el wizard.
- `target='current'` (no `'new'`): conserva la pantalla completa del diagrama. El escáner usa
  `'current'` en contexto de pedido; el pedido usa `'new'` porque vive en diálogo. Aquí el diagrama es
  pantalla completa ⇒ `'current'`.

**D4 — Estado del popover/OWL: nada que preservar (CERRADA).**
- El diagrama del producto NO persiste foco de nodo (a diferencia del pedido, que tiene `focus_line_id`):
  `printflow.product.flow` no expone ningún campo de foco ⇒ basta invalidar la caché y recargar el mismo
  registro. Cero trabajo extra.

**D5 — Impacto en tests/candados (CERRADA).**
- `tests/test_product_flow_canvas.py`: valida CAMPOS del wizard y el payload, NO la arch de la vista ⇒
  el `<header>` nuevo no lo afecta.
- `tests/test_product_flow_production_signals.py::test_product_flow_view_has_legend_and_chain`: usa
  `assertIn` sobre la arch ⇒ un `<header>` ADITIVO no lo rompe.
- `tests/test_product_flow_payload_parity.py`: SIN claves nuevas en el payload (el botón solo fuerza el
  recómputo) ⇒ el esqueleto congelado y `BASE_NODE_KEYS` quedan INTACTOS.
- NO se toca ningún candado existente. **CREAR** `tests/test_product_flow_recalculate.py` (CA-1..CA-4) y
  registrarlo en `tests/__init__.py`.

### 3.6 Archivos candidatos (el Planificador confirma/ajusta)
| Acción | Archivo | Qué se cambia |
|---|---|---|
| MODIFICAR | `wizard/printflow_product_flow_views.xml` | Añadir el `<header>` (o `<footer>`) con el botón "Recalcular" → `action_recalculate`. |
| MODIFICAR | `wizard/printflow_product_flow.py` | Nuevo `def action_recalculate(self)` (invalida caché + devuelve el `act_window` de recarga). |
| CREAR/MODIFICAR | `tests/*` | Test que fija CA-1..CA-4; registrar en `tests/__init__.py`. |

**SIN CAMBIOS (a propósito):** motor `x_product_dimensional_pricing`; builder
`printflow_flow_payload_builder.py`; widget `static/src/js|xml/printflow_order_timeline.*`; estrategia
`.order`; `__manifest__.py`; `data/printflow_product_flow_server_action.xml`.

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): SOLO LECTURA; PROHIBIDO `cr.execute` de
  escritura / `cr.commit()`.
- **No forzar ni reinventar flujos nativos**: se engancha con el patrón existente; cero escrituras.
- **NO tocar el motor** `x_product_dimensional_pricing` ni el widget/builder/payload.
- **NO romper la paridad del pedido** ni el escáner (`test_flow_canvas_parity.py`, `test_diagnostic_*`).
- **`models/` nunca importa `wizard/`.** Sin CSS nuevo. Un archivo por responsabilidad.

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | La vista del diagrama de producto incluye el botón "Recalcular" que invoca `action_recalculate`. | Inspección de la arch (`//button[@name='action_recalculate']` en `wizard/printflow_product_flow_views.xml`); la vista carga sin error en el `-u`. |
| CA-2 | `action_recalculate()` recarga el MISMO wizard (`res_model='printflow.product.flow'`, `res_id=self.id`) y el diagrama refleja datos FRESCOS. | Test: cambiar una fuente (p. ej. existencia) → `timeline_json`/`severity` cambian tras el botón. |
| CA-3 | Solo lectura. | `TransactionCase` (rollback); sin `cr.execute`/`cr.commit` en producción. |
| CA-4 | Paridad intacta: pedido y escáner sin cambios; motor/builder/widget/payload intactos. | `test_flow_canvas_parity.py`, `test_diagnostic_*`, `test_product_flow_canvas.py` verdes. |

### 3.9 Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| "Recalcular" no refresca (caché no invalidada) | Medio | Invalidar explícitamente las fuentes (D2) + test CA-2. |
| El `<header>`/`<footer>` rompe el layout del form | Bajo | Seguir el patrón del escáner/pedido; inspección de arch. |
| Tocar el payload/widget por inercia | Alto | Restricción dura: sin claves nuevas; solo recómputo. |
| Tocar datos al "recalcular" | Crítico | Solo LECTURA; `TransactionCase`. |

### 3.10 Observaciones (fuera de alcance)
- **O-1**: la causa raíz es de **paridad de UX** entre pantallas hermanas que comparten widget; NO es un
  defecto del motor de flujo.
- **O-2**: si el dueño quisiera además un "Recalcular" en el catálogo u otros listados, se decide en
  sesión aparte.
- **O-3**: el diagrama del pedido y el escáner conservan su propio `action_recalculate`; NO se tocan.

### 3.11 Plan de ejecución atómico y secuencial (T1–T3)

> **Ejecución por LOTES de máximo 3 tareas; cada lote = una sesión NUEVA de `odoo-dev`.**
> Como el plan tiene **≤3 tareas**, hay **un solo lote**. Convenciones OCA
> (`odoo-17-clean-architecture` §2.5): métodos `action_*`/`_pf_*`, `snake_case`, un archivo por
> responsabilidad, `<?xml ... ?>` + nodo `<odoo>`, `id` antes de `model`. **SOLO LECTURA** de BD
> (search/read); prohibido `cr.execute` de escritura y `cr.commit()`.

#### Lote 1 (T1–T3) — Método + vista + test

- [x] **T1 — Método `action_recalculate()` en el wizard del producto.**
  - Archivo: `wizard/printflow_product_flow.py`.
  - Añadir una sección NUEVA "ACCIONES (recómputo solo lectura)" justo DESPUÉS del bloque CÓMPUTOS
    (tras `_compute_timeline_json`) y ANTES del bloque "CONTEXTO DEL CANVAS" (espejo del escáner:
    computes → acciones). Contenido del método (el Dev lo escribe con su docstring, con el estilo del
    archivo):
    ```python
    def action_recalculate(self):
        """Recalcula el diagrama sobre el MISMO wizard (sin recrearlo)."""
        self.ensure_one()
        if not self.product_id:
            return {'type': 'ir.actions.act_window_close'}
        # 1) Fuentes del producto (cantidades computadas): suelta la caché del
        #    ORM para releer movimientos/quants actuales (SIN escribir en BD).
        self.env['product.product'].invalidate_model([
            'qty_available', 'outgoing_qty', 'incoming_qty',
            'free_qty', 'virtual_available'])
        # 2) Compute del wizard (dependen de product_id, que NO cambia).
        self.invalidate_recordset()
        # 3) Recarga el MISMO registro a pantalla completa.
        return {
            'type': 'ir.actions.act_window',
            'name': self.name or _('Flujo del producto'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
    ```
  - **NO** se reimplementa el cómputo: reutiliza `_compute_header_fields`/`_compute_timeline_json` y el
    canvas. **NO** se añade ningún helper de negocio nuevo ni se toca el motor/builder/widget.
- [x] **T2 — Botón "Recalcular" en el `<header>` de la vista.**
  - Archivo: `wizard/printflow_product_flow_views.xml`, record `printflow_product_flow_view_form`.
  - Insertar, como PRIMER hijo de `<form create="false" edit="false" delete="false">` y ANTES de
    `<sheet>`:
    ```xml
    <header>
        <button name="action_recalculate" type="object" string="Recalcular"
                class="btn-secondary" icon="fa-refresh"
                title="Volver a calcular el diagnóstico con los datos actuales"/>
    </header>
    ```
  - Resto de la vista INTACTO (button_box, h1, group, `timeline_json`, leyenda y franja de cadena).
  - `__manifest__.py` **SIN cambios** (la vista ya está declarada en `data`).
- [x] **T3 — Test que fija CA-1..CA-4.**
  - **CREAR** `tests/test_product_flow_recalculate.py` y registrarlo en `tests/__init__.py`.
    - **CA-1**: `env.ref('printflow_gestion_inventario.printflow_product_flow_view_form').arch_db`
      contiene `name="action_recalculate"` (el botón vive en la arch).
    - **CA-2**: `wizard.action_recalculate()` devuelve `ir.actions.act_window`
      (`res_model='printflow.product.flow'`, `res_id=wizard.id`, `view_mode='form'`, `target='current'`);
      tras cambiar una FUENTE (existencia: `-3.0` → `+3.0`), `timeline_json` y `severity` cambian (datos
      FRESCOS).
    - **CA-3**: `TransactionCase` (rollback); sin `cr.execute`/`cr.commit` (solo `invalidate_*`).
    - **CA-4**: `timeline_json == json.dumps(_pf_build_payload(wizard, 'product'))` tras el recálculo
      (paridad serializado↔fábrica) — candado ADITIVO, sin tocar los candados existentes.

**Verificación (turno del Verificador, fuera del dev).** `--test-tags /printflow_gestion_inventario` (o
subconjunto: `test_product_flow_recalculate`, `test_product_flow_canvas`,
`test_product_flow_canvas_controls`, `test_product_flow_payload_parity`, `test_product_flow_actions`,
`test_flow_canvas_parity`, `test_diagnostic_timeline_payload`, `test_product_flow_production_signals`).
Al hilo solo vuelve el exit code, N/N y, si falla, la aserción + cola del traceback.

### 3.12 Contratos que NO deben romperse

- CA-1..CA-4 de 3.8.
- Firma/forma de `printflow.flow.canvas._pf_build_payload(host, mode)` y del builder (SIN claves nuevas).
- Widget `printflow_order_timeline` (+ XML) y `static/src/js|xml/printflow_open_timeline.*`: SIN cambios.
- Payload del producto: `timeline_json` serializado == fábrica (candado `test_product_flow_payload_parity`).
- Motor externo `x_product_dimensional_pricing`: SOLO LECTURA.
- Estrategia `.order`, escáner de producto y diagnóstico de pedido: SIN cambios (paridad intacta).
- `__manifest__.py`: SIN cambios.

---

## 3.E (ANEXO · TAREA CERRADA) — Maquetación de la Compra Rápida (regresión visual)

> **Turno:** Odoo Analista (cierre de ciclo). **Estado:** CERRADA (Dev: exit 0, **13/13 verdes**;
> camino rápido Trivial ⇒ sin Verificador formal).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA` · **Ruta:** `C:\odoo_custom\printflow_gestion_inventario`
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **TRIVIAL**
> (un solo archivo de vista; ajuste de MAQUETACIÓN, sin diseño nuevo): **camino rápido**
> Analista → Dev (se saltan Planificador y Verificador; los tests relevantes los corre el Dev en
> su lote, y al cierre el Analista aplica la compuerta §4.3).

### 3.1 Problema (evidencia en la vista y en la BD)
La tarea anterior (ver **anexo 3.D**) añadió —por herencia de vista, tarea T9— el botón
**"Traer pedidos que requieren compra"** (método `action_pf_import_requiring_orders` del bridge)
**antes** del campo `order_line_ids` de la Compra Rápida. Ese `<button>` se insertó **dentro del
grid del `<group string="Pedido">`** (que es una tabla de **2 columnas**), por lo que el botón pasó a
**compartir fila** con el `order_line_ids`:

- El botón quedó en la celda IZQUIERDA (ancho mínimo) ⇒ su texto se envuelve **en vertical**
  ("Traer / pedidos / que / requieren / compra").
- El campo `order_line_ids` ("Agrupar pedidos") quedó **comprimido a la mitad derecha**, así que su
  tabla sale con las columnas **mal repartidas**: la del selector `sale_order_id` (que ahora muestra
  "número − cliente", D5/3.D) queda **encogida** ("P…") y la de `partner_id` ("Cliente")
  desproporcionada.

Evidencia:
- Vista heredada (regresión): `views/printflow_quick_purchase_views.xml` L23-28 → `<xpath
  expr="//field[@name='order_line_ids']" position="before">` con un `<button>` **suelto**
  (sin contenedor de ancho completo).
- Vista base (motor externo, **SOLO LECTURA**): `x_product_dimensional_pricing/wizard/
  mrp_quick_purchase_wizard_views.xml` L9-22 → el `order_line_ids` vive dentro de
  `<group string="Pedido" colspan="2">` (grid de 2 columnas).
- BD (`odoo-impreven` / `Ciber Estudios 2015 RESTAURADA`): `ir.ui.view` id **12751**
  (`printflow_gestion_inventario.mrp_quick_purchase_wizard_form_pf`, `mode=extension`,
  `active=true`) hereda de id **11764** (`x_product_dimensional_pricing.mrp_quick_purchase_wizard_form`).
- Captura del dueño ("Compra Rápida (producto)"): botón "Traer pedidos…" **en vertical** a la
  izquierda y tabla "Agrupar pedidos" apretada (cabeceras "P…" │ "Cliente").

### 3.2 Objetivo (acotado)
**SÍ:**
1. Devolver a la Compra Rápida su **maquetación correcta**: el botón "Traer pedidos que requieren
   compra" en su **propia fila de ancho completo** (sin compartir celda con la tabla) y la tabla de
   "Agrupar pedidos" ocupando el **ancho completo**, con la columna del selector legible.
2. **Cero cambios de comportamiento**: el botón sigue llamando a `action_pf_import_requiring_orders`
   y sigue visible solo con `product_id`; el contexto `pf_purchase_partner_label` del selector
   `sale_order_id` queda **igual**.

**NO:**
- NO tocar la lógica (bridge `printflow_quick_purchase_bridge.py`, estrategias, motor de pendientes,
  `action_pf_import_requiring_orders`).
- NO tocar la vista base del motor `x_product_dimensional_pricing` (se hereda igual, `position`
  ADITIVA, **sin `position="replace"`**).
- NO tocar el motor externo, el payload, el widget ni los tests/candados existentes.
- NO escribir datos.

### 3.3 Contrato funcional (objetivo de la vista)
| Superficie | Debe quedar |
|---|---|
| Botón "Traer pedidos que requieren compra" | En su **propia fila de ancho completo**, alineado a la izquierda; texto en una sola línea (o envuelto de forma natural, **NUNCA vertical letra por letra**). Visible solo con `product_id` (`invisible="not product_id"`). |
| Campo `order_line_ids` ("Agrupar pedidos") | Ocupando el **ancho completo** del grupo ⇒ su tabla muestra las columnas con ancho razonable (selector "número − cliente" legible). |
| Contexto del selector `sale_order_id` | **Intacto**: `{'pf_purchase_partner_label': True}`. |
| Resto del wizard ("Compras a registrar", "Comprobante de Pago", footer) | **Sin cambios**. |

### 3.4 Fuente ÚNICA / patrón a reutilizar (cero reinvención)
- Mismo patrón ya usado en la vista BASE del propio motor para los textos de ancho completo:
  `<div class="text-muted small" colspan="2">` (`mrp_quick_purchase_wizard_views.xml` L52-55 y
  L61-64). Es decir, dentro de un `<group>`, un contenedor con `colspan="2"` ocupa la **fila
  completa**: ese es el mecanismo a reutilizar (no se inventa CSS ni clases nuevas).
- No hay helpers nuevos: es XML de vista. **CERO CSS nuevo.**

### 3.5 Cambio concreto (lo mínimo)
- Archivo: `views/printflow_quick_purchase_views.xml` (**ÚNICO archivo**).
- **Envolver** el `<button>` existente en un contenedor de **ancho completo** (p. ej.
  `<div colspan="2" class="mb-2"> … </div>`) dentro del mismo
  `<xpath expr="//field[@name='order_line_ids']" position="before">`.
- **Dar `colspan="2"`** al `field order_line_ids` (vía
  `<xpath expr="//field[@name='order_line_ids']" position="attributes">` →
  `<attribute name="colspan">2</attribute>`) para que su tabla recupere el ancho completo del grupo.
- Dejar **INTACTO** el `xpath` que añade el contexto `{'pf_purchase_partner_label': True}` al
  `sale_order_id` del tree.
- **Sin `position="replace"`**; sin tocar el motor ni el bridge.

> Nota: con `colspan="2"` la etiqueta "Agrupar pedidos" pasa a verse **encima** de la tabla (label
> arriba, tabla a ancho completo). Es el comportamiento esperado.

### 3.6 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): SOLO se edita el XML de la vista;
  PROHIBIDO `cr.execute` de escritura / `cr.commit()`.
- **No forzar ni reinventar flujos nativos**: es MAQUETACIÓN; no se altera ningún método.
- **NO tocar el motor** `x_product_dimensional_pricing` (ni su vista base): solo se hereda.
- **Payload / widget / estrategias intactos**; `__manifest__.py` **SIN cambios** (la vista ya está
  declarada en `data`).
- **Sin `position="replace"`**.

### 3.7 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | El botón "Traer pedidos que requieren compra" queda en su **propia fila de ancho completo** (no comparte celda con la tabla). | Inspección de la arch heredada: el `<button>` va envuelto en un contenedor `colspan="2"` dentro del `xpath position="before"` del `order_line_ids`. |
| CA-2 | La tabla de "Agrupar pedidos" ocupa el **ancho completo**; el selector `sale_order_id` es legible. | El `field order_line_ids` lleva `colspan="2"`; la vista carga sin error en el `-u`. |
| CA-3 | **Sin regresión funcional**: el botón sigue visible solo con `product_id`, invoca `action_pf_import_requiring_orders`, y el contexto del selector sigue `{'pf_purchase_partner_label': True}`. | `TestFlowComprasPorComprar` (8/8, CA-1..CA-6) verde; `TestQuickPurchaseGrouping` / `TestQuickPurchaseWithoutSaleOrder` verdes. |
| CA-4 | Solo lectura / sin tocar el motor externo. | Sin `cr.execute`/`cr.commit`; `git status` solo con el XML de vista modificado. |

### 3.8 Plan de ejecución (atómico)
- [x] **T1 — Maquetación del botón y de la tabla (único archivo).**
  - Archivo: `views/printflow_quick_purchase_views.xml`.
  - Envolver el `<button name="action_pf_import_requiring_orders" …>` en un contenedor de ancho
    completo (`<div colspan="2" class="mb-2"> … </div>`) dentro del
    `<xpath expr="//field[@name='order_line_ids']" position="before">`.
  - Añadir `colspan="2"` al `<field name="order_line_ids">` (mediante un `xpath … position="attributes"`).
  - Dejar **INTACTO** el `xpath` del contexto `pf_purchase_partner_label` del `sale_order_id`.
  - **Verificación del Dev (salida a archivo):** `-u printflow_gestion_inventario` carga sin error
    (log `loading …/views/printflow_quick_purchase_views.xml`); `--test-tags` sobre
    `TestFlowComprasPorComprar`, `TestQuickPurchaseGrouping`, `TestQuickPurchaseWithoutSaleOrder`
    → exit 0, todo verde.

**Verificación (turno del Verificador).** *Camino rápido (Trivial): NO se convoca al Verificador; la
evidencia de tests del lote del Dev es suficiente.* La vista se valida por inspección de la arch
heredada + carga sin error.

### 3.9 Contratos que NO deben romperse
- CA-1..CA-4 de 3.7.
- `action_pf_import_requiring_orders` (bridge) y su `invisible="not product_id"`.
- Contexto `{'pf_purchase_partner_label': True}` del selector `sale_order_id` (CA-5 de 3.D).
- Vista base `x_product_dimensional_pricing.mrp_quick_purchase_wizard_form` (**NO** se toca).
- `mrp.quick.purchase.wizard` / `.line` / `.order`: sin cambios de campos ni métodos.
- La **Compra Rápida NORMAL** (sin `pf_freeze_qty`) intacta.

### 3.10 Observaciones (fuera de alcance)
- **O-1**: si con `colspan="2"` la etiqueta "Agrupar pedidos" sube sobre la tabla, es estética
  aceptable; el requisito es que las **columnas** sean legibles.
- **O-2**: el botón mantiene el texto largo ("Traer pedidos que requieren compra"); si aun así se ve
  desproporcionado, se decide en una sesión aparte si acortarlo (NO en esta tarea, para no cambiar
  textos sin pedido del dueño).

---

## 3.D (ANEXO · TAREA CERRADA) — Faltante REAL y pedidos por comprar en el nodo Compras

> **Turno:** Odoo Analista (cierre). **Estado:** CERRADA (Verificador `cumple`: exit 0, `TestFlowComprasPorComprar` **8/8** CA-1..CA-6 + candados **24/24** verdes).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA` · **Ruta:** `C:\odoo_custom\printflow_gestion_inventario`
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **GRANDE**
> (toca el flujo de Compras): cadena completa Analista → Planificador → Analista → Dev →
> Verificador → Analista.

### 3.1 Problema (evidencia en la BD)
La resolución del nodo **COMPRAS** (faltante → Compra Rápida) tiene **dos huecos** que producen
**duplicidad de existencias** y **pérdida de trazabilidad**:

**(a) El faltante está INFLADO: no descuenta lo ya pedido sin confirmar.**
Hoy el faltante que se muestra y se compra es `outgoing_qty − qty_available − incoming_qty`
= 35 − 4 − 0 = **31**. NO descuenta las **OC en borrador** del producto, así que si el operador
**confirma esas OC y además compra el faltante, DUPLICA entradas**.

**(b) La resolución no muestra los pedidos que requieren la compra.**
`_pf_open_quick_purchase` abre la Compra Rápida con "Agrupar pedidos" **vacío**: el operador debe
buscar los pedidos uno a uno, y el selector solo muestra el número de venta (`S06637`), **no el
cliente**.

Evidencia (producto `IMPRESION BANNER ` id 13571 / plantilla 8329; `purchase_ok=True`; **sin BOM**
⇒ no fabricable; nodo de quiebre = **Compras**):

| Dato | Valor |
|---|---|
| Demanda pendiente (`outgoing_qty`, 29 pedidos) | 35 |
| Existencia (`qty_available`) | 4 |
| En camino (`incoming_qty`) | 0 |
| **Faltante que muestra hoy el sistema** | **31** |
| OC en **borrador** del producto | **4** (6 u): P00290 (S03215, 1), P00295 (S03253, 1), P00297 (S03275, 3), P00300 (S03281, 1) |
| De esas, las que cubren pedidos con **entrega pendiente** | **3** (5 u): S03253, S03275, S03281 |
| **Faltante real por pedir** = 35 − 4 − 5 | **26** |
| OC **canceladas** del producto | 5 (3 de ellas de pedidos que siguen esperando: S03297, S03442, S03447) |
| Pedidos que **requieren** compra (entrega pendiente y **sin compra en trámite**) | **26** = 19 sin OC (22 u) + 7 con OC **ya recibida** (8 u) |

Comprobación: **4 (existencia) + 5 (OC a confirmar) + 26 (compra nueva) = 35**. ✅

### 3.2 Objetivo (acotado)
**SÍ:**
1. El nodo **Compras** debe mostrar el **faltante REAL** = demanda − existencia − en camino −
   **lo ya pedido en OC sin confirmar** (hoy **26**, no 31).
2. El nodo debe **explicitar que hay OC sin confirmar** (documentos vinculados a pedidos que solo
   requieren confirmarse), para que se entienda **por qué** el faltante no cubre todos los pedidos.
3. La **resolución** del nodo debe abrir la **Compra Rápida** con cantidad = **faltante real (26)**,
   y esa cantidad **NO debe recalcularse** con la lista de pedidos.
4. La Compra Rápida debe ofrecer un **botón/acción** que traiga a "Agrupar pedidos" los **pedidos
   que requieren la compra** (entrega pendiente del producto y **sin compra en trámite**).
5. En el selector de "Agrupar pedidos", el operador debe leer **"número de venta − cliente"**.
6. **General/reutilizable**: aplica a CUALQUIER producto y a AMBOS diagramas (producto y pedido) sin
   romper la paridad. **Sin hardcode**.

**NO:**
- NO tocar el motor `x_product_dimensional_pricing` (solo LECTURA / reutilizar). **Extender** con
  `_inherit` + `super()` sí.
- NO escribir datos (SOLO LECTURA; la OC se crea únicamente al pulsar "Confirmar Compras").
- NO reimplementar: reutilizar `deficit_qty`/`_pf_deficit_qty`, el motor de pendientes
  (`printflow.flow.pending`) y `_find_purchase_orders_by_sale_names`.
- NO romper la paridad del pedido. El método manual del operador SE QUEDA.

### 3.3 Contrato funcional
| Nodo / superficie | Debe mostrar / hacer |
|---|---|
| **Compras** (ambos diagramas) | Magnitud = **faltante real** (descuenta OC sin confirmar): "Faltan comprar **26**". Señal SECUNDARIA/explicativa: "**N OC sin confirmar**". |
| **Compras · resolución** | Abrir la **Compra Rápida** con producto + cantidad = **26**, cantidad **CONGELADA** (no recalculada por la lista de pedidos). |
| **Compra Rápida · "Agrupar pedidos"** | Botón/acción que **importa** los pedidos que requieren compra (entrega pendiente y sin compra en trámite). |
| **Compra Rápida · selector** | Mostrar "**S03253 − Cliente**". |
| Inventario / Entrega | Sin cambios. |
| Compra Rápida (operador manual) | Sin cambios: el operador sigue eligiendo pedidos a mano. |

### 3.4 Fuente ÚNICA a reutilizar (cero reinvención)
- **Faltante actual:** `models/printflow_flow_strategy_product.py::_pf_flow_context` (L83-88) y
  `wizard/printflow_product_flow.py::_pf_deficit_qty` (L444-455). **AJUSTAR** para restar lo pedido
  sin confirmar. (En el pedido: `wizard/printflow_order_diagnostic_failure.py::_pf_deficit_qty`.)
- **OC sin confirmar:** `printflow.flow.pending.PURCHASE_UNCONFIRMED_STATES` /
  `_pf_purchase_unconfirmed_states()` (fuente única ya existente).
- **Pedidos ↔ OC:** `printflow.purchase.link.mixin._find_purchase_orders_by_sale_names` (vínculo por
  `origin`; ya existe y lo usa el tablero).
- **Pedidos con entrega pendiente:** motor de pendientes
  `printflow.flow.pending._pf_node_pending_rows('delivery', ...)` (misma lectura del nodo Entrega).
- **Vínculo picking → venta:** patrón de `printflow_finding_resolution.pf_reserving_sale_orders`
  (`picking_id.sale_id` | `move.sale_line_id.order_id`).
- **Compra prellenada (YA EXISTE):** `_pf_open_buy_product` → `_pf_open_quick_purchase`
  (`material_received=False`, sin forzar recepción).
- **Etiquetas:** `printflow.flow.presentation._PF_NODE_SHORTFALL_LABELS` / `_PF_NODE_PENDING_LABELS`.
- **Wizard de Compra Rápida (motor, solo lectura):** `x_product_dimensional_pricing/wizard/mrp_quick_purchase_wizard.py`
  (`_demand_for_product` L187-209 y `_create_purchase_order` L646-680 son el punto donde hoy se recalcula la cantidad).

### 3.5 Decisiones de diseño cerradas (D1–D8)

> **Cierre del Odoo Planificador.** Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` ·
> Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no**
> (SOLO LECTURA: `search`/`read`). El diseño se **engancha** a lo ya existente (motor de pendientes,
> `deficit_qty`, `_pf_open_buy_product` → Compra Rápida, `_find_purchase_orders_by_sale_names`) y
> **NO toca** el motor externo `x_product_dimensional_pricing`. **Sin claves nuevas** en el payload
> del widget: el badge `shortfall_qty`/`shortfall_label` y el badge `pending`/`pending_label` de las
> tareas 3.B/3.C se REUTILIZAN.

**D1 — Fórmula del "faltante real" y su alcance (CERRADA).**
- Definición: `faltante_real(P) = max(0, déficit_físico(P) − cobertura_sin_confirmar(P))`, donde
  `déficit_físico = outgoing_qty − qty_available − incoming_qty` (el MISMO `deficit` que ya calcula
  cada estrategia) y `cobertura_sin_confirmar(P)` = unidades de las líneas de OC del producto en
  estado **sin confirmar** (`draft`/`sent`/`to approve`, FUENTE ÚNICA `PURCHASE_UNCONFIRMED_STATES`)
  cuyo `origin` referencia un **pedido con entrega pendiente del producto**.
- Por qué 5 y no 6 (caso real): la OC P00290 (S03215) es de un pedido **colgado** (entrega cancelada,
  sin demanda pendiente) ⇒ su unidad NO cubre demanda ⇒ no se resta (O-1/H-005). 35 − 4 − 5 = **26**.
- DÓNDE se calcula: nuevo helper en el **motor de pendientes** `printflow.flow.pending`
  (`_pf_purchase_unconfirmed_cover`). NO se toca el motor externo.
- **Alcance del nodo:** SOLO el badge de **Compras** (`shortfall_by_key['purchase']`). El nodo
  **Inventario** NO cambia: su "Sin stock: N" es el déficit físico (magnitud distinta). El `deficit`
  crudo (veredicto / `playbook_ctx` / `physical_remedy`) NO se altera.
- Candado: sin OC sin confirmar, `cobertura = 0` ⇒ `shortfall == déficit` (los candados actuales
  siguen verdes).

**D2 — Señal explícita de "OC sin confirmar" (CERRADA).**
- Se REUTILIZA el badge `pending` / `pending_label` ya existente (tarea 3.B): "**N OC sin
  confirmar**" (N = **DOCUMENTOS** de OC sin confirmar del producto = cuántas OC debe CONFIRMAR el
  operador). NO se añade clave nueva al payload.
- O-3 resuelto: el badge cuenta DOCUMENTOS (acción: "confirmá estas N OC") y el badge de faltante
  descuenta UNIDADES cubiertas (acción: "comprá estas M"); son dos lecturas complementarias. No se
  inventa un desglose de unidades para no engordar el payload.

**D3 — Congelar la cantidad de la Compra Rápida (CERRADA).**
- Mecanismo (`_inherit` + `super()`): nuevo `models/printflow_quick_purchase_bridge.py` que hereda
  `mrp.quick.purchase.wizard`, añade `pf_freeze_qty = fields.Boolean(...)` y sobrescribe
  `_demand_for_product(self, product)`:
  `res = super()._demand_for_product(product); return 0.0 if self.pf_freeze_qty else res`.
- Por qué basta: `_demand_for_product` es la ÚNICA fuente de recálculo (la usan
  `_onchange_recompute_qty` vía `_total_component_demand`, el `_onchange_product_id` de la línea y
  `_create_purchase_order`). Devolver `0.0` con la marca congela la cantidad sin ramificar por caso.
- La **Compra Rápida NORMAL** (sin la marca) llama a `super()` ⇒ comportamiento INTACTO
  (`test_quick_purchase_grouping`, `test_quick_purchase_without_sale_order` verdes).
- La cantidad congelada vive en la línea (`product_qty`), que la resolución prellena con el
  faltante real.

**D4 — Botón "traer pedidos" (CERRADA).**
- Nombre: `action_pf_import_requiring_orders` (método del bridge `mrp.quick.purchase.wizard`).
- Vive en la vista HEREDADA de la Compra Rápida, junto a "Agrupar pedidos" (`order_line_ids`),
  visible solo con `product_id`.
- Filtro exacto (`printflow.flow.pending._pf_sale_orders_requiring_purchase(product)`):
  1. **Candidatos** = pedidos con **entrega pendiente del producto** (línea de venta `state='sale'`
     con `product_uom_qty − qty_delivered > 0`).
  2. `pos = printflow.purchase.link.mixin._find_purchase_orders_by_sale_names(nombres)` (vínculo por
     `origin`, fuente ÚNICA ya existente).
  3. **"Compra en trámite"** = OC con línea del producto que va a surtir: **sin confirmar**
     (`draft/sent/to approve`) **o** confirmada con **recepción pendiente** (OC `state='purchase'`
     con albarán `incoming` abierto).
  4. **EXCLUIR** los pedidos cuyo nombre aparece en el `origin` de una OC en trámite (ya tienen
     compra que va a llegar: solo hay que confirmarla/recibirla).
  5. **INCLUIR** los pedidos sin OC, con OC **cancelada** o con OC **ya recibida** (sin recepción
     abierta): su demanda no tiene entrada futura ⇒ **requieren compra**.
- El botón IMPORTA (crea filas en `order_line_ids`, idempotente: sin duplicar) y devuelve la acción
  que recarga el wizard. NO crea OC ni ejecuta nada ("abrir ≠ ejecutar").

**D5 — Cliente en el selector (CERRADA).**
- Nuevo `models/printflow_sale_order_display.py`: `_inherit = 'sale.order'` + override de
  `_compute_display_name()` con `super()`, gateado por contexto:
  `if self.env.context.get('pf_purchase_partner_label'): display_name = '%s − %s' % (name, partner_id.name)`.
- El contexto se activa SOLO en el campo del selector de "Agrupar pedidos"
  (`mrp.quick.purchase.wizard.order.sale_order_id`) por **herencia de vista**
  (`context="{'pf_purchase_partner_label': True}"`). Sin ese contexto, `sale.order.display_name`
  queda IGUAL en todo el sistema ⇒ cero efecto colateral.

**D6 — Paridad producto/pedido (CERRADA).**
- Producto: `shortfall_by_key = {'purchase': max(0, déficit − cobertura(producto))}`.
- Pedido: `shortfall_by_key = {'purchase': max(0, line.deficit_qty − cobertura(producto, sale_order=pedido_foco))}`
  (la cobertura se RESTRINGE al pedido enfocado).
- Forma IDÉNTICA del nodo en AMBOS ejes; el builder (agnóstico) NO cambia. Precedencia: solo se
  llena cuando `purchase == 'missing'` y el valor `> _EPS`.
- `test_flow_canvas_parity.py` sigue verde (compara el ARMADO pedido↔canvas, no los valores del
  badge).

**D7 — Caso fabricable/componentes (CERRADA · FUERA).**
- El badge de faltante aplica al **terminado** (producto del diagrama). El caso de **componentes**
  (`buy_components`) queda FUERA: su resolución conserva el **déficit físico** (`_pf_deficit_qty`)
  porque la cobertura de OC del terminado no es trasladable a los insumos. Se documenta como
  extensión futura. (El badge igual aplica en el eje `manufacture` si el nodo `purchase` está
  `missing`.)

**D8 — Impacto en tests/candados (CERRADA · decisiones DELIBERADAS).**
- **SIN claves nuevas** en el nodo ⇒ `tests/test_product_flow_payload_parity.py` (BASE_NODE_KEYS) NO
  cambia.
- `tests/test_flow_compras_deficit_magnitude.py` NO crea OC sin confirmar ⇒ `cobertura = 0` ⇒
  `shortfall == déficit` ⇒ sigue **verde sin tocar**.
- **SIN CAMBIOS** (siguen verdes): `test_flow_canvas_parity.py`, `test_diagnostic_timeline_payload.py`,
  `test_diagnostic_flow_geometry.py`, `test_diagnostic_levels.py`,
  `test_diagnostic_unified_solution.py`, `test_product_flow_canvas.py`,
  `test_product_flow_parity_panel.py`, `test_node_pending_enumeration.py` (rojo pre-existente B1,
  ajeno), `test_quick_purchase_grouping.py`, `test_quick_purchase_without_sale_order.py`.
- **CREAR** `tests/test_flow_compras_por_comprar.py` (CA-1..CA-6) y registrarlo en
  `tests/__init__.py`.
- **Único cambio deliberado de infraestructura:** el `__manifest__.py` gana la vista heredada
  `views/printflow_quick_purchase_views.xml` (botón "Traer pedidos" + contexto del selector).
  Justificado: la UX del botón no existe hoy.

### 3.6 Archivos (confirmados por el Planificador)

| Acción | Archivo | Qué se cambia |
|---|---|---|
| MODIFICAR | `models/printflow_flow_pending.py` | 3 helpers de lectura: `_pf_sale_orders_pending_delivery`, `_pf_purchase_unconfirmed_cover`, `_pf_sale_orders_requiring_purchase` (T1–T3). |
| MODIFICAR | `models/printflow_flow_strategy_product.py` | `shortfall_by_key` = faltante real (T4). |
| MODIFICAR | `models/printflow_flow_strategy_order.py` | Paridad del faltante real (T5). |
| CREAR | `models/printflow_quick_purchase_bridge.py` | `_inherit` de `mrp.quick.purchase.wizard`: `pf_freeze_qty` + `_demand_for_product` congelado (T6) + `action_pf_import_requiring_orders` (T7). |
| CREAR | `models/printflow_sale_order_display.py` | `_inherit` de `sale.order`: `_compute_display_name` por contexto (T8). |
| MODIFICAR | `models/__init__.py` | Importar los 2 archivos nuevos (T6/T8). |
| MODIFICAR | `wizard/printflow_product_flow.py` | `_pf_purchase_shortfall_qty` + `_pf_open_buy_product` + `_pf_open_quick_purchase` (freeze + `product_id`) (T10). |
| MODIFICAR | `wizard/printflow_order_diagnostic_failure.py` | Ídem paridad del pedido (T11). |
| CREAR | `views/printflow_quick_purchase_views.xml` | Botón "Traer pedidos" + contexto del selector (T9). |
| MODIFICAR | `__manifest__.py` | Añadir la vista heredada a `data` (deliberado, D8) (T9). |
| CREAR | `tests/test_flow_compras_por_comprar.py` | Fijan CA-1..CA-6; registrar en `tests/__init__.py` (T12). |

**SIN CAMBIOS (a propósito):** motor externo `x_product_dimensional_pricing` (solo LECTURA; se
**extiende** `sale.order` y `mrp.quick.purchase.wizard` desde `printflow`);
`printflow_flow_payload_builder.py` (sin claves nuevas);
`static/src/js|xml/printflow_order_timeline.*` (el badge ya existe); los candados de test
existentes (D8).

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): SOLO LECTURA. `_inherit` + `super()`;
  PROHIBIDO `cr.execute` de escritura o `cr.commit()`.
- **NO tocar el motor** `x_product_dimensional_pricing` (se extiende desde `printflow`).
- **NO romper la paridad del pedido** (`test_flow_canvas_parity.py`, `test_diagnostic_*` verdes).
- **Payload/contrato del widget:** cambios ADITIVOS.
- **`models/` nunca importa `wizard/`.** **Sin N+1** (una lectura por modelo, en lote).
- La **compra rápida NORMAL** (operador eligiendo a mano) debe seguir verde
  (`x_product_dimensional_pricing`: `test_quick_purchase_grouping`, `test_quick_purchase_without_sale_order`).

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | Con OC en borrador de pedidos que esperan entrega, el nodo Compras muestra el faltante **descontándolas** (hoy 26, no 31). | Test del payload `_pf_build_payload(wizard,'product')`: `purchase.shortfall_qty == demanda − existencia − en camino − pedido_sin_confirmar`. |
| CA-2 | El nodo explicita que hay **OC sin confirmar** (documentos vinculados) junto a la magnitud. | Test del payload/etiqueta. |
| CA-3 | La resolución abre la Compra Rápida con cantidad = faltante real y **NO** se recalcula al importar pedidos. | Test: wizard con pedidos agrupados → la línea conserva la cantidad del faltante (no la suma de pedidos). |
| CA-4 | El botón importa SOLO los pedidos que requieren compra (entrega pendiente y sin compra en trámite); excluye los de OC en borrador. | Test con OC borrador / cancelada / recibida. |
| CA-5 | El selector de "Agrupar pedidos" permite leer el cliente (número − cliente). | Test de vista/`display_name` en contexto. |
| CA-6 | Paridad del pedido + compra rápida normal intactas; **solo lectura**. | `test_flow_canvas_parity.py` + `test_diagnostic_*` + `test_quick_purchase_*` verdes; `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`. |

### 3.9 Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Cambiar el faltante rompe candados que congelan 31 (Inventario/Compras/pedido) | Alto | D1/D8: actualizar candados de forma DELIBERADA y documentada; acotar el cambio. |
| El wizard recalcula la cantidad y "pisa" el faltante | Alto | D3: marca de contexto + `super()`; la compra normal queda intacta. |
| Romper la paridad del pedido | Alto | D6: mismo criterio en ambos ejes; tests candado. |
| Duplicar lecturas (N+1) al traer pedidos + OC | Medio | Reutilizar las lecturas batch del motor de pendientes. |
| Tocar datos al "importar pedidos" | Crítico | Escribir solo en el **transient** del wizard (efímero); `TransactionCase`. |

### 3.10 Observaciones (fuera de alcance)
- **O-1**: la OC P00290 (S03215, 1 u) es de un pedido **colgado** (entrega cancelada, 0 entregado):
  no cubre demanda pendiente. Se reporta como hallazgo (H-005), no se toca.
- **O-2**: el tablero marca S03215 como "delivered" pero sus documentos dicen otra cosa. Desfase
  reportado como hallazgo (H-006).
- **O-3**: el desglose "N unidades de OC sin confirmar" vs "N documentos" queda a criterio del Planificador.
- **O-4**: los listados de OC del diagrama de PEDIDO (`board._find_purchase_orders_by_sale_names`,
  `_pf_collect_causante_vals`) NO se alinean (son las compras del propio pedido).
- **O-5**: el caso de **componentes** (producto fabricable, pedidos derivados de OF) → D7.

### 3.11 Plan de ejecución atómico y secuencial (T1–T12)

> **Ejecución por LOTES de máximo 3 tareas; cada lote = una sesión NUEVA de `odoo-dev`.**
> Convenciones OCA (`odoo-17-clean-architecture` §2.5): un archivo por modelo, métodos `_pf_*`,
> `snake_case`, imports por bloques, nodo `<odoo>`. **SOLO LECTURA** de BD (search/read).

#### Lote 1 (T1–T3) — Motor de pendientes (`models/printflow_flow_pending.py`)

- [x] **T1 — Helper "pedidos con entrega pendiente del producto".**
  - Archivo: `models/printflow_flow_pending.py`.
  - `@api.model def _pf_sale_orders_pending_delivery(self, product_ids)` → `{pid: set(names)}`:
    UNA `search_read` de `sale.order.line` (`order_id.state='sale'`, `product_id in ids`, campos
    `['product_id','order_id','product_uom_qty','qty_delivered']`) + UNA lectura batch de
    `sale.order` (`['name']`) para traducir ids→nombres; pendiente =
    `product_uom_qty − qty_delivered > _EPS`. Sin N+1. Solo lectura.
- [x] **T2 — Helper "cobertura de OC sin confirmar".**
  - Archivo: `models/printflow_flow_pending.py`.
  - `@api.model def _pf_purchase_unconfirmed_cover(self, product_ids, sale_order=None)` → `{pid: float}`:
    lee las líneas de OC del producto (`purchase.order.line`, `order_id.state in
    PURCHASE_UNCONFIRMED_STATES`, campos `['product_id','order_id','product_qty']`) + el `origin` de
    sus OC (lectura batch); suma `product_qty` cuando el `origin` referencia un nombre de pedido con
    entrega pendiente de T1 (o `sale_order.name` si se pasa). Reutiliza
    `Remedy._pf_origin_sale_names` para tokenizar el `origin`. Sin N+1.
- [x] **T3 — Helper "pedidos que requieren compra" (filtro D4).**
  - Archivo: `models/printflow_flow_pending.py`.
  - `@api.model def _pf_sale_orders_requiring_purchase(self, product)` → `sale.order`:
    candidatos de T1 ∧ NO bloqueados por una OC "en trámite". "En trámite" = OC con línea del
    producto con `state in PURCHASE_UNCONFIRMED_STATES` **o** `state='purchase'` con albarán
    `incoming` abierto (lectura batch de `stock.picking`). Vínculo por `origin` con
    `self.env['printflow.purchase.link.mixin']._find_purchase_orders_by_sale_names(names)`.

#### Lote 2 (T4–T6) — Estrategias + bridge (congelado)

- [x] **T4 — Estrategia PRODUCTO: shortfall real.**
  - Archivo: `models/printflow_flow_strategy_product.py`, `_pf_flow_context`.
  - `cover = env['printflow.flow.pending']._pf_purchase_unconfirmed_cover([product.id]).get(product.id, 0.0)`;
    `shortfall = max(0.0, deficit − cover)`; `shortfall_by_key = {'purchase': shortfall}` si
    `statuses['purchase'] == 'missing'` y `shortfall > _EPS` (si no, `{}`). El `deficit` crudo se
    conserva intacto.
- [x] **T5 — Estrategia PEDIDO: shortfall real (paridad).**
  - Archivo: `models/printflow_flow_strategy_order.py`, `_pf_flow_context`.
  - `cover = env['printflow.flow.pending']._pf_purchase_unconfirmed_cover(
    [line.product_id.id], sale_order=line.order_id)`; `shortfall = max(0.0, deficit − cover)`;
    `shortfall_by_key = {'purchase': shortfall}` con la misma precedencia de T4.
- [x] **T6 — Bridge: campo `pf_freeze_qty` + `_demand_for_product` congelado.**
  - Archivo: CREAR `models/printflow_quick_purchase_bridge.py`; registrar en `models/__init__.py`.
  - `_inherit = 'mrp.quick.purchase.wizard'`; `pf_freeze_qty = fields.Boolean(
    string='Cantidad congelada (faltante real)')` (orden OCA: atributos → campos → métodos);
    override `def _demand_for_product(self, product)` con `super()` + early-return `0.0` si
    `self.pf_freeze_qty`. **NO** se toca ningún otro método del wizard base.

#### Lote 3 (T7–T9) — Bridge (import) + selector + vista

- [x] **T7 — Bridge: botón `action_pf_import_requiring_orders`.**
  - Archivo: `models/printflow_quick_purchase_bridge.py` (mismo bridge de T6).
  - `def action_pf_import_requiring_orders(self)`: resuelve el producto de referencia
    (`self.purchase_line_ids[:1].product_id or self.product_id`); obtiene los pedidos de
    `printflow.flow.pending._pf_sale_orders_requiring_purchase(product)`; crea las filas
    `order_line_ids` que falten (idempotente, sin duplicar) y devuelve la acción que RECARGA el
    wizard (`act_window` `res_id=self.id`, `target='new'`). Solo escribe en el **transient** del
    wizard.
- [x] **T8 — Selector: "número − cliente" (`sale.order`).**
  - Archivo: CREAR `models/printflow_sale_order_display.py`; registrar en `models/__init__.py`.
  - `_inherit = 'sale.order'`; `@api.depends('name', 'partner_id') def _compute_display_name(self)`
    con `super()` + `if self.env.context.get('pf_purchase_partner_label'): rec.display_name =
    '%s − %s' % (rec.name, rec.partner_id.name)`. Sin el contexto, intacto.
- [x] **T9 — Vista heredada del wizard + `__manifest__.py`.**
  - Archivos: CREAR `views/printflow_quick_purchase_views.xml`; MODIFICAR `__manifest__.py` (añadir
    la vista a `data`, tras `wizard/printflow_product_flow_views.xml`).
  - `<record id="mrp_quick_purchase_wizard_form_pf" model="ir.ui.view">` con `inherit_id =
    x_product_dimensional_pricing.mrp_quick_purchase_wizard_form`; `xpath
    //field[@name='order_line_ids']` `position="before"` → botón
    `name="action_pf_import_requiring_orders" type="object" string="Traer pedidos que requieren
    compra"` con `invisible="not product_id"`; y, en el `sale_order_id` del tree,
    `position="attributes"` → `context="{'pf_purchase_partner_label': True}"`. Sin `position="replace"`.

#### Lote 4 (T10–T12) — Wizards (cantidad) + tests

- [x] **T10 — Wizard PRODUCTO: cantidad = faltante real + congelada.**
  - Archivo: `wizard/printflow_product_flow.py`.
  - Nuevo `def _pf_purchase_shortfall_qty(self)`: `max(0.0, déficit − cover) or 1.0` con
    `cover = env['printflow.flow.pending']._pf_purchase_unconfirmed_cover([product.id])`.
    `_pf_open_buy_product` usa `_pf_purchase_shortfall_qty()` (NO `_pf_deficit_qty`, que se conserva
    para OF/componentes — D7). `_pf_open_quick_purchase` añade `product_id` (referencia) y
    `pf_freeze_qty: True` al `create()` del wizard.
- [x] **T11 — Wizard PEDIDO: paridad de la cantidad.**
  - Archivo: `wizard/printflow_order_diagnostic_failure.py`.
  - Nuevo `def _pf_purchase_shortfall_qty(self)`: `max(0.0, line.deficit_qty − cover) or 1.0` con
    `cover = env['printflow.flow.pending']._pf_purchase_unconfirmed_cover(
    [line.product_id.id], sale_order=board.sale_order_id)`. `_pf_open_buy_product` lo usa.
    `_pf_open_quick_purchase` añade `product_id` + `pf_freeze_qty: True`.
- [x] **T12 — Tests (CA-1..CA-6).**
  - **CREAR** `tests/test_flow_compras_por_comprar.py` y registrar en `tests/__init__.py`.
    - **CA-1**: producto comprable con OC `draft` ligada a un pedido con entrega pendiente →
      `_pf_build_payload(wizard,'product')`: `purchase['shortfall_qty'] == déficit − oc_qty`.
    - **CA-2**: el nodo trae el badge `pending` (`== nº de OC sin confirmar`) con
      `pending_label == 'OC sin confirmar'` junto a la magnitud.
    - **CA-3**: `action_run_pf_plan('order_supply_missing','solution')` (producto) abre
      `mrp.quick.purchase.wizard` con `pf_freeze_qty=True` y la línea con el faltante real; tras
      `action_pf_import_requiring_orders()`, la línea **conserva** la cantidad.
    - **CA-4**: `action_pf_import_requiring_orders()` importa SOLO los pedidos que requieren compra:
      EXCLUYE el de OC `draft`; INCLUYE el de OC **cancelada** y el de OC **ya recibida**.
    - **CA-5**: con contexto `pf_purchase_partner_label`, `sale.order.display_name` ==
      `'SXXX − Cliente'`; SIN contexto, == nombre.
    - **CA-6**: paridad → `focus_timeline_json` del pedido también lleva `shortfall_qty`; compra
      normal intacta; `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`.
  - **NO se modifican** los candados existentes (D8).

**Verificación (turno del Verificador, fuera del dev).** `--test-tags /printflow_gestion_inventario`
(o subconjunto: `test_flow_compras_por_comprar`, `test_flow_compras_deficit_magnitude`,
`test_product_flow_payload_parity`, `test_flow_canvas_parity`, `test_diagnostic_timeline_payload`,
`test_diagnostic_levels`, `test_diagnostic_unified_solution`, `test_diagnostic_flow_geometry`,
`test_product_flow_canvas`, `test_product_flow_parity_panel`, `test_quick_purchase_grouping`,
`test_quick_purchase_without_sale_order`). Al hilo solo vuelve el exit code, N/N y, si falla, la
aserción + cola del traceback.

### 3.12 Contratos que NO deben romperse

- CA-1..CA-6 de 3.8.
- Firma/forma de `printflow.flow.canvas._pf_build_payload(host, mode)` y del builder (SIN claves
  nuevas por nodo; se reutilizan `shortfall_qty`/`shortfall_label` y `pending`/`pending_label`).
- `status_label`/`summary`/`tone` de los nodos: valores INTACTOS.
- `deficit_qty`/`purchase_status` del veredicto; motor externo `x_product_dimensional_pricing`
  (solo LECTURA); reglas de `printflow.stock.remedy`.
- `_pf_open_buy_product`/`_pf_open_quick_purchase` (Compra Rápida, `material_received=False`, sin
  forzar recepción) y la **Compra Rápida NORMAL** (sin `pf_freeze_qty`).
- `mrp.quick.purchase.wizard` / `.line` / `.order`: solo se AÑADE el campo `pf_freeze_qty` y los
  overrides `_demand_for_product`/`action_pf_import_requiring_orders`; `default_get`,
  `action_confirm`, `_create_purchase_order` y el dominio del selector quedan intactos.
- El motor EXTENDIDO `x_product_dimensional_pricing` NO se modifica (se hereda `sale.order` y
  `mrp.quick.purchase.wizard` desde `printflow`).
- `models/` nunca importa `wizard/`.

---

## 3.C (ANEXO · TAREA CERRADA) — Magnitud del déficit en el nodo COMPRAS (y resolución a Compra Rápida)

> **Turno:** Odoo Analista (cierre). **Estado:** CERRADA (Verificador `cumple`: exit 0, **90/90 verdes**; CA-1..CA-5 cubiertos).
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA` · **Ruta:** `C:\odoo_custom\printflow_gestion_inventario`
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Clasificación **GRANDE**
> (toca el flujo de Compras): cadena completa Analista → Planificador → Analista → Dev →
> Verificador → Analista.

### 3.1 Problema (evidencia en el diagrama y en la BD)
El **nodo Compras** no comunica la **magnitud** de lo que falta comprar ni guía a
comprarlo. El error NACE en Compras y se propaga a Inventario y Entrega —que **sí**
muestran su magnitud— pero Compras, siendo la RAÍZ, no lo hace.

Evidencia (diagrama del producto `IMPRESION BANNER ` id 13571; `purchase_ok=True`;
**sin BOM** ⇒ NO fabricable; nodo de quiebre = **Compras**; semáforo Crítico):
- **Compras** → estado "**Falta comprar**" (SIN cantidad) + badge "**4 OC sin confirmar**"
  (cuenta DOCUMENTOS ya creados, no lo que falta por comprar).
- **Inventario** → "Sin stock: **31.00**" (SÍ muestra la magnitud).
- **Entrega** → "**29** por entregar" (SÍ muestra la magnitud).
- Déficit real = 35 (demanda de ventas, `outgoing_qty`) − 4 (existencia) − 0 (en camino)
  = **31 u**.
- La resolución/oferta actual abre/listan **compras ya hechas**, no guía a comprar lo que
  falta: `wizard/printflow_product_flow.py::_pf_open_purchase_orders` (L520-538) filtra
  OC en `draft/sent/to approve/purchase` (incluye confirmadas) y
  `models/printflow_flow_strategy_product.py::_pf_root_tray` (L712-725) lista OC
  incluyendo confirmadas (es el pendiente **B2** del backlog). Además, el plan de pedido
  `order_supply_missing` (playbook L697-713) propone "Ver la compra del pedido"
  (`target='purchase_order'`) en vez de "comprar el faltante".

### 3.2 Objetivo (acotado)
**SÍ:**
1. El nodo **Compras** debe mostrar EXPLÍCITAMENTE la magnitud de lo que falta por
   comprar (p. ej. "Faltan comprar 31"), no solo "Falta comprar".
2. La acción de resolución del nodo Compras debe **guiar a comprar lo que falta**:
   **producto + cantidad del déficit**.
3. **General (arquitectura):** debe funcionar para CUALQUIER producto/causa (no solo este
   caso) y en **AMBOS** diagramas (producto y pedido) sin romper la paridad.

**NO:**
- NO tocar el motor externo `x_product_dimensional_pricing` (solo LECTURA / reutilizar).
- NO reimplementar el cálculo del déficit: se REUTILIZA (`deficit_qty` del veredicto y
  `_pf_deficit_qty` del wizard).
- NO crear OC/albaranes por sí solo: la acción NAVEGA/prellena; el operador confirma
  ("abrir ≠ ejecutar", decisión ya vigente del módulo).
- NO escribir ningún dato (tarea de SOLO LECTURA).

### 3.3 Contrato funcional (objetivo por nodo)
| Nodo | Debe mostrar | Resolución ("Solucionar") |
|---|---|---|
| **Compras** | Magnitud del faltante: "Faltan comprar **N**" cuando déficit>0 (la señal de documentos "N OC sin confirmar" puede conservarse como señal SECUNDARIA). | **Guiar a comprar lo que falta** = producto + cantidad (= déficit). La lista de OC ya hechas NO debe ser la acción principal. |
| Inventario | sin cambios ("Sin stock: N"). | sin cambios. |
| Entrega | sin cambios ("N por entregar"). | sin cambios. |

### 3.4 Fuente ÚNICA a reutilizar (cero reinvención)
- **Déficit:** `deficit_qty` del veredicto (`printflow.product.flow.diagnostic.
  _pf_flow_verdict`) y `wizard/printflow_product_flow.py::_pf_deficit_qty` (L444-455).
- **Compra prellenada (YA EXISTE):** `_pf_open_buy_product` → `_pf_open_buy_components` →
  `_pf_open_quick_purchase` (abren "Compra Rápida" con la cantidad = déficit, sin forzar
  recepción). Reutilizar, no reinventar.
- **Etiquetas:** `printflow.flow.presentation._PF_NODE_STATUS_LABELS` /
  `_PF_NODE_PENDING_LABELS` (el nodo `purchase` hoy pinta `missing`="Falta comprar").
- **Playbook:** `printflow.resolution.playbook` — planes `buy_product`
  (`_pf_plan_buy_product`, L426-442) y `order_supply_missing` (L697-713).
- **Iconografía de remedio físico:** `PF_PHYSICAL_REMEDY_TO_CAUSE` /
  `_pf_physical_remedy_key` (motor, solo LECTURA).

### 3.5 Decisiones de diseño que cierra el PLANIFICADOR (D1..D5)
- **D1 — Dónde se pinta la magnitud.** ¿En el `statusLabel` del nodo (p. ej. "Falta
  comprar 31"), en el `summary` del nodo, o en un `pending_label`/badge nuevo? Cuidar la
  compatibilidad del payload del widget (cambios ADITIVOS). Mismo criterio en producto y
  pedido.
- **D2 — Qué acción es la RESOLUCIÓN del nodo Compras.** Confirmar el wiring ACTUAL del
  "Solucionar"/acciones del nodo Compras (qué plan/acción resuelve hoy: ¿`buy_product`
  quick-purchase o `purchase_order` lista?) y definirlo para que apunte a **comprar lo que
  falta** (producto + cantidad), despriorizando/rotulando los listados de OC ya hechas.
- **D3 — Relación con el backlog B2.** `_pf_open_purchase_orders` y `_pf_root_tray` listan
  OC incluyendo confirmadas. Decidir si se alinean (solo pendientes) en ESTA tarea o se
  dejan; documentar. (El dueño pidió explícitamente que la resolución NO muestre las
  compras hechas.)
- **D4 — Generalidad y paridad.** Cómo se generaliza a cualquier causa/producto (insumos/
  fabricación) sin hardcodear, y cómo queda en el diagrama de PEDIDO sin romper paridad.
- **D5 — Impacto en tests/candados.** `test_product_flow_payload_parity.py` (set de claves
  del nodo), `test_flow_canvas_parity.py`, `test_diagnostic_timeline_payload.py`,
  `test_diagnostic_levels.py` (buy_product). Decidir actualizaciones DELIBERADAS y
  documentarlas.

### 3.6 Archivos candidatos (el Planificador confirma/ajusta)
| Acción | Archivo | Qué se cambia |
|---|---|---|
| MODIFICAR | `models/printflow_flow_strategy_product.py` | Etiqueta/`summary` del nodo Compras con la magnitud; acción de compra del nodo. |
| MODIFICAR | `models/printflow_flow_strategy_order.py` | Paridad en el pedido. |
| MODIFICAR | `models/printflow_flow_presentation.py` | Etiqueta explícita de "falta comprar N". |
| MODIFICAR | `models/printflow_resolution_playbook.py` | Plan `buy_product`/`order_supply_missing`: resolución = comprar lo que falta (no listar OC hechas). |
| MODIFICAR | `wizard/printflow_product_flow.py` | Acción de compra / quick-purchase; alinear listados de OC si D3 lo cierra. |
| MODIFICAR | `models/printflow_flow_payload_builder.py` | Solo si hace falta exponer la magnitud (aditivo). |
| MODIFICAR | `static/src/xml/printflow_order_timeline.xml` (+ `.js` si aplica) | Solo si el badge necesita la magnitud. |
| CREAR/MODIFICAR | `tests/*` | Fijan CA-1..CA-5; registrar en `tests/__init__.py`. |

**SIN CAMBIOS (a propósito):** motor externo `x_product_dimensional_pricing` (solo lectura);
reglas de déficit del veredicto; `__manifest__.py` (salvo assets, improbable).

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): SOLO LECTURA.
- **No forzar/reinventar flujos nativos**: `_inherit` + `super()`; PROHIBIDO `cr.execute`
  de escritura o `cr.commit()`.
- **NO tocar el motor** `x_product_dimensional_pricing`.
- **NO romper la paridad del pedido**: `test_flow_canvas_parity.py` y `test_diagnostic_*`
  verdes.
- **Payload/contrato del widget:** cambios ADITIVOS.
- **`models/` nunca importa `wizard/`.** **Sin N+1**: una sola lectura por modelo (lote).

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | Con déficit>0 y producto comprable, el nodo Compras muestra la magnitud (p. ej. "Falta comprar 31"). | Test del payload `_pf_build_payload(wizard,'product')`: el nodo `purchase` refleja la cantidad del déficit. |
| CA-2 | La resolución del nodo Compras guía a comprar lo que falta (producto + cantidad = déficit), NO a las compras ya hechas. | Test: el plan/acción resuelve al quick-purchase con cantidad = déficit. |
| CA-3 | Generaliza (p. ej. producto fabricable con déficit de insumos) sin hardcodear. | Test con BOM + déficit de componentes. |
| CA-4 | Paridad del pedido intacta. | `test_flow_canvas_parity.py` + `test_diagnostic_*` verdes. |
| CA-5 | Solo lectura. | `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`. |

### 3.9 Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Cambiar el status/label del nodo rompe candados del payload | Alto | D1/D5: cambios ADITIVOS; actualizar candados de forma deliberada. |
| Romper la paridad del pedido | Alto | D4: mismo criterio en ambos; tests candado. |
| Duplicar el déficit (reinventar la regla) | Medio | Reutilizar `deficit_qty`/`_pf_deficit_qty`. |
| Tocar datos al "resolver" | Crítico | Solo LECTURA; `abrir ≠ ejecutar`; TransactionCase. |

### 3.10 Decisiones de diseño cerradas (D1–D5)

> Cierre del **Odoo Planificador**. Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` ·
> Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no**
> (SOLO LECTURA). El diseño se **engancha** a lo existente: reutiliza el déficit y la Compra Rápida
> ya probada y NO toca el motor externo `x_product_dimensional_pricing`. Los cambios al payload del
> widget son **ADITIVOS**.

**D1 — Dónde se pinta la magnitud (CERRADA).** Con un **BADGE ADITIVO** nuevo por nodo, NO en el
`statusLabel` ni en el `summary`. **Por qué:** cuando el nodo Compras está roto, el widget muestra el
`summary` ("Falta comprar") y NO el `statusLabel`; por eso una cifra dentro del `statusLabel` no se
vería en la tarjeta. Se añaden DOS claves ADITIVAS al nodo (mismo patrón que `pending`/`pending_label`):
`shortfall_qty` (Float) y `shortfall_label` (Char, p. ej. "Faltan comprar"). El widget pinta el badge
"**Faltan comprar N**" cuando `shortfall_qty > 0`. El `status_label`/`summary`/`tone` y los registros
del motor **NO se tocan** (cero riesgo a los candados de valores). El badge de pendientes ("N OC sin
confirmar") se conserva como señal **SECUNDARIA**.

**D2 — Qué resuelve el nodo Compras (CERRADA).** La resolución = **comprar lo que falta** (producto +
cantidad = déficit), reutilizando la **Compra Rápida** existente (`_pf_open_buy_product` →
`_pf_open_quick_purchase`, qty = déficit, `material_received=False`, sin forzar recepción). Wiring
confirmado y cambio:
- **Producto:** la fila del panel "Solucionar" usa el plan del playbook de la causa `order_supply_missing`,
  cuya `solution` hoy es `('navigate','purchase_order')` → abre la LISTA de OC (`_pf_open_purchase_orders`).
  Se cambia a `('open_wizard','buy_product')` → abre la Compra Rápida. Los botones del nodo (`buy_product`,
  `buy_components`) ya existen y se conservan.
- **Pedido:** el botón unificado "Solucionar" ya abre la Compra Rápida por el **remedio**
  (`pf_remedy_target='buy_product'`). Al alinear el plan, el remedio queda REDUNDANTE y la regla
  anti-duplicación lo apaga (`pf_remedy_available=False`); el botón sigue abriendo la **Compra Rápida**,
  ahora por la vía de la `solution`. Comportamiento neto idéntico y coherente.

**D3 — Listados de OC ya hechas (CERRADA · cierra el backlog B2).** El dueño pidió que la resolución NO
muestre las compras ya hechas. Se alinean en ESTA tarea **solo los listados del diagrama de PRODUCTO**:
- `wizard/printflow_product_flow.py::_pf_open_purchase_orders` (acción `view_purchase`/"Ver la compra")
  → dominio a **solo OC sin confirmar**.
- `models/printflow_flow_strategy_product.py::_pf_root_tray` (tray "Recopilar" del nodo raíz) → ídem.
Los estados "sin confirmar" salen de la FUENTE ÚNICA (`printflow.flow.pending`): NO se duplica la tupla.
**Fuera de alcance (O-3):** los listados equivalentes del diagrama de PEDIDO usan otra mecánica
(`board._find_purchase_orders_by_sale_names`, `_pf_collect_causante_vals`): son las compras DEL PROPIO
pedido y su "Solucionar" ya guía a comprar; no se tocan.

**D4 — Generalidad y paridad (CERRADA).** La magnitud se deriva del **déficit** ya calculado, NUNCA de un
producto/caso concreto: cada estrategia llena un mapa normalizado `ctx['shortfall_by_key'] = {'purchase':
déficit}` cuando el nodo `purchase` está `missing` (déficit > 0). Producto: el `deficit` del contexto
(mismo número del veredicto y de `_pf_open_buy_product`). Pedido: `line.deficit_qty` (el MISMO campo que
usa el motor de fallas). El builder (agnóstico) emite el badge igual en AMBOS diagramas (el nodo
`purchase` existe en los dos ejes). La resolución es el **plan compartido** del playbook → coherente.
Nada hardcodeado. Se usa el déficit **real** (no `_pf_deficit_qty`, que tiene suelo a `1.0`): sin
déficit, sin badge.

**D5 — Impacto en tests/candados (CERRADA · decisiones DELIBERADAS).**
- **MODIFICAR** `tests/test_product_flow_payload_parity.py`: añadir `'shortfall_qty'` y
  `'shortfall_label'` a `BASE_NODE_KEYS` (claves ADITIVAS del nodo). El esqueleto congelado
  (`FROZEN_SKELETON_*`) **NO cambia** (la magnitud no está en `_SKELETON_FIELDS`).
- **MODIFICAR** `tests/test_diagnostic_levels.py::test_failures_per_broken_node` (L158-164):
  `pf_solution_target` pasa de `'purchase_order'` a `'buy_product'`; `pf_remedy_available` pasa de
  `True` a `False` (remedio redundante); `pf_remedy_target` sigue `'buy_product'`;
  `action_open_solution()` sigue abriendo `mrp.quick.purchase.wizard`.
- **MODIFICAR** `tests/test_diagnostic_unified_solution.py::test_supply_missing_opens_quick_purchase_via_remedy`
  (L110-115): misma actualización. El test "redundante" (L128-145, causa `buy_product` del nodo stock)
  queda **intacto**.
- **SIN CAMBIOS (siguen verdes):** `test_diagnostic_timeline_payload.py`
  (`test_payload_nodes_carry_short_summary`: el `summary` no se toca; el badge es una clave aditiva que
  ese test no inspecciona), `test_flow_canvas_parity.py`, `test_diagnostic_node_actions.py`,
  `test_product_flow_canvas.py`, `test_diagnostic_flow_geometry.py`, `test_product_flow_parity_panel.py`,
  `test_flow_compras_recepcion_snapshot.py`, `test_node_pending_enumeration.py`.
- **CREAR** `tests/test_flow_compras_deficit_magnitude.py` (CA-1..CA-5) y registrar en `tests/__init__.py`.

### 3.11 Plan de ejecución atómico y secuencial (T1–T10)

> Ejecutar EN ORDEN. T1–T5 = presentación/estrategias/motor (`models/`); T6 = playbook; T7 = wizard;
> T8 = estrategia del producto; T9 = widget; T10 = tests. Convenciones OCA
> (`odoo-17-clean-architecture` 2.5): métodos `_pf_*`, `snake_case`, un archivo por modelo. **SOLO
> LECTURA** de BD (search/read).

- [x] **T1 — Presentación: etiqueta del faltante por nodo.**
  - Archivo: `models/printflow_flow_presentation.py`.
  - `_PF_NODE_SHORTFALL_LABELS = {'purchase': _('Faltan comprar')}` +
    `_PF_NODE_SHORTFALL_LABEL_DEFAULT = ''` + `@api.model def _pf_node_shortfall_label(self, key)`
    (mismo patrón que `_pf_node_pending_label`). Presentación pura (sin BD).

- [x] **T2 — Builder: exponer `shortfall_qty` + `shortfall_label` (ADITIVO).**
  - Archivo: `models/printflow_flow_payload_builder.py`, dict `node` (junto a `pending_label`).
  - `'shortfall_qty': float((ctx.get('shortfall_by_key') or {}).get(key) or 0.0) if focus else 0.0`
    y `'shortfall_label': presentation._pf_node_shortfall_label(key)`.
  - NO tocar ninguna otra clave (`pending`, `status_label`, `summary`, `tone`).

- [x] **T3 — Estrategia PRODUCTO: llenar `shortfall_by_key` con el déficit.**
  - Archivo: `models/printflow_flow_strategy_product.py`, `_pf_flow_context`.
  - `shortfall_by_key = ({'purchase': deficit} if (statuses.get('purchase') == 'missing' and deficit > _EPS) else {})`;
    añadirlo al `base` (y `{}` en el early-return sin producto). Reutiliza el `deficit` YA calculado.

- [x] **T4 — Estrategia PEDIDO: llenar `shortfall_by_key` con el déficit de la línea.**
  - Archivo: `models/printflow_flow_strategy_order.py`, `_pf_flow_context`.
  - `deficit = (line.deficit_qty if line else 0.0) or 0.0`;
    `'shortfall_by_key': ({'purchase': deficit} if (line and statuses.get('purchase') == 'missing' and deficit > _EPS) else {})`;
    ya con `statuses` resuelto.

- [x] **T5 — Motor de pendientes: fuente única de "OC sin confirmar".**
  - Archivo: `models/printflow_flow_pending.py`.
  - `@api.model def _pf_purchase_unconfirmed_states(self): return PURCHASE_UNCONFIRMED_STATES`
    (reexporta la tupla YA existente; sin duplicarla).

- [x] **T6 — Playbook: la resolución de `order_supply_missing` guía a COMPRAR.**
  - Archivo: `models/printflow_resolution_playbook.py`, `_pf_plan_order_supply_missing`.
  - `solution`: de `self._pf_action(_('Ver la compra del pedido'), 'navigate', 'purchase_order')` a
    `self._pf_action(_('Comprar lo que falta'), 'open_wizard', 'buy_product')`. `summary`/`steps` se
    conservan. NO tocar `_pf_plan_order_shortfall` (causa distinta).

- [x] **T7 — Wizard PRODUCTO: listado de OC ya hechas → solo sin confirmar (D3).**
  - Archivo: `wizard/printflow_product_flow.py`, `_pf_open_purchase_orders`.
  - Dominio: `('order_id.state', 'in', self.env['printflow.flow.pending']._pf_purchase_unconfirmed_states())`
    (sustituye la tupla con `'purchase'`). Título: "N OC sin confirmar del producto".

- [x] **T8 — Estrategia PRODUCTO: tray raíz + etiqueta (D3).**
  - Archivo: `models/printflow_flow_strategy_product.py`.
  - `_pf_root_tray`: mismo dominio → solo `_pf_purchase_unconfirmed_states()`.
  - `_pf_node_actions` (nodo `purchase`): etiqueta de `view_purchase` → `_('Ver OC sin confirmar')`
    (acción SECUNDARIA; `buy_product` sigue disponible).
  - Paridad (opcional): `printflow_flow_strategy_order.py::_pf_node_actions`, etiqueta de `view_purchase`
    → `_('Ver OC sin confirmar')`.

- [x] **T9 — Widget: pintar el badge de faltante.**
  - `static/src/js/printflow_order_timeline.js` (`get nodes()`): `shortfallQty: node.shortfall_qty || 0`
    y `shortfallLabel: node.shortfall_label || ""`.
  - `static/src/xml/printflow_order_timeline.xml`: badge nuevo (espejo del de pendientes), SIN
    `t-on-click` y con expresión JS (`shape.shortfallQty > 0`): "Faltan comprar N". Assets ya
    declarados: **NO** se toca el `__manifest__.py`.

- [x] **T10 — Tests (fijan CA-1..CA-5; candados).**
  - **CREAR** `tests/test_flow_compras_deficit_magnitude.py` (registrar en `tests/__init__.py`):
    - CA-1: producto comprable con déficit → en `_pf_build_payload(wizard,'product')` el nodo `purchase`
      tiene `shortfall_qty == déficit` (>0) y `shortfall_label` no vacío.
    - CA-2: `action_run_pf_plan('order_supply_missing','solution')` (producto) y
      `failure.action_open_solution()` (pedido) abren `mrp.quick.purchase.wizard`; sin crear OC
      (`abrir ≠ ejecutar`).
    - CA-3: producto fabricable (BOM + componente) TAMBIÉN comprable con déficit → el mecanismo aplica
      en el eje `manufacture` (nodo `purchase` con magnitud) sin hardcode.
    - CA-4: paridad → `focus_timeline_json` del pedido también lleva `shortfall_qty` en `purchase`.
    - CA-5: `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; motor externo intacto.
  - **MODIFICAR** (D5): `tests/test_product_flow_payload_parity.py`, `tests/test_diagnostic_levels.py`,
    `tests/test_diagnostic_unified_solution.py`.

**Verificación (turno del Verificador, fuera del dev).** `--test-tags /printflow_gestion_inventario` (o
subconjunto: `test_flow_compras_deficit_magnitude`, `test_product_flow_payload_parity`,
`test_flow_canvas_parity`, `test_diagnostic_timeline_payload`, `test_diagnostic_levels`,
`test_diagnostic_unified_solution`, `test_diagnostic_node_actions`, `test_product_flow_canvas`,
`test_diagnostic_flow_geometry`, `test_product_flow_parity_panel`, `test_flow_compras_recepcion_snapshot`).
Al hilo solo vuelve el exit code, N/N y, si falla, la aserción + cola del traceback.

### 3.12 Contratos que NO deben romperse

- CA-1..CA-5 de 3.8.
- Firma/forma de `printflow.flow.canvas._pf_build_payload(host, mode)` y del builder
  `printflow.flow.payload.builder` (solo +2 claves ADITIVAS por nodo: `shortfall_qty`, `shortfall_label`).
- `pending`/`pending_label`/`pending_action` y el badge `text-bg-info` de pendientes.
- `status_label`/`summary`/`tone` de los nodos: valores INTACTOS.
- Motor externo `x_product_dimensional_pricing` (SOLO LECTURA); `deficit_qty`/`purchase_status` del
  veredicto; reglas del motor de salud.
- `_pf_open_buy_product`/`_pf_open_quick_purchase` (Compra Rápida, qty = déficit, `material_received=False`,
  sin forzar recepción).
- Estrategia `.order` (salvo T4/T8-opcional); `__manifest__.py` SIN cambios.
- `models/` nunca importa `wizard/`.

### 3.13 Observaciones (fuera de alcance)

- **O-1**: solo el nodo `purchase` pinta el badge (los demás nodos devuelven `shortfall_label=''` y
  `shortfall_qty=0`).
- **O-2**: `_pf_plan_order_shortfall` (causa "déficit sin ruta") conserva su `solution`
  `('navigate','purchase_order')`; es otra causa y no forma parte del nodo Compras de esta tarea.
- **O-3**: los listados/causantes de OC del diagrama de PEDIDO (`board._find_purchase_orders_by_sale_names`,
  `_pf_collect_causante_vals`) NO se alinean (son las compras del propio pedido). Reportado por si el
  dueño los quiere homologar.
- **O-4**: el catálogo (`printflow.inventory.catalog`) no pinta el badge (es un listado, no un diagrama):
  sin cambios.

---

## 3.B (ANEXO · TAREA CERRADA) — Fotografía real de Compras/Recepción
> **Estado:** CERRADA (núcleo CA-1..CA-6 verde, veredicto `cumple`; ver bitácora). Se
> conserva como referencia; NO forma parte de la tarea actual.

### 3.1 Problema (evidencia en BD)
El diagrama NO es todavía una fotografía limpia: el nodo **Compras** mezcla en la MISMA
tarjeta dos cosas distintas y el nodo **Recepción** no tiene señal propia.

- **Nodo Compras — contradicción visible.** La tarjeta pinta `statusLabel="Falta comprar"`
  (déficit) y DEBAJO el badge genérico "**29 pendiente(s)**". El 29 sale del motor de
  pendientes (`models/printflow_flow_pending.py` L275-280: el nodo `purchase` cuenta OC con
  `order_id.state in ('draft','sent','to approve','purchase')` **sin mirar si ya se recibió**).
  El badge se lee como "faltan 29 compras", pero **no** son compras faltantes.
  - **Evidencia (BD):** producto `IMPRESION BANNER` (id 13571, `purchase_ok=True`,
    `qty_available=4`, `outgoing_qty=35`, `incoming_qty=0`) tiene **29 OC**:
    **20 confirmadas** (`state=purchase`) — **todas ya recibidas** (21 albaranes de entrada
    `done`) pero **sin bloquear** (`done`), por eso siguen contando — y **9 en `draft`**
    (nunca confirmadas). 20 + 9 = 29.
- **Nodo Recepción — sin señal propia.** Su estado se "pide prestado" de Compras:
  `statuses['receipt'] = {'pending':'pending','missing':'na'}.get(purchase_status, ...)` en
  `models/printflow_flow_strategy_product.py` L132-134 y `models/printflow_flow_strategy_order.py`
  L216-217. NO informa de las recepciones REALES pendientes ni de los insumos.
- **Déficit real (a conservar):** 35 demanda − 4 existencia − 0 en camino = **31 u**. Eso es
  lo que el nodo debe seguir diciendo con "Falta comprar".

### 3.2 Objetivo (acotado)
**SÍ:**
1. **Recepción = señal PROPIA**: "hay N **recepciones pendientes por recibir**" derivadas de
   las compras → albaranes de entrada (`stock.picking`, `picking_type_id.code='incoming'`)
   abiertos (`state not in ('done','cancel')`) con movimientos del producto.
2. **Recepción con insumos (fabricación)**: cuando el producto es **fabricable**, además de
   contar las recepciones del terminado, contar las **recepciones pendientes de los
   componentes/insumos** de su BOM. Objetivo: poder saber si *falta validar la recepción de
   un componente* o si *falta comprar un componente y no hay existencia para fabricar*. La
   lógica debe quedar LISTA aunque el producto de hoy (`IMPRESION BANNER`) sea comprado.
3. **Compras = dos señales separadas y explícitas**:
   - (i) *"¿falta comprar para cubrir la demanda de ventas?"* → déficit (`missing`).
     **Se conserva** tal cual (el dueño confirma que hoy funciona).
   - (ii) *"¿hay OC en **borrador sin confirmar**?"* → **señal NUEVA** y rotulada aparte.
4. **Las OC ya RECIBIDAS dejan de contar** como pendientes (la mercancía ya entró; lo "por
   recibir" lo expresa el nodo Recepción).
5. **Mensajes/badges EXPLÍCITOS por nodo** en la cuadrícula: no un "N pendiente(s)" genérico
   que conviva con "Falta comprar". Cada badge debe decir DE QUÉ es (p. ej. "N sin confirmar",
   "N por recibir").
6. Aplica a **AMBOS** diagramas (producto y pedido) para no tener dos vocabularios.

**NO:**
- NO tocar el motor externo `x_product_dimensional_pricing` (solo LECTURA / reutilizar).
- NO reimplementar reglas de déficit/veredicto: se REUTILIZA el motor.
- NO escribir ningún dato (tarea de SOLO LECTURA).
- NO romper la paridad del pedido.

### 3.3 Semántica objetivo por nodo (contrato funcional)
| Nodo | Debe mostrar | Fuente |
|---|---|---|
| **Compras** | (i) Demanda: "Falta comprar" si déficit>0 (status `missing`). (ii) Documentos: "N OC sin confirmar" = OC del producto en `draft`/`sent`/`to approve`. | motor de salud (`purchase_status`) + motor de pendientes (`purchase`, filtrado a NO confirmadas) |
| **Recepción** | "N recepciones por recibir" = albaranes de entrada abiertos del terminado (+ insumos si fabricable). Si no hay ninguna → "No aplica"/"Recibido". | motor de pendientes (`receipt`) + BOM del producto |
| **Inventario / Almacén insumos / terminado** | sin cambios (delegan en `stock.health`). | — |

### 3.4 Fuente ÚNICA a reutilizar (cero reinvención)
- Motor de pendientes `printflow.flow.pending`: `_pf_node_pending_rows` (ya lee albaranes de
  entrada para `receipt` y OC para `purchase`), `_pf_node_pending_counts`,
  `_pf_node_pending_document_*`. NO reinventar lecturas.
- Fabricabilidad y BOM: `engine._pf_manufacturable_products(products)`,
  `strategy._pf_bom_components(product)` / `mrp.bom._bom_find`, `remedy._pf_has_bom`.
- Etiquetas: `printflow.flow.presentation._PF_NODE_STATUS_LABELS`.
- `deficit_qty` del veredicto (`purchase_status`) se conserva (NO se toca).

### 3.5 Decisiones de diseño que cierra el PLANIFICADOR (D1..D7)
- **D1 — Alcance del cambio del motor de pendientes.** El motor `printflow.flow.pending` lo
  comparten: diagrama de producto, diagrama de pedido (`_pf_node_pending_lookup`) y el
  **catálogo** (`printflow_inventory_catalog._pf_pending_label` / `node_pending_total`). Decidir
  si el cambio de dominio (purchase = solo no confirmadas; receipt con insumos) se hace DENTRO
  del motor o en la capa de presentación; y cómo queda el catálogo. Documentar.
- **D2 — Criterio de "OC ya recibida".** Definir la exclusión: `qty_received >= product_qty` en
  TODAS las líneas del producto (por OC) o vía estado del albarán. Considerar líneas parciales.
  No inventar: si no hay criterio fiable, documentar.
- **D3 — Qué estados cuentan como "sin confirmar".** `draft` (borrador) seguro; decidir
  `sent` / `to approve`. Alinear con la semántica pedida ("compras en estado borrador sin
  confirmar").
- **D4 — Recepción con INSUMOS.** Definir cómo se incluyen las recepciones de los componentes
  (BOM) sin N+1 (una sola lectura por lote) y cómo se refleja en el nodo Recepción (¿suma
  terminado + insumos? ¿chip/desglose?). Para producto NO fabricable → solo terminado.
- **D5 — Rotulado del badge por nodo.** Dónde vive el texto explícito del pendiente (p. ej.
  mapa en `presentation` + campo `pending_label` en el nodo del payload) y cómo lo pinta el
  widget `static/src/xml/printflow_order_timeline.xml` (hoy `<shape.pending/> pendiente(s)`,
  L121-126). Mantener compatibilidad del payload (`pending` numérico) y de los tests.
- **D6 — Desacople del status de Recepción.** Definir el nuevo cálculo de `statuses['receipt']`
  (producto y pedido) para que derive de las recepciones REALES (no del proxy de
  `purchase_status`). Cuidar la paridad del pedido.
- **D7 — Impacto en tests / candados.** `test_flow_canvas_parity.py`,
  `test_diagnostic_timeline_payload.py`, `test_node_pending_enumeration.py`, `test_flow_explain.py`
  (node_pending), `test_product_flow_*`. Decidir actualizaciones DELIBERADAS y documentarlas.

### 3.6 Archivos candidatos (el Planificador confirma/ajusta)
| Acción | Archivo | Qué se cambia |
|---|---|---|
| MODIFICAR | `models/printflow_flow_pending.py` | Dominio/conteo del nodo `purchase` (excluir OC ya recibidas; aislar "sin confirmar") y `receipt` (incluir insumos cuando aplique). |
| MODIFICAR | `models/printflow_flow_presentation.py` | Rotulado explícito del pendiente por nodo. |
| MODIFICAR | `models/printflow_flow_payload_builder.py` | Añadir la etiqueta del pendiente al nodo (forma aditiva). |
| MODIFICAR | `models/printflow_flow_strategy_product.py` / `..._order.py` | Desacople de `statuses['receipt']`; alimentar los nuevos conteos. |
| MODIFICAR | `static/src/xml/printflow_order_timeline.xml` (+ `.js` si aplica) | Pintar el badge con su etiqueta explícita. |
| MODIFICAR | `models/printflow_inventory_catalog.py` | Alinear el catálogo si cambia el motor (D1). |
| CREAR/MODIFICAR | `tests/*` | Fijan CA-1..CA-4; registrar en `tests/__init__.py`. |

**SIN CAMBIOS (a propósito):** motor externo `x_product_dimensional_pricing` (solo lectura);
reglas de déficit del veredicto; resto del widget/canvas no relacionado con los badges.

### 3.7 Restricciones duras
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): PROHIBIDO escribir/borrar en
  `purchase.order`, `stock.picking`, `stock.move`, `stock.quant`, `mrp.production` o cualquier
  registro. Solo LECTURA.
- **No forzar/reinventar flujos nativos**: se engancha con `_inherit` + `super()`; PROHIBIDO
  `cr.execute` de escritura o `cr.commit()`.
- **NO tocar el motor** `x_product_dimensional_pricing`.
- **NO romper la paridad del pedido**: `test_flow_canvas_parity.py` y los `test_diagnostic_*`
  siguen verdes.
- **Compatibilidad del payload/contrato del widget**: `pending` numérico se conserva; la
  etiqueta es ADITIVA.
- **`models/` nunca importa `wizard/`.**
- **Sin N+1**: una sola lectura por modelo (lote).

### 3.8 Criterios de Aceptación verificables
| # | Criterio | Verificación |
|---|---|---|
| CA-1 | Con una OC en `draft` y otra confirmada **ya recibida**, el nodo Compras reporta como pendiente SOLO la(s) borrador(es). | Test: crear ambas OC; `_pf_node_pending_map`/payload → purchase pending == nº borradores; la recibida NO cuenta. |
| CA-2 | Con un albarán de entrada abierto, el nodo Recepción lo reporta "por recibir"; con todo recibido, no. | Test sobre `receipt` (pending count y `status`). |
| CA-3 | Producto fabricable con componente con recepción pendiente → el nodo Recepción lo refleja. | Test con BOM + albarán de entrada del componente abierto. |
| CA-4 | Los mensajes/badges son explícitos por nodo (no el genérico "N pendiente(s)"). | Test del payload/vista: etiqueta del pendiente presente y diferenciada. |
| CA-5 | Paridad del pedido intacta. | `test_flow_canvas_parity.py` + `test_diagnostic_*` verdes. |
| CA-6 | Solo lectura. | `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; `git status` sin cambios en datos. |

### 3.9 Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Cambiar el motor compartido rompe el catálogo/pedido | Alto | D1: decidir capa; candados de tests; revisar catálogo. |
| Falsos negativos al excluir "recibidas" | Medio | Criterio explícito (D2) + test parcial. |
| N+1 al incluir insumos | Medio | Lectura por lote (D4). |
| Romper paridad del pedido | Alto | Cambios compartidos justificados + tests candado. |
| Tocar datos | Crítico | Solo LECTURA; `TransactionCase`. |

> **Nota para el Planificador:** cerrar D1..D7 y detallar T1..Tn en ESTA Sección 3 antes de
> pasar el turno a `odoo-dev`. Objetivo: FOTOGRAFÍA REAL → Compras = "¿tengo que comprar? +
> ¿hay borradores sin confirmar?"; Recepción = "¿qué falta por recibir?" (terminado e insumos).

### 3.10 Decisiones de diseño cerradas (D1–D7)

> Cierre del **Odoo Planificador**. Fuente: `odoo-impreven` / BD `Ciber Estudios 2015 RESTAURADA` ·
> Ruta `C:\odoo_custom\printflow_gestion_inventario`. Regla vigente: **código sí, datos no**. El
> diseño se ENGANCHA a lo existente (`_inherit` + `super()` / reutilización del motor); **solo LEE**
> (search/read). No toca el motor externo ni el builder/widget salvo lo ADITIVO.

**D1 — Capa del cambio (CERRADA).**
- El cambio de **dominio de `purchase`** (contar SOLO OC no confirmadas) se hace **DENTRO del motor
  único `printflow.flow.pending`**: `_pf_node_pending_rows` (L276-280), `_pf_node_pending_domain`
  (L351-355) y `_pf_node_pending_document_domain` (L465-471). Así las **tres superficies**
  (diagrama de producto, diagrama de pedido y catálogo `printflow.inventory.catalog`) hablan el
  mismo idioma; el catálogo hereda el nuevo conteo sin cambios extra.
- El **status propio de Recepción** y la **expansión a insumos** se hacen en la **capa de
  estrategia** (presentación por diagrama), reutilizando los lectores del motor. El catálogo NO
  incluye insumos (es un listado, no un diagrama): decisión documentada (O-4).
- `deficit_qty` / `purchase_status` del veredicto se **conservan tal cual** (NO se tocan).

**D2 — Criterio de "OC ya recibida" (CERRADA).**
- El dominio de `purchase` queda en estados **pre-confirmación**: `('draft','sent','to approve')`.
  Una OC **confirmada** (`state='purchase'`) NUNCA cuenta como "sin confirmar".
- Recibir exige confirmar antes, así que toda OC recibida está en `state='purchase'`: la exclusión de
  "ya recibidas" es **intrínseca al filtro de estado**. NO se usa el criterio frágil
  `qty_received >= product_qty` (se documenta por qué). Una OC **parcialmente** recibida sigue en
  `state='purchase'` → fuera de Compras; lo "por recibir" lo expresa el nodo Recepción.

**D3 — Estados "sin confirmar" (CERRADA).**
- Cuentan `draft`, `sent` y `to approve` (todo lo previo a la confirmación). El badge rotula
  "**N OC sin confirmar**".

**D4 — Recepción con INSUMOS (CERRADA).**
- Nuevo helper en el motor `printflow.flow.pending`: `@api.model _pf_receipt_pending_distinct(self,
  product_ids)` → UNA sola lectura con `_pf_node_pending_rows('receipt', ids)` y cuenta
  **albaranes DISTINTOS** (`picking_id`). Sin N+1 y **sin doble conteo** de un albarán con varios
  componentes.
- En AMBAS estrategias, cuando el producto es **fabricable**, el pendiente de `receipt` se recalcula
  con `ids = [terminado] + componentes(BOM)` (reutiliza `_pf_bom_components`). Para NO fabricable →
  solo el terminado (comportamiento actual).
- Se **suma** terminado + insumos en un solo número ("N por recibir"); NO hay chip/desglose en esta
  tarea (documentado como extensión futura, O-2).
- `_pf_bom_components` se **MUEVE** de `printflow.flow.strategy.product` a la base compartida
  `printflow.flow.strategy` (helper caso-agnóstico); los llamadores existentes
  (`wizard/printflow_product_flow.py` L170 y `models/printflow_flow_supply.py` L228) siguen
  resolviéndolo por herencia, sin cambios.

**D5 — Rotulado del badge por nodo (CERRADA).**
- Mapa `_PF_NODE_PENDING_LABELS` (+ `_PF_NODE_PENDING_LABEL_DEFAULT`) y helper
  `@api.model _pf_node_pending_label(key)` en `printflow.flow.presentation`.
- El builder `printflow_flow_payload_builder._pf_build` agrega `node['pending_label']` (string) —
  **ADITIVO**; `pending` numérico SE CONSERVA.
- Widget: `printflow_order_timeline.js` expone `pendingLabel: node.pending_label || ""`; la plantilla
  `printflow_order_timeline.xml` pinta `<t t-esc="shape.pending"/> <t t-esc="shape.pendingLabel"/>`
  conservando el `<span class="badge text-bg-info">` y **SIN** `t-on-click` (no rompe
  `test_timeline_pending_notice_is_informational_badge`).
- Etiquetas: `purchase`→"OC sin confirmar"; `receipt`→"por recibir"; `production`→"OF pendientes";
  `delivery`→"por entregar"; `stock*`→"con alerta"; resto→"pendiente(s)".

**D6 — Desacople del status de Recepción (CERRADA).**
- `statuses['receipt']` se deriva de las **recepciones REALES** (no del proxy de `purchase_status`):
  `'pending'` si el conteo de recepción del nodo (terminado [+ insumos]) > 0; `'na'` si no hay
  ninguna. **Misma regla** en producto y pedido. Etiquetas existentes: `pending`→"Por recibir",
  `na`→"No aplica".
- Se calcula **después** de tener `pending_by_key`.
- **Anti-falso-root (guard)**: como `receipt` comparte el slot `purchase` con el nodo Compras, se
  evita que su semáforo abra cadena por sí solo. En `printflow.flow.strategy._pf_broken_slots`
  (L167-177) se **omite la clave `receipt`** en la detección por tono (igual que ya se omite
  `customer`). Es un **no-op** para el comportamiento actual (hoy receipt sólo es warn cuando
  purchase también lo es) y **protege** el caso nuevo "solo recepción pendiente". La cadena causal
  sigue decidiéndola Compras/Inventario/Fabricación.
- Se usa `'na'` (no `'ok'`/"Recibido") cuando no hay recepciones abiertas: evita una lectura extra y
  **preserva** el candado del producto (el esqueleto congelado espera receipt `na`/"No aplica").

**D7 — Impacto en tests / candados (decisiones DELIBERADAS) (CERRADA).**
- **MODIFICAR DELIBERADAMENTE** `tests/test_product_flow_payload_parity.py`: agregar
  `'pending_label'` a `BASE_NODE_KEYS` (campo ADITIVO del nodo). Es el ÚNICO candado que congela el
  set de claves del nodo; el resto del candado queda intacto (los escenarios no crean OC/recepciones).
- **SIN CAMBIOS** (usan OC en `draft`, siguen verdes): `test_node_pending_enumeration.py`,
  `test_pending_native_validate.py`, `test_diagnostic_timeline_payload.py`
  (`test_popover_offers_pending_action` y el badge informativo), `test_inventory_catalog_*`,
  `test_diagnostic_flow_geometry.py`, `test_product_flow_canvas.py`, `test_flow_canvas_parity.py`.
- **CREAR** `tests/test_flow_compras_recepcion_snapshot.py` (CA-1..CA-6) y registrar en
  `tests/__init__.py`.

### 3.11 Plan de ejecución atómico y secuencial (T1–T8)

> Ejecutar EN ORDEN. T1–T2 = motor (`models/`); T3 = presentación; T4 = builder; T5–T6 = estrategias;
> T7 = widget; T8 = tests. Convenciones OCA (`odoo-17-clean-architecture` 2.5): métodos `_pf_*`,
> `snake_case`, un archivo por modelo, imports por bloques, nodo `<odoo>`... Solo LECTURA de BD.

- [x] **T1 — Motor: dominio de `purchase` = SOLO no confirmadas.**
  - Archivo: `models/printflow_flow_pending.py`.
  - En `_pf_node_pending_rows` (L276-280), `_pf_node_pending_domain` (L351-355) y
    `_pf_node_pending_document_domain` (L465-471): cambiar
    `('draft','sent','to approve','purchase')` → `('draft','sent','to approve')`.
  - Comentario del "por qué" (D2: recibida ⊂ confirmada). NO tocar `receipt`/`delivery`/`sale`/`production`.

- [x] **T2 — Motor: helper de recepción distinta (para insumos).**
  - Archivo: `models/printflow_flow_pending.py`.
  - Nuevo `@api.model def _pf_receipt_pending_distinct(self, product_ids)`: IDs limpios; si vacío → 0;
    `rows = self._pf_node_pending_rows('receipt', ids)`; `return len({r['picking_id'][0] for r in rows
    if r.get('picking_id')})`. Reutiliza el lector del motor (respeta `pf_node_pending_limit`). UNA consulta.

- [x] **T3 — Presentación: etiquetas de pendiente por nodo.**
  - Archivo: `models/printflow_flow_presentation.py`.
  - `_PF_NODE_PENDING_LABELS` (D5) + `_PF_NODE_PENDING_LABEL_DEFAULT = _('pendiente(s)')` +
    `@api.model def _pf_node_pending_label(self, key)`.

- [x] **T4 — Builder: exponer `pending_label` (aditivo).**
  - Archivo: `models/printflow_flow_payload_builder.py`, dict `node` (L124-159):
    `'pending_label': presentation._pf_node_pending_label(key)`.

- [x] **T5 — Estrategia PRODUCTO: Recepción propia + insumos + status.**
  - Archivo: `models/printflow_flow_strategy_product.py`.
  - Tras `pending_by_key` (L147-149): si `manufacturable` y hay componentes (`_pf_bom_components`),
    `ids = [product.id] + components.ids` y
    `receipt_count = env['printflow.flow.pending']._pf_receipt_pending_distinct(ids)`; si > 0 fijar
    `pending_by_key['receipt'] = receipt_count` (si 0, quitar la clave).
  - `statuses['receipt'] = 'pending' if pending_by_key.get('receipt') else 'na'` (sustituye el proxy
    de `purchase_status` de L132-134). NO fabricable → sólo terminado.
  - El resto del contexto (statuses/members/stock_split/playbook_ctx) intacto.

- [x] **T6 — Estrategia PEDIDO: Recepción propia + insumos + status.**
  - Archivos: `models/printflow_flow_strategy_order.py` (+ mover `_pf_bom_components` a la base
    `models/printflow_flow_strategy.py`, D4).
  - En `_pf_flow_context`, tras `_pf_node_pending_lookup` / override de `delivery` (L86-91): si
    `line.is_manufacturable`, expandir `pending_by_key['receipt']` con
    `_pf_receipt_pending_distinct([product] + componentes)`; luego
    `statuses['receipt'] = 'pending' if pending_by_key.get('receipt') else 'na'`.
  - **PARIDAD del pedido**: no cambiar el resto; `broken_slots` (L70) sigue calculándose antes del
    override, así el status propio NO abre cadena (guard de D6).

- [x] **T7 — Widget: pintar la etiqueta del badge.**
  - Archivos: `static/src/js/printflow_order_timeline.js` (en `get nodes()`: `pendingLabel:
    node.pending_label || ""`, junto a `pending` L311) y
    `static/src/xml/printflow_order_timeline.xml` (L121-126: `<t t-esc="shape.pending"/> <t
    t-esc="shape.pendingLabel"/>`, conservando span `text-bg-info` y sin `t-on-click`).
  - Son assets ya declarados en `__manifest__.py`; **NO** se toca el manifest.

- [x] **T8 — Tests: fijan CA-1..CA-6; candados.**
  - **CREAR** `tests/test_flow_compras_recepcion_snapshot.py` (registrar en `tests/__init__.py`):
    - CA-1: producto comprable con 1 OC `draft` + 1 OC confirmada y **recibida** (flujo NATIVO
      `action_confirm` + validar albarán) → `_pf_node_pending_map(product)['purchase'] == 1`.
    - CA-2: albarán de entrada abierto → receipt pending ≥1 y `status=='pending'`; todo recibido →
      receipt 0 y `status=='na'` (sobre `_pf_build_payload(wizard,'product')`).
    - CA-3: producto fabricable con BOM + OC confirmada de un componente (albarán abierto) → el nodo
      Recepción del producto (y del pedido) refleja ≥1.
    - CA-4: nodo del payload con `pending_label` presente y diferenciado (purchase ≠ receipt); con OC
      `draft` el badge de Compras es "OC sin confirmar".
    - CA-6: `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; sin tocar el motor.
  - **MODIFICAR** `tests/test_product_flow_payload_parity.py`: `BASE_NODE_KEYS` += `'pending_label'`
    (deliberado, D7).

**Verificación (turno del Verificador, fuera del dev).** `--test-tags /printflow_gestion_inventario`
(o subconjunto: `test_flow_compras_recepcion_snapshot`, `test_node_pending_enumeration`,
`test_pending_native_validate`, `test_diagnostic_timeline_payload`, `test_flow_canvas_parity`,
`test_product_flow_payload_parity`, `test_diagnostic_flow_geometry`, `test_product_flow_canvas`,
`test_inventory_catalog_*`). Al hilo solo vuelve exit code, N/N y, si falla, aserción + cola.

### 3.12 Contratos que NO deben romperse

- CA-1..CA-6 de 3.8.
- Firma/forma de `printflow.flow.canvas._pf_build_payload(host, mode)` y del builder
  `printflow.flow.payload.builder` (solo +1 clave ADITIVA `pending_label` por nodo).
- `pending` numérico y `pending_action` del nodo; el badge `text-bg-info` con `t-esc="shape.pending"`.
- `printflow.flow.pending` sigue siendo la ÚNICA fuente de pendientes (no se duplican lecturas).
- `deficit_qty`/`purchase_status` del veredicto; motor `x_product_dimensional_pricing` (solo LECTURA).
- Estrategia `.order`/`.product` (salvo lo de T5/T6), `__manifest__.py` (SIN cambios) y los llamadores
  de `_pf_bom_components` (`printflow_flow_supply.py`, `wizard/printflow_product_flow.py`).

### 3.13 Observaciones (fuera de alcance)

- **O-1**: el badge de nodos no listados en `_PF_NODE_PENDING_LABELS` conserva el texto genérico
  `pendiente(s)` (compatibilidad visual).
- **O-2**: el desglose "N de insumos" (terminado vs insumos) en el nodo Recepción queda FUERA; se
  suma en un solo número. Se reporta por si el dueño lo quiere.
- **O-3**: `receipt` no usa `'ok'`/"Recibido" para no añadir una lectura de albaranes `done` y
  preservar el candado del producto.
- **O-4**: el catálogo (`printflow.inventory.catalog`) hereda el nuevo dominio de `purchase` (solo no
  confirmadas) pero NO la expansión a insumos (es un listado, no un diagrama).

---

## 3.A (ANEXO · TAREA CERRADA) — Diagrama producto↔pedido: señales OF, cadena y leyenda
> **Estado:** CERRADA (verificado 32/32, exit 0, ver bitácora). Se conserva como referencia;
> NO forma parte de la tarea actual.

> **Turno:** Odoo Analista (cierre). **Estado:** CERRADA. Verificador: **32/32 verdes, exit 0, veredicto `cumple`**; CA-1..CA-5 cubiertos.
> **Fuente:** odoo-impreven / BD `Ciber Estudios 2015 RESTAURADA` · **Ruta:** `C:\odoo_custom\printflow_gestion_inventario`
> **Regla vigente:** código sí, datos no (`regla-trabajo-odoo-17-ce`). Tarea **GRANDE** (toca un flujo): cadena completa Analista → Planificador → Analista → Dev → Verificador → Analista.

### 3.1 Problema
Los dos diagramas **comparten el dibujante y el constructor**, pero **NO la cabeza**:
el widget `printflow_order_timeline` (puro: solo pinta el payload), el servicio
`models/printflow_flow_canvas.py::_pf_build_payload` y el builder
`models/printflow_flow_payload_builder.py::_pf_build` son ÚNICOS. Lo que cambia es la
**estrategia** (`printflow.flow.strategy.product` vs `.order`) y la **vista**. Por eso,
aunque sea "el mismo diagrama", el payload del producto sale más pobre.

La estrategia del PRODUCTO (`models/printflow_flow_strategy_product.py`) tiene 4 huecos
que hacen su diagrama menos informativo que el del pedido:

- **Hueco 1 — Fabricación ciega a la OF real.** `_pf_flow_context` pasa QUEMADOS
  `'active_mos': []` y `'done_mos': []` (L98-99) y NO pasa `has_draft_mo`,
  `mo_without_materials`, `is_late_material`, `design_pending`, `in_production_stage`,
  `in_delivery_stage` ni `is_stock_covered`. El motor
  `printflow.order.health.engine._pf_product_production` (L796-806) concluye `na`
  cuando no ve MOs → el nodo FABRICACIÓN queda **"No aplica" (gris)** aunque el producto
  tenga OF activa, mientras el badge de pendientes sí cuenta la OF. **Contradicción
  visible: "No aplica" + "N pendiente(s)".**
  - **Evidencia (BD):** producto `FONDO NEGRO` (id 13058) tiene OF activa
    `WH/MO/03587` (id 3588, `state=confirmed`); su diagrama muestra FABRICACIÓN
    "No aplica" con badge "1 pendiente(s)".
- **Hueco 2 — La CADENA DE FALLAS nunca aparece.** `chain_summary` va quemado en vacío
  (`'chain_summary': ''`, L147). El pedido sí lo llena (`host.focus_chain_summary`), por
  eso el diagrama del pedido muestra abajo *"Cadena de fallas: Compras (origen) →
  Inventario (consecuencia)"* y el del producto no.
- **Hueco 3 — Señales finas ausentes.** Ver Hueco 1: el pedido SÍ manda esas señales
  (`wizard/printflow_order_diagnostic_wizard.py` L1539-1552); la estrategia del producto
  no.
- **Hueco 4 — Vista sin leyenda ni franja de cadena.** `wizard/printflow_product_flow_views.xml`
  tiene SOLO el campo del widget; la vista del pedido
  (`wizard/printflow_order_diagnostic_wizard_views.xml` L191-221) incluye la **leyenda de
  colores** (`o_pf_timeline_legend`) y la **franja "Cadena de fallas"**.

> Aclaración de correctitud: parte de la diferencia es LEGÍTIMA. Un producto sano
> (p. ej. FONDO NEGRO: `qty_available` 1113.76, `purchase_ok=False`) DEBE verse sano
> (Compras "No aplica" es correcto). NO se busca que ambos diagramas se vean idénticos;
> se busca que el del producto sea igual de informativo **cuando hay problema**.

### 3.2 Objetivo (acotado)
**SÍ:**
1. Que la estrategia del producto lea las **señales reales de la OF** del producto (activa,
   borrador, sin insumos, en proceso; y —si hay fuente fiable— retraso y arte pendiente) y
   las pase al motor, de modo que el nodo FABRICACIÓN refleje la realidad (deje de decir
   "No aplica" con OF en curso).
2. Que el diagrama de producto **muestre la cadena de fallas** (raíz → consecuencias)
   cuando exista, igual que el del pedido.
3. Que la **vista** del producto muestre la **leyenda de colores** y la **franja de cadena**
   (Hueco 4).

**NO:**
- NO tocar la ESTRATEGIA DEL PEDIDO ni el builder ni el widget (paridad del pedido intacta).
- NO reimplementar reglas: se REUTILIZA el motor (misma fuente que el tablero/wizard).
- NO escribir ningún dato (módulo de SOLO LECTURA para el producto).

### 3.3 Fuente ÚNICA a reutilizar (cero reinvención)
- **Clasificación de OF:** `printflow.order.health.engine._pf_classify_mos(mos)` →
  `{'non_done','done','draft'}`. La usa el wizard/tablero
  (`wizard/printflow_order_diagnostic_wizard.py` L1422-1434). El producto debe leer sus OF
  con `mrp.production` (excluyendo `cancel`) y clasificarlas con ESTE helper.
- **Fabricabilidad:** `engine._pf_manufacturable_products(products)`.
- **Banderas de OF:** `engine._pf_mo_without_materials(mos)`, `_pf_mo_waiting_material`,
  `_pf_has_launched_mo`.
- **Veredicto:** `printflow.product.flow.diagnostic._pf_flow_verdict(ctx)` (ya llamado en
  L88-101 de la estrategia).
- **Etiquetas de cadena:** `PF_CHAIN_LABELS` (importado del motor) y los roles ya calculados
  por la estrategia (`_pf_slot_chain_roles` → `ctx['roles']` / `broken_slots`).
- **La estrategia del producto NO puede importar `wizard/`** (regla del módulo: `models/`
  nunca importa `wizard/`). El helper de lectura de OF debe vivir en `models/`.

### 3.4 Decisiones de diseño que el PLANIFICADOR debe cerrar (no el Dev)
- **D1 — Lectura de OF sin venta.** Definir el helper (en `models/`) que traiga las OF del
  producto y las clasifique con `_pf_classify_mos`. Prohibido reinventar la clasificación.
- **D2 — Compuertas sin pedido.** `in_production_stage` / `in_delivery_stage` son etapas de
  PEDIDO; sin venta no existen. Definir defaults que NO fabriquen falsos `to_launch`/`no_mo`
  (p. ej. no gatear `to_launch` sin etapa, o documentar el criterio elegido).
- **D3 — `is_late_material` sin pedido.** El tablero lo trae como flag; para un producto sin
  venta definir si hay criterio fiable (p. ej. OF activa con fecha vencida y sin material)
  o dejarlo explícitamente fuera (documentar). NO inventar un criterio divergente del motor.
- **D4 — `is_stock_covered`.** Sin demanda pendiente no hay "cobertura"; decidir si aplica.
- **D5 — `chain_summary` del producto.** Derivarlo de `roles`/`broken_slots` (raíz +
  consecuencias) + `PF_CHAIN_LABELS`. NO tocar el `_pf_chain_summary` de registros del
  pedido. Exponer un campo `chain_summary` (Char, compute) en `printflow.product.flow`,
  análogo a `focus_chain_summary`.
- **D6 — Leyenda (Hueco 4).** Reutilizar las clases SCSS ya existentes
  (`o_pf_timeline_legend`, `o_pf_legend_dot`, `o_pf_legend_ring`, etc.). NO crear CSS nuevo.
  Verificar que el SCSS no esté acoplado al modal del pedido (`o_pf_diag_modal`).
- **D7 — Alcance del escáner.** `models/checks/check_flow.py` (L107) también usa
  `active_mos: []`. El Planificador decide si queda FUERA de alcance (recomendado) y lo
  documenta.

### 3.5 Archivos candidatos (el Planificador confirma/ajusta)

| Acción | Archivo | Qué se cambia (a detallar por el Planificador) |
|---|---|---|
| MODIFICAR | `models/printflow_flow_strategy_product.py` | Reemplazar `active_mos: []`/`done_mos: []` por OF reales; pasar banderas finas; calcular `chain_summary` real. |
| MODIFICAR | `wizard/printflow_product_flow.py` | Exponer `chain_summary` (Char, compute) para la vista. |
| MODIFICAR | `wizard/printflow_product_flow_views.xml` | Agregar leyenda + franja "Cadena de fallas" (espejo de la vista del pedido). |
| CREAR/MODIFICAR | `tests/*` | Test que fije CA-1/CA-2; revisar/actualizar el candado del producto `tests/test_product_flow_payload_parity.py` si cambia el payload; registrar en `tests/__init__.py`. |

**SIN CAMBIOS (a propósito):** widget `static/src/js/printflow_order_timeline.js` y su
XML (el widget NO pinta la cadena; eso va en la VISTA), builder
`printflow_flow_payload_builder.py`, estrategia `.order`, y el motor
`x_product_dimensional_pricing` (solo LECTURA). El `__manifest__.py` no requiere assets
nuevos.

### 3.6 Restricciones (duras)
- **Código sí, datos no** (`regla-trabajo-odoo-17-ce`): PROHIBIDO escribir/borrar en
  `mrp.production`, `stock.move`, `stock.quant`, `stock.picking` o cualquier registro.
  Solo LECTURA (search/read).
- **No forzar/reinventar flujos nativos** (inventario/fabricación): el código se engancha
  con `_inherit` + `super()` donde aplique; PROHIBIDO `cr.execute` de escritura o
  `cr.commit()`.
- **NO tocar el motor** `x_product_dimensional_pricing` (solo reutilizar sus helpers).
- **NO romper la PARIDAD del pedido:** estrategia `.order`, builder y widget intactos;
  `test_flow_canvas_parity.py` y los `test_diagnostic_*` deben seguir verdes.
- **NO cambiar el contrato del widget:** la leyenda/cadena se pintan en la VISTA, no en el
  widget.
- **`models/` nunca importa `wizard/`.**

### 3.7 Criterios de Aceptación verificables

| # | Criterio | Verificación |
|---|---|---|
| CA-1 | El nodo FABRICACIÓN del diagrama de producto refleja la OF real: con OF activa NO dice "No aplica". | Test que cree un producto fabricable con OF activa y verifique `production_status` ≠ `na` y `tone` ≠ `na` en el nodo `production` del payload `_pf_build_payload(wizard,'product')`. |
| CA-2 | Con fallas, el diagrama de producto muestra la cadena de fallas. | Test: `global.chain_summary` no vacío y el campo `chain_summary` del wizard poblado cuando hay raíz+consecuencia. |
| CA-3 | La vista del producto muestra la leyenda de colores y la franja de cadena. | Vista: `//div[contains(@class,'o_pf_timeline_legend')]` y el `field` de `chain_summary` presentes en `printflow.product.flow` form. |
| CA-4 | Paridad del pedido intacta. | `test_flow_canvas_parity.py`, `test_diagnostic_timeline_payload.py` y demás `test_diagnostic_*` siguen verdes. |
| CA-5 | No se crea/modifica ningún dato persistente. | Tests `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; `git status` sin cambios en `x`. |

### 3.8 Riesgos y efectos colaterales a vigilar

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Romper la paridad del pedido | Alto | Solo se toca la estrategia `.product`; el pedido usa `.order`. Tests de pedido como candado. |
| `test_product_flow_payload_parity.py` (candado del producto) falla por el cambio de payload | Alto | Revisar y actualizar ese candado de forma DELIBERADA, documentando el nuevo contrato esperado. |
| Falsos positivos al "encender" FABRICACIÓN | Alto | Reutilizar `_pf_product_production` con los MISMOS helpers y las compuertas que el pedido; no inventar reglas. |
| N+1 al leer OF/componentes por producto | Medio | Lectura en UNA sola pasada (search por lote), reutilizando `_pf_classify_mos` y `_pf_manufacturable_products`. |
| Tocar el motor o el widget | Alto | Restricción explícita: motor solo LECTURA; widget sin cambios. |
| Tocar datos | Crítico | Solo LECTURA; tests `TransactionCase`. |

> **Nota de diseño (para el Planificador):** el objetivo es PARIDAD DE INFORMACIÓN, no
> identidad visual. Un producto sano debe seguir mostrándose sano. Detallar T1→Tn y
> actualizar esta Sección 3 antes de pasar el turno a `odoo-dev`.


## 3.9 Decisiones de diseño cerradas (D1–D7)

> Cierre del Planificador (turno entrante). Cierra las decisiones de 3.4 sin tocar el
> motor, el builder, el widget ni la estrategia del pedido. Principio: el diseno se
> ENGANCHA a lo existente y REUTILIZA el motor; solo LEE la BD (regla: codigo si, datos no).

- **D1 — Lectura de OF sin venta (CERRADA).** Nuevo helper `@api.model` en `models/`
  (dentro de `models/printflow_flow_strategy_product.py`, seccion "HELPERS DE CONTEXTO DEL
  PRODUCTO", junto a `_pf_root_tray`, que ya lee `mrp.production`): `_pf_product_mos(product)`
  -> busca `mrp.production` (`sudo`, `product_id = product.id`, `state != 'cancel'`) y
  clasifica con `engine._pf_classify_mos(...)`; devuelve `{'non_done', 'draft', 'done'}`.
  UNA sola consulta (en lote, sin N+1); clasificacion REUTILIZADA, jamas reinventada.
- **D2 — Compuertas sin pedido (CERRADA).** `in_delivery_stage = False` (sin venta no hay
  entrega -> evita el falso `no_mo`: un fabricable SIN OF queda `na`, nunca "sin orden").
  `in_production_stage = True` (sin etapa de pedido, el borrador de OF ES un "sin lanzar"
  real; el objetivo 3.2#1 pide reflejar el borrador). `production_alert` NO se pasa
  (queda `None`); el motor no dispara `no_mo` por esa via.
- **D3 — `is_late_material` sin pedido (CERRADA, FUERA de alcance).** El `is_late_material`
  del tablero es un flag POR PEDIDO (ventana +24h) sin equivalente fiable por producto. NO
  se inventa criterio divergente del motor: NO se pasa. Efecto: una OF con material
  pendiente se reporta como `material` (no `late`), que ya es informativo.
- **D4 — `is_stock_covered` sin pedido (CERRADA, no aplica).** "Cobertura" exige demanda
  pendiente; sin venta no la hay. NO se pasa (ausente => el motor no suprime senales). Asi
  las senales reales de la OF (borrador/sin insumos/en proceso) SI se ven.
- **D5 — `chain_summary` del producto (CERRADA).** Se DERIVA de lo ya calculado en la
  estrategia (roles por slot, `root_slot`, `broken_slots`), no de registros de pedido. Se
  agrega el helper `@api.model _pf_product_chain_summary(ctx)` (en la estrategia del
  producto) que reproduce EL MISMO FORMATO del pedido (`canvas._pf_chain_summary`):
  "Etiqueta (origen) -> Etiqueta (consecuencia)", con `PF_CHAIN_LABELS` y los sufijos
  `_('origen')` / `_('consecuencia')`, ordenado por `PF_CHAIN_SLOTS` y deduplicado por nodo.
  Se asigna en `_pf_with_derived` (alli ya viven `roles`/`broken_slots`/`root_slot`) sobre
  `ctx['chain_summary']` (hoy `''`). NO se toca `canvas._pf_chain_summary` (pedido intacto).
- **D6 — Leyenda (CERRADA).** Reutilizar las clases SCSS existentes
  (`o_pf_timeline_legend`, `o_pf_timeline_legend_item`, `o_pf_legend_dot` + `tone-*`,
  `o_pf_legend_ring`, `o_pf_legend_dashed`). VERIFICADO: son GENERICAS y NO estan acopladas
  al modal del pedido (`o_pf_diag_modal` solo aplica a `.modal-dialog`). CERO CSS nuevo.
- **D7 — Escaner (CERRADA, FUERA de alcance).** `models/checks/check_flow.py` (L107) conserva
  `active_mos: []` / `done_mos: []`. NO se toca en esta tarea (documentado).

## 3.10 Plan de ejecucion atomico y secuencial (T1-T7)

> Ejecutar EN ORDEN. T1-T4 son `models/` (logica); T5 el wizard; T6 la vista; T7 los tests.
> Convenciones OCA (skill `odoo-17-clean-architecture` 2.5): un archivo por modelo, metodos
> `_pf_*`, `snake_case`, `xml_id` `printflow_product_flow_view_form`, nodo `<odoo>`.

- [x] **T1 — Helper de lectura de OF del producto (models/).**
- Archivo: `models/printflow_flow_strategy_product.py`.
- Agregar `@api.model def _pf_product_mos(self, product)` -> `{'non_done','done','draft'}`
  via `engine._pf_classify_mos` (D1). Lectura en UNA sola pasada (sin N+1).
- Solo `search`/`read`; no escribe nada.

- [x] **T2 — Inyectar las senales reales de la OF en el contexto del veredicto.**
- Archivo: `models/printflow_flow_strategy_product.py`, metodo `_pf_flow_context` (L74-101).
- Reemplazar `'active_mos': []` / `'done_mos': []` por los buckets de T1.
- Anadir al dict del veredicto (mismas claves que el pedido, `printflow_order_diagnostic_wizard.py`
  L1539-1552): `has_draft_mo`, `mo_without_materials` (`engine._pf_mo_without_materials(non_done)`),
  `in_production_stage = True` y `in_delivery_stage = False` (D2). NO pasar `production_alert`,
  `is_stock_covered`, `is_late_material` ni `design_pending` (D2/D3/D4).
- Mantener intacto el resto del contrato del contexto (statuses, members, stock_split,
  pending_by_key, playbook_ctx).

- [x] **T3 — Fabricabilidad por la fuente unica.**
- Archivo: mismo, `_pf_flow_context` (~L84).
- Resolver `manufacturable = product.id in engine._pf_manufacturable_products(product)`
  (reutiliza `_pf_manufacturable_products`, 3.3). Conservar `flow_type` derivado de
  `manufacturable` (NO se cambia la logica del eje; ver Observacion O-2).

- [x] **T4 — `chain_summary` real del producto (D5).**
- Archivo: mismo.
- Agregar `@api.model def _pf_product_chain_summary(self, ctx)` (D5).
- En `_pf_with_derived`, tras calcular `roles`/`broken_slots`/`root_slot`, asignar
  `ctx['chain_summary'] = self._pf_product_chain_summary(ctx)` (hoy `''` en L147).
- Importar `PF_CHAIN_SLOTS` desde el motor (el archivo ya importa `PF_CHAIN_LABELS` y
  `PF_NODE_TO_SLOT` de alli).
- NO tocar `printflow.flow.canvas._pf_chain_summary`.

- [x] **T5 — Exponer `chain_summary` en el wizard del producto.**
- Archivo: `wizard/printflow_product_flow.py`.
- Campo `chain_summary = fields.Char(string='Cadena de fallas', compute='_compute_header_fields', readonly=True)`
  (orden OCA: tras `root_cause_node`, antes de `timeline_json`).
- En `_compute_header_fields`, asignar `rec.chain_summary = ctx.get('chain_summary') or ''`.

- [x] **T6 — Vista: leyenda + franja de cadena (Hueco 4 / D6).**
- Archivo: `wizard/printflow_product_flow_views.xml`, form `printflow_product_flow_view_form`.
- Despues del campo `timeline_json`, insertar (espejo del pedido,
  `printflow_order_diagnostic_wizard_views.xml` L191-221): (a) el bloque de LEYENDA
  `div.o_pf_timeline_legend` con sus items (Sano / Atencion / Critico / Sin dato, Raiz ->
  consecuencia, Raiz, Independiente) y (b) la FRANJA de cadena
  `div.alert.alert-light.border...` con `invisible="not chain_summary"` y
  `<field name="chain_summary">`.
- Usar modificadores Odoo 17 (`invisible=`), NO `attrs=`. CERO CSS nuevo.

- [x] **T7 — Tests (fijan CA-1/CA-2; candados CA-4/CA-5).**
- Crear `tests/test_product_flow_production_signals.py` y registrarlo en `tests/__init__.py`.
  - CA-1: producto FABRICABLE con una OF activa (`state` no `cancel`/`done`) -> en el payload
    `_pf_build_payload(wizard, 'product')` el nodo `production` tiene `status != 'na'` y
    `tone != 'na'`.
  - CA-2: escenario con raiz + consecuencia de la cadena -> `payload['global']['chain_summary']`
    NO vacio y `wizard.chain_summary` NO vacio.
  - CA-5: `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`.
- Revisar `tests/test_product_flow_payload_parity.py`: sus escenarios NO crean OF, por lo que
  el payload NO debe cambiar (esperado: sin cambios). Actualizarlo SOLO si el contrato cambia,
  de forma deliberada y documentada (riesgo Alto de 3.8).

**Verificacion (fuera del turno dev = Verificador).** Correr solo lo relevante con salida a
archivo: `--test-tags /printflow_gestion_inventario` (o subconjunto: `test_product_flow_*`,
`test_flow_canvas_parity`, `test_diagnostic_timeline_payload`). Al hilo solo vuelve el exit
code, el conteo N/N y, si falla, la asercion + cola del traceback.

## 3.11 Contratos que NO deben romperse

- CA-1..CA-5 de 3.7.
- Firma y forma de `printflow.flow.canvas._pf_build_payload(host, mode)`.
- Builder `printflow.flow.payload.builder`; widget `printflow_order_timeline` (+ XML).
- Estrategia `.order`, `canvas._pf_chain_summary`, motor `x_product_dimensional_pricing`.
- `__manifest__.py` SIN cambios (no hay assets nuevos; la vista ya esta en `data`).
- SIN CAMBIOS a proposito: `printflow_flow_strategy_order.py`,
  `printflow_flow_payload_builder.py`, `static/src/js/printflow_order_timeline.js` (+ xml),
  `models/checks/check_flow.py` (D7).

## 3.12 Observaciones (fuera de alcance)

- **O-1**: el badge "N pendiente(s)" ya cuenta la OF aunque el nodo diga "No aplica": es la
  contradiccion que T2 corrige (evidencia: FONDO NEGRO id 13058 + OF WH/MO/03587).
- **O-2**: si un producto tuviera una OF pero `_pf_manufacturable_products` no lo marcara
  fabricable (p. ej. BOM archivada), el eje seria `purchase` y no habria nodo Fabricacion.
  Se deja FUERA (no se altera la logica del eje); se reporta por si el dueno decide otra cosa.
- **O-3**: D3 (`late`) y el arte (`design_pending`) sin venta quedan FUERA por falta de fuente
  fiable (documentado en D3/D4).

## 4. Histórico / Bitácora de Cambios (Changelog)
- [2026-10-15 · Odoo Analista] Creación del CONTEXT.md. Diagnóstico: el botón
  "Ver diagrama" del catálogo fue eliminado (F7) sin cablear el clic al diagrama,
  incumpliendo el plan §3.3 (fila 9). Se abre la tarea de restauración del
  drill-down por clic en `product_id`.
- [2026-10-15 · Odoo Planificador] Diseño aprobado: Opción 1 (generalizar el
  widget `printflow_open_timeline` con `options.action`, default
  `action_open_product`). Se detalló la Sección 3 con T1→T5, CA-1..CA-5 y riesgos.
- [2026-10-15 · Odoo Dev] Ejecutado T1→T5. Modificados:
  `static/src/js/printflow_open_timeline.js` (prop `actionMethod` + `extractProps`
  + `resModel` derivado del registro), `views/printflow_inventory_catalog_views.xml`
  (L29 widget+options; comentario F7 actualizado), creado
  `tests/test_catalog_list_drilldown_widget.py` y registrado en `tests/__init__.py`.
  **Tests: 11/11 verdes** (nuevo 4/4 + `test_diagnostic_selector_view` 4/4 +
  `test_inventory_catalog_drilldown` 3/3). CA-1..CA-5 cumplidos.
  **Pendiente del dueño:** reiniciar Odoo (servidor 8071) para recargar assets JS.
  Observación (fuera de alcance, no tocada): el `-u` loguea `<delete>` sobre xmlids
  ya inexistentes del motor de salud retirado en `printflow_node_pending_views.xml`
  y `printflow_inventory_health_views.xml` (no rompen la carga).
- [2026-10-15 · Odoo Analista] Cierre de ciclo. Bitácora escrita, tareas T1→T5
  marcadas `[x]`. Tarea cerrada. Turno devuelto a Odoo Analista.
- [2026-10-15 · Odoo Analista] Nueva tarea (Grande): ALINEAR el diagrama de flujo del
  PRODUCTO con el del PEDIDO (opción 2+3). Diagnóstico: mismo widget/canvas/builder,
  pero distinta estrategia y vista. Huecos: (1) `active_mos`/`done_mos` quemados →
  FABRICACIÓN "No aplica" con OF viva (evidencia: FONDO NEGRO id 13058 + OF WH/MO/03587);
  (2) `chain_summary=''` → sin cadena de fallas; (3) señales finas ausentes; (4) vista de
  producto sin leyenda ni franja de cadena. Escrita la Sección 3 con contrato §3.3 y
  decisiones de diseño D1-D7 para el Planificador. Turno → Odoo Planificador.
- [2026-10-15 · Odoo Planificador] Plan atomico entregado (3.9-3.11). Decisiones D1-D7 cerradas: helper de OF en `models/` reutilizando `_pf_classify_mos` (D1); senales reales (active/done/draft) + `mo_without_materials`/`has_draft_mo` al veredicto (T2); compuertas `in_delivery_stage=False` / `in_production_stage=True` (D2); `late` (D3) y `is_stock_covered` (D4) FUERA;   `chain_summary` derivado de `roles` (D5); leyenda/franja por clases SCSS existentes (D6); escaner FUERA (D7). T1-T7 definidas; sin cambios en motor/builder/widget/estrategia de pedido. Turno -> Odoo Analista (paso 3: revisar y pasar a Odoo Tech).
- [2026-10-15 · Odoo Analista] Convención del Diagrama de Partes (metáfora del carro)
  oficializada en la skill `metodo-trabajo-odoo-context-md` (§2.1): capas MOTOR (arriba,
  `NO SE TOCA`) → TRANSMISION → RUEDAS (intercambiables), flechas = cables rotulados,
  colores por rol + leyenda, y **regla de imagen SIEMPRE** (fuente `.mermaid` + `.png`
  re-renderizado en el mismo turno). Reescrita la Sección 2.B de este CONTEXT.md con el
  nuevo diagrama (motor arriba, transmite hacia afuera) y añadida la carpeta
  `docs/diagramas/` (`printflow_gestion_inventario.mermaid` + `.png`). Sin tocar código ni
  datos. **Pendiente del dueño:** reiniciar opencode para recargar la skill.
- [2026-10-15 · Odoo Tech (Dev)] Ejecutado T1→T7. Modificados:
  `models/printflow_flow_strategy_product.py` (T1 helper `_pf_product_mos` reutilizando
  `_pf_classify_mos`; T2 señales reales + compuertas D2; T3 fabricabilidad por
  `_pf_manufacturable_products`; T4 `_pf_product_chain_summary`),
  `wizard/printflow_product_flow.py` (T5 campo `chain_summary` Char compute),
  `wizard/printflow_product_flow_views.xml` (T6 leyenda + franja de cadena, cero CSS nuevo),
  creado `tests/test_product_flow_production_signals.py` y registrado en `tests/__init__.py`.
  SIN cambios a propósito: widget, builder, estrategia `.order`, `check_flow.py` (D7),
  `__manifest__.py`. Solo lectura de BD.
- [2026-10-15 · Odoo Verificador] Veredicto **`cumple`**. Evidencia:
  `odoo-bin -d pf_picker_tests -u printflow_gestion_inventario,x_product_dimensional_pricing
  --test-enable --test-tags /printflow_gestion_inventario:TestProductFlowProductionSignals,
  TestProductFlowPayloadParity,TestFlowCanvasParity,TestDiagnosticTimelinePayload
  --stop-after-init` → **exit 0, 32/32 verdes** (7+8+3+14), 0 failed/0 error. CA-1..CA-5
  cubiertos; paridad del pedido intacta (candado del producto pasó tal cual). Hallazgo
  [baja]: `__manifest__.py` en 17.0.1.3.0 (la BD tenía 1.2.0); mtime previo a los archivos
  de código del turno ⇒ no atribuible con certeza a esta tarea (no añade assets/data).
- [2026-10-15 · Odoo Analista] Cierre de ciclo (compuerta de convergencia §4.3). Evidencia
  del Verificador aceptada (32/32 verdes, exit 0, `cumple`). T1→T7 marcadas `[x]`. Ficha y
  Sección 3 cerradas. Bitácora escrita. Turno devuelto a Odoo Analista.
  **Pendiente del dueño:** (1) reiniciar/actualizar el módulo en el servidor 8071 (`-u
  printflow_gestion_inventario`) para recargar la vista del producto; (2) decidir si la
  subida de versión del `__manifest__.py` (1.2.0 → 1.3.0) se mantiene.
- [2026-10-15 · Odoo Analista] Nueva tarea (Grande): FOTOGRAFÍA REAL del diagrama en los
  nodos COMPRAS y RECEPCIÓN. Diagnóstico (BD): el nodo Compras muestra "Falta comprar" +
  badge genérico "29 pendiente(s)"; el 29 = OC abiertas del motor de pendientes
  (`printflow_flow_pending.py` L275-280), que cuenta OC en `draft/sent/to approve/purchase`
  **sin mirar si ya se recibió**. Evidencia: `IMPRESION BANNER` (id 13571, `qty_available=4`,
  `outgoing_qty=35`, `incoming_qty=0`, déficit 31) → 20 OC confirmadas (todas ya recibidas,
  sin bloquear) + 9 en borrador = 29. El nodo Recepción NO tiene señal propia (usa el proxy
  `statuses['receipt']` de `purchase_status`, `strategy_product.py` L132-134). Acordado con
  el dueño: (a) Recepción = "N recepciones pendientes por recibir" (albaranes de entrada
  abiertos) del terminado Y —si fabricable— de los insumos de su BOM; (b) Compras = déficit
  ("Falta comprar", se conserva) + señal separada "N OC en borrador sin confirmar";
  (c) las OC ya recibidas dejan de contar; (d) badges explícitos por nodo; aplica a AMBOS
  diagramas sin romper la paridad del pedido. Escrita la Sección 3 (contrato §3.3, D1-D7,
  CA-1..CA-6); la tarea anterior pasa a anexo 3.A. Turno → Odoo Planificador.
- [2026-10-15 · Odoo Planificador] Plan de la FOTOGRAFÍA REAL de Compras/Recepción. Decisiones D1-D7 cerradas sobre el motor único `printflow.flow.pending` (D1): `purchase` = solo no confirmadas (`draft/sent/to approve`, D2/D3) → la exclusión de "ya recibidas" es intrínseca al estado; Recepción propia desde albaranes de entrada abiertos con INSUMOS de la BOM cuando fabricable (D4: `_pf_receipt_pending_distinct`, `_pf_bom_components` movido a la base); badge EXPLÍCITO por nodo vía `pending_label` aditivo (D5); status de Recepción desacoplado del proxy de compra + guard en `_pf_broken_slots` para no abrir cadena (D6). Tareas T1-T8 (3.11). Único candado a actualizar de forma DELIBERADA: `BASE_NODE_KEYS` de `test_product_flow_payload_parity.py` (+`pending_label`). Nuevo `tests/test_flow_compras_recepcion_snapshot.py` (CA-1..CA-6). Sin cambios en el motor externo, el builder del pedido, el widget (salvo el badge) ni `__manifest__.py`. Turno -> Odoo Analista (revisar y pasar a Odoo Tech).
- [2026-10-15 · Odoo Analista] Revisión (paso 3): plan de la Sección 3 CONFORME al contrato §3.3
  (D1–D7 cerradas, T1–T8, CA-1..CA-6, restricciones duras). Turno → Odoo Tech.
- [2026-10-15 · Odoo Tech (Dev)] Ejecutado T1→T8. Cambios: `printflow_flow_pending.py`
  (`PURCHASE_UNCONFIRMED_STATES = ('draft','sent','to approve')` en las 3 rutas; helper
  `_pf_receipt_pending_distinct`), `printflow_flow_presentation.py` (`_PF_NODE_PENDING_LABELS`
  + `_pf_node_pending_label`), `printflow_flow_payload_builder.py` (`node['pending_label']`
  aditivo), `printflow_flow_strategy.py` (`_pf_bom_components` movido a la base + guard `receipt`
  en `_pf_broken_slots`), `printflow_flow_strategy_product.py` / `..._order.py` (recepción propia
  + insumos + status desacoplado), widget `.js`/`.xml` (`pendingLabel`). Creado
  `tests/test_flow_compras_recepcion_snapshot.py`; `BASE_NODE_KEYS` += `pending_label` (D7).
  `py_compile` OK. Solo LECTURA; `__manifest__.py` sin cambios.
- [2026-10-15 · Odoo Verificador] Veredicto **`cumple`**. Evidencia:
  `odoo-bin -d pf_picker_tests -u printflow_gestion_inventario,x_product_dimensional_pricing
  --test-enable --test-tags /printflow_gestion_inventario` → NÚCLEO verde:
  `TestFlowComprasRecepcionSnapshot` 6/6 (CA-1..CA-6), `TestFlowCanvasParity` 3/3,
  `TestProductFlowPayloadParity` 8/8, `TestDiagnosticTimelinePayload` 14/14,
  `TestDiagnosticFlowGeometry` 12/12, `TestProductFlowCanvas` 8/8, `TestInventoryCatalog*` verde.
  El full-suite termina exit 1 con **7 failed + 1 error AJENOS** (delivery/lote/phase7; footprint
  fuera de Compras/Recepción/`pending_label`/paridad) y el fallo pre-existente
  `test_node_pending_enumeration.test_limit_is_per_node` (limit aplicado en el caller, no en el
  motor). Hallazgo [baja]: sin baseline (git sin commits) la atribución es por footprint, no diff.
- [2026-10-15 · Odoo Analista] Cierre de ciclo (compuerta de convergencia §4.3). Evidencia del
  Verificador aceptada (núcleo CA-1..CA-6 verde, veredicto `cumple`). T1→T8 marcadas `[x]`. Ficha
  y Sección 3 cerradas. Bitácora escrita.
  **Pendiente del dueño:** (1) reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar el widget (assets JS) y ver los badges
  explícitos; (2) ABIERTO (ajeno a esta tarea): 8 rojos de la suite completa (delivery/lote/phase7
  + `test_node_pending_enumeration.test_limit_is_per_node`) que conviene atacar en una tarea
  aparte; (3) el Dev reportó que `wizard/printflow_product_flow.py::_pf_open_purchase_orders` y
  `_pf_root_tray` siguen listando OC incluyendo confirmadas (listados informativos, no el badge);
  decidir si se alinean.
- [2026-10-15 · Odoo Analista] A petición del dueño, los pendientes 2 y 3 se difieren: quedan
  registrados como **Backlog para próximas sesiones** (Sección 1): **B1** = analizar los 8 rojos de
  la suite completa (obtener baseline primero); **B2** = decidir/alinear los listados informativos
  de OC del producto (`_pf_open_purchase_orders`, `_pf_root_tray`). No se toca código ni datos; se
  abordarán en una sesión aparte arrancando por el Analista.
- [2026-10-15 · Odoo Analista] Nueva tarea (GRANDE, arquitectura): el nodo **COMPRAS** debe decir
  **CUÁNTO** falta comprar y su resolución debe **GUIAR A COMPRARLO** (no a las compras hechas).
  Diagnóstico (BD `Ciber Estudios 2015 RESTAURADA`, producto `IMPRESION BANNER ` id 13571): el
  nodo Compras pinta "Falta comprar" **SIN magnitud** + badge "4 OC sin confirmar" (documentos),
  mientras Inventario ("Sin stock: 31.00") y Entrega ("29 por entregar") SÍ muestran su magnitud;
  déficit real = 35 (`outgoing_qty`) − 4 (`qty_available`) − 0 (`incoming_qty`) = **31 u**. La
  resolución actual abre/listan compras YA hechas (`_pf_open_purchase_orders` incluye confirmadas;
  `_pf_root_tray` lista OC incluyendo confirmadas = **B2**; el plan `order_supply_missing` propone
  "Ver la compra del pedido"). Se confirmó POR DATOS que el producto NO tiene ninguna recepción
  abierta (21 OC confirmadas, todas con albarán `done`; 4 OC en borrador; 5 canceladas) ⇒ el nodo
  Recepción "No aplica" es **correcto**; la mejora es de COMPRAS. Escrita la Sección 3 (contrato
  §3.3, D1-D5, CA-1..CA-5); la tarea anterior de Compras/Recepción pasa al **anexo 3.B**.
  Turno → Odoo Planificador.

- [2026-10-15 · Odoo Planificador] Plan de la magnitud del déficit en el nodo COMPRAS. Decisiones
  D1-D5 cerradas: D1 = badge ADITIVO nuevo por nodo (`shortfall_qty`/`shortfall_label`; el widget
  muestra el `summary` y no el `statusLabel` cuando hay falla, por eso la cifra va en un badge);
  D2 = resolución del nodo = Compra Rápida (plan `order_supply_missing` → `open_wizard`/`buy_product`),
  reutilizando `_pf_open_buy_product`; D3 = cerrar B2 alineando los listados de OC del PRODUCTO
  (`_pf_open_purchase_orders`, `_pf_root_tray`) a solo "sin confirmar" (fuente única `printflow.flow.pending`);
  D4 = generalidad/paridad vía `ctx['shortfall_by_key']` (déficit real, sin hardcode; ambos ejes);
  D5 = candados: `BASE_NODE_KEYS` (+2 claves), `test_diagnostic_levels` y `test_diagnostic_unified_solution`
  (plan ahora = Compra Rápida; remedio redundante). Plan T1-T10 + CA-1..CA-5 (nuevo
  `tests/test_flow_compras_deficit_magnitude.py`). SIN cambios en el motor externo, `__manifest__.py` ni
  el contrato del widget (salvo el badge aditivo). Turno → Odoo Analista (paso 3: revisar y pasar a `odoo-dev`).
- [2026-10-15 · Odoo Analista] Revisión (paso 3): plan de la Sección 3 **CONFORME** al contrato §3.3
  (D1-D5 cerradas, T1-T10 atómicos y en orden, CA-1..CA-5, restricciones duras, cambios **ADITIVOS** al
  payload del widget). Verificado el punto fino de **D1** contra el widget
  (`static/src/xml/printflow_order_timeline.xml` L98-107: cuando hay `summary` **NO** se pinta el
  `statusLabel` ⇒ la cifra DEBE ir en un badge aditivo nuevo, `shortfall_qty`/`shortfall_label`, no en el
  `statusLabel`). Cierra además el backlog **B2** (listados de OC del producto → solo "sin confirmar").
  Turno → **Odoo Dev**.
- [2026-10-15 · Odoo Dev] Ejecutado T1→T10. Cambios: `printflow_flow_presentation.py`
  (`_PF_NODE_SHORTFALL_LABELS` = {'purchase': 'Faltan comprar'} + `_pf_node_shortfall_label`);
  `printflow_flow_payload_builder.py` (claves ADITIVAS `shortfall_qty`/`shortfall_label` en el nodo);
  `printflow_flow_strategy_product.py` (`shortfall_by_key` = déficit real si `purchase` está `missing`;
  `_pf_root_tray` → solo OC sin confirmar; etiqueta `view_purchase` → "Ver OC sin confirmar");
  `printflow_flow_strategy_order.py` (`_EPS` + `shortfall_by_key` = `line.deficit_qty`; etiqueta
  `view_purchase` paridad); `printflow_flow_pending.py` (`_pf_purchase_unconfirmed_states`, reexporta la
  tupla); `printflow_resolution_playbook.py` (`order_supply_missing` solution → `open_wizard`/`buy_product`,
  "Comprar lo que falta"); `wizard/printflow_product_flow.py` (`_pf_open_purchase_orders` → solo sin
  confirmar + título "N OC sin confirmar del producto"); widget `.js`/`.xml` (badge "Faltan comprar N",
  sin `t-on-click`). Tests: creado `tests/test_flow_compras_deficit_magnitude.py` (CA-1..CA-5) y
  registrado; `BASE_NODE_KEYS` += `shortfall_qty`/`shortfall_label`; actualizados
  `test_diagnostic_levels` y `test_diagnostic_unified_solution` (plan = Compra Rápida; remedio redundante).
  `py_compile` OK. Solo LECTURA; motor externo y `__manifest__.py` intactos.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 para recargar assets JS.
  Turno → **Odoo Verificador**.
- [2026-10-15 · Odoo Verificador] Veredicto **`cumple`**. Evidencia:
  `odoo-bin -d pf_picker_tests -u printflow_gestion_inventario,x_product_dimensional_pricing
  --test-enable --test-tags /printflow_gestion_inventario:<subconjunto> --stop-after-init`
  → **exit 0, 90/90 verdes (0 failed, 0 errors)**: `TestFlowComprasDeficitMagnitude` 7/7 (CA-1..CA-5),
  `TestProductFlowPayloadParity` 8/8, `TestDiagnosticTimelinePayload` 14/14, `TestDiagnosticLevels` 7/7,
  `TestDiagnosticUnifiedSolution` 6/6, `TestFlowCanvasParity` 3/3, `TestDiagnosticNodeActions` 18/18,
  `TestProductFlowCanvas` 8/8, `TestDiagnosticFlowGeometry` 12/12, `TestProductFlowParityPanel` 1/1,
  `TestFlowComprasRecepcionSnapshot` 6/6. Sin `cr.execute`/`cr.commit` en producción; `TransactionCase`
  (rollback); motor externo `x_product_dimensional_pricing` intacto. BD de test `pf_picker_tests` (NO se
  corrió sobre la BD de producción, para no tocar datos). Hallazgos [baja]: (a) §3.10/D5 cita
  `test_node_pending_enumeration` como verde, pero `test_limit_is_per_node` ya era rojo pre-existente
  (B1); (b) el `-u` loguea `External ID not found ... menu_printflow_dashboards/printflow_health_center_*`
  (aviso de carga pre-existente, exit 0); (c) no se corrió la suite completa ⇒ los 8 rojos ajenos (B1)
  no se re-validaron.
- [2026-10-15 · Odoo Analista] Cierre de ciclo (compuerta de convergencia §4.3). Evidencia del
  Verificador aceptada (90/90 verdes, exit 0, `cumple`). T1→T10 marcadas `[x]`. Ficha y Sección 3
  cerradas. Bitácora escrita. **Cierra además el backlog B2** (listados de OC del producto alineados a
  "solo sin confirmar"). **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar los assets JS y ver el badge "Faltan comprar N".
- [2026-10-16 · Odoo Analista] Nueva tarea (GRANDE): **faltante REAL y pedidos por comprar en el nodo
  Compras**. Análisis (BD `Ciber Estudios 2015 RESTAURADA`, producto `IMPRESION BANNER ` id 13571):
  el nodo muestra "Faltan comprar **31**" (= 35 demanda − 4 existencia − 0 en camino) pero **NO
  descuenta 4 OC en borrador** del producto (6 u; de las cuales **5 u** cubren pedidos con entrega
  pendiente: S03253/S03275/S03281). El dueño confirmó la lógica: "las OC en borrador ya tienen su
  venta vinculada (por el `origin`) — solo falta confirmarlas". ⇒ **Faltante real por pedir = 26**
  (la compra rápida debe usar 26 y NO recalcularse; si se compra 31 y se confirman las OC, se
  DUPLICA). Pedidos que requieren compra = 26 (19 sin OC + 7 con OC **ya recibida**; se EXCLUYEN los
  de OC en borrador/por recibir y se INCLUYEN los de OC cancelada o ya recibida, porque su mercancía
  no está). Además: la Compra Rápida debe traer esos pedidos a "Agrupar pedidos" (botón) y mostrar el
  **cliente** en el selector. Escrita la Sección 3 (contrato + D1..D8 + CA-1..CA-6); la tarea anterior
  de magnitud del déficit pasa al **anexo 3.C**. Hallazgos H-004..H-006 registrados. Turno → **Odoo
  Planificador**.
- [2026-10-16 · Odoo Planificador] Plan del **faltante REAL y pedidos por comprar** (Sección 3).
  D1–D8 cerradas: (D1) `faltante_real = max(0, déficit_físico − cobertura_OC_sin_confirmar)`, donde
  cobertura = unidades de OC en `draft/sent/to approve` cuyo `origin` referencia un pedido con entrega
  pendiente del producto (solo Compras; Inventario sin cambios; helper en `printflow.flow.pending`);
  (D2) señal "N OC sin confirmar" reutilizando el badge `pending`/`pending_label` (documentos);
  (D3) congelar la cantidad con `pf_freeze_qty` + override de `_demand_for_product` con `super()`
  (compra normal intacta); (D4) botón `action_pf_import_requiring_orders` con filtro "entrega pendiente
  y sin compra en trámite" (reutiliza `_find_purchase_orders_by_sale_names`); (D5) cliente en el
  selector vía `_compute_display_name` de `sale.order` gateado por contexto; (D6) paridad producto/pedido
  sin claves nuevas; (D7) componentes FUERA; (D8) sin tocar candados existentes + nuevo
  `tests/test_flow_compras_por_comprar.py`. Plan T1–T12 en 4 lotes de 3; único cambio de infraestructura
  deliberado: vista heredada del wizard + `__manifest__.py`. Turno → **Odoo Analista** (paso 3: revisar y
  pasar a `odoo-dev`).
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado.** Archivo: `models/printflow_flow_pending.py`
  (único tocado). Añadido `_EPS = 1e-6` (umbral, mismo del resto de piezas) y TRES helpers `@api.model`
  de SOLO LECTURA en una sección nueva "FALTANTE REAL Y PEDIDOS POR COMPRAR (D1/D4)":
  (T1) `_pf_sale_orders_pending_delivery(product_ids) → {pid: set(names)}` — 1 `search_read` de
  `sale.order.line` (`order_id.state='sale'`, pendiente = `product_uom_qty − qty_delivered > _EPS`) +
  1 lectura batch de `sale.order` (`['name']`) para traducir ids→nombres;
  (T2) `_pf_purchase_unconfirmed_cover(product_ids, sale_order=None) → {pid: float}` — 1 `search_read`
  de `purchase.order.line` (`order_id.state in PURCHASE_UNCONFIRMED_STATES`) + 1 lectura batch del
  `origin` de sus OC; suma `product_qty` cuando el `origin` referencia un pedido con entrega pendiente
  de T1 (o `sale_order.name` si se pasa; paridad D6) tokenizando con la FUENTE ÚNICA
  `printflow.stock.remedy._pf_origin_sale_names`;
  (T3) `_pf_sale_orders_requiring_purchase(product) → sale.order` — candidatos de T1 menos los pedidos
  con compra "EN TRÁMITE" (OC con línea del producto sin confirmar OR confirmada con albarán `incoming`
  abierto; vínculo por `origin` con la FUENTE ÚNICA
  `printflow.purchase.link.mixin._find_purchase_orders_by_sale_names`). Sin N+1 (todo por lote);
  `cr.execute`/`cr.commit` ausentes; motor externo y `__manifest__.py` intactos.
  **Pruebas (BD `pf_picker_tests`, sin `-u`; sintaxis `--test-tags /mod:Clase` repetida):**
  `TestFlowComprasRecepcionSnapshot` 6/6, `TestPendingNativeValidate` 5/5,
  `TestNodePendingEnumeration` 7/8 (único fallo `test_limit_is_per_node`, **rojo pre-existente B1**
  ajeno: límite aplicado en el caller, no en el motor) → 0 fallos/0 errores nuevos; exit 1 solo por B1.
  `py_compile` OK. (Nota: se corrió sin `-u` porque el filestore por defecto bajo `Program Files` da
  `PermissionError`/`ParseError` al recargar datos; Lote 1 no cambia esquema/datos, así que el registry
  cargó el código nuevo en disco sin problema.) **Pendiente del dueño:** reiniciar/actualizar el módulo
  en el servidor 8071 para el lote siguiente. Turno → **Odoo Dev** (Lote 2: T4–T6).
- [2026-10-16 · Odoo Dev] **Lote 2 (T4–T6) ejecutado** (sesión NUEVA; el turno anterior se interrumpió
  dejando parte del código en disco, así que se REVISÓ antes de escribir). Estado encontrado y verificado:
  (T4) `models/printflow_flow_strategy_product.py::_pf_flow_context` ya traía `cover =
  _pf_purchase_unconfirmed_cover([product.id])` + `shortfall = max(0, deficit − cover)` +
  `shortfall_by_key = {'purchase': shortfall}` (early-return sin producto con `{}`); `deficit` crudo intacto.
  (T5) `models/printflow_flow_strategy_order.py::_pf_flow_context` ya traía la paridad (`deficit =
  line.deficit_qty`, `cover`, `shortfall_by_key`). (T6) `models/printflow_quick_purchase_bridge.py` ya
  existía (`_inherit = 'mrp.quick.purchase.wizard'`, `pf_freeze_qty` + `_demand_for_product` con `super()` +
  early-return `0.0`) y registrado en `models/__init__.py` L85. **ÚNICO cambio del turno (bug del lote
  interrumpido):** en T5 el código usaba `sale_order=line.order_id`, pero
  `printflow.order.diagnostic.wizard.line` NO tiene `order_id` → `AttributeError` (23 errores en la 1ª
  corrida). Corregido a `sale_order=host.board_id.sale_order_id` (el pedido enfocado sale del BOARD del
  wizard; misma fuente que el resto del contexto, sin inventar campos). **Pruebas (BD `pf_picker_tests`,
  `--data-dir` a temp escribible porque el filestore bajo `Program Files` da `PermissionError` con `-u`;
  `--test-tags` por clase repetida):** exit **0**, **77/77 verdes (0 failed, 0 errors)** →
  `TestFlowComprasDeficitMagnitude` 7/7, `TestProductFlowPayloadParity` 8/8, `TestFlowCanvasParity` 3/3,
  `TestDiagnosticLevels` 7/7, `TestDiagnosticUnifiedSolution` 6/6, `TestDiagnosticTimelinePayload` 14/14,
  `TestDiagnosticFlowGeometry` 12/12, `TestProductFlowCanvas` 8/8, `TestProductFlowParityPanel` 1/1,
  `TestFlowComprasRecepcionSnapshot` 6/6, `TestQuickPurchaseGrouping` 3/3,
  `TestQuickPurchaseWithoutSaleOrder` 2/2 (compra rápida NORMAL intacta). `py_compile` OK. Solo LECTURA
  (sin `cr.execute`/`cr.commit`); motor externo `x_product_dimensional_pricing` y `__manifest__.py`
  intactos. **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 para recargar el
  campo/override del bridge. Turno → **Odoo Dev** (Lote 3: T7–T9).
- [2026-10-16 · Odoo Dev] **Lote 3 (T7–T9) ejecutado** (sesión NUEVA). Archivos: (T7) MODIFICADO
  `models/printflow_quick_purchase_bridge.py`: +import `_` y método
  `action_pf_import_requiring_orders()` (resuelve el producto de referencia
  `purchase_line_ids[:1].product_id or product_id`, trae los pedidos de la FUENTE ÚNICA
  `printflow.flow.pending._pf_sale_orders_requiring_purchase(product)`, crea solo las filas
  `order_line_ids` que FALTAN comparando por `sale_order_id` (idempotente, sin duplicar) y devuelve
  `act_window res_id=self.id target='new'` para RECARGAR el wizard; solo escribe en el transient).
  (T8) CREADO `models/printflow_sale_order_display.py`: `_inherit='sale.order'` +
  `_compute_display_name` con `super()` y, solo con el contexto `pf_purchase_partner_label`,
  `'%s − %s' % (name, partner)`; sin el contexto queda INTACTO. (T9) CREADO
  `views/printflow_quick_purchase_views.xml` (hereda `x_product_dimensional_pricing.mrp_quick_purchase_wizard_form`;
  `//field[@name='order_line_ids']` `position="before"` → botón `action_pf_import_requiring_orders`
  `invisible="not product_id"`; y `.../tree//field[@name='sale_order_id']` `position="attributes"` →
  `context="{'pf_purchase_partner_label': True}"`; SIN `position="replace"`). MODIFICADO
  `models/__init__.py` (+import del nuevo modelo, sección 15) y `__manifest__.py` (+vista heredada a
  `data`, tras `wizard/printflow_product_flow_views.xml`). **Pruebas (BD `pf_picker_tests`,
  `--data-dir` temporal `pf_data`, `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`):**
  la vista nueva cargó sin error (`loading .../views/printflow_quick_purchase_views.xml`); **599 tests →
  7 failed + 1 error**, EXACTAMENTE el baseline ajeno **B1** (`test_diagnostic_delivery_orders`,
  `test_node_pending_enumeration.test_limit_is_per_node`, `test_phase7_board_permissions`,
  `test_product_flow_failure_negative_reserved`, `test_product_flow_lot_picker_ux`,
  `test_product_flow_lot_tray_ux` ×2, `test_product_flow_solution_single` ERROR) ⇒ **cero fallos
  nuevos**; `TestQuickPurchaseGrouping`/`TestQuickPurchaseWithoutSaleOrder`/`TestQuickPurchaseMultiProvider`
  verdes (compra rápida NORMAL intacta). `py_compile` OK. Solo LECTURA (sin `cr.execute`/`cr.commit`;
  la importación escribe solo en el transient del wizard). Motor externo `x_product_dimensional_pricing`
  intacto. **Observación (fuera de alcance, NO tocada):** Odoo 17 ya trae
  `sale.order._compute_display_name` con su propia clave de contexto (`sale_show_partner_name`, guion
  simple); el diseño D5 usa una clave propia (`pf_purchase_partner_label`, guion largo "−") para no
  acoplarse a la nativa — se respeta el plan. **Pendiente del dueño:** reiniciar/actualizar el módulo
  en el servidor 8071 para recargar assets/vistas. Turno → **Odoo Dev** (Lote 4: T10–T12).
- [2026-10-16 · Odoo Dev] **Lote 4 (T10–T12) ejecutado** (sesión NUEVA). Archivos: (T10) MODIFICADO
  `wizard/printflow_product_flow.py`: nuevo `_pf_purchase_shortfall_qty()` (= `max(0, déficit −
  cobertura de OC sin confirmar) or 1.0`, con la FUENTE ÚNICA
  `printflow.flow.pending._pf_purchase_unconfirmed_cover`; `_pf_deficit_qty` SE CONSERVA para
  OF/componentes, D7); `_pf_open_buy_product` ahora usa el faltante REAL; `_pf_open_quick_purchase`
  añade `product_id` (referencia = 1er producto de la lista) + `pf_freeze_qty: True` al `create()`.
  (T11) MODIFICADO `wizard/printflow_order_diagnostic_failure.py`: paridad del pedido con
  `_pf_purchase_shortfall_qty()` (cover restringido a `board.sale_order_id`) + `product_id`/`pf_freeze_qty`
  en `_pf_open_quick_purchase`. (T12) CREADO `tests/test_flow_compras_por_comprar.py` (CA-1..CA-6) y
  registrado en `tests/__init__.py`. **Dos correcciones dentro del mismo lote (aprendizajes):**
  (a) el test NO puede sacar el déficit de un `sale.order` pseudo-confirmado: `product.outgoing_qty` se
  computa de los MOVIMIENTOS de entrega, no de la línea de venta ⇒ se usa el patrón de la suite
  (existencia negativa para el déficit + pedido pendiente para el vínculo por `origin`);
  (b) CA-5 exige invalidar el caché del campo computado entre lecturas (`invalidate_recordset()`):
  el caché de `display_name` NO es sensible al contexto (mismo cuidado que el nativo
  `sale_show_partner_name`). **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal, `--no-http`;
  `--test-tags`):** exit **0**. Núcleo nuevo: `TestFlowComprasPorComprar` **8/8** (CA-1..CA-6).
  Candados CA-6: `TestFlowCanvasParity` + `TestProductFlowPayloadParity` + `TestFlowComprasDeficitMagnitude`
  + `TestFlowComprasRecepcionSnapshot` + `TestQuickPurchaseGrouping` + `TestQuickPurchaseWithoutSaleOrder`
  → **24/24** verdes (0 failed, 0 errors; compra rápida NORMAL intacta). `py_compile` OK. Solo LECTURA
  (sin `cr.execute`/`cr.commit`; la importación escribe solo en el transient del wizard). Motor externo
  `x_product_dimensional_pricing` intacto. **Pendiente del dueño:** reiniciar/actualizar el módulo en el
  servidor 8071 (`-u printflow_gestion_inventario`) para recargar el código de los wizards. Turno →
  **Odoo Verificador** (verificación final del plan completo).
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia del
  Verificador aceptada: **veredicto `cumple`** — `TestFlowComprasPorComprar` **8/8** (CA-1..CA-6) +
  candados **24/24** verdes (exit 0, 0 failed / 0 errors). T1→T12 marcadas `[x]`; Ficha y Sección 3
  cerradas; hallazgos del Verificador registrados (H-007 `descartado`; los avisos de carga y la no
  re-corrida de la suite completa quedan informativos, cubiertos por H-002/B1). **H-004 pasa a
  `resuelto`** (el faltante real ya descuenta las OC sin confirmar). **Tarea CERRADA.**
  **Pendiente del dueño:** (1) reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar assets/vistas/código y ver: el badge
  "Faltan comprar **26**", el botón **"Traer pedidos"** en la Compra Rápida y el **cliente** en el
  selector de "Agrupar pedidos"; (2) decidir los puntos abiertos **O-1/H-005** (OC P00290 huérfana) y
  **O-2/H-006** (el tablero marca S03215 "delivered" pero sus documentos dicen otra cosa).
- [2026-10-16 · Odoo Dev] **T1 ejecutada (único archivo).** MODIFICADO
  `views/printflow_quick_purchase_views.xml`: (a) el `<button name="action_pf_import_requiring_orders">`
  se **envuelve** en `<div colspan="2" class="mb-2"> … </div>` dentro del
  `<xpath expr="//field[@name='order_line_ids']" position="before">` (mismo patrón de ancho completo de
  la vista base del motor) ⇒ el botón queda en su PROPIA fila, sin compartir celda con la tabla;
  (b) nuevo `<xpath expr="//field[@name='order_line_ids']" position="attributes">` con
  `<attribute name="colspan">2</attribute>` ⇒ la tabla "Agrupar pedidos" recupera el **ancho completo**
  y el selector `sale_order_id` ("número − cliente") vuelve a leerse. Se dejó **INTACTO** el `xpath` del
  contexto `{'pf_purchase_partner_label': True}` del `sale_order_id`; **sin `position="replace"`**; motor,
  bridge, payload, widget y `__manifest__.py` sin tocar; cero CSS nuevo. **Pruebas (BD `pf_picker_tests`,
  `--data-dir` temporal `pf_data`, `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`;
  `--test-tags /printflow_gestion_inventario:TestFlowComprasPorComprar,/x_product_dimensional_pricing:TestQuickPurchaseGrouping,/x_product_dimensional_pricing:TestQuickPurchaseWithoutSaleOrder`):**
  exit **0**, **13/13 verdes (0 failed, 0 errors)** → `TestFlowComprasPorComprar` 8/8 (CA-1..CA-6),
  `TestQuickPurchaseGrouping` 3/3, `TestQuickPurchaseWithoutSaleOrder` 2/2 (compra rápida NORMAL intacta).
  La vista cargó sin error (`loading …/views/printflow_quick_purchase_views.xml`); ningún WARNING/ERROR
  asociado a la vista. Los `External ID not found` del log (`menu_printflow_dashboards` /
  `printflow_health_center_*`) son avisos de carga **pre-existentes** (ya documentados). Solo LECTURA
  (sin `cr.execute`/`cr.commit`). **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor
  8071 (`-u printflow_gestion_inventario`) para recargar la vista y ver el botón en fila completa.
  Turno → **Odoo Analista** (cierre del ciclo: es tarea TRIVIAL; la evidencia de tests del Dev es
  suficiente, no se convoca al Verificador).
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Tarea TRIVIAL:
  se acepta la evidencia del Dev (exit 0, **13/13 verdes**: `TestFlowComprasPorComprar` 8/8,
  `TestQuickPurchaseGrouping` 3/3, `TestQuickPurchaseWithoutSaleOrder` 2/2). Verificado el archivo:
  botón envuelto en `<div colspan="2" class="mb-2">` y `field order_line_ids` con `colspan="2"`;
  `xpath` del contexto `pf_purchase_partner_label` intacto; sin `position="replace"`. T1 marcada `[x]`;
  Ficha y Sección 3 cerradas. **Hallazgo H-008 pasa a `resuelto`.** **Tarea CERRADA.**
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar la vista y ver el botón "Traer pedidos que
  requieren compra" en su propia fila y la tabla "Agrupar pedidos" a ancho completo.
- [2026-10-16 · Odoo Analista] **Nueva tarea (NORMAL): botón "Recalcular" en el diagrama de flujo del
  PRODUCTO (paridad de UX).** El dueño reporta que el diagrama del producto (abierto desde Gestión de
  Inventario) no tiene "Recalcular" y que "el mismo diagrama" desde PrintFlow sí lo tiene. Análisis (BD
  `Ciber Estudios 2015 RESTAURADA`): en todo el sistema solo **DOS** vistas usan el widget
  `printflow_order_timeline` — el diagrama de **PRODUCTO** (`printflow.product.flow`, `ir.ui.view` id
  **12715**, `<form>` SIN `<header>`/`<footer>`) y el diagnóstico del **PEDIDO**
  (`printflow.order.diagnostic.wizard`, `action_recalculate` en el `<footer>`, `..._views.xml` L231).
  El `action_recalculate` existe también en el escáner de producto (`printflow_product_diagnostic_views.xml`
  L18) y en el diagnóstico de BOM kit (L119). ⇒ No es "el mismo diagrama": son **pantallas hermanas**
  que comparten widget; a la del producto le **falta** el botón. Se escribió la Sección 3 (contrato §3.3,
  D1..D5, CA-1..CA-4) y se registró el hallazgo **H-009**. Turno → **Odoo Planificador**.
- [2026-10-16 · Odoo Planificador] **Plan del botón "Recalcular" en el diagrama del PRODUCTO (Sección 3).**
  D1–D5 cerradas: (D1) el botón va en el `<header>` (el diagrama SIEMPRE abre a pantalla completa
  `target='current'`; el `<footer>` solo se pinta en diálogo); (D2) invalida la caché de
  `product.product` (`qty_available`/`outgoing_qty`/`incoming_qty`/`free_qty`/`virtual_available`) +
  `self.invalidate_recordset()` (los compute dependen solo de `product_id`); SIN `clear_caches`
  (verificado: no hay `ormcache` ni en el módulo ni en el motor externo); (D3) recarga el MISMO wizard
  (`act_window`, `res_id=self.id`, `target='current'`); (D4) no hay foco de nodo que preservar;
  (D5) sin claves nuevas en el payload ⇒ candados intactos. Plan **T1–T3 en un solo lote** (≤3):
  1 método (`action_recalculate`) + 1 vista (`<header>`) + 1 test. Turno → **Odoo Analista** (paso 3:
  revisar y pasar a Odoo Tech).
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** (sesión NUEVA; el plan es de un solo lote).
  Archivos: (T1) MODIFICADO `wizard/printflow_product_flow.py`: sección NUEVA
  "ACCIONES (recómputo solo lectura)" entre CÓMPUTOS y CONTEXTO DEL CANVAS con `action_recalculate()`
  (`ensure_one`; si no hay `product_id` cierra; invalida la caché de `product.product` para
  `qty_available`/`outgoing_qty`/`incoming_qty`/`free_qty`/`virtual_available` + `self.invalidate_recordset()`
  y devuelve el `act_window` que recarga el MISMO registro a `target='current'`; solo LECTURA, `invalidate_*`
  es caché en memoria, nunca escritura). (T2) MODIFICADO `wizard/printflow_product_flow_views.xml`:
  `<header>` como PRIMER hijo de `<form>` y antes de `<sheet>` con el botón `action_recalculate`
  ("Recalcular", `class="btn-secondary"`, `icon="fa-refresh"`, title "Volver a calcular el diagnóstico con
  los datos actuales"); resto de la vista INTACTO (button_box, h1, group, `timeline_json`, leyenda y franja
  de cadena); `__manifest__.py` **SIN cambios**. (T3) CREADO `tests/test_product_flow_recalculate.py`
  (CA-1..CA-4) y registrado en `tests/__init__.py`. **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal,
  `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`; `--test-tags` por clase
  repetida):** exit **0**, **56/56 verdes (0 failed, 0 errors)** → `TestProductFlowRecalculate` **5/5**
  (CA-1..CA-4), `TestProductFlowCanvas` 8/8, `TestProductFlowCanvasControls` 3/3,
  `TestProductFlowPayloadParity` 8/8, `TestProductFlowActions` 8/8, `TestFlowCanvasParity` 3/3,
  `TestDiagnosticTimelinePayload` 14/14, `TestProductFlowProductionSignals` 7/7. `py_compile` OK. Solo
  LECTURA (sin `cr.execute`/`cr.commit`); motor externo `x_product_dimensional_pricing`, builder, widget y
  estrategia `.order` intactos. **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar la vista y ver el botón "Recalcular" en el diagrama del
  producto. Turno → **Odoo Verificador** (verificación final del plan completo).
- [2026-10-16 · Odoo Verificador] Veredicto **`cumple`** (verificación LIGERA, una pasada). Sin
  `git diff` de referencia (repo sin commits ⇒ baseline inexistente, ya documentado en H-002): la
  verificación de alcance se hizo por **lectura directa** de los 4 archivos + la evidencia de tests del
  Dev. Contraste con la Sección 3: **T1** `action_recalculate()` vive en la sección nueva "ACCIONES
  (recómputo solo lectura)" (`wizard/printflow_product_flow.py` L148-177), invalida
  `product.product` (`qty_available`/`outgoing_qty`/`incoming_qty`/`free_qty`/`virtual_available`) +
  `self.invalidate_recordset()` y devuelve `act_window` (`res_model=self._name`, `res_id=self.id`,
  `view_mode='form'`, `target='current'`), **sin recrear** el wizard; **T2** `<header>` como primer
  hijo de `<form>` con el botón `action_recalculate` ("Recalcular", `btn-secondary`, `fa-refresh`, title
  pedido), resto de la vista INTACTO; **T3** `tests/test_product_flow_recalculate.py` (CA-1..CA-4)
  registrado en `tests/__init__.py`. Flujos **no forzados**: `action_recalculate` NO escribe (solo suelta
  caché en memoria); sin `cr.execute`/`cr.commit` en producción; `TransactionCase` (rollback). **No
  re-corre la suite** (modo ligero: la evidencia del Dev es completa y nada huele mal). Hallazgos [baja]:
  (a) el test muta existencias con `stock.quant._update_available_quantity` para fabricar el cambio de
  fuente —aceptable dentro de `TransactionCase` (rollback); patrón de test intensivo en stock— (H-010);
  (b) ausencia de baseline git (cubierto por H-002).
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia del
  Verificador aceptada: **veredicto `cumple`**; Dev exit 0, **56/56 verdes (0 failed, 0 errors)** →
  `TestProductFlowRecalculate` **5/5** (CA-1..CA-4), `TestProductFlowCanvas` 8/8,
  `TestProductFlowCanvasControls` 3/3, `TestProductFlowPayloadParity` 8/8, `TestProductFlowActions` 8/8,
  `TestFlowCanvasParity` 3/3, `TestDiagnosticTimelinePayload` 14/14,
  `TestProductFlowProductionSignals` 7/7. T1→T3 marcadas `[x]` por el Dev (0 pendientes). Ficha y
  Sección 3 cerradas. **Hallazgo H-009 pasa a `resuelto`**; se registra **H-010** (patrón de test en
  stock, `descartado`). **Tarea CERRADA.** Motor `x_product_dimensional_pricing`, builder, widget,
  payload y estrategia `.order` intactos; `__manifest__.py` sin cambios.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar la vista y ver el botón **"Recalcular"** en el
  diagrama de flujo del producto (abierto desde Salud de Inventario → Productos → clic en el producto).
- [2026-10-16 · Odoo Analista] **Nueva tarea (GRANDE): el lote de la Compra Rápida no viaja a la OC ni
  al albarán.** Reporte del dueño verificado POR DATOS (BD `Ciber Estudios 2015 RESTAURADA`): producto
  `IMPRESION BANNER ` (id 13571, `tracking='lot'`); wizard Compra Rápida **638** (línea **762**,
  `lot_name="LOTE-000001"`, `material_received=False`, `pf_freeze_qty=True`) → OC **P01807** (id 1818,
  `state=purchase`) → albarán **WH/IN/00578** (picking 40565, `assigned`, **sin lote**): `stock.move`
  127860 `lot_ids=[]`, `stock.move.line` 94861 `lot_id=false`, y **no existe** `stock.lot`
  "LOTE-000001". Causa raíz: el lote solo se materializa en
  `x_product_dimensional_pricing/wizard/mrp_quick_purchase_wizard.py::_validate_incoming_pickings()`
  (L703-719), que corre **solo si `line.material_received=True`**; PrintFlow abre la Compra Rápida con
  `material_received=False` a propósito ("abrir ≠ ejecutar", `wizard/printflow_product_flow.py` L741-773,
  L761) ⇒ el albarán queda abierto y el lote nunca se persiste en la compra/entrada (el `pf_lot_name`
  solo se escribe en los `sale.order`, L416-418). Registrado el hallazgo **H-011**. Escrita la Sección 3
  (contrato §3.3, D1..D6 a cerrar por el Planificador, CA-1..CA-4); la tarea anterior "Recalcular" pasa
  al **anexo 3.F**. Turno → **Odoo Planificador**.
- [2026-10-16 · Odoo Analista] **Revisión (paso 3): plan CONFORME.** D1–D6 cerradas reutilizando primitivas
  NATIVAS (`button_confirm`, `action_assign`, `_get_or_create_lot`); fix **100 % en PrintFlow** (`_inherit` +
  `super()`; motor `x_product_dimensional_pricing` intacto); **GATE** `pf_freeze_qty` para no romper la Compra
  Rápida normal ni la recepción automática; PROHIBIDO `button_validate` desde el fix ("abrir ≠ ejecutar").
  Plan T1–T4 en 2 lotes; CA-1..CA-4 verificables. Turno → **Odoo Tech (Dev)** (Lote 1: T1–T3).

- [2026-10-16 · Odoo Planificador] **Plan del lote de la Compra Rápida (Sección 3).** D1–D6 cerradas:
  (D1) se persiste el NOMBRE en un campo NUEVO y ADITIVO `pf_lot_name` de `purchase.order` (espejo de
  `sale.order.pf_lot_name`); el `stock.lot` se materializa idempotentemente al PRELLENAR la entrada
  (reutiliza `mrp.production._get_or_create_lot`), NO al confirmar; (D2) el prellenado es NATIVO: en
  `purchase.order.button_confirm` (`_inherit` + `super()`) se hace `picking.action_assign()` y se escribe
  `lot_id`+`lot_name` en las `stock.move.line` de la entrada (mismo patrón de `_validate_incoming_pickings`),
  SIN `button_validate` ("abrir ≠ ejecutar"); (D3) el fix vive **100 % en PrintFlow** (`_inherit` sobre
  `purchase.order` y `mrp.quick.purchase.wizard.line`; reutiliza el helper del motor) ⇒ NO se toca
  `x_product_dimensional_pricing` y no hace falta autorización del dueño para tocar el motor;
  (D4) una línea = una OC = un lote, sin N+1; (D5) **GATE** `pf_freeze_qty` ⇒ la Compra Rápida normal y la
  recepción automática quedan intactas (cambios ADITIVOS); (D6) la OC P01807/WH/IN/00578 se deja como
  validación manual (lote previsto `LOTE-000001`), NO se corrige por datos. Archivos: **CREAR**
  `models/purchase_order.py` (campo + `button_confirm` + `_pf_prefill_incoming_lot`), **MODIFICAR**
  `models/printflow_quick_purchase_bridge.py` (clase `mrp.quick.purchase.wizard.line` con
  `_create_purchase_order`), **MODIFICAR** `models/__init__.py` (import), **CREAR**
  `tests/test_quick_purchase_lot_tracking.py` (CA-1..CA-4). Plan **T1–T4 en 2 lotes**. SIN cambios: motor
  `x_product_dimensional_pricing`, wizards de PrintFlow, vista/widget, `__manifest__.py`. Turno →
  **Odoo Analista** (paso 3: revisar y pasar a `odoo-dev`).
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** (sesión NUEVA). Archivos: (T1) CREADO
  `models/purchase_order.py`: `_inherit = 'purchase.order'` con campo ADITIVO `pf_lot_name` (Char, espejo de
  `sale.order.pf_lot_name`), override `button_confirm()` (`res = super().button_confirm();
  self._pf_prefill_incoming_lot(); return res`) y `_pf_prefill_incoming_lot()` (para cada OC con
  `pf_lot_name`: `picking.action_assign()` sobre las entradas abiertas y escritura de `lot_id`/`lot_name` en
  las `stock.move.line` del producto por lote SIN lote; el `stock.lot` se materializa idempotentemente con el
  helper canónico `mrp.production._get_or_create_lot`; **SIN** `button_validate`). (T2) MODIFICADO
  `models/printflow_quick_purchase_bridge.py`: clase NUEVA `MrpQuickPurchaseWizardLine`
  (`_inherit = 'mrp.quick.purchase.wizard.line'`) con override `_create_purchase_order()` que, con el **GATE**
  `self.wizard_id.pf_freeze_qty` + `product_id.tracking == 'lot'` + `lot_name`, escribe
  `po.pf_lot_name = self.lot_name` (compra rápida normal INTACTA); + bullet en el docstring del módulo. (T3)
  MODIFICADO `models/__init__.py`: `from . import purchase_order` al final (sección 16). SIN cambios: motor
  `x_product_dimensional_pricing`, wizards de PrintFlow, vista/widget, `__manifest__.py`. Solo LECTURA de datos
  ajenos (sin `cr.execute`/`cr.commit`; las escrituras son las propias del flujo: crear el lote pedido y
  prellenar la move line). **Pruebas (BD de test `pf_picker_tests`, `--data-dir` temporal, `--no-http`;
  `-u printflow_gestion_inventario,x_product_dimensional_pricing`; `--test-tags` por clase):** exit **0**,
  **32/32 verdes (0 failed, 0 errors)** → `TestFlowComprasPorComprar` + `TestFlowComprasDeficitMagnitude` +
  `TestFlowComprasRecepcionSnapshot` (PrintFlow) y `TestQuickPurchaseGrouping` +
  `TestQuickPurchaseWithoutSaleOrder` + `TestQuickPurchaseMultiProvider` (motor; compra rápida NORMAL
  intacta). El modelo nuevo cargó sin error (`loading .../views/printflow_quick_purchase_views.xml`); los
  `External ID not found` del log (`menu_printflow_dashboards` / `printflow_health_center_*`) son avisos de
  carga **pre-existentes**. `py_compile` OK. **Pendiente del dueño:** reiniciar/actualizar el módulo en el
  servidor 8071 (`-u printflow_gestion_inventario`) para recargar el campo/override. Turno → **Odoo Dev**
  (Lote 2: T4 — test que fija CA-1..CA-4).
- [2026-10-16 · Odoo Dev] **Lote 2 (T4) ejecutado** (sesión NUEVA; con este lote queda COMPLETO el plan T1–T4).
  Archivos: **CREADO** `tests/test_quick_purchase_lot_tracking.py` (`TransactionCase`, 6 tests) y **MODIFICADO**
  `tests/__init__.py` (registro del nuevo test, junto al bloque de Compras). El test custodia CA-1..CA-4 SIN tocar
  código de producción: (CA-1) abrir la Compra Rápida estilo PrintFlow (`pf_freeze_qty=True`, línea
  `material_received=False`, `lot_name='LOTE-TEST'`) → `action_confirm()` → la OC trae `pf_lot_name == 'LOTE-TEST'`;
  (CA-2) el albarán de entrada ABIERTO trae el lote PRE-RELLENADO en su `stock.move.line` (`lot_id.name ==
  'LOTE-TEST'`) y el `stock.lot` existe, y el albarán sigue ABIERTO ("abrir ≠ ejecutar"); (CA-3) compra Rápida
  NORMAL sin `pf_freeze_qty` → `pf_lot_name == False` y move lines sin lote; recepción AUTOMÁTICA
  (`material_received=True`, wizard normal) → el albarán se valida (`state == 'done'`) y la OC no lleva
  `pf_lot_name`; (CA-4) sin `cr.execute`/`cr.commit` en los archivos tocados + motor externo
  `x_product_dimensional_pricing` intacto (no conoce `pf_freeze_qty`; conserva sus helpers canónicos
  `_get_or_create_lot`/`_validate_incoming_pickings`). **Aprendizaje (corrección dentro del mismo lote):** la 1ª
  corrida falló en `test_ca4_external_motor_untouched` porque el motor YA contiene `pf_lot_name` (lo usa para el
  lado VENTA en `_link_existing_lot`); se ajustó la aserción a la marca que SÍ es de PrintFlow (`pf_freeze_qty`) +
  presencia de los helpers. **Pruebas (BD de test `pf_picker_tests`, `--data-dir` temporal, `--no-http`;
  `--test-tags` por clase):** exit **0**, **11/11 verdes (0 failed, 0 errors)** → `TestQuickPurchaseLotTracking`
  **6/6** (CA-1..CA-4) + `TestQuickPurchaseGrouping` **3/3** + `TestQuickPurchaseWithoutSaleOrder` **2/2** (compra
  rápida NORMAL intacta). `py_compile` OK. `TransactionCase` (rollback); sin `cr.execute`/`cr.commit`; motor
  externo intacto; `__manifest__.py` sin cambios. Los `External ID not found`/`View error context` del log son
  avisos de carga **pre-existentes** (ya documentados). **Plan T1–T4 COMPLETO (2/2 lotes).** Turno →
  **Odoo Verificador** (verificación final del plan completo).
- [2026-10-16 · Odoo Verificador] Veredicto **`cumple`** (verificación LIGERA, una pasada). Contraste T1–T4
  por **lectura directa** de los 4 archivos (sin `git diff` de referencia: repo sin commits ⇒ baseline
  inexistente, cubierto por H-002): T1 `models/purchase_order.py` (campo ADITIVO `pf_lot_name` + override
  `button_confirm` → `_pf_prefill_incoming_lot`, L41-79, que hace `action_assign()` y escribe
  `lot_id`/`lot_name` en las move lines sin lote materializando con `mrp.production._get_or_create_lot`,
  **sin** `button_validate`); T2 `printflow_quick_purchase_bridge.py::MrpQuickPurchaseWizardLine`
  (`_create_purchase_order` con GATE `pf_freeze_qty`); T3 `models/__init__.py` (import, sección 16); T4
  `tests/test_quick_purchase_lot_tracking.py` (CA-1..CA-4) registrado. Flujos no forzados: los 2 archivos de
  producción NO contienen `cr.execute`/`cr.commit`/`button_validate`/`_action_done`/`stock.quant`; el orden
  motor→PrintFlow es correcto (`_create_purchase_order` persiste ANTES de `button_confirm()` prellenа). Motor
  externo no tocado (mtime 01/10/2026). Hallazgos [baja]: (a) escribe `lot_name` además de `lot_id`
  (intencional, D2) → **H-012 `descartado`**; (b) sin baseline git (cubierto por H-002).
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia del Verificador
  aceptada: **veredicto `cumple`**; Dev exit 0, **43/43 verdes** (Lote 1: 32/32; Lote 2: 11/11 —
  `TestQuickPurchaseLotTracking` 6/6 CA-1..CA-4 + `TestQuickPurchaseGrouping` 3/3 +
  `TestQuickPurchaseWithoutSaleOrder` 2/2). T1→T4 marcadas `[x]` (0 pendientes); Ficha y Sección 3 cerradas.
  **Hallazgo H-011 pasa a `resuelto`**; se registra **H-012** (`descartado`). **Tarea CERRADA.** Motor
  `x_product_dimensional_pricing` intacto (solo heredado/reutilizado); `__manifest__.py` sin cambios.
  **Pendiente del dueño:** (1) reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar el código (`models/purchase_order.py` + el bridge);
  (2) el dato YA creado (OC **P01807** / albarán **WH/IN/00578**) quedó sin lote por la regla
  *código sí, datos no*: al validarlo, el operador teclea/crea el lote previsto **`LOTE-000001`** una sola vez
  (guía de D6); las PRÓXIMAS compras rápidas ya nacerán con el lote prellenado.
- [2026-10-16 · Odoo Analista] **Nueva tarea (GRANDE): el albarán de entrada WH/IN/00578 no se puede validar.**
  El dueño reporta que asignó un lote a la línea y al validar salta *"Operación no válida — No se puede modificar
  una ficha finalizada, cancelada o archivada."*. Verificado POR LOG (`odoo.log`, 16/10 07:27:00: `WARNING
  odoo.http: No se puede modificar una ficha finalizada, cancelada o archivada.`) y por BD. Causa raíz
  (**pre-existente del MOTOR** `x_product_dimensional_pricing`, `stock_picking.py` mtime 02/10/2026):
  `stock.picking.button_validate` → `_technical_sheet_invalidate_on_receive()` (L95-127) recalcula las fichas
  técnicas de los pedidos del `origin` de la OC (32 pedidos S…) y entre ellas hay fichas en estado **terminal**
  (`archived_delivered`: S03349 id1000, S06581 id2033). El cómputo `_compute_state_from_docs` (`mrp_technical_sheet_state.py`
  L293-299) asigna `is_partial_fabrication` (compute+store, **no** en `_PRINTFLOW_TECHNICAL_WRITE_FIELDS`) sobre
  TODAS las fichas, incluidas las bloqueadas ⇒ el candado `mrp_technical_sheet_crud.write()` L90-92 lanza el
  `UserError`. El hook NO pasa `bypass_sheet_write_lock`/`printflow_sync` (a diferencia de `printflow_recompute_states`).
  **El `lot_name="12569"` lo tecleó el usuario** (uid 2, 07:25:13) — el sistema NO genera lotes aleatorios (O-1).
  Registrado el hallazgo **H-013**. Escrita la Sección 3 (contrato §3.3, D1..D5 a cerrar por el Planificador,
  CA-1..CA-3); la tarea del lote de la Compra Rápida pasa al **anexo 3.G**. Turno → **Odoo Planificador**.
- [2026-10-16 · Odoo Analista] **Revisión (paso 3): plan CONFORME.** D1–D5 cerradas; se elige la opción (c)
  **100 % PrintFlow** (extender la whitelist del candado vía `_inherit` + `super()`, SIN tocar el motor) ⇒
  no requiere autorización del dueño (D2). NO usa `bypass_sheet_write_lock` (candado estricto por campo);
  cubre recepción Y entrega con un solo cambio (D4); cambios ADITIVOS que preservan el candado de test del
  motor (D5). Plan T1–T3 en **un solo lote** (≤3). Turno → **Odoo Tech (Dev)**.
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** (sesión NUEVA; el plan es de un solo lote).
  Archivos: (T1) **CREADO** `models/mrp_technical_sheet.py`: `_inherit = 'mrp.technical.sheet'` con el
  atributo ADITIVO `_PF_TERMINAL_EXTRA_WRITE_FIELDS = frozenset({'is_partial_fabrication'})` y el override
  del método-seam `_printflow_skip_terminal_write_lock` (`super()` + `bool(vals) and
  set(vals).issubset(self._PF_TERMINAL_EXTRA_WRITE_FIELDS)`); NO reimplementa `write` ni el cómputo y NO
  toca el motor. (T2) **MODIFICADO** `models/__init__.py` (sección 17: `from . import mrp_technical_sheet`
  con comentario del motivo). (T3) **CREADO** `tests/test_technical_sheet_terminal_lock.py` (CA-1..CA-4,
  `TransactionCase`) y **MODIFICADO** `tests/__init__.py` (registro). `py_compile` OK.
  **Pruebas (BD de test `pf_picker_tests`, `--data-dir` temporal, `--no-http`;
  `-u printflow_gestion_inventario,x_product_dimensional_pricing`; `--test-tags` por clase):** exit **0**,
  **11/11 verdes (0 failed, 0 errors)** → `TestTechnicalSheetTerminalLock` **5/5** (CA-1..CA-4) +
  `TestTechnicalSheetRefactorParity` **6/6** (candado del motor intacto, D5).
  **Verificación de fuerza del test:** se desactivó temporalmente el set aditivo del override y la corrida
  reprodujo el bug (CA-1/CA-2/CA-3 → `UserError: No se puede modificar una ficha finalizada, cancelada o
  archivada.`; CA-4 → falla por whitelist no extendida) ⇒ el test SÍ custodia el arreglo; el override se
  restauró y la corrida final volvió a exit 0, 11/11. Solo LECTURA de datos ajenos (sin `cr.execute`/
  `cr.commit`); motor `x_product_dimensional_pricing` y `__manifest__.py` intactos.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u
  printflow_gestion_inventario`) para recargar el código. Turno → **Odoo Verificador** (verificación final
  del plan completo: T1–T3 en un solo lote ⇒ plan completo).
- [2026-10-16 · Odoo Verificador] Veredicto **`cumple`** (verificación LIGERA, una pasada). Contraste por
  **lectura directa**: **T1** `models/mrp_technical_sheet.py` (`_inherit = 'mrp.technical.sheet'`; atributo
  aditivo `_PF_TERMINAL_EXTRA_WRITE_FIELDS = frozenset({'is_partial_fabrication'})` + override del método-seam
  `_printflow_skip_terminal_write_lock` con `super()` + set propio, L46-58; no reimplementa `write` ni el
  cómputo); **T2** `models/__init__.py` (sección 17, `from . import mrp_technical_sheet`); **T3**
  `tests/test_technical_sheet_terminal_lock.py` (CA-1..CA-4) registrado. **Motor intacto** (el override es
  aditivo; `_printflow_skip_terminal_write_lock` y `_PRINTFLOW_TECHNICAL_WRITE_FIELDS` del motor sin cambios;
  `stock_picking.py` mtime 02/10/2026, sheet files 2019 ⇒ no tocados). Flujos no forzados: el archivo nuevo sin
  `cr.execute(`/`cr.commit(`, no importa `wizard/`, no escribe `stock.quant`/`stock.move`/estados; solo habilita
  UN campo compute+store readonly en el candado. Evidencia de tests con **control negativo** (desactivar el set
  reproduce el `UserError`; restaurar → verde). Hallazgos [baja]: (a) CA-3 usa `stock.quant._update_available_quantity`
  para el setup (patrón de test, `TransactionCase`) → **H-014 `descartado`** (mismo caso que H-010); (b) sin
  baseline git (cubierto por H-002). **No re-corre la suite** (modo ligero).
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia del Verificador
  aceptada: **veredicto `cumple`**; Dev exit 0, **11/11 verdes** → `TestTechnicalSheetTerminalLock` **5/5**
  (CA-1..CA-4) + `TestTechnicalSheetRefactorParity` **6/6** (candado del motor intacto). T1→T3 marcadas `[x]`
  (0 pendientes); Ficha y Sección 3 cerradas. **Hallazgo H-013 pasa a `resuelto`**; se registra **H-014**
  (`descartado`). **Tarea CERRADA.** Motor `x_product_dimensional_pricing` intacto (solo heredado/extendido);
  `__manifest__.py` sin cambios. **Pendiente del dueño:** (1) reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar el código; (2) con el fix cargado, el albarán **WH/IN/00578**
  ya se podrá validar (el operador decide cuánto recibir; el `lot_name="12569"` de la línea lo tecleó él y puede
  ajustarlo).
- [2026-10-16 · Odoo Analista] **Sesión de análisis de datos (consultas del dueño) + apertura de tarea (GRANDE).**
  Cadena de consultas sobre el producto `IMPRESION BANNER ` (id 13571, `tracking='lot'`, `x_is_printflow_managed`,
  `pf_purchase_on_order`) resueltas POR DATOS (BD `Ciber Estudios 2015 RESTAURADA`): (1) el nodo Compras mostraba
  "Faltan comprar 31" sin descontar las OC en borrador → **H-004** (ya resuelto en el anexo 3.D); (2) tras confirmar
  el dueño las 4 OC (P00290/P00295/P00297/P00300) el déficit quedó en 0 (34 existencia vs 34 demanda) pero el nodo
  Compras seguía sin cifra → **H-015**; (3) el badge "28 por entregar" convivía con una lista de **1** entrega (dos
  acciones con dominios distintos: `_pf_node_pending_domain` vs `_pf_open_delivery_orders`) → **H-016**; (4) la
  entrega **WH/OUT/02974** reservaba el lote vacío `dwqdqwd` (0 existencia) → **H-017**; (5) las **28** entregas
  quedaron **sin lote** (0 `move_line`; el flujo exige el lote EXCLUSIVO del pedido, `SXXXXX-Lyyyy`, vacío) → **H-018**;
  (6) el dueño preguntó por la superficie guiada que usó con **FONDO NEGRO** → identificada como la **bandeja guiada
  de fallas** (`printflow.flow.failure.tray`), que SOLO cubre `lot_orphan_reservation` y `data_anomaly` (FONDO NEGRO);
  el caso del banner es `lot_no_stock` y NO está en el registro → **H-019** y **Sección 3**. Se movió la tarea del
  candado de fichas al **anexo 3.H**. Clasificación **GRANDE** (toca el flujo de inventario/entregas).
  Turno → **Odoo Planificador**.
- [2026-10-16 · Odoo Planificador] **Plan de la bandeja guiada de fallas para `lot_no_stock` (Sección 3).** Decisiones D1-D6 cerradas: (D1) se crea una falla NUEVA `printflow.flow.failure.lot.no.stock` (NO se reutiliza `over.reservation`: evidencia y saneo distintos); (D2) alcance mínimo: SOLO `lot_no_stock` entra a la guiada; el resto de estados de lote conserva la bandeja clásica como fallback (la paridad del PEDIDO queda intacta: `_pf_open_registered_failure_tray` excluye lote); (D3) evidencias = UNA fila por lote sin existencia (`no_stock_lot_ids`, filtradas por excepciones AUTORIZADAS) y acciones reutilizando saneo EXISTENTE: `reassign` (principal, `_pf_reassign_by_lot`, guardia `_pf_assert_can_clean`), `view_supporting_moves` (navigate) y `leave`; (D4) NO se crea/activa `pf_failure_guided_tray` (basta la clave con `product_id` explícito que la fila del panel ya envía); (D5) `pf_lot_missing_action` FUERA; (D6) SIN modificar candados (los existentes abren la clásica con 2 args) + 1 test NUEVO `tests/test_product_flow_failure_lot_no_stock.py` (CA-1..CA-4). Archivos: **CREAR** `models/printflow_flow_failure_lot_no_stock.py`; **MODIFICAR** `models/printflow_flow_failure_registry.py` (mapa `'lot_no_stock'`) y `models/__init__.py` (import, sección 2d); **CREAR** el test. Plan **T1-T4 en 2 lotes** (Lote 1: T1-T3; Lote 2: T4). SIN cambios: motor `x_product_dimensional_pricing`, bandeja guiada (contrato/vistas/widget), bandeja clásica, casos huérfana/`data_anomaly`, `__manifest__.py` y `security/`. Turno -> **Odoo Analista** (paso 3: revisar y delegar el Lote 1 a `odoo-dev`).
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** (sesión NUEVA). Archivos: (T1) **CREADO** `models/printflow_flow_failure_lot_no_stock.py`: `AbstractModel` (`_name='printflow.flow.failure.lot.no.stock'`, `_inherit='printflow.flow.failure'`) con docstring de módulo del "por qué"; identidad/detección (`_pf_fault_code='lot_no_stock'`; `_pf_fault_detect` delega en `printflow.stock.health._pf_lot_state` + adaptador `printflow.finding.exception.filter._pf_apply_to_lot_info`, filtro `tracking=='lot'` y estado `lot_no_stock`); presentación (`severity='danger'`, summary, 3 pasos); **evidencias = UNA fila por lote** de `no_stock_lot_ids` usando SOLO campos del contrato de la línea (para no romper el `dict(row, …)` del `create`) y dos lecturas SIN N+1 (`_pf_lot_facts`: una `search_read` de quants internos → físico/reservado; `_pf_move_lines_for_lots` + `_pf_support_map`: una búsqueda de move lines activas → respaldo, documentos y ubicación); `res_model='stock.lot'`; acciones `reassign` (execute, primary) / `view_supporting_moves` (navigate) / `leave` (close); ejecución `_pf_fault_execute('reassign')` REUTILIZA el saneo EXISTENTE `printflow.stock.health._pf_reassign_by_lot` con la guardia EXISTENTE `printflow.stock.remedy._pf_assert_can_clean` (+ bitácora `message_post`); sin `cr.execute`/`cr.commit`; NO toca el motor. (T2) **MODIFICADO** `models/printflow_flow_failure_registry.py`: línea ADITIVA `'lot_no_stock': 'printflow.flow.failure.lot.no.stock'` en `_pf_registry()` (resto del mapa y `_pf_failure_for`/`_pf_supported`/`_pf_guided_tray_forced` INTACTOS). (T3) **MODIFICADO** `models/__init__.py`: `from . import printflow_flow_failure_lot_no_stock` tras `printflow_flow_failure_over_reservation` (sección 2d). `models/` no importa `wizard/`. `py_compile` OK en los 3 archivos. **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal `pf_data`, `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`; `--test-tags` por clase):** exit **1** con **65/68 verdes (3 failed, 0 errors)**. Los 3 fallos son EL baseline ajeno **B1** (rojos pre-existentes): `TestProductFlowFailureNegativeReserved.test_negative_reserved_rises_to_support` (causa `lot_orphan_reservation`, ajena), `TestProductFlowLotTrayUx.test_tray_exposes_lot_quantities` (bandeja CLÁSICA, `3.0 != 5.0`) y `TestProductFlowLotTrayUx.test_tree_exposes_document_and_conditional_quantities` (bandeja CLÁSICA, `4 != 3`). **Control negativo:** se repitieron los 3 tests con la línea del registry TEMPORALMENTE comentada → **exactamente los mismos 3 fallos** ⇒ NO los causa este lote (pre-existentes). Verde: `TestProductFlowFailureRegistry`, `TestProductFlowFailureTrayGeneric`, `TestProductFlowFailureOverReservation`, `TestProductFlowFailureOrphanReconcile`, `TestProductFlowFailurePermissionsSplit`, `TestProductFlowLotActions`, `TestProductFlowLotTray`, `TestProductFlowLotTrayDocument`, `TestProductFlowSupplyTray`. SIN cambios: motor `x_product_dimensional_pricing`, bandeja guiada (contrato/vistas/widget), bandeja clásica, casos huérfana/`data_anomaly`, `__manifest__.py` y `security/`. **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`) para registrar la nueva falla. Turno → **Odoo Dev** (Lote 2: T4 — test que fija CA-1..CA-4).
- [2026-10-16 · Odoo Dev] **Lote 2 (T4) ejecutado** (sesión NUEVA; con este lote queda COMPLETO el plan T1–T4).
  Archivos: **CREADO** `tests/test_product_flow_failure_lot_no_stock.py` (`TransactionCase`, 9 tests: CA-1..CA-4) y
  **MODIFICADO** `tests/__init__.py` (registro del nuevo test, junto a las fallas guiadas). El test custodia CA-1..CA-4
  SIN tocar código de producción: (CA-1) `action_run_pf_plan('lot_no_stock', 'solution', product.id)` (3 args) abre
  `printflow.flow.failure.tray`, y la MISMA llamada de 2 args sigue abriendo `printflow.flow.lot.tray` (fallback clásico
  INTACTO); (CA-2) `_pf_populate(None, 'lot_no_stock', product)` trae UNA fila por lote sin existencia con
  `res_model='stock.lot'` y las acciones `reassign` (execute, principal), `view_supporting_moves` (navigate) y `leave`
  (close); `action_run(line.id, 'reassign')` devuelve `display_notification` (saneo EXISTENTE, sin excepción) y una clave
  desconocida cierra; (CA-3) el registry sigue resolviendo `lot_orphan_reservation` -> `printflow.flow.failure.lot.orphan`
  y `data_anomaly` -> `printflow.flow.failure.over.reservation`, `_pf_supported()` contiene los TRES códigos y la guiada
  de la huérfana sigue abriendo (3 args); (CA-4) `TransactionCase` (rollback), el archivo nuevo sin `cr.execute(`/
  `cr.commit(` (leído desde `get_module_path`) y la falla REUTILIZA las primitivas EXISTENTES del motor
  (`printflow.stock.health._pf_reassign_by_lot` / `printflow.stock.remedy._pf_assert_can_clean`). Escenario del lote sin
  existencia = patrón de `test_product_flow_lot_actions.py` (lote REAL con stock + albarán de salida que retiene un lote
  FANTASMA sin existencia); la huérfana = patrón de `test_product_flow_failure_tray_generic.py`. **Pruebas (BD de test
  `pf_picker_tests`, `--data-dir` temporal, `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`;
  `--test-tags` por clase):** exit **0**, **41/41 verdes (0 failed, 0 errors)** -> `TestProductFlowFailureLotNoStock`
  **9/9** (CA-1..CA-4) + `TestProductFlowFailureRegistry` + `TestProductFlowFailureTrayGeneric` +
  `TestProductFlowFailureOverReservation` + `TestProductFlowLotActions` + `TestProductFlowLotTray` (candados: los dos
  casos previos y el fallback clásico INTACTOS). Los `External ID not found` del log (`menu_printflow_dashboards` /
  `printflow_health_center_*`) son avisos de carga **pre-existentes** (ya documentados). Solo LECTURA de datos ajenos
  (sin `cr.execute`/`cr.commit`; la acción `reassign` es saneo propio dentro de `TransactionCase`). Motor externo
  `x_product_dimensional_pricing`, bandeja guiada, bandeja clásica y `__manifest__.py` intactos. **Plan T1–T4 COMPLETO
  (2/2 lotes).** **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para registrar la nueva falla. Turno → **Odoo Verificador**.
- [2026-10-16 · Odoo Verificador] Veredicto **`cumple`** (verificación LIGERA, una pasada). Contraste T1–T4 por
  **lectura directa** de los 4 archivos + **corrida acotada de cierre**: `exit 0, 20/20 verdes`
  (`--test-tags /printflow_gestion_inventario:TestProductFlowSupplyTray,TestProductFlowFailureLotNoStock`), sobre la
  evidencia del Dev (**41/41 verdes**, `TestProductFlowFailureLotNoStock` **9/9**). El archivo nuevo NO contiene
  `cr.execute`/`cr.commit`/`_action_done`/`button_validate`/`.write(`/`.create(`/`.unlink(` (solo lecturas + el saneo
  EXISTENTE); `_pf_open_failure_tray`/`_pf_use_guided_failure_tray`/`action_run_pf_plan` **SIN cambios** (el fallback
  clásico con 2 args sigue: `_pf_is_lot_cause('lot_no_stock')` → `LOT_REMEDY_BY_STATE`, sin `product_id` ⇒ clásica);
  motor `x_product_dimensional_pricing` solo reutilizado; `__manifest__.py`/`security/` sin cambios. Hallazgos [baja]:
  (a) 3 rojos del baseline **B1** con control negativo del Dev ⇒ pre-existentes (ya en Sección 1); (b) sin baseline git
  (H-002). Sin hallazgos de alta/media.
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia del Verificador
  aceptada: **veredicto `cumple`**; Dev exit 0, **41/41 verdes** (`TestProductFlowFailureLotNoStock` **9/9**
  CA-1..CA-4 + `TestProductFlowFailureRegistry`/`...TrayGeneric`/`...OverReservation`/`...LotActions`/`...LotTray`)
  + corrida acotada del Verificador **20/20**. T1→T4 marcadas `[x]` (0 pendientes); Ficha y Sección 3 cerradas.
  **Hallazgo H-019 pasa a `resuelto`.** **Tarea CERRADA.** Motor `x_product_dimensional_pricing`, bandeja guiada,
  bandeja clásica, casos `lot_orphan_reservation`/`data_anomaly` y `__manifest__.py` intactos.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`) para
  registrar la nueva falla y verificar que el "Solucionar" del caso **"Lote sin existencia"** abre la **bandeja GUIADA**
  con el saneo **"Reasignar la reserva por lote"**.
  **Nota (fuera de alcance, H-018):** las 28 entregas del banner siguen **sin lote** (el flujo exige el lote exclusivo
  del pedido, `SXXXXX-Lyyyy`, vacío); la bandeja guiada ahora cubre `lot_no_stock` (lote reservado SIN existencia),
  pero el caso "movimiento SIN ningún lote asignado" es `lot_missing` y queda como extensión futura (D2/O-4).
- [2026-10-16 · Odoo Planificador] **Plan del ERROR DE LOTE en el diagrama de PRODUCTO (nodos Entrega e
  Inventario) — Sección 3.** D1–D6 cerradas: (D1/P1) las DOS fallas se presentan como UNA mediante el helper
  ADITIVO `_pf_lot_coupled_roles` en `models/printflow_flow_strategy_product.py` (cableado en `_pf_with_derived`
  DESPUÉS del cálculo normal de `roles`/`broken_slots`), que invierte la cadena (RAÍZ=Entrega → CONSECUENCIA=
  Inventario) SOLO cuando el producto tiene `lot_missing` en Entrega **y** `data_anomaly` (quant colgado sin lote
  o == lote esperado) en Inventario; la causa raíz viaja por el `summary` del nodo Entrega (lote exclusivo
  esperado, reutilizando `_get_exclusive_lot_name`/`_get_exclusive_delivery_lot`) y por `summary`/`steps` del
  playbook — **SIN claves nuevas en el payload** (widget, `BASE_NODE_KEYS` y candados de paridad INTACTOS).
  (D2/P2) la bandeja CLÁSICA se EXTIENDE (no se reemplaza): nuevo constructor `_pf_rows_pending_orders` SUMADO a
  `_pf_rows_missing_moves` en `_pf_rows_for_state`, con UNA fila por ORDEN (picking) sin lote desde la FUENTE
  ÚNICA `printflow.flow.pending._pf_node_pending_rows('delivery', …)` (una lectura batch, sin N+1), `kind` nuevo
  `pending_order` cableado con lista blanca en `_compute_lot_action_mode` (→`assign`), `_pf_search_lot_action_mode`
  y `_pf_document_move`. (D3/P3) el "problem" de `_pf_plan_lot_missing` se RENOMBRA a "Ver existencias por lote"
  (el `target` sigue `quants`); cambio de 1 línea. (D4/P4) el saneo acotado se hace **100 % desde PrintFlow** con
  `_inherit='printflow.stock.remedy'` + `_pf_release_hanging_lot_reservation` (guardia `_pf_assert_can_clean`,
  helper puro `pf_quant_is_hanging_reservation`, guardia anti-entrega-sana: solo suelta líneas sin lote o con lote
  sin existencia, y re-reserva con `action_assign()` NATIVO) ⇒ `_pf_cleanup_product_reservations` del motor queda
  **INTACTO** ⇒ **sin autorización del dueño**. (D5) candados verificados por aserción (siguen verdes) + 3 tests
  NUEVOS; B1 (rojos pre-existentes) NO se toca. (D6) el P2 solo LISTA/decide por fila; NO hay asignación masiva de
  lotes (es DATOS, O-1/H-018). Archivos: **MODIFICAR** `models/printflow_flow_strategy_product.py`,
  `models/printflow_flow_lots.py`, `models/printflow_resolution_playbook.py`,
  `wizard/printflow_flow_lot_tray.py` (+vista solo si aplica), `models/printflow_flow_failure_over_reservation.py`,
  `models/__init__.py`; **CREAR** `models/printflow_stock_remedy.py`,
  `tests/test_product_flow_lot_coupled_chain.py`, `tests/test_product_flow_lot_tray_orders.py`,
  `tests/test_product_flow_over_reservation_scoped.py`. Plan **T1–T9 en 3 lotes**. SIN CAMBIOS: motor
  `x_product_dimensional_pricing`, widget/builder/payload, bandeja guiada, casos
  `lot_orphan_reservation`/`data_anomaly`/`lot_no_stock`, `__manifest__.py` y `security/`. Turno → **Odoo
  Analista** (paso 3: revisar y delegar el Lote 1 a `odoo-dev`).
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** (sesión NUEVA). **P1: las DOS fallas como UNA, con causa
  raíz.** Archivos: (T1) MODIFICADO `models/printflow_flow_strategy_product.py`: (a) helper
  `_pf_lot_coupling_active(slot_failures)` (L322-343) — dispara el acoplamiento SOLO si hay `lot_missing` en
  `slot_failures['delivery']` **y** `data_anomaly` en `slot_failures['inventory']`; (b) helper
  `_pf_lot_coupled_roles(self, roles, statuses, slot_failures)` (L345+) — devuelve COPIA de `roles` con
  `delivery='root'`/`inventory='consequence'` (misma referencia si NO hay acoplamiento); (c) cableado en
  `_pf_with_derived` (L249-257) DESPUÉS del cálculo normal: si acopla → `roles=coupled`, `parents['inventory']='delivery'`,
  `root_slot='delivery'`, `root_label_node='delivery'`; (d) `_pf_product_chain_summary` (L510-543) REORDENADA para
  pintar PRIMERO la raíz y luego la consecuencia (formato `Entrega (origen) → Inventario (consecuencia)`).
  **DESVIACIÓN deliberada de la firma:** el plan pedía `_pf_lot_coupled_roles(self, roles, statuses)`, pero
  `statuses` colapsa `lot_missing`/`lot_no_stock` y NO lleva `data_anomaly`; se mantuvo el NOMBRE y se añadió el
  3.er parámetro `slot_failures` (fuente real de las causas por slot). **Por qué NO basta `root_slot='delivery'`:**
  `engine._pf_chain_steps` (L386) solo marca `consequence` a los slots POSTERIORES a la raíz en `PF_CHAIN_SLOTS`
  (…,`inventory`(4),`delivery`(5)) ⇒ con raíz=`delivery` el `inventory` quedaría `independent`; por eso se ajustan
  `roles`/`parents` a mano. (T2) MODIFICADO `models/printflow_flow_lots.py`: helper
  `_pf_expected_exclusive_lot_name(lot_info)` (L287) que navega `missing_move_ids` → `stock.move` →
  `move.sale_line_id._get_exclusive_lot_name()` (primer nombre no vacío, sin lecturas nuevas) y, en
  `_pf_issue_from_lot_info`, enriquece el `detail` del nodo Entrega con *"se espera el lote exclusivo del pedido
  <S…-L…>"* SOLO con `key=='delivery' and state=='lot_missing' and mode=='product'` (el gate a `mode=='product'`
  es OBLIGATORIO: `printflow_flow_explain` usa `detail` para AMBOS diagramas ⇒ sin él se rompería la paridad del
  PEDIDO). MODIFICADO `models/printflow_resolution_playbook.py::_pf_plan_lot_missing` (L891): `summary`/`steps`
  explican que Entrega (raíz) e Inventario "Reserva colgada" son la MISMA falla y el paso correcto; el `problem`
  (`'Ver movimientos sin lote'`) queda INTACTO (su renombre es T4). (T3) CREADO
  `tests/test_product_flow_lot_coupled_chain.py` (`TransactionCase`, `post_install`, mixin
  `PrintflowStockHealthTestMixin`) + registrado en `tests/__init__.py`: CA-1a (acoplado → `delivery.role='root'`,
  `stock.role='consequence'`, `stock.parent='delivery'`, `root_link.target_key='delivery'`, `chain_summary` con
  Entrega antes que Inventario), CA-1b (no acoplado → `stock.role != 'consequence'`, sin `root_link`, `chain_summary`
  vacío) y CA-1c (el `summary` del nodo Entrega nombra el lote exclusivo `S…-L…`). **APRENDIZAJE clave (2
  iteraciones con dump temporal):** (1) `stock.move._action_confirm()` en Odoo 17 llama internamente a
  `_action_assign()` ⇒ si YA hay existencia reserva por su cuenta (creaba una move line extra y duplicaba la
  reserva); el escenario confirma el movimiento ANTES de añadir stock; (2) **la propia move line sin lote
  AUTO-RESERVA** sobre un quant sin lote (`quantity=0, reserved=3`) — es EXACTAMENTE el hecho real (quant 15219)
  ⇒ el helper `_hanging_quant` sobraba (sumaba de más) y se sustituyó por `_backing_quant` (físico sin lote que
  RESPALDA la reserva) para fabricar el caso NO acoplado; (3) el rol vive en `node['role']` (NO en `node['chain']`,
  que es el slot) — el plan lo citaba al revés. **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal, `--no-http`;
  `-u printflow_gestion_inventario`; `--test-tags`):** `TestProductFlowLotCoupledChain` **3/3** (CA-1a/b/c) y
  candados **68/68 verdes** (0 failed, 0 errors): `TestProductFlowLotTray`, `TestProductFlowLotTrayDocument`,
  `TestProductFlowLotTrayAuthorize`, `TestProductFlowLotActions`, `TestProductFlowLotRemedyPermissions`,
  `TestFlowCanvasParity` (paridad del PEDIDO), `TestProductFlowPayloadParity`, `TestDiagnosticTimelinePayload`,
  `TestFindingExceptionFormal`. `py_compile` OK; sin restos de depuración. Solo LECTURA de datos ajenos (sin
  `cr.execute`/`cr.commit`); motor `x_product_dimensional_pricing`, widget/builder/payload, bandeja guiada y
  `__manifest__.py` INTACTOS. **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar el código. Turno → **Odoo Dev** (Lote 2: T4–T6).
- [2026-10-16 · Odoo Dev] **Lote 2 (T4–T6) ejecutado** (sesión NUEVA). **P2 + P3: la bandeja lista las órdenes +
  botón honesto.** Archivos: (T4) MODIFICADO `models/printflow_resolution_playbook.py::_pf_plan_lot_missing`
  (L929-930): el ítem "problem" pasa de `_('Ver movimientos sin lote')` a **`_('Ver existencias por lote')`**;
  su `kind='navigate'`/`target='quants'` NO cambian (el rótulo ahora dice la verdad sobre su destino). El
  `solution` (`run_action`/`assign_lot`) sigue intacto ⇒ en `_pf_apply_action` el `problem` queda HABILITADO
  (solo se apaga si `(kind,target)` coincide con la solución). (T5) MODIFICADO
  `wizard/printflow_flow_lot_tray.py` con 5 cambios quirúrgicos: (a) constructores del `builders`:
  `'lot_missing': self._pf_rows_lot_missing` (L456); (b) NUEVO `_pf_rows_lot_missing(product, lot_info)` =
  `self._pf_rows_missing_moves(...) + self._pf_rows_pending_orders(...)` (**SUMA**, nunca reemplazo; O-5: se
  conservan AMBAS lecturas — evidencia técnica del movimiento + dimensión operativa por orden — sin
  deduplicar); (c) NUEVO `_pf_rows_pending_orders(product, lot_info)` (L529-575): lee la FUENTE ÚNICA
  `printflow.flow.pending._pf_node_pending_rows('delivery', [product.id])`, resuelve los `stock.move` de esos
  pickings y **excluye** los que ya tienen `lot_ids` (entregas SANAS) ⇒ una fila `kind='pending_order'` por
  ORDEN sin lote, con SOLO campos REALES del modelo `printflow.flow.lot.tray` (`label`, `lot_name`, `qty`,
  `state_label`, `detail`, `res_model='stock.picking'`, `res_id`, `picking_id`, `partner_id`,
  `scheduled_date`, `location_id`, `demand_qty`, `can_choose_lot=True`, `lot_id=False`); (d)
  `_compute_lot_action_mode`: rama EXPLÍCITA `kind == 'pending_order'` → `'assign'`; (e) `_pf_document_move`:
  caso `pending_order` + `res_model='stock.picking'` → `Move.search([...], limit=1)` para que
  `_pf_row_lot_context` traiga el lote exclusivo esperado (`own_lot_name`). **DESVIACIONES deliberadas
  (documentadas):** (1) **2 lecturas batch** (pending_rows + moves) en vez de "UNA sola" — `stock.move.line`
  no permite decidir "sin lote" en batch sin N+1, pero `stock.move.lot_ids` (m2m) SÍ es consultable en
  `search_read` ⇒ 2 lecturas O(1), sin N+1; (2) el modelo de fila es **`printflow.flow.lot.tray`** (cada
  registro ES una fila; el `.line` del docstring L540 está OBSOLETO) ⇒ el test asevera sobre
  `tray.filtered(kind=...)`, no sobre `tray.line_ids`; (3) `_pf_search_lot_action_mode` hubo que **conservar
  la tupla EXACTA** de kinds del candado `test_product_flow_lot_tray_document` (L344-346) y añadir
  `'pending_order'` como rama **OR SEPARADA** (`'|', '|', (tupla intacta), ('kind','=','pending_order'), '&',
  ('kind','=','unassigned_mo'), ('own_lot_name','=',False)`) ⇒ ningún test existente se modificó.
  **`_pf_open_lot_tray` usa el `lot_state` PASADO** (no el recomputado) ⇒ la bandeja refleja el nodo/enlace
  que pulsó el operador; `_pf_use_guided_failure_tray` devuelve `False` en llamadas de 2 args ⇒ cae a la
  bandeja clásica (fallback intacto). (T6) CREADO `tests/test_product_flow_lot_tray_orders.py`
  (`TransactionCase`, `post_install`, 5 tests) + registrado en `tests/__init__.py`: CA-2 (escenario con 3
  entregas pendientes SIN lote —2 sin reserva y 1 con move line sin lote— + 1 entrega SANA con lote real con
  existencia: `action_run_pf_plan('lot_missing','solution')` abre la bandeja; una fila `pending_order`/
  `stock.picking` por cada orden sin lote; la SANA NO aparece; todas en modo `assign`; `document_ref` resuelve
  el par; la demanda viaja por fila; no-regresión: la fila `missing_move` del movimiento ya creado sigue
  presente) + CA-2b (si TODAS las entregas tienen lote → ninguna orden inventada) + CA-2c (el filtro
  `lot_action_mode='assign'` NO pierde las órdenes nuevas) + CA-3 ("problem" de `lot_missing` == "Ver
  existencias por lote", `kind='navigate'`, `target='quants'`, tanto por `_pf_plan_for_state` como por el
  builder del playbook en ambos modos). **APRENDIZAJES (2 iteraciones):** (1) en Odoo 17 el `Reference`
  computado cachea un RECORDSET ⇒ comparar `row.document_ref` contra el string `'modelo,id'` falla; se usa el
  patrón ya establecido en `test_product_flow_lot_tray_document` (`row.document_ref._name` / `.id`); (2) si el
  caso NO tiene falla (todas con lote) la bandeja legítimamente viene VACÍA ⇒ el helper `_open_tray` acepta
  `expect_rows=False` (la aserción de "≥1 fila" solo donde aplica). **Pruebas (BD `pf_picker_tests`,
  `--data-dir` temporal, `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`;
  `--test-tags` por clase):** exit **0**, **82/82 verdes (0 failed, 0 errors)** →
  `TestProductFlowLotTrayOrders` **5/5** (CA-2/CA-3) + candados `TestProductFlowLotTray`,
  `TestProductFlowLotTrayDocument` (incluye el candado crítico del search L344-346), `TestProductFlowLotTrayAuthorize`,
  `TestProductFlowLotActions`, `TestProductFlowLotRemedyPermissions`, `TestProductFlowLotReassignPerDocument`,
  `TestProductFlowLotCoupledChain` (Lote 1), `TestFlowCanvasParity` (paridad del PEDIDO), `TestProductFlowPayloadParity`,
  `TestDiagnosticTimelinePayload` y `TestFindingExceptionFormal`. `py_compile` OK. Solo LECTURA de datos ajenos
  (sin `cr.execute`/`cr.commit`; `TransactionCase` con rollback; el `pf_node_pending_limit='0'` que fija el test
  es transitorio). `wizard/printflow_flow_lot_tray_views.xml` **SIN CAMBIOS** (el filtro `assign` de la vista
  sigue funcionando gracias a la rama OR del search); motor `x_product_dimensional_pricing`, widget/builder/payload,
  bandeja guiada, casos `lot_no_stock`/`lot_orphan_reservation`/`data_anomaly` y `__manifest__.py` INTACTOS.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`)
  para recargar el código. Turno → **Odoo Dev** (Lote 3: T7–T9 — saneo acotado).
- [2026-10-16 · Odoo Dev] **Lote 3 (T7–T9) ejecutado** (sesión NUEVA; con este lote queda COMPLETO el plan T1–T9).
  **P4: saneo ACOTADO de la reserva colgada.** Archivos: (T7) **CREADO** `models/printflow_stock_remedy.py`:
  `class PrintflowStockRemedy(models.AbstractModel)` con `_inherit = 'printflow.stock.remedy'` (docstring del
  "por qué": acotar el saneo para no des-asignar entregas sanas de la misma ubicación) y el método
  `@api.model _pf_release_hanging_lot_reservation(self, product)`: (1) guardia EXISTENTE
  `self._pf_assert_can_clean()`; (2) localiza los quants COLGADOS del producto con el helper PURO del motor
  `pf_quant_is_hanging_reservation(quantity, reserved)` (UNA `search_read` de quants internos/tránsito) ⇒ set
  `(location_id, lot_id)` colgados + mapa `lot→stock`; si no hay ninguno → contrato vacío sin escribas; (3)
  selecciona SOLO las `stock.move.line` activas (`state not in ('done','cancel')`, `quantity > _EPS`) cuya
  **ubicación** pertenece a un quant colgado **y** cuyo **lote coincide** con el del quant (`False` incluido);
  (4) **GUARDIA anti-entrega-sana**: una línea respaldada por stock real (`lot_stock > _EPS`) NUNCA se suelta
  ⇒ la entrega sana con su excepción queda intacta (CA-4); (5) suelta con la primitiva EXISTENTE
  `stock.move._pf_unreserve_reservation()` y re-reserva por las reglas **NATIVAS** (`picking.action_assign()`);
  (6) devuelve el **MISMO contrato** del motor (`{'cleaned_pickings': [...], 'still_negative': bool}`) +
  `message_post` (bitácora). Detalle fino: el motor suelta `pickings.move_ids` (TODOS los moves del picking);
  el método scoped suelta `targets.move_id` (solo los moves TARGET) ⇒ MÁS acotado, que es el objetivo.
  (T8) **MODIFICADO** `models/printflow_flow_failure_over_reservation.py`: docstring de módulo (bullet del
  saneo acotado, H-022), docstring de `_pf_fault_execute` y la llamada dentro de `_pf_fault_execute` pasa de
  `Remedy._pf_cleanup_product_reservations(product)` a **`Remedy._pf_release_hanging_lot_reservation(product)`**
  (MISMO contrato de retorno); evidencias/acciones (`view_quant`/`leave`)/guardia **INTACTAS**. `models/__init__.py`
  (sección 18: `from . import printflow_stock_remedy`). (T9) **CREADO** `tests/test_product_flow_over_reservation_scoped.py`
  (`TransactionCase`, `post_install`, 5 tests: `test_ca4_scoped_saneo_preserves_healthy_delivery`,
  `..._through_tray_action`, `..._method_returns_engine_contract`, `test_ca4_engine_method_still_exists_and_intact`,
  `test_ca4_scoped_source_has_no_raw_sql`) + registrado en `tests/__init__.py`. Escenario CA-4 = DOS entregas de
  salida en la MISMA ubicación: (a) SANA con su lote exclusivo CON existencia (`_backed_quant`, reservado 2) y
  (b) COLGADA sin lote (`_hanging_quant`, `quantity=0`/`reserved=3`); tras el saneo la SANA conserva su `lot_id`
  y su `reserved`, y sólo se libera/re-asigna la colgada.
  **APRENDIZAJES (2 correcciones dentro del lote):** (1) el motor declara `printflow.stock.remedy` como
  **`AbstractModel`** ⇒ la extensión DEBE ser `models.AbstractModel`; con `models.Model` el registry NO carga y
  la 1ª corrida murió con `TypeError: ... transforms the abstract model 'printflow.stock.remedy' into a
  non-abstract model` (lo cachó el `EXIT=-1` + log). Corregido a `AbstractModel`. (2) sintaxis de `--test-tags`:
  el prefijo `/modulo:Clase` es OBLIGATORIO en CADA clase (las comas separan specs completas; una clase "pelada"
  se interpreta como **TAG** y no matchea) ⇒ la 1ª corrida sólo ejecutó 5 tests (mi clase) y parecía que faltaban
  los candados. Re-lanzada con `/printflow_gestion_inventario:Clase` repetido por clase.
  **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal, `--no-http`; `-u printflow_gestion_inventario,x_product_dimensional_pricing`;
  `--test-tags` por clase repetida):** exit **0**, **0 failed / 0 error(s) de 72 tests** →
  `TestProductFlowOverReservationScoped` **5/5** (CA-4) + candados `TestProductFlowFailureOverReservation` (8/8),
  `TestProductFlowLotCoupledChain` (3/3, Lote 1), `TestProductFlowLotTrayOrders` (5/5, Lote 2),
  `TestProductFlowLotTray` (15/15), `TestFlowCanvasParity` (3/3, paridad del PEDIDO),
  `TestProductFlowPayloadParity` (8/8), `TestDiagnosticTimelinePayload` (14/14) y `TestFindingExceptionFormal`
  (11/11). `py_compile` OK. Solo LECTURA de datos ajenos (sin `cr.execute`/`cr.commit`; todas `TransactionCase`
  con rollback); motor `x_product_dimensional_pricing`, widget/builder/payload, bandeja guiada, bandeja clásica,
  casos `lot_no_stock`/`lot_orphan_reservation`/`data_anomaly`, `__manifest__.py` y `security/` **INTACTOS**.
  **Plan T1–T9 COMPLETO (3/3 lotes).** Los avisos `External ID not found` (`menu_printflow_dashboards` /
  `printflow_health_center_*`) del log son de carga **pre-existentes**. **Pendiente del dueño:**
  reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`) para recargar el código.
  Turno → **Odoo Verificador** (verificación final del plan completo).
- [2026-10-16 · Odoo Verificador] Veredicto **`cumple`** (verificación LIGERA, una pasada al final del ciclo).
  Contraste por **lectura directa** de los archivos + evidencia de tests de los 3 lotes del Dev (exit 0): Lote 1
  `TestProductFlowLotCoupledChain` 3/3 + candados 68/68; Lote 2 `TestProductFlowLotTrayOrders` 5/5 + candados 82/82;
  Lote 3 `TestProductFlowOverReservationScoped` 5/5 + candados (72 tests, 0 failed/0 errors). Conforme a CA-1..CA-5
  y a §3.7: **P1 (T1)** `_pf_with_derived` (L249-256) invierte `parents['inventory']='delivery'`/`root_slot='delivery'`
  y recalcula `chain_summary` (L288) **sin claves nuevas de payload**; **P1 (T2)** `_pf_plan_lot_missing` (L891-933)
  explica la MISMA falla (raíz=Entrega, consecuencia=Inventario); **P2 (T5)** `_pf_rows_lot_missing` (L513) SUMA
  `_pf_rows_missing_moves` + `_pf_rows_pending_orders` (L530, fuente única `_pf_node_pending_rows('delivery', …)`,
  excluye entregas con lote), `kind='pending_order'` cableado (modo `assign`, dominio OR, `_pf_document_move` L796);
  **P3 (T4)** rótulo "Ver existencias por lote" con `target='quants'` (L930); **P4 (T7/T8)** `printflow_stock_remedy.py`
  (`AbstractModel`, `_inherit`) + `_pf_release_hanging_lot_reservation`; la falla apunta al método acotado; motor
  `_pf_cleanup_product_reservations` **intacto**. Grep de `cr.execute`/`cr.commit`/`button_validate`/`_action_done`
  en `models/`+`wizard/` sin usos reales (solo docstrings). Hallazgos [baja]: (a) desviación deliberada de la firma de
  `_pf_lot_coupled_roles` (3.er parámetro `slot_failures`, registrada como **H-025 `descartado`**); (b) sin baseline
  git (cubierto por H-002). Sin hallazgos de severidad alta/media. Turno → **Odoo Analista**.
- [2026-10-16 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia del Verificador
  aceptada: **veredicto `cumple`**; Dev exit 0 los 3 lotes (`TestProductFlowLotCoupledChain` 3/3, `TestProductFlowLotTrayOrders` 5/5,
  `TestProductFlowOverReservationScoped` 5/5) + candados (paridad del PEDIDO `TestFlowCanvasParity` 3/3,
  `TestProductFlowPayloadParity` 8/8, `TestDiagnosticTimelinePayload` 14/14, `TestProductFlowLotTray` 15/15,
  `TestProductFlowFailureOverReservation` 8/8, `TestFindingExceptionFormal` 11/11). T1→T9 marcadas `[x]`
  (0 pendientes); Ficha y Sección 3 cerradas. **Hallazgos `resuelto`:** **H-020** (P1: las dos fallas como UNA con
  causa raíz), **H-022** (P4: saneo acotado, no des-asigna la entrega sana), **H-023** (P3: botón honesto), **H-024**
  (P2: la bandeja lista las órdenes). **H-021 queda `abierto`** (fase 2 / O-2: "Autorizar excepción" ≠ "Asignar lote"
  y el saneo por documento). **H-016 queda `abierto`** (nota: el O-4 del plan afirmaba que T5 lo alineaba "de la mano",
  pero H-016 es el botón `_pf_open_delivery_orders` del nodo Entrega —OTRA superficie, NO tocada—; la bandeja de T5 es
  la del "Solucionar"/`_pf_open_lot_tray`; se mantiene abierto). **H-018** (asignación REAL de lotes) y **H-015**
  siguen abiertos (datos / UX de cifra 0). **H-025** (`descartado`, desviación deliberada de firma). Contador de
  `HALLAZGOS.md`: **8 abiertos**. **Tarea CERRADA.** Motor `x_product_dimensional_pricing`, widget/builder/payload,
  bandeja guiada, bandeja clásica, casos `lot_no_stock`/`lot_orphan_reservation`/`data_anomaly`, `__manifest__.py` y
  `security/` **INTACTOS**. **Pendiente del dueño:** (1) reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar el código y ver: la cadena "Entrega (origen) → Inventario
  (consecuencia)" con la causa raíz, la bandeja que lista las órdenes pendientes y el botón renombrado; (2) la
  asignación REAL de lotes a las 26 entregas sigue siendo **datos** (H-018), el código solo muestra/facilita.
- [2026-10-16 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** (sesión NUEVA). **NOTA CLAVE:** al abrir la sesión se
  encontró un **intento anterior INTERRUMPIDO**: los 3 archivos de código ya existían en disco
  (`wizard/printflow_flow_lot_candidate.py` con `bulk_id`/`_pf_parent()`, `printflow_flow_lot_assign_bulk_line.py`
  y `printflow_flow_lot_assign_bulk.py` completos) y el registro ya estaba cableado (`wizard/__init__.py` L28-29,
  `security/ir.model.access.csv` L33-34). NO se duplicó nada: se **VERIFICÓ contra la Sección 3.11/3.12 y se
  CORRIGIÓ el único defecto real que dejó a medias**.
  **Defecto encontrado y corregido (bloqueante):** `printflow_flow_lot_candidate.py::_compute_is_recommended`
  agrupaba los padres con `self.mapped('picker_id') | self.mapped('bulk_id')` ⇒ el ORM de Odoo 17 lanza
  `TypeError: inconsistent models in: printflow.flow.lot.picker(191,) | printflow.flow.lot.assign.bulk()`
  (`models.py::union`) cuando un candidato tiene padre picker y el otro recordset está VACÍO. En la 1ª corrida
  eso producía **1 error** (`TestProductFlowLotPickerUx.test_exactly_one_recommended`) y rompía la sugerencia de
  TODA la bandeja/selector. **Corrección mínima:** se agrupa POR MODELO (un bucle por `picker_id` y otro por
  `bulk_id`) delegando en el helper nuevo `_pf_recommend_for_parent(parent, cands)`; se reutiliza el helper
  existente `_pf_parent_demand(parent)` y se conserva EXACTA la semántica (lote propio que cubre > mayor libre
  que cubre > mayor libre). Sin cambios de contrato ni de campos.
  **Mejora dentro del mismo archivo nuevo (T3):** en `printflow_flow_lot_assign_bulk.py::_pf_populate` se llamaba
  DOS veces seguidas a `self._pf_own_lot_ids(product, prepared)` (2 búsquedas idénticas de `stock.lot`); ahora
  se resuelve UNA vez (`own_lot_ids = set(...)`) y se reutiliza para `include_lot_ids`. Cero cambios de
  comportamiento; se respeta "sin N+1" (una lectura).
  **Archivos del lote (estado final):** (T1) `wizard/printflow_flow_lot_candidate.py` — `bulk_id`
  (m2o `printflow.flow.lot.assign.bulk`, `ondelete='cascade'`, index), `picker_id` SIN `required`, helper
  `_pf_parent()` = `picker_id or bulk_id`, `_pf_parent_demand()`, `_compute_is_picked`/`_pf_enforce_single_selection`
  generalizados al padre, `_compute_is_recommended` (fallback `bulk_id.total_demand` en `@api.depends`). (T2)
  `wizard/printflow_flow_lot_assign_bulk_line.py` — `printflow.flow.lot.assign.bulk.line` (snapshot de destino:
  `bulk_id`/`seq`/`kind`/`res_model`/`res_id`/`move_id`/`label`/`demand_qty`/`location_id`/`scheduled_date`/
  `assignable`/`result`/`result_note`). (T3) `wizard/printflow_flow_lot_assign_bulk.py` — contenedor
  `printflow.flow.lot.assign.bulk` (`_pf_populate` con UNA lectura batch de `stock.move` + UNA de
  `stock.picking` para ubicación/fecha, DEDUPE por `move_id`, FIFO por fecha/id, candidatos vía
  `_pf_available_lots` y `_pf_own_lot_ids`; `_pf_check_coverage`, `_pf_selected_lot`, `action_assign_lot_bulk`
  con `_pf_assert_can_clean` + `reason` + política `_pf_exception_policy` + captura de `UserError` POR DESTINO +
  `message_post` solo en `stock.picking`/`mrp.production` + `display_notification` con 4 conteos).
  `wizard/__init__.py` (línea→contenedor tras `printflow_flow_lot_candidate`) y `security/ir.model.access.csv`
  (2 filas `base.group_user,1,1,1,1`). **Solo LECTURA de datos ajenos**: la ÚNICA escritura es el ORQUESTADOR
  NATIVO `_pf_assign_lot_to_document`; sin `cr.execute`/`cr.commit`, sin `stock.quant`/`stock.move` a mano,
  sin `button_validate`. Motor `x_product_dimensional_pricing` INTACTO.
  **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal `...\Temp\opencode\pf_data`, `--no-http`, `-u
  printflow_gestion_inventario`, `--test-tags` por clase repetida, salida a `--logfile`):**
  (a) candados del SELECTOR POR DOCUMENTO (superficie de T1): **exit 1, 1 failed / 0 errores de 30** →
  el ÚNICO rojo es el **pre-existente B1** `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  (línea 143, ya documentado en 3.10/O-4); **el error `test_exactly_one_recommended` desapareció** tras el fix.
  (b) regresión de bandeja/lote: **exit 0, 0 failed / 0 errores de 36** → `TestProductFlowLotTray`,
  `TestProductFlowLotTrayDocument` (incluye el candado del `search` del filtro `assign`), `TestProductFlowLotTrayAuthorize`,
  `TestProductFlowLotActions`, `TestProductFlowLotTrayOrders` (Lote 2 del ciclo anterior) y `TestProductFlowLotCoupledChain`.
  **Verificación de registro (lectura):** `ir_model` contiene `printflow.flow.lot.assign.bulk` y
  `...assign.bulk.line`; sus 2 ACL están en `ir_model_access` (1,1,1,1); `fields_get` del contenedor responde con
  los campos del contrato de T3 y `fields_get` de la línea con los 13 campos de T2; `printflow.flow.lot.candidate`
  expone `bulk_id` y `picker_id` **sin** `required`. `py_compile` OK en los 3 archivos.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`)
  para recargar el código. Turno → **Odoo Dev** (Lote 2: T4–T6 — handler nativo `pending_order`, acción de
  bandeja y botón de cabecera).
- [2026-10-16 · Odoo Dev] **Lote 2 (T4–T6) ejecutado** (sesión NUEVA). Archivos: (T4) MODIFICADO
  `wizard/printflow_product_flow.py`: `handlers` de `_pf_assign_lot_to_document` + un método NUEVO
  `@api.model _pf_assign_lot_on_pending_order_doc(res_model, res_id, lot, product)` — con
  `res_model='stock.picking'` resuelve su `stock.move` activo del producto (`limit=1`, `state not in
  ('done','cancel')`; mismo camino que `printflow.flow.lot.tray._pf_document_move`), con `stock.move`
  directo hace `browse(res_id)`, y delega la ESCRITURA en `_pf_reassign_move_lot` (protocolo NATIVO de
  reserva). Devuelve `0` si no hay movimiento activo o la reserva da 0 (el orquestador lanza su
  `UserError`, que el bloque captura POR DESTINO). **Cierra H-026 en la vía por fila** ("Elegir lote" de
  una fila `pending_order` deja de lanzar `UserError`) y habilita la vía en BLOQUE con el MISMO escritor
  (D4/D9). (T5) MODIFICADO `wizard/printflow_flow_lot_tray.py`: constante `_BULK_ASSIGNABLE_KINDS =
  ('missing_move','pending_order')` y método PÚBLICO `action_assign_lot_bulk()` — `_pf_assert_can_clean()`;
  `records = self or self.search(active_domain)` (igual que `action_authorize_selected`); filtra ASIGNABLES
  (`can_choose_lot` + kind de entrega sin lote + producto), cuenta `omitted`; si no hay asignables ⇒
  `_pf_authorize_selected_notification` (sin abrir wizard); resuelve el movimiento de cada fila con
  `_pf_document_move` (YA soporta `pending_order`), DESCARTA las que no resuelven y DEDUPLICA por `move.id`
  (D5); construye el contenedor con `printflow.flow.lot.assign.bulk._pf_populate(product, rows,
  omitted_count=omitted)` y devuelve `act_window` (`target='new'`). NO escribe nada: el wizard es quien
  ejecuta el remedio NATIVO con su guardia y su motivo. (T6) MODIFICADO
  `wizard/printflow_flow_lot_tray_views.xml`: botón de cabecera NUEVO `action_assign_lot_bulk`
  ("Asignar lote", `class="btn-primary"`, `icon="fa-tags"`, `display="selection"`, title pedido), HERMANO de
  los botones de autorización; **sin tocar** los botones/columnas existentes. **Pruebas (BD `pf_picker_tests`,
  `--data-dir` temporal, `--no-http`, `-u printflow_gestion_inventario`, `--test-tags` por clase repetida,
  salida a `--logfile`):** (a) superficie de bandeja/lote/selector: **exit 1, 1 failed / 0 error(s) de 57** →
  el ÚNICO rojo es **B1 pre-existente** `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  (`6.0 != 8.0`, documentado en 3.10/O-4); el resto verde: `TestProductFlowLotTray` 15/15,
  `TestProductFlowLotTrayDocument` 12/12, `TestProductFlowLotTrayAuthorizeBulk` 5/5 (incluye el candado de
  vista `test_view_has_selection_action`), `TestProductFlowLotTrayAuthorize`, `TestProductFlowLotTrayOrders` 5/5,
  `TestProductFlowLotCoupledChain` 3/3, `TestProductFlowLotPicker` 11/11, `TestProductFlowLotPickerComponent` 2/2,
  `TestProductFlowLotPickerUx` 2/3, `TestProductFlowLotActions` 1/1. (b) `TestProductFlowLotTrayUx`: **exit 1,
  2 failed / 0 error(s) de 7** = los **2 B1 pre-existentes** (aritmética `3.0 != 5.0` y columnas `4 != 3`; mi
  botón NO añade `invisible=` ni columnas ⇒ no puede afectar esos candados). La vista nueva cargó sin error
  (`loading …/wizard/printflow_flow_lot_tray_views.xml`). `py_compile` OK; XML OK. Solo LECTURA de datos ajenos
  (la ÚNICA escritura de la acción es el ORQUESTADOR NATIVO `_pf_assign_lot_to_document` → `_pf_reassign_move_lot`;
  sin `cr.execute`/`cr.commit`, sin `stock.quant`/`stock.move` a mano, sin `button_validate`). Motor
  `x_product_dimensional_pricing` INTACTO; `models/` sin cambios. **Nota:** T4/T5 no tienen test propio en este
  lote (los crea **T8**, Lote 3); por eso la verificación del Lote 2 es la regresión de las superficies tocadas.
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`)
  para recargar el código/la vista. Turno → **Odoo Dev** (Lote 3: T7–T8 — vista del wizard + `__manifest__.py` +
  tests).
- [2026-10-17 · Odoo Dev] **Lote 3 (T7–T8) ejecutado** (sesión NUEVA). Archivos: (T7) NUEVO
  `wizard/printflow_flow_lot_assign_bulk_views.xml`: form `printflow_flow_lot_assign_bulk_view_form`
  (`create="false" delete="false"`, model `printflow.flow.lot.assign.bulk`) con cabecera (producto,
  `source_label`, `total_demand`, `location_id`, `assignable_count`, `omitted_count`), aviso VISIBLE de
  `multi_location`, decisión (`lot_id`, `confirm_partial`, `confirm_exception`), `candidate_ids` (reutiliza
  el tree `printflow_flow_lot_candidate_view_tree` por el default del modelo), `line_ids` (tree readonly con
  las 6 columnas EXACTAS del plan: `seq`/`label`/`kind`/`demand_qty`/`location_id`/`result`) y `<footer>` con
  "Asignar lote" (`action_assign_lot_bulk`, `btn-primary`, `fa-tags`) + "Cancelar" (`special="cancel"`). NO se
  puso `edit="false"`: esta superficie ES una decisión (marcar la fila y escribir el motivo), y con
  `edit="false"` Odoo 17 abriría el registro en `mode="readonly"`. (T7) MODIFICADO `__manifest__.py`: entrada
  `'wizard/printflow_flow_lot_assign_bulk_views.xml'` DESPUÉS de `'wizard/printflow_flow_lot_picker_views.xml'`
  (que define el tree reutilizado). (T8) NUEVO `tests/test_product_flow_lot_assign_bulk.py` (10 casos:
  CA-2 asignación a toda la selección + sin asignables ⇒ notificación sin wizard; CA-3 omitidas; CA-4 parcial
  exige check + lote escaso se REPORTa por destino; CA-5 permisos abrir/ejecutar; CA-6 motivo obligatorio +
  política ≠ `warn` exige `confirm_exception`; CA-7 conteos y las órdenes resueltas desaparecen; CA-9 dedupe
  por movimiento) y NUEVO `tests/test_product_flow_lot_pending_order_assign.py` (CA-1: `target_kind='pending_order'`,
  `res_model='stock.picking'` asigna SIN `UserError` + idempotencia). Registrados AMBOS en `tests/__init__.py`
  al final del bloque de lote. **Pruebas (BD `pf_picker_tests`, `--data-dir` temporal, `--no-http`,
  `-u printflow_gestion_inventario`, `--test-tags` por clase repetida, salida a `--logfile`):** (a) los 2 test
  nuevos: **exit 0, 0 failed / 0 error(s) de 12**; (b) candados de lote/bandeja/selector
  (`TestProductFlowLotTray`/`TrayDocument`/`TrayAuthorizeBulk`/`TrayOrders`/`Picker`/`Actions`/`CoupledChain`):
  **exit 0, 0 failed / 0 error(s) de 52**. Las vistas nuevas cargaron sin error. **Nota de evidencia:** al
  reparar el test CA-3 se corrigió el escenario (crear la fila no asignable DESPUÉS de `_pf_populate`, que
  limpia las filas del producto+estado) y la aserción de identidad (en una fila `pending_order` `res_id` es el
  ALBARÁN y `move_id` el movimiento), sin tocar código de producción. Solo LECTURA de datos ajenos (la ÚNICA
  escritura es el ORQUESTADOR NATIVO `_pf_assign_lot_to_document` → `_pf_reassign_move_lot`; sin
  `cr.execute`/`cr.commit`, sin `stock.quant`/`stock.move` a mano, sin `button_validate`). Motor
  `x_product_dimensional_pricing` INTACTO; `models/` sin cambios. **Aviso fuera de alcance (NO corregido):** el
  `-u` sigue registrando `External ID not found` de `x_product_dimensional_pricing.menu_printflow_dashboards` y
  `printflow_health_center_*` (vistas/menú retirados del motor; ver 3.10/O-4) — es PRE-EXISTENTE y ajeno a este
  lote. Rojo **B1** pre-existente `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  sigue ajeno (no se tocó el selector). **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor
  8071 (`-u printflow_gestion_inventario`) para recargar código + vista. Turno → **Odoo Verificador** (verificación
  LIGERA del ciclo completo, una sola pasada al final de los 3 lotes).
- [2026-10-17 · Odoo Verificador] Verificación **LIGERA** (una sola pasada, al final de los 3 lotes). Veredicto:
  **`cumple`**. Evidencia: lectura directa de los archivos del cambio + la evidencia de tests ya registrada por los
  lotes (Lote 1: regresión bandeja `exit 0` 36/36 y candados del selector `exit 1` 1 failed/30 = B1 pre-existente;
  Lote 2: superficies `exit 1` 1 failed/57 y `TrayUx` 2 failed/7 = B1; Lote 3: 12/12 nuevos `exit 0` + 52/52 candados
  `exit 0`). No re-corrió la suite (modo ligero; no faltaba evidencia). Grueso verificado: **(a)** cero flujos
  forzados (sin `cr.execute`/`cr.commit`/`button_validate` reales; solo menciones en docstrings); **(b)** ÚNICO
  escritor = `_pf_assign_lot_to_document` → `_pf_reassign_move_lot` (protocolo NATIVO), sin segundo camino;
  **(c)** selector por documento y bandeja clásica INTACTOS (en la bandeja solo se AGREGA el botón); **(d)** **H-026
  resuelto sin `UserError`** (`'pending_order'` en la lista blanca + test no vacuo que ejecuta `action_assign_lot()` y
  verifica reserva real); **(e)** evidencia de tests completa. Hallazgos [baja]: (1) el módulo está UNTRACKED en git ⇒
  sin diff de referencia (re-confirma **H-002**); (2) `wizard/printflow_flow_lot_tray.py` L1048-1129 reutiliza
  `_pf_authorize_selected_notification(...)` en la rama "sin asignables" (nombre heredado del flujo de autorización;
  funcionalmente correcto, solo puede confundir al lector). **Nota:** el Verificador opera con `edit: deny` (solo lee y
  corre pruebas) ⇒ NO escribió su veredicto; lo registra el **Analista** (esta entrada + los hallazgos).
- [2026-10-17 · Odoo Analista] **Cierre de ciclo** (compuerta de convergencia §4.3). Plan **T1–T8 COMPLETO en 3 lotes**
  (0 pendientes); veredicto del Verificador = **`cumple`** con evidencia aceptada. Hallazgos actualizados:
  **H-021 → `resuelto`** (ya existe la acción masiva; la parte "Autorizar excepción no cambia el lote" queda **por
  diseño**, no es defecto) y **H-026 → `resuelto`** (el handler `pending_order` cierra la vía por fila Y la de bloque
  con el MISMO escritor). Se registran los hallazgos [baja] del Verificador: **H-028** (`abierto`); el de "repo sin
  commits" se anexa a **H-002** (para no duplicar fila). **H-027** (avisos `External ID not found` al `-u`)
  `descartado`: son `<delete>` **intencionales** del módulo sobre xmlids del motor. Ficha y Sección 3 cerradas;
  bitácora escrita. **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`). Turno devuelto a **Odoo Analista** (tarea CERRADA).
- [2026-10-17 · Odoo Dev] **Lote 1 de 3 (T1–T3) — Detalle del resultado de la asignación en bloque
  (H-029 · modelos + registro).** NUEVOS: (T1) `wizard/printflow_flow_lot_assign_bulk_result_line.py`
  (`printflow.flow.lot.assign.bulk.result.line`, `_order='seq asc, id asc'`, 7 campos:
  `result_id` m2o required/ondelete cascade/indexado + `seq`/`label`/`kind`/`demand_qty`
  (`digits='Product Unit of Measure'`)/`result` (los MISMOS 5 códigos `pending/assigned/partial/skipped/error`
  del contenedor)/`result_note`, los 6 readonly: es SOLO LECTURA, snapshot sin escribir `stock.*`);
  (T2) `wizard/printflow_flow_lot_assign_bulk_result.py` (`printflow.flow.lot.assign.bulk.result`, campos
  `bulk_id`/`product_id`/`source_label`/`line_ids` + `assigned_count`/`partial_count`/`omitted_count`/`error_count`
  con `_compute_counts` y `@api.depends('line_ids.result')`, y `@api.model _pf_build_from_bulk(bulk)` que copia
  **UNA fila por `bulk.line_ids`** — TODAS: `assigned/partial/skipped/error/pending` — con `seq/label/kind/demand_qty/
  result/result_note`, devolviendo el recordset creado). Patrón **PORTADO** del motor
  `x_product_dimensional_pricing/wizard/printflow_delivery_bulk_result*.py` (leído, NO editado). (T3) MODIFICADOS:
  `wizard/__init__.py` (2 imports — línea ANTES de cabecera por el One2many — justo DESPUÉS de
  `printflow_flow_lot_assign_bulk` y ANTES de `printflow_flow_lot_picker`, con comentario del motivo) y
  `security/ir.model.access.csv` (2 filas `base.group_user,1,1,1,1` al final:
  `access_printflow_flow_lot_assign_bulk_result` / `..._result_line`). **`_description` de la línea = 64 caracteres**
  (bajo el umbral de 68) y el `string` de la línea es **"Motivo"** (no "Nota del resultado"), para que la columna de la
  vista de T5 lea el motivo completo. NO se tocó el contenedor del bloque, la bandeja, el motor ni
  `models/`. **Sin `cr.execute` de escritura / `cr.commit`** (verificado por búsqueda en los 2 archivos nuevos);
  `wizard/` no importa `models/` de forma inversa. **Evidencia de sintaxis:** `py_compile` de los 3 archivos ⇒
  exit 0. **Evidencia en BD (solo lectura, `odoo-impreven` / `Ciber Estudios 2015 RESTAURADA`):**
  `ir.model` ⇒ `printflow.flow.lot.assign.bulk` **1** (ya registrado), `printflow.flow.lot.assign.bulk.result` **0** y
  `...result.line` **0** ⇒ los 2 modelos nuevos aparecerán al actualizar el módulo. **NO se corrieron tests:** los
  del ciclo (T8/T9) pertenecen al **Lote 3**, y T1–T3 no añade lógica ejecutable hasta el `-u` (el Dev no reinicia
  Odoo ni hace upgrade por su cuenta). **Verificación de T1–T3 pendiente del `-u`** (`fields_get` de los 2 modelos +
  carga del tree nuevo ⇒ la hace el dueño / el lote siguiente). Trabajo **solo de CÓDIGO**: 0 registros de la BD
  tocados. **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`). **SIGUE EL LOTE 2 (T4–T6):** rótulos + `selection_note` (H-031), vista del
  bloque + vista NUEVA del detalle + `__manifest__.py` y el encadenado del detalle en `action_assign_lot_bulk`
  (H-029). Turno → **Odoo Dev** (sesión NUEVA, Lote 2).
- [2026-10-17 · Odoo Dev] **Lote 2 de 3 (T4–T6) — H-031 (rótulos + texto visible) y encadenado del detalle
  (H-029).** MODIFICADOS: (T4/T6) `wizard/printflow_flow_lot_assign_bulk.py` — (a) **rótulos**:
  `total_demand` → `string='Unidades a entregar'`, `assignable_count` → `string='Entregas por asignar'`,
  `omitted_count` → `string='Entregas omitidas'` (SIN tocar `digits='Product Unit of Measure'`, `compute` ni la
  lógica de cálculo: 26 filas = 30 u sigue siendo CORRECTO); (b) **campo NUEVO computado**
  `selection_note = fields.Char(string='Resumen de la selección', compute='_compute_selection_note', readonly=True)`
  con `@api.depends('assignable_count', 'total_demand')` y texto **por `_()`** (traducible): *"Cada fila es una
  entrega (albarán de salida). %(n)s entregas por asignar = %(m)s unidades a entregar."* — `n` = `assignable_count`,
  `m` = `total_demand` formateado con **`%.2f`** (el MISMO formato que ya usa `_pf_check_coverage`), **SIN** sufijos
  de unidad (la palabra "unidades" va en la oración, D3); (c) **`_pf_result_notification(self, result=None)`**:
  **CONSERVA** el `display_notification` con el **texto EXACTO** de los 4 conteos (contrato CA-7) y ahora arma
  `params['next']`: con `result` ⇒ `ir.actions.act_window` (`name='Detalle de la asignación en bloque'`,
  `res_model='printflow.flow.lot.assign.bulk.result'`, `res_id=result.id`, `view_mode='form'`, `target='new'`); sin
  `result` ⇒ `{'type': 'ir.actions.act_window_close'}` (retro-compatible); (d) al final de `action_assign_lot_bulk`
  (antes `return self._pf_result_notification()`): `result = env['printflow.flow.lot.assign.bulk.result']
  ._pf_build_from_bulk(self)` y `return self._pf_result_notification(result)` — **DESPUÉS** del bucle de escritura,
  sin tocar la guardia, el `reason`, la política, el bucle FIFO ni los conteos. **`__manifest__.py`** (T5):
  `'wizard/printflow_flow_lot_assign_bulk_result_views.xml'` en `data`, **DESPUÉS** de
  `'wizard/printflow_flow_lot_assign_bulk_views.xml'` (con comentario del motivo). VISTA MODIFICADA (T5):
  `wizard/printflow_flow_lot_assign_bulk_views.xml` — en el `<group string="Selección">` se QUITÓ el
  `string="Filas omitidas"` de `omitted_count` (para que gobierne el del modelo; R-5) y se añadió **`selection_note`
  como texto VISIBLE** (`readonly="1" nolabel="1" colspan="2"`, sin `invisible` y sin tooltip) en la ranura
  "Selección"; el resto del form (candidatos, destinos, motivo, footer, aviso `multi_location`) **INTACTO**.
  VISTA NUEVA (T5): `wizard/printflow_flow_lot_assign_bulk_result_views.xml`
  (`printflow_flow_lot_assign_bulk_result_view_form`, `model='printflow.flow.lot.assign.bulk.result'`,
  `form create="false" edit="false" delete="false"`) con el `<div class="alert alert-info">` ("Motivo por destino de
  la asignación en bloque: revisa abajo cada entrega."), el `<group string="Resumen">` con los **4 conteos** y
  `line_ids` readonly con `<tree create="false" edit="false" delete="false">` y decoraciones
  `success=assigned` / `warning=partial` / `muted=skipped` / `danger=error`, columnas `#`·`Entrega`·`Tipo`·`Demanda`·
  `Resultado`·`Motivo`, y `<footer>` con **"Cerrar"** (`special="cancel"`). Patrón **PORTADO** del motor
  `x_product_dimensional_pricing/wizard/printflow_delivery_bulk_result_views.xml` (**leído, NO editado**) y del
  precedente de encadenado `models/printflow_node_pending_line.py::action_pf_validate_selected` (L221-233:
  notificación + `next` = ventana). **NO** se tocó: el contenedor del bloque salvo lo anterior, el candidato y su
  tree, `printflow_flow_lot_picker*`, la bandeja, `models/`, `security/`, ni NINGÚN archivo de
  `x_product_dimensional_pricing` (**sin cambios** ⇒ sin autorización del dueño). **Sin `cr.execute` de escritura /
  `cr.commit()`**; `models/` no se tocó ⇒ `wizard/` sigue sin ser importado por `models/`. **Evidencia de sintaxis:**
  `py_compile` de los 3 `.py` + parseo XML de las 2 vistas ⇒ **OK (exit 0)**. **Evidencia de tests (BD de test
  `pf_picker_tests` —NO la de producción—, `--data-dir` temporal, `--no-http`, `-u printflow_gestion_inventario`,
  `--test-tags` por clase, salida a `--logfile`):** exit **0**, **0 failed / 0 error(s) de 12 tests** ⇒
  `TestProductFlowLotAssignBulk` **9/9** (incluye **CA-7**, que fija el texto EXACTO de los 4 conteos ⇒ la cadena
  nueva **no** lo rompió) y `TestProductFlowLotPendingOrderAssign` **2/2**. El log confirma
  `loading …/wizard/printflow_flow_lot_assign_bulk_result_views.xml` **sin error**. **Evidencia en BD (solo lectura,
  `pf_picker_tests`):** `ir_model_fields` ⇒ `assignable_count` = *"Entregas por asignar"*, `omitted_count` =
  *"Entregas omitidas"*, `total_demand` = *"Unidades a entregar"* y `selection_note` (char, *"Resumen de la
  selección"*); `ir_model_data` ⇒ `printflow_gestion_inventario.printflow_flow_lot_assign_bulk_result_view_form`
  (ir.ui.view) registrado. Los avisos del log son los **pre-existentes** de O-6 (`Skipping deletion for missing XML
  ID` de `x_product_dimensional_pricing.menu_printflow_dashboards` / `printflow_health_center_*`): **ajenos** a T4–T6
  y NO se tocan. Trabajo **solo de CÓDIGO**: 0 registros de la BD de producción tocados. **SIGUE EL LOTE 3 (T7–T9):**
  `models/stock_move.py` (guardián ADITIVO de H-030) + los 2 tests nuevos. Turno → **Odoo Dev** (sesión NUEVA, Lote 3).
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`).
- [2026-10-17 · Odoo Dev] **Lote 3 de 3 (T7–T9) — H-030 (preservar la reserva de lote por excepción) +
  los 2 tests del ciclo.** NUEVOS: (T7) `models/stock_move.py` — `_EPS = 1e-6`; `class StockMove(models.Model):
  _inherit = 'stock.move'` con docstring del "por qué" (H-030: el NATIVO `_action_assign` NO re-asigna un
  movimiento ya reservado, pero la rama EXCLUSIVA del motor llama SIEMPRE a `_assign_exclusive_lot()` ⇒
  `_pf_reassign_lot` soltaba la excepción del operador y reservaba el lote exclusivo `S…-Lyyy` VACÍO ⇒
  reserva 0 ⇒ el albarán quedaba sin lote y el bulk lo omitía con *"Sin stock reservado."*). Método
  `_pf_keep_current_lot_reservation(self)` (`ensure_one`) ⇒ `False` si `product_id.tracking != 'lot'`;
  `False` si no hay línea activa con lote (`move_line_ids.filtered(lambda ml: ml.lot_id and not ml.picked
  and ml.quantity > _EPS)`); `False` si `self._get_exclusive_delivery_lot()` no devuelve lote; si lo hay,
  `free = env['stock.quant']._get_available_quantity(product, location_id, lot_id=lot)` y **CONSERVA** la
  reserva (`return free <= _EPS`). Override ADITIVO del seam MÁS PEQUEÑO `_assign_exclusive_lot(self)`: con
  el guardián activo ⇒ `self._recompute_state(); return True` (solo re-sincroniza el `state`); en cualquier
  otro caso ⇒ `return super()._assign_exclusive_lot()` ⇒ **el motor `x_product_dimensional_pricing` queda
  INTACTO** (mejor: su comportamiento actual no cambia). Es la MISMA regla del core ("si ya está reservado no
  se toca") aplicada a la rama EXCLUSIVA; NO se inventa regla nueva. (T7) MODIFICADO `models/__init__.py`:
  `from . import stock_move` en la sección 19 de extensiones heredadas del motor, con comentario del motivo.
  (T8) NUEVO `tests/test_pf_bulk_validate_preserves_lot.py` (`TestPfBulkValidatePreservesLot`,
  `TransactionCase` sellado `@tagged('post_install','-at_install')`, 4 casos): **CA-1/CA-2a** la excepción
  SOBREVIVE (`move.move_line_ids.mapped('lot_id') == generic_lot`, `picking.state == 'assigned'` tras
  `action_assign()`); **CA-2b** el bulk valida de verdad (`result == 'done'`, `reason` vacío,
  `picking.state == 'done'`, y NO aparece *"Sin stock reservado."*); **CA-2c** sin reserva y sin existencia
  SIGUE `skipped` con *"Sin stock reservado."* (honesto, no regresión); **CA-5** con el lote exclusivo CON
  existencia y sin reserva previa ⇒ `action_assign()` reserva el **lote EXCLUSIVO** (motor sin cambios);
  + candado `test_touched_files_have_no_raw_sql_and_motor_untouched` (sin `cr.execute(`/`cr.commit(`, y el
  fuente del motor sin cambios). (T9) NUEVO `tests/test_product_flow_lot_assign_bulk_result.py`
  (`TestProductFlowLotAssignBulkResult`, 4 casos): **CA-3 (H-029)** `bulk.action_assign_lot_bulk()` sigue
  devolviendo `display_notification` con el **MISMO** texto de los 4 conteos y ahora
  `params['next']['res_model'] == 'printflow.flow.lot.assign.bulk.result'` + el detalle trae **UNA fila por
  destino** (mismo número que `bulk.line_ids`) y las filas `error`/`skipped` con `result_note` NO vacío
  (incluye el caso de destino OMITIDO listado en el detalle); **CA-4 (H-031)**
  `fields_get('printflow.flow.lot.assign.bulk')` ⇒ *"Unidades a entregar"* / *"Entregas por asignar"* /
  *"Entregas omitidas"* y `bulk.selection_note` contiene `'entrega'` y las cifras; + candado de SQL crudo.
  Ambos registrados en `tests/__init__.py` al final del bloque de lote (líneas 166 y 170). **NO** se tocó el
  motor, el contenedor del bloque, la bandeja, `security/`, ni ningún archivo de `x_product_dimensional_pricing`
  (sin autorización del dueño). Sin `cr.execute` de escritura / `cr.commit`; sin `stock.quant`/`stock.move` a
  mano; sin `button_validate` (solo el flujo NATIVO del bulk). **Nota de docstring:** se escribió `cr.commit`
  (sin paréntesis) en el "por qué" para no disparar el candado textual `cr.commit(`.
  **Evidencia de sintaxis:** `py_compile` de los 5 archivos (2 nuevos + `models/__init__.py` +
  `tests/__init__.py`) ⇒ exit 0. **Evidencia de tests (BD de test `pf_picker_tests` —NO la de producción—,
  `--data-dir` temporal, `--no-http`, `--max-cron-threads=0`, `-u printflow_gestion_inventario`, `--test-tags`
  con prefijo `/printflow_gestion_inventario:<Clase>` por clase, salida a `--logfile`):** exit **1**,
  **1 failed / 0 error(s) de 104 tests** ⇒ VERDES: `TestPfBulkValidatePreservesLot` **4/4** (T8),
  `TestProductFlowLotAssignBulkResult` **4/4** (T9), `TestProductFlowLotAssignBulk` **9/9**,
  `TestProductFlowLotPendingOrderAssign`, `TestProductFlowLotPicker`, `TestProductFlowLotTray`,
  `TestProductFlowLotTrayOrders`, `TestProductFlowLotTrayDocument`, `TestProductFlowLotTrayAuthorize`,
  `TestProductFlowOverReservationScoped`, `TestProductFlowLotCoupledChain`, `TestLotManagement`,
  `TestPendingNativeValidate`. **Único rojo — B1 PRE-EXISTENTE:**
  `TestDiagnosticDeliveryOrders.test_bulk_validate_mixed_success_and_failure`
  (`tests/test_diagnostic_delivery_orders.py:200`, `AssertionError: 'done' == 'done'`), ya documentado en B1
  de la Sección 1 (mismo archivo y línea). **Delta documentado:** sus productos NO van por lote ⇒ el override
  (que solo actúa en la rama EXCLUSIVA por lote) NO está en su ruta; el rojo es ajeno a T7–T9 y no se toca.
  **Nota de evidencia:** la primera corrida usó `--test-tags` sin prefijo `/modulo:` en el segundo tag, que se
  interpretó como tag literal y no corrió `TestProductFlowLotAssignBulkResult`; se repitió con prefijos
  completos y ya aparece 4/4. El test de T8/T9 pasa; el fallo **sin** T7 está razonado (el motor des-reserva la
  excepción), no re-verificado revirtiendo código. Los avisos del log son los **pre-existentes** de O-6
  (`Skipping deletion for missing XML ID` de `x_product_dimensional_pricing.menu_printflow_dashboards` /
  `printflow_health_center_*`, labels duplicados, `<i>` sin `title`, `unknown parameter 'placeholder'`):
  ajenos a T7–T9 y NO se tocan. Trabajo **solo de CÓDIGO**: 0 registros de la BD de producción tocados.
  **Plan T1–T9 COMPLETO en 3 lotes (0 pendientes).** Turno → **Odoo Verificador** (verificación LIGERA, una
  sola pasada al final del ciclo). **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar `models/stock_move.py`.
- [2026-10-17 · Odoo Analista] **Cierre de ciclo (compuerta de convergencia §4.3).** Evidencia aceptada del
  `odoo-verificador`: **veredicto `cumple`**, sin hallazgos nuevos. Cadena completa: contrato (Analista) →
  **PLAN D1–D7 + T1–T9 en 3 lotes** (Planificador) → **3 sesiones NUEVAS de `odoo-dev`** (Lote 1: T1–T3 ·
  Lote 2: T4–T6 · Lote 3: T7–T9, cada una marcando `[x]` y dejando su bitácora) → **verificación LIGERA**
  (una sola pasada al final). **Plan T1–T9 COMPLETO, 0 pendientes.**
  **Evidencia de tests del Dev (BD de test `pf_picker_tests`, NUNCA la de producción):** exit **1**,
  **1 failed / 0 errors de 104**; único rojo = **B1 PRE-EXISTENTE** (`tests/test_diagnostic_delivery_orders.py:200`);
  nuevos en VERDE: `TestPfBulkValidatePreservesLot` **4/4** (H-030) y `TestProductFlowLotAssignBulkResult`
  **4/4** (H-029/H-031); candados del ciclo verdes (`TestProductFlowLotAssignBulk` 9/9, picker/tray/orders/
  coupled/over-reservation/lot-management). **Verificado por el Verificador (sin re-correr la suite):** sin
  `cr.execute`/`cr.commit`; el override `models/stock_move.py::_assign_exclusive_lot` **solo PRESERVA** (lee
  `move_line_ids`, el lote exclusivo y `_get_available_quantity`; NO escribe `stock.quant`/`stock.move`; NO
  fuerza `state`/`quantity`); el motor `x_product_dimensional_pricing` **SIN CAMBIOS** (mtime previo a la
  tarea); el detalle de H-029 es un TransientModel de **SOLO LECTURA**; rótulos + `selection_note` conformes
  a lo DECIDIDO con el dueño; convenciones OCA OK.
  **Hallazgos: H-029, H-030 y H-031 pasan a `resuelto`** → **8 abiertos** (H-001 · H-002 · H-005 · H-006 ·
  H-015 · H-016 · H-018 · H-028). **Tarea CERRADA.**
  **Pendiente del dueño:** (1) **reiniciar/actualizar el módulo** en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar `models/stock_move.py` y las vistas; (2) **acción de DATOS
  (H-018)**: en la bandeja "Asignar lote" elegir un lote **CON existencia** (`666634` = 23 u) sobre las 26
  entregas, con el check de **asignación parcial** (la demanda sumada es 30 u), y volver a validar con
  "validar entregas en lote" (que ya **NO** des-reservará la excepción). **Regla respetada: código sí, datos no**
  — 0 registros de la BD de producción tocados.
- [2026-10-17 · Odoo Dev] **Lote único (T1–T3) del ciclo 17/10-bis — fix del crash al abrir el detalle del bloque
  (H-032 · H-033).** Tarea **NORMAL** (cableado de una ACCIÓN; nada del flujo de inventario). **Causa raíz:** Odoo
  normaliza `views` SOLO en la acción `ir.actions.act_window` de **PRIMER nivel** que devuelve un botón; una acción
  **ANIDADA** en `params['next']` de un `display_notification` **NO** se normaliza y el cliente revienta en
  `action_service.js::_preprocessAction` (`action.views.map` ⇒ `TypeError ... reading 'map'`). (T1) MODIFICADO
  `wizard/printflow_flow_lot_assign_bulk.py`: en `_pf_result_notification` el dict `nxt` (L548-556) ahora incluye
  `'views': [(False, 'form')]` (MISMA convención del core al normalizar; `False` = vista por defecto del modelo) —
  se conservan `type='ir.actions.act_window'`, `name`, `res_model`, `res_id`, `view_mode='form'`, `target='new'`; el
  texto de los 4 conteos, el bucle de escritura, la guardia, el motivo y la política quedan **INTACTOS**. (T2)
  MODIFICADO `models/printflow_node_pending_line.py`: en `action_pf_validate_selected` (rama `others`) la acción
  anidada en `'next'` se arma sobre una **COPIA** del retorno del motor (`next_action = dict(result)` +
  `next_action.setdefault('views', [(False, 'form')])`) ⇒ se agrega `views` **sin mutar** el dict del motor
  (`x_product_dimensional_pricing`: **SIN CAMBIOS**, solo lectura). (T3) MODIFICADO
  `tests/test_product_flow_lot_assign_bulk_result.py`: se fija **CA-1** con
  `assertEqual(nxt['views'], [(False, 'form')])` en `test_ca3_notification_chains_detail_with_reasons` (junto a
  `res_model`/`res_id`) y la misma aserción en `test_ca3_omitted_destination_is_listed_in_detail`; se documentó
  CA-1/H-032 en el docstring del módulo. **NO** se tocó: la lógica de conteo/`result_note`/`state`/`quantity`,
  `_action_assign`, la vista ni ningún archivo de `x_product_dimensional_pricing`. Sin `cr.execute` de escritura /
  `cr.commit()`. **Evidencia de sintaxis:** `py_compile` de los 3 `.py` ⇒ **OK (exit 0)**. **Evidencia de tests
  (BD de test `pf_picker_tests` —NO la de producción—, `--data-dir` temporal, `--no-http`, `--max-cron-threads=0`,
  `-u printflow_gestion_inventario`, `--test-tags` con prefijo `/printflow_gestion_inventario:<Clase>` por clase,
  salida a `--logfile`):** exit **0**, **0 failed / 0 error(s) de 19 tests** ⇒ `TestProductFlowLotAssignBulkResult`
  **4/4** (incluye CA-1 con `views`), `TestProductFlowLotAssignBulk` **10/10** (CA-2..CA-9; su CA-7 fija el texto
  EXACTO de los 4 conteos ⇒ la cadena nueva **no** lo rompió) y `TestPendingNativeValidate` **5/5** (cubre la rama
  `others` de T2 sin regresión). Los avisos del log son los **pre-existentes** de O-6 (`Skipping deletion for
  missing XML ID` de `x_product_dimensional_pricing.menu_printflow_dashboards` / `printflow_health_center_*`):
  **ajenos** a T1–T3 y NO se tocan. Trabajo **solo de CÓDIGO**: 0 registros de la BD de producción tocados.
  **Plan §3.5 T1–T3 COMPLETO (0 pendientes en el lote).** Turno → **Odoo Verificador** (al cerrar el ciclo).
  **Pendiente del dueño:** recargar el módulo en el servidor 8071 (`-u printflow_gestion_inventario`) y volver a
  pulsar **"Asignar lote"**: el detalle debe abrir **sin error** mostrando el motivo por entrega.
- [2026-10-17 · Odoo Analista] **Cierre de ciclo 17/10-bis (compuerta de convergencia §4.3).** Evidencia
  aceptada del `odoo-verificador`: **veredicto `cumple`**, sin hallazgos nuevos. Cadena: contrato (Analista) →
  **UN lote `odoo-dev` (T1–T3)** → **verificación LIGERA** (una sola pasada). **Tarea NORMAL** (cableado de una
  ACCIÓN, no del flujo de inventario) ⇒ camino con Verificador por tocar 2 archivos de código + 1 de test.
  **Evidencia de tests del Dev (BD de test `pf_picker_tests`, NUNCA la de producción):** exit **0**,
  **0 failed / 0 error(s) de 19** ⇒ `TestProductFlowLotAssignBulkResult` **4/4** (incl. la nueva aserción CA-1
  de `views`), `TestProductFlowLotAssignBulk` **10/10** (su CA-7 fija el texto EXACTO de los 4 conteos ⇒ la
  cadena nueva no lo rompió) y `TestPendingNativeValidate` **5/5** (ejercita la rama `others` de T2).
  **Verificado por el Verificador (sin re-correr la suite):** `_preprocessAction` es el punto exacto del crash y
  la convención `[(False, 'form')]` es la MISMA que usa el core al normalizar acciones de primer nivel; el fix de
  T2 es **no mutante** (`dict(result)` + `setdefault`) ⇒ motor intacto; `py_compile` OK; sin `cr.execute` de
  escritura / `cr.commit()`; motor `x_product_dimensional_pricing` **SIN CAMBIOS** (mtime 01/10 y 15/10, previos
  al ciclo); texto CA-7 y `nxt` sin `result` (⇒ `act_window_close`) **retro-compatibles**.
  **Hallazgos: H-032 y H-033 pasan a `resuelto`** → **8 abiertos** (H-001 · H-002 · H-005 · H-006 · H-015 ·
  H-016 · H-018 · H-028). **Tarea CERRADA.**
  **Nota de cobertura (H-033):** no tiene candado propio; su rama `others` queda ejercitada por
  `TestPendingNativeValidate` (5/5). Si se quiere blindar, se abre como tarea aparte — **no** es defecto.
  **Pendiente del dueño:** (1) **reiniciar/actualizar el módulo** en el servidor 8071
  (`-u printflow_gestion_inventario`) para recargar `wizard/printflow_flow_lot_assign_bulk.py` y
  `models/printflow_node_pending_line.py`; (2) **reprobar** el botón **"Asignar lote"** (debe abrir el detalle
  sin error, con el motivo por entrega); (3) sigue en pie la **acción de DATOS (H-018)**: asignar lote a las 26
  entregas con un lote **CON existencia** (`666634` = 23 u) y el check de asignación parcial (demanda 30 u).
  **Regla respetada: código sí, datos no** — 0 registros de la BD de producción tocados.
- [2026-10-17 · Odoo Dev] **Lote 1 (T1–T3) ejecutado** — núcleo del reparto multi-lote (H-037 / H-036).
  Sesión NUEVA; no se retomó ninguna anterior. **(T1)** `models/stock_move.py`: docstring del módulo extendido
  con el bloque *"Reparto ADITIVO multi-lote (H-037)"* (por qué el camino del motor `_pf_reassign_lot` no era
  aditivo: libera ANTES de reservar) y método NUEVO `_pf_reassign_lots(self, lots)` en sección propia
  `# REPARTO ADITIVO MULTI-LOTE`: `ensure_one()` → salida temprana si no hay lotes o `tracking != 'lot'` →
  **guardián** (`self.picked or self.state in ('done','cancel')` ⇒ `0.0`) → `need = product_uom_qty` →
  **UNA** `_pf_unreserve_reservation()` (primitiva del MOTOR) → bucle `for lot in lots` con
  `remaining = need - taken`, corte en `<= _EPS` y `taken += self._pf_reserve_lot(lot, remaining)`
  (primitiva del MOTOR, **ADITIVA** por `_update_reserved_quantity`). `_pf_keep_current_lot_reservation` y
  `_assign_exclusive_lot` (H-030) quedan **INTACTOS**. **(T2)** `wizard/printflow_product_flow.py`: constante
  de módulo `_SPLIT_KINDS = ('missing_move', 'pending_order')` (lista blanca explícita, se consulta con `in`,
  **nunca `getattr`**) + `@api.model _pf_assign_lots_to_document(self, target_kind, res_model, res_id, lots,
  product=None)` (guardia `_pf_assert_can_clean()` → `UserError` si `lots` vacío → `0.0` si el `kind` no está
  en la lista blanca → resolver del movimiento → `move._pf_reassign_lots(list(lots))`) + resolver PRIVADO
  propio `@api.model _pf_split_target_move(self, res_model, res_id, product)` (mismo camino que
  `_pf_assign_lot_on_pending_order_doc` pero SIN tocar el handler existente: `stock.move` directo o
  `stock.picking` filtrando el movimiento activo del producto, `limit=1`). `_pf_assign_lot_to_document`, el
  mapa `handlers`, `_pf_assign_lot_on_*` y `_pf_reassign_move_lot` quedan **INTACTOS** (el modo `single` no
  cambia: `git diff --stat` = **solo inserciones**, 0 borrados). **(T3)**
  `wizard/printflow_flow_lot_candidate.py`: campo NUEVO `is_in_split = fields.Boolean(string='Incluir')` junto
  a `is_selected`, con docstring del módulo extendido (la fila sirve a TRES superficies). NO se tocaron `write`,
  `_pf_enforce_single_selection`, `_pf_parent`, `_compute_is_picked`, `_compute_is_recommended` ni
  `_compute_is_elective` ⇒ la selección ÚNICA de `is_selected` sigue intacta (**H-036**: multi-tick
  independiente). **Evidencia de sintaxis:** `python -m py_compile` de los 3 `.py` ⇒ **OK (exit 0)**.
  **Evidencia estática (script de solo lectura):** los 3 métodos/campos nuevos existen; los candados del
  lote anterior (`_pf_keep_current_lot_reservation`, `_assign_exclusive_lot`, `_pf_assign_lot_to_document`,
  `_pf_reassign_move_lot`, `_pf_enforce_single_selection`, `is_selected`) **presentes**; sin `cr.execute(` ni
  `cr.commit(` reales (solo menciones en docstrings). **NO se corrió la suite:** los tests del reparto son la
  **T8 (Lote 3)** y requieren `-u printflow_gestion_inventario` ⇒ queda para el lote de tests / el Verificador
  (esta sesión NO reinicia ni actualiza Odoo, §9). **Motor `x_product_dimensional_pricing`: NO tocado por esta
  sesión** (`models/stock_move.py` del motor **fuera** de su `git status`; se consumen tal cual
  `_pf_unreserve_reservation` / `_pf_reserve_lot`). **OBSERVACIÓN FUERA DE ALCANCE (no tocada, para el
  Analista):** el repo del motor tiene un `git diff` **no vacío PRE-EXISTENTE** (22 archivos, ~2025+/1744−,
  p. ej. `models/mrp_technical_sheet.py`, `wizard/mrp_quick_purchase_wizard.py`) ajeno a este lote; el plan
  §3.6.3 dice "motor SIN CAMBIOS" ⇒ se reporta pero **no** se revierte ni se toca (el `stock_move.py` del
  motor sí está limpio). **Regla respetada: código sí, datos no** — 0 registros de la BD `Ciber Estudios 2015
  RESTAURADA` escritos. **Plan §3.11 Lote 1 (T1–T3) COMPLETO (0 pendientes).** Turno → **Odoo Dev**
  (Lote 2: T4–T6, sesión NUEVA).
- [2026-10-17 · Odoo Dev] **Lote 2 (T4–T6) ejecutado** — contenedor en MODO reparto + acción de bandeja +
  vistas (H-037 / H-036). Sesión NUEVA; no se retomó ninguna anterior; no se tocaron tareas `[x]` ni las del
  Lote 3.
  **(T4) `wizard/printflow_flow_lot_assign_bulk.py`:** campos NUEVOS `mode` (Selection `single`/`split`,
  default `'single'`, readonly) y `split_note` (Char compute VISIBLE); `_compute_split_note`
  (`@api.depends('candidate_ids.is_in_split','candidate_ids.lot_name','candidate_ids.available_here',
  'candidate_ids.available','total_demand')`, orden = el de la tabla vía `filtered('is_in_split')`, texto guía
  si no hay marcados, `%.2f` sin sufijos); `_pf_populate(self, product, rows, omitted_count=0, mode='single')`
  (**argumento NUEVO con default** ⇒ los llamadores del modo `single` no cambian) con `'mode': mode` en el
  `create`; `_pf_split_lots()` (lista ORDENADA de `stock.lot`); `_pf_check_split_coverage(lots)` (D3: libre por
  ubicación efectiva vía `stock.quant._get_available_quantity` o `Σ available` de los marcados si
  `multi_location`; `UserError` guía si `<= _EPS` o si no alcanza sin `confirm_partial`; **no escribe**);
  `action_split_lot_bulk()` (mismo esqueleto del `single`: guardia `_pf_assert_can_clean` → `reason`
  obligatorio → política `_pf_exception_policy` → cobertura → bucle FIFO con captura de `UserError` POR
  destino → `_pf_line_breakdown` + clasificación `error`/`partial`/`assigned` → `_pf_log_split_document` →
  `_pf_build_from_bulk` + `_pf_result_notification`, **mismos 4 conteos**); `_pf_line_breakdown(line, lots)`
  (desglose *"Reparto: lote → qty · …"*, aviso de lotes sin existencia, `sudo()`, **no** toca
  `_pf_line_reserved`); `_pf_log_split_document(line, lots, reserved)` (patrón de `_pf_log_document`, que NO se
  toca). **INTACTOS:** `action_assign_lot_bulk`, `_pf_selected_lot`, `_pf_check_coverage`, `_pf_log_document`,
  `_pf_result_notification`, `_pf_line_reserved` (modo `single` byte a byte). Docstring del módulo extendido
  (dos modos) + contrato.
  **(T5) `wizard/printflow_flow_lot_tray.py`:** helper NUEVO `@api.model _pf_bulk_rows(self, records)` que
  devuelve `(product, rows, omitted)` **sin efectos secundarios ni notificaciones** (extracción
  BEHAVIOR-PRESERVING: filtro de asignables, `_pf_document_move`, descarte y **dedupe por `move.id`** se
  movieron TAL CUAL); `action_assign_lot_bulk` **conserva el mismo comportamiento observable** (mismos mensajes
  de vacío y mismo `act_window`) y ahora **solo delega** en el helper; `action_split_lot_bulk(self)` NUEVO
  (público, Odoo 17 rechaza privados por RPC): guardia → `records = self or search(active_domain)` →
  `_pf_bulk_rows` → `_pf_populate(..., mode='split')` → `act_window` con **`views` explícitos** al form
  `printflow_gestion_inventario.printflow_flow_lot_assign_bulk_view_form_split`. **NO** se tocaron
  `_pf_document_move`, `_pf_populate`, `_pf_rows_*`, `action_authorize_selected` ni el tree.
  **(T6) `wizard/printflow_flow_lot_assign_bulk_views.xml`:** `<record id="printflow_flow_lot_assign_bulk_view_form_split">`
  NUEVO (`name` = `printflow.flow.lot.assign.bulk.form.split`, `<form string="Repartir lotes en bloque">`) con
  `mode`/`multi_location` ocultos, grupo "Selección" con **los mismos rótulos** (H-031), aviso `alert-warning`
  de `multi_location`, grupo "Reparto" con `split_note` **VISIBLE** + `confirm_partial`/`confirm_exception` y su
  microcopy, grupo "Lotes" con `<field name="candidate_ids">` y un **`<tree>` INLINE** (`editable="bottom"`,
  mismas decoraciones, columna `is_in_split` `string="Incluir"` `readonly="not is_elective"`, secundarios
  `optional="hide"` y de apoyo `column_invisible="True"`), grupo "Destinos" con el **MISMO** tree readonly de
  `line_ids`, "Motivo de la asignación" con `reason` required y `<footer>` con `action_split_lot_bulk`
  (`btn-primary`, `fa-random`) + Cancelar; y al form del modo `single` **solo se le AGREGA** una frase al
  `<div class="text-muted">` de la ranura "Lotes" (H-036: "la casilla elige UN solo lote por corrida… para
  repartir usa 'Repartir lotes'"). **NO** se tocó el tree COMPARTIDO
  `printflow_flow_lot_candidate_view_tree` (R-5) ni `__manifest__.py` (la vista nueva es un `<record>` de un
  archivo YA declarado en `data`).
  **Evidencia de sintaxis:** `python -m py_compile` de `wizard/printflow_flow_lot_assign_bulk.py` y
  `wizard/printflow_flow_lot_tray.py` ⇒ **OK (exit 0)**.
  **Evidencia de carga + tests (BD de TEST `pf_picker_tests`, NUNCA la de producción):**
  `odoo-bin -c odoo.conf -d pf_picker_tests -u printflow_gestion_inventario --data-dir=<temp>
  --no-http --test-enable --test-tags /printflow_gestion_inventario:TestProductFlowLotAssignBulk,
  /printflow_gestion_inventario:TestProductFlowLotAssignBulkResult,… --stop-after-init --logfile=<archivo>`
  ⇒ **exit 1** por **UN** rojo, **1 failed / 0 error(s) de 110**. La carga del módulo **terminó sin error**
  ("Modules loaded.", 109 módulos) y la **vista NUEVA cargó** como `ir.ui.view(2070)` (su arch carga
  `mode`/`split_note`/`is_in_split` ⇒ los campos EXISTEN y resuelven; único aviso = `alert` sin `role`, el
  MISMO patrón que ya emitía el form `single` ⇒ no es regresión). Desglose (todos ejecutados):
  `TestLotManagement` 22, `TestProductFlowLotTray` 15, `TestProductFlowLotTrayDocument` 12,
  `TestProductFlowLotPicker` 11, `TestProductFlowLotAssignBulk` 10, `TestProductFlowLotTrayAuthorizeBulk` 5,
  `TestProductFlowLotTrayOrders` 5, `TestProductFlowOverReservationScoped` 5, `TestTrayAuthorizeCurrentLot` 5,
  `TestPfBulkValidatePreservesLot` 4, `TestProductFlowLotAssignBulkResult` 4,
  `TestProductFlowLotPickerCandidates` 4, `TestProductFlowLotCoupledChain` 3, `TestProductFlowLotPickerUx` 3,
  `TestProductFlowLotPendingOrderAssign` 2.
  **El ÚNICO rojo es PRE-EXISTENTE y AJENO (delta = 0):**
  `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  (`test_product_flow_lot_picker_ux.py:143`, `AssertionError: 6.0 != 8.0`) — el MISMO rojo ya documentado en el
  anexo **§3.K · O-4** (aritmética del propio test sobre existencias/reservas, ajeno a este lote; **B1/O-5 no
  se persigue**). **Nota de entorno (no del código):** el primer intento falló con
  `PermissionError [WinError 5]` sobre `sessions\filestore\pf_picker_tests` (escritura del `web_icon` de
  `views/printflow_inventory_health_views.xml:260`) ⇒ se re-corrió con `--data-dir` en un directorio
  ESCRIBIBLE (temp). Es un permiso del filestore de la instalación, **ajeno** a estos archivos (esa vista no se
  tocó).
  **NO se tocó** el motor `x_product_dimensional_pricing` (**solo lectura**; se consumen
  `_pf_unreserve_reservation`/`_pf_reserve_lot` tal cual); sin `cr.execute` de escritura ni `cr.commit()`; la
  ÚNICA escritura sigue siendo el protocolo NATIVO disparado por el operador. **Regla respetada: código sí,
  datos no** — 0 registros de `Ciber Estudios 2015 RESTAURADA` leídos o escritos (toda la evidencia se tomó en
  la BD de test).
  **Regresión REAL de T1 (CA-1) aún NO comprobable aquí:** el test del reparto es **T8 (Lote 3)**.
  **Plan §3.11 Lote 2 (T4–T6) COMPLETO (0 pendientes).** Turno → **Odoo Dev** (Lote 3: T7–T8, sesión NUEVA).
  **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para ver el botón **"Repartir lotes"** y el form del MODO reparto
  (el botón de cabecera es la **T7**, siguiente lote).

- [2026-10-17 · Odoo Dev] **Lote 3 (T7–T8) ejecutado** (sesión NUEVA). Cierra el plan §3.11 de H-037/H-036.
  **Archivos:**
  *(T7)* MODIFICADO `wizard/printflow_flow_lot_tray_views.xml` — botón de cabecera **"Repartir lotes"**
  (`name="action_split_lot_bulk"`, `type="object"`, `display="selection"`, `class="btn-secondary"`,
  `icon="fa-random"`), **HERMANO** de "Asignar lote" sobre la MISMA selección; abre el contenedor en
  `mode='split'`. **NO** se tocó ningún botón ni columna existente (H-029/H-031/H-032 intactos).
  *(T8)* NUEVO `tests/test_product_flow_lot_assign_bulk_split.py` (`TestProductFlowLotAssignBulkSplit`);
  MODIFICADO `tests/__init__.py` (registro junto a `test_product_flow_lot_assign_bulk_result`, motivo H-037/H-036).
  Cubre CA-1, CA-2, CA-3, CA-4, CA-5, CA-6 y CA-8 + el candado de SQL crudo.
  **Evidencia de carga + tests (BD de TEST `pf_picker_tests`, NUNCA la de producción):**
  `odoo-bin -c odoo.conf -d pf_picker_tests -u printflow_gestion_inventario --data-dir=<temp>
  --no-http --test-enable --test-tags /printflow_gestion_inventario:TestProductFlowLotAssignBulkSplit
  --stop-after-init --logfile=<archivo>`
  ⇒ **exit 0**, **0 failed / 0 error(s) de 8** (el lote nuevo, `TestProductFlowLotAssignBulkSplit`, **8/8 verde**).
  La carga del módulo **terminó sin error** y `wizard/printflow_flow_lot_tray_views.xml` **cargó sin error**
  (no aparece ningún `ERROR` tras su `loading`; los `External ID not found: x_product_dimensional_pricing.*`
  del log son del **motor** en su paso "Skipping deletion for missing XML ID", **pre-existentes y ajenos**).
  **Set de regresión del plan (§3.11) en UNA pasada — `--test-tags` con un spec por clase
  (`/printflow_gestion_inventario:Clase`):** `TestProductFlowLotAssignBulkSplit` (8, NUEVO),
  `TestProductFlowLotAssignBulk`, `TestProductFlowLotAssignBulkResult`, `TestProductFlowLotPendingOrderAssign`,
  `TestProductFlowLotTray`, `TestProductFlowLotTrayOrders`, `TestProductFlowLotTrayDocument`,
  `TestTrayAuthorizeCurrentLot`, `TestProductFlowLotPicker`, `TestProductFlowLotPickerCandidates`,
  `TestProductFlowLotPickerUx`, `TestProductFlowLotCoupledChain`, `TestLotManagement`,
  `TestPfBulkValidatePreservesLot`, `TestProductFlowOverReservationScoped`
  ⇒ **exit 1** por **UN** rojo, **1 failed / 0 error(s) de 113** (= 110 del Lote 2 − 5 de
  `TestProductFlowLotTrayAuthorizeBulk` + 8 del test NUEVO). **El ÚNICO rojo es PRE-EXISTENTE y AJENO
  (delta = 0):** `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  (`test_product_flow_lot_picker_ux.py:143`, `AssertionError: 6.0 != 8.0`) — el MISMO rojo ya documentado en
  §3.K · O-4 y en la entrada del Lote 2 (aritmética del propio test sobre existencias/reservas; **B1/O-5 no se
  persigue**). Todos los demás candados citados **VERDES**.
  **Regresión REAL de T1 (CA-1) COMPROBADA (no decorativa):** se revirtió TEMPORALMENTE el patrón aditivo de
  `models/stock_move.py::_pf_reassign_lots` (se sustituyó "1 liberación + N reservas acotadas por `remaining`"
  por "liberar+reservar la demanda completa por lote", que hace que el 2.º lote **pise** al 1.º) y se corrió
  solo `TestProductFlowLotAssignBulkSplit.test_ca1_split_reserves_all_marked_lots`
  ⇒ **exit 1**, `AssertionError: '1 asignadas' not found in '0 asignadas · 1 parciales · 0 omitidas · 0 con
  error.'` (**1 failed / 0 error(s) de 1**). El archivo se **restauró con `git checkout -- models/stock_move.py`**
  (diff vacío verificado): la reversión fue SOLO de diagnóstico, **en disco no quedó ningún cambio** ahí.
  **NO se tocó** el motor `x_product_dimensional_pricing` (**solo lectura**: se consumen
  `_pf_unreserve_reservation`/`_pf_reserve_lot` tal cual); sin `cr.execute` de escritura ni `cr.commit()`; la
  **ÚNICA** escritura sigue siendo el protocolo **NATIVO** disparado por el operador (la reserva ADITIVA del
  wizard). El candado del test nuevo audita los archivos TOCADOS por la tarea
  (`wizard/printflow_flow_lot_assign_bulk.py`, `wizard/printflow_flow_lot_tray.py`, `models/stock_move.py`) vía
  `get_module_path`, **no** al propio archivo de test (auditarse a sí mismo lo delataría por las agujas
  literales). **Regla respetada: código sí, datos no** — 0 registros de `Ciber Estudios 2015 RESTAURADA` leídos
  o escritos (toda la evidencia se tomó en la BD de test `pf_picker_tests`).
  **Plan §3.11 Lote 3 (T7–T8) COMPLETO (0 pendientes).** Turno → **Odoo Verificador** (una sola pasada, al
  cerrar todos los lotes). **Pendiente del dueño:** reiniciar/actualizar el módulo en el servidor 8071
  (`-u printflow_gestion_inventario`) para ver el botón **"Repartir lotes"** y el form del MODO reparto.
- [2026-10-17 · Odoo Analista] **CIERRE del ciclo H-037/H-036 — reparto multi-lote en bloque.** COMPUERTA DE
  CONVERGENCIA (§4.3): **APLICADA Y PASADA** ⇒ tarea **CERRADA**.
  *Checklist §3.11:* `T1–T8` **8/8 en `[x]`**, **0 pendientes** (plan completo en 3 lotes; cada lote en sesión
  **NUEVA** de `odoo-dev`, sin retomar la anterior).
  *Verificación (paso 4 · LIGERA, una sola pasada):* `odoo-verificador` = **`cumple`**, **sin hallazgos**;
  chequeo INDEPENDIENTE suyo: `py_compile` de los `.py` tocados + el test = **exit 0**, y lectura del `git diff`
  contra la Sección 3.
  *Evidencia de tests:* `TestProductFlowLotAssignBulkSplit` **8/8 verde** (CA-1..CA-6, CA-8 + candado de SQL
  crudo) y **regresión real de T1** comprobada (revertir el patrón aditivo ⇒ CA-1 falla; archivo restaurado con
  `git checkout`, diff vacío). Set de regresión: **113 tests, 1 rojo PRE-EXISTENTE y AJENO** (`TestProductFlowLotPickerUx`,
  `AssertionError: 6.0 != 8.0`; **delta = 0**, §3.K · O-4 / B1).
  *Restricciones duras:* ✅ **no** se forzó ningún flujo nativo (la reserva la ejecuta el protocolo **NATIVO**; se
  consumen `_pf_unreserve_reservation`/`_pf_reserve_lot` **tal cual**); ✅ **motor `x_product_dimensional_pricing`
  NO tocado** (solo lectura); ✅ sin `cr.execute` de escritura ni `cr.commit()`; ✅ **código sí, datos no** — **0**
  registros de `Ciber Estudios 2015 RESTAURADA` leídos o escritos (toda la evidencia se tomó en la BD de test
  `pf_picker_tests`).
  *Hallazgos:* **H-036** y **H-037** → **`resuelto`** (implementado y verificado). **H-034** sigue FUERA (§3.10 ·
  O-1; eje vecino: multi-**MOVIMIENTO**). **H-038** sigue `abierto` (riesgo de proceso del repo del MOTOR, ajeno
  a este módulo; se reporta al dueño, no se toca desde aquí). Contador de la Ficha: **13 → 11 abiertos**.
  *Git:* `88c0daf` (plan), `ef8c039`/`0ea7fde` (Lote 1), `56de92b`/`181b510` (Lote 2), `ebc6947`/`b2699b0`
  (Lote 3) — **todo subido a `origin/main`**. La Sección 3 pasó a **§3.N (ANEXO · TAREA CERRADA)**.
  **Firma del cierre:** Analista ✅ · Planificador ✅ · Dev ✅ (3 lotes) · Verificador ✅ (`cumple`).
  **Único pendiente = del DUEÑO (funcional, NO de código):** recargar el módulo en el 8071 y probar el botón
  **"Repartir lotes"** (ver §3.N · "pendiente del dueño").
- [2026-10-17 · Odoo Dev] **§3.O · Lote 1 `[motor]` (T1–T3) COMPLETO.** Grano de la decisión = **MOVIMIENTO**
  (H-039/H-040; H-034 queda cerrado por construcción en el contenedor). Fuente: `odoo-impreven` /
  `Ciber Estudios 2015 RESTAURADA` (solo lectura); ruta escrita: `C:\odoo_custom\printflow_gestion_inventario`.
  *Archivos (4; el motor `x_product_dimensional_pricing` **SIN cambios**):*
  (1) `wizard/printflow_flow_lot_assign_bulk_line.py` — T1: `lot_id` (decisión por fila, dominio sobre
  `bulk_id.product_id`/`candidate_lot_ids`), `own_lot_id`/`own_lot_name`/`own_lot_qty`,
  `sale_order_name`/`sale_line_id`, `move_id` re-rotulado **'Unidad'**; docstring del módulo al grano por unidad.
  (2) `wizard/printflow_flow_lot_assign_bulk.py` — T2: `_pf_prepare_rows` resuelve el **lote propio por
  movimiento** (lectura batch + `sale.order.line._get_exclusive_lot_name`, respaldo del `own_lot_name` de la
  bandeja; FIFO y dedupe intactos); `_pf_populate` escribe las claves nuevas y **pre-llena `lot_id`** solo si el
  lote propio tiene **existencia efectiva** (`available_here` / `available`, salida de la MISMA lectura de
  candidatos, sin N+1); `action_assign_lot_bulk` **reescrita**: guardia + motivo + política, guía si ninguna fila
  trae lote, y por fila `_pf_assign_lots_to_document(kind, 'stock.move', line.move_id.id, [line.lot_id])` con
  captura `UserError` POR FILA y bitácora por documento; rótulos `Unidades por asignar` / `Filas omitidas` y
  `selection_note` en unidades. (3) `wizard/printflow_flow_lot_tray.py` — T3: `_pf_bulk_rows` **expande** cada
  `pending_order` en **una fila por `stock.move` activo** (UNA búsqueda batch, `res_model`/`res_id` = albarán,
  `move_id` = movimiento exacto, `demand_qty` = `product_uom_qty`) y se **retira** `action_split_lot_bulk`.
  (4) `wizard/printflow_flow_lot_tray_views.xml` — **desvío declarado** (ver abajo): se borró el `<button
  name="action_split_lot_bulk">` (T5) porque la vista valida en carga que el método exista.
  *Verificación:* `py_compile` de los 3 `.py` **OK**; `-u printflow_gestion_inventario` en la BD de test
  `pf_picker_tests` **sin error de carga** (`--data-dir` propio: el `filestore` de `Program Files` es de otro
  usuario). En shell (solo lectura): `fields_get` de la línea con los 7 campos y `move_id='Unidad'`; dominio de
  `lot_id` = `[('product_id','=',bulk_id.product_id),('id','in',bulk_id.candidate_lot_ids)]`;
  `hasattr(tray,'action_split_lot_bulk') is False`; el contenedor **conserva** `mode`/`split_note`/`lot_id`
  (se retiran en T6, como manda el orden).
  *Tests (BD de test `pf_picker_tests`, no la restaurada):* set bandeja/pending/reparto **47 tests → 0 failed /
  6 error(s)**: los 41 verdes son `TestProductFlowLotPendingOrderAssign`, `TestProductFlowLotTray`,
  `TestProductFlowLotTrayOrders`, `TestProductFlowLotTrayDocument` y `TestProductFlowLotTrayAuthorizeBulk`
  (**CA-8 y candados de bandeja intactos**). Los 6 rojos son `TestProductFlowLotAssignBulkSplit`
  (`AttributeError: … tray … no attribute 'action_split_lot_bulk'`), esperados: **T8 RETIRA ese archivo**.
  `TestProductFlowLotAssignBulkResult` (4): **1 passed** (candado SQL) + **2 error** (el guard nuevo exige lote
  por fila; el test aún escribe `bulk.lot_id`) + **1 failed** (`'Unidades por asignar' != 'Entregas por
  asignar'`, el rótulo que T2 ordena cambiar); **T9 lo adapta**. `TestProductFlowLotAssignBulk` (modo `single`)
  también queda para **T8**. Ningún test nuevo en este lote (el del camino por unidad es **T7**).
  *Restricciones:* ✅ sin `cr.execute`/`cr.commit` (solo docstrings); ✅ no se forzó ningún flujo nativo (la ÚNICA
  escritura sigue siendo `_pf_assign_lots_to_document` → `stock.move._pf_reassign_lots` → primitivas NATIVAS del
  motor); ✅ motor **sin diff**; ✅ **código sí, datos no** — 0 escrituras en `Ciber Estudios 2015 RESTAURADA`.
  **Desviaciones declaradas:** (D-1) el `<button name="action_split_lot_bulk">` de la bandeja se borró en ESTE
  lote (T5 lo pedía): sin eso el módulo **no carga** (`ParseError: action_split_lot_bulk is not a valid action on
  printflow.flow.lot.tray`), porque la vista valida en carga; se prefirió borrar la superficie antes que dejar el
  método vivo (residuo que ninguna tarea posterior retiraba). No se tocó ningún otro botón ni el re-rotulado de
  "Asignar lote" (sigue para `odoo-vistas` en T5). (D-2) El docstring de `action_assign_lot_bulk` (bandeja) se
  actualizó al grano nuevo **sin cambio de comportamiento**. (D-3) `demand_qty` usa `move.product_uom_qty` como
  **respaldo** cuando la fila llega sin demanda. (D-4) El `own_lot_qty` de la fila se toma de `qty_on_hand` del
  candidato (existencia física, igual semántica que `_pf_annotate_lot_quantities` de la bandeja).
  **Inconsistencias del plan que se REPORTAN (no se arreglan aquí):** (I-1) T2 afirma que
  `test_product_flow_lot_assign_bulk_result.py` sigue verde, pero T2 cambia un rótulo que ese test afirma y el
  guard por fila choca con `bulk.lot_id`: solo se pone verde en **T9** (su propia tarea). (I-2) Igual con
  `test_product_flow_lot_assign_bulk_split.py`: T3 retira el método de la bandeja que ese test usa ⇒ rojo hasta
  **T8** (que lo retira). (I-3) T3 manda retirar el método pero deja su botón para T5 ⇒ **el módulo no carga**
  (ver D-1). **Riesgo abierto para Lote 2 (`odoo-vistas`):** el dominio de `lot_id` viaja como
  `bulk_id.product_id`/`bulk_id.candidate_lot_ids`; si el cliente no lo resolviera en el tree embebido, la
  salida declarada en T1 es usar `parent.`/campos `related` (no se implementó por no acumular campos sin uso).
  **Turno → siguiente: Lote 2 (T4–T5) `[pantalla]` (`odoo-vistas`).** Entre este lote y el Lote 2 **la pantalla
  NO se usa** (estado intermedio declarado). **Pendiente del dueño:** `-u printflow_gestion_inventario` en el
  8071 cuando lo indique el Analista.
- [2026-10-17 · Odoo Vistas] **§3.O · Lote 2 `[pantalla]` (T4–T5) COMPLETO.** Una sola pantalla de decisión por
  **unidad** (un movimiento = una fila = su selector de lote) + retiro de la superficie del reparto.
  Fuente: `odoo-impreven` / `Ciber Estudios 2015 RESTAURADA` (**solo lectura**; no se abrió la pantalla ni se
  ejecutó `-u` desde este turno). Ruta escrita: `C:\odoo_custom\printflow_gestion_inventario`. Motor
  `x_product_dimensional_pricing`: **SIN cambios** (no se abrió).
  *Archivos (2):*
  (1) `wizard/printflow_flow_lot_assign_bulk_views.xml` — **T4**: REESCRITO el record
  `printflow_flow_lot_assign_bulk_view_form` (`form string="Asignar lote en bloque"`, `create="false"`,
  `delete="false"`, **sin** `edit="false"` — la superficie ES una decisión): (a) técnicos ocultos
  `candidate_lot_ids`, `multi_location`; (b) `<group string="Selección">` con `product_id`, `source_label`,
  `total_demand` | `location_id`, `assignable_count`, `omitted_count`, `selection_note` (visible); (c) el
  `alert-warning` de `multi_location` (texto ajustado a "las unidades", sin cambio de forma); (d)
  `<group string="Unidades de la entrega" col="1">` con la guía *"Elige el lote de CADA unidad…"* y `line_ids` en
  **`<tree editable="bottom" create="false" delete="false">`** con `seq`(#), `label`(Entrega),
  `sale_order_name`(Pedido, `optional="hide"`), `sale_line_id`(Línea de pedido), `move_id`(Unidad),
  `own_lot_name`(Lote propio), `own_lot_qty`(Existencia), `lot_id`(Lote a asignar,
  `options={'no_create': True,'no_open': True}`, `readonly="not assignable"`), `demand_qty`(Demanda),
  `result`(Resultado), `result_note`(Nota, `optional="show"`) y ocultos
  `kind`/`res_model`/`res_id`/`assignable`/`location_id`, con decoraciones `success/warning/muted/danger`;
  (e) `<group string="Lotes con existencia" col="1">` con la nota informativa y `candidate_ids` en **tree INLINE
  de SOLO LECTURA** (`create="false" delete="false" editable="false"`) con Lote · Existencia · Reservado ·
  Disponible · Rol (`lot_name`, `qty_on_hand`, `reserved`, `available`, `role_label`) + `is_own_lot`,
  `is_elective`, `is_occupied` con `column_invisible="True"` — **sin ninguna columna de marca** (tabla
  INFORMATIVA, §3.3·6); (f) `<group string="Motivo de la asignación" col="1">` con `reason` **required** +
  microcopy; (g) `<footer>` con **"Asignar lote"** (`action_assign_lot_bulk`, `btn-primary`, `fa-tags`) +
  "Cancelar" (`special="cancel"`). **BORRADO** el record `printflow_flow_lot_assign_bulk_view_form_split`
  (el árbol del reparto, con su tabla de marcas `is_in_split` y su botón "Repartir lotes") — **sin residuo**.
  **NO** se tocó el tree COMPARTIDO `printflow_flow_lot_candidate_view_tree` ni `__manifest__.py`.
  (2) `wizard/printflow_flow_lot_tray_views.xml` — **T5**: `title` del botón `action_assign_lot_bulk`
  actualizado al contrato nuevo (*"Elige el lote de CADA unidad (cada fila es un movimiento de la entrega).
  ESCRIBE inventario por la vía NATIVA (reserva). Requiere jefe de taller/administrador"*). **NO** se tocó ningún
  otro botón de cabecera ni las columnas del tree (H-029/H-031/H-032 intactos).
  *Verificación (estática):* `xml.dom.minidom.parse` **OK** en los dos archivos; `grep` de
  `action_split_lot_bulk|is_in_split|view_form_split|Repartir lotes|split_note` sobre `wizard/*.xml` ⇒ **0**
  referencias de VISTA (los símbolos sobreviven solo en `.py`, que los retiran T6/T8); el record del reparto
  `printflow_flow_lot_assign_bulk_view_form_split` **ya no existe**. No se accionó ningún botón (BD de PRUEBA:
  abrir = lectura).
  *Métricas de diseño (skill `odoo-view-design`, §2 + `VIEW-REVIEW-CHECKLIST.md` corrido):* form =
  **6.548** caracteres, **4** `<div>`, **2** `colspan`, **6** `<group>`, **1** `<record>`. Referencia
  hermana MEDIDA: el form del selector por documento
  (`printflow_flow_lot_picker_views.xml`) = **9.649** caracteres / 10 `<div>` ⇒ el nuevo quedó **~32 % más
  pequeño** que su vecino. El form roza el techo nativo ~6K: se **justifica y declara** porque es **DOS
  tablas** (la de DECISIÓN con 12 columnas + la INFORMATIVA con 5), no texto; los **4 `<div>` son microcopy
  mandado por §3.O** (aviso `multi_location`, guía de la tabla, nota informativa, microcopy del motivo). Del
  checklist se corrigió un punto antes de entregar: se **quitaron los `colspan="2"` de los `<div>` que
  colgaban de un `<group col="1">`** ("div colspan dentro de group col=1 haciendo de reja"); quedan **2**
  `colspan` legítimos (la nota de selección dentro de un `<group>` de 2 columnas y el aviso a nivel de form).
  *Restricciones:* OK solo `views/` (`.xml`) — **sin** tocar `models/` ni el motor; OK árbol compartido del
  candidato intacto (CA-8 protegido); OK **código sí, datos no** — 0 escrituras en `Ciber Estudios 2015
  RESTAURADA` (no se abrió la pantalla ni se ejecutó `-u`).
  **Desviaciones declaradas:** (D-1) se **refrescó el comentario** del botón en la bandeja (T5 solo pedía el
  `title`): dejarlo describiendo "UN lote a N entregas" era residuo engañoso; no se agregó/quitó ningún botón ni
  columna. (D-2) El texto del `alert-warning` pasó de "los destinos" a "las unidades" (consecuencia declarada de
  D1, mismo contenido, sin cambio de forma).
  **Gap REPORTADO al Analista (no bloquea; NO se decide por cuenta propia):** el campo **`confirm_exception`** del
  contenedor —que `action_assign_lot_bulk` exige cuando la política de excepción ≠ `warn` (CA-6)— **no aparece en
  la lista de campos del form que fija T4**, así que la pantalla **no ofrece la casilla** para confirmar la
  excepción. El módulo carga y el camino por defecto (`warn`) funciona; con la política en otro valor, el
  operador **no podría confirmar desde la UI**. Queda a decisión del Analista (¿añadir la casilla al grupo
  "Motivo" o aceptarlo así?). **No** se añadió por no decidir campos fuera del plan.
  **Verificación en vivo: NO realizada en este turno** — es un lote `[pantalla]` y el plan (§3.O · "Verificación")
  sitúa la **verificación en vivo del `odoo-verificador` una sola vez, al final del ciclo** (tras los lotes 3–4).
  **Pendiente del dueño:** `-u printflow_gestion_inventario` en el 8071 (recarga de vistas) cuando lo indique el
  Analista. **Turno → siguiente: Lote 3 (T6–T8) `[motor]` (`odoo-dev`).**
- [2026-10-17 · Odoo Dev] **§3.O · Lote 3 `[motor]` (T6–T8) COMPLETO.** Retiro verificado del residuo del modo
  retirado + test NUEVO del camino POR UNIDAD (una fila = un movimiento = su lote) + retiro/adaptación de los tests
  de los modos viejos. Fuente: `odoo-impreven` / `Ciber Estudios 2015 RESTAURADA` (**solo lectura**: no se le
  ejecutó `-u` ni tests). Ruta escrita: `C:\odoo_custom\printflow_gestion_inventario`. Motor
  `x_product_dimensional_pricing`: **no se tocó** (solo se LEYÓ `models/sale_order_line.py:160-174` para confirmar
  que `_get_exclusive_lot_name` no depende de cantidades). Aviso: el `git diff` del repo del motor **no** es vacío,
  pero ese estado es **PRE-EXISTENTE** (repo del motor sin commits: todo el árbol figura modificado/untracked), así
  que **no** se usa como evidencia de CA-9; la evidencia es que ningún archivo del motor se abrió para escritura.
  *BD de trabajo (NUNCA la de producción):* se restauró un **clon** `pf_lote3_verif` desde `pg_dump` de la BD de
  PRUEBA y TODA la evidencia (`-u` + tests) se tomó ahí; el clon se **elimina** al cerrar el lote. La BD de PRUEBA
  quedó con **0 escrituras**.
  *Archivos (1 nuevo, 3 modificados, 1 borrado):*
  (1) **T6 — sin código nuevo en este turno: se VERIFICÓ el retiro que dejó la sesión cortada.**
  `wizard/printflow_flow_lot_assign_bulk.py` ya NO tiene `mode`, `split_note`, `_compute_split_note`, `lot_id` (del
  contenedor), `_pf_selected_lot`, `_pf_check_coverage`, `_pf_split_lots`, `_pf_check_split_coverage`,
  `_pf_log_split_document`, `action_split_lot_bulk` ni `confirm_partial` (y `_pf_populate` ya recibe solo
  `records`); `wizard/printflow_flow_lot_candidate.py` ya NO tiene `is_in_split`: `_compute_is_picked` depende solo
  de `picker_id.lot_id` + `lot_id`, `_pf_enforce_single_selection` espeja SOLO sobre `picker_id` (el contenedor no
  espeja nada) y el docstring declara las DOS superficies (selector + tabla informativa). `grep -E
  "is_in_split|split_note|action_split_lot_bulk|_pf_split_|_pf_check_coverage|_pf_log_split_document"` sobre
  `wizard/` ⇒ **0** en el contenedor y en el candidato. Lo que sí sobrevive es de OTRAS superficies y se conserva a
  propósito: `_pf_selected_lot` de `printflow_flow_lot_picker.py` y `_pf_split_target_move` de
  `printflow_product_flow.py` (los consume el camino VIVO) y `_pf_split_line_commands` del wizard de diagnóstico
  (parte líneas de pedido, ajeno).
  (2) **T7 NUEVO** `tests/test_product_flow_lot_assign_bulk_per_move.py` (`TestProductFlowLotAssignBulkPerMove`,
  **9 casos**, `@tagged('post_install','-at_install')`): CA-1 (superficie única: `mode`/`split_note`/`lot_id`/
  `confirm_partial` fuera del contenedor e `is_in_split` fuera del candidato), CA-2 (**cierra H-034**: 2 movimientos
  ⇒ 2 `line_ids` con 2 `move_id` distintos y `demand_qty = 1` cada una), CA-3/CA-4 (lote propio por fila + pre-llenado
  SOLO si tiene existencia; el vacío llega vacío y visible), CA-5 (2 lotes elegidos uno por fila ⇒ 2/2 reservado,
  cada movimiento con SU lote), CA-6 (guardia de permisos al ABRIR y al EJECUTAR, motivo obligatorio, política ≠
  `warn` sin `confirm_exception`), CA-7 (la fila parcial no frena a la otra; la fila sin lote queda `skipped` y no
  escribe), CA-10 (abrir/poblar el contenedor no altera `stock.quant`/`stock.lot`/`stock.move`) y el **candado** de
  SQL crudo sobre los archivos tocados (`cr.execute(`/`cr.commit(`).
  **Ajuste necesario del TEST (no del motor):** los helpers heredados creaban los 2 movimientos con
  `sale_line_id = False`; `sale_stock` agrega `sale_line_id` a `_prepare_merge_moves_distinct_fields`, así que dos
  movimientos IDÉNTICOS se **fusionan** en uno y el caso medía 1 fila. El camino por unidad es "una unidad = una
  línea de pedido" ⇒ CA-2/CA-5/CA-7/CA-10 crean **líneas de pedido distintas** (`_sale_lines(count=2)`) y las pasan a
  `_outgoing(...)`: el albarán conserva sus **2 movimientos** y el test mide lo que debe medir.
  (3) **T8** RETIRADO `tests/test_product_flow_lot_assign_bulk_split.py` (`git rm`) y su import en
  `tests/__init__.py` (sustituido por el registro del test nuevo, con el comentario del motivo **H-039/H-040 ·
  cierre H-034**). ADAPTADO `tests/test_product_flow_lot_assign_bulk.py`: `bulk.lot_id = lot.id` ⇒ **lote por FILA**
  (`line.lot_id`); `test_ca4_partial_requires_confirmation` REEMPLAZADO por `test_ca4_partial_is_reported_per_row`
  (ya no existe el check global de parcial) y `test_ca4_scarce_lot_reports_error_on_starved_destination`
  renombrado/adaptado a `test_ca4_scarce_lot_reports_error_on_starved_row` (clasificación POR FILA con nota).
  **Ningún test quedó en `skip`.** `grep -E "is_in_split|action_split_lot_bulk|split_note"` sobre `tests/` ⇒ solo
  las aserciones del test NUEVO (que comprueban justamente su ausencia).
  (4) **Desviación DEV-1 (declarada, mano `[motor]`)** — `wizard/printflow_flow_lot_assign_bulk_line.py`: el dominio
  de `lot_id` pasó de `bulk_id.product_id`/`bulk_id.candidate_lot_ids` a
  `parent.product_id`/`parent.candidate_lot_ids`. **Motivo:** con la ruta `bulk_id.` el módulo **NO CARGABA**
  (`Field 'bulk_id' used in domain of python field 'lot_id' … must be present in view but is missing`): Odoo 17
  exige que el campo del prefijo esté pintado en la sub-vista. La ruta `parent.` es el patrón NATIVO del core
  (`test_domain_on_field_in_subview_with_parent`) y la semántica es **IDÉNTICA** (solo lotes con existencia del
  producto, D4); el contenedor ya pinta `product_id` y `candidate_lot_ids`. Se resuelve en Python porque el árbol de
  T4 (vista) **no se tocó**; queda a ratificación del Analista / `odoo-vistas`.
  *Evidencia (clon `pf_lote3_verif`):* `py_compile` de los `.py` tocados ⇒ **exit 0**;
  `-u printflow_gestion_inventario` ⇒ **sin error de carga** (tras DEV-1).
  Corrida acotada del lote (antes de añadir el candado de SQL crudo):
  `--test-tags "/printflow_gestion_inventario:TestProductFlowLotAssignBulkPerMove,
  /printflow_gestion_inventario:TestProductFlowLotAssignBulk"` ⇒ **exit 0**, **0 failed / 0 error(s) de 18**
  (`PerMove` **8/8** + `Bulk` adaptado **10/10**). Pasada FINAL (ya con el candado = 9.º caso de `PerMove`):
  las MISMAS 2 clases (19 tests) + el set de candado del picker (`TestProductFlowLotPicker`, `…Candidates`,
  `…Component`, `…Exception`, `TestPickerAuthorizeSharedLot`, `TestFlowLotPickerNegativeReserved`, `…PickerUx`)
  ⇒ **exit 1**, **1 failed / 0 error(s) de 49**; **las 19 del lote, VERDES**. El ÚNICO rojo es
  **PRE-EXISTENTE y AJENO (delta = 0, B1)**:
  `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  (`test_product_flow_lot_picker_ux.py:143`, `AssertionError: 6.0 != 8.0 within 7 places (2.0 difference)`), ya
  documentado en **H-002** y en las bitácoras de los lotes anteriores (§3.K · O-4). Todos los demás candados VERDES.
  *Regresión REAL, no decorativa (lo que exige T7), con reversiones TEMPORALES y restauración verificada:*
  (a) **T3 revertido** (`_pf_bulk_rows`: `for move in moves:` ⇒ `moves[:1]`, sin expandir a movimientos) ⇒
  `test_ca2_two_moves_of_one_delivery_are_two_rows` **FALLA**: `AssertionError: 1 != 2` (**1 failed / 0 error de 1**):
  el contenedor trae 1 fila en vez de 2.
  (b) **T2 revertido** (el contenedor decide UN solo lote para todas las filas — el gesto pre-T2 "una caja para
  todas") ⇒ `test_ca5_per_row_lots_cover_both_moves` **FALLA**: `AssertionError: '2 asignadas' not found in
  '1 asignadas · 0 parciales · 0 omitidas · 1 con error.'` (**1 failed / 0 error de 1**): la segunda unidad se queda
  sin su lote.
  Los dos archivos se restauraron desde respaldo y se **verificó el SHA256** contra el original
  (`printflow_flow_lot_tray.py` = `DCDE79B7…505BB`; `printflow_flow_lot_assign_bulk.py` = `5494CC25…7F65C`): **en
  disco no quedó ningún cambio** de las reversiones (solo los cambios declarados de este lote).
  *Restricciones:* ✅ sin `cr.execute` de escritura ni `cr.commit()`; ✅ **no** se forzó ningún flujo nativo (la
  ÚNICA escritura sigue siendo `_pf_assign_lots_to_document` → `stock.move._pf_reassign_lots` → primitivas NATIVAS
  del motor: **0** `stock.quant` escritos a mano, **0** `stock.move` creados fuera de un picking, **0** estados
  forzados); ✅ motor `x_product_dimensional_pricing` **sin cambios** (solo lectura); ✅ **código sí, datos no** —
  **0** registros de `Ciber Estudios 2015 RESTAURADA` escritos.
  *Reportes (fuera de alcance; NO se toca):* (R-1) `tests/test_product_flow_lot_assign_bulk_result.py` sigue usando
  `bulk.confirm_partial`/`bulk.lot_id` ⇒ **esperado en ROJO hasta T9 (Lote 4)**. (R-2) El CA-4 por fila del set
  adaptado y el CA-7 del test nuevo cubren lo mismo desde dos superficies: se conservan ambos porque así lo manda el
  plan (T8 el primero, T7 el segundo); si el Analista quiere deduplicar, es tarea de retiro. (R-3) En la BD de
  PRUEBA el esquema del contenedor seguía **viejo** (`mode`/`lot_id`/`confirm_partial` en `fields_get`) porque el
  último `-u` real de esa BD **nunca completó** (rollback por el error de vista); el `-u` correcto lo debe correr el
  dueño.
  **Plan §3.O · Lote 3 (T6–T8) COMPLETO (0 pendientes).** **Turno → siguiente: Lote 4 (T9) `[motor]` (`odoo-dev`,
  sesión NUEVA).** Ojo: **T10** (`[pantalla]`, §3.O · Lote 5) sigue PENDIENTE por el gap de `confirm_exception` que
  reportó `odoo-vistas` en el Lote 2.
  **Pendiente del dueño:** reiniciar/actualizar el 8071 (`-u printflow_gestion_inventario`).
- [2026-10-18 · Odoo Dev] **§3.O · Lote 4 `[motor]` (T9) COMPLETO.** Adaptación de los tests del DETALLE (H-029)
  y revisión del camino `pending_order` al grano por UNIDAD, + revisión de los candados de bandeja/picker (delta
  reportado). Fuente: `odoo-impreven` / `Ciber Estudios 2015 RESTAURADA` (**solo lectura**: no se le ejecutó `-u`
  ni tests). Ruta escrita: `C:\odoo_custom\printflow_gestion_inventario`. Motor
  `x_product_dimensional_pricing`: **no se tocó** (0 archivos del motor abiertos para escritura).
  *BD de trabajo (NUNCA la de producción):* clon `pf_lote4_verif` restaurado desde `pg_dump` de la BD de PRUEBA;
  TODA la evidencia (`-u` + tests) se tomó ahí; el clon se **elimina** al cerrar el lote. La BD de PRUEBA quedó con
  **0 escrituras**.
  *Archivos (1 modificado):*
  (1) **T9 — ADAPTADO** `tests/test_product_flow_lot_assign_bulk_result.py` al detalle por MOVIMIENTO: los dos casos
  de CA-3 (`test_ca3_notification_chains_detail_with_reasons`, `test_ca3_omitted_destination_is_listed_in_detail`)
  pasan de `bulk.lot_id = lot.id` + `bulk.confirm_partial = True` (campos RETIRADOS en T6) a **lote POR FILA**
  (`for line in bulk.line_ids: line.lot_id = lot.id`): el MISMO lote (2 u) se elige en cada unidad y la parcial ya
  NO se bloquea en bloque (CA-7). Los 4 conteos del detalle (asignadas/parciales/omitidas/error) quedan **por
  UNIDAD** (`len(detail.line_ids) == len(bulk.line_ids)`) y `params['next']` sigue apuntando a
  `printflow.flow.lot.assign.bulk.result` con `views == [(False, 'form')]` (H-029/H-032 intactos).
  `test_ca4_selection_labels_and_note` actualiza los rótulos al grano nuevo: `assignable_count` =
  **"Unidades por asignar"**, `omitted_count` = **"Filas omitidas"** y el `selection_note` =
  *"Cada fila es una unidad (un movimiento de la entrega = una línea de pedido). N unidades por asignar = M
  unidades a entregar."*; `total_demand` CONSERVA su `digits` (D3). Docstring del módulo re-escrito al grano por
  unidad. **Ningún test en `skip`.**
  (2) **REVISADO sin cambio** `tests/test_product_flow_lot_pending_order_assign.py`: la fila `pending_order` de la
  bandeja sigue apuntando al ALBARÁN (`res_model='stock.picking'`; la bandeja NO cambia su grano) y el test ejercita
  el **selector por documento** (`action_open_lot_picker` → `Picker.action_assign_lot`), NO el contenedor ⇒ **0
  adaptaciones** (sus 2 casos verdes).
  (3) **REVISADOS los candados (delta = NINGUNO):** `test_product_flow_lot_tray.py`, `..._tray_orders.py`,
  `..._tray_document.py`, `..._tray_authorize.py`, `..._tray_authorize_bulk.py`, `..._lot_picker*.py`,
  `test_lot_management.py` y `test_pf_bulk_validate_preserves_lot.py` **no referencian** el contenedor
  (`grep "assign\.bulk|action_assign_lot_bulk"` ⇒ **0** coincidencias en esos archivos): su contrato es la BANDEJA y
  el SELECTOR POR DOCUMENTO, ajenos al grano del contenedor (§3.6). `grep` de los símbolos retirados
  (`is_in_split|split_note|action_split_lot_bulk|_pf_split_*`) sobre `tests/` ⇒ solo las **aserciones negativas**
  de `TestProductFlowLotAssignBulkPerMove.test_ca1_only_one_bulk_action_exists` (que comprueban justamente su
  AUSENCIA); **0** usos residuales.
  *Evidencia (clon `pf_lote4_verif`):* `python -m py_compile tests/test_product_flow_lot_assign_bulk_result.py` ⇒
  **exit 0**; `-u printflow_gestion_inventario` ⇒ **sin error de carga** (módulos cargados); corrida acotada
  `--test-tags` sobre el set de lote/bandeja/picker (14 clases) ⇒ **exit 1**, **1 failed / 0 error(s) de 110**; el
  set del lote, VERDE: `TestProductFlowLotAssignBulkResult` **4/4** (los 3 adaptados + el candado de SQL crudo),
  `TestProductFlowLotAssignBulkPerMove` **9/9**, `TestProductFlowLotAssignBulk` **10/10**,
  `TestProductFlowLotPendingOrderAssign` **2/2**, `TestProductFlowLotTray`, `…TrayOrders`, `…TrayDocument`,
  `TestTrayAuthorizeCurrentLot`, `…TrayAuthorizeBulk`, `TestProductFlowLotPicker` **11/11**, `…CoupledChain`,
  `TestLotManagement`, `TestPfBulkValidatePreservesLot` VERDES. El ÚNICO rojo es **PRE-EXISTENTE y AJENO (delta =
  0, B1/H-002)**: `TestProductFlowLotPickerUx.test_own_and_current_lots_are_listed_and_labeled`
  (`test_product_flow_lot_picker_ux.py:143`, `AssertionError: 6.0 != 8.0 within 7 places (2.0 difference)`), ya
  documentado en **H-002** y en las bitácoras de los lotes anteriores (§3.K · O-4 / §3.O · Lote 3).
  *Restricciones:* ✅ el archivo tocado NO contiene `cr.execute(`/`cr.commit(` (lo custodia su propio candado);
  ✅ **código sí, datos no** — **0** registros de `Ciber Estudios 2015 RESTAURADA` escritos (todo en el clon);
  ✅ motor `x_product_dimensional_pricing` **sin cambios**.
  *Desviaciones:* **ninguna** (T9 es solo adaptación/revisión de tests; no se tocó el motor del contenedor).
  **Plan §3.O · Lote 4 (T9) COMPLETO (0 pendientes).** **Turno → siguiente: Lote 5 (T10) `[pantalla]`
  (`odoo-vistas`, sesión NUEVA):** restituir `confirm_exception` en el form del contenedor (regresión de T4).
  **Pendiente del dueño:** reiniciar/actualizar el 8071 (`-u printflow_gestion_inventario`).
- [2026-10-17 · Odoo Vistas] **Lote 5 (T10) `[pantalla]` · camino rápido §4.1 · COMPLETO (0 pendientes).**
  Tarea: restituir `confirm_exception` en el form del contenedor (regresión de T4). **1 archivo, sin decisión
  de diseño.**
  (1) **Modificado** `wizard/printflow_flow_lot_assign_bulk_views.xml`: dentro del `<group string="Motivo de la
  asignación" col="1">`, se AÑADIÓ `<field name="confirm_exception" help="La política vigente exige confirmar la
  excepción."/>` **después** de `reason` (+ comentario XML breve con el motivo). **Nada más**: no se tocó ningún
  otro campo, grupo, ni el `<footer>`; no se tocó `confirm_partial` (retirado a propósito en T6 — la parcial se
  reporta por fila, CA-7). El campo **ya existe** en el modelo `printflow.flow.lot.assign.bulk`
  (`printflow_flow_lot_assign_bulk.py` L103-106, Boolean *"Confirmo la excepción"*), que la acción
  `action_assign_lot_bulk` exige cuando la política ≠ `'warn'` (CA-6) ⇒ era una **regresión de T4** (callejón sin
  salida para el operador con política estricta), no un campo nuevo.
  *Evidencia:* `python -c "xml.dom.minidom.parse(...)"` ⇒ **XML OK**; `grep confirm_exception` sobre la vista ⇒
  **1** ocurrencia. **Métricas de diseño (§2):** archivo **8634** chars · **4** `<div>` · **2** `colspan` · **6**
  `<group>` · **1** `help` · línea de texto más larga **204** chars. Mi delta es **+1 campo y +1 comentario**;
  el tamaño por encima del presupuesto del core (~6K) es **PRE-EXISTENTE de T4** (3 paneles informativos), **no**
  de esta tarea — **observación para el Analista**, no se corrige aquí (T10 dice "nada más").
  *Restricciones:* ✅ código sí, datos no — **0** escrituras a `Ciber Estudios 2015 RESTAURADA` (solo se editó un
  XML); ✅ motor `x_product_dimensional_pricing` **sin cambios**; ✅ no se forzó ningún flujo nativo.
  *Desviaciones:* **ninguna** (la vista no se pudo abrir en navegador: no se reinició Odoo/`-u` por regla §6
  ⇒ **sin verificación en vivo**, la hace el `odoo-verificador` al cerrar el ciclo, junto con CA-6).
  **Plan §3.O: Lotes 1–5 CERRADOS. Ciclo completo para el Verificador.**
  **Pendiente del dueño:** reiniciar/actualizar el 8071 (`-u printflow_gestion_inventario`) y probar el camino.

