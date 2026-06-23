from odoo import models, fields, api


class CustomerImageWorkspace(models.Model):
    _name = 'customer.image.workspace'
    _description = 'Patient  Image Workspace'

    name = fields.Char(compute="_compute_name", store=True)

    partner_id = fields.Many2one(
        'res.partner',
        required=True
    )

    image_ids = fields.One2many(
        'customer.image',
        'workspace_id',
        string='All Images'
    )

    # UI-only filter
    image_category_id = fields.Many2one(
        'customer.image.category',
        string="Category",
        store=False,
    )

    # 🔥 THIS IS WHAT KANBAN USES
    filtered_image_ids = fields.One2many(
        'customer.image',
        compute='_compute_filtered_images',
        store=False,
    )

    compare_image_ids = fields.One2many(
        'customer.image',
        compute='_compute_compare_images',
        store=False,
    )

    # ✅ PUBLIC BUTTON METHOD
    def action_apply_filter(self):
        """Button hook to refresh kanban"""
        # Just touching the record forces recompute
        return True

    @api.depends('image_ids', 'image_category_id')
    def _compute_filtered_images(self):
        for rec in self:
            images = rec.image_ids.filtered(
                lambda i: i.partner_id == rec.partner_id
            )
            if rec.image_category_id:
                images = images.filtered(
                    lambda i: i.category_id == rec.image_category_id
                )
            rec.filtered_image_ids = images

    @api.depends('filtered_image_ids.compare')
    def _compute_compare_images(self):
        for rec in self:
            rec.compare_image_ids = rec.filtered_image_ids.filtered(
                lambda i: i.compare
            )

    @api.depends("partner_id")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.partner_id.name or "Workspace"

    def action_apply_filter(self):
        domain = [('workspace_id', '=', self.id)]

        if self.image_category_id:
            domain.append(('category_id', '=', self.image_category_id.id))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'customer.image.workspace',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
            'context': {
                'image_domain': domain,
            }
        }

