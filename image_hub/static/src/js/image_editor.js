/** @odoo-module **/

import { Component, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ImageEditor extends Component {
    static template = "image_hub.ImageEditor";

    setup() {
        console.log("🔥 ImageEditor setup (Odoo 19)");

        this.orm = useService("orm");
        this.actionService = useService("action");

        const ctx = this.props?.action?.context || {};
        this.imageId = ctx.image_id;
        this.imageUrl = `/web/image/customer.image/${this.imageId}/image_1920?unique=${Date.now()}`;

        this.canvasRef = useRef("canvas");

         // 🔍 Zoom state
        this.zoom = 1;
        this.minZoom = 0.5;
        this.maxZoom = 3;

        onMounted(() => {
            console.log("📌 Mounted, canvas:", this.canvasRef.el);
            this.initCanvas();
            this._enableWheelZoom();
            this._enablePan();
        });
    }

    initCanvas() {
        const fabric = window.fabric;
        if (!fabric) {
            console.error("❌ Fabric.js not loaded");
            return;
        }

        this.canvas = new fabric.Canvas(this.canvasRef.el, {
            width: 800,
            height: 600,
            preserveObjectStacking: true,
        });

        /* ✏️ Brush */
        this.penBrush = new fabric.PencilBrush(this.canvas);
        this.penBrush.width = 3;
        this.penBrush.color = "#ff0000";

        this.canvas.isDrawingMode = true;
        this.canvas.freeDrawingBrush = this.penBrush;

        /* 📷 Load image */
        fabric.Image.fromURL(
            this.imageUrl,
            (img) => {
                const scale = Math.min(800 / img.width, 600 / img.height);

                img.set({
                    originX: "center",
                    originY: "center",
                    left: 400,
                    top: 300,
                    scaleX: scale,
                    scaleY: scale,
                    selectable: false,
                    evented: false,
                });

                this.imageObj = img;
                this.canvas.add(img);
                this.canvas.sendToBack(img);
                this.canvas.renderAll();
            },
            { crossOrigin: "anonymous" }
        );
    }
    _enableWheelZoom() {
        this.canvas.on("mouse:wheel", (opt) => {
            let delta = opt.e.deltaY;
            let zoom = this.canvas.getZoom();

            zoom *= 0.999 ** delta;
            zoom = Math.min(this.maxZoom, Math.max(this.minZoom, zoom));

            this.canvas.zoomToPoint(
                { x: opt.e.offsetX, y: opt.e.offsetY },
                zoom
            );

            opt.e.preventDefault();
            opt.e.stopPropagation();
        });
    }

    _enablePan() {
        let isPanning = false;

        this.canvas.on("mouse:down", (opt) => {
            if (opt.e.code === "Space") {
                isPanning = true;
                this.canvas.isDrawingMode = false;
                this.canvas.selection = false;
            }
        });

        this.canvas.on("mouse:move", (opt) => {
            if (isPanning) {
                const e = opt.e;
                const vpt = this.canvas.viewportTransform;

                vpt[4] += e.movementX;
                vpt[5] += e.movementY;

                this.canvas.requestRenderAll();
            }
        });

        this.canvas.on("mouse:up", () => {
            isPanning = false;
            this.canvas.selection = true;
        });
    }

    /* ✏️ Draw */
    enableDraw() {
        console.log("✏️ Draw clicked");

        this._disableEraser();
        this.canvas.isDrawingMode = true;
        this.canvas.freeDrawingBrush = this.penBrush;
    }

    /* 🧽 Object Eraser (Odoo-safe) */
    enableEraser() {
        console.log("🧽 Erase clicked");

        this.canvas.isDrawingMode = false;
        this._disableEraser();

        this._eraserHandler = (ev) => {
            const target = ev.target;
            if (!target || target === this.imageObj) return;

            this.canvas.remove(target);
            this.canvas.requestRenderAll();
        };

        this.canvas.on("mouse:down", this._eraserHandler);
    }

    _disableEraser() {
        if (this._eraserHandler) {
            this.canvas.off("mouse:down", this._eraserHandler);
            this._eraserHandler = null;
        }
    }

   async save() {
    console.log("💾 Save clicked");

    const data = this.canvas.toDataURL({ format: "png" });

    await this.orm.write(
        "customer.image",
        [this.imageId],
        { image_1920: data.split(",")[1] }
    );

    // ✅ Odoo 19 proper close
    this.actionService.restore();
}

cancel() {
    console.log("❌ Cancel clicked");

    // ✅ Odoo 19 proper close
    this.actionService.restore();
}

}

registry.category("actions").add("image_editor", ImageEditor);
