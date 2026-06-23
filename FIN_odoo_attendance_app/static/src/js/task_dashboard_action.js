/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const STATUS_ORDER = ["pending", "in_process", "done"];
const STATUS_META = {
    pending: { label: _t("Pending"), color: "#f59e0b" },
    in_process: { label: _t("In Process"), color: "#2563eb" },
    done: { label: _t("Done"), color: "#16a34a" },
};
const ANALYTIC_COLORS = ["#2563eb", "#ef4444", "#16a34a", "#f59e0b", "#7c3aed", "#0f766e", "#db2777", "#0891b2"];

export class TaskDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: null,
            allTasks: [],
            visibleTasks: [],
            employeeMap: {},
            taskAssigneeMap: {},
            filters: {
                search: "",
                taskId: "",
                dateFrom: "",
                dateTo: "",
                statusValues: [],
                employeeIds: [],
                analyticIds: [],
            },
            options: {
                employees: [],
                analytics: [],
            },
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        this.state.error = null;
        try {
            const tasks = await this.fetchAllTasks();
            const reportRows = await this.fetchAllDashboardReportRows();
            const { employeeMap, taskAssigneeMap } = this.buildReportMaps(reportRows, tasks);
            this.state.employeeMap = employeeMap;
            this.state.taskAssigneeMap = taskAssigneeMap;
            this.state.allTasks = tasks;
            this.state.options = this.buildOptions(tasks, employeeMap);
            this.applyFilters();
        } catch (error) {
            console.error("Failed to load task dashboard", error);
            this.state.error = _t("Failed to load task dashboard.");
            this.state.allTasks = [];
            this.state.visibleTasks = [];
        } finally {
            this.state.loading = false;
        }
    }

    async fetchAllTasks() {
        const fields = [
            "id",
            "x_task_number",
            "name",
            "description",
            "employee_id",
            "assignee_ids",
            "manager_id",
            "analytic_account_id",
            "target_start_date",
            "target_end_date",
            "progress",
            "status",
            "last_update_at",
            "priority",
            "active",
        ];
        const domain = [["active", "=", true]];
        const limit = 200;
        let offset = 0;
        const tasks = [];

        while (true) {
            const batch = await this.orm.searchRead("fin.employee.task", domain, fields, {
                limit,
                offset,
                order: "target_end_date asc, progress asc, id desc",
            });
            tasks.push(...batch);
            if (batch.length < limit) {
                break;
            }
            offset += limit;
        }
        return tasks;
    }

    async fetchAllDashboardReportRows() {
        const fields = ["task_id", "assignee_employee_id", "employee_id", "primary_employee_id"];
        const domain = [["active", "=", true]];
        const limit = 500;
        let offset = 0;
        const rows = [];

        while (true) {
            const batch = await this.orm.searchRead("fin.employee.task.dashboard.report", domain, fields, {
                limit,
                offset,
                order: "id asc",
            });
            rows.push(...batch);
            if (batch.length < limit) {
                break;
            }
            offset += limit;
        }
        return rows;
    }

    buildReportMaps(reportRows, tasks) {
        const employeeMap = {};
        const taskAssigneeMap = {};

        for (const row of reportRows) {
            const assigneeId = this.getMany2oneId(row.assignee_employee_id);
            const assigneeName = this.getMany2oneName(row.assignee_employee_id);
            if (assigneeId && assigneeName) {
                employeeMap[assigneeId] = assigneeName;
            }
            const employeeId = this.getMany2oneId(row.employee_id);
            const employeeName = this.getMany2oneName(row.employee_id);
            if (employeeId && employeeName) {
                employeeMap[employeeId] = employeeName;
            }
            const primaryId = this.getMany2oneId(row.primary_employee_id);
            const primaryName = this.getMany2oneName(row.primary_employee_id);
            if (primaryId && primaryName) {
                employeeMap[primaryId] = primaryName;
            }

            const taskId = this.getMany2oneId(row.task_id);
            if (!taskId || !assigneeId) {
                continue;
            }
            if (!taskAssigneeMap[taskId]) {
                taskAssigneeMap[taskId] = [];
            }
            if (!taskAssigneeMap[taskId].some((item) => item.id === assigneeId)) {
                taskAssigneeMap[taskId].push({
                    id: assigneeId,
                    name: assigneeName || `${_t("Employee")} #${assigneeId}`,
                });
            }
        }

        for (const task of tasks) {
            const taskId = task.id;
            if (!taskAssigneeMap[taskId]?.length) {
                const primaryId = this.getMany2oneId(task.employee_id);
                const primaryName = this.getMany2oneName(task.employee_id);
                if (primaryId) {
                    employeeMap[primaryId] = primaryName || employeeMap[primaryId] || `${_t("Employee")} #${primaryId}`;
                    taskAssigneeMap[taskId] = [{ id: primaryId, name: employeeMap[primaryId] }];
                }
            }
        }

        return { employeeMap, taskAssigneeMap };
    }

    buildOptions(tasks, employeeMap) {
        const employeeIds = new Set();
        const analytics = new Map();
        for (const task of tasks) {
            const primaryId = this.getMany2oneId(task.employee_id);
            if (primaryId) {
                employeeIds.add(primaryId);
            }
            for (const assigneeId of task.assignee_ids || []) {
                if (assigneeId) {
                    employeeIds.add(assigneeId);
                }
            }
            const analyticId = this.getMany2oneId(task.analytic_account_id);
            const analyticName = this.getMany2oneName(task.analytic_account_id);
            if (analyticId && analyticName) {
                analytics.set(analyticId, analyticName);
            }
        }

        return {
            employees: Array.from(employeeIds)
                .map((id) => ({ id, name: employeeMap[id] || `${_t("Employee")} #${id}` }))
                .sort((left, right) => left.name.localeCompare(right.name)),
            analytics: Array.from(analytics.entries())
                .map(([id, name]) => ({ id, name }))
                .sort((left, right) => left.name.localeCompare(right.name)),
        };
    }

    onSearchInput(ev) {
        this.state.filters.search = ev.target.value || "";
        this.applyFilters();
    }

    onTaskIdInput(ev) {
        this.state.filters.taskId = ev.target.value || "";
        this.applyFilters();
    }

    onDateFromInput(ev) {
        this.state.filters.dateFrom = ev.target.value || "";
        this.applyFilters();
    }

    onDateToInput(ev) {
        this.state.filters.dateTo = ev.target.value || "";
        this.applyFilters();
    }

    onStatusChange(ev) {
        this.state.filters.statusValues = this.getSelectedValues(ev.target.options);
        this.applyFilters();
    }

    onEmployeeChange(ev) {
        this.state.filters.employeeIds = this.getSelectedValues(ev.target.options).map((value) => parseInt(value, 10));
        this.applyFilters();
    }

    onAnalyticChange(ev) {
        this.state.filters.analyticIds = this.getSelectedValues(ev.target.options).map((value) => parseInt(value, 10));
        this.applyFilters();
    }

    getSelectedValues(options) {
        return Array.from(options || [])
            .filter((option) => option.selected)
            .map((option) => option.value);
    }

    clearFilters() {
        this.state.filters.search = "";
        this.state.filters.taskId = "";
        this.state.filters.dateFrom = "";
        this.state.filters.dateTo = "";
        this.state.filters.statusValues = [];
        this.state.filters.employeeIds = [];
        this.state.filters.analyticIds = [];
        this.applyFilters();
    }

    formatDateLabel(value) {
        if (!value) {
            return "";
        }
        const parsed = new Date(`${value}T00:00:00`);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        return parsed.toLocaleDateString([], {
            year: "numeric",
            month: "short",
            day: "numeric",
        });
    }

    summarizeLabels(labels, limit = 2) {
        const values = (labels || []).filter(Boolean);
        if (!values.length) {
            return "";
        }
        if (values.length <= limit) {
            return values.join(", ");
        }
        return `${values.slice(0, limit).join(", ")} +${values.length - limit}`;
    }

    removeFilterChip(chip) {
        if (!chip || !chip.type) {
            return;
        }
        if (chip.type === "search") {
            this.state.filters.search = "";
        } else if (chip.type === "task") {
            this.state.filters.taskId = "";
        } else if (chip.type === "date_from") {
            this.state.filters.dateFrom = "";
        } else if (chip.type === "date_to") {
            this.state.filters.dateTo = "";
        } else if (chip.type === "status") {
            this.state.filters.statusValues = this.state.filters.statusValues.filter((value) => value !== chip.value);
        } else if (chip.type === "employee") {
            this.state.filters.employeeIds = this.state.filters.employeeIds.filter((value) => value !== chip.value);
        } else if (chip.type === "analytic") {
            this.state.filters.analyticIds = this.state.filters.analyticIds.filter((value) => value !== chip.value);
        }
        this.applyFilters();
    }

    applyFilters() {
        const searchValue = (this.state.filters.search || "").trim().toLowerCase();
        const taskIdValue = (this.state.filters.taskId || "").trim().toLowerCase();
        const visibleTasks = this.state.allTasks.filter((task) => {
            if (this.state.filters.statusValues.length && !this.state.filters.statusValues.includes(task.status || "pending")) {
                return false;
            }
            if (this.state.filters.employeeIds.length) {
                const assigneeIds = this.getTaskAssigneeIds(task);
                const hasEmployee = this.state.filters.employeeIds.some((employeeId) => assigneeIds.includes(employeeId));
                if (!hasEmployee) {
                    return false;
                }
            }
            if (this.state.filters.analyticIds.length) {
                const analyticId = this.getMany2oneId(task.analytic_account_id);
                if (!analyticId || !this.state.filters.analyticIds.includes(analyticId)) {
                    return false;
                }
            }
            if (!this.taskMatchesDateRange(task, this.state.filters.dateFrom, this.state.filters.dateTo)) {
                return false;
            }
            if (taskIdValue) {
                const taskNumber = (task.x_task_number || "").toLowerCase();
                const numericId = String(task.id || "").toLowerCase();
                if (taskNumber !== taskIdValue && numericId !== taskIdValue) {
                    return false;
                }
            }
            if (!searchValue) {
                return true;
            }
            const haystack = [
                task.x_task_number || "",
                task.name || "",
                task.description || "",
                String(task.id || ""),
                this.getMany2oneName(task.analytic_account_id) || "",
                this.getTaskAssigneeNames(task).join(" "),
            ]
                .join(" ")
                .toLowerCase();
            return haystack.includes(searchValue);
        });
        this.state.visibleTasks = visibleTasks;
    }

    taskMatchesDateRange(task, dateFrom, dateTo) {
        if (!dateFrom && !dateTo) {
            return true;
        }
        const start = this.parseServerDate(task.target_start_date);
        const end = this.parseServerDate(task.target_end_date);
        if (!start || !end) {
            return false;
        }
        const fromDate = dateFrom ? new Date(`${dateFrom}T00:00:00`) : null;
        const toDate = dateTo ? new Date(`${dateTo}T23:59:59`) : null;
        if (fromDate && end < fromDate) {
            return false;
        }
        if (toDate && start > toDate) {
            return false;
        }
        return true;
    }

    parseServerDate(value) {
        if (!value) {
            return null;
        }
        return new Date(String(value).replace(" ", "T") + "Z");
    }

    getMany2oneId(value) {
        return Array.isArray(value) ? value[0] : null;
    }

    getMany2oneName(value) {
        return Array.isArray(value) ? value[1] : "";
    }

    getTaskAssigneeIds(task) {
        const mappedIds = (this.state.taskAssigneeMap[task.id] || []).map((item) => item.id);
        if (mappedIds.length) {
            return mappedIds;
        }
        const ids = Array.isArray(task.assignee_ids) ? [...task.assignee_ids] : [];
        const primaryId = this.getMany2oneId(task.employee_id);
        if (!ids.length && primaryId) {
            ids.push(primaryId);
        } else if (primaryId && !ids.includes(primaryId)) {
            ids.push(primaryId);
        }
        return ids;
    }

    getTaskAssigneeNames(task) {
        const mappedAssignees = this.state.taskAssigneeMap[task.id] || [];
        if (mappedAssignees.length) {
            return mappedAssignees.map((item) => item.name).filter(Boolean);
        }
        return this.getTaskAssigneeIds(task)
            .map((employeeId) => this.state.employeeMap[employeeId] || `${_t("Employee")} #${employeeId}`)
            .filter(Boolean);
    }

    getTaskAnalyticName(task) {
        return this.getMany2oneName(task.analytic_account_id) || _t("Unassigned");
    }

    getTaskStatusLabel(status) {
        return (STATUS_META[status] || STATUS_META.pending).label;
    }

    getStatusColor(status) {
        return (STATUS_META[status] || STATUS_META.pending).color;
    }

    formatDateTime(value) {
        const parsed = this.parseServerDate(value);
        if (!parsed || Number.isNaN(parsed.getTime())) {
            return value || "-";
        }
        return parsed.toLocaleString([], {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    buildStatusCounts(tasks) {
        const counts = { pending: 0, in_process: 0, done: 0 };
        for (const task of tasks) {
            const status = task.status || "pending";
            if (counts[status] !== undefined) {
                counts[status] += 1;
            }
        }
        return counts;
    }

    buildAverageProgress(tasks, keyBuilder) {
        const buckets = new Map();
        for (const task of tasks) {
            const items = keyBuilder(task);
            for (const item of items) {
                if (!item || !item.key) {
                    continue;
                }
                if (!buckets.has(item.key)) {
                    buckets.set(item.key, { label: item.label, total: 0, count: 0 });
                }
                const bucket = buckets.get(item.key);
                bucket.total += parseFloat(task.progress || 0);
                bucket.count += 1;
            }
        }

        return Array.from(buckets.entries())
            .map(([key, bucket]) => ({
                key,
                label: bucket.label,
                avg: bucket.count ? bucket.total / bucket.count : 0,
                count: bucket.count,
            }))
            .sort((left, right) => {
                const countCompare = right.count - left.count;
                if (countCompare !== 0) {
                    return countCompare;
                }
                return left.label.localeCompare(right.label);
            });
    }

    buildStatusMatrix(tasks, keyBuilder) {
        const matrix = new Map();
        for (const task of tasks) {
            const progress = parseFloat(task.progress || 0);
            const status = task.status || "pending";
            const items = keyBuilder(task);
            for (const item of items) {
                if (!item || !item.key) {
                    continue;
                }
                if (!matrix.has(item.key)) {
                    matrix.set(item.key, { label: item.label, statuses: {} });
                }
                const row = matrix.get(item.key);
                if (!row.statuses[status]) {
                    row.statuses[status] = { count: 0, total: 0 };
                }
                row.statuses[status].count += 1;
                row.statuses[status].total += progress;
            }
        }

        return Array.from(matrix.values())
            .map((row) => {
                let totalCount = 0;
                let totalProgress = 0;
                const cells = {};
                for (const status of STATUS_ORDER) {
                    const bucket = row.statuses[status] || { count: 0, total: 0 };
                    cells[status] = {
                        count: bucket.count,
                        avg: bucket.count ? bucket.total / bucket.count : 0,
                    };
                    totalCount += bucket.count;
                    totalProgress += bucket.total;
                }
                return {
                    label: row.label,
                    cells,
                    totalCount,
                    totalAvg: totalCount ? totalProgress / totalCount : 0,
                };
            })
            .sort((left, right) => {
                const countCompare = right.totalCount - left.totalCount;
                if (countCompare !== 0) {
                    return countCompare;
                }
                return left.label.localeCompare(right.label);
            });
    }

    formatMatrixCell(cell) {
        if (!cell || !cell.count) {
            return "-";
        }
        return `${cell.count} (${cell.avg.toFixed(1)}%)`;
    }

    get selectedStatusCount() {
        return this.state.filters.statusValues.length;
    }

    get selectedEmployeeCount() {
        return this.state.filters.employeeIds.length;
    }

    get selectedAnalyticCount() {
        return this.state.filters.analyticIds.length;
    }

    get activeFilterChips() {
        const chips = [];
        const searchValue = (this.state.filters.search || "").trim();
        const taskIdValue = (this.state.filters.taskId || "").trim();
        const analyticMap = new Map(this.state.options.analytics.map((item) => [item.id, item.name]));

        if (searchValue) {
            chips.push({ key: "search", type: "search", label: `${_t("Search")}: ${searchValue}` });
        }
        if (taskIdValue) {
            chips.push({ key: "task", type: "task", label: `${_t("Task")}: ${taskIdValue}` });
        }
        if (this.state.filters.dateFrom) {
            chips.push({
                key: "from",
                type: "date_from",
                label: `${_t("From")}: ${this.formatDateLabel(this.state.filters.dateFrom)}`,
            });
        }
        if (this.state.filters.dateTo) {
            chips.push({
                key: "to",
                type: "date_to",
                label: `${_t("To")}: ${this.formatDateLabel(this.state.filters.dateTo)}`,
            });
        }
        for (const status of this.state.filters.statusValues) {
            chips.push({
                key: `status-${status}`,
                type: "status",
                value: status,
                label: `${_t("Status")}: ${this.getTaskStatusLabel(status)}`,
            });
        }
        for (const employeeId of this.state.filters.employeeIds) {
            chips.push({
                key: `employee-${employeeId}`,
                type: "employee",
                value: employeeId,
                label: `${_t("Employee")}: ${this.state.employeeMap[employeeId] || `${_t("Employee")} #${employeeId}`}`,
            });
        }
        for (const analyticId of this.state.filters.analyticIds) {
            chips.push({
                key: `analytic-${analyticId}`,
                type: "analytic",
                value: analyticId,
                label: `${_t("Project")}: ${analyticMap.get(analyticId) || `${_t("Project")} #${analyticId}`}`,
            });
        }
        return chips;
    }

    get filteredResultsLabel() {
        return `${_t("Showing")} ${this.state.visibleTasks.length} ${_t("of")} ${this.state.allTasks.length} ${_t("tasks")}`;
    }

    get statusCounts() {
        return this.buildStatusCounts(this.state.visibleTasks);
    }

    get metricCards() {
        const counts = this.statusCounts;
        return STATUS_ORDER.map((status) => ({
            key: status,
            label: this.getTaskStatusLabel(status),
            color: this.getStatusColor(status),
            value: counts[status] || 0,
        }));
    }

    get statusPieSegments() {
        const counts = this.statusCounts;
        return STATUS_ORDER.map((status) => ({
            key: status,
            label: this.getTaskStatusLabel(status),
            color: this.getStatusColor(status),
            value: counts[status] || 0,
        })).filter((segment) => segment.value > 0);
    }

    get progressByEmployee() {
        return this.buildAverageProgress(this.state.visibleTasks, (task) =>
            this.getTaskAssigneeIds(task).map((employeeId) => ({
                key: `employee-${employeeId}`,
                label: this.state.employeeMap[employeeId] || `${_t("Employee")} #${employeeId}`,
            }))
        );
    }

    get progressByAnalytic() {
        return this.buildAverageProgress(this.state.visibleTasks, (task) => [
            {
                key: `analytic-${this.getMany2oneId(task.analytic_account_id) || 0}`,
                label: this.getTaskAnalyticName(task),
            },
        ]);
    }

    get statusDistributionItems() {
        return STATUS_ORDER.map((status) => ({
            key: status,
            label: this.getTaskStatusLabel(status),
            color: this.getStatusColor(status),
            value: this.statusCounts[status] || 0,
        }));
    }

    get analyticDistributionItems() {
        const counts = new Map();
        for (const task of this.state.visibleTasks) {
            const analyticId = this.getMany2oneId(task.analytic_account_id) || 0;
            const key = `analytic-${analyticId}`;
            if (!counts.has(key)) {
                counts.set(key, {
                    key,
                    label: this.getTaskAnalyticName(task),
                    value: 0,
                });
            }
            counts.get(key).value += 1;
        }

        return Array.from(counts.values())
            .sort((left, right) => {
                const valueCompare = right.value - left.value;
                if (valueCompare !== 0) {
                    return valueCompare;
                }
                return left.label.localeCompare(right.label);
            })
            .map((item, index) => ({
                ...item,
                color: ANALYTIC_COLORS[index % ANALYTIC_COLORS.length],
            }));
    }

    get analyticStatusRows() {
        return this.buildStatusMatrix(this.state.visibleTasks, (task) => [
            {
                key: `analytic-${this.getMany2oneId(task.analytic_account_id) || 0}`,
                label: this.getTaskAnalyticName(task),
            },
        ]);
    }

    get employeeStatusRows() {
        return this.buildStatusMatrix(this.state.visibleTasks, (task) =>
            this.getTaskAssigneeIds(task).map((employeeId) => ({
                key: `employee-${employeeId}`,
                label: this.state.employeeMap[employeeId] || `${_t("Employee")} #${employeeId}`,
            }))
        );
    }

    get visibleTaskRows() {
        return this.state.visibleTasks.slice(0, 20).map((task) => ({
            id: task.id,
            taskTitle: task.x_task_number ? `${task.x_task_number} - ${task.name || ""}` : `${_t("Task")} #${task.id} - ${task.name || ""}`,
            analytic: this.getTaskAnalyticName(task),
            assignees: this.getTaskAssigneeNames(task).join(", ") || _t("Unassigned"),
            statusLabel: this.getTaskStatusLabel(task.status || "pending"),
            statusColor: this.getStatusColor(task.status || "pending"),
            progress: `${parseInt(task.progress || 0, 10)}%`,
            dueDate: this.formatDateTime(task.target_end_date),
        }));
    }

    get statusPieStyle() {
        return this.getPieStyle(this.statusPieSegments);
    }

    get analyticPieStyle() {
        return this.getPieStyle(this.analyticDistributionItems);
    }

    getPieStyle(segments) {
        const total = segments.reduce((sum, segment) => sum + segment.value, 0);
        if (!total) {
            return "background: #dbe3f0;";
        }
        let start = 0;
        const stops = [];
        for (const segment of segments) {
            const angle = (segment.value / total) * 360;
            stops.push(`${segment.color} ${start.toFixed(2)}deg ${(start + angle).toFixed(2)}deg`);
            start += angle;
        }
        return `background: conic-gradient(${stops.join(", ")});`;
    }

    getTotal(items) {
        return items.reduce((sum, item) => sum + item.value, 0);
    }

    getBarWidth(value, total) {
        if (!total) {
            return "0%";
        }
        return `${Math.max((value / total) * 100, value > 0 ? 6 : 0)}%`;
    }

    getProgressWidth(value) {
        const safeValue = Math.max(0, Math.min(value || 0, 100));
        return `${safeValue}%`;
    }

    getProgressBarClass(value) {
        if (value >= 100) {
            return "is-done";
        }
        if (value >= 50) {
            return "is-active";
        }
        return "is-pending";
    }

    async openTask(taskId) {
        if (!taskId) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "fin.employee.task",
            res_id: taskId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

TaskDashboardAction.template = "odoo_attendance_app.TaskDashboard";
registry.category("actions").add("odoo_attendance_app.task_dashboard", TaskDashboardAction);
