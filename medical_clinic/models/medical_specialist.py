# -*- coding: utf-8 -*-

from odoo import fields, models


class MedicalSpecialist(models.Model):
    """To mention doctors Specialised field"""
    _name = 'medical.specialist'
    _description = "Medical Specialist"

    name = fields.Char(string="Name", help="Name of the medical specialist")
    code = fields.Char(string="Code", help="Add the code for the name")
