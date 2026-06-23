# -*- coding: utf-8 -*-
from odoo import models, fields


class OdooAttendanceVehicle(models.Model):
    _name = "odoo.attendance.vehicle"
    _description = "FIN Attendance Vehicle"

    name = fields.Char(string="Vehicle Name", required=True)
    license_plate = fields.Char(string="License Plate")
    description = fields.Text(string="Internal Notes")
    active = fields.Boolean(string="Active", default=True)
    
    # New fleet tracking fields
    current_kilometrage = fields.Float(string="Current (km / mi / hr)", help="Current odometer reading")
    vehicle_type = fields.Selection([
        ('car', 'Car'),
        ('truck', 'Truck'),
        ('van', 'Van'),
        ('motorcycle', 'Motorcycle'),
    ], string="Vehicle Type")
    vehicle_status = fields.Selection([
        ('active', 'Active'),
        ('in_maintenance', 'In Maintenance'),
        ('retired', 'Retired'),
    ], string="Vehicle Status", default='active')
    last_maintenance_kilometrage = fields.Float(string="Last Maintenance (km / mi / hr)")
    vehicle_specifications = fields.Text(string="Vehicle Specifications")
    fuel_type = fields.Selection([
        ('petrol', 'Petrol'),
        ('diesel', 'Diesel'),
        ('electric', 'Electric'),
        ('hybrid', 'Hybrid'),
    ], string="Fuel Type")
    purchase_date = fields.Date(string="Purchase Date")
    vin_number = fields.Char(string="VIN Number")

    allowed_employee_ids = fields.Many2many(
        "odoo.attendance.employee",
        "odoo_attendance_vehicle_employee_rel",
        "vehicle_id",
        "employee_app_id",
        string="Allowed Drivers",
        help="Mobile app employees who are allowed to select this vehicle.",
    )
