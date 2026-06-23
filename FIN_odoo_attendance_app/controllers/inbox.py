# -*- coding: utf-8 -*-
import logging
from datetime import timezone

from odoo import http, fields
from odoo.http import request

from ..utils import response_helper
from .employee import authenticate_request
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


class InboxController(http.Controller):
    @staticmethod
    def _to_utc_iso(dt):
        """Return ISO8601 string with explicit UTC offset for mobile parsing."""
        if not dt:
            return None
        # Odoo stores Datetime in UTC as naive values; mark as UTC explicitly.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace('+00:00', 'Z')

    def _get_recipient_entry(self, employee_app, message_id):
        Recipient = request.env['odoo.attendance.inbox.recipient'].sudo()
        # Primary lookup: message_id (new API usage)
        rec = Recipient.search(
            [
                ('message_id', '=', message_id),
                ('employee_app_id', '=', employee_app.id),
            ],
            limit=1,
        )
        if rec:
            return rec
        # Backward-compat: some clients pass recipient_id instead of message_id
        return Recipient.search(
            [
                ('id', '=', message_id),
                ('employee_app_id', '=', employee_app.id),
            ],
            limit=1,
        )

    @http.route(
        '/api/odoo-attendance/inbox/messages',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        cors='*',
    )
    def list_messages(self, **kwargs):
        """
        List inbox messages for the authenticated mobile employee.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            employee_app, _hr_employee = auth_result

            limit = int(kwargs.get('limit') or 50)
            offset = int(kwargs.get('offset') or 0)
            limit = max(1, min(limit, 200))
            offset = max(0, offset)

            Recipient = request.env['odoo.attendance.inbox.recipient'].sudo()
            recs = Recipient.search(
                [('employee_app_id', '=', employee_app.id)],
                limit=limit,
                offset=offset,
                order='delivered_at desc, id desc',
            )

            items = []
            for rec in recs:
                msg = rec.message_id
                items.append(
                    {
                        'id': rec.id,
                        'message_id': msg.id,
                        'name': msg.name or '',
                        'body': msg.body or '',
                        'message_type': msg.message_type or 'broadcast',
                        'sent_at': self._to_utc_iso(rec.delivered_at or msg.sent_at or fields.Datetime.now()),
                        'is_read': bool(rec.is_read),
                        'read_at': self._to_utc_iso(rec.read_at),
                    }
                )

            unread_count = Recipient.search_count(
                [('employee_app_id', '=', employee_app.id), ('is_read', '=', False)]
            )

            return response_helper.success_response(
                {
                    'items': items,
                    'unread_count': unread_count,
                    'limit': limit,
                    'offset': offset,
                }
            )
        except Exception as e:
            _logger.exception(f'Error in inbox/messages: {e}')
            return response_helper.server_error_response('An error occurred')

    @http.route(
        '/api/odoo-attendance/inbox/messages/<int:message_id>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        cors='*',
    )
    def get_message_by_id(self, message_id, **kwargs):
        """
        Get a single inbox message by its original message ID.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            employee_app, _hr_employee = auth_result

            Message = request.env['odoo.attendance.inbox.message'].sudo()
            msg = Message.search([('id', '=', message_id)], limit=1)
            recipient_entry = None
            if msg:
                recipient_entry = self._get_recipient_entry(employee_app, msg.id)
            else:
                # Fallback: message_id might be a recipient id
                recipient_entry = self._get_recipient_entry(employee_app, message_id)
                if recipient_entry:
                    msg = recipient_entry.message_id

            if not msg:
                return response_helper.not_found_response('Message not found')
            if not recipient_entry:
                return response_helper.forbidden_response('You do not have access to this message.')

            return response_helper.success_response({
                'id': recipient_entry.id,
                'message_id': msg.id,
                'name': msg.name or '',
                'body': msg.body or '',
                'message_type': msg.message_type or 'broadcast',
                'sent_at': self._to_utc_iso(recipient_entry.delivered_at or msg.sent_at or fields.Datetime.now()),
                'is_read': bool(recipient_entry.is_read),
                'read_at': self._to_utc_iso(recipient_entry.read_at),
            })
        except Exception as e:
            _logger.exception(f'Error in inbox get_message_by_id: {e}')
            return response_helper.server_error_response('An error occurred')

    @http.route(
        '/api/odoo-attendance/inbox/messages/<int:recipient_id>/read',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        cors='*',
    )
    def mark_read(self, recipient_id, **kwargs):
        """
        Mark a recipient entry as read.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            employee_app, _hr_employee = auth_result

            Recipient = request.env['odoo.attendance.inbox.recipient'].sudo()
            rec = Recipient.search(
                [('id', '=', recipient_id), ('employee_app_id', '=', employee_app.id)],
                limit=1,
            )
            if not rec:
                return response_helper.not_found_response('Message not found')

            if not rec.is_read:
                rec.write({'is_read': True, 'read_at': fields.Datetime.now()})

            return response_helper.success_response({'ok': True})
        except Exception as e:
            _logger.exception(f'Error in inbox mark_read: {e}')
            return response_helper.server_error_response('An error occurred')

