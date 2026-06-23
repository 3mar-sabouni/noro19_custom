# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta


class OdooAttendanceSession(models.Model):
    """
    Stores JWT refresh tokens for mobile app authentication.
    Each session is tied to a specific employee and device.
    """
    _name = 'odoo.attendance.session'
    _description = 'FIN Attendance Session'
    _order = 'created_at desc'
    
    employee_app_id = fields.Many2one(
        'odoo.attendance.employee',
        string='App Employee',
        required=True,
        ondelete='cascade',
        index=True
    )
    refresh_token_hash = fields.Char(
        string='Refresh Token Hash',
        required=True,
        help='SHA256 hash of refresh token'
    )
    device_id = fields.Char(
        string='Device ID',
        required=True,
        index=True
    )
    expires_at = fields.Datetime(
        string='Expires At',
        required=True,
        index=True
    )
    fcm_token = fields.Char(
        string='FCM Token',
        help='Push token bound to this authenticated device session.',
    )
    fcm_token_updated_at = fields.Datetime(
        string='FCM Token Updated At',
        readonly=True,
    )
    created_at = fields.Datetime(
        string='Created At',
        default=fields.Datetime.now,
        readonly=True
    )
    is_revoked = fields.Boolean(
        string='Revoked',
        default=False,
        help='If true, this session is invalidated'
    )
    
    _unique_employee_device = models.Constraint(
        'UNIQUE(employee_app_id, device_id)',
        'Only one active session per employee per device is allowed.',
    )
    
    @api.model
    def cleanup_expired_sessions(self):
        """
        Cron job to delete expired sessions.
        Should be scheduled to run daily.
        """
        expired_sessions = self.search([
            ('expires_at', '<', fields.Datetime.now())
        ])
        count = len(expired_sessions)
        expired_sessions.unlink()
        return count
    
    def is_valid(self):
        """Check if session is valid (not expired and not revoked)"""
        self.ensure_one()
        if self.is_revoked:
            return False
        if self.expires_at < fields.Datetime.now():
            return False
        return True
    
    def revoke(self):
        """Revoke this session (logout)"""
        self.write({'is_revoked': True})
