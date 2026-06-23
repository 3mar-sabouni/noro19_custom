# -*- coding: utf-8 -*-

from odoo import fields, models


class MedicalMedicine(models.Model):
    """For creating the medicines used in the medical clinic"""
    _inherit = 'product.template'

    is_medicine = fields.Boolean('Is Medicine',
                                 help="If the product is a Medicine")
    generic_name = fields.Char(string="Generic Name",

                               help="Generic name of the medicament")
    dosage_strength = fields.Integer(string="Dosage Strength",

                                     help="Dosage strength of medicament")
