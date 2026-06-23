/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";

patch(DateTimeField.prototype, {

    setup() {
        super.setup(...arguments);

        // Force 30-minute steps
        this.timePickerProps = {
            ...this.timePickerProps,
            minuteStep: 30,
            hoursStep: 1,
        };
    },

});
