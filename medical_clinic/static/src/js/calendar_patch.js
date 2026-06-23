/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CalendarModel } from "@web/views/calendar/calendar_model";

patch(CalendarModel.prototype, {

    async createRecord(record) {
        try {
            return await super.createRecord(record);
        } catch (error) {
            // 🔥 HARD RESET calendar
            await this.load();
            throw error;
        }
    },

    async updateRecord(record, changes) {
        try {
            return await super.updateRecord(record, changes);
        } catch (error) {
            // 🔥 HARD RESET calendar
            await this.load();
            throw error;
        }
    },

});
