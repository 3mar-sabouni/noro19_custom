
from odoo import models, fields

class CustomerImageCategory(models.Model):
    _name = "customer.image.category"
    _description = "Image Category"

    name = fields.Char(required=True)
