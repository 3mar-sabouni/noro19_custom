# -*- coding: utf-8 -*-
import logging

import psycopg2
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
import pytz

from ..utils.geofence_helper import get_geofence_locations, haversine_km

_logger = logging.getLogger(__name__)
MODULE_NAME = __name__.split(".")[2] if __name__.startswith("odoo.addons.") else "FIN_odoo_attendance_app"


def _local_xmlid(name):
    return f"{MODULE_NAME}.{name}"


class OdooAttendanceAppConfig(models.Model):
    _name = 'odoo.attendance.app.config'
    _description = 'FIN Attendance Configuration'
    _rec_name = 'name'

    name = fields.Char(default='Settings', readonly=True)
    selfie_retention_days = fields.Integer(string='Selfie Retention (days)', default=60)
    cron_interval_number = fields.Integer(string='Cleanup Interval', default=1)
    cron_interval_type = fields.Selection(
        [
            ('minutes', 'Minutes'),
            ('hours', 'Hours'),
            ('days', 'Days'),
            ('weeks', 'Weeks'),
            ('months', 'Months'),
        ],
        string='Cleanup Interval Unit',
        default='days',
        required=True,
    )

    license_server_url = fields.Char(string='License Server URL')
    license_key = fields.Char(string='License Key')
    license_grace_days = fields.Integer(string='License Grace (days)', default=7)

    fcm_server_key = fields.Char(
        string='FCM Server Key (Push - Legacy)',
        help='Deprecated: Firebase Cloud Messaging Legacy server key. Most new Firebase projects no longer support Legacy HTTP.',
    )
    fcm_project_id = fields.Char(
        string='FCM Project ID (Android/iOS Push)',
        help='Firebase/Google Cloud project_id used for FCM HTTP v1. If empty, it will be read from the service account JSON.',
    )
    fcm_service_account_json = fields.Text(
        string='FCM Service Account JSON (Android/iOS Push)',
        help='Service account JSON (Firebase Admin SDK) used for FCM HTTP v1 for both Android and iOS. Keep this secret.',
    )

    license_status = fields.Char(string='License Status', compute='_compute_license_state', store=False)
    license_valid_until = fields.Datetime(string='Valid Until', compute='_compute_license_state', store=False)
    license_last_check = fields.Datetime(string='Last Check', compute='_compute_license_state', store=False)
    license_employee_limit = fields.Integer(string='Employee Limit', compute='_compute_license_state', store=False)
    license_employee_count = fields.Integer(string='Active Employees', compute='_compute_license_state', store=False)
    license_last_error = fields.Text(string='Last License Error', compute='_compute_license_state', store=False)
    message_timezone = fields.Selection(
        [(tz, tz) for tz in pytz.common_timezones],
        string='Messages Timezone',
        help='Timezone used to compute scheduled/repeat message times.',
    )

    @api.constrains('selfie_retention_days', 'cron_interval_number')
    def _check_positive(self):
        for record in self:
            if record.selfie_retention_days < 0:
                raise ValidationError('Selfie retention days must be 0 or greater.')
            if record.cron_interval_number <= 0:
                raise ValidationError('Cleanup interval must be greater than 0.')
            if record.license_grace_days < 0:
                raise ValidationError('License grace days must be 0 or greater.')

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        icp = self.env['ir.config_parameter'].sudo()

        def _get_int(key, default):
            raw = icp.get_param(key, default=str(default))
            try:
                return int(raw)
            except Exception:
                return default

        def _get_param_multi(suffix, default=''):
            prefixes = ('odoo_attendance_app', 'FIN_odoo_attendance_app', 'fin_odoo_attendance_app')
            for prefix in prefixes:
                value = (icp.get_param(f'{prefix}.{suffix}', default='') or '').strip()
                if value:
                    return value
            return default


        result.setdefault(
            'selfie_retention_days',
            _get_int('odoo_attendance_app.selfie_retention_days', 60),
        )
        result.setdefault(
            'license_grace_days',
            _get_int('odoo_attendance_app.license_grace_days', 7),
        )
        result.setdefault(
            'license_server_url',
            (icp.get_param('odoo_attendance_app.license_server_url', default='') or '').strip(),
        )
        result.setdefault(
            'license_key',
            (icp.get_param('odoo_attendance_app.license_key', default='') or '').strip(),
        )
        result.setdefault(
            'fcm_server_key',
            _get_param_multi('fcm_server_key', default=''),
        )
        result.setdefault(
            'fcm_project_id',
            _get_param_multi('fcm_project_id', default=''),
        )
        result.setdefault(
            'fcm_service_account_json',
            _get_param_multi('fcm_service_account_json', default=''),
        )
        result.setdefault(
            'message_timezone',
            (icp.get_param('odoo_attendance_app.message_timezone', default='') or '').strip(),
        )
        cron = self.env.ref(
            _local_xmlid('ir_cron_cleanup_attendance_selfies'),
            raise_if_not_found=False,
        )
        if cron:
            result.setdefault('cron_interval_number', cron.interval_number or 1)
            result.setdefault('cron_interval_type', cron.interval_type or 'days')

        return result

    def _compute_license_state(self):
        from ..utils import license_helper

        for record in self:
            cfg = license_helper.get_license_config(record.env)
            cached = license_helper.get_cached_license_state(record.env)
            valid_until = cached.get('valid_until')
            last_check = cached.get('last_check')
            server_status = (cached.get('status') or '').strip().lower()

            record.license_valid_until = valid_until
            record.license_last_check = last_check
            record.license_employee_limit = cached.get('employee_limit') or 0
            record.license_employee_count = license_helper.get_employee_count(record.env)
            record.license_last_error = cached.get('last_error') or ''

            # Display an "effective" status consistent with enforcement:
            # - if not configured -> unconfigured
            # - if server revoked/blocked -> blocked
            # - else derive from valid_until + grace window
            if not cfg.get('license_key') or not cfg.get('license_server_url'):
                record.license_status = 'unconfigured'
                continue

            if server_status in ('revoked', 'blocked'):
                record.license_status = 'blocked'
                continue

            # If the last check failed (invalid key, server unreachable, etc), show that explicitly.
            # Otherwise the UI may still display "active" based on a previously cached valid_until.
            if server_status in ('error', 'unconfigured'):
                record.license_status = server_status
                continue

            if not valid_until:
                record.license_status = 'unknown'
                continue

            grace_days = max(int(cfg.get('grace_days') or 7), 0)
            now = license_helper._utcnow()
            grace_until = valid_until + license_helper.timedelta(days=grace_days)
            if now <= valid_until:
                record.license_status = 'active'
            elif now <= grace_until:
                record.license_status = 'grace'
            else:
                record.license_status = 'expired'

    def action_check_license_now(self):
        from ..utils import license_helper

        self.ensure_one()
        # Ensure current form values are persisted to system parameters first
        # so the license check uses the latest URL/key even if the user didn't
        # manually save before clicking the button.
        self._apply()
        ok, msg = license_helper.refresh_license_from_server(self.env)

        # Surface whether we actually received a signed token that the mobile app requires.
        cached_token = license_helper.get_cached_license_token(self.env) if ok else ''
        token_ok = bool(cached_token and not license_helper._is_license_token_expired(cached_token))
        if ok and not token_ok:
            msg = (msg or '').strip() or 'License is valid, but no signed license token was returned by the license server.'
        notification = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'License Check',
                'message': 'License is valid.' if (ok and token_ok) else (msg or 'License check failed.'),
                'sticky': False,
                'type': 'success' if (ok and token_ok) else 'warning',
                # Refresh the form so computed "Current Status" fields update immediately.
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }
        return notification

    @api.model
    def _cron_license_check(self):
        from ..utils import license_helper

        license_helper.refresh_license_from_server(self.env)
        return True
    def _timestamp_timezone_label(self):
        label = (self.message_timezone or '').strip()
        return label if label else 'UTC'

    def _format_timestamp(self, timestamp):
        if not timestamp:
            return 'Unknown'
        tz_name = self._timestamp_timezone_label()
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.UTC
        dt = timestamp
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        localized = tz.normalize(dt.astimezone(tz))
        return localized.strftime('%Y-%m-%d %H:%M:%S %Z')

    @api.model_create_multi
    def create(self, vals_list):
        if self.search_count([]) > 0:
            raise ValidationError('Only one configuration record is allowed.')
        for vals in vals_list:
            vals.setdefault('name', 'Settings')
        records = super().create(vals_list)
        records._apply()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._apply()
        return result

    def _apply(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('odoo_attendance_app.selfie_retention_days', str(self.selfie_retention_days))
        icp.set_param('odoo_attendance_app.license_server_url', (self.license_server_url or '').strip())
        icp.set_param('odoo_attendance_app.license_key', (self.license_key or '').strip())
        icp.set_param('odoo_attendance_app.license_grace_days', str(self.license_grace_days))
        icp.set_param('odoo_attendance_app.fcm_server_key', (self.fcm_server_key or '').strip())
        icp.set_param('odoo_attendance_app.fcm_project_id', (self.fcm_project_id or '').strip())
        icp.set_param('odoo_attendance_app.fcm_service_account_json', (self.fcm_service_account_json or '').strip())
        for prefix in ('FIN_odoo_attendance_app', 'fin_odoo_attendance_app'):
            icp.set_param(f'{prefix}.fcm_server_key', (self.fcm_server_key or '').strip())
            icp.set_param(f'{prefix}.fcm_project_id', (self.fcm_project_id or '').strip())
            icp.set_param(f'{prefix}.fcm_service_account_json', (self.fcm_service_account_json or '').strip())
        icp.set_param('odoo_attendance_app.message_timezone', (self.message_timezone or '').strip())
        self.env['odoo.attendance.inbox.message'].sudo()._recompute_pending_repeat_schedules()
        cron = self.env.ref(
            _local_xmlid('ir_cron_cleanup_attendance_selfies'),
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo().write(
                {
                    'interval_number': self.cron_interval_number,
                    'interval_type': self.cron_interval_type,
                    'active': True,
                }
            )

    @api.model
    def action_open_settings(self):
        """
        Open the singleton settings record (create it if missing).
        This avoids users accidentally creating a second record and hitting the constraint.
        """
        record = self.search([], order='id desc', limit=1)
        if not record:
            record = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Settings',
            'res_model': 'odoo.attendance.app.config',
            'view_mode': 'form',
            'res_id': record.id,
            'target': 'current',
            'context': {'create': False, 'delete': False},
        }
