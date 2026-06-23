from odoo import models, fields


class MedicalPurpose(models.Model):
    _name = 'medical.purpose'
    _description = 'Medical Treatment Purpose'

    name = fields.Char(string='Treatment name', store=True)
