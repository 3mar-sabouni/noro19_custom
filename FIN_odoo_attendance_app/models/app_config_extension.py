# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OdooAttendanceAppConfig(models.Model):
    _inherit = 'odoo.attendance.app.config'

    _MOBILE_API_USER_PARAM_KEYS = (
        'odoo_attendance_app.mobile_api_user_id',
        'FIN_odoo_attendance_app.mobile_api_user_id',
        'fin_odoo_attendance_app.mobile_api_user_id',
    )

    checkin_project_required = fields.Boolean(
        string="Require Project on Check-In",
        default=True,
        help="If checked, employees must select a project/analytic account when checking in."
    )
    task_project_required = fields.Boolean(
        string="Require Project on New Tasks",
        default=True,
        help="If checked, creating a task requires selecting a project/analytic account."
    )
    checkin_note_required = fields.Boolean(
        string="Require Note on Check-In",
        default=True,
        help="If checked, employees must enter a note when checking in."
    )
    checkout_note_required = fields.Boolean(
        string="Require Note on Check-Out",
        default=True,
        help="If checked, employees must enter a note when checking out."
    )
    mobile_api_user_id = fields.Many2one(
        'res.users',
        string="Mobile API User",
        domain=[('share', '=', False), ('active', '=', True)],
        help="Authenticated mobile app requests run as this Odoo user instead of Public. Leave empty to keep Public."
    )

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        if 'checkin_project_required' in fields_list:
            raw_value = self.env['ir.config_parameter'].sudo().get_param(
                'odoo_attendance_app.checkin_project_required',
                'True',
            )
            result['checkin_project_required'] = str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
        if 'task_project_required' in fields_list:
            raw_value = self.env['ir.config_parameter'].sudo().get_param(
                'odoo_attendance_app.task_project_required',
                'True',
            )
            result['task_project_required'] = str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
        if 'checkin_note_required' in fields_list:
            raw_value = self.env['ir.config_parameter'].sudo().get_param(
                'odoo_attendance_app.checkin_note_required',
                'True',
            )
            result['checkin_note_required'] = str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
        if 'checkout_note_required' in fields_list:
            raw_value = self.env['ir.config_parameter'].sudo().get_param(
                'odoo_attendance_app.checkout_note_required',
                'True',
            )
            result['checkout_note_required'] = str(raw_value).strip().lower() in ('1', 'true', 'yes', 'on')
        if 'mobile_api_user_id' in fields_list:
            params = self.env['ir.config_parameter'].sudo()
            for param_key in self._MOBILE_API_USER_PARAM_KEYS:
                raw_value = params.get_param(param_key, None)
                if raw_value in (None, ''):
                    continue
                try:
                    result['mobile_api_user_id'] = int(str(raw_value).strip())
                except (TypeError, ValueError):
                    result['mobile_api_user_id'] = False
                break
        return result

    def _apply(self):
        result = super()._apply()
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_attendance_app.checkin_project_required',
            'True' if self.checkin_project_required else 'False',
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_attendance_app.task_project_required',
            'True' if self.task_project_required else 'False',
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_attendance_app.checkin_note_required',
            'True' if self.checkin_note_required else 'False',
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_attendance_app.checkout_note_required',
            'True' if self.checkout_note_required else 'False',
        )
        mobile_api_user_id = self.mobile_api_user_id.id or ''
        params = self.env['ir.config_parameter'].sudo()
        for param_key in self._MOBILE_API_USER_PARAM_KEYS:
            params.set_param(param_key, mobile_api_user_id)
        return result
