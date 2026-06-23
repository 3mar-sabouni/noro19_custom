# -*- coding: utf-8 -*-

from odoo import fields, models


class MedicalTreatment(models.Model):
    """For adding Medical treatment details of the patients"""
    _name = 'medical.treatment'
    _description = "Medical Treatment"

    name = fields.Char(string='Treatment Name', help="Date of the treatment")
    treatment_categ_id = fields.Many2one('treatment.category',
                                         string="Category",
                                         help="name of the treatment")
    cost = fields.Float(string='Cost',
                        help="Cost of the Treatment")
