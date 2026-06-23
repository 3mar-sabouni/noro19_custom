# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

import logging
import uuid
import re
from datetime import datetime, time, timedelta
import pytz

from ..utils import license_helper
from ..utils import push_helper

_logger = logging.getLogger(__name__)


class OdooAttendanceInboxMessage(models.Model):
    _name = 'odoo.attendance.inbox.message'
    _description = 'Attendance App Inbox Message'
    _order = 'sent_at desc, id desc'

    name = fields.Char(string='Subject', required=True)
    body = fields.Text(string='Message', required=True)

    message_type = fields.Selection(
        [
            ('broadcast', 'Broadcast'),
            ('attendance', 'Attendance'),
            ('system', 'System'),
        ],
        string='Type',
        default='broadcast',
        required=True,
    )

    target_all = fields.Boolean(
        string='Send to all active employees',
        default=True,
        help='If enabled, this message will be delivered to all active Mobile App Employees.',
    )
    recipient_mode = fields.Selection(
        [
            ('all_active', 'Send to all active employees'),
            ('selected', 'Send to selected list'),
            ('checked_in', 'Send to all at work now (checked in only)'),
        ],
        string='Recipients',
        default='all_active',
        required=True,
        index=True,
    )
    target_employee_app_ids = fields.Many2many(
        'odoo.attendance.employee',
        'odoo_attendance_inbox_msg_target_rel',
        'message_id',
        'employee_app_id',
        string='Target Employees',
        help='Used only when recipient mode is "Send to selected list".',
    )

    scheduled_at = fields.Datetime(
        string='Scheduled At',
        help='If set, the message will be delivered at this time by a cron job.',
    )
    sent_at = fields.Datetime(string='Sent At', readonly=True)
    scheduled_at_local = fields.Char(
        string='Scheduled (Messages TZ)',
        compute='_compute_local_timestamps',
        store=False,
    )
    sent_at_local = fields.Char(
        string='Sent (Messages TZ)',
        compute='_compute_local_timestamps',
        store=False,
    )

    send_mode = fields.Selection(
        [
            ('send_now', 'Send Now'),
            ('schedule', 'Schedule'),
            ('repeat', 'Repeat'),
        ],
        string='Send Mode',
        default='send_now',
        required=True,
        help='Controls whether the message is sent immediately, scheduled once, or repeated.',
    )
    source_ref = fields.Char(string='Source Reference', index=True, readonly=True, copy=False)
    repeat_enabled = fields.Boolean(
        string='Repeat Message',
        default=False,
        help='When enabled, this message will be re-scheduled automatically.',
    )
    repeat_group_id = fields.Char(string='Repeat Group', readonly=True)
    repeat_time = fields.Float(
        string='Repeat Time',
        help='Time of day (hours) for the next message, e.g. 9.5 = 09:30.',
    )
    repeat_time_hhmm = fields.Char(
        string='Repeat Time (HH:MM)',
        compute='_compute_repeat_time_hhmm',
        inverse='_inverse_repeat_time_hhmm',
        store=True,
        help='Time of day in HH:MM format (24h), e.g. 09:30.',
    )
    repeat_mon = fields.Boolean(string='Mon')
    repeat_tue = fields.Boolean(string='Tue')
    repeat_wed = fields.Boolean(string='Wed')
    repeat_thu = fields.Boolean(string='Thu')
    repeat_fri = fields.Boolean(string='Fri')
    repeat_sat = fields.Boolean(string='Sat')
    repeat_sun = fields.Boolean(string='Sun')

    recipient_ids = fields.One2many(
        'odoo.attendance.inbox.recipient',
        'message_id',
        string='Recipients',
        readonly=True,
    )
    recipient_count = fields.Integer(compute='_compute_counts', store=False)
    read_count = fields.Integer(compute='_compute_counts', store=False)
    unread_count = fields.Integer(compute='_compute_counts', store=False)

    repeat_group_count = fields.Integer(compute='_compute_repeat_group_count', store=False)

    @staticmethod
    def _has_explicit_targets(value):
        if not value:
            return False
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, int):
                    return True
                command = getattr(item, 'command', None)
                if command is not None:
                    if command == 6:
                        ids = getattr(item, 'ids', None) or []
                        if ids:
                            return True
                        continue
                    if command == 4:
                        rec_id = getattr(item, 'id', None) or getattr(item, 'record_id', None)
                        if rec_id:
                            return True
                        continue
                    if command in (3, 5):
                        continue
                    # Unknown command object in payload: treat as explicit target update.
                    return True
                if not isinstance(item, (list, tuple)) or not item:
                    # Unknown payload entry: treat as explicit target update.
                    return True
                command = item[0]
                if command == 6 and len(item) > 2 and item[2]:
                    return True
                if command == 4 and len(item) > 1 and item[1]:
                    return True
            return False
        return bool(value)

    def _compute_repeat_group_count(self):
        for record in self:
            group_id = (record.repeat_group_id or '').strip()
            if not group_id:
                record.repeat_group_count = 0
                continue
            record.repeat_group_count = self.sudo().search_count([('repeat_group_id', '=', group_id)])

    def _maybe_sync_repeat_schedule(self, *, force=False):
        for record in self:
            if not record.repeat_enabled:
                continue
            if record.repeat_time is None:
                continue
            if not record._get_repeat_days():
                continue
            if record.scheduled_at and not force:
                continue
            base_dt = record._get_repeat_seed_datetime()
            record.scheduled_at = record._get_next_repeat_datetime(base_dt, allow_past_within_grace=True)

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        schedule_sync_indexes = []
        for index, vals in enumerate(vals_list):
            vals = dict(vals or {})
            requested_mode = vals.get('recipient_mode')
            if requested_mode:
                if requested_mode == 'all_active':
                    vals['target_all'] = True
                else:
                    vals['target_all'] = False
                if requested_mode == 'checked_in':
                    vals['target_employee_app_ids'] = [(6, 0, [])]
            elif 'target_all' not in vals:
                vals['recipient_mode'] = 'all_active'
                vals['target_all'] = True
            elif vals.get('target_all') is True and not vals.get('recipient_mode'):
                vals['recipient_mode'] = 'all_active'
            elif vals.get('target_all') is False and not vals.get('recipient_mode'):
                vals['recipient_mode'] = (
                    'selected'
                    if self._has_explicit_targets(vals.get('target_employee_app_ids'))
                    else 'checked_in'
                )
            send_mode = vals.get('send_mode') or 'send_now'
            if send_mode == 'repeat':
                vals['repeat_enabled'] = True
                if not vals.get('scheduled_at'):
                    vals.pop('scheduled_at', None)
                    schedule_sync_indexes.append(index)
            elif send_mode == 'schedule':
                vals['repeat_enabled'] = False
            else:
                vals['send_mode'] = 'send_now'
                vals['repeat_enabled'] = False
                vals['scheduled_at'] = False
            normalized_vals_list.append(vals)

        records = super().create(normalized_vals_list)
        if schedule_sync_indexes:
            records_to_sync = self.browse([records.ids[index] for index in schedule_sync_indexes])
            records_to_sync._maybe_sync_repeat_schedule(force=True)
        return records

    def write(self, vals):
        vals = dict(vals or {})
        requested_mode = vals.get('recipient_mode')
        if requested_mode:
            if requested_mode == 'all_active':
                vals['target_all'] = True
            else:
                vals['target_all'] = False
            if requested_mode == 'checked_in':
                vals['target_employee_app_ids'] = [(6, 0, [])]
        elif 'target_all' in vals:
            if vals.get('target_all'):
                vals['recipient_mode'] = 'all_active'
            else:
                vals['recipient_mode'] = (
                    'selected'
                    if self._has_explicit_targets(vals.get('target_employee_app_ids'))
                    else 'checked_in'
                )
        res = super().write(vals)
        if 'send_mode' in vals:
            for record in self:
                if record.send_mode == 'repeat':
                    record.repeat_enabled = True
                    record.scheduled_at = False
                elif record.send_mode == 'schedule':
                    record.repeat_enabled = False
                    if not record.scheduled_at:
                        record.scheduled_at = fields.Datetime.now()
                else:
                    record.repeat_enabled = False
                    record.scheduled_at = False
        repeat_fields = {
            'repeat_enabled',
            'repeat_time',
            'repeat_time_hhmm',
            'repeat_mon',
            'repeat_tue',
            'repeat_wed',
            'repeat_thu',
            'repeat_fri',
            'repeat_sat',
            'repeat_sun',
        }
        if repeat_fields.intersection(vals.keys()):
            self._maybe_sync_repeat_schedule(force=True)
        return res

    @api.onchange(
        'repeat_enabled',
        'repeat_time',
        'repeat_time_hhmm',
        'repeat_mon',
        'repeat_tue',
        'repeat_wed',
        'repeat_thu',
        'repeat_fri',
        'repeat_sat',
        'repeat_sun',
    )
    def _onchange_repeat_schedule(self):
        for record in self:
            if not record.repeat_enabled:
                continue
            if record.repeat_time is None:
                continue
            if not record._get_repeat_days():
                continue
            base_dt = record._get_repeat_seed_datetime()
            record.scheduled_at = record._get_next_repeat_datetime(base_dt, allow_past_within_grace=True)

    @api.depends('recipient_ids.is_read')
    def _compute_counts(self):
        for record in self:
            recipients = record.recipient_ids
            record.recipient_count = len(recipients)
            record.read_count = len(recipients.filtered(lambda r: r.is_read))
            record.unread_count = record.recipient_count - record.read_count

    @api.constrains('recipient_mode', 'target_all', 'target_employee_app_ids')
    def _check_targets(self):
        for record in self:
            if record.recipient_mode == 'selected' and not record.target_employee_app_ids:
                raise ValidationError(_('Please select at least one target employee for "Send to selected list".'))

    @api.constrains(
        'send_mode',
        'repeat_enabled',
        'repeat_time',
        'repeat_time_hhmm',
        'repeat_mon',
        'repeat_tue',
        'repeat_wed',
        'repeat_thu',
        'repeat_fri',
        'repeat_sat',
        'repeat_sun',
    )
    def _check_repeat_config(self):
        for record in self:
            if not record.repeat_enabled:
                continue
            if record.repeat_time is None:
                raise ValidationError(_('Please set a repeat time (HH:MM).'))
            if not record._get_repeat_days():
                raise ValidationError(_('Please select at least one weekday for repetition.'))
            if record.send_mode != 'repeat':
                raise ValidationError(_('Send Mode must be "Repeat" when Repeat Message is enabled.'))

    @api.constrains('send_mode', 'scheduled_at')
    def _check_schedule_config(self):
        for record in self:
            if record.send_mode == 'schedule' and not record.scheduled_at:
                raise ValidationError(_('Please set a Scheduled At date/time.'))

    @api.onchange('send_mode')
    def _onchange_send_mode(self):
        for record in self:
            if record.send_mode == 'repeat':
                record.repeat_enabled = True
                record.scheduled_at = False
            elif record.send_mode == 'schedule':
                record.repeat_enabled = False
                if not record.scheduled_at:
                    record.scheduled_at = fields.Datetime.now()
            else:
                record.repeat_enabled = False
                record.scheduled_at = False

    @api.depends('repeat_time')
    def _compute_repeat_time_hhmm(self):
        for record in self:
            if record.repeat_time is None:
                record.repeat_time_hhmm = ''
                continue
            hours = int(record.repeat_time or 0)
            minutes = int(round(((record.repeat_time or 0) - hours) * 60))
            if minutes >= 60:
                hours += minutes // 60
                minutes = minutes % 60
            record.repeat_time_hhmm = f'{hours:02d}:{minutes:02d}'

    def _inverse_repeat_time_hhmm(self):
        for record in self:
            raw = (record.repeat_time_hhmm or '').strip()
            if not raw:
                record.repeat_time = 0.0
                continue
            if ':' not in raw:
                raise ValidationError(_('Repeat Time must be in HH:MM format.'))
            parts = raw.split(':')
            if len(parts) != 2:
                raise ValidationError(_('Repeat Time must be in HH:MM format.'))
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
            except ValueError:
                raise ValidationError(_('Repeat Time must be in HH:MM format.'))
            if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
                raise ValidationError(_('Repeat Time must be in HH:MM format (00:00-23:59).'))
            record.repeat_time = hours + (minutes / 60.0)

    def _get_repeat_days(self):
        self.ensure_one()
        days = []
        if self.repeat_mon:
            days.append(0)
        if self.repeat_tue:
            days.append(1)
        if self.repeat_wed:
            days.append(2)
        if self.repeat_thu:
            days.append(3)
        if self.repeat_fri:
            days.append(4)
        if self.repeat_sat:
            days.append(5)
        if self.repeat_sun:
            days.append(6)
        return days

    def _get_repeat_tz_name(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        cfg_tz = (icp.get_param('odoo_attendance_app.message_timezone', default='') or '').strip()
        return (cfg_tz or self.env.context.get('tz') or self.env.user.tz or self.create_uid.tz or 'UTC')

    def _get_message_tz(self):
        return self._get_repeat_tz_name()

    def _format_with_tz(self, dt, tz_name):
        if not dt:
            return ''
        tz = pytz.timezone(tz_name)
        aware = self._as_utc_aware(dt)
        local_dt = tz.normalize(aware.astimezone(tz))
        return fields.Datetime.to_string(local_dt.replace(tzinfo=None))

    def _get_repeat_clock(self):
        self.ensure_one()
        hours = int(self.repeat_time or 0)
        minutes = int(round(((self.repeat_time or 0) - hours) * 60))
        if minutes >= 60:
            hours += minutes // 60
            minutes = minutes % 60
        return hours % 24, minutes

    def _localize_repeat_datetime(self, local_date, hours, minutes, tz):
        naive_dt = datetime.combine(local_date, time(hour=hours, minute=minutes))
        try:
            return tz.localize(naive_dt, is_dst=None)
        except pytz.NonExistentTimeError:
            return tz.localize(naive_dt + timedelta(hours=1), is_dst=None)
        except pytz.AmbiguousTimeError:
            return tz.localize(naive_dt, is_dst=False)

    def _get_repeat_grace_minutes(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        raw = (icp.get_param('odoo_attendance_app.repeat_grace_minutes', default='60') or '').strip()
        try:
            minutes = int(raw)
        except Exception:
            minutes = 60
        return max(0, minutes)

    def _as_utc_aware(self, dt):
        if not dt:
            return None
        if dt.tzinfo:
            return dt.astimezone(pytz.utc)
        return pytz.utc.localize(dt)

    def _get_repeat_seed_datetime(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if not self.scheduled_at:
            return now

        message_tz_name = self._get_repeat_tz_name()
        message_tz = pytz.timezone(message_tz_name)
        now_local = self._as_utc_aware(now).astimezone(message_tz)
        scheduled_local = self._as_utc_aware(self.scheduled_at).astimezone(message_tz)
        scheduled_day_start = scheduled_local.replace(hour=0, minute=0, second=0, microsecond=0)
        seed_local = scheduled_day_start if scheduled_day_start > now_local else now_local
        return seed_local.astimezone(pytz.utc).replace(tzinfo=None)

    def _get_next_repeat_datetime(self, base_dt, *, allow_past_within_grace: bool = True):
        self.ensure_one()
        if not base_dt:
            base_dt = fields.Datetime.now()

        message_tz_name = self._get_repeat_tz_name()
        message_tz = pytz.timezone(message_tz_name)
        base_dt_local = self._as_utc_aware(base_dt).astimezone(message_tz)
        grace_minutes = self._get_repeat_grace_minutes()
        grace = timedelta(minutes=grace_minutes) if grace_minutes else timedelta(0)

        repeat_days = self._get_repeat_days()
        if not repeat_days:
            return False

        hours, minutes = self._get_repeat_clock()

        for add_days in range(0, 14):
            candidate_local = base_dt_local + timedelta(days=add_days)
            if candidate_local.weekday() not in repeat_days:
                continue
            candidate_local_dt = self._localize_repeat_datetime(
                candidate_local.date(),
                hours,
                minutes,
                message_tz,
            )
            if candidate_local_dt > base_dt_local:
                return candidate_local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            if (
                allow_past_within_grace
                and add_days == 0
                and grace
                and candidate_local_dt <= base_dt_local
                and (base_dt_local - candidate_local_dt) <= grace
            ):
                # If the scheduled time just passed (within grace), treat it as due now.
                # We return "now" (not the past scheduled time) so it won't keep re-triggering.
                return base_dt_local.astimezone(pytz.utc).replace(tzinfo=None)
        return False

    @api.model
    def _recompute_pending_repeat_schedules(self, preserve_due=False):
        pending_messages = self.sudo().search(
            [
                ('send_mode', '=', 'repeat'),
                ('repeat_enabled', '=', True),
                ('sent_at', '=', False),
            ],
            order='repeat_group_id asc, scheduled_at asc, id asc',
        )
        pending_by_group = {}
        for message in pending_messages:
            group_key = message.repeat_group_id or f'message:{message.id}'
            pending_by_group.setdefault(group_key, []).append(message.id)

        now = fields.Datetime.now()
        for message_ids in pending_by_group.values():
            group_messages = self.sudo().browse(message_ids).exists()
            if not group_messages:
                continue
            due_messages = group_messages.filtered(lambda message: message.scheduled_at and message.scheduled_at <= now)
            if preserve_due and due_messages:
                message = due_messages[:1]
                duplicates = group_messages - message
                if duplicates:
                    duplicates.sudo().write({'repeat_enabled': False, 'scheduled_at': False})
                continue
            message = group_messages[0]
            if message.repeat_time is None or not message._get_repeat_days():
                continue
            next_dt = message._get_next_repeat_datetime(now, allow_past_within_grace=False)
            if next_dt and message.scheduled_at != next_dt:
                message.sudo().write({'scheduled_at': next_dt})
            duplicates = group_messages - message
            if duplicates:
                duplicates.sudo().write({'repeat_enabled': False, 'scheduled_at': False})

    @api.depends('scheduled_at', 'sent_at')
    def _compute_local_timestamps(self):
        for rec in self:
            tz_name = rec._get_message_tz()
            rec.scheduled_at_local = rec._format_with_tz(rec.scheduled_at, tz_name)
            rec.sent_at_local = rec._format_with_tz(rec.sent_at, tz_name)

    def _ensure_repeat_group(self):
        if not self.repeat_group_id and self.repeat_enabled:
            self.repeat_group_id = uuid.uuid4().hex

    def _schedule_next_repeat_message(self, next_dt):
        self.ensure_one()
        if not self.repeat_enabled or not next_dt:
            return False

        self._ensure_repeat_group()
        pending_messages = self.sudo().search(
            [
                ('id', '!=', self.id),
                ('repeat_group_id', '=', self.repeat_group_id),
                ('repeat_enabled', '=', True),
                ('sent_at', '=', False),
            ],
            order='scheduled_at asc, id asc',
        )
        pending = pending_messages[:1]
        duplicates = pending_messages - pending
        if duplicates:
            duplicates.sudo().write({'repeat_enabled': False, 'scheduled_at': False})
        if pending:
            if pending.scheduled_at != next_dt:
                pending.sudo().write({'scheduled_at': next_dt})
            return pending

        return self.sudo().copy(
            {
                'sent_at': False,
                'scheduled_at': next_dt,
                'repeat_group_id': self.repeat_group_id,
            }
        )

    def _get_target_employees(self):
        self.ensure_one()
        EmployeeApp = self.env['odoo.attendance.employee'].sudo()
        mode = self.recipient_mode or ('all_active' if self.target_all else 'selected')
        if mode == 'all_active':
            return EmployeeApp.search([('is_active', '=', True)])
        if mode == 'checked_in':
            Attendance = self.env['hr.attendance'].sudo()
            checked_in_hr_employee_ids = Attendance.search([('check_out', '=', False)]).mapped('employee_id').ids
            if not checked_in_hr_employee_ids:
                return EmployeeApp.browse()
            return EmployeeApp.search([
                ('is_active', '=', True),
                ('employee_id', 'in', checked_in_hr_employee_ids),
            ])
        return self.target_employee_app_ids.sudo().filtered(lambda e: e.is_active)

    def _deliver_to_targets(self, raise_on_block=False):
        self.ensure_one()
        if self.sent_at:
            return

        ok, msg = license_helper.is_subscription_active(self.env, allow_refresh=True)
        if not ok:
            # Fail closed: do not deliver when the subscription is invalid/expired.
            _logger.warning('Message delivery blocked by subscription check (message_id=%s): %s', self.id, msg)
            if raise_on_block:
                raise ValidationError(msg or _('Subscription is not active.'))
            return

        targets = self._get_target_employees()
        if not targets:
            if raise_on_block:
                if self.recipient_mode == 'checked_in':
                    raise ValidationError(_('No employees are currently checked in.'))
                if self.recipient_mode == 'selected':
                    raise ValidationError(_('No active employees found in the selected list.'))
                raise ValidationError(_('No active employees found to receive this message.'))
            return
        Recipient = self.env['odoo.attendance.inbox.recipient'].sudo()
        now = fields.Datetime.now()

        to_create = [
            {
                'message_id': self.id,
                'employee_app_id': emp.id,
                'delivered_at': now,
            }
            for emp in targets
        ]
        if to_create:
            Recipient.create(to_create)

        # Send Android push notifications (best-effort).
        # Push is optional and requires a configured FCM server key.
        try:
            from ..utils import push_helper

            title = self.name or 'Message'
            body = (self.body or '').strip()
            push_body = body

            if self.message_type == 'attendance':
                lines = [l for l in body.splitlines() if l.strip()]
                # Drop any map URL line from the push body to avoid truncated links.
                filtered = [l for l in lines if not l.lower().startswith('map:')]
                push_body = '\n'.join(filtered).strip() or body

            if len(push_body) > 140:
                push_body = push_body[:137] + '...'

            # Match each employee to their recipient record id for identification in the app.
            all_recipients = Recipient.search([('message_id', '=', self.id), ('employee_app_id', 'in', targets.ids)])
            emp_to_rec_id = {r.employee_app_id.id: r.id for r in all_recipients}

            ok_count = 0
            fail_count = 0
            Session = self.env['odoo.attendance.session'].sudo()
            valid_sessions = Session.search([
                ('employee_app_id', 'in', targets.ids),
                ('is_revoked', '=', False),
                ('fcm_token', '!=', False),
            ])
            sent_keys = set()
            for session in valid_sessions:
                emp = session.employee_app_id
                token = (session.fcm_token or '').strip()
                if not emp or not token:
                    continue
                key = (emp.id, token)
                if key in sent_keys:
                    continue
                sent_keys.add(key)

                rec_id = emp_to_rec_id.get(emp.id, self.id)
                ok, msg = push_helper.send_fcm_push(
                    env=self.env,
                    token=token,
                    title=title,
                    body=push_body,
                    silent=False,
                    data={
                        'kind': 'inbox',
                        'messageId': str(rec_id),
                        'messageType': (self.message_type or ''),
                        'title': title,
                        'body': push_body,
                    },
                )
                if ok:
                    ok_count += 1
                else:
                    fail_count += 1
                    _logger.info(
                        'FCM push failed (employee_app_id=%s, session_id=%s, message_id=%s, rec_id=%s): %s',
                        emp.id,
                        session.id,
                        self.id,
                        rec_id,
                        msg,
                    )

            # Fallback to employee-level token when no active session token was available/sent.
            for emp in targets:
                token = (emp.fcm_token or '').strip()
                if not token:
                    continue
                key = (emp.id, token)
                if key in sent_keys:
                    continue
                sent_keys.add(key)

                rec_id = emp_to_rec_id.get(emp.id, self.id)
                ok, msg = push_helper.send_fcm_push(
                    env=self.env,
                    token=token,
                    title=title,
                    body=push_body,
                    silent=False,
                    data={
                        'kind': 'inbox',
                        'messageId': str(rec_id),
                        'messageType': (self.message_type or ''),
                        'title': title,
                        'body': push_body,
                    },
                )
                if ok:
                    ok_count += 1
                else:
                    fail_count += 1
                    _logger.info(
                        'FCM push failed via employee token (employee_app_id=%s, message_id=%s, rec_id=%s): %s',
                        emp.id,
                        self.id,
                        rec_id,
                        msg,
                    )

            if ok_count or fail_count:
                _logger.info(
                    'FCM push summary (message_id=%s): ok=%s failed=%s',
                    self.id,
                    ok_count,
                    fail_count,
                )
        except Exception:
            _logger.exception('FCM push send failed unexpectedly (message_id=%s)', self.id)

        self.sudo().write({'sent_at': now})

        if self.repeat_enabled:
            next_dt = self._get_next_repeat_datetime(now, allow_past_within_grace=False)
            if next_dt:
                self._schedule_next_repeat_message(next_dt)
    def action_send_now(self):
        has_fcm_json = bool((push_helper._get_fcm_service_account_json(self.env) or '').strip())
        has_legacy_key = bool((push_helper.get_fcm_server_key(self.env) or '').strip())
        if not (has_fcm_json or has_legacy_key):
            raise ValidationError(
                _(
                    'Push notifications are not configured. '
                    'Please set "FCM Service Account JSON" in Attendance App Settings.'
                )
            )
        for record in self:
            record._deliver_to_targets(raise_on_block=True)
        return True

    def action_open_repeat_group(self):
        self.ensure_one()
        group_id = (self.repeat_group_id or '').strip()
        if not group_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Repeat Messages'),
            'res_model': 'odoo.attendance.inbox.message',
            'view_mode': 'list,form',
            'domain': [('repeat_group_id', '=', group_id)],
            'context': {'search_default_group_by_sent_at': 1},
        }

    def action_stop_repeat(self):
        for record in self:
            if record.repeat_group_id:
                self.search([('repeat_group_id', '=', record.repeat_group_id)]).write(
                    {'repeat_enabled': False}
                )
            else:
                record.repeat_enabled = False
        return True

    @api.model
    def _cron_send_scheduled_messages(self):
        ok, msg = license_helper.is_subscription_active(self.env, allow_refresh=True)
        if not ok:
            _logger.warning('Scheduled message cron blocked by subscription check: %s', msg)
            return True

        self._recompute_pending_repeat_schedules(preserve_due=True)
        now = fields.Datetime.now()
        msgs = self.sudo().search(
            [
                ('sent_at', '=', False),
                ('scheduled_at', '!=', False),
                ('scheduled_at', '<=', now),
            ],
            limit=200,
            order='scheduled_at asc',
        )
        processed_repeat_groups = set()
        for msg in msgs:
            if msg.send_mode == 'repeat' and msg.repeat_group_id:
                if msg.repeat_group_id in processed_repeat_groups:
                    continue
                processed_repeat_groups.add(msg.repeat_group_id)
                duplicate_due = self.sudo().search(
                    [
                        ('id', '!=', msg.id),
                        ('repeat_group_id', '=', msg.repeat_group_id),
                        ('repeat_enabled', '=', True),
                        ('sent_at', '=', False),
                        ('scheduled_at', '!=', False),
                        ('scheduled_at', '<=', now),
                    ]
                )
                if duplicate_due:
                    next_dt = msg._get_next_repeat_datetime(now, allow_past_within_grace=False)
                    if next_dt:
                        duplicate_due.sudo().write({'scheduled_at': next_dt})
            # Avoid sending a large backlog of repeat messages if a bad schedule pushed many records into the past.
            if msg.send_mode == 'repeat' and msg.repeat_group_id and msg.scheduled_at:
                try:
                    grace_minutes = msg._get_repeat_grace_minutes()
                except Exception:
                    grace_minutes = 60
                grace = timedelta(minutes=int(grace_minutes or 0))
                if grace and (now - msg.scheduled_at) > grace:
                    msg._ensure_repeat_group()
                    next_dt = msg._get_next_repeat_datetime(now, allow_past_within_grace=False)
                    if next_dt:
                        _logger.warning(
                            'Skipping stale repeat message (message_id=%s, group=%s, scheduled_at=%s). Rescheduled to %s.',
                            msg.id,
                            msg.repeat_group_id,
                            msg.scheduled_at,
                            next_dt,
                        )
                        msg.sudo().write({'scheduled_at': next_dt})
                        continue
            msg._deliver_to_targets()
        return True


class OdooAttendanceInboxRecipient(models.Model):
    _name = 'odoo.attendance.inbox.recipient'
    _description = 'Attendance App Inbox Recipient'
    _order = 'delivered_at desc, id desc'

    message_id = fields.Many2one(
        'odoo.attendance.inbox.message',
        string='Message',
        required=True,
        ondelete='cascade',
        index=True,
    )
    employee_app_id = fields.Many2one(
        'odoo.attendance.employee',
        string='Mobile App Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )

    delivered_at = fields.Datetime(string='Delivered At', readonly=True)
    is_read = fields.Boolean(string='Read', default=False, index=True)
    read_at = fields.Datetime(string='Read At', readonly=True)


    def action_mark_read(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.is_read:
                rec.sudo().write({'is_read': True, 'read_at': now})
        return True
