from odoo import models, fields

class CustomerImageComparison(models.Model):
    _name = "customer.image.comparison"
    _description = "Before / After Comparison"

    name = fields.Char(required=True)

    workspace_id = fields.Many2one(
        "customer.image.workspace",
        required=True,
        ondelete="cascade"
    )

    partner_id = fields.Many2one(
        "res.partner",
        related="workspace_id.partner_id",
        store=True,
        readonly=True
    )

    before_image_id = fields.Many2one(
        "customer.image",
        required=True
    )

    after_image_id = fields.Many2one(
        "customer.image",
        required=True
    )
