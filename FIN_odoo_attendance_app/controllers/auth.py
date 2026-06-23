# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta
from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request
from ..utils import jwt_helper, password_helper, response_helper, license_helper
from .subscription import require_active_subscription
from .employee import apply_mobile_api_user

_logger = logging.getLogger(__name__)


class AuthController(http.Controller):
    """
    Authentication endpoints for mobile app.
    Handles login and token refresh.
    """
    
    @http.route('/api/odoo-attendance/auth/login', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def login(self, **kwargs):
        """
        Login endpoint with device binding.
        
        POST /api/odoo-attendance/auth/login
        
        Request body:
        {
            "username": "john.doe",
            "password": "password123",
            "device_id": "android-abc123def456"
        }
        
        Response:
        {
            "success": true,
            "data": {
                "access_token": "eyJ...",
                "refresh_token": "eyJ...",
                "employee": {
                    "id": 123,
                    "name": "John Doe",
                    "username": "john.doe"
                }
            }
        }
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp
            apply_mobile_api_user()

            # Require a signed license token (issued by the license server) so the mobile app can enforce licensing
            # even if the customer tampers with the Odoo module code.
            license_token, token_msg = license_helper.get_signed_license_token(request.env, allow_refresh=False)
            if not license_token:
                license_token, token_msg = license_helper.get_signed_license_token(request.env, allow_refresh=True)
            if not license_token:
                return response_helper.payment_required_response(token_msg or 'Subscription required')

            # Parse request body
            try:
                data = json.loads(request.httprequest.data)
            except:
                return response_helper.validation_error_response('Invalid JSON in request body')
            
            username = data.get('username')
            password = data.get('password')
            device_id = (data.get('device_id') or '').strip()
            
            # Validate required fields
            if not username or not password or not device_id:
                return response_helper.validation_error_response('Missing required fields: username, password, device_id')
            
            # Find employee app record (disable prefetch to avoid selecting newly-added columns before module upgrade)
            EmployeeApp = request.env['odoo.attendance.employee'].sudo().with_context(prefetch_fields=False)
            employee_app = EmployeeApp.search([('username', '=', username)], limit=1)
            
            if not employee_app:
                _logger.warning(f'Login failed: username not found: {username}')
                return response_helper.unauthorized_response('Invalid credentials')
            
            # Check if account is active
            if not employee_app.is_active:
                return response_helper.forbidden_response('Account is disabled. Contact administrator.')
            
            # Verify password
            if not password_helper.verify_password(password, employee_app.password_hash):
                _logger.warning(f'Login failed: invalid password for username: {username}')
                return response_helper.unauthorized_response('Invalid credentials')
            
            # Verify device binding
            if not employee_app.verify_device(device_id):
                _logger.warning(f'Login failed: device not authorized for username: {username}')
                return response_helper.forbidden_response(
                    'Device not authorized. This device is already linked to another account or this account is linked to another device. Contact administrator to reset.'
                )
            
            # Bind device on first login
            if not employee_app.device_id:
                employee_app.bind_device(device_id)
            
            # Update last login
            employee_app.update_last_login()
            
            # Generate tokens
            access_token = jwt_helper.generate_access_token(
                request.env,
                employee_app.id,
                employee_app.employee_id.id,
                employee_app.username,
                device_id
            )
            
            refresh_token = jwt_helper.generate_refresh_token(
                request.env,
                employee_app.id,
                device_id
            )
            
            # Store refresh token hash in sessions table
            Session = request.env['odoo.attendance.session'].sudo()
            
            # Remove old session for this employee/device
            old_sessions = Session.search([
                ('employee_app_id', '=', employee_app.id),
                ('device_id', '=', device_id)
            ])
            old_sessions.unlink()
            
            # Create new session
            Session.create({
                'employee_app_id': employee_app.id,
                'refresh_token_hash': jwt_helper.hash_refresh_token(refresh_token),
                'device_id': device_id,
                'expires_at': datetime.now() + timedelta(days=jwt_helper.REFRESH_TOKEN_EXPIRY_DAYS)
            })
            
            # Return response
            return response_helper.success_response({
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_type': 'Bearer',
                'expires_in': jwt_helper.ACCESS_TOKEN_EXPIRY_HOURS * 3600,
                'license_token': license_token,
                'employee': {
                    'id': employee_app.employee_id.id,
                    'name': employee_app.employee_id.name,
                    'username': employee_app.username,
                    'email': employee_app.employee_id.work_email or '',
                    'job_title': employee_app.employee_id.job_title or '',
                }
            })
            
        except ValidationError as e:
            return response_helper.forbidden_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in login endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred during login')
    
    
    @http.route('/api/odoo-attendance/auth/refresh', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def refresh(self, **kwargs):
        """
        Refresh access token using refresh token.
        
        POST /api/odoo-attendance/auth/refresh
        
        Request body:
        {
            "refresh_token": "eyJ..."
        }
        
        Response:
        {
            "success": true,
            "data": {
                "access_token": "eyJ...",
                "refresh_token": "eyJ..."
            }
        }
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp
            apply_mobile_api_user()

            license_token, token_msg = license_helper.get_signed_license_token(request.env, allow_refresh=False)
            if not license_token:
                license_token, token_msg = license_helper.get_signed_license_token(request.env, allow_refresh=True)
            if not license_token:
                return response_helper.payment_required_response(token_msg or 'Subscription required')

            # Parse request body
            try:
                data = json.loads(request.httprequest.data)
            except:
                return response_helper.validation_error_response('Invalid JSON in request body')
            
            refresh_token = data.get('refresh_token')
            
            if not refresh_token:
                return response_helper.validation_error_response('Missing refresh_token')
            
            # Verify refresh token
            try:
                payload = jwt_helper.verify_token(request.env, refresh_token, expected_type='refresh')
            except Exception as e:
                _logger.warning(f'Invalid refresh token: {str(e)}')
                return response_helper.unauthorized_response('Invalid or expired refresh token')
            
            employee_app_id = int(payload['sub'])
            device_id = payload['device_id']
            
            # Verify session exists in database
            Session = request.env['odoo.attendance.session'].sudo()
            token_hash = jwt_helper.hash_refresh_token(refresh_token)
            
            session = Session.search([
                ('employee_app_id', '=', employee_app_id),
                ('device_id', '=', device_id),
                ('refresh_token_hash', '=', token_hash)
            ], limit=1)
            
            if not session or not session.is_valid():
                return response_helper.unauthorized_response('Session expired or revoked')
            
            # Get employee app record (disable prefetch to avoid selecting newly-added columns before module upgrade)
            EmployeeApp = request.env['odoo.attendance.employee'].sudo().with_context(prefetch_fields=False)
            employee_app = EmployeeApp.browse(employee_app_id)
            
            if not employee_app.exists() or not employee_app.is_active:
                return response_helper.forbidden_response('Account is disabled')
            
            # Generate new access token
            access_token = jwt_helper.generate_access_token(
                request.env,
                employee_app.id,
                employee_app.employee_id.id,
                employee_app.username,
                device_id
            )
            
            # Optionally rotate refresh token
            new_refresh_token = jwt_helper.generate_refresh_token(
                request.env,
                employee_app.id,
                device_id
            )
            
            # Update session with new token
            session.write({
                'refresh_token_hash': jwt_helper.hash_refresh_token(new_refresh_token),
                'expires_at': datetime.now() + timedelta(days=jwt_helper.REFRESH_TOKEN_EXPIRY_DAYS)
            })
            
            return response_helper.success_response({
                'access_token': access_token,
                'refresh_token': new_refresh_token,
                'token_type': 'Bearer',
                'expires_in': jwt_helper.ACCESS_TOKEN_EXPIRY_HOURS * 3600,
                'license_token': license_token,
            })
            
        except Exception as e:
            _logger.exception(f'Error in refresh endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred during token refresh')

    @http.route('/api/odoo-attendance/auth/logout', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def logout(self, **kwargs):
        """
        Logout endpoint:
        - Revokes current device session
        - Clears FCM token so push notifications stop after logout
        """
        try:
            apply_mobile_api_user()
            auth_header = request.httprequest.headers.get('Authorization')
            if not auth_header:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            token = jwt_helper.extract_bearer_token(auth_header)
            if not token:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            try:
                payload = jwt_helper.verify_token(request.env, token, expected_type='access')
            except Exception:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            employee_app_id = int(payload['sub'])
            device_id = (payload.get('device_id') or '').strip()

            Session = request.env['odoo.attendance.session'].sudo()
            domain = [('employee_app_id', '=', employee_app_id)]
            if device_id:
                domain.append(('device_id', '=', device_id))
            sessions = Session.search(domain)
            if sessions:
                sessions.write({
                    'is_revoked': True,
                    'fcm_token': False,
                    'fcm_token_updated_at': False,
                })

            EmployeeApp = request.env['odoo.attendance.employee'].sudo().with_context(prefetch_fields=False)
            employee_app = EmployeeApp.browse(employee_app_id)
            if employee_app.exists():
                employee_app.write({
                    'fcm_token': False,
                    'fcm_token_updated_at': False,
                })

            return response_helper.success_response({'logged_out': True})
        except Exception as e:
            _logger.exception(f'Error in logout endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred during logout')
