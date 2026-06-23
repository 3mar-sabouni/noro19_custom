from odoo import models, fields, api


class CustomerImage(models.Model):
    _name = 'customer.image'
    _description = 'Customer Image'

    workspace_id = fields.Many2one(
        'customer.image.workspace',
        ondelete='cascade'
    )

    partner_id = fields.Many2one(
        'res.partner',
        related='workspace_id.partner_id',
        store=True,
        readonly=True,
    )

    image_1920 = fields.Image(
        string="Image",
        required=True
    )

    category_id = fields.Many2one(
        'customer.image.category',
        string="Category"
    )

    tag_ids = fields.Many2many(
        'customer.image.tag',
        string="Tags"
    )

    description = fields.Text()

    date = fields.Date(
        default=fields.Date.context_today
    )

    compare = fields.Boolean(
        string="Compare"
    )

    image_url = fields.Char(
        compute="_compute_image_url",
        store=False
    )

    def _compute_image_url(self):
        for rec in self:
            rec.image_url = f"/web/image/customer.image/{rec.id}/image_1920"
    def copy(self, default=None):
        """
        Duplicate record but force new image upload
        """
        default = dict(default or {})
        default['image_1920'] = False   # 🔥 clear image
        return super(CustomerImage, self).copy(default)
