# -*- coding: utf-8 -*-
from odoo import fields, models


class AnalyticAccountLocation(models.Model):
    _name = 'odoo.attendance.analytic.location'
    _description = 'Analytic Account Location'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Location Name')
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        required=True,
        ondelete='cascade',
    )
    latitude = fields.Float(string='Latitude', digits=(10, 7))
    longitude = fields.Float(string='Longitude', digits=(10, 7))
    radius_km = fields.Float(string='Allowed Radius (km)')
    active = fields.Boolean(default=True)
