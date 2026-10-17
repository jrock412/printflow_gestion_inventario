/** @odoo-module **/
import { Component, onMounted, onPatched, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Widget del diagrama de línea de tiempo del Diagnóstico de Pedido.
 *
 * CENTRO DE OPERACIONES: dibuja el flujo FÍSICO completo del producto
 * (compra o fabricación -> recepción -> inventario/fabricación -> entrega ->
 * cliente). El backend manda:
 *
 *   * ``nodes``: nodos de CANVAS con geometría (``col``/``row``), ``tone``
 *     (semáforo decidido por el backend), ``role``/``parent``, ``actions``
 *     (popover resolutivo) y ``panel``/``tray`` (contenido del popover);
 *   * ``edges``: flujo secuencial + errores raíz -> consecuencia;
 *   * ``layout``: ``grid`` y ``cell``.
 *
 * El widget es PURO: NO decide negocio, solo pinta y dispara métodos/propósitos
 * existentes. Las acciones con efecto conservan los permisos del usuario.
 */

const STATUS_LABELS = {
    ok: _t("Sano"),
    na: _t("Sin dato / N/A"),
    pending: _t("Pendiente"),
    partial: _t("Entrega parcial"),
    error: _t("Cancelado"),
    deficit: _t("Sin stock"),
    over: _t("Stock en contención"),
    missing: _t("Falta comprar"),
    design: _t("Arte pendiente"),
    material: _t("Falta material"),
    no_mo: _t("Sin orden de fabricación"),
    late: _t("Retraso"),
    to_launch: _t("Sin lanzar"),
    no_supply: _t("Sin insumos"),
    in_progress: _t("OF en proceso"),
};

const ROLE_LABELS = {
    root: _t("Raíz"),
    consequence: _t("Consecuencia"),
    independent: _t("Independiente"),
};

// Acción del popover -> método EXISTENTE del modelo de falla (cero lógica nueva).
const FAILURE_METHODS = {
    problem: "action_open_problem",
    solution: "action_open_solution",
    second_remedy: "action_apply_second_remedy",
    inventory_health: "action_open_inventory_health",
};

// Geometría: grilla (col/row -> px). Son solo FALLBACK: el widget lee la
// geometría real desde `payload.layout.cell` (fuente única en el backend), de
// modo que ya NO hay números duplicados. Deben coincidir con `_PF_FLOW_CELL`.
const CELL_W = 176;
const CELL_H = 132;
const GAP_X = 24;
const GAP_Y = 28;
const PAD_TOP = 72;
const SVG_W = 1376;
const SVG_H = 480;
// Margen inferior del lienzo: deja aire bajo la última fila de nodos. El alto
// real del lienzo sale de PAD_TOP + filas*CELL_H + gaps + este margen (NO del
// SVG_H fijo, que reservaba ~2,6x de más y encogía el diagrama).
const BOTTOM_PAD = 16;
const ERROR_LANE_Y = 22;
// Margen de seguridad al calcular el alto disponible para el "fit".
const FIT_MARGIN = 12;

// Escala mínima del "fit" del diagrama. Por debajo de esto se prefiere el
// scroll horizontal (fallback) antes que un texto ilegible.
const MIN_FIT_SCALE = 0.7;

// Escala MÁXIMA del "fit": el canvas de 2 filas es angosto (576 px con 3
// columnas, 776 px con 4) frente a un modal amplio. Se permite crecer por encima
// de 1 para APROVECHAR el ancho y que el texto se vea GRANDE. `transform:
// scale()` sobre DOM re-rasteriza el texto (no emborrona como una imagen), así
// que 1.3 es legible y no se siente desproporcionado.
const MAX_FIT_SCALE = 1.3;

// El carril "entre filas" del diagrama de 2 filas lo comparten DOS aristas: el
// RETORNO secuencial (verde, último de fila 0 -> primero de fila 1) y las
// flechas de ERROR raíz -> consecuencia (rojo). Para que NO se pinten encima se
// separan en DOS sub-carriles: el retorno sube RETURN_LANE_DY sobre el centro
// del hueco y el error baja ERROR_LANE_DY, con 10 px de separación total (cabe
// de sobra en gap_y = 28 px).
const RETURN_LANE_DY = 5;
const ERROR_LANE_DY = 5;

// Sufijo único por instancia para los ids de los <marker> (evita colisiones).
let UID_SEQ = 0;

export class PrintflowOrderTimelineField extends Component {
    static template = "x_product_dimensional_pricing.PrintflowOrderTimelineField";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
        this.rootRef = useRef("root");
        this.fitRef = useRef("fit");
        this.uid = ++UID_SEQ;
        this.state = useState({
            openKey: null,
            hoverRoot: null,
            // Fit del lienzo: escala, alto ya escalado y desplazamiento X para
            // centrarlo. La geometría interna NO se toca (sigue en px).
            fit: { scale: 1, height: SVG_H, offsetX: 0, overflow: false },
        });
        this._fitRaf = null;
        this._lastWidth = null;
        this._lastCanvasW = null;
        // Clic FUERA del diagrama cierra el popover.
        onMounted(() => {
            this.onDocumentClick = (ev) => {
                const root = this.rootRef.el;
                if (root && !root.contains(ev.target)) {
                    this.closePopover();
                }
            };
            document.addEventListener("click", this.onDocumentClick);
            this._markDialog();
            this.onWindowResize = () => this._scheduleFit();
            window.addEventListener("resize", this.onWindowResize);
            if (typeof ResizeObserver !== "undefined") {
                // Solo re-encajamos cuando cambia el ANCHO del lienzo (`fitRef`):
                // el alto lo fija el propio fit, así que observarlo generaría un
                // bucle. El ancho es independiente de la escala.
                this._resizeObserver = new ResizeObserver((entries) => {
                    for (const entry of entries) {
                        const width = entry.contentRect.width;
                        if (this._lastWidth === null
                            || Math.abs(width - this._lastWidth) > 0.5) {
                            this._lastWidth = width;
                            this._scheduleFit();
                        }
                    }
                });
                if (this.fitRef.el) {
                    this._resizeObserver.observe(this.fitRef.el);
                }
            }
            this._scheduleFit();
        });
        // El wizard reutiliza el widget al cambiar de producto (no se
        // remonta): si el payload cambia el ancho del lienzo, re-encajamos.
        onPatched(() => {
            const canvasW = this.svg.width;
            if (this._lastCanvasW === null || canvasW !== this._lastCanvasW) {
                this._lastCanvasW = canvasW;
                this._scheduleFit();
            }
        });
        onWillUnmount(() => {
            document.removeEventListener("click", this.onDocumentClick);
            window.removeEventListener("resize", this.onWindowResize);
            if (this._resizeObserver) {
                this._resizeObserver.disconnect();
            }
            if (this._fitRaf) {
                cancelAnimationFrame(this._fitRaf);
                this._fitRaf = null;
            }
            this._unmarkDialog();
        });
    }

    _dialogEl() {
        const root = this.rootRef.el;
        return root ? root.closest(".modal-dialog") : null;
    }

    /** Marca el modal del wizard para poder ensancharlo por SCSS (Odoo 17 no
     *  lee el atributo `size` de <form>; el ancho solo se controla por CSS). */
    _markDialog() {
        const dialog = this._dialogEl();
        if (dialog) {
            dialog.classList.add("o_pf_diag_modal");
        }
    }

    _unmarkDialog() {
        const dialog = this._dialogEl();
        if (dialog) {
            dialog.classList.remove("o_pf_diag_modal");
        }
    }

    _scheduleFit() {
        if (this._fitRaf) {
            return;
        }
        this._fitRaf = requestAnimationFrame(() => {
            this._fitRaf = null;
            this._fit();
        });
    }

    /**
     * Ajusta (fit) el lienzo COMPLETO —nodos, flechas, píldoras y leyenda— al
     * espacio real disponible, conservando proporciones y la posición relativa
     * de los conectores.
     *
     * Estrategia de MÍNIMO RIESGO: la geometría interna sigue calculándose en px
     * (nada cambia en `svg`/`shapes`/`edges`); aquí solo se aplica un
     * `transform: scale()` sobre el lienzo. `transform-origin: top left` se
     * declara en SCSS y un `translateX` lo centra cuando sobra ancho.
     *
     * La altura disponible se calcula como el viewport menos TODO lo que no es
     * diagrama y está ENCIMA de él (encabezado del pedido, botones, título,
     * leyenda y cadena) más el header/pie del modal y un margen. Ese resto no
     * depende de la escala, por eso el cálculo no entra en bucle.
     */
    _fit() {
        this._markDialog();
        const root = this.rootRef.el;
        const fitEl = this.fitRef.el;
        if (!root || !fitEl) {
            return;
        }
        const canvasW = this.svg.width;
        const canvasH = this.svg.height;
        const availW = fitEl.clientWidth;
        if (!availW) {
            return;
        }

        const rootRect = root.getBoundingClientRect();
        // Alto disponible = viewport menos el "chrome" FIJO que vive ENCIMA del
        // diagrama (encabezado del pedido, botones, título, leyenda y cadena)
        // más el header y el footer del modal y un margen. Se mide SOLO lo de
        // arriba (no `body.scrollHeight - rootRect.height`, que incluía la tabla
        // y era frágil): así el diagrama aprovecha el alto real y desaparece el
        // hueco vertical muerto.
        const body = root.closest(".modal-body");
        let availH = Math.round(window.innerHeight * 0.55);
        if (body) {
            const content = body.closest(".modal-content") || body;
            const header = content.querySelector(".modal-header");
            const footer = content.querySelector(".modal-footer");
            const dialog = content.closest(".modal-dialog");
            const bodyRect = body.getBoundingClientRect();
            const above = Math.max(0, rootRect.top - bodyRect.top);
            const headerH = header ? header.getBoundingClientRect().height : 0;
            const footerH = footer ? footer.getBoundingClientRect().height : 0;
            let chrome = 0;
            if (dialog) {
                const style = getComputedStyle(dialog);
                chrome = (parseFloat(style.marginTop) || 0)
                    + (parseFloat(style.marginBottom) || 0);
            }
            availH = window.innerHeight - headerH - above - footerH
                - chrome - FIT_MARGIN;
        }
        availH = Math.max(120, availH);

        const raw = Math.min(availW / canvasW, availH / canvasH);
        // Se permite escalar POR ENCIMA de 1 (hasta MAX_FIT_SCALE) para que el
        // canvas angosto llene el ancho disponible y el texto se vea grande; el
        // ancho sigue ganando como límite, así que nunca desborda (offsetX
        // centra) y nunca aparece scroll innecesario.
        const scale = Math.min(
            MAX_FIT_SCALE, Math.max(MIN_FIT_SCALE, raw));
        const overflow = raw < MIN_FIT_SCALE;
        const height = Math.round(canvasH * scale);
        const offsetX = Math.max(0, (availW - canvasW * scale) / 2);

        const prev = this.state.fit;
        if (Math.abs(prev.scale - scale) < 0.001
            && prev.height === height
            && Math.abs(prev.offsetX - offsetX) < 0.5
            && prev.overflow === overflow) {
            return;
        }
        this.state.fit = { scale, height, offsetX, overflow };
        root.classList.toggle("is-overflow", overflow);
    }

    get payload() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) {
            return { order: [], global: {}, nodes: [] };
        }
        try {
            return JSON.parse(raw);
        } catch {
            return { order: [], global: {}, nodes: [] };
        }
    }

    get nodes() {
        const payload = this.payload;
        const labelByKey = {};
        for (const node of payload.nodes || []) {
            labelByKey[node.key] = node.label;
        }
        return (payload.nodes || []).map((node) => ({
            ...node,
            // El tono del semáforo lo decide el BACKEND (`node.tone`).
            tone: node.tone || "na",
            roleClass: node.role || "none",
            hasIssues: (node.issues || 0) > 0,
            hasInfo: (node.info || 0) > 0,
            // Fase 3: aviso de PENDIENTES acumulados del hito + su acción de
            // navegación (dict del mismo shape que `actions[]`). `hasInfo`/`info`
            // se conservan por compatibilidad de tests.
            pending: node.pending || 0,
            // Etiqueta EXPLÍCITA del pendiente (aditiva, PrintFlow D5): dice DE
            // QUÉ son (p. ej. "OC sin confirmar", "por recibir") en vez del
            // genérico "pendiente(s)". El fallback conserva compatibilidad.
            pendingLabel: node.pending_label || "",
            // Magnitud del FALTANTE por hito (aditiva, PrintFlow D1): el déficit
            // real de Compras. El widget solo pinta el badge cuando es > 0; el
            // resto de nodos trae 0 y etiqueta vacía.
            shortfallQty: node.shortfall_qty || 0,
            shortfallLabel: node.shortfall_label || "",
            pendingAction: node.pending_action || null,
            summary: node.summary || "",
            summaryMore: node.summary_more || 0,
            // El backend manda un `status_label` ESPECÍFICO del hito (p.ej.
            // Entrega ok => "Entregado", Fabricación in_progress => "OF en
            // proceso"). Si no viene, cae al mapa genérico (compatibilidad).
            statusLabel: node.status_label
                || STATUS_LABELS[node.status]
                || STATUS_LABELS.na,
            roleLabel: ROLE_LABELS[node.role] || "",
            parentLabel: node.parent ? labelByKey[node.parent] || node.parent : "",
            actions: node.actions || [],
            panel: node.panel || [],
            tray: node.tray || [],
            rootLink: node.root_link || null,
            // Capa de EXPLICACIÓN (headline/what/why/how/severity). El backend
            // la emite SIEMPRE; el widget solo la pinta en el panel lateral.
            explain: node.explain || null,
            extraCount: node.extra_count || 0,
            // F1: reserva colgada detectada por el backend. El widget NO decide
            // negocio: solo pinta el badge cuando el payload lo marca.
            anomaly: !!node.anomaly,
        }));
    }

    get openNode() {
        if (!this.state.openKey) {
            return null;
        }
        return this.nodes.find((node) => node.key === this.state.openKey) || null;
    }

    /** Geometría de la celda, leída del PAYLOAD (fuente única del backend). */
    get cell() {
        const cell = (this.payload.layout && this.payload.layout.cell) || {};
        return {
            w: cell.w || CELL_W,
            h: cell.h || CELL_H,
            gap_x: cell.gap_x != null ? cell.gap_x : GAP_X,
            gap_y: cell.gap_y != null ? cell.gap_y : GAP_Y,
            pad_top: cell.pad_top != null ? cell.pad_top : PAD_TOP,
        };
    }

    /** Grilla (cols/rows) del payload: define el salto entre filas y el carril. */
    get grid() {
        const grid = (this.payload.layout && this.payload.layout.grid) || {};
        return { cols: grid.cols || 0, rows: grid.rows || 1 };
    }

    get svg() {
        const cell = this.cell;
        const nodes = this.payload.nodes || [];
        let maxCol = 0;
        let maxRow = 0;
        for (const node of nodes) {
            maxCol = Math.max(maxCol, node.col || 0);
            maxRow = Math.max(maxRow, node.row || 0);
        }
        const width = nodes.length
            ? (maxCol + 1) * cell.w + maxCol * cell.gap_x
            : SVG_W;
        // Alto REAL del lienzo: el hueco de las filas usadas (1 o 2 en
        // serpentina) más el margen inferior. NO se usa SVG_H como limitante
        // (queda solo como fallback sin nodos).
        const height = nodes.length
            ? cell.pad_top + (maxRow + 1) * cell.h + maxRow * cell.gap_y
                + BOTTOM_PAD
            : SVG_H;
        return { width, height };
    }

    _cellCenter(col, row) {
        const cell = this.cell;
        return {
            cx: col * (cell.w + cell.gap_x) + cell.w / 2,
            cy: cell.pad_top + row * (cell.h + cell.gap_y) + cell.h / 2,
        };
    }

    /**
     * Geometría de los nodos: cada nodo del payload trae su ``col``/``row`` y
     * ``kind``/``shape``. El widget solo traduce la celda a píxeles.
     */
    get shapes() {
        const cell = this.cell;
        const hover = this.state.hoverRoot;
        return this.nodes.map((node) => {
            const center = this._cellCenter(node.col || 0, node.row || 0);
            return {
                ...node,
                cx: center.cx,
                cy: center.cy,
                x: center.cx - cell.w / 2,
                y: center.cy - cell.h / 2,
                w: cell.w,
                h: cell.h,
                highlighted: !!hover && node.role === "consequence",
            };
        });
    }

    get edges() {
        const payload = this.payload;
        if (!Array.isArray(payload.edges) || !payload.edges.length) {
            return [];
        }
        const shapeByKey = {};
        for (const shape of this.shapes) {
            shapeByKey[shape.key] = shape;
        }
        const hover = !!this.state.hoverRoot;
        const edges = [];
        for (const edge of payload.edges) {
            const type = edge.type || "flow";
            const geometry = this._edgeGeometry(edge, shapeByKey);
            if (!geometry) {
                continue;
            }
            edges.push({
                ...edge,
                d: geometry.d,
                marker: this._markerRef(type),
                dashed: edge.style === "dashed",
                pill: edge.label
                    ? {
                          text: edge.label,
                          x: geometry.pill.x,
                          y: geometry.pill.y,
                          type,
                          tone: edge.tone || "na",
                      }
                    : null,
                highlighted: hover && type === "error",
            });
        }
        return edges;
    }

    _markerRef(type) {
        let kind = "flow";
        if (type === "error") {
            kind = "error";
        } else if (type === "branch") {
            kind = "branch";
        }
        return `url(#o_pf-arrow-${kind}-${this.uid})`;
    }

    /**
     * Convierte una arista lógica en el atributo `d` de un `<path>`:
     * tramo recto si es del mismo carril; el RETORNO entre filas (ortogonal por
     * el hueco); Bézier si salta de carril; y una curva por el CARRIL SUPERIOR
     * para las flechas de error (1 fila de fallback).
     */
    _edgeGeometry(edge, shapeByKey) {
        const from = shapeByKey[edge.from];
        const to = shapeByKey[edge.to];
        if (!from || !to) {
            return null;
        }
        const cell = this.cell;
        const hw = cell.w / 2;
        const hh = cell.h / 2;
        const sx = from.cx;
        const sy = from.cy;
        const tx = to.cx;
        const ty = to.cy;
        if (edge.type === "error") {
            return this._errorGeometry(from, to, sx, sy, tx, ty, hh, cell);
        }
        // RETORNO secuencial entre filas (2 filas): la arista que baja del
        // ÚLTIMO nodo de la fila 0 (extremo derecho) al PRIMER nodo de la fila 1
        // (extremo izquierdo). Se enruta ORTOGONAL por el hueco (sub-carril del
        // retorno) para NO cruzar por encima de los nodos.
        if (this.grid.rows >= 2 && from.row !== to.row) {
            return this._returnGeometry(from, to, sx, sy, tx, ty, hh, cell);
        }
        const dx = tx - sx;
        const dy = ty - sy;
        if (Math.abs(dx) >= Math.abs(dy)) {
            const x1 = sx + Math.sign(dx) * hw;
            const y1 = sy;
            const x2 = tx - Math.sign(dx) * hw;
            const y2 = ty;
            if (Math.abs(dy) < 1) {
                return {
                    d: `M ${x1} ${y1} L ${x2} ${y2}`,
                    pill: { x: (x1 + x2) / 2, y: y1 - 14 },
                };
            }
            const mx = (x1 + x2) / 2;
            return {
                d: `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`,
                pill: { x: mx, y: (y1 + y2) / 2 - 14 },
            };
        }
        const x1 = sx;
        const y1 = sy + Math.sign(dy) * hh;
        const x2 = tx;
        const y2 = ty - Math.sign(dy) * hh;
        const my = (y1 + y2) / 2;
        return {
            d: `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`,
            pill: { x: (x1 + x2) / 2 + 12, y: my },
        };
    }

    /**
     * Carriles del hueco ENTRE las dos filas del diagrama.
     *
     * El hueco va del borde inferior de la fila 0 al borde superior de la fila 1
     * y su centro está en `pad_top + h + gap_y/2`. Se divide en DOS sub-carriles
     * para que el retorno (verde) y el error (rojo) no se solapen: `flow` sube
     * RETURN_LANE_DY y `error` baja ERROR_LANE_DY.
     */
    _betweenRowsLanes(cell) {
        const base = cell.pad_top + cell.h + cell.gap_y / 2;
        return {
            flow: base - RETURN_LANE_DY,
            error: base + ERROR_LANE_DY,
        };
    }

    /**
     * RETORNO secuencial entre filas (verde): sale por el borde inferior del
     * nodo de la fila 0, baja al sub-carril del retorno, recorre el hueco
     * horizontalmente hasta la columna del destino y baja al borde superior del
     * nodo de la fila 1. Ortogonal, sin cruzar nodos.
     */
    _returnGeometry(from, to, sx, sy, tx, ty, hh, cell) {
        const laneY = this._betweenRowsLanes(cell).flow;
        const y1 = from.row === 0 ? sy + hh : sy - hh;
        const y2 = to.row === 0 ? ty + hh : ty - hh;
        return {
            d: `M ${sx} ${y1} L ${sx} ${laneY} L ${tx} ${laneY} L ${tx} ${y2}`,
            pill: { x: (sx + tx) / 2, y: laneY - 12 },
        };
    }

    /**
     * Carril de las flechas de ERROR raíz -> consecuencia.
     *
     * * 2 filas: usa el SUB-CARRIL del error (más abajo que el retorno verde)
     *   dentro del hueco entre filas. Trazado ORTOGONAL: sale por el borde del
     *   origen más cercano al carril (fila 0 -> borde inferior; fila 1 -> borde
     *   superior), recorre el hueco horizontal hasta la columna destino (sin
     *   cruzar nodos) y entra por el borde del destino más cercano al carril. La
     *   píldora se ancla al tramo horizontal.
     * * 1 fila (fallback): conserva el carril SUPERIOR actual (`ERROR_LANE_Y`).
     */
    _errorGeometry(from, to, sx, sy, tx, ty, hh, cell) {
        if (this.grid.rows < 2) {
            const x1 = sx;
            const y1 = sy - hh;
            const x2 = tx;
            const y2 = ty - hh;
            return {
                d: `M ${x1} ${y1} C ${x1} ${ERROR_LANE_Y}, ${x2} ${ERROR_LANE_Y}, ${x2} ${y2}`,
                pill: { x: (x1 + x2) / 2, y: ERROR_LANE_Y - 2 },
            };
        }
        const laneY = this._betweenRowsLanes(cell).error;
        const y1 = from.row === 0 ? sy + hh : sy - hh;
        const y2 = to.row === 0 ? ty + hh : ty - hh;
        return {
            d: `M ${sx} ${y1} L ${sx} ${laneY} L ${tx} ${laneY} L ${tx} ${y2}`,
            pill: { x: (sx + tx) / 2, y: laneY },
        };
    }

    closePopover() {
        if (this.state.openKey !== null) {
            this.state.openKey = null;
        }
    }

    onNodeClick(node, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!node.key) {
            return;
        }
        if (this.state.openKey === node.key) {
            this.closePopover();
            return;
        }
        this.state.openKey = node.key;
    }

    onNodeEnter(node) {
        if (node.role === "root") {
            this.state.hoverRoot = node.key;
        }
    }

    onNodeLeave(node) {
        if (node.role === "root") {
            this.state.hoverRoot = null;
        }
    }

    /** Abre el panel del nodo raíz referenciado por una consecuencia. */
    onRootLinkClick(node, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const target = node.rootLink && node.rootLink.target_key;
        if (target) {
            this.state.openKey = target;
        }
    }

    async onActionClick(node, action, ev) {
        ev.preventDefault();
        // stopPropagation evita que el clic burbujee al `onNodeClick` del nodo
        // (que abriría el popover). stopImmediatePropagation lo blinda frente a
        // cualquier otro listener del mismo elemento. El botón de pendientes y
        // las acciones del popover dependen de que el clic NO abra el popover.
        ev.stopPropagation();
        ev.stopImmediatePropagation();
        if (!action.enabled) {
            return;
        }
        if (action.method && action.res_model) {
            // `args` viaja como lista JSON (Odoo 17 lo parsea en
            // `doActionButton`). El popover usa el dispatcher público
            // `action_run_pf_node` y le pasa la CLAVE de la acción: así NUNCA
            // se invoca un método privado (`_pf_*`) por RPC.
            await this.action.doActionButton({
                type: "object",
                name: action.method,
                resModel: action.res_model,
                resId: action.res_id || undefined,
                context: {},
                args: action.args ? JSON.stringify(action.args) : undefined,
            });
            this.closePopover();
            return;
        }
        const method = FAILURE_METHODS[action.key];
        if (!method || !action.failure_id) {
            return;
        }
        // Reusa el método EXISTENTE del modelo de falla. El frontend no
        // ejecuta lógica de negocio.
        await this.action.doActionButton({
            type: "object",
            name: method,
            resModel: "printflow.order.diagnostic.failure",
            resId: action.failure_id,
            context: {},
        });
        this.closePopover();
    }

    /** Navega a un causante de la bandeja (tray) del nodo raíz. */
    async onTrayClick(item, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!item.res_model || !item.res_id) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: item.label || item.ref_name || _t("Detalle"),
            res_model: item.res_model,
            res_id: item.res_id,
            view_mode: "form",
            target: "current",
        });
        this.closePopover();
    }
}

registry.category("fields").add("printflow_order_timeline", {
    component: PrintflowOrderTimelineField,
    displayName: _t("Línea de tiempo (diagrama)"),
    supportedTypes: ["text", "char"],
});
