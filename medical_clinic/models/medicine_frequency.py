# -*- coding: utf-8 -*-

from odoo import fields, models


class MedicineFrequency(models.Model):
    """To specifing the medicine frequency, how to consume it."""
    _name = 'medicine.frequency'
    _description = "Medicine Frequency"
    _rec_name = "medicament_frequency"

    code = fields.Char(string="Code", help="code of medicine frequency")
    medicament_frequency = fields.Char(string="Medicine Frequency",
                                       help="Add the frquency of medicine how to eat")
