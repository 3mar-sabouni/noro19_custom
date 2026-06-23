# -*- coding: utf-8 -*-

from odoo import fields, models


class MedicalSource(models.Model):
    """Adding the Source """
    _name = 'medical.source'
    _description = "Medical  Source"

    name = fields.Char(string="Name", help=" Source Name like 'facebook' etc")
