# -*- coding: utf-8 -*-

from odoo import fields, models


class TreatmentCategory(models.Model):
    """Adding the treatment category"""
    _name = 'treatment.category'
    _description = "Treatment Category"

    name = fields.Char(string="Name", help="Name of the treatment category")
