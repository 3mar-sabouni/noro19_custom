/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

class AttendanceEmployeeListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this._buttonClickHandler = this.onClickResetAllDeviceBindings.bind(this);

        onMounted(() => {
            this.ensureResetButton();
        });
        onPatched(() => {
            this.ensureResetButton();
        });
        onWillUnmount(() => {
            this.removeResetButton();
        });
    }

    async onClickResetAllDeviceBindings() {
        const confirmed = window.confirm(
            _t("This will unbind every device and invalidate all mobile app sessions for all employees. Continue?")
        );
        if (!confirmed) {
            return;
        }

        const result = await this.orm.call("odoo.attendance.employee", "action_reset_all_device_bindings", []);
        const resetCount = result?.reset_count || 0;
        const sessionCount = result?.session_count || 0;

        this.notification.add(
            _t("%s employee device bindings reset. %s mobile sessions invalidated.", resetCount, sessionCount),
            {
                title: _t("Device Bindings Reset"),
                type: "success",
            }
        );
        await this.action.doAction({ type: "ir.actions.client", tag: "reload" });
    }

    ensureResetButton() {
        const container = document.querySelector(".o_control_panel .o_cp_buttons, .o_control_panel .o_list_buttons");
        if (!container) {
            return;
        }

        let button = container.querySelector(".o_fin_reset_all_devices_btn");
        if (!button) {
            button = document.createElement("button");
            button.type = "button";
            button.className = "btn btn-outline-danger ms-2 o_fin_reset_all_devices_btn";
            button.textContent = _t("Reset All Device Bindings");
            button.addEventListener("click", this._buttonClickHandler);
            container.appendChild(button);
        }
    }

    removeResetButton() {
        const button = document.querySelector(".o_fin_reset_all_devices_btn");
        if (button) {
            button.removeEventListener("click", this._buttonClickHandler);
            button.remove();
        }
    }
}

export const attendanceEmployeeListView = {
    ...listView,
    Controller: AttendanceEmployeeListController,
};

registry.category("views").add("fin_attendance_employee_list", attendanceEmployeeListView);
