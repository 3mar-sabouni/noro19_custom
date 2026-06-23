from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_doctor = fields.Boolean(string="Is a Doctor")
    employee_type = fields.Selection(selection_add=[
        ('doctor', 'Doctor'),
        ('receptionist', 'Receptionist')
    ],ondelete={'doctor': 'set default', 'receptionist': 'set default'})

