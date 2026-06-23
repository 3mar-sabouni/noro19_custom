# -*- coding: utf-8 -*-
from odoo import fields, models


class OdooAttendanceEmployeeLocation(models.Model):
    _name = 'odoo.attendance.employee.location'
    _description = 'Mobile App Employee Geofence Location'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Location Name')
    employee_app_id = fields.Many2one(
        'odoo.attendance.employee',
        string='Mobile App Employee',
        required=True,
        ondelete='cascade',
    )
    latitude = fields.Float(string='Latitude', digits=(10, 7))
    longitude = fields.Float(string='Longitude', digits=(10, 7))
    radius_km = fields.Float(string='Allowed Radius (km)')
    active = fields.Boolean(default=True)
