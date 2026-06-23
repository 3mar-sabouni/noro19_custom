from odoo import models, fields

class CustomerImageUploadWizard(models.TransientModel):
    _name = 'customer.image.upload.wizard'
    _description = 'Multi Image Upload Wizard'

    workspace_id = fields.Many2one(
        'customer.image.workspace',
        required=True
    )

    category_id = fields.Many2one('customer.image.category')
    tag_ids = fields.Many2many('customer.image.tag')
    description = fields.Text()

    attachment_ids = fields.Many2many(
        'ir.attachment',
        string="Images"
    )

    def action_upload_images(self):
        for attachment in self.attachment_ids:
            self.env['customer.image'].create({
                'workspace_id': self.workspace_id.id,
                'image_1920': attachment.datas,
                'category_id': self.category_id.id,
                'tag_ids': [(6, 0, self.tag_ids.ids)],
                'description': self.description,
            })

        return {'type': 'ir.actions.act_window_close'}
