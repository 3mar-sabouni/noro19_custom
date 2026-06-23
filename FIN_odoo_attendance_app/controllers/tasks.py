# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, time, timedelta
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import ValidationError
from .employee import authenticate_request
from .subscription import require_active_subscription
from ..utils import response_helper

_logger = logging.getLogger(__name__)


def _parse_date(raw, label):
    if raw in (None, ''):
        return None
    try:
        return fields.Date.to_date(raw)
    except Exception:
        raise ValidationError(f'{label} is invalid.')


def _parse_task_datetime(raw, label):
    if raw in (None, ''):
        return None
    try:
        value = fields.Datetime.to_datetime(raw)
        if value:
            return value
    except Exception:
        pass
    try:
        return datetime.combine(fields.Date.to_date(raw), time.min)
    except Exception:
        raise ValidationError(f'{label} is invalid.')


def _date_to_day_start(value):
    if value in (None, ''):
        return None
    return datetime.combine(value, time.min)


def _date_to_day_end(value):
    if value in (None, ''):
        return None
    return datetime.combine(value, time(23, 59, 59))


def _parse_int(raw, label):
    if raw in (None, ''):
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        raise ValidationError(f'{label} is invalid.')

def _parse_int_list(raw, label):
    if raw in (None, ''):
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = [raw]
    expanded = []
    for item in items:
        if item in (None, ''):
            continue
        if isinstance(item, str):
            normalized = item.replace(';', ',')
            expanded.extend([part.strip() for part in normalized.split(',') if part.strip()])
        else:
            expanded.append(item)
    result = []
    for item in expanded:
        if item in (None, ''):
            continue
        try:
            result.append(int(str(item).strip()))
        except Exception:
            raise ValidationError(f'{label} is invalid.')
    # Keep stable ordering while deduplicating.
    return list(dict.fromkeys(result))


def _parse_choice_list(raw, label, allowed):
    if raw in (None, ''):
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = [raw]
    expanded = []
    for item in items:
        if item in (None, ''):
            continue
        if isinstance(item, str):
            normalized = item.replace(';', ',')
            expanded.extend([part.strip() for part in normalized.split(',') if part.strip()])
        else:
            expanded.append(str(item).strip())

    allowed_set = set(allowed)
    result = []
    for item in expanded:
        value = str(item).strip()
        if not value:
            continue
        if value not in allowed_set:
            raise ValidationError(f'{label} is invalid.')
        result.append(value)
    # Keep stable ordering while deduplicating.
    return list(dict.fromkeys(result))


def _parse_float(raw, label):
    if raw in (None, ''):
        return None
    try:
        return float(str(raw).strip())
    except Exception:
        raise ValidationError(f'{label} must be a number.')


def _parse_priority(raw):
    """
    Normalize priority from mobile/web payloads to task model values.
    Accepted:
    - int/number: 0=low, 1=medium, 2=high, 3=high (mobile "Very High" fallback)
    - string: low/medium/high, very_high/very high (mapped to high), 0..3
    """
    if raw in (None, ''):
        return False
    if isinstance(raw, bool):
        raise ValidationError('Invalid priority value.')
    if isinstance(raw, (int, float)):
        idx = int(raw)
        if idx <= 0:
            return 'low'
        if idx == 1:
            return 'medium'
        return 'high'

    value = str(raw).strip().lower()
    if not value:
        return False
    if value in ('low', 'medium', 'high'):
        return value
    if value in ('very_high', 'very high'):
        return 'high'
    if value in ('0', '1', '2', '3'):
        return _parse_priority(int(value))
    raise ValidationError('Invalid priority value.')


def _build_analytic_access_domain(hr_employee):
    return [
        ('active', '=', True),
    ]


def _is_task_project_required(env):
    raw_value = env['ir.config_parameter'].sudo().get_param(
        'odoo_attendance_app.task_project_required',
        None,
    )
    if raw_value not in (None, ''):
        return str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
    config = env['odoo.attendance.app.config'].sudo().search([], order='id desc', limit=1)
    if config and 'task_project_required' in config._fields:
        return bool(config.task_project_required)
    return True


def _normalize_task_attachments(data):
    raw_attachments = data.get('attachments')
    attachments = []

    if raw_attachments not in (None, ''):
        if isinstance(raw_attachments, dict):
            raw_attachments = [raw_attachments]
        if not isinstance(raw_attachments, (list, tuple)):
            raise ValidationError('attachments must be a list.')

        for item in raw_attachments:
            if not isinstance(item, dict):
                raise ValidationError('attachments must contain objects.')

            attachment_base64 = (item.get('base64') or '').strip()
            if not attachment_base64:
                continue

            attachment_name = (item.get('name') or '').strip()
            attachment_mimetype = (item.get('mimetype') or '').strip() or 'application/octet-stream'
            if attachment_base64.lower().startswith('data:') and ',' in attachment_base64:
                header, attachment_base64 = attachment_base64.split(',', 1)
                raw_mimetype = header[5:].split(';', 1)[0].strip() if ';' in header else ''
                if raw_mimetype:
                    attachment_mimetype = raw_mimetype

            attachments.append({
                'base64': attachment_base64,
                'name': attachment_name,
                'mimetype': attachment_mimetype or 'application/octet-stream',
            })
        return attachments

    attachment_base64 = (data.get('attachment_base64') or '').strip()
    if not attachment_base64:
        return attachments

    attachment_name = (data.get('attachment_name') or '').strip()
    attachment_mimetype = (data.get('attachment_mimetype') or '').strip() or 'application/octet-stream'
    if attachment_base64.lower().startswith('data:') and ',' in attachment_base64:
        header, attachment_base64 = attachment_base64.split(',', 1)
        raw_mimetype = header[5:].split(';', 1)[0].strip() if ';' in header else ''
        if raw_mimetype:
            attachment_mimetype = raw_mimetype

    attachments.append({
        'base64': attachment_base64,
        'name': attachment_name,
        'mimetype': attachment_mimetype or 'application/octet-stream',
    })
    return attachments


def _create_task_attachments(task, attachments, prefix, task_update=None):
    if not attachments:
        return

    Attachment = request.env['ir.attachment'].sudo()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    target_model = 'fin.employee.task'
    target_id = task.id
    if task_update and task_update.exists():
        target_model = 'fin.employee.task.update'
        target_id = task_update.id

    for index, attachment in enumerate(attachments, start=1):
        Attachment.create({
            'name': attachment.get('name') or f'{prefix}_{task.id}_{timestamp}_{index}',
            'type': 'binary',
            'datas': attachment['base64'],
            'mimetype': attachment.get('mimetype') or 'application/octet-stream',
            'res_model': target_model,
            'res_id': target_id,
        })


def _serialize_attachment(attachment):
    return {
        'id': attachment.id,
        'name': attachment.name or '',
        'mimetype': attachment.mimetype or 'application/octet-stream',
        'created_at': fields.Datetime.to_string(attachment.create_date)
        if attachment.create_date
        else None,
        'download_endpoint': f'/api/odoo-attendance/tasks/attachments/{attachment.id}/download',
    }


def _get_update_attachments(task, update):
    Attachment = request.env['ir.attachment'].sudo()
    attachments = Attachment.search(
        [
            ('res_model', '=', 'fin.employee.task.update'),
            ('res_id', '=', update.id),
        ],
        order='id desc',
    )
    if attachments:
        return attachments

    # Legacy fallback: earlier builds stored progress files on the task record.
    if not update.updated_at:
        return Attachment.browse()
    window_start = fields.Datetime.to_string(update.updated_at - timedelta(minutes=10))
    window_end = fields.Datetime.to_string(update.updated_at + timedelta(minutes=10))
    return Attachment.search(
        [
            ('res_model', '=', 'fin.employee.task'),
            ('res_id', '=', task.id),
            ('create_date', '>=', window_start),
            ('create_date', '<=', window_end),
        ],
        order='id desc',
    )

def _serialize_task(task):
    assignees = task.assignee_ids
    if not assignees and task.employee_id:
        assignees = task.employee_id
    task_attachments = task.task_attachment_ids.sorted(key=lambda a: a.id, reverse=True)
    updates = task.update_history_ids.sorted(
        key=lambda u: (u.updated_at or fields.Datetime.now(), u.id),
        reverse=True,
    )
    update_history = []
    for update in updates:
        update_attachments = _get_update_attachments(task, update)
        update_history.append({
            'id': update.id,
            'updated_at': fields.Datetime.to_string(update.updated_at)
            if update.updated_at
            else None,
            'progress': int(update.progress or 0),
            'update_note': update.update_note or '',
            'updated_by_user': {
                'id': update.updated_by_user_id.id,
                'name': update.updated_by_user_id.name or '',
            } if update.updated_by_user_id else None,
            'updated_by_employee': {
                'id': update.updated_by_employee_id.id,
                'name': update.updated_by_employee_id.name or '',
            } if update.updated_by_employee_id else None,
            'attachment_count': len(update_attachments),
            'attachments': [_serialize_attachment(att) for att in update_attachments],
        })

    return {
        'id': task.id,
        'x_task_number': task.x_task_number or '',
        'name': task.name or '',
        'description': task.description or '',
        'assignees': [
            {'id': emp.id, 'name': emp.name or ''}
            for emp in assignees
        ] if assignees else [],
        'employee': {
            'id': task.employee_id.id,
            'name': task.employee_id.name or '',
        } if task.employee_id else None,
        'manager': {
            'id': task.manager_id.id,
            'name': task.manager_id.name or '',
        } if task.manager_id else None,
        'analytic_account': {
            'id': task.analytic_account_id.id,
            'name': task.analytic_account_id.name or '',
            'code': task.analytic_account_id.code or '',
        } if task.analytic_account_id else None,
        'target_start_date': fields.Datetime.to_string(task.target_start_date)
        if task.target_start_date
        else None,
        'target_end_date': fields.Datetime.to_string(task.target_end_date)
        if task.target_end_date
        else None,
        'progress': int(task.progress or 0),
        'status': task.status or 'pending',
        'last_update_at': fields.Datetime.to_string(task.last_update_at)
        if task.last_update_at
        else None,
        'update_note': task.update_note or '',
        'priority': task.priority or '',
        'estimated_hours': task.estimated_hours or 0.0,
        'active': bool(task.active),
        'attachments': [_serialize_attachment(att) for att in task_attachments],
        'update_history': update_history,
    }


def _can_edit_original_task(hr_employee, task):
    if not hr_employee or not task:
        return False
    if task.manager_id and task.manager_id.id == hr_employee.id:
        return True
    if getattr(hr_employee, 'user_id', False) and hr_employee.user_id and task.create_uid:
        return task.create_uid.id == hr_employee.user_id.id
    return False


def _serialize_task_for_actor(task, hr_employee):
    data = _serialize_task(task)
    data['can_edit_original'] = bool(_can_edit_original_task(hr_employee, task))
    return data


class TasksController(http.Controller):
    """
    Employee task management endpoints.
    """

    def _get_odoo_hierarchy_employee_ids(self, hr_employee, include_self=False):
        Employee = request.env['hr.employee'].sudo()
        if not hr_employee:
            return []
        hierarchy_ids = set(
            Employee.search([
                ('active', '=', True),
                ('id', 'child_of', hr_employee.id),
            ]).ids
        )
        if include_self:
            hierarchy_ids.add(hr_employee.id)
        else:
            hierarchy_ids.discard(hr_employee.id)
        return list(hierarchy_ids)

    def _validate_assignable_employees(self, hr_employee, employees):
        if not employees:
            return
        Employee = request.env['hr.employee'].sudo()
        allowed_ids = set(Employee.search([('active', '=', True)]).ids)
        invalid_employees = employees.filtered(lambda emp: emp.id not in allowed_ids)
        if invalid_employees:
            names = ', '.join(invalid_employees.mapped('name'))
            raise ValidationError(
                f'You can only assign tasks to active employees. Invalid employees: {names}.'
            )

    def _get_fallback_employee_ids(self, hr_employee):
        EmployeeApp = request.env['odoo.attendance.employee'].sudo()
        app_records = EmployeeApp.search([('manager_employee_ids', 'in', [hr_employee.id])])
        return app_records.mapped('employee_id').ids

    def _get_manager_tree_employee_ids(self, hr_employee):
        """
        Resolve all indirect reports using the mobile app manager mapping.
        This walks the graph where each employee may have manager_employee_ids set.
        """
        Employee = request.env['hr.employee'].sudo()
        EmployeeApp = request.env['odoo.attendance.employee'].sudo()
        seen_employee_ids = set()
        seen_manager_ids = {hr_employee.id}
        queue_manager_ids = {hr_employee.id}

        while queue_manager_ids:
            app_records = EmployeeApp.search([('manager_employee_ids', 'in', list(queue_manager_ids))])
            found_employee_ids = set(app_records.mapped('employee_id').ids)
            new_employee_ids = found_employee_ids - seen_employee_ids
            if not new_employee_ids:
                break
            seen_employee_ids.update(new_employee_ids)
            # Treat newly found employees as managers for next level
            new_manager_ids = new_employee_ids - seen_manager_ids
            if not new_manager_ids:
                break
            seen_manager_ids.update(new_manager_ids)
            queue_manager_ids = new_manager_ids

        # Expand using HR hierarchy as well, so manager scope includes all lower levels
        # even when some intermediate employees do not have mobile app records.
        hierarchy_seed_ids = [hr_employee.id] + list(seen_employee_ids)
        if hierarchy_seed_ids:
            hierarchy_ids = Employee.search([('id', 'child_of', hierarchy_seed_ids)]).ids
            seen_employee_ids.update(hierarchy_ids)

        seen_employee_ids.discard(hr_employee.id)
        return list(seen_employee_ids)

    def _get_team_employee_ids(self, hr_employee, include_self=False):
        return self._get_odoo_hierarchy_employee_ids(hr_employee, include_self=include_self)

    def _get_task_related_employee_ids(self, task):
        task_employee_ids = set(task.assignee_ids.ids or [])
        if task.employee_id:
            task_employee_ids.add(task.employee_id.id)
        return task_employee_ids

    def _can_update_team_task(self, hr_employee, task):
        task_employee_ids = self._get_task_related_employee_ids(task)
        if hr_employee.id in task_employee_ids:
            return True
        if task.manager_id.id == hr_employee.id:
            return True
        team_employee_ids = set(self._get_team_employee_ids(hr_employee, include_self=False))
        return bool(team_employee_ids.intersection(task_employee_ids))

    @http.route('/api/odoo-attendance/tasks/attachments/<int:attachment_id>/download', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def download_task_attachment(self, attachment_id, **kwargs):
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            Attachment = request.env['ir.attachment'].sudo()
            attachment = Attachment.browse(attachment_id)
            if not attachment.exists():
                return response_helper.not_found_response('Attachment not found.')

            Task = request.env['fin.employee.task'].sudo()
            TaskUpdate = request.env['fin.employee.task.update'].sudo()

            task = Task.browse()
            if attachment.res_model == 'fin.employee.task':
                task = Task.browse(attachment.res_id)
            elif attachment.res_model == 'fin.employee.task.update':
                update = TaskUpdate.browse(attachment.res_id)
                if update.exists():
                    task = update.task_id
            else:
                return response_helper.forbidden_response('Attachment is not linked to task records.')

            if not task or not task.exists():
                return response_helper.not_found_response('Task for this attachment was not found.')

            if not self._can_update_team_task(hr_employee, task):
                return response_helper.forbidden_response('You do not have access to this attachment.')

            if attachment.type != 'binary' or not attachment.datas:
                return response_helper.not_found_response('Attachment has no downloadable binary data.')

            import base64
            binary = base64.b64decode(attachment.datas)
            filename = (attachment.name or f'attachment_{attachment.id}').replace('"', '')
            return request.make_response(
                binary,
                headers=[
                    ('Content-Type', attachment.mimetype or 'application/octet-stream'),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                ],
            )
        except Exception as e:
            _logger.exception(f'Error in download_task_attachment endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/tasks/assignees', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def list_task_assignees(self, **kwargs):
        """
        List active employees available for task assignment.
        Supports optional search query and pagination.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            search_query = request.params.get('q', '').strip()
            limit = _parse_int(request.params.get('limit', 50), 'limit') or 50
            offset = _parse_int(request.params.get('offset', 0), 'offset') or 0
            include_self = str(request.params.get('include_self', '')).lower() in ('1', 'true', 'yes')
            Employee = request.env['hr.employee'].sudo()
            allowed_employee_ids = set(Employee.search([('active', '=', True)]).ids)
            if not include_self:
                allowed_employee_ids.discard(hr_employee.id)
            allowed_employee_ids = list(allowed_employee_ids)

            domain = [
                ('active', '=', True),
                ('id', 'in', allowed_employee_ids or [0]),
            ]
            if search_query:
                domain.extend(['|', ('name', 'ilike', search_query), ('work_email', 'ilike', search_query)])

            employees = Employee.search(domain, limit=limit, offset=offset, order='name asc')

            results = []
            for emp in employees:
                results.append(
                    {
                        'id': emp.id,
                        'name': emp.name or '',
                        'job_title': emp.job_title or '',
                        'department': emp.department_id.name if emp.department_id else '',
                        'company': emp.company_id.name if emp.company_id else '',
                        'parent_id': emp.parent_id.id if emp.parent_id else None,
                        'has_children': bool(emp.child_ids),
                    }
                )

            return response_helper.success_response({'results': results})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in list_task_assignees endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/my_tasks', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_my_tasks(self, **kwargs):
        """
        Returns tasks for the authenticated employee.

        Supports filters similar to the team_tasks endpoint:
        - analytic_account_id
        - status: pending | in_process | done
        - date_from / date_to (overlap with task target dates)
        - limit / offset

        Backward compatibility:
        - If `date` is provided (legacy clients), it's treated as date_from=date_to=date.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            legacy_date = _parse_date(request.params.get('date'), 'date')
            date_from = _parse_date(request.params.get('date_from'), 'date_from')
            date_to = _parse_date(request.params.get('date_to'), 'date_to')
            if legacy_date and not date_from and not date_to:
                date_from = legacy_date
                date_to = legacy_date

            analytic_account_ids = _parse_int_list(
                request.params.get('analytic_account_ids'),
                'analytic_account_ids',
            )
            legacy_analytic_account_id = _parse_int(
                request.params.get('analytic_account_id'),
                'analytic_account_id',
            )
            if legacy_analytic_account_id and legacy_analytic_account_id not in analytic_account_ids:
                analytic_account_ids.append(legacy_analytic_account_id)

            statuses = _parse_choice_list(
                request.params.get('statuses'),
                'statuses',
                ('pending', 'in_process', 'done'),
            )
            legacy_status = (request.params.get('status') or '').strip()
            if legacy_status:
                if legacy_status not in ('pending', 'in_process', 'done'):
                    return response_helper.validation_error_response('Invalid status filter.')
                if legacy_status not in statuses:
                    statuses.append(legacy_status)
            task_id = _parse_int(request.params.get('task_id'), 'task_id')

            Task = request.env['fin.employee.task'].sudo()
            domain = [
                ('active', '=', True),
                '|',
                ('assignee_ids', 'in', [hr_employee.id]),
                ('employee_id', '=', hr_employee.id),
            ]

            if analytic_account_ids:
                domain.append(('analytic_account_id', 'in', analytic_account_ids))

            if statuses:
                domain.append(('status', 'in', statuses))

            if date_from and date_to:
                domain.extend([
                    ('target_start_date', '<=', _date_to_day_end(date_to)),
                    ('target_end_date', '>=', _date_to_day_start(date_from)),
                ])
            elif date_from:
                domain.append(('target_end_date', '>=', _date_to_day_start(date_from)))
            elif date_to:
                domain.append(('target_start_date', '<=', _date_to_day_end(date_to)))

            if task_id:
                domain.append(('id', '=', task_id))

            limit = _parse_int(request.params.get('limit'), 'limit')
            offset = _parse_int(request.params.get('offset'), 'offset') or 0
            if limit is not None:
                limit = max(1, min(limit, 200))
            else:
                # Legacy behavior: if a client requests a single day without pagination params, return all items.
                limit = None if legacy_date else 50
            offset = max(0, offset)

            tasks = Task.search(
                domain,
                limit=limit,
                offset=offset,
                order='target_end_date asc, progress asc, id desc',
            )
            results = [_serialize_task_for_actor(task, hr_employee) for task in tasks]

            return response_helper.success_response({'items': results})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in get_my_tasks endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/team_tasks', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_team_tasks(self, **kwargs):
        """
        Returns all active tasks (team-wide visibility).
        Supports filtering and optional summary metrics.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            employee_ids = _parse_int_list(request.params.get('employee_ids'), 'employee_ids')
            legacy_employee_id = _parse_int(request.params.get('employee_id'), 'employee_id')
            if legacy_employee_id and legacy_employee_id not in employee_ids:
                employee_ids.append(legacy_employee_id)

            analytic_account_ids = _parse_int_list(
                request.params.get('analytic_account_ids'),
                'analytic_account_ids',
            )
            legacy_analytic_account_id = _parse_int(
                request.params.get('analytic_account_id'),
                'analytic_account_id',
            )
            if legacy_analytic_account_id and legacy_analytic_account_id not in analytic_account_ids:
                analytic_account_ids.append(legacy_analytic_account_id)

            statuses = _parse_choice_list(
                request.params.get('statuses'),
                'statuses',
                ('pending', 'in_process', 'done'),
            )
            legacy_status = (request.params.get('status') or '').strip()
            if legacy_status:
                if legacy_status not in ('pending', 'in_process', 'done'):
                    return response_helper.validation_error_response('Invalid status filter.')
                if legacy_status not in statuses:
                    statuses.append(legacy_status)
            date_from = _parse_date(request.params.get('date_from'), 'date_from')
            date_to = _parse_date(request.params.get('date_to'), 'date_to')
            task_id = _parse_int(request.params.get('task_id'), 'task_id')
            limit = _parse_int(request.params.get('limit', 50), 'limit') or 50
            offset = _parse_int(request.params.get('offset', 0), 'offset') or 0
            include_summary = str(request.params.get('include_summary', '1')).lower() in ('1', 'true', 'yes')

            Task = request.env['fin.employee.task'].sudo()
            base_domain = [('active', '=', True)]

            if employee_ids:
                base_domain.extend([
                    '|',
                    ('assignee_ids', 'in', employee_ids),
                    ('employee_id', 'in', employee_ids),
                ])

            if analytic_account_ids:
                base_domain.append(('analytic_account_id', 'in', analytic_account_ids))

            if statuses:
                base_domain.append(('status', 'in', statuses))

            if date_from and date_to:
                base_domain.extend([
                    ('target_start_date', '<=', _date_to_day_end(date_to)),
                    ('target_end_date', '>=', _date_to_day_start(date_from)),
                ])
            elif date_from:
                base_domain.append(('target_end_date', '>=', _date_to_day_start(date_from)))
            elif date_to:
                base_domain.append(('target_start_date', '<=', _date_to_day_end(date_to)))

            if task_id:
                base_domain.append(('id', '=', task_id))

            tasks = Task.search(
                base_domain,
                limit=limit,
                offset=offset,
                order='target_end_date asc, progress asc, id desc',
            )
            results = [_serialize_task_for_actor(task, hr_employee) for task in tasks]

            payload = {'items': results}

            if include_summary:
                payload['summary'] = self._build_team_summary(Task, base_domain, filter_employee_ids=employee_ids)

            return response_helper.success_response(payload)

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in get_team_tasks endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    def _build_team_summary(self, Task, domain, filter_employee_ids=None):
        tasks_count = Task.search_count(domain)
        summary = {
            'counts_by_status': {'pending': 0, 'in_process': 0, 'done': 0},
            'avg_progress_by_employee': [],
            'avg_progress_by_analytic': [],
        }

        if not tasks_count:
            return summary

        status_groups = Task.read_group(domain, ['status'], ['status'], lazy=False)
        for group in status_groups:
            status = group.get('status')
            count = group.get('__count', 0)
            if status in summary['counts_by_status']:
                summary['counts_by_status'][status] = count

        # Fallback for counts if grouping didn't return expected buckets
        if sum(summary['counts_by_status'].values()) == 0 and tasks_count > 0:
            pending_domain = list(domain) + [('progress', '=', 0)]
            in_process_domain = list(domain) + [('progress', '>', 0), ('progress', '<', 100)]
            done_domain = list(domain) + [('progress', '>=', 100)]
            summary['counts_by_status']['pending'] = Task.search_count(pending_domain)
            summary['counts_by_status']['in_process'] = Task.search_count(in_process_domain)
            summary['counts_by_status']['done'] = Task.search_count(done_domain)

        emp_groups = Task.read_group(domain, ['progress:avg'], ['assignee_ids'], lazy=False)
        if not emp_groups:
            emp_groups = Task.read_group(domain, ['progress:avg'], ['employee_id'], lazy=False)

        for group in emp_groups:
            emp = group.get('assignee_ids') or group.get('employee_id')
            avg = group.get('progress_avg')
            emp_ids = []
            if emp:
                if isinstance(emp, (list, tuple)):
                    emp_ids = list(emp)
                else:
                    emp_ids = [emp]
            if (
                filter_employee_ids
                and emp_ids
                and not any(emp_id in filter_employee_ids for emp_id in emp_ids)
            ):
                continue
            if avg is None:
                avg = group.get('progress')
            if emp:
                summary['avg_progress_by_employee'].append(
                    {
                        'employee_id': emp[0],
                        'employee_name': emp[1],
                        'avg_progress': round(avg or 0.0, 1),
                    }
                )

        analytic_groups = Task.read_group(domain, ['progress:avg'], ['analytic_account_id'], lazy=False)
        for group in analytic_groups:
            analytic = group.get('analytic_account_id')
            avg = group.get('progress_avg')
            if avg is None:
                avg = group.get('progress')
            if analytic:
                summary['avg_progress_by_analytic'].append(
                    {
                        'analytic_account_id': analytic[0],
                        'analytic_account_name': analytic[1],
                        'avg_progress': round(avg or 0.0, 1),
                    }
                )

        summary['avg_progress_by_employee'].sort(key=lambda x: x['employee_name'])
        summary['avg_progress_by_analytic'].sort(key=lambda x: x['analytic_account_name'])
        return summary

    @http.route('/api/odoo-attendance/tasks', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_task(self, **kwargs):
        """
        Create a new task.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                return response_helper.validation_error_response('Invalid JSON in request body')

            name = (data.get('name') or '').strip()
            description = (data.get('description') or '').strip()
            employee_ids = _parse_int_list(data.get('employee_ids'), 'employee_ids')
            employee_id = _parse_int(data.get('employee_id'), 'employee_id')
            allow_self_raw = data.get('allow_self')
            analytic_account_id = _parse_int(data.get('analytic_account_id'), 'analytic_account_id')
            target_start_date = _parse_task_datetime(data.get('target_start_date'), 'target_start_date')
            target_end_date = _parse_task_datetime(data.get('target_end_date'), 'target_end_date')
            priority = _parse_priority(data.get('priority'))
            estimated_hours = _parse_float(data.get('estimated_hours'), 'estimated_hours')
            allow_self = str(allow_self_raw).strip().lower() in ('1', 'true', 'yes', 'on')
            attachments = _normalize_task_attachments(data)

            if not name:
                return response_helper.validation_error_response('Task title is required.')
            if not employee_ids and employee_id:
                employee_ids = [employee_id]
            if not employee_ids and allow_self:
                employee_ids = [hr_employee.id]
            if not employee_ids:
                return response_helper.validation_error_response('employee_ids is required.')
            task_project_required = _is_task_project_required(request.env)
            if task_project_required and not analytic_account_id:
                return response_helper.validation_error_response('analytic_account_id is required.')
            if not target_start_date or not target_end_date:
                return response_helper.validation_error_response('Target start and end date/time are required.')
            if target_end_date < target_start_date:
                return response_helper.validation_error_response('End date/time must be on or after start date/time.')

            Employee = request.env['hr.employee'].sudo()
            assignees = Employee.browse(employee_ids).exists()
            if not assignees or len(assignees) != len(set(employee_ids)):
                return response_helper.validation_error_response('Employee not found.')
            self._validate_assignable_employees(hr_employee, assignees)

            analytic_record = None
            if analytic_account_id:
                Analytic = request.env['account.analytic.account'].sudo()
                analytic_record = Analytic.browse(analytic_account_id)
                if not analytic_record.exists():
                    return response_helper.validation_error_response('Analytic account not found.')

                for emp in assignees:
                    analytic_domain = [('id', '=', analytic_account_id)] + _build_analytic_access_domain(emp)
                    analytic = Analytic.search(analytic_domain, limit=1)
                    if not analytic:
                        return response_helper.forbidden_response(
                            'Analytic account is not accessible to the employee.'
                        )

            Task = request.env['fin.employee.task'].sudo()
            primary_id = assignees[0].id if assignees else employee_ids[0]
            task_vals = {
                'name': name,
                'description': description,
                'employee_id': primary_id,
                'assignee_ids': [(6, 0, assignees.ids)],
                'manager_id': hr_employee.id,
                'target_start_date': target_start_date,
                'target_end_date': target_end_date,
                'priority': priority or False,
                'estimated_hours': estimated_hours,
            }
            if analytic_record:
                task_vals['analytic_account_id'] = analytic_record.id

            task = Task.create(task_vals)
            _create_task_attachments(task, attachments, 'task_create')

            return response_helper.success_response({'task': _serialize_task_for_actor(task, hr_employee)})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in create_task endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/tasks/<int:task_id>', type='http', auth='public', methods=['PATCH', 'POST'], csrf=False, cors='*')
    def update_task(self, task_id, **kwargs):
        """
        Update task details.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                return response_helper.validation_error_response('Invalid JSON in request body')
            if not isinstance(data, dict):
                return response_helper.validation_error_response('Request body must be a JSON object.')
            if 'id' in data or 'task_id' in data:
                return response_helper.validation_error_response(
                    'Task ID is generated by Odoo and must not be provided.'
                )

            Task = request.env['fin.employee.task'].sudo()
            task = Task.browse(task_id)
            if not task.exists():
                return response_helper.not_found_response('Task not found.')

            can_edit = _can_edit_original_task(hr_employee, task)
            if not can_edit:
                return response_helper.forbidden_response(
                    'Only the user who created this task can edit task details.'
                )

            vals = {}

            if 'name' in data:
                name = (data.get('name') or '').strip()
                if not name:
                    return response_helper.validation_error_response('Task title is required.')
                vals['name'] = name

            if 'description' in data:
                vals['description'] = (data.get('description') or '').strip()

            employee_ids = _parse_int_list(data.get('employee_ids'), 'employee_ids') if 'employee_ids' in data else []
            employee_id = _parse_int(data.get('employee_id'), 'employee_id') if 'employee_id' in data else None
            allow_self_raw = data.get('allow_self')
            allow_self = str(allow_self_raw).strip().lower() in ('1', 'true', 'yes', 'on')
            has_assignee_update = ('employee_ids' in data) or ('employee_id' in data)
            if not employee_ids and employee_id:
                employee_ids = [employee_id]
            if has_assignee_update and not employee_ids and allow_self:
                employee_ids = [hr_employee.id]

            assignees = None
            if has_assignee_update:
                if not employee_ids:
                    return response_helper.validation_error_response('employee_ids is required.')

                Employee = request.env['hr.employee'].sudo()
                assignees = Employee.browse(employee_ids).exists()
                if not assignees or len(assignees) != len(set(employee_ids)):
                    return response_helper.validation_error_response('Employee not found.')
                self._validate_assignable_employees(hr_employee, assignees)

                vals['employee_id'] = assignees[0].id
                vals['assignee_ids'] = [(6, 0, assignees.ids)]

            new_start_date = _parse_task_datetime(data.get('target_start_date'), 'target_start_date') if 'target_start_date' in data else task.target_start_date
            new_end_date = _parse_task_datetime(data.get('target_end_date'), 'target_end_date') if 'target_end_date' in data else task.target_end_date
            if not new_start_date or not new_end_date:
                return response_helper.validation_error_response('Target start and end date/time are required.')
            if new_end_date < new_start_date:
                return response_helper.validation_error_response('End date/time must be on or after start date/time.')
            if 'target_start_date' in data:
                vals['target_start_date'] = new_start_date
            if 'target_end_date' in data:
                vals['target_end_date'] = new_end_date

            if 'priority' in data:
                vals['priority'] = _parse_priority(data.get('priority'))

            if 'estimated_hours' in data:
                raw_estimated = data.get('estimated_hours')
                if raw_estimated in (None, ''):
                    vals['estimated_hours'] = 0.0
                else:
                    estimated_hours = _parse_float(raw_estimated, 'estimated_hours')
                    if estimated_hours is not None and estimated_hours < 0:
                        return response_helper.validation_error_response('estimated_hours must be a positive number.')
                    vals['estimated_hours'] = estimated_hours

            analytic_account_id = _parse_int(data.get('analytic_account_id'), 'analytic_account_id') if 'analytic_account_id' in data else task.analytic_account_id.id
            task_project_required = _is_task_project_required(request.env)
            if task_project_required and not analytic_account_id:
                return response_helper.validation_error_response('analytic_account_id is required.')

            target_assignees = assignees or task.assignee_ids
            if not target_assignees and task.employee_id:
                target_assignees = task.employee_id

            if analytic_account_id:
                Analytic = request.env['account.analytic.account'].sudo()
                analytic_record = Analytic.browse(analytic_account_id)
                if not analytic_record.exists():
                    return response_helper.validation_error_response('Analytic account not found.')

                for emp in target_assignees:
                    analytic_domain = [('id', '=', analytic_account_id)] + _build_analytic_access_domain(emp)
                    analytic = Analytic.search(analytic_domain, limit=1)
                    if not analytic:
                        return response_helper.forbidden_response(
                            'Analytic account is not accessible to the employee.'
                        )

            if 'analytic_account_id' in data:
                vals['analytic_account_id'] = analytic_account_id or False

            if vals:
                if 'progress' in vals or 'update_note' in vals:
                    ctx = {
                        'force_task_update_notification': True,
                        'task_update_actor_employee_id': hr_employee.id,
                    }
                    if getattr(hr_employee, 'user_id', False) and hr_employee.user_id:
                        ctx['task_update_actor_user_id'] = hr_employee.user_id.id
                    task.with_context(**ctx).write(vals)
                else:
                    task.write(vals)

            return response_helper.success_response({'task': _serialize_task_for_actor(task, hr_employee)})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in update_task endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/tasks/<int:task_id>/progress', type='http', auth='public', methods=['PATCH', 'POST'], csrf=False, cors='*')
    def update_task_progress(self, task_id, **kwargs):
        """
        Update task progress from my/team tasks when the employee has update access.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                return response_helper.validation_error_response('Invalid JSON in request body')
            if not isinstance(data, dict):
                return response_helper.validation_error_response('Request body must be a JSON object.')
            if 'id' in data or 'task_id' in data:
                return response_helper.validation_error_response(
                    'Task ID is immutable and cannot be provided in the request body.'
                )

            progress = _parse_int(data.get('progress'), 'progress')
            update_note = data.get('update_note', None)
            attachments = _normalize_task_attachments(data)

            if progress is None:
                return response_helper.validation_error_response('progress is required.')
            if progress < 0 or progress > 100:
                return response_helper.validation_error_response('progress must be between 0 and 100.')

            Task = request.env['fin.employee.task'].sudo()
            task = Task.browse(task_id)
            if not task.exists():
                return response_helper.not_found_response('Task not found.')

            can_edit = self._can_update_team_task(hr_employee, task)
            if not can_edit:
                return response_helper.forbidden_response(
                    'You can only update tasks you are assigned to, tasks you assigned, or tasks in your hierarchy.'
                )

            vals = {
                'progress': progress,
                'last_update_at': fields.Datetime.now(),
            }
            if update_note is not None:
                vals['update_note'] = (update_note or '').strip()
            ctx = {
                'force_task_update_notification': True,
                'task_update_actor_employee_id': hr_employee.id,
            }
            if getattr(hr_employee, 'user_id', False) and hr_employee.user_id:
                ctx['task_update_actor_user_id'] = hr_employee.user_id.id
            task.with_context(**ctx).write(vals)
            task_update = request.env['fin.employee.task.update'].sudo().search(
                [('task_id', '=', task.id)],
                order='updated_at desc, id desc',
                limit=1,
            )
            _create_task_attachments(task, attachments, 'task_progress', task_update=task_update)

            return response_helper.success_response({'task': _serialize_task_for_actor(task, hr_employee)})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in update_task_progress endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/tasks/<int:task_id>/delegate', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def delegate_task(self, task_id, **kwargs):
        """
        Delegate a task from the authenticated employee to another employee.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                return response_helper.validation_error_response('Invalid JSON in request body')

            target_employee_id = _parse_int(data.get('employee_id'), 'employee_id')
            if not target_employee_id:
                return response_helper.validation_error_response('employee_id is required.')

            Task = request.env['fin.employee.task'].sudo()
            task = Task.browse(task_id)
            if not task.exists():
                return response_helper.not_found_response('Task not found.')

            current_assignees = set(task.assignee_ids.ids or [])
            if not current_assignees and task.employee_id:
                current_assignees.add(task.employee_id.id)

            if hr_employee.id not in current_assignees and task.employee_id.id != hr_employee.id:
                return response_helper.forbidden_response('You can only delegate your own tasks.')

            Employee = request.env['hr.employee'].sudo()
            target_employee = Employee.browse(target_employee_id)
            if not target_employee.exists() or not target_employee.active:
                return response_helper.validation_error_response('Employee not found.')
            self._validate_assignable_employees(hr_employee, target_employee)

            current_assignees.add(hr_employee.id)
            current_assignees.add(target_employee_id)

            vals = {
                'assignee_ids': [(6, 0, list(current_assignees))],
            }
            if task.employee_id and task.employee_id.id == hr_employee.id:
                vals['employee_id'] = target_employee_id

            task.write(vals)

            return response_helper.success_response({'task': _serialize_task_for_actor(task, hr_employee)})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in delegate_task endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/tasks/<int:task_id>/delete', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def delete_task(self, task_id, **kwargs):
        """
        Delete a task if the authenticated employee assigned it or it belongs to
        the employee hierarchy they can manage.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            Task = request.env['fin.employee.task'].sudo()
            task = Task.browse(task_id)
            if not task.exists():
                return response_helper.not_found_response('Task not found.')

            team_employee_ids = set(self._get_team_employee_ids(hr_employee, include_self=False))
            task_employee_ids = set(task.assignee_ids.ids or [])
            if task.employee_id:
                task_employee_ids.add(task.employee_id.id)
            can_delete = task.manager_id.id == hr_employee.id or bool(team_employee_ids.intersection(task_employee_ids))
            if not can_delete:
                return response_helper.forbidden_response('You can only delete tasks you assigned or tasks in your hierarchy.')

            task.unlink()
            return response_helper.success_response({'ok': True, 'task_id': task_id})

        except ValidationError as e:
            return response_helper.validation_error_response(str(e))
        except Exception as e:
            _logger.exception(f'Error in delete_task endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')





