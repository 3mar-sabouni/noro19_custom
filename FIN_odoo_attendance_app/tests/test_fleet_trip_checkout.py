from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestFleetTripCheckout(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_attendance_app.checkin_project_required',
            'False',
        )
        self.employee = self.env['hr.employee'].create({'name': 'Test Driver'})
        self.vehicle = self.env['odoo.attendance.vehicle'].create({
            'name': 'Test Vehicle',
            'current_kilometrage': 100.0,
        })
        self.check_in = fields.Datetime.now() - timedelta(hours=1)

    def _create_trip(self):
        return self.env['odoo.attendance.fleet.trip'].create({
            'trip_start_date_time': self.check_in,
            'vehicle_id': self.vehicle.id,
            'start_kilometrage': 100.0,
        })

    def test_attendance_checkout_completes_linked_trip(self):
        trip = self._create_trip()
        attendance = self.env['hr.attendance'].create({
            'employee_id': self.employee.id,
            'check_in': self.check_in,
            'x_vehicle_id': self.vehicle.id,
            'x_start_kilometrage': 100.0,
            'x_fleet_trip_id': trip.id,
        })
        check_out = fields.Datetime.now()

        attendance.write({
            'check_out': check_out,
            'x_end_kilometrage': 125.0,
            'x_checkout_gps_address': 'Test destination',
        })

        self.assertEqual(trip.state, 'completed')
        self.assertEqual(trip.trip_end_date_time, check_out)
        self.assertEqual(trip.end_kilometrage, 125.0)
        self.assertEqual(trip.end_google_maps_location, 'Test destination')
        self.assertEqual(self.vehicle.current_kilometrage, 125.0)

    def test_reconcile_repairs_stale_open_trip(self):
        trip = self._create_trip()
        check_out = fields.Datetime.now()
        self.env['hr.attendance'].create({
            'employee_id': self.employee.id,
            'check_in': self.check_in,
            'check_out': check_out,
            'x_vehicle_id': self.vehicle.id,
            'x_start_kilometrage': 100.0,
            'x_end_kilometrage': 130.0,
            'x_fleet_trip_id': trip.id,
        })

        self.assertTrue(trip._reconcile_from_linked_attendance())
        self.assertEqual(trip.state, 'completed')
        self.assertEqual(trip.trip_end_date_time, check_out)
        self.assertEqual(trip.end_kilometrage, 130.0)
