from datetime import datetime
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestInboxMessageRepeatTimezone(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_attendance_app.message_timezone',
            'Africa/Cairo',
        )

    def test_repeat_time_uses_messages_timezone_for_utc_schedule(self):
        message = self.env['odoo.attendance.inbox.message'].new({
            'name': 'Check In Reminder',
            'body': 'Remember to check in',
            'send_mode': 'repeat',
            'repeat_enabled': True,
            'repeat_time': 9.0,
            'repeat_mon': True,
        })

        scheduled_at = message._get_next_repeat_datetime(
            datetime(2026, 6, 22, 0, 0, 0),
            allow_past_within_grace=False,
        )

        self.assertEqual(scheduled_at, datetime(2026, 6, 22, 6, 0, 0))
        self.assertEqual(
            message._format_with_tz(scheduled_at, 'Africa/Cairo'),
            '2026-06-22 09:00:00',
        )

    def test_recompute_keeps_future_pending_repeat_schedule(self):
        model = self.env['odoo.attendance.inbox.message'].sudo()
        scheduled_at = datetime(2026, 6, 23, 13, 0, 0)
        message = model.create({
            'name': 'Check Out Reminder',
            'body': 'Remember to check out',
            'send_mode': 'repeat',
            'repeat_enabled': True,
            'repeat_time': 16.0,
            'repeat_mon': True,
            'repeat_tue': True,
            'scheduled_at': scheduled_at,
        })

        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 6, 22, 13, 48, 0)):
            model._recompute_pending_repeat_schedules()

        self.assertEqual(message.scheduled_at, scheduled_at)

    def test_recompute_repairs_due_duplicate_pending_repeat_messages(self):
        model = self.env['odoo.attendance.inbox.message'].sudo()
        repeat_group_id = 'repeat-loop-test'
        first = model.create({
            'name': 'Check Out Reminder',
            'body': 'Remember to check out',
            'send_mode': 'repeat',
            'repeat_enabled': True,
            'repeat_group_id': repeat_group_id,
            'repeat_time': 16.0,
            'repeat_mon': True,
            'repeat_tue': True,
            'scheduled_at': datetime(2026, 6, 22, 13, 47, 0),
        })
        duplicate = model.create({
            'name': 'Check Out Reminder',
            'body': 'Remember to check out',
            'send_mode': 'repeat',
            'repeat_enabled': True,
            'repeat_group_id': repeat_group_id,
            'repeat_time': 16.0,
            'repeat_mon': True,
            'repeat_tue': True,
            'scheduled_at': datetime(2026, 6, 22, 13, 48, 0),
        })

        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 6, 22, 13, 49, 0)):
            model._recompute_pending_repeat_schedules()

        messages = first | duplicate
        active = messages.filtered(lambda msg: msg.repeat_enabled and msg.scheduled_at)
        inactive = messages - active
        self.assertEqual(len(active), 1)
        self.assertEqual(active.scheduled_at, datetime(2026, 6, 23, 13, 0, 0))
        self.assertFalse(inactive.repeat_enabled)
        self.assertFalse(inactive.scheduled_at)

    def test_cron_recompute_preserves_due_repeat_message(self):
        model = self.env['odoo.attendance.inbox.message'].sudo()
        due_at = datetime(2026, 6, 23, 5, 0, 0)
        message = model.create({
            'name': 'Check In Reminder',
            'body': 'Remember to check in',
            'send_mode': 'repeat',
            'repeat_enabled': True,
            'repeat_group_id': 'repeat-due-test',
            'repeat_time': 8.0,
            'repeat_tue': True,
            'repeat_wed': True,
            'scheduled_at': due_at,
        })

        with patch('odoo.fields.Datetime.now', return_value=datetime(2026, 6, 23, 5, 5, 0)):
            model._recompute_pending_repeat_schedules(preserve_due=True)

        self.assertEqual(message.scheduled_at, due_at)
        self.assertTrue(message.repeat_enabled)
