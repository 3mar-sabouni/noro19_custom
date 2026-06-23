
from odoo import models, fields

class CustomerImageTag(models.Model):
    _name = "customer.image.tag"
    _description = "Image Tag"

    name = fields.Char(required=True)
