# -*- coding: utf-8 -*-
import json
import logging

from odoo import http, fields
from odoo.http import request

from ..utils import response_helper
from .employee import authenticate_request
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


class LocationController(http.Controller):
    @http.route(
        '/api/odoo-attendance/location/update',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        cors='*',
    )
    def update_location(self, **kwargs):
        """
        Update last-known location for the authenticated mobile employee.
        This is "last known" unless the app sends frequent updates.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            employee_app, hr_employee = auth_result

            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                return response_helper.validation_error_response('Invalid JSON in request body')

            gps_lat = data.get('gps_lat')
            gps_lng = data.get('gps_lng')
            gps_accuracy = data.get('gps_accuracy')
            gps_address = data.get('gps_address', '')

            if gps_lat is None or gps_lng is None:
                return response_helper.validation_error_response('gps_lat and gps_lng are required')

            _logger.info('Location update received: employee=%s app_id=%s lat=%s lng=%s', hr_employee.name, employee_app.id, gps_lat, gps_lng)

            Location = request.env['hr.employee.location.latest'].sudo()
            # Search by employee_id since it's unique
            existing = Location.search([('employee_id', '=', hr_employee.id)], limit=1)
            
            vals = {
                'employee_id': hr_employee.id,
                'latitude': gps_lat,
                'longitude': gps_lng,
                'accuracy': gps_accuracy,
                'timestamp_utc': fields.Datetime.now(),
                'source': 'mobile',
            }
            
            if existing:
                existing.write(vals)
            else:
                Location.create(vals)

            return response_helper.success_response({'ok': True})
        except Exception as e:
            _logger.exception(f'Error in location/update: {e}')
            return response_helper.server_error_response('An error occurred')

    @http.route(
        '/api/odoo-attendance/location/checked-in-employees',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
        cors='*',
    )
    def get_checked_in_employees(self, **kwargs):
        """
        Returns a list of all employees who are currently checked in.
        """
        try:
            # Search for attendance records that have not been checked out
            checked_in_attendances = request.env['hr.attendance'].search([
                ('check_out', '=', False)
            ])
            # Get the unique employee IDs from these attendance records
            employee_ids = checked_in_attendances.mapped('employee_id').ids
            
            # Search for the employee details based on the collected IDs
            employees = request.env['hr.employee'].search_read(
                [('id', 'in', employee_ids)],
                ['id', 'name', 'work_email']
            )
            return response_helper.success_response(employees)
        except Exception as e:
            _logger.exception(f'Error in get_checked_in_employees: {e}')
            return response_helper.server_error_response('An error occurred')

