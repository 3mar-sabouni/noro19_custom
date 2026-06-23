# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class FleetTrip(models.Model):
    _name = "odoo.attendance.fleet.trip"
    _description = "Fleet Trip Management"
    _order = "trip_start_date_time desc"

    name = fields.Char(string="Trip Reference", compute='_compute_name', store=True)
    
    # Trip identification
    trip_start_date_time = fields.Datetime(string="Trip Start", required=True)
    trip_end_date_time = fields.Datetime(string="Trip End")
    
    # Driver and Vehicle
    driver_employee_app_id = fields.Many2one(
        'odoo.attendance.employee',
        string="Driver (Mobile App)",
        index=True,
        help="Mobile app employee who created this trip.",
    )
    driver_user_id = fields.Many2one(
        'res.users', 
        string="Driver", 
        required=False,
        help="Driver who completed this trip"
    )
    vehicle_id = fields.Many2one(
        'odoo.attendance.vehicle', 
        string="Vehicle", 
        required=True,
        help="Vehicle used for this trip"
    )
    
    # Project/Analytic tracking
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string="Analytic Account",
        help="Project or cost center for this trip"
    )
    
    # Location tracking
    start_google_maps_location = fields.Text(string="Start Location")
    end_google_maps_location = fields.Text(string="End Location")
    
    # km/mi/hr tracking
    start_kilometrage = fields.Float(string="Start (km / mi / hr)", required=True)
    end_kilometrage = fields.Float(string="End (km / mi / hr)")
    kilometrage_difference = fields.Float(
        string="Distance Travelled",
        compute='_compute_kilometrage_difference',
        store=True
    )
    
    # Status and metadata
    state = fields.Selection([
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string="Status", default='in_progress')
    
    @api.depends('driver_employee_app_id', 'driver_user_id', 'trip_start_date_time')
    def _compute_name(self):
        for record in self:
            if record.trip_start_date_time:
                date_str = record.trip_start_date_time.strftime('%Y-%m-%d')
                driver_name = (
                    record.driver_employee_app_id.employee_id.name
                    or record.driver_employee_app_id.username
                    or record.driver_user_id.name
                )
                if driver_name:
                    record.name = f"{driver_name} - {date_str}"
                else:
                    record.name = f"Trip - {date_str}"
            else:
                record.name = "New Trip"
    
    @api.depends('start_kilometrage', 'end_kilometrage')
    def _compute_kilometrage_difference(self):
        for record in self:
            if record.start_kilometrage and record.end_kilometrage:
                record.kilometrage_difference = record.end_kilometrage - record.start_kilometrage
            else:
                record.kilometrage_difference = 0

    def _complete_from_attendance(self, attendance):
        """Complete this trip from its checked-out attendance record."""
        self.ensure_one()
        attendance.ensure_one()
        if not attendance.check_out:
            return False

        end_location = attendance.x_checkout_gps_address or ''
        if not end_location and (
            attendance.x_checkout_gps_lat or attendance.x_checkout_gps_lng
        ):
            end_location = (
                'https://www.google.com/maps/search/?api=1&query='
                f'{attendance.x_checkout_gps_lat:.6f}%2C'
                f'{attendance.x_checkout_gps_lng:.6f}'
            )

        self.sudo().write({
            'trip_end_date_time': attendance.check_out,
            'end_kilometrage': attendance.x_end_kilometrage,
            'end_google_maps_location': end_location,
            'state': 'completed',
        })

        if attendance.x_end_kilometrage >= self.vehicle_id.current_kilometrage:
            try:
                self.vehicle_id.sudo().write({
                    'current_kilometrage': attendance.x_end_kilometrage,
                })
            except Exception as exc:
                _logger.warning(
                    'Trip %s completed but vehicle kilometrage update failed: %s',
                    self.id,
                    exc,
                )
        return True

    def _reconcile_from_linked_attendance(self):
        """Repair a stale open trip when its linked attendance is checked out."""
        self.ensure_one()
        attendance = self.env['hr.attendance'].sudo().search([
            ('x_fleet_trip_id', '=', self.id),
            ('check_out', '!=', False),
        ], order='check_out desc, id desc', limit=1)
        if not attendance:
            return False
        with self.env.cr.savepoint():
            self._complete_from_attendance(attendance)
        return True
    
    def action_complete_trip(self):
        self.write({'state': 'completed'})
    
    def action_cancel_trip(self):
        self.write({'state': 'cancelled'})
