# -*- coding: utf-8 -*-

from datetime import date
from odoo import api, fields, models


class MedicalDoctor(models.Model):
    """Extension of hr.employee to add doctors of the medical clinic"""
    _inherit = 'hr.employee'

    # ----------------------
    # Doctor-specific fields
    # ----------------------
    job_position = fields.Char(
        string="Designation",
        help="Job position of the doctor"
    )
    specialised_in_id = fields.Many2one(
        'medical.specialist',
        string='Specialised In',
        help="Specialisation of the doctor"
    )
    dob = fields.Date(
        string="Date of Birth",
        required=True,
        help="DOB of the doctor"
    )
    doctor_age = fields.Integer(
        compute='_compute_doctor_age',
        store=True,
        string="Age",
        help="Age of the doctor"
    )
    sex = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female')
    ], string="Gender", help="Gender of the doctor")
    time_shift_ids = fields.Many2many(
        'medical.time.shift',
        string="Time Shift",
        help="Time shifts assigned to the doctor"
    )
    is_doctor = fields.Boolean(string="Is a Doctor")

    # ----------------------
    # Employee type field
    # ----------------------
    employee_type = fields.Selection([
        ('doctor', 'Doctor'),
        ('receptionist', 'Receptionist'),
        ('other', 'Other')
    ], string='Employee Type', required=True, default='other', help="Type of employee")

    reg_no = fields.Char(string="Register No:")

    # ----------------------
    # Overrides
    # ----------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Automatically create an internal user with mobile login"""
        for vals in vals_list:
            if 'mobile_phone' in vals and vals['mobile_phone']:
                existing_user = self.env['res.users'].search([('login', '=', vals['mobile_phone'])])
                if existing_user:
                    raise ValueError("Mobile number already exists for another user!")

        doctors = super(MedicalDoctor, self).create(vals_list)

        for doctor in doctors:
            if doctor.mobile_phone and not doctor.user_id:
                user_vals = {
                    'name': doctor.name,
                    'login': doctor.mobile_phone,  # Set mobile number as login
                    'employee_id': doctor.id,
                    'company_id': doctor.company_id.id,
                    # 'groups_id': [(4, self.env.ref('medical.group_doctor').id)],  # Optional: Assign Doctor Group
                }
                new_user = self.env['res.users'].create(user_vals)
                doctor.user_id = new_user.id  # Link the created user to the doctor

        return doctors

    def unlink(self):
        """Delete the corresponding user from res.users when deleting the doctor"""
        for record in self:
            if record.user_id:
                record.user_id.unlink()
        return super(MedicalDoctor, self).unlink()

    # ----------------------
    # Compute Methods
    # ----------------------
    @api.depends('dob')
    def _compute_doctor_age(self):
        """Calculate the doctor's age from DOB"""
        today = date.today()
        for record in self:
            if record.dob:
                record.doctor_age = today.year - record.dob.year - (
                    (today.month, today.day) < (record.dob.month, record.dob.day)
                )
            else:
                record.doctor_age = 0
