# -*- coding: utf-8 -*-
import json
import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from ..utils.password_helper import hash_password
from ..utils import license_helper

_logger = logging.getLogger(__name__)


class OdooAttendanceEmployee(models.Model):
    """
    Stores employee credentials for mobile app authentication.
    Each employee has app-specific username/password separate from Odoo users.
    Implements strict device binding (one device per employee and one active employee per device).
    """
    _name = 'odoo.attendance.employee'
    _description = 'FIN Attendance Employee'
    _rec_name = 'username'
    
    username = fields.Char(
        string='FIN Attendance Username',
        required=True,
        index=True,
        help='Unique username for mobile app login'
    )
    password_hash = fields.Char(
        string='Password Hash',
        required=True,
        help='bcrypt hashed password (never store plain text)'
    )
    password = fields.Char(
        string='Set Password',
        store=False,
        help='Enter a new password to update the hash'
    )
    
    @api.model_create_multi
    def create(self, vals_list):
        # Enforce subscription employee limit on creation (active employees only)
        active_new = sum(1 for vals in vals_list if vals.get('is_active', True))
        if active_new:
            ok, msg = license_helper.is_subscription_active(self.env, allow_refresh=True)
            if not ok:
                raise ValidationError(_(msg))

            cached = license_helper.get_cached_license_state(self.env)
            limit = cached.get('employee_limit') or 0
            if limit > 0:
                current = license_helper.get_employee_count(self.env)
                if current + active_new > limit:
                    raise ValidationError(
                        _(
                            'Your subscription includes %s employees and you have reached the maximum. '
                            'Please upgrade your subscription to add more employees.'
                        )
                        % limit
                    )

        # Hash passwords when provided
        for vals in vals_list:
            if 'device_id' in vals:
                vals['device_id'] = self._normalize_device_id(vals.get('device_id'))
            if vals.get('password'):
                vals['password_hash'] = hash_password(vals['password'])
            if 'password_hash' not in vals and not vals.get('password'):
                # Fallback or error could be raised here, but we'll let Odoo required=True handle missing field if neither exist
                pass

        return super(OdooAttendanceEmployee, self).create(vals_list)

    def write(self, vals):
        # Enforce subscription employee limit when activating an employee
        if vals.get('is_active') is True:
            ok, msg = license_helper.is_subscription_active(self.env, allow_refresh=True)
            if not ok:
                raise ValidationError(_(msg))

            cached = license_helper.get_cached_license_state(self.env)
            limit = cached.get('employee_limit') or 0
            if limit > 0:
                # Count currently active excluding records being written if currently inactive
                current = license_helper.get_employee_count(self.env)
                activating = len(self.filtered(lambda r: not r.is_active))
                if current + activating > limit:
                    raise ValidationError(
                        _(
                            'Your subscription includes %s employees and you have reached the maximum. '
                            'Please upgrade your subscription to add more employees.'
                        )
                        % limit
                    )

        if vals.get('password'):
            vals['password_hash'] = hash_password(vals['password'])
        if 'device_id' in vals:
            vals['device_id'] = self._normalize_device_id(vals.get('device_id'))
        return super(OdooAttendanceEmployee, self).write(vals)
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
        help='Link to HR Employee record'
    )
    manager_employee_ids = fields.Many2many(
        'hr.employee',
        'odoo_attendance_employee_manager_rel',
        'employee_app_id',
        'manager_id',
        string='Manager',
        help='Managers who should receive check-in/out notifications for this employee.',
    )
    selfie_policy_checkin = fields.Selection(
        [
            ('optional', 'Optional'),
            ('required', 'Required'),
        ],
        string='Check-in Selfie',
        default='optional',
        required=True,
        help='Whether a selfie is required when checking in from the mobile app.',
    )
    selfie_policy_checkout = fields.Selection(
        [
            ('optional', 'Optional'),
            ('required', 'Required'),
        ],
        string='Check-out Selfie',
        default='optional',
        required=True,
        help='Whether a selfie is required when checking out from the mobile app.',
    )
    geofence_policy = fields.Selection(
        [
            ('optional', 'Optional'),
            ('required', 'Required'),
        ],
        string='Geofence',
        default='required',
        required=True,
        help='Whether geofence validation is required for this employee.',
    )
    geofence_location_ids = fields.One2many(
        'odoo.attendance.employee.location',
        'employee_app_id',
        string='Geofence Locations',
    )
    can_check_attendance_for_others = fields.Boolean(
        string='Can check in/out for other users',
        default=False,
        help='If enabled, this user can perform attendance actions for selected users.',
    )
    allowed_attendance_user_ids = fields.Many2many(
        'odoo.attendance.employee',
        'odoo_attendance_employee_allowed_user_rel',
        'employee_app_id',
        'allowed_user_id',
        string='Users allowed for check-in/out',
        help='Exact users this account is allowed to check in/out for.',
    )
    device_id = fields.Char(
        string='Device ID',
        index=True,
        help='Platform-specific device identifier for binding'
    )
    fcm_token = fields.Char(
        string='FCM Token',
        index=True,
        help='Firebase Cloud Messaging token (Android/iOS) used for push notifications.',
    )
    fcm_token_updated_at = fields.Datetime(
        string='FCM Token Updated At',
        readonly=True,
    )
    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, employee cannot login to mobile app'
    )
    is_driver = fields.Boolean(
        string='Is Driver',
        default=False,
        help='If enabled, the mobile app will require km / mi / hr and vehicle details.',
    )
    last_login = fields.Datetime(
        string='Last Login',
        readonly=True
    )
    
    # Relational fields
    session_ids = fields.One2many(
        'odoo.attendance.session',
        'employee_app_id',
        string='Sessions'
    )
    
    _unique_username = models.Constraint(
        'UNIQUE(username)',
        'Username must be unique! This username is already taken.',
    )
    _unique_employee = models.Constraint(
        'UNIQUE(employee_id)',
        'An app user already exists for this employee!',
    )

    @api.model
    def _normalize_device_id(self, device_id):
        return (device_id or '').strip()

    def _find_conflicting_device_owner(self, device_id):
        normalized_device_id = self._normalize_device_id(device_id)
        if not normalized_device_id:
            return self.browse()
        return self.sudo().search(
            [
                ('id', 'not in', self.ids),
                ('is_active', '=', True),
                ('device_id', '=', normalized_device_id),
            ],
            limit=1,
        )
    
    @api.constrains('username')
    def _check_username(self):
        """Validate username format"""
        for record in self:
            if record.username:
                if len(record.username) < 3:
                    raise ValidationError(_('Username must be at least 3 characters long.'))
                if not record.username.replace('.', '').replace('_', '').replace('-', '').isalnum():
                    raise ValidationError(_('Username can only contain letters, numbers, dots, underscores, and hyphens.'))

    @api.constrains('device_id', 'is_active')
    def _check_unique_active_device_binding(self):
        for record in self:
            normalized_device_id = record._normalize_device_id(record.device_id)
            if not record.is_active or not normalized_device_id:
                continue
            conflict = record._find_conflicting_device_owner(normalized_device_id)
            if conflict:
                raise ValidationError(
                    _(
                        'This device is already linked to another active employee account (%s). '
                        'Reset device binding for that account first.'
                    )
                    % (conflict.username or conflict.employee_id.name or conflict.id)
                )

    @api.constrains('allowed_attendance_user_ids')
    def _check_attendance_delegate_config(self):
        for record in self:
            if record.id in record.allowed_attendance_user_ids.ids:
                raise ValidationError(_('You cannot add the same user in allowed users list.'))

    def can_manage_attendance_employee(self, target_employee):
        self.ensure_one()
        if not target_employee:
            return False
        if target_employee.id == self.employee_id.id:
            return True
        if not self.can_check_attendance_for_others:
            return False
        allowed_employee_ids = set(self.allowed_attendance_user_ids.mapped('employee_id').ids)
        return target_employee.id in allowed_employee_ids

    
    def update_last_login(self):
        """Update last login timestamp"""
        self.ensure_one()
        self.write({'last_login': fields.Datetime.now()})
    
    def bind_device(self, device_id):
        """Bind employee to a device"""
        self.ensure_one()
        normalized_device_id = self._normalize_device_id(device_id)
        if not normalized_device_id:
            raise ValidationError(_('Invalid device identifier.'))
        conflict = self._find_conflicting_device_owner(normalized_device_id)
        if conflict:
            raise ValidationError(
                _(
                    'This device is already linked to another active employee account (%s). '
                    'Reset device binding for that account first.'
                )
                % (conflict.username or conflict.employee_id.name or conflict.id)
            )
        if self.device_id and self.device_id != normalized_device_id:
            raise ValidationError(_(
                'This employee is already bound to another device. '
                'Contact administrator to reset device binding.'
            ))
        self.write({'device_id': normalized_device_id})
    
    def reset_device_binding(self):
        """Admin function to reset device binding"""
        self.write({'device_id': False})
        # Also invalidate all sessions
        self.session_ids.sudo().unlink()
        return True

    @api.model
    def action_reset_all_device_bindings(self):
        """Reset all employee device bindings and invalidate every mobile session."""
        employee_model = self.env['odoo.attendance.employee'].sudo()
        session_model = self.env['odoo.attendance.session'].sudo()

        bound_employees = employee_model.search([('device_id', '!=', False)])
        reset_count = len(bound_employees)
        session_count = session_model.search_count([])

        if reset_count:
            bound_employees.write({'device_id': False})
        if session_count:
            session_model.search([]).unlink()

        return {
            'reset_count': reset_count,
            'session_count': session_count,
        }
    
    def verify_device(self, device_id):
        """Check if device is authorized for this employee"""
        self.ensure_one()
        normalized_device_id = self._normalize_device_id(device_id)
        if not normalized_device_id:
            return False
        conflict = self._find_conflicting_device_owner(normalized_device_id)
        if conflict:
            return False
        if not self.device_id:
            # First login - no device bound yet
            return True
        return self.device_id == normalized_device_id










