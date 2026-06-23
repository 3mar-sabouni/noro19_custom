# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class FinEmployeeTaskUpdate(models.Model):
    _name = 'fin.employee.task.update'
    _description = 'Employee Task Update'
    _order = 'updated_at desc, id desc'

    task_id = fields.Many2one(
        'fin.employee.task',
        string='Task',
        required=True,
        ondelete='cascade',
        index=True,
    )
    updated_at = fields.Datetime(
        string='Updated At',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    progress = fields.Integer(string='Progress (%)', required=True)
    update_note = fields.Text(string='Update Note')

    updated_by_employee_id = fields.Many2one(
        'hr.employee',
        string='Updated By (Employee)',
        ondelete='set null',
        index=True,
    )
    updated_by_user_id = fields.Many2one(
        'res.users',
        string='Updated By (User)',
        ondelete='set null',
        index=True,
    )
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments',
        compute='_compute_attachments',
        readonly=True,
    )
    attachment_count = fields.Integer(
        string='Attachment Count',
        compute='_compute_attachments',
        readonly=True,
    )

    @api.constrains('progress')
    def _check_progress_range(self):
        for rec in self:
            if rec.progress < 0 or rec.progress > 100:
                raise ValidationError('Progress must be between 0 and 100.')

    def _compute_attachments(self):
        for record in self:
            record.attachment_ids = record._resolve_attachments()
            record.attachment_count = len(record.attachment_ids)

    def _resolve_attachments(self):
        self.ensure_one()
        Attachment = self.env['ir.attachment'].sudo()
        attachments = Attachment.search(
            [
                ('res_model', '=', 'fin.employee.task.update'),
                ('res_id', '=', self.id),
            ],
            order='id desc',
        )
        if attachments:
            return attachments

        # Backward compatibility for older records where progress attachments
        # were stored on the task instead of the update line.
        if not self.task_id or not self.updated_at:
            return attachments
        window_start = fields.Datetime.to_string(self.updated_at - timedelta(minutes=10))
        window_end = fields.Datetime.to_string(self.updated_at + timedelta(minutes=10))
        return Attachment.search(
            [
                ('res_model', '=', 'fin.employee.task'),
                ('res_id', '=', self.task_id.id),
                ('create_date', '>=', window_start),
                ('create_date', '<=', window_end),
            ],
            order='id desc',
        )

    def action_download_attachments(self):
        self.ensure_one()
        attachments = self._resolve_attachments()
        if not attachments:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No attachments',
                    'message': 'This update has no attachments.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        if len(attachments) == 1:
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%s?download=true' % attachments[0].id,
                'target': 'self',
            }
        form_view = self.env.ref('base.view_attachment_form', raise_if_not_found=False)
        views = []
        if form_view:
            views.append((form_view.id, 'form'))
        first = attachments[0]
        return {
            'type': 'ir.actions.act_window',
            'name': 'Update Attachments',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'views': views or False,
            'target': 'current',
            'domain': [('id', 'in', attachments.ids)],
            'context': {
                'default_res_model': first.res_model,
                'default_res_id': first.res_id,
                'search_default_group_by_res_model': 0,
            },
        }

    def action_delete_attachments(self):
        self.ensure_one()
        attachments = self._resolve_attachments()
        if not attachments:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No attachments',
                    'message': 'This update has no attachments to delete.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        attachments.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

