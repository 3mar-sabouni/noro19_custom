/** @odoo-module **/

import { registry } from "@web/core/registry";
import { KanbanController } from "@web/views/kanban/kanban_controller";

class ImageCompareKanban extends KanbanController {

    setup() {
        super.setup();
        this.before = null;
    }

    async onCardClicked(record) {
        const workspace = this.props.context.active_id;
        if (!workspace) return;

        if (!this.before) {
            this.before = record.resId;
            await this.orm.write(
                "customer.image.workspace",
                [workspace],
                { before_image_id: record.resId }
            );
        } else {
            await this.orm.write(
                "customer.image.workspace",
                [workspace],
                { after_image_id: record.resId }
            );
            this.before = null;
        }
    }
}

registry.category("views").add("image_compare_kanban", {
    ...registry.category("views").get("kanban"),
    Controller: ImageCompareKanban,
});
