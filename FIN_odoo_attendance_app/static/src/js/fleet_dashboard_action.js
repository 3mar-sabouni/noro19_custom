/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const TRIP_STATE_ORDER = ["in_progress", "completed", "cancelled"];
const TRIP_STATE_META = {
    in_progress: { label: _t("In Progress"), color: "#2563eb" },
    completed: { label: _t("Completed"), color: "#16a34a" },
    cancelled: { label: _t("Cancelled"), color: "#ef4444" },
};
const VEHICLE_STATUS_ORDER = ["active", "in_maintenance", "retired"];
const VEHICLE_STATUS_META = {
    active: { label: _t("Active"), color: "#0891b2" },
    in_maintenance: { label: _t("In Maintenance"), color: "#f59e0b" },
    retired: { label: _t("Retired"), color: "#64748b" },
};
const VEHICLE_TYPE_META = {
    car: { label: _t("Car"), color: "#2563eb" },
    truck: { label: _t("Truck"), color: "#7c3aed" },
    van: { label: _t("Van"), color: "#0f766e" },
    motorcycle: { label: _t("Motorcycle"), color: "#db2777" },
};
const FUEL_TYPE_META = {
    petrol: { label: _t("Petrol"), color: "#ea580c" },
    diesel: { label: _t("Diesel"), color: "#2563eb" },
    electric: { label: _t("Electric"), color: "#16a34a" },
    hybrid: { label: _t("Hybrid"), color: "#a855f7" },
};
const CHART_COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#7c3aed", "#0f766e", "#db2777", "#ea580c", "#0891b2"];

export class FleetDashboardAction extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            error: null,
            allVehicles: [],
            visibleVehicles: [],
            allTrips: [],
            visibleTrips: [],
            employeeMap: {},
            vehicleMap: {},
            filters: {
                dateFrom: "",
                dateTo: "",
                stateValues: [],
                vehicleIds: [],
                driverIds: [],
                analyticIds: [],
                vehicleStatuses: [],
                vehicleTypes: [],
                fuelTypes: [],
            },
            options: {
                vehicles: [],
                drivers: [],
                analytics: [],
                states: TRIP_STATE_ORDER.map((key) => ({
                    key,
                    label: this.getTripStateLabel(key),
                })),
                vehicleStatuses: VEHICLE_STATUS_ORDER.map((key) => ({
                    key,
                    label: this.getVehicleStatusLabel(key),
                })),
                vehicleTypes: Object.keys(VEHICLE_TYPE_META).map((key) => ({
                    key,
                    label: this.getVehicleTypeLabel(key),
                })),
                fuelTypes: Object.keys(FUEL_TYPE_META).map((key) => ({
                    key,
                    label: this.getFuelTypeLabel(key),
                })),
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
            const [vehicles, trips, employees] = await Promise.all([
                this.fetchAllVehicles(),
                this.fetchAllTrips(),
                this.fetchAllEmployees(),
            ]);
            const employeeMap = this.buildEmployeeMap(employees);
            const vehicleMap = Object.fromEntries(vehicles.map((vehicle) => [vehicle.id, vehicle]));
            this.state.allVehicles = vehicles;
            this.state.allTrips = trips;
            this.state.employeeMap = employeeMap;
            this.state.vehicleMap = vehicleMap;
            this.state.options = this.buildOptions(vehicles, trips, employees, employeeMap);
            this.applyFilters();
        } catch (error) {
            console.error("Failed to load fleet dashboard", error);
            this.state.error = _t("Failed to load fleet dashboard.");
            this.state.allVehicles = [];
            this.state.visibleVehicles = [];
            this.state.allTrips = [];
            this.state.visibleTrips = [];
        } finally {
            this.state.loading = false;
        }
    }

    async fetchAllVehicles() {
        const fields = [
            "id",
            "name",
            "license_plate",
            "vehicle_type",
            "vehicle_status",
            "current_kilometrage",
            "last_maintenance_kilometrage",
            "fuel_type",
            "purchase_date",
            "allowed_employee_ids",
            "active",
        ];
        return this.fetchAllRecords("odoo.attendance.vehicle", fields, "name asc");
    }

    async fetchAllTrips() {
        const fields = [
            "id",
            "name",
            "trip_start_date_time",
            "trip_end_date_time",
            "driver_employee_app_id",
            "vehicle_id",
            "analytic_account_id",
            "start_kilometrage",
            "end_kilometrage",
            "kilometrage_difference",
            "state",
        ];
        return this.fetchAllRecords("odoo.attendance.fleet.trip", fields, "trip_start_date_time desc, id desc");
    }

    async fetchAllEmployees() {
        const fields = ["id", "username", "employee_id", "is_active", "is_driver"];
        return this.fetchAllRecords("odoo.attendance.employee", fields, "id asc");
    }

    async fetchAllRecords(model, fields, order) {
        const limit = 200;
        let offset = 0;
        const rows = [];
        while (true) {
            const batch = await this.orm.searchRead(model, [], fields, {
                limit,
                offset,
                order,
            });
            rows.push(...batch);
            if (batch.length < limit) {
                break;
            }
            offset += limit;
        }
        return rows;
    }

    buildEmployeeMap(employees) {
        const map = {};
        for (const employee of employees) {
            const employeeName = this.getMany2oneName(employee.employee_id);
            map[employee.id] = employeeName || employee.username || `${_t("Employee")} #${employee.id}`;
        }
        return map;
    }

    buildOptions(vehicles, trips, employees, employeeMap) {
        const driverIds = new Set();
        const analytics = new Map();

        for (const vehicle of vehicles) {
            for (const employeeId of vehicle.allowed_employee_ids || []) {
                if (employeeId) {
                    driverIds.add(employeeId);
                }
            }
        }

        for (const trip of trips) {
            const driverId = this.getMany2oneId(trip.driver_employee_app_id);
            if (driverId) {
                driverIds.add(driverId);
            }
            const analyticId = this.getMany2oneId(trip.analytic_account_id);
            const analyticName = this.getMany2oneName(trip.analytic_account_id);
            if (analyticId && analyticName) {
                analytics.set(analyticId, analyticName);
            }
        }

        return {
            vehicles: vehicles
                .map((vehicle) => ({
                    id: vehicle.id,
                    label: this.getVehicleLabel(vehicle),
                }))
                .sort((left, right) => left.label.localeCompare(right.label)),
            drivers: Array.from(driverIds)
                .map((id) => ({
                    id,
                    label: employeeMap[id] || `${_t("Employee")} #${id}`,
                }))
                .sort((left, right) => left.label.localeCompare(right.label)),
            analytics: Array.from(analytics.entries())
                .map(([id, label]) => ({ id, label }))
                .sort((left, right) => left.label.localeCompare(right.label)),
            states: TRIP_STATE_ORDER.map((key) => ({ key, label: this.getTripStateLabel(key) })),
            vehicleStatuses: VEHICLE_STATUS_ORDER.map((key) => ({ key, label: this.getVehicleStatusLabel(key) })),
            vehicleTypes: Object.keys(VEHICLE_TYPE_META).map((key) => ({ key, label: this.getVehicleTypeLabel(key) })),
            fuelTypes: Object.keys(FUEL_TYPE_META).map((key) => ({ key, label: this.getFuelTypeLabel(key) })),
        };
    }

    onDateFromInput(ev) {
        this.state.filters.dateFrom = ev.target.value || "";
        this.applyFilters();
    }

    onDateToInput(ev) {
        this.state.filters.dateTo = ev.target.value || "";
        this.applyFilters();
    }

    onTripStateChange(ev) {
        this.state.filters.stateValues = this.getSelectedValues(ev.target.options);
        this.applyFilters();
    }

    onVehicleChange(ev) {
        this.state.filters.vehicleIds = this.getSelectedValues(ev.target.options).map((value) => parseInt(value, 10));
        this.applyFilters();
    }

    onDriverChange(ev) {
        this.state.filters.driverIds = this.getSelectedValues(ev.target.options).map((value) => parseInt(value, 10));
        this.applyFilters();
    }

    onAnalyticChange(ev) {
        this.state.filters.analyticIds = this.getSelectedValues(ev.target.options).map((value) => parseInt(value, 10));
        this.applyFilters();
    }

    onVehicleStatusChange(ev) {
        this.state.filters.vehicleStatuses = this.getSelectedValues(ev.target.options);
        this.applyFilters();
    }

    onVehicleTypeChange(ev) {
        this.state.filters.vehicleTypes = this.getSelectedValues(ev.target.options);
        this.applyFilters();
    }

    onFuelTypeChange(ev) {
        this.state.filters.fuelTypes = this.getSelectedValues(ev.target.options);
        this.applyFilters();
    }

    getSelectedValues(options) {
        return Array.from(options || [])
            .filter((option) => option.selected)
            .map((option) => option.value);
    }

    clearFilters() {
        this.state.filters.dateFrom = "";
        this.state.filters.dateTo = "";
        this.state.filters.stateValues = [];
        this.state.filters.vehicleIds = [];
        this.state.filters.driverIds = [];
        this.state.filters.analyticIds = [];
        this.state.filters.vehicleStatuses = [];
        this.state.filters.vehicleTypes = [];
        this.state.filters.fuelTypes = [];
        this.applyFilters();
    }

    removeFilterChip(chip) {
        if (!chip || !chip.type) {
            return;
        }
        if (chip.type === "date_from") {
            this.state.filters.dateFrom = "";
        } else if (chip.type === "date_to") {
            this.state.filters.dateTo = "";
        } else if (chip.type === "state") {
            this.state.filters.stateValues = this.state.filters.stateValues.filter((value) => value !== chip.value);
        } else if (chip.type === "vehicle") {
            this.state.filters.vehicleIds = this.state.filters.vehicleIds.filter((value) => value !== chip.value);
        } else if (chip.type === "driver") {
            this.state.filters.driverIds = this.state.filters.driverIds.filter((value) => value !== chip.value);
        } else if (chip.type === "analytic") {
            this.state.filters.analyticIds = this.state.filters.analyticIds.filter((value) => value !== chip.value);
        } else if (chip.type === "vehicle_status") {
            this.state.filters.vehicleStatuses = this.state.filters.vehicleStatuses.filter((value) => value !== chip.value);
        } else if (chip.type === "vehicle_type") {
            this.state.filters.vehicleTypes = this.state.filters.vehicleTypes.filter((value) => value !== chip.value);
        } else if (chip.type === "fuel_type") {
            this.state.filters.fuelTypes = this.state.filters.fuelTypes.filter((value) => value !== chip.value);
        }
        this.applyFilters();
    }

    applyFilters() {
        const baseVehicles = this.state.allVehicles.filter((vehicle) => this.vehicleMatchesBaseFilters(vehicle));
        const visibleTrips = this.state.allTrips.filter((trip) => this.tripMatchesFilters(trip, baseVehicles));
        const hasTripScopedFilter =
            this.state.filters.dateFrom ||
            this.state.filters.dateTo ||
            this.state.filters.stateValues.length ||
            this.state.filters.driverIds.length ||
            this.state.filters.analyticIds.length;

        let visibleVehicles = baseVehicles;
        if (hasTripScopedFilter) {
            const tripVehicleIds = new Set(
                visibleTrips
                    .map((trip) => this.getMany2oneId(trip.vehicle_id))
                    .filter(Boolean)
            );
            visibleVehicles = baseVehicles.filter((vehicle) => tripVehicleIds.has(vehicle.id));
        }

        this.state.visibleVehicles = visibleVehicles;
        this.state.visibleTrips = visibleTrips;
    }

    vehicleMatchesBaseFilters(vehicle) {
        if (!vehicle || vehicle.active === false) {
            return false;
        }
        if (this.state.filters.vehicleIds.length && !this.state.filters.vehicleIds.includes(vehicle.id)) {
            return false;
        }
        if (this.state.filters.vehicleStatuses.length && !this.state.filters.vehicleStatuses.includes(vehicle.vehicle_status || "active")) {
            return false;
        }
        if (this.state.filters.vehicleTypes.length && !this.state.filters.vehicleTypes.includes(vehicle.vehicle_type || "car")) {
            return false;
        }
        if (this.state.filters.fuelTypes.length && !this.state.filters.fuelTypes.includes(vehicle.fuel_type || "petrol")) {
            return false;
        }
        return true;
    }

    tripMatchesFilters(trip, visibleVehicles) {
        const tripState = trip.state || "in_progress";
        const vehicleId = this.getMany2oneId(trip.vehicle_id);
        const driverId = this.getMany2oneId(trip.driver_employee_app_id);
        const analyticId = this.getMany2oneId(trip.analytic_account_id);
        const visibleVehicleIds = new Set(visibleVehicles.map((vehicle) => vehicle.id));

        if (vehicleId && !visibleVehicleIds.has(vehicleId)) {
            return false;
        }
        if (this.state.filters.stateValues.length && !this.state.filters.stateValues.includes(tripState)) {
            return false;
        }
        if (this.state.filters.vehicleIds.length && (!vehicleId || !this.state.filters.vehicleIds.includes(vehicleId))) {
            return false;
        }
        if (this.state.filters.driverIds.length && (!driverId || !this.state.filters.driverIds.includes(driverId))) {
            return false;
        }
        if (this.state.filters.analyticIds.length && (!analyticId || !this.state.filters.analyticIds.includes(analyticId))) {
            return false;
        }
        if (!this.tripMatchesDateRange(trip, this.state.filters.dateFrom, this.state.filters.dateTo)) {
            return false;
        }
        return true;
    }

    tripMatchesDateRange(trip, dateFrom, dateTo) {
        if (!dateFrom && !dateTo) {
            return true;
        }
        const start = this.parseServerDate(trip.trip_start_date_time);
        const end = this.parseServerDate(trip.trip_end_date_time) || start;
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

    getVehicleLabel(vehicle) {
        if (!vehicle) {
            return _t("Unknown Vehicle");
        }
        return vehicle.license_plate ? `${vehicle.name} (${vehicle.license_plate})` : vehicle.name || `${_t("Vehicle")} #${vehicle.id}`;
    }

    getDriverName(employeeId) {
        return this.state.employeeMap[employeeId] || `${_t("Employee")} #${employeeId}`;
    }

    getAllowedDriverNames(vehicle) {
        return (vehicle.allowed_employee_ids || []).map((employeeId) => this.getDriverName(employeeId));
    }

    getAnalyticName(trip) {
        return this.getMany2oneName(trip.analytic_account_id) || _t("No Project");
    }

    getTripStateLabel(state) {
        return (TRIP_STATE_META[state] || TRIP_STATE_META.in_progress).label;
    }

    getTripStateColor(state) {
        return (TRIP_STATE_META[state] || TRIP_STATE_META.in_progress).color;
    }

    getVehicleStatusLabel(status) {
        return (VEHICLE_STATUS_META[status] || VEHICLE_STATUS_META.active).label;
    }

    getVehicleStatusColor(status) {
        return (VEHICLE_STATUS_META[status] || VEHICLE_STATUS_META.active).color;
    }

    getVehicleTypeLabel(type) {
        return (VEHICLE_TYPE_META[type] || { label: type || _t("Other") }).label;
    }

    getFuelTypeLabel(type) {
        return (FUEL_TYPE_META[type] || { label: type || _t("Other") }).label;
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

    formatKm(value) {
        const numericValue = parseFloat(value || 0);
        return `${numericValue.toLocaleString([], {
            minimumFractionDigits: 0,
            maximumFractionDigits: 1,
        })} km / mi / hr`;
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

    getTripDistance(trip) {
        const computed = parseFloat(trip.kilometrage_difference || 0);
        if (!Number.isNaN(computed) && computed > 0) {
            return computed;
        }
        const startKm = parseFloat(trip.start_kilometrage || 0);
        const endKm = parseFloat(trip.end_kilometrage || 0);
        const diff = endKm - startKm;
        return Number.isFinite(diff) && diff > 0 ? diff : 0;
    }

    buildCountBuckets(items, keyBuilder) {
        return this.buildValueBuckets(items, keyBuilder, () => 1, false);
    }

    buildDistanceBuckets(items, keyBuilder) {
        return this.buildValueBuckets(items, keyBuilder, (item) => this.getTripDistance(item), true);
    }

    buildValueBuckets(items, keyBuilder, valueBuilder, valueIsDistance) {
        const buckets = new Map();
        for (const item of items) {
            for (const descriptor of keyBuilder(item)) {
                if (!descriptor || !descriptor.key) {
                    continue;
                }
                if (!buckets.has(descriptor.key)) {
                    buckets.set(descriptor.key, {
                        key: descriptor.key,
                        label: descriptor.label,
                        value: 0,
                        color: descriptor.color,
                    });
                }
                buckets.get(descriptor.key).value += valueBuilder(item);
            }
        }
        return Array.from(buckets.values())
            .sort((left, right) => {
                const valueCompare = right.value - left.value;
                if (valueCompare !== 0) {
                    return valueCompare;
                }
                return left.label.localeCompare(right.label);
            })
            .map((item, index) => ({
                ...item,
                color: item.color || CHART_COLORS[index % CHART_COLORS.length],
                valueLabel: valueIsDistance ? this.formatKm(item.value) : String(item.value),
            }));
    }

    buildDistribution(items, keyBuilder, labelBuilder, colorBuilder) {
        const counts = new Map();
        for (const item of items) {
            const key = keyBuilder(item);
            if (!key) {
                continue;
            }
            if (!counts.has(key)) {
                counts.set(key, {
                    key,
                    label: labelBuilder(key),
                    value: 0,
                    color: colorBuilder(key),
                });
            }
            counts.get(key).value += 1;
        }
        return Array.from(counts.values()).sort((left, right) => right.value - left.value || left.label.localeCompare(right.label));
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

    async openVehicle(vehicleId) {
        if (!vehicleId) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "odoo.attendance.vehicle",
            res_id: vehicleId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openTrip(tripId) {
        if (!tripId) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "odoo.attendance.fleet.trip",
            res_id: tripId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get selectedTripStateCount() {
        return this.state.filters.stateValues.length;
    }

    get selectedVehicleCount() {
        return this.state.filters.vehicleIds.length;
    }

    get selectedDriverCount() {
        return this.state.filters.driverIds.length;
    }

    get selectedAnalyticCount() {
        return this.state.filters.analyticIds.length;
    }

    get selectedVehicleStatusCount() {
        return this.state.filters.vehicleStatuses.length;
    }

    get selectedVehicleTypeCount() {
        return this.state.filters.vehicleTypes.length;
    }

    get selectedFuelTypeCount() {
        return this.state.filters.fuelTypes.length;
    }

    get activeFilterChips() {
        const chips = [];
        const vehicleMap = new Map(this.state.options.vehicles.map((item) => [item.id, item.label]));
        const driverMap = new Map(this.state.options.drivers.map((item) => [item.id, item.label]));
        const analyticMap = new Map(this.state.options.analytics.map((item) => [item.id, item.label]));

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
        for (const state of this.state.filters.stateValues) {
            chips.push({
                key: `state-${state}`,
                type: "state",
                value: state,
                label: `${_t("Trip State")}: ${this.getTripStateLabel(state)}`,
            });
        }
        for (const vehicleId of this.state.filters.vehicleIds) {
            chips.push({
                key: `vehicle-${vehicleId}`,
                type: "vehicle",
                value: vehicleId,
                label: `${_t("Vehicle")}: ${vehicleMap.get(vehicleId) || `${_t("Vehicle")} #${vehicleId}`}`,
            });
        }
        for (const driverId of this.state.filters.driverIds) {
            chips.push({
                key: `driver-${driverId}`,
                type: "driver",
                value: driverId,
                label: `${_t("Driver")}: ${driverMap.get(driverId) || `${_t("Employee")} #${driverId}`}`,
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
        for (const status of this.state.filters.vehicleStatuses) {
            chips.push({
                key: `vehicle-status-${status}`,
                type: "vehicle_status",
                value: status,
                label: `${_t("Vehicle Status")}: ${this.getVehicleStatusLabel(status)}`,
            });
        }
        for (const type of this.state.filters.vehicleTypes) {
            chips.push({
                key: `vehicle-type-${type}`,
                type: "vehicle_type",
                value: type,
                label: `${_t("Vehicle Type")}: ${this.getVehicleTypeLabel(type)}`,
            });
        }
        for (const fuelType of this.state.filters.fuelTypes) {
            chips.push({
                key: `fuel-type-${fuelType}`,
                type: "fuel_type",
                value: fuelType,
                label: `${_t("Fuel Type")}: ${this.getFuelTypeLabel(fuelType)}`,
            });
        }
        return chips;
    }

    get filteredResultsLabel() {
        return `${_t("Showing")} ${this.state.visibleTrips.length} ${_t("trips across")} ${this.state.visibleVehicles.length} ${_t("vehicles")}`;
    }

    get vehicleStatusCounts() {
        const counts = { active: 0, in_maintenance: 0, retired: 0 };
        for (const vehicle of this.state.visibleVehicles) {
            const status = vehicle.vehicle_status || "active";
            if (counts[status] !== undefined) {
                counts[status] += 1;
            }
        }
        return counts;
    }

    get tripStateCounts() {
        const counts = { in_progress: 0, completed: 0, cancelled: 0 };
        for (const trip of this.state.visibleTrips) {
            const state = trip.state || "in_progress";
            if (counts[state] !== undefined) {
                counts[state] += 1;
            }
        }
        return counts;
    }

    get metricCards() {
        const assignedVehicles = this.state.visibleVehicles.filter((vehicle) => (vehicle.allowed_employee_ids || []).length > 0).length;
        const totalDistance = this.state.visibleTrips.reduce((sum, trip) => sum + this.getTripDistance(trip), 0);
        const averageDistance = this.state.visibleTrips.length ? totalDistance / this.state.visibleTrips.length : 0;

        return [
            { key: "vehicles", label: _t("Visible Vehicles"), value: this.state.visibleVehicles.length, color: "#0f766e" },
            { key: "active", label: _t("Active Vehicles"), value: this.vehicleStatusCounts.active || 0, color: "#0891b2" },
            { key: "maintenance", label: _t("In Maintenance"), value: this.vehicleStatusCounts.in_maintenance || 0, color: "#f59e0b" },
            { key: "retired", label: _t("Retired"), value: this.vehicleStatusCounts.retired || 0, color: "#64748b" },
            { key: "assigned", label: _t("With Assigned Drivers"), value: assignedVehicles, color: "#7c3aed" },
            { key: "trips", label: _t("Visible Trips"), value: this.state.visibleTrips.length, color: "#2563eb" },
            { key: "open_trips", label: _t("In Progress Trips"), value: this.tripStateCounts.in_progress || 0, color: "#1d4ed8" },
            { key: "completed", label: _t("Completed Trips"), value: this.tripStateCounts.completed || 0, color: "#16a34a" },
            { key: "distance", label: _t("Total Distance"), value: this.formatKm(totalDistance), color: "#ea580c" },
            { key: "avg_distance", label: _t("Avg Distance / Trip"), value: this.formatKm(averageDistance), color: "#db2777" },
        ];
    }

    get vehicleStatusDistributionItems() {
        return VEHICLE_STATUS_ORDER.map((key) => ({
            key,
            label: this.getVehicleStatusLabel(key),
            value: this.vehicleStatusCounts[key] || 0,
            color: this.getVehicleStatusColor(key),
        })).filter((item) => item.value > 0);
    }

    get tripStateDistributionItems() {
        return TRIP_STATE_ORDER.map((key) => ({
            key,
            label: this.getTripStateLabel(key),
            value: this.tripStateCounts[key] || 0,
            color: this.getTripStateColor(key),
        })).filter((item) => item.value > 0);
    }

    get vehicleTypeDistributionItems() {
        return this.buildDistribution(
            this.state.visibleVehicles,
            (vehicle) => vehicle.vehicle_type || "car",
            (key) => this.getVehicleTypeLabel(key),
            (key) => (VEHICLE_TYPE_META[key] || {}).color || "#2563eb"
        );
    }

    get fuelTypeDistributionItems() {
        return this.buildDistribution(
            this.state.visibleVehicles,
            (vehicle) => vehicle.fuel_type || "petrol",
            (key) => this.getFuelTypeLabel(key),
            (key) => (FUEL_TYPE_META[key] || {}).color || "#ea580c"
        );
    }

    get tripCountByVehicle() {
        return this.buildCountBuckets(this.state.visibleTrips, (trip) => {
            const vehicleId = this.getMany2oneId(trip.vehicle_id);
            const vehicle = this.state.vehicleMap[vehicleId];
            return [{
                key: `vehicle-${vehicleId || 0}`,
                label: vehicle ? this.getVehicleLabel(vehicle) : this.getMany2oneName(trip.vehicle_id) || _t("Unassigned"),
            }];
        });
    }

    get distanceByVehicle() {
        return this.buildDistanceBuckets(this.state.visibleTrips, (trip) => {
            const vehicleId = this.getMany2oneId(trip.vehicle_id);
            const vehicle = this.state.vehicleMap[vehicleId];
            return [{
                key: `vehicle-${vehicleId || 0}`,
                label: vehicle ? this.getVehicleLabel(vehicle) : this.getMany2oneName(trip.vehicle_id) || _t("Unassigned"),
            }];
        });
    }

    get tripCountByDriver() {
        return this.buildCountBuckets(this.state.visibleTrips, (trip) => {
            const driverId = this.getMany2oneId(trip.driver_employee_app_id);
            return [{
                key: `driver-${driverId || 0}`,
                label: driverId ? this.getDriverName(driverId) : _t("Unassigned"),
            }];
        });
    }

    get distanceByDriver() {
        return this.buildDistanceBuckets(this.state.visibleTrips, (trip) => {
            const driverId = this.getMany2oneId(trip.driver_employee_app_id);
            return [{
                key: `driver-${driverId || 0}`,
                label: driverId ? this.getDriverName(driverId) : _t("Unassigned"),
            }];
        });
    }

    get tripCountByProject() {
        return this.buildCountBuckets(this.state.visibleTrips, (trip) => [{
            key: `project-${this.getMany2oneId(trip.analytic_account_id) || 0}`,
            label: this.getAnalyticName(trip),
        }]);
    }

    get maintenanceAttentionRows() {
        return this.state.visibleVehicles
            .map((vehicle) => {
                const currentKm = parseFloat(vehicle.current_kilometrage || 0);
                const maintenanceKm = parseFloat(vehicle.last_maintenance_kilometrage || 0);
                const gap = Math.max(currentKm - maintenanceKm, 0);
                return {
                    id: vehicle.id,
                    vehicleLabel: this.getVehicleLabel(vehicle),
                    statusLabel: this.getVehicleStatusLabel(vehicle.vehicle_status || "active"),
                    statusColor: this.getVehicleStatusColor(vehicle.vehicle_status || "active"),
                    currentKm: this.formatKm(currentKm),
                    maintenanceKm: this.formatKm(maintenanceKm),
                    gapValue: gap,
                    gapLabel: this.formatKm(gap),
                };
            })
            .sort((left, right) => right.gapValue - left.gapValue || left.vehicleLabel.localeCompare(right.vehicleLabel))
            .slice(0, 10);
    }

    get vehiclesWithoutDriverRows() {
        return this.state.visibleVehicles
            .filter((vehicle) => !(vehicle.allowed_employee_ids || []).length)
            .map((vehicle) => ({
                id: vehicle.id,
                vehicleLabel: this.getVehicleLabel(vehicle),
                statusLabel: this.getVehicleStatusLabel(vehicle.vehicle_status || "active"),
                statusColor: this.getVehicleStatusColor(vehicle.vehicle_status || "active"),
                fuelLabel: this.getFuelTypeLabel(vehicle.fuel_type || "petrol"),
                typeLabel: this.getVehicleTypeLabel(vehicle.vehicle_type || "car"),
            }))
            .slice(0, 10);
    }

    get recentTripRows() {
        return this.state.visibleTrips.slice(0, 12).map((trip) => ({
            id: trip.id,
            tripLabel: trip.name || `${_t("Trip")} #${trip.id}`,
            vehicleLabel: this.getMany2oneName(trip.vehicle_id) || _t("Unassigned"),
            driverLabel: this.getMany2oneId(trip.driver_employee_app_id)
                ? this.getDriverName(this.getMany2oneId(trip.driver_employee_app_id))
                : _t("Unassigned"),
            projectLabel: this.getAnalyticName(trip),
            stateLabel: this.getTripStateLabel(trip.state || "in_progress"),
            stateColor: this.getTripStateColor(trip.state || "in_progress"),
            dateRange: `${this.formatDateTime(trip.trip_start_date_time)} -> ${this.formatDateTime(trip.trip_end_date_time)}`,
            distanceLabel: this.formatKm(this.getTripDistance(trip)),
        }));
    }

    get vehicleOverviewRows() {
        const tripCounts = new Map();
        const distances = new Map();
        for (const trip of this.state.visibleTrips) {
            const vehicleId = this.getMany2oneId(trip.vehicle_id);
            if (!vehicleId) {
                continue;
            }
            tripCounts.set(vehicleId, (tripCounts.get(vehicleId) || 0) + 1);
            distances.set(vehicleId, (distances.get(vehicleId) || 0) + this.getTripDistance(trip));
        }

        return this.state.visibleVehicles
            .map((vehicle) => ({
                id: vehicle.id,
                vehicleLabel: this.getVehicleLabel(vehicle),
                driverLabel: this.summarizeLabels(this.getAllowedDriverNames(vehicle), 2) || _t("No drivers"),
                statusLabel: this.getVehicleStatusLabel(vehicle.vehicle_status || "active"),
                statusColor: this.getVehicleStatusColor(vehicle.vehicle_status || "active"),
                typeLabel: this.getVehicleTypeLabel(vehicle.vehicle_type || "car"),
                tripCount: tripCounts.get(vehicle.id) || 0,
                distanceLabel: this.formatKm(distances.get(vehicle.id) || 0),
            }))
            .sort((left, right) => right.tripCount - left.tripCount || left.vehicleLabel.localeCompare(right.vehicleLabel))
            .slice(0, 12);
    }

    get vehicleStatusPieStyle() {
        return this.getPieStyle(this.vehicleStatusDistributionItems);
    }

    get tripStatePieStyle() {
        return this.getPieStyle(this.tripStateDistributionItems);
    }
}

FleetDashboardAction.template = "odoo_attendance_app.FleetDashboard";
registry.category("actions").add("odoo_attendance_app.fleet_dashboard", FleetDashboardAction);
