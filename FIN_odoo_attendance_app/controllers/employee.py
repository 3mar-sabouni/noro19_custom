# -*- coding: utf-8 -*-
import json
import logging
from odoo import http, fields
from odoo.http import request
from ..utils import jwt_helper, response_helper
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


MOBILE_API_USER_PARAM_KEYS = (
    'odoo_attendance_app.mobile_api_user_id',
    'FIN_odoo_attendance_app.mobile_api_user_id',
    'fin_odoo_attendance_app.mobile_api_user_id',
)


def _get_mobile_api_user_id():
    params = request.env['ir.config_parameter'].sudo()
    for param_key in MOBILE_API_USER_PARAM_KEYS:
        raw_value = params.get_param(param_key, None)
        if raw_value in (None, ''):
            continue
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError):
            _logger.warning(
                'Invalid mobile API user id in %s: %r',
                param_key,
                raw_value,
            )
    return None


def apply_mobile_api_user():
    user_id = _get_mobile_api_user_id()
    if not user_id:
        return None

    user = request.env['res.users'].sudo().browse(user_id)
    if not user.exists() or not user.active:
        _logger.warning(
            'Configured mobile API user is missing or inactive (user_id=%s)',
            user_id,
        )
        return None

    request.update_env(user=user.id)
    return user


def authenticate_request():
    """
    Middleware to authenticate API requests using JWT.
    Extracts and verifies access token from Authorization header.
    
    Returns: tuple (employee_app_record, hr_employee_record) or None
    """
    auth_header = request.httprequest.headers.get('Authorization')
    
    if not auth_header:
        return None
    
    token = jwt_helper.extract_bearer_token(auth_header)
    if not token:
        return None
    
    try:
        payload = jwt_helper.verify_token(request.env, token, expected_type='access')
        employee_app_id = int(payload['sub'])
        
        # Disable prefetch to avoid selecting newly-added columns before module upgrade
        EmployeeApp = request.env['odoo.attendance.employee'].sudo().with_context(prefetch_fields=False)
        employee_app = EmployeeApp.browse(employee_app_id)
        
        if not employee_app.exists() or not employee_app.is_active:
            return None

        apply_mobile_api_user()
        
        return employee_app, employee_app.employee_id
        
    except Exception as e:
        _logger.warning(f'Authentication failed: {str(e)}')
        return None


def _is_checkin_project_required():
    return _get_config_bool(
        'odoo_attendance_app.checkin_project_required',
        'checkin_project_required',
        default=True,
    )


def _is_task_project_required():
    return _get_config_bool(
        'odoo_attendance_app.task_project_required',
        'task_project_required',
        default=True,
    )


def _get_config_bool(param_key, field_name, default=True):
    raw_value = request.env['ir.config_parameter'].sudo().get_param(
        param_key,
        None,
    )
    if raw_value not in (None, ''):
        return str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
    config = request.env['odoo.attendance.app.config'].sudo().search([], order='id desc', limit=1)
    if config and field_name in config._fields:
        return bool(getattr(config, field_name))
    return default


def _is_checkin_note_required():
    return _get_config_bool(
        'odoo_attendance_app.checkin_note_required',
        'checkin_note_required',
        default=True,
    )


def _is_checkout_note_required():
    return _get_config_bool(
        'odoo_attendance_app.checkout_note_required',
        'checkout_note_required',
        default=True,
    )


class EmployeeController(http.Controller):
    """
    Employee profile and location endpoints.
    """

    def _get_vehicle_last_kilometrage(self, vehicle_id):
        """
        Return the latest entered kilometrage for a vehicle.
        Preference:
        1) Vehicle.current_kilometrage
        2) Latest trip end_kilometrage
        3) Latest trip start_kilometrage
        """
        Vehicle = request.env['odoo.attendance.vehicle'].sudo()
        vehicle = Vehicle.browse(vehicle_id)
        if vehicle and vehicle.current_kilometrage is not None:
            return float(vehicle.current_kilometrage)

        FleetTrip = request.env['odoo.attendance.fleet.trip'].sudo()
        trip = FleetTrip.search(
            [
                ('vehicle_id', '=', vehicle_id),
                ('end_kilometrage', '!=', False),
            ],
            limit=1,
            order='trip_end_date_time desc, id desc',
        )
        if trip and trip.end_kilometrage is not None:
            return float(trip.end_kilometrage)

        trip = FleetTrip.search(
            [
                ('vehicle_id', '=', vehicle_id),
                ('start_kilometrage', '!=', False),
            ],
            limit=1,
            order='trip_start_date_time desc, id desc',
        )
        if trip and trip.start_kilometrage is not None:
            return float(trip.start_kilometrage)

        Attendance = request.env['hr.attendance'].sudo()
        att = Attendance.search(
            [
                ('x_vehicle_id', '=', vehicle_id),
                ('x_end_kilometrage', '!=', False),
            ],
            limit=1,
            order='check_out desc, id desc',
        )
        if att and att.x_end_kilometrage is not None:
            return float(att.x_end_kilometrage)

        att = Attendance.search(
            [
                ('x_vehicle_id', '=', vehicle_id),
                ('x_start_kilometrage', '!=', False),
            ],
            limit=1,
            order='check_in desc, id desc',
        )
        if att and att.x_start_kilometrage is not None:
            return float(att.x_start_kilometrage)

        return None

    @http.route('/api/odoo-attendance/employee/profile', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_profile(self, **kwargs):
        """
        Get employee profile and current attendance status.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            # Authenticate
            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')
            
            employee_app, hr_employee = auth_result
            
            # Get current attendance status
            Attendance = request.env['hr.attendance'].sudo()
            current_attendance = Attendance.search([
                ('employee_id', '=', hr_employee.id),
                ('check_out', '=', False)
            ], limit=1)
            
            attendance_data = None
            if current_attendance:
                attendance_data = {
                    'id': current_attendance.id,
                    'check_in': current_attendance.check_in.isoformat() if current_attendance.check_in else None,
                    'analytic_account': {
                        'id': current_attendance.x_analytic_account_id.id,
                        'name': current_attendance.x_analytic_account_id.name
                    } if current_attendance.x_analytic_account_id else None,
                    'worked_hours': current_attendance.worked_hours
                }

            allowed_vehicles = []
            if employee_app.is_driver:
                Vehicle = request.env['odoo.attendance.vehicle'].sudo()
                vehicles = Vehicle.search([('allowed_employee_ids', 'in', [employee_app.id])], order='name asc')
                allowed_vehicles = [
                    {
                        'id': vehicle.id,
                        'name': vehicle.name,
                        'license_plate': vehicle.license_plate or '',
                        'last_kilometrage': self._get_vehicle_last_kilometrage(vehicle.id),
                    }
                    for vehicle in vehicles
                ]
            allowed_attendance_users = []
            for allowed_user in employee_app.allowed_attendance_user_ids.sudo().with_context(prefetch_fields=False):
                if not allowed_user.is_active or not allowed_user.employee_id:
                    continue
                allowed_attendance_users.append({
                    'user_id': allowed_user.id,
                    'username': allowed_user.username or '',
                    'employee_id': allowed_user.employee_id.id,
                    'employee_name': allowed_user.employee_id.name or '',
                })
            
            return response_helper.success_response({
                'employee': {
                    'id': hr_employee.id,
                    'name': hr_employee.name,
                    'username': employee_app.username,
                    'email': hr_employee.work_email or '',
                    'job_title': hr_employee.job_title or '',
                    'department': hr_employee.department_id.name if hr_employee.department_id else '',
                    'company': hr_employee.company_id.name if hr_employee.company_id else '',
                    'is_driver': bool(employee_app.is_driver),
                    'allowed_vehicles': allowed_vehicles,
                    'can_check_attendance_for_others': bool(employee_app.can_check_attendance_for_others),
                },
                'settings': {
                    'checkin_project_required': _is_checkin_project_required(),
                    'task_project_required': _is_task_project_required(),
                    'checkin_note_required': _is_checkin_note_required(),
                    'checkout_note_required': _is_checkout_note_required(),
                    'geofence_policy': employee_app.geofence_policy or 'required',
                    'geofence_required': (employee_app.geofence_policy or 'required') == 'required',
                    'geofence_locations_count': len(employee_app.geofence_location_ids),
                    'can_check_attendance_for_others': bool(employee_app.can_check_attendance_for_others),
                    'allowed_attendance_user_ids': [u['user_id'] for u in allowed_attendance_users],
                    'allowed_attendance_users': allowed_attendance_users,
                },
                'can_check_attendance_for_others': bool(employee_app.can_check_attendance_for_others),
                'allowed_attendance_user_ids': [u['user_id'] for u in allowed_attendance_users],
                'allowed_attendance_users': allowed_attendance_users,
                'attendance_status': {
                    'is_checked_in': bool(current_attendance),
                    'current_attendance': attendance_data
                }
            })
            
        except Exception as e:
            _logger.exception(f'Error in get_profile endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/employee/update-location', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def update_live_location(self, **kwargs):
        """
        Receives a location update from the mobile app in response to a request.
        """
        try:
            # Authenticate
            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')
            
            _employee_app, hr_employee = auth_result

            # Parse request body
            try:
                data = json.loads(request.httprequest.data)
            except:
                return response_helper.validation_error_response('Invalid JSON')

            gps_lat = data.get('gps_lat')
            gps_lng = data.get('gps_lng')
            gps_accuracy = data.get('gps_accuracy')

            if not all([gps_lat, gps_lng]):
                return response_helper.validation_error_response('gps_lat and gps_lng are required')

            # Find existing record to update or create a new one
            LiveLocation = request.env['employee.live.location'].sudo()
            location_record = LiveLocation.search([('employee_id', '=', hr_employee.id)], limit=1)

            location_vals = {
                'employee_id': hr_employee.id,
                'gps_lat': gps_lat,
                'gps_lng': gps_lng,
                'gps_accuracy': gps_accuracy,
                'located_at': fields.Datetime.now(),
                'status': 'received',
            }

            if location_record:
                location_record.write(location_vals)
            else:
                LiveLocation.create(location_vals)

            return response_helper.success_response({'status': 'ok'})

        except Exception as e:
            _logger.exception(f'Error in update_live_location endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')


