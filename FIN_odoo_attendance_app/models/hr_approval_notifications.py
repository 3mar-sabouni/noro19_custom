# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


def _is_approved_state(state, approved_states):
    return bool(state and state in approved_states)


def _skip_leave_approval_notification(env):
    return bool(env.context.get('fin_skip_leave_approval_notify'))


def _notify_mobile_employee(env, hr_employee, title, body, *, source='unknown'):
    if not hr_employee:
        _logger.info('Approval notify skipped: missing employee (source=%s)', source)
        return False

    employee_apps = env['odoo.attendance.employee'].sudo().search([
        ('employee_id', '=', hr_employee.id),
        ('is_active', '=', True),
    ])
    if not employee_apps:
        _logger.info(
            'Approval notify skipped: no active mobile app user for employee_id=%s (source=%s)',
            hr_employee.id,
            source,
        )
        return False

    message = env['odoo.attendance.inbox.message'].sudo().create({
        'name': title,
        'body': body,
        'message_type': 'system',
        'target_all': False,
        'target_employee_app_ids': [(6, 0, employee_apps.ids)],
    })
    message.action_send_now()
    return True


def _fmt_date(value):
    if not value:
        return '-'
    try:
        return fields.Date.to_string(value)
    except Exception:
        return str(value)


class HrLeave(models.Model):
    _inherit = 'hr.leave'
    _description = 'HR Leave (FIN Approval Notifications)'

    _approved_states = {'validate'}

    def _notify_leave_approved(self, old_states):
        if _skip_leave_approval_notification(self.env):
            _logger.info('Leave approval notify skipped by context flag (fin_skip_leave_approval_notify)')
            return
        for rec in self:
            old_state = old_states.get(rec.id)
            if _is_approved_state(old_state, self._approved_states):
                continue
            if not _is_approved_state(rec.state, self._approved_states):
                continue
            try:
                leave_type = rec.holiday_status_id.display_name or rec.holiday_status_id.name or _('Time Off')
                date_from = _fmt_date(rec.request_date_from)
                date_to = _fmt_date(rec.request_date_to)
                title = _('Time Off Approved')
                body = _(
                    'Your time off request "%(leave_type)s" (%(date_from)s - %(date_to)s) has been approved.'
                ) % {
                    'leave_type': leave_type,
                    'date_from': date_from,
                    'date_to': date_to,
                }
                sent = _notify_mobile_employee(self.env, rec.employee_id, title, body, source='hr.leave')
                _logger.info(
                    'Leave approval notify result: sent=%s leave_id=%s employee_id=%s old=%s new=%s',
                    bool(sent), rec.id, rec.employee_id.id if rec.employee_id else None, old_state, rec.state,
                )
            except Exception:
                _logger.exception('Failed leave approval notification (leave_id=%s)', rec.id)

    def action_approve(self, *args, **kwargs):
        old_states = {rec.id: rec.state for rec in self}
        res = super(HrLeave, self.with_context(fin_approval_notify_from_action=True)).action_approve(*args, **kwargs)
        self._notify_leave_approved(old_states)
        return res

    def action_validate(self, *args, **kwargs):
        old_states = {rec.id: rec.state for rec in self}
        res = super(HrLeave, self.with_context(fin_approval_notify_from_action=True)).action_validate(*args, **kwargs)
        self._notify_leave_approved(old_states)
        return res

    def write(self, vals):
        old_states = {rec.id: rec.state for rec in self} if 'state' in vals else {}
        res = super().write(vals)
        if old_states and not self.env.context.get('fin_approval_notify_from_action'):
            self._notify_leave_approved(old_states)
        return res


class HrExpense(models.Model):
    _inherit = 'hr.expense'
    _description = 'HR Expense (FIN Approval Notifications)'

    _approved_states = {'approved', 'done'}

    def _notify_expense_approved(self, old_states):
        for rec in self:
            old_state = old_states.get(rec.id)
            if _is_approved_state(old_state, self._approved_states):
                continue
            if not _is_approved_state(rec.state, self._approved_states):
                continue
            if getattr(rec, 'sheet_id', False):
                continue
            try:
                amount = rec.total_amount if hasattr(rec, 'total_amount') else (rec.unit_amount or 0.0)
                currency = rec.currency_id.symbol if getattr(rec, 'currency_id', False) else ''
                expense_name = rec.name or rec.display_name or _('Expense')
                title = _('Expense Approved')
                body = _(
                    'Your expense "%(name)s" has been approved (%(amount).2f %(currency)s).'
                ) % {
                    'name': expense_name,
                    'amount': amount or 0.0,
                    'currency': currency or '',
                }
                sent = _notify_mobile_employee(self.env, rec.employee_id, title, body, source='hr.expense')
                _logger.info(
                    'Expense approval notify result: sent=%s expense_id=%s employee_id=%s old=%s new=%s',
                    bool(sent), rec.id, rec.employee_id.id if rec.employee_id else None, old_state, rec.state,
                )
            except Exception:
                _logger.exception('Failed expense approval notification (expense_id=%s)', rec.id)

    def write(self, vals):
        old_states = {rec.id: rec.state for rec in self} if 'state' in vals else {}
        res = super().write(vals)
        if old_states:
            self._notify_expense_approved(old_states)
        return res

