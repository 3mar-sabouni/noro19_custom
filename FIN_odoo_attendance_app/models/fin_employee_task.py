# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class FinEmployeeTask(models.Model):
    _name = 'fin.employee.task'
    _description = 'Employee Task'
    _order = 'target_start_date desc, id desc'

    # Unique task number sequence
    x_task_number = fields.Char(
        string='Task Number',
        readonly=True,
        copy=False,
        index=True,
    )

    name = fields.Char(string='Title', required=True, index=True)
    description = fields.Text(string='Description')
    employee_id = fields.Many2one(
        'hr.employee',
        string='Primary Employee',
        required=True,
        index=True,
        ondelete='restrict',
    )
    assignee_ids = fields.Many2many(
        'hr.employee',
        'fin_employee_task_assignee_rel',
        'task_id',
        'employee_id',
        string='Assignees',
        help='Employees assigned to this task (shared progress).',
    )
    assignable_employee_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_assignable_employee_ids',
        string='Assignable Employees',
        compute_sudo=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Assigned By',
        required=True,
        index=True,
        ondelete='restrict',
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        required=False,
        index=True,
        ondelete='restrict',
    )
    target_start_date = fields.Datetime(string='Target Start Date', required=True, index=True)
    target_end_date = fields.Datetime(string='Target End Date', required=True, index=True)
    progress = fields.Integer(string='Progress (%)', default=0)
    progress_avg = fields.Float(
        string='Progress (%)',
        compute='_compute_progress_avg',
        store=True,
        aggregator='avg',
    )
    progress_target = fields.Integer(
        string='Progress Target',
        compute='_compute_progress_target',
        store=True,
    )
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('in_process', 'In Process'),
            ('done', 'Done'),
        ],
        string='Status',
        compute='_compute_status',
        store=True,
        index=True,
    )
    last_update_at = fields.Datetime(
        string='Last Update At',
        default=fields.Datetime.now,
        index=True,
    )
    update_note = fields.Text(string='Update Note')
    update_history_ids = fields.One2many(
        'fin.employee.task.update',
        'task_id',
        string='Update History',
        readonly=True,
        copy=False,
    )
    priority = fields.Selection(
        [
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
        ],
        string='Priority',
    )
    estimated_hours = fields.Float(string='Estimated Hours')
    active = fields.Boolean(default=True)
    task_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments',
        compute='_compute_task_attachments',
        readonly=True,
    )
    task_attachment_count = fields.Integer(
        string='Attachments Count',
        compute='_compute_task_attachments',
        readonly=True,
    )

    @api.depends('progress')
    def _compute_status(self):
        for task in self:
            progress = task.progress or 0
            if progress <= 0:
                task.status = 'pending'
            elif progress < 100:
                task.status = 'in_process'
            else:
                task.status = 'done'

    @api.depends('progress')
    def _compute_progress_avg(self):
        for task in self:
            task.progress_avg = float(task.progress or 0)

    @api.depends('progress')
    def _compute_progress_target(self):
        for task in self:
            task.progress_target = 100

    def _get_current_user_assignable_employee_ids(self):
        return self.env['hr.employee'].sudo().search([('active', '=', True)]).ids

    @api.depends_context('uid')
    def _compute_assignable_employee_ids(self):
        allowed_ids = self._get_current_user_assignable_employee_ids()
        employees = self.env['hr.employee'].browse(allowed_ids)
        for task in self:
            task.assignable_employee_ids = employees

    def _is_task_project_required(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_attendance_app.task_project_required',
            None,
        )
        if raw_value not in (None, ''):
            return str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
        config = self.env['odoo.attendance.app.config'].sudo().search([], order='id desc', limit=1)
        if config and 'task_project_required' in config._fields:
            return bool(config.task_project_required)
        return True

    @api.constrains('analytic_account_id')
    def _check_analytic_account_required(self):
        if not self._is_task_project_required():
            return
        for task in self:
            if not task.analytic_account_id:
                raise ValidationError('Analytic account is required for tasks.')

    @api.constrains('progress')
    def _check_progress_range(self):
        for task in self:
            if task.progress is None:
                continue
            if task.progress < 0 or task.progress > 100:
                raise ValidationError('Progress must be between 0 and 100.')

    @api.constrains('target_start_date', 'target_end_date')
    def _check_dates(self):
        for task in self:
            if task.target_start_date and task.target_end_date:
                if task.target_end_date < task.target_start_date:
                    raise ValidationError('Target End Date must be on or after Target Start Date.')

    @api.constrains('employee_id', 'assignee_ids')
    def _check_assignment_hierarchy(self):
        Employee = self.env['hr.employee'].sudo()
        active_employee_ids = set(Employee.search([('active', '=', True)]).ids)
        if not active_employee_ids:
            return
        for task in self:
            target_ids = set(task.assignee_ids.ids or [])
            if not target_ids and task.employee_id:
                target_ids.add(task.employee_id.id)
            elif task.employee_id:
                target_ids.add(task.employee_id.id)
            if target_ids.difference(active_employee_ids):
                raise ValidationError(
                    _('You can only assign tasks to active employees.')
                )

    @staticmethod
    def _extract_assignee_ids(value, current_ids):
        if value is None:
            return list(current_ids or [])
        if isinstance(value, (list, tuple)):
            if not value:
                return []
            # List of ints -> direct ids
            if isinstance(value[0], int):
                return list(dict.fromkeys(int(v) for v in value))
            # M2M commands
            ids = set(current_ids or [])
            for cmd in value:
                if not isinstance(cmd, (list, tuple)) or not cmd:
                    continue
                command = cmd[0]
                if command == 6:
                    ids = set(cmd[2] or [])
                elif command == 4:
                    ids.add(cmd[1])
                elif command == 3:
                    ids.discard(cmd[1])
                elif command == 5:
                    ids.clear()
            return list(ids)
        return list(current_ids or [])

    def _normalize_assignees_vals(self, vals, current_assignee_ids=None):
        current_assignee_ids = current_assignee_ids or []
        employee_id = vals.get('employee_id') or (self.employee_id.id if self else None)
        assignee_val = vals.get('assignee_ids', None)

        if assignee_val is None:
            if employee_id:
                vals['assignee_ids'] = [(6, 0, [employee_id])]
            return vals

        ids = self._extract_assignee_ids(assignee_val, current_assignee_ids)
        if not ids and employee_id:
            ids = [employee_id]
        if employee_id and employee_id not in ids:
            ids.append(employee_id)
        if not employee_id and ids:
            vals['employee_id'] = ids[0]
        vals['assignee_ids'] = [(6, 0, ids)]
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for i, vals in enumerate(vals_list):
            vals = dict(vals or {})
            vals = self._normalize_assignees_vals(vals, [])
            # Generate task number if not provided
            if not vals.get('x_task_number'):
                Sequence = self.env['ir.sequence']
                next_num = Sequence.next_by_code('fin.employee.task.sequence')
                # Use sequence result, or generate a proper fallback based on current count
                if next_num:
                    task_number = next_num
                else:
                    # Fallback: get current max number + 1
                    self.env.cr.execute("""
                        SELECT MAX(CAST(SUBSTRING(x_task_number FROM 6) AS INTEGER)) 
                        FROM fin_employee_task 
                        WHERE x_task_number LIKE 'TASK-%'
                    """)
                    max_num = self.env.cr.fetchone()[0] or 0
                    task_number = f'TASK-{max_num + i + 1:04d}'
                    _logger.warning(f"Sequence failed, using fallback: {task_number}")
                
                vals['x_task_number'] = task_number
                _logger.info(f"Generated task number: {task_number} for task: {vals.get('name', 'Unnamed')}")
            normalized.append(vals)
        tasks = super(FinEmployeeTask, self).create(normalized)
        if not self.env.context.get('skip_task_assignment_notification'):
            for task in tasks:
                task._notify_new_assignees(task._effective_assignee_ids())
        return tasks

    def _effective_assignee_ids(self):
        self.ensure_one()
        assignee_ids = set(self.assignee_ids.ids or [])
        if not assignee_ids and self.employee_id:
            assignee_ids.add(self.employee_id.id)
        return assignee_ids

    def _notify_new_assignees(self, assignee_ids):
        """Create/send inbox + push notification for newly assigned employees."""
        self.ensure_one()
        if self.env.context.get('skip_task_assignment_notification'):
            return
        target_hr_ids = set(assignee_ids or [])
        if not target_hr_ids:
            return

        try:
            EmployeeApp = self.env['odoo.attendance.employee'].sudo()
            target_apps = EmployeeApp.search(
                [
                    ('employee_id', 'in', list(target_hr_ids)),
                    ('is_active', '=', True),
                ]
            )
            if not target_apps:
                return

            task_ref = (self.x_task_number or '').strip() or f'#{self.id}'
            task_name = (self.name or '').strip() or _('Task')
            manager_name = (self.manager_id.name or '').strip() if self.manager_id else ''
            due_date = fields.Datetime.to_string(self.target_end_date) if self.target_end_date else ''

            body_lines = [
                _('You have been assigned to task %(ref)s: %(name)s') % {
                    'ref': task_ref,
                    'name': task_name,
                }
            ]
            if manager_name:
                body_lines.append(_('Assigned by: %(manager)s') % {'manager': manager_name})
            if due_date:
                body_lines.append(_('Due date: %(due)s') % {'due': due_date})

            message = self.env['odoo.attendance.inbox.message'].sudo().create(
                {
                    'name': _('New Task Assignment'),
                    'body': '\n'.join(body_lines),
                    'message_type': 'system',
                    'target_all': False,
                    'target_employee_app_ids': [(6, 0, target_apps.ids)],
                    'send_mode': 'send_now',
                }
            )
            message.action_send_now()
        except Exception:
            _logger.exception(
                'Failed to send task assignment notifications (task_id=%s, assignee_ids=%s)',
                self.id,
                list(target_hr_ids),
            )

    def _get_task_update_actor(self):
        """Return (actor_hr_ids, actor_name) for task update notifications."""
        Employee = self.env['hr.employee'].sudo()
        User = self.env['res.users'].sudo()
        actor_hr_ids = set()
        actor_name = ''

        actor_employee_id = self.env.context.get('task_update_actor_employee_id')
        actor_user_id = self.env.context.get('task_update_actor_user_id') or self.env.user.id

        if actor_employee_id:
            actor_employee = Employee.browse(actor_employee_id)
            if actor_employee.exists():
                actor_hr_ids.add(actor_employee.id)
                actor_name = actor_employee.name or ''

        if actor_user_id:
            actor_user = User.browse(actor_user_id)
            if actor_user.exists():
                if not actor_name:
                    actor_name = actor_user.name or ''
                if actor_user.employee_id:
                    actor_hr_ids.add(actor_user.employee_id.id)
                elif hasattr(actor_user, 'employee_ids') and len(actor_user.employee_ids) == 1:
                    actor_hr_ids.add(actor_user.employee_ids.id)

        return actor_hr_ids, actor_name

    def _notify_related_task_update(self):
        """Create/send inbox + push notification to related task users except updater."""
        if self.env.context.get('skip_task_update_notification'):
            return
        if not self.env.context.get('force_task_update_notification'):
            raw_enabled = self.env['ir.config_parameter'].sudo().get_param(
                'odoo_attendance_app.task_update_notify_primary_employee',
                'True',
            )
            if str(raw_enabled).strip().lower() not in ('1', 'true', 'yes', 'on'):
                return

        EmployeeApp = self.env['odoo.attendance.employee'].sudo()
        actor_hr_ids, actor_name = self._get_task_update_actor()

        for task in self:
            target_hr_ids = set(task.assignee_ids.ids or [])
            if task.employee_id:
                target_hr_ids.add(task.employee_id.id)
            if task.manager_id:
                target_hr_ids.add(task.manager_id.id)
            if actor_hr_ids:
                target_hr_ids.difference_update(actor_hr_ids)
            if not target_hr_ids:
                _logger.info(
                    'Task update notify skipped: no recipients after excluding actor (task_id=%s, actor_hr_ids=%s)',
                    task.id,
                    list(actor_hr_ids),
                )
                continue

            try:
                target_apps = EmployeeApp.search(
                    [
                        ('employee_id', 'in', list(target_hr_ids)),
                        ('is_active', '=', True),
                    ]
                )
                if not target_apps:
                    _logger.info(
                        'Task update notify skipped: no active app users for recipients (task_id=%s, target_hr_ids=%s)',
                        task.id,
                        list(target_hr_ids),
                    )
                    continue
                _logger.info(
                    'Task update notify dispatch (task_id=%s, target_hr_ids=%s, target_app_ids=%s)',
                    task.id,
                    list(target_hr_ids),
                    target_apps.ids,
                )

                task_ref = (task.x_task_number or '').strip() or f'#{task.id}'
                task_name = (task.name or '').strip() or _('Task')
                note = (task.update_note or '').strip()
                body_lines = [
                    _('Task %(ref)s was updated: %(name)s') % {
                        'ref': task_ref,
                        'name': task_name,
                    },
                    _('Progress: %(progress)s%%') % {'progress': int(task.progress or 0)},
                ]
                if actor_name:
                    body_lines.append(_('Updated by: %(actor)s') % {'actor': actor_name})
                if note:
                    body_lines.append(_('Update note: %(note)s') % {'note': note})

                message = self.env['odoo.attendance.inbox.message'].sudo().create(
                    {
                        'name': _('Task Update'),
                        'body': '\n'.join(body_lines),
                        'message_type': 'system',
                        'target_all': False,
                        'target_employee_app_ids': [(6, 0, target_apps.ids)],
                        'send_mode': 'send_now',
                    }
                )
                message.action_send_now()
            except Exception:
                _logger.exception(
                    'Failed to send task update notification (task_id=%s, target_hr_ids=%s)',
                    task.id,
                    list(target_hr_ids),
                )

    def _compute_task_attachments(self):
        Attachment = self.env['ir.attachment'].sudo()
        grouped = {task.id: Attachment.browse() for task in self}

        if self:
            task_attachments = Attachment.search(
                [
                    ('res_model', '=', 'fin.employee.task'),
                    ('res_id', 'in', self.ids),
                ],
                order='id desc',
            )
            for attachment in task_attachments:
                if attachment.res_id in grouped:
                    grouped[attachment.res_id] |= attachment

            updates = self.env['fin.employee.task.update'].sudo().search(
                [('task_id', 'in', self.ids)]
            )
            update_to_task = {update.id: update.task_id.id for update in updates}
            if update_to_task:
                update_attachments = Attachment.search(
                    [
                        ('res_model', '=', 'fin.employee.task.update'),
                        ('res_id', 'in', list(update_to_task.keys())),
                    ],
                    order='id desc',
                )
                for attachment in update_attachments:
                    task_id = update_to_task.get(attachment.res_id)
                    if task_id in grouped:
                        grouped[task_id] |= attachment

        empty = Attachment.browse()
        for task in self:
            task.task_attachment_ids = grouped.get(task.id, empty)
            task.task_attachment_count = len(task.task_attachment_ids)

    def action_open_task_attachments(self):
        self.ensure_one()
        attachments = self.task_attachment_ids.sudo()
        if not attachments:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No attachments',
                    'message': 'No attachments are available for this task.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        tree_view = self.env.ref('base.view_attachment_tree', raise_if_not_found=False)
        form_view = self.env.ref('base.view_attachment_form', raise_if_not_found=False)
        views = []
        if tree_view:
            views.append((tree_view.id, 'list'))
        if form_view:
            views.append((form_view.id, 'form'))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Task Attachments',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'views': views or False,
            'target': 'current',
            'domain': [('id', 'in', attachments.ids)],
            'context': {
                'default_res_model': 'fin.employee.task',
                'default_res_id': self.id,
                'search_default_group_by_res_model': 0,
                'create': False,
            },
        }

    def _create_update_history_entries(self, *, write_vals=None):
        """
        Append one history line per task capturing the latest progress + note.

        Uses context keys set by API controllers when running under sudo:
        - task_update_actor_employee_id
        - task_update_actor_user_id
        """
        Update = self.env['fin.employee.task.update'].sudo()
        actor_employee_id = self.env.context.get('task_update_actor_employee_id')
        actor_user_id = self.env.context.get('task_update_actor_user_id') or self.env.user.id
        write_vals = dict(write_vals or {})

        vals_list = []
        for task in self:
            updated_at = write_vals.get('last_update_at') or task.last_update_at or fields.Datetime.now()
            vals_list.append(
                {
                    'task_id': task.id,
                    'updated_at': updated_at,
                    'progress': int(task.progress or 0),
                    'update_note': task.update_note or '',
                    'updated_by_employee_id': actor_employee_id or False,
                    'updated_by_user_id': actor_user_id or False,
                }
            )
        if vals_list:
            Update.create(vals_list)

    def write(self, vals):
        vals = dict(vals or {})
        force_task_update_notification = bool(self.env.context.get('force_task_update_notification'))
        wants_log = (
            ('progress' in vals or 'update_note' in vals)
            and (force_task_update_notification or not self.env.context.get('skip_task_update_log'))
        )

        if 'progress' in vals or 'update_note' in vals:
            vals.setdefault('last_update_at', fields.Datetime.now())

        if 'assignee_ids' in vals or 'employee_id' in vals:
            for record in self:
                old_assignee_ids = record._effective_assignee_ids()
                record_vals = dict(vals)
                record_vals = record._normalize_assignees_vals(
                    record_vals,
                    record.assignee_ids.ids,
                )
                should_log = False
                if wants_log:
                    old_progress = int(record.progress or 0)
                    old_note = record.update_note or ''
                    new_progress = int(record_vals.get('progress', old_progress) or 0)
                    if 'update_note' in record_vals:
                        new_note = record_vals.get('update_note') or ''
                    else:
                        new_note = old_note
                    should_log = (new_progress != old_progress) or (
                        'update_note' in record_vals and new_note != old_note
                    )
                    if force_task_update_notification:
                        should_log = True
                super(FinEmployeeTask, record).write(record_vals)
                if should_log:
                    record._create_update_history_entries(write_vals=record_vals)
                    record._notify_related_task_update()
                new_assignee_ids = record._effective_assignee_ids()
                added_assignee_ids = new_assignee_ids - old_assignee_ids
                if added_assignee_ids:
                    record._notify_new_assignees(added_assignee_ids)
            return True

        to_log = self.browse()
        if wants_log:
            for record in self:
                old_progress = int(record.progress or 0)
                old_note = record.update_note or ''
                new_progress = int(vals.get('progress', old_progress) or 0)
                if 'update_note' in vals:
                    new_note = vals.get('update_note') or ''
                else:
                    new_note = old_note
                if force_task_update_notification or (new_progress != old_progress) or (
                    'update_note' in vals and new_note != old_note
                ):
                    to_log |= record

        res = super(FinEmployeeTask, self).write(vals)
        if to_log:
            to_log._create_update_history_entries(write_vals=vals)
            to_log._notify_related_task_update()
        return res

    @api.model
    def init(self):
        """Ensure existing tasks have assignees populated from the primary employee."""
        super(FinEmployeeTask, self).init()
        
        # Find the maximum existing task number to ensure uniqueness
        self.env.cr.execute("""
            SELECT MAX(CAST(SUBSTRING(x_task_number FROM 6) AS INTEGER)) 
            FROM fin_employee_task 
            WHERE x_task_number LIKE 'TASK-%'
        """)
        max_task_number = self.env.cr.fetchone()[0]
        start_sequence = (max_task_number or 0) + 1

        # Reset the main sequence to the next available number
        if max_task_number:
            self.env.cr.execute(f"""
                UPDATE ir_sequence 
                   SET number_next = {start_sequence}
                   WHERE code = 'fin.employee.task.sequence'
            """)

        # Create a temporary sequence starting from the next available number
        self.env.cr.execute(f"""
            CREATE TEMPORARY SEQUENCE IF NOT EXISTS temp_task_seq START {start_sequence}
        """)
        
        # Populate missing task numbers using the temporary sequence
        self.env.cr.execute(
            """
            UPDATE fin_employee_task
               SET x_task_number = 'TASK-' || LPAD(nextval('temp_task_seq')::text, 4, '0')
             WHERE x_task_number IS NULL OR x_task_number = ''
            """
        )
        
        # Drop the temporary sequence
        self.env.cr.execute(
            """
            DROP SEQUENCE IF EXISTS temp_task_seq
            """
        )
        
        self.env.cr.execute(
            """
            INSERT INTO fin_employee_task_assignee_rel (task_id, employee_id)
            SELECT t.id, t.employee_id
            FROM fin_employee_task t
            WHERE t.employee_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM fin_employee_task_assignee_rel rel
                WHERE rel.task_id = t.id
              )
            """
        )
        self.env.cr.execute(
            """
            UPDATE fin_employee_task
               SET status = CASE
                   WHEN COALESCE(progress, 0) <= 0 THEN 'pending'
                   WHEN COALESCE(progress, 0) < 100 THEN 'in_process'
                   ELSE 'done'
               END
             WHERE status IS NULL
            """
        )







