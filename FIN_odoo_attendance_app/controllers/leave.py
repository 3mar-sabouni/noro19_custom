# -*- coding: utf-8 -*-
import json
import base64
import logging
from datetime import datetime
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import ValidationError
from .employee import authenticate_request
from ..utils import response_helper
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


class LeaveController(http.Controller):
    """
    Time off / leave management endpoints.
    """
    
    def _mobile_leave_types(self, hr_employee):
        LeaveType = request.env['hr.leave.type'].sudo()
        leave_types = LeaveType.search(
            [('active', '=', True)],
            order='sequence asc, name asc'
        )

        names = {}
        for lt in leave_types:
            # Match Odoo Time Off configuration names as-is.
            names[lt.id] = (lt.name or lt.display_name or '').strip()
        return leave_types, names
    
    @http.route('/api/odoo-attendance/leave/types', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_leave_types(self, **kwargs):
        """
        Get available leave types.
        
        GET /api/odoo-attendance/leave/types
        Authorization: Bearer <access_token>
        
        Response:
        {
            "success": true,
            "data": [
                {
                    "id": 1,
                    "name": "Paid Time Off",
                    "code": "PTO",
                    "request_unit": "day/hour",
                    ...
                }
            ]
        }
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
            
            leave_types, leave_type_names = self._mobile_leave_types(hr_employee)
            
            results = []
            for lt in leave_types:
                results.append({
                    'id': lt.id,
                    'name': leave_type_names.get(lt.id, lt.name),
                    'code': lt.code if hasattr(lt, 'code') else '',
                    'request_unit': lt.request_unit,
                    'requires_allocation': lt.requires_allocation if hasattr(lt, 'requires_allocation') else False
                })
            
            return response_helper.success_response(results)
            
        except Exception as e:
            _logger.exception(f'Error in get_leave_types endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')
    
    
    @http.route('/api/odoo-attendance/leave/balance', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_leave_balance(self, **kwargs):
        """
        Get leave balances for all leave types.
        
        GET /api/odoo-attendance/leave/balance
        Authorization: Bearer <access_token>
        
        Response:
        {
            "success": true,
            "data": [
                {
                    "leave_type_id": 1,
                    "leave_type_name": "Paid Time Off",
                    "allocated": 20.0,
                    "taken": 5.5,
                    "remaining": 14.5
                }
            ]
        }
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
            leave_types, leave_type_names = self._mobile_leave_types(hr_employee)
            allowed_type_ids = {lt.id for lt in leave_types}

            # Only show "current" allocations (active today) to avoid listing historical periods.
            # We treat allocations as current if their validity period includes "today":
            # - date_from is empty or <= today
            # - date_to is empty or >= today
            today = fields.Date.context_today(request.env.user)
            
            # Get allocations
            Allocation = request.env['hr.leave.allocation'].sudo()
            alloc_domain = [
                ('employee_id', '=', hr_employee.id),
                ('state', '=', 'validate'),
            ]
            # Odoo versions differ slightly; guard on field existence.
            if 'date_from' in Allocation._fields:
                alloc_domain += ['|', ('date_from', '=', False), ('date_from', '<=', today)]
            if 'date_to' in Allocation._fields:
                alloc_domain += ['|', ('date_to', '=', False), ('date_to', '>=', today)]

            allocations = Allocation.search(alloc_domain)
            
            # Get leave requests
            Leave = request.env['hr.leave'].sudo()
            leaves = Leave.search([
                ('employee_id', '=', hr_employee.id),
                ('state', '=', 'validate'),
            ])
            
            # Group by leave type
            balance_data = {}
            alloc_windows = {}
            
            # Process allocations
            for alloc in allocations:
                leave_type_id = alloc.holiday_status_id.id
                if leave_type_id not in allowed_type_ids:
                    continue
                # Track an effective "current window" per leave type to filter taken leaves as well.
                if leave_type_id not in alloc_windows:
                    alloc_windows[leave_type_id] = {'start': None, 'end': None}
                start = alloc.date_from if hasattr(alloc, 'date_from') else None
                end = alloc.date_to if hasattr(alloc, 'date_to') else None
                # If any allocation has no start/end, treat the window edge as open.
                if start:
                    cur = alloc_windows[leave_type_id]['start']
                    alloc_windows[leave_type_id]['start'] = start if (cur is None or start < cur) else cur
                if end:
                    cur = alloc_windows[leave_type_id]['end']
                    alloc_windows[leave_type_id]['end'] = end if (cur is None or end > cur) else cur
                if not start:
                    alloc_windows[leave_type_id]['start'] = None
                if not end:
                    alloc_windows[leave_type_id]['end'] = None

                if leave_type_id not in balance_data:
                    balance_data[leave_type_id] = {
                        'leave_type_id': leave_type_id,
                        'leave_type_name': leave_type_names.get(
                            leave_type_id,
                            alloc.holiday_status_id.name
                        ),
                        'allocated': 0.0,
                        'taken': 0.0
                    }
                balance_data[leave_type_id]['allocated'] += alloc.number_of_days
            
            # Process taken leaves
            for leave in leaves:
                leave_type_id = leave.holiday_status_id.id
                if leave_type_id not in allowed_type_ids:
                    continue
                # Only show balances for leave types that have a current (active today) allocation.
                # Otherwise old leave types (or expired allocation periods) show up as "allocated 0 / negative remaining".
                if leave_type_id not in balance_data:
                    continue
                # If we have a validity window for this leave type, only count leaves in that window.
                if leave_type_id in alloc_windows:
                    win = alloc_windows[leave_type_id]
                    start = win.get('start')
                    end = win.get('end')
                    leave_start = leave.request_date_from if hasattr(leave, 'request_date_from') else None
                    leave_end = leave.request_date_to if hasattr(leave, 'request_date_to') else None
                    if leave_start and start and leave_start < start:
                        continue
                    if leave_end and end and leave_end > end:
                        continue
                if leave_type_id not in balance_data:
                    balance_data[leave_type_id] = {
                        'leave_type_id': leave_type_id,
                        'leave_type_name': leave_type_names.get(
                            leave_type_id,
                            leave.holiday_status_id.name
                        ),
                        'allocated': 0.0,
                        'taken': 0.0
                    }
                balance_data[leave_type_id]['taken'] += leave.number_of_days
            
            # Calculate remaining
            results = []
            for data in balance_data.values():
                data['remaining'] = round(data['allocated'] - data['taken'], 2)
                data['allocated'] = round(data['allocated'], 2)
                data['taken'] = round(data['taken'], 2)
                results.append(data)
            
            return response_helper.success_response(results)
            
        except Exception as e:
            _logger.exception(f'Error in get_leave_balance endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')
    
    
    @http.route('/api/odoo-attendance/leave/request', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_leave_request(self, **kwargs):
        """
        Create a leave request.
        
        POST /api/odoo-attendance/leave/request
        Authorization: Bearer <access_token>
        
        Request body:
        {
            "leave_type_id": 1,
            "date_from": "2026-01-10",
            "date_to": "2026-01-12",
            "request_unit": "day",  // or "half_day", "hour"
            "request_date_from_period": "am",  // for half_day: "am" or "pm"
            "request_hour_from": "9.0",  // for hour
            "request_hour_to": "17.0",  // for hour
            "name": "Family vacation",
            "attachment_base64": "...",  // optional
            "attachment_name": "medical_certificate.pdf"  // optional
        }
        
        Response:
        {
            "success": true,
            "data": {
                "leave_id": 123,
                "state": "confirm",
                "number_of_days": 3.0
            }
        }
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
            
            # Parse request body
            try:
                data = json.loads(request.httprequest.data)
            except:
                return response_helper.validation_error_response('Invalid JSON in request body')
            
            # Validate required fields
            leave_type_id = data.get('leave_type_id')
            date_from = data.get('date_from')
            date_to = data.get('date_to')
            request_unit = data.get('request_unit', 'day')
            name = data.get('name', 'Leave request from mobile app')
            
            if not leave_type_id or not date_from or not date_to:
                return response_helper.validation_error_response(
                    'Missing required fields: leave_type_id, date_from, date_to'
                )

            try:
                leave_type_id = int(leave_type_id)
            except Exception:
                return response_helper.validation_error_response('leave_type_id must be a valid integer.')

            leave_types, _leave_type_names = self._mobile_leave_types(hr_employee)
            if leave_type_id not in set(leave_types.ids):
                return response_helper.forbidden_response(
                    'This leave type is not available for your employee profile.'
                )
            
            # Parse dates
            try:
                date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
                date_to_dt = datetime.strptime(date_to, '%Y-%m-%d')
            except:
                return response_helper.validation_error_response('Invalid date format. Use YYYY-MM-DD')
            
            # Prepare leave values
            leave_vals = {
                'employee_id': hr_employee.id,
                'holiday_status_id': leave_type_id,
                'request_date_from': date_from_dt,
                'request_date_to': date_to_dt,
                'request_unit_half': request_unit == 'half_day',
                'request_unit_hours': request_unit == 'hour',
                'name': name
            }
            
            # Add half-day specific fields
            if request_unit == 'half_day':
                leave_vals['request_date_from_period'] = data.get('request_date_from_period', 'am')
            
            # Add hour-based fields
            if request_unit == 'hour':
                leave_vals['request_hour_from'] = data.get('request_hour_from', '9.0')
                leave_vals['request_hour_to'] = data.get('request_hour_to', '17.0')
            
            # Create leave request
            Leave = request.env['hr.leave'].sudo()
            leave = Leave.with_context(fin_skip_leave_approval_notify=True).create(leave_vals)
            
            # Handle attachment if provided
            if data.get('attachment_base64'):
                try:
                    Attachment = request.env['ir.attachment'].sudo()
                    attachment_name = data.get('attachment_name', 'attachment.pdf')
                    Attachment.create({
                        'name': attachment_name,
                        'type': 'binary',
                        'datas': data['attachment_base64'],
                        'res_model': 'hr.leave',
                        'res_id': leave.id,
                        'mimetype': 'application/pdf'
                    })
                except Exception as e:
                    _logger.warning(f'Failed to save attachment: {str(e)}')
            
            return response_helper.success_response({
                'leave_id': leave.id,
                'state': leave.state,
                'number_of_days': leave.number_of_days,
                'date_from': leave.request_date_from.isoformat() if leave.request_date_from else None,
                'date_to': leave.request_date_to.isoformat() if leave.request_date_to else None
            }, message='Leave request created successfully')
            
        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in create_leave_request endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred while creating leave request')
    
    
    @http.route('/api/odoo-attendance/leave/requests', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_leave_requests(self, **kwargs):
        """
        Get leave request history.
        
        GET /api/odoo-attendance/leave/requests?limit=50
        Authorization: Bearer <access_token>
        
        Response:
        {
            "success": true,
            "data": [
                {
                    "id": 123,
                    "leave_type": "Paid Time Off",
                    "date_from": "2026-01-10",
                    "date_to": "2026-01-12",
                    "number_of_days": 3.0,
                    "state": "validate",
                    "state_label": "Approved"
                }
            ]
        }
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
            leave_types, leave_type_names = self._mobile_leave_types(hr_employee)
            allowed_type_ids = {lt.id for lt in leave_types}
            
            # Get query params
            limit = int(request.params.get('limit', 50))
            
            # Search leave requests
            Leave = request.env['hr.leave'].sudo()
            domain = [
                ('employee_id', '=', hr_employee.id),
                ('holiday_status_id', 'in', list(allowed_type_ids)),
            ]
            leaves = Leave.search(domain, limit=limit, order='create_date desc')
            
            # State labels
            state_labels = {
                'draft': 'Draft',
                'confirm': 'To Approve',
                'refuse': 'Refused',
                'validate1': 'Second Approval',
                'validate': 'Approved',
                'cancel': 'Cancelled'
            }
            
            results = []
            for leave in leaves:
                results.append({
                    'id': leave.id,
                    'leave_type': leave_type_names.get(
                        leave.holiday_status_id.id,
                        leave.holiday_status_id.name
                    ),
                    'leave_type_id': leave.holiday_status_id.id,
                    'date_from': leave.request_date_from.strftime('%Y-%m-%d') if leave.request_date_from else None,
                    'date_to': leave.request_date_to.strftime('%Y-%m-%d') if leave.request_date_to else None,
                    'number_of_days': round(leave.number_of_days, 2),
                    'state': leave.state,
                    'state_label': state_labels.get(leave.state, leave.state),
                    'name': leave.name,
                    'request_unit': leave.request_unit if hasattr(leave, 'request_unit') else 'day'
                })
            
            return response_helper.success_response(results)
            
        except Exception as e:
            _logger.exception(f'Error in get_leave_requests endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')
