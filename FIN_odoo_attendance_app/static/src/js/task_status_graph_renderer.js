/** @odoo-module **/

import { graphView } from "@web/views/graph/graph_view";
import { GraphRenderer } from "@web/views/graph/graph_renderer";
import { registry } from "@web/core/registry";

const STATUS_COLOR_MAP = {
    pending: "#ef4444",
    in_process: "#3b82f6",
    done: "#22c55e",
};

class TaskStatusGraphRenderer extends GraphRenderer {
    getBarChartData() {
        const data = super.getBarChartData();
        const showProgressMeasure = this.model.metaData.measure === "progress_pct";
        data.datasets.forEach((dataset) => {
            const color = this._getStatusColor(dataset);
            if (color) {
                dataset.backgroundColor = color;
                dataset.borderColor = color;
            }
            if (showProgressMeasure) {
                // Keep 0% statuses visible (e.g., pending) while preserving true values.
                dataset.minBarLength = 3;
            }
        });
        return data;
    }

    _getStatusColor(dataset) {
        const statusKey = this._getStatusKey(dataset);
        if (!statusKey) {
            return null;
        }
        return STATUS_COLOR_MAP[statusKey];
    }

    _getStatusKey(dataset) {
        return (
            this._getStatusKeyFromDomain(dataset.domains) ||
            this._normalizeStatusLabel(dataset.label)
        );
    }

    _getStatusKeyFromDomain(domains) {
        if (!Array.isArray(domains)) {
            return null;
        }
        for (const domain of domains) {
            if (!Array.isArray(domain)) {
                continue;
            }
            for (const clause of domain) {
                if (!Array.isArray(clause) || clause.length < 3) {
                    continue;
                }
                const [fieldName, operator, value] = clause;
                if (fieldName !== "status") {
                    continue;
                }
                if (operator === "=") {
                    return value;
                }
                if (operator === "in" && Array.isArray(value) && value.length === 1) {
                    return value[0];
                }
            }
        }
        return null;
    }

    _normalizeStatusLabel(label = "") {
        return String(label)
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "_")
            .replace(/^_+|_+$/g, "");
    }
}

registry.category("views").add("task_status_graph", {
    ...graphView,
    Renderer: TaskStatusGraphRenderer,
});
