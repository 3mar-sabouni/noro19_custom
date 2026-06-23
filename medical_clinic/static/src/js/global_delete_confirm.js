/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";

patch(ListRenderer.prototype, {

    setup() {
        super.setup();
        this.dialog = useService("dialog");
    },

    async onDeleteRecord(record) {
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: "Delete Record",
                body: "Are you sure you want to delete this record?",
                confirm: async () => {
                    await super.onDeleteRecord(record);
                    resolve();
                },
                cancel: () => resolve(),
            });
        });
    },

});
