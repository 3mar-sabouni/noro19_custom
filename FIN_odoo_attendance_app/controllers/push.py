# -*- coding: utf-8 -*-
import json
import logging

from odoo import http, fields
from odoo.http import request

from .employee import authenticate_request
from ..utils import jwt_helper
from ..utils import response_helper
from .subscription import require_active_subscription


_logger = logging.getLogger(__name__)


class PushController(http.Controller):
    """
    Push notification registration endpoints (Android + iOS via FCM).
    """

    @http.route('/api/odoo-attendance/push/register', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def register_push_token(self, **kwargs):
        """
        Register (or update) the device push token for the authenticated Mobile App Employee.

        POST /api/odoo-attendance/push/register
        Authorization: Bearer <access_token>
        Body: { "fcm_token": "<token>", "platform": "android|ios" }
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            employee_app, _hr_employee = auth_result

            try:
                data = json.loads(request.httprequest.data or b'{}')
            except Exception:
                return response_helper.validation_error_response('Invalid JSON in request body')

            token = (data.get('fcm_token') or '').strip()
            platform = (data.get('platform') or '').strip().lower()
            if not token:
                return response_helper.validation_error_response('Missing required field: fcm_token')

            employee_app.sudo().write(
                {
                    'fcm_token': token,
                    'fcm_token_updated_at': fields.Datetime.now(),
                }
            )

            # Also bind token to the current authenticated session/device.
            try:
                auth_header = request.httprequest.headers.get('Authorization')
                access_token = jwt_helper.extract_bearer_token(auth_header) if auth_header else None
                if access_token:
                    payload = jwt_helper.verify_token(request.env, access_token, expected_type='access')
                    device_id = (payload.get('device_id') or '').strip()
                    if device_id:
                        Session = request.env['odoo.attendance.session'].sudo()
                        session = Session.search(
                            [
                                ('employee_app_id', '=', employee_app.id),
                                ('device_id', '=', device_id),
                                ('is_revoked', '=', False),
                            ],
                            limit=1,
                            order='created_at desc',
                        )
                        if session:
                            session.write(
                                {
                                    'fcm_token': token,
                                    'fcm_token_updated_at': fields.Datetime.now(),
                                }
                            )
            except Exception:
                _logger.exception('Failed to bind FCM token to session (employee_app_id=%s)', employee_app.id)

            _logger.info(
                'FCM token registered (employee_app_id=%s, platform=%s, token_len=%s, token_suffix=%s)',
                employee_app.id,
                platform or 'unknown',
                len(token),
                token[-8:] if len(token) >= 8 else token,
            )
            return response_helper.success_response({'registered': True, 'platform': platform or 'unknown'})
        except Exception as e:
            _logger.exception('Error in push/register: %s', e)
            return response_helper.server_error_response('An error occurred')
