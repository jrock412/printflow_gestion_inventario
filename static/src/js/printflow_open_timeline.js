/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Widget genérico "m2o -> enlace que abre una acción de objeto".
 *
 * Muestra el NOMBRE del registro como un enlace clickeable que, al hacer clic,
 * dispara un método de OBJETO sobre el PROPIO registro de la fila (sin botón
 * dedicado). El modelo destino se deriva del propio registro
 * (``record.resModel``) y el método es configurable por ``options.action``.
 *
 * Uso:
 *   * Diagnóstico de Pedido (Nivel 1): campo ``product_id`` del árbol de
 *     ``product_line_ids``. Sin ``options`` => default ``action_open_product``
 *     (abre la línea de tiempo del producto).
 *   * Catálogo Productos (lista): campo ``product_id`` con
 *     ``options="{'action': 'action_open_flow'}"`` (drill-down al diagrama).
 *
 * ``displayName``, la plantilla XML y el uso de ``doActionButton`` se conservan
 * para no romper el caso ya probado del selector de diagnóstico.
 */
export class PrintflowOpenTimelineField extends Component {
    static template = "x_product_dimensional_pricing.PrintflowOpenTimelineField";
    static props = {
        ...standardFieldProps,
        actionMethod: { type: String, optional: true },
    };
    // Default seguro: el selector del diagnóstico conserva su comportamiento
    // aunque su vista no declare ``options``.
    static defaultProps = {
        actionMethod: "action_open_product",
    };

    setup() {
        this.action = useService("action");
    }

    get displayName() {
        const value = this.props.record.data[this.props.name];
        if (Array.isArray(value)) {
            return value[1] || "";
        }
        return (value && value.display_name) || "";
    }

    async onClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        // Se invoca el botón de objeto vía el servicio de acciones para pasar
        // por `/web/dataset/call_button` (que aplica `clean_action` y agrega
        // `views`). Un `orm.call` directo iría por `call_kw`, que NO procesa la
        // acción, y `_preprocessAction` fallaría al hacer `action.views.map(...)`.
        await this.action.doActionButton({
            type: "object",
            name: this.props.actionMethod,
            resModel: this.props.record.resModel,
            resId: this.props.record.resId,
            context: {},
        });
    }
}

registry.category("fields").add("printflow_open_timeline", {
    component: PrintflowOpenTimelineField,
    displayName: _t("Abrir línea de tiempo"),
    supportedTypes: ["many2one"],
    // Cero hardcodeo del método: la vista decide el método vía
    // ``options="{'action': '<metodo>'}"``; sin options, default seguro.
    extractProps: ({ options }) => ({
        actionMethod: (options && options.action) || "action_open_product",
    }),
});
