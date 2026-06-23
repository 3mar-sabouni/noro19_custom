# -*- coding: utf-8 -*-
from datetime import timedelta

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)
MODULE_NAME = __name__.split(".")[2] if __name__.startswith("odoo.addons.") else "FIN_odoo_attendance_app"


def _local_xmlid(name):
    return f"{MODULE_NAME}.{name}"

class HrAttendance(models.Model):
    """
    Extends hr.attendance with fields required for mobile app:
    - Analytic account (mandatory for check-in)
    - GPS coordinates and reverse-geocoded address
    - Optional selfie attachments
    """
    _inherit = 'hr.attendance'

    # Analytic Account (Project/Department)
    x_analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        required=False,
        index=True,
        help='Project or cost center for this attendance'
    )
    
    # Check-in GPS Data
    x_checkin_gps_lat = fields.Float(
        string='Check-in Latitude',
        digits=(10, 7),
        help='GPS latitude at check-in'
    )
    x_checkin_gps_lng = fields.Float(
        string='Check-in Longitude',
        digits=(10, 7),
        help='GPS longitude at check-in'
    )
    x_checkin_gps_accuracy = fields.Float(
        string='Check-in GPS Accuracy',
        help='GPS accuracy in meters at check-in'
    )
    x_checkin_gps_address = fields.Text(
        string='Check-in Address',
        help='Reverse-geocoded address at check-in'
    )
    x_checkin_selfie_id = fields.Many2one(
        'ir.attachment',
        string='Check-in Selfie',
        help='Optional selfie photo taken at check-in'
    )
    x_checkin_gallery_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Check-in Photos',
        compute='_compute_checkin_gallery_attachments',
        store=False,
        help='Additional optional photos uploaded at check-in from the mobile app.',
    )
    x_checkin_gallery_count = fields.Integer(
        string='Check-in Photos Count',
        compute='_compute_checkin_gallery_attachments',
        store=False,
    )
    x_checkin_note = fields.Text(
        string='Check-in Note',
        help='Mandatory note provided by the user at check-in'
    )

    message_in = fields.Char(string='Check-in Message')
    
    # Check-out GPS Data (optional separate fields)
    x_checkout_gps_lat = fields.Float(
        string='Check-out Latitude',
        digits=(10, 7),
        help='GPS latitude at check-out'
    )
    x_checkout_gps_lng = fields.Float(
        string='Check-out Longitude',
        digits=(10, 7),
        help='GPS longitude at check-out'
    )
    x_checkout_gps_accuracy = fields.Float(
        string='Check-out GPS Accuracy',
        help='GPS accuracy in meters at check-out'
    )
    x_checkout_gps_address = fields.Text(
        string='Check-out Address',
        help='Reverse-geocoded address at check-out'
    )
    x_checkout_selfie_id = fields.Many2one(
        'ir.attachment',
        string='Check-out Selfie',
        help='Optional selfie photo taken at check-out'
    )
    
    # Fleet tracking fields
    x_vehicle_id = fields.Many2one(
        'odoo.attendance.vehicle',
        string='Vehicle',
        help='Vehicle used for this attendance trip'
    )
    x_start_kilometrage = fields.Float(
        string='Start (km / mi / hr)',
        help='Odometer reading at check-in'
    )
    x_end_kilometrage = fields.Float(
        string='End (km / mi / hr)',
        help='Odometer reading at check-out'
    )
    x_kilometrage_difference = fields.Float(
        string='Distance Travelled',
        compute='_compute_kilometrage_difference',
        store=True,
        help='Total distance travelled during this trip'
    )
    x_fleet_trip_id = fields.Many2one(
        'odoo.attendance.fleet.trip',
        string='Fleet Trip',
        help='Linked fleet trip record'
    )
    x_checkout_note = fields.Text(
        string='Check-out Note',
        help='Mandatory note provided by the user at check-out'
    )

    x_checkout_gallery_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Check-out Photos',
        compute='_compute_checkout_gallery_attachments',
        store=False,
        help='Additional optional photos uploaded at check-out from the mobile app.',
    )
    x_checkout_gallery_count = fields.Integer(
        string='Check-out Photos Count',
        compute='_compute_checkout_gallery_attachments',
        store=False,
    )

    # Google Maps links (computed, non-stored)
    x_checkin_map_url = fields.Char(
        string='Check-in Map',
        compute='_compute_map_urls',
        store=False
    )
    x_checkout_map_url = fields.Char(
        string='Check-out Map',
        compute='_compute_map_urls',
        store=False
    )
    
    # Computed field for full GPS info display
    x_gps_info = fields.Char(
        string='GPS Info',
        compute='_compute_gps_info',
        store=False
    )

    x_scheduled_hours = fields.Float(
        string='Scheduled Hours',
        compute='_compute_scheduled_and_extra_hours',
        store=False,
        help="Planned hours for the check-in day based on the employee's working schedule.",
    )
    x_extra_hours = fields.Float(
        string='Extra Hours (App)',
        compute='_compute_scheduled_and_extra_hours',
        store=False,
        help='Extra hours = max(0, worked hours - scheduled hours).',
    )

    x_timesheet_line_id = fields.Many2one(
        'account.analytic.line',
        string='Timesheet Line',
        readonly=True,
        help='Timesheet line created from this attendance record.',
    )
    x_timesheet_transferred_at = fields.Datetime(
        string='Timesheet Transferred At',
        readonly=True,
        help='When this attendance was transferred to a timesheet line.',
    )
    x_performed_by_user_id = fields.Many2one(
        'res.users',
        string='Performed By User',
        readonly=True,
        help='User who executed the attendance action.',
    )
    x_performed_by_employee_id = fields.Many2one(
        'hr.employee',
        string='Performed By Employee',
        readonly=True,
        help='Employee who executed the attendance action.',
    )
    x_performed_for_employee_id = fields.Many2one(
        'hr.employee',
        string='Performed For Employee',
        readonly=True,
        help='Employee for whom attendance was performed.',
    )
    x_action_source = fields.Selection(
        [('mobile_app', 'Mobile App'), ('other', 'Other')],
        string='Action Source',
        default='other',
        readonly=True,
    )
    x_is_checked_by_delegate = fields.Boolean(
        string='Checked By Delegate',
        default=False,
        readonly=True,
        help='True when attendance was performed on behalf of another employee.',
    )
    @api.model
    def _is_checkin_project_required(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_attendance_app.checkin_project_required',
            None,
        )
        if raw_value not in (None, ''):
            return str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
        config = self.env['odoo.attendance.app.config'].sudo().search([], order='id desc', limit=1)
        if config and 'checkin_project_required' in config._fields:
            return bool(config.checkin_project_required)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if self._is_checkin_project_required():
            for vals in vals_list:
                has_check_in = bool(vals.get('check_in'))
                has_check_out = bool(vals.get('check_out'))
                if not has_check_in or has_check_out:
                    continue
                analytic_id = vals.get('x_analytic_account_id')
                try:
                    analytic_id = int(analytic_id) if analytic_id not in (None, False, '') else 0
                except Exception:
                    analytic_id = 0
                if analytic_id <= 0:
                    raise ValidationError('Project is required for check-in.')
        return super().create(vals_list)

    def write(self, vals):
        checkout_requested = bool(vals.get('check_out'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            if checkout_requested:
                for record in self.filtered('x_fleet_trip_id'):
                    record.x_fleet_trip_id.sudo()._complete_from_attendance(record)
            if self._is_checkin_project_required():
                for record in self:
                    if record.check_in and not record.check_out and not record.x_analytic_account_id:
                        raise ValidationError('Project is required for check-in.')
        return result
    
    @api.depends('x_checkin_gps_lat', 'x_checkin_gps_lng', 'x_checkout_gps_lat', 'x_checkout_gps_lng')
    def _compute_gps_info(self):
        """Display GPS coordinates in readable format"""
        for record in self:
            parts = []
            if record.x_checkin_gps_lat and record.x_checkin_gps_lng:
                parts.append(f"In: {record.x_checkin_gps_lat:.5f}, {record.x_checkin_gps_lng:.5f}")
            if record.x_checkout_gps_lat and record.x_checkout_gps_lng:
                parts.append(f"Out: {record.x_checkout_gps_lat:.5f}, {record.x_checkout_gps_lng:.5f}")
            record.x_gps_info = ' | '.join(parts) if parts else ''

    def _compute_map_urls(self):
        """Build Google Maps URLs for check-in/out points"""
        for record in self:
            if record.x_checkin_gps_lat and record.x_checkin_gps_lng:
                record.x_checkin_map_url = (
                    'https://www.google.com/maps/search/?api=1&query='
                    f'{record.x_checkin_gps_lat:.6f}%2C{record.x_checkin_gps_lng:.6f}'
                )
            else:
                record.x_checkin_map_url = False

            if record.x_checkout_gps_lat and record.x_checkout_gps_lng:
                record.x_checkout_map_url = (
                    'https://www.google.com/maps/search/?api=1&query='
                    f'{record.x_checkout_gps_lat:.6f}%2C{record.x_checkout_gps_lng:.6f}'
                )
            else:
                record.x_checkout_map_url = False

    @api.depends('check_in', 'worked_hours', 'employee_id', 'employee_id.resource_calendar_id')
    def _compute_scheduled_and_extra_hours(self):
        """
        Scheduled hours are computed for the UTC calendar day of check_in.
        Extra hours = max(0, worked_hours - scheduled_hours).
        """
        for record in self:
            record.x_scheduled_hours = 0.0
            record.x_extra_hours = 0.0

            if not record.check_in or not record.employee_id:
                continue

            calendar = record.employee_id.resource_calendar_id
            if calendar:
                day_start = record.check_in.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                try:
                    scheduled = float(calendar.get_work_hours_count(day_start, day_end, compute_leaves=False))
                except Exception:
                    scheduled = 0.0
            else:
                scheduled = 0.0

            worked = float(record.worked_hours or 0.0)
            extra = worked - scheduled

            record.x_scheduled_hours = round(max(scheduled, 0.0), 2)
            record.x_extra_hours = round(extra if extra > 0 else 0.0, 2)

    def _compute_checkout_gallery_attachments(self):
        Attachment = self.env['ir.attachment'].sudo()
        for record in self:
            if not record.id:
                record.x_checkout_gallery_attachment_ids = [(6, 0, [])]
                record.x_checkout_gallery_count = 0
                continue

            attachments = Attachment.search([
                ('res_model', '=', 'hr.attendance'),
                ('res_id', '=', record.id),
            ], order='create_date desc')

            emp_id = record.employee_id.id or 0
            analytic_id = record.x_analytic_account_id.id or 0

            # Keep only gallery photos with the naming scheme: employee_id-analytic_account_id-date-serial.jpg
            gallery_attachments = attachments.filtered(
                lambda a: self._is_checkout_gallery_attachment_name(a.name, emp_id, analytic_id)
            )
            record.x_checkout_gallery_attachment_ids = gallery_attachments
            record.x_checkout_gallery_count = len(gallery_attachments)

    def _compute_checkin_gallery_attachments(self):
        Attachment = self.env['ir.attachment'].sudo()
        for record in self:
            if not record.id:
                record.x_checkin_gallery_attachment_ids = [(6, 0, [])]
                record.x_checkin_gallery_count = 0
                continue

            attachments = Attachment.search([
                ('res_model', '=', 'hr.attendance'),
                ('res_id', '=', record.id),
            ], order='create_date desc')

            emp_id = record.employee_id.id or 0
            analytic_id = record.x_analytic_account_id.id or 0

            gallery_attachments = attachments.filtered(
                lambda a: self._is_checkin_gallery_attachment_name(a.name, emp_id, analytic_id)
            )
            record.x_checkin_gallery_attachment_ids = gallery_attachments
            record.x_checkin_gallery_count = len(gallery_attachments)

    @api.model
    def _is_checkout_gallery_attachment_name(self, name, employee_id, analytic_account_id):
        if not name or not name.endswith('.jpg'):
            return False
        prefix = f'{employee_id}-{analytic_account_id}-'
        if not name.startswith(prefix):
            return False
        rest = name[len(prefix):]
        parts = rest.rsplit('-', 1)
        if len(parts) != 2:
            return False
        serial_part = parts[1].removesuffix('.jpg')
        return serial_part.isdigit()

    @api.model
    def _is_checkin_gallery_attachment_name(self, name, employee_id, analytic_account_id):
        if not name or not name.endswith('.jpg'):
            return False
        prefix = f'checkin-{employee_id}-{analytic_account_id}-'
        if not name.startswith(prefix):
            return False
        rest = name[len(prefix):]
        parts = rest.rsplit('-', 1)
        if len(parts) != 2:
            return False
        serial_part = parts[1].removesuffix('.jpg')
        return serial_part.isdigit()

    def _get_checkout_gallery_attachments_domain(self):
        self.ensure_one()
        emp_id = self.employee_id.id or 0
        analytic_id = self.x_analytic_account_id.id or 0
        return [
            ('res_model', '=', 'hr.attendance'),
            ('res_id', '=', self.id),
            ('name', '=ilike', f'{emp_id}-{analytic_id}-%'),
        ]

    def _get_checkin_gallery_attachments_domain(self):
        self.ensure_one()
        emp_id = self.employee_id.id or 0
        analytic_id = self.x_analytic_account_id.id or 0
        return [
            ('res_model', '=', 'hr.attendance'),
            ('res_id', '=', self.id),
            ('name', '=ilike', f'checkin-{emp_id}-{analytic_id}-%'),
        ]

    def action_open_checkout_gallery_attachments(self):
        self.ensure_one()
        tree_view = self.env.ref(
            _local_xmlid('view_ir_attachment_checkout_gallery_tree'),
            raise_if_not_found=False,
        )
        kanban_view = self.env.ref(
            _local_xmlid('view_ir_attachment_checkout_gallery_kanban'),
            raise_if_not_found=False,
        )
        form_view = self.env.ref('base.view_attachment_form', raise_if_not_found=False)

        views = []
        if kanban_view:
            views.append((kanban_view.id, 'kanban'))
        if tree_view:
            views.append((tree_view.id, 'list'))
        if form_view:
            views.append((form_view.id, 'form'))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Check-out Photos',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'views': views or False,
            'target': 'current',
            'domain': self._get_checkout_gallery_attachments_domain(),
            'context': {
                'default_res_model': 'hr.attendance',
                'default_res_id': self.id,
                'search_default_group_by_res_model': 0,
            },
        }

    def action_open_checkin_gallery_attachments(self):
        self.ensure_one()
        tree_view = self.env.ref(
            _local_xmlid('view_ir_attachment_checkin_gallery_tree'),
            raise_if_not_found=False,
        )
        kanban_view = self.env.ref(
            _local_xmlid('view_ir_attachment_checkin_gallery_kanban'),
            raise_if_not_found=False,
        )
        form_view = self.env.ref('base.view_attachment_form', raise_if_not_found=False)

        views = []
        if kanban_view:
            views.append((kanban_view.id, 'kanban'))
        if tree_view:
            views.append((tree_view.id, 'list'))
        if form_view:
            views.append((form_view.id, 'form'))

        return {
            'type': 'ir.actions.act_window',
            'name': 'Check-in Photos',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'views': views or False,
            'target': 'current',
            'domain': self._get_checkin_gallery_attachments_domain(),
            'context': {
                'default_res_model': 'hr.attendance',
                'default_res_id': self.id,
                'search_default_group_by_res_model': 0,
            },
        }

    def action_download_checkout_gallery_zip(self):
        self.ensure_one()
        if not self.x_checkout_gallery_count:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No photos',
                    'message': 'No check-out photos to download for this attendance.',
                    'sticky': False,
                    'type': 'warning',
                },
            }
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo_attendance_app/attendance/{self.id}/checkout_photos.zip',
            'target': 'self',
        }

    def action_download_checkin_gallery_zip(self):
        self.ensure_one()
        if not self.x_checkin_gallery_count:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No photos',
                    'message': 'No check-in photos to download for this attendance.',
                    'sticky': False,
                    'type': 'warning',
                },
            }
        return {
            'type': 'ir.actions.act_url',
            'url': f'/odoo_attendance_app/attendance/{self.id}/checkin_photos.zip',
            'target': 'self',
        }

    @api.model
    def _get_selfie_retention_days(self):
        icp = self.env['ir.config_parameter'].sudo()
        raw_value = icp.get_param('odoo_attendance_app.selfie_retention_days', default='60')
        try:
            days = int(raw_value)
        except Exception:
            days = 60
        return max(days, 0)

    @api.model
    def _cron_cleanup_old_attendance_selfies(self):
        days = self._get_selfie_retention_days()
        if days <= 0:
            return True

        cutoff = fields.Datetime.now() - timedelta(days=days)
        Attachment = self.env['ir.attachment'].sudo()

        selfies = Attachment.search([
            ('res_model', '=', 'hr.attendance'),
            ('create_date', '<', cutoff),
            '|',
            ('name', '=ilike', 'CheckIn_Selfie_%'),
            ('name', '=ilike', 'CheckOut_Selfie_%'),
        ])

        if not selfies:
            return True

        attendance_ids = set(selfies.mapped('res_id'))
        attendances = self.sudo().browse(list(attendance_ids)).exists()

        # Clear selfie fields pointing to soon-to-be-deleted attachments to avoid dangling Many2one values
        for attendance in attendances:
            values = {}
            if attendance.x_checkin_selfie_id and attendance.x_checkin_selfie_id in selfies:
                values['x_checkin_selfie_id'] = False
            if attendance.x_checkout_selfie_id and attendance.x_checkout_selfie_id in selfies:
                values['x_checkout_selfie_id'] = False
            if values:
                attendance.write(values)

        selfies.unlink()
        return True

    def _prepare_timesheet_vals(self, *, allow_skip_zero=False):
        self.ensure_one()
        if not self.employee_id:
            raise ValidationError('Employee is required to create a timesheet line.')
        if not self.x_analytic_account_id:
            raise ValidationError('Analytic account is required to create a timesheet line.')
        if not self.check_in:
            raise ValidationError('Check-in time is required to create a timesheet line.')

        hours = float(self.worked_hours or 0.0)
        if hours <= 0 and self.check_in and self.check_out:
            delta = self.check_out - self.check_in
            hours = max(delta.total_seconds() / 3600.0, 0.0)
        if hours <= 0:
            hours = 0.01

        employee_user_id = self.employee_id.user_id.id if self.employee_id.user_id else False
        if not employee_user_id:
            employee_user_id = self.env.user.id

        values = {
            'name': f'Attendance {self.id}',
            'employee_id': self.employee_id.id,
            'account_id': self.x_analytic_account_id.id,
            'unit_amount': hours,
            'date': fields.Date.to_date(self.check_in),
            'company_id': self.employee_id.company_id.id if self.employee_id.company_id else False,
            'project_id': self._get_timesheet_project_id(),
        }
        values['user_id'] = employee_user_id
        return values

    def _get_timesheet_project_id(self):
        self.ensure_one()
        Project = self.env.get('project.project')
        if not Project or not self.x_analytic_account_id:
            return False
        project = Project.sudo().search(
            [('analytic_account_id', '=', self.x_analytic_account_id.id)],
            limit=1,
        )
        if project:
            return project.id
        vals = {
            'name': self.x_analytic_account_id.name,
            'analytic_account_id': self.x_analytic_account_id.id,
        }
        if 'allow_timesheets' in Project._fields:
            vals['allow_timesheets'] = True
        project = Project.sudo().create(vals)
        return project.id

    def action_transfer_to_timesheet(self):
        created = 0
        skipped = 0
        errors = 0
        error_samples = []
        created_line_ids = []
        for record in self:
            if record.x_timesheet_line_id:
                skipped += 1
                continue
            vals = record._prepare_timesheet_vals(allow_skip_zero=True)
            if not vals:
                skipped += 1
                continue
            try:
                line = self.env['account.analytic.line'].sudo().create(vals)
                record.sudo().write(
                    {
                        'x_timesheet_line_id': line.id,
                        'x_timesheet_transferred_at': fields.Datetime.now(),
                    }
                )
                created += 1
                created_line_ids.append(line.id)
            except Exception as exc:
                _logger.warning('Timesheet transfer failed for attendance %s: %s', record.id, exc)
                if len(error_samples) < 3:
                    error_samples.append(str(exc))
                errors += 1

        details = ''
        if error_samples:
            details = ' Errors: ' + '; '.join(error_samples)

        if created_line_ids:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Timesheet Lines',
                'res_model': 'account.analytic.line',
                'view_mode': 'list,form',
                'domain': [('id', 'in', created_line_ids)],
                'target': 'current',
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Timesheet transfer',
                'message': f'Created {created}, skipped {skipped}, errors {errors}.' + details,
                'sticky': False,
                'type': 'success' if created else 'warning',
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    @api.model
    def _cron_transfer_attendance_to_timesheets(self):
        attendances = self.sudo().search(
            [
                ('x_timesheet_line_id', '=', False),
                ('x_analytic_account_id', '!=', False),
                ('check_in', '!=', False),
                ('worked_hours', '>', 0),
            ],
            order='check_in asc',
        )
        for record in attendances:
            try:
                vals = record._prepare_timesheet_vals(allow_skip_zero=True)
                if not vals:
                    continue
                line = self.env['account.analytic.line'].sudo().create(vals)
                record.sudo().write(
                    {
                        'x_timesheet_line_id': line.id,
                        'x_timesheet_transferred_at': fields.Datetime.now(),
                    }
                )
            except Exception as exc:
                _logger.warning('Cron timesheet transfer failed for attendance %s: %s', record.id, exc)
                continue
        return True

    @api.depends('x_start_kilometrage', 'x_end_kilometrage')
    def _compute_kilometrage_difference(self):
        for record in self:
            if record.x_start_kilometrage and record.x_end_kilometrage:
                record.x_kilometrage_difference = record.x_end_kilometrage - record.x_start_kilometrage
            else:
                record.x_kilometrage_difference = 0
    
    @api.constrains('x_start_kilometrage', 'x_end_kilometrage')
    def _check_kilometrage_values(self):
        for record in self:
            if record.x_start_kilometrage and record.x_end_kilometrage:
                if record.x_end_kilometrage < record.x_start_kilometrage:
                    raise ValidationError('End (km / mi / hr) cannot be less than start (km / mi / hr)')




