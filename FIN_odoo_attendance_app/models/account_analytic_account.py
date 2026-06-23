# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AccountAnalyticAccount(models.Model):
    """
    Extends account.analytic.account with employee access control.
    Only employees in x_allowed_employee_ids can see this analytic account in the mobile app,
    unless x_allow_all_employees is enabled (default).
    """
    _inherit = 'account.analytic.account'
    
    x_allow_all_employees = fields.Boolean(
        string='Allow All Employees',
        default=True,
        help='If enabled, all employees can use this analytic account in the mobile app.'
    )
    x_allowed_employee_ids = fields.Many2many(
        'hr.employee',
        'analytic_account_employee_rel',
        'analytic_account_id',
        'employee_id',
        string='Allowed Employees',
        help='Employees who can select this analytic account in the mobile attendance app'
    )

    x_employee_count = fields.Integer(
        string='Allowed Employees Count',
        compute='_compute_employee_count',
        store=True
    )

    # Geofencing: optional coordinates and radius (km) to restrict check-ins
    x_enable_geofence = fields.Boolean(
        string='Enable Geofence',
        help='If enabled, check-ins/outs must be within the defined radius of the coordinates.'
    )
    x_location_lat = fields.Float(
        string='Latitude',
        help='Latitude of the allowed check-in area for this analytic account.'
    )
    x_location_lng = fields.Float(
        string='Longitude',
        help='Longitude of the allowed check-in area for this analytic account.'
    )
    x_location_radius_km = fields.Float(
        string='Allowed Radius (km)',
        help='Maximum distance (in km) from the set coordinates where check-in is allowed. Leave 0 to disable.'
    )
    x_location_ids = fields.One2many(
        'odoo.attendance.analytic.location',
        'analytic_account_id',
        string='Locations',
        help='Optional list of allowed locations for this analytic account.',
    )
    x_geofence_exception_employee_ids = fields.Many2many(
        'hr.employee',
        'analytic_account_geofence_exception_rel',
        'analytic_account_id',
        'employee_id',
        string='Geofence Exceptions',
        help='Employees who are allowed to check-in/out without being restricted by this analytic account geofence.',
    )

    x_selfie_policy_checkin = fields.Selection(
        [
            ('optional', 'Optional'),
            ('required', 'Required'),
        ],
        string='Check-in Selfie',
        default='optional',
        required=True,
        help='Whether a selfie is required when checking in to this project from the mobile app.',
    )
    x_selfie_policy_checkout = fields.Selection(
        [
            ('optional', 'Optional'),
            ('required', 'Required'),
        ],
        string='Check-out Selfie',
        default='optional',
        required=True,
        help='Whether a selfie is required when checking out of this project from the mobile app.',
    )
    
    @api.depends('x_allowed_employee_ids', 'x_allow_all_employees')
    def _compute_employee_count(self):
        """Count allowed employees"""
        for record in self:
            record.x_employee_count = (
                record.env['hr.employee'].sudo().search_count([('active', '=', True)])
                if record.x_allow_all_employees
                else len(record.x_allowed_employee_ids)
            )

    @api.model_create_multi
    def create(self, vals_list):
        # Default to allow all employees if not explicitly set and populate list when appropriate
        all_emp_ids = None
        for vals in vals_list:
            vals.setdefault('x_allow_all_employees', True)
            if vals.get('x_allow_all_employees'):
                if all_emp_ids is None:
                    all_emp_ids = self.env['hr.employee'].sudo().search([('active', '=', True)]).ids
                vals['x_allowed_employee_ids'] = [(6, 0, all_emp_ids)]
        return super(AccountAnalyticAccount, self).create(vals_list)

    def write(self, vals):
        # Default to allow all employees if not explicitly set
        vals.setdefault('x_allow_all_employees', True)

        # If user disables allow-all and provides no explicit list, clear the list
        if vals.get('x_allow_all_employees') is False and 'x_allowed_employee_ids' not in vals:
            vals['x_allowed_employee_ids'] = [(6, 0, [])]
        # If user enables allow-all, populate the allowed list with all active employees
        if vals.get('x_allow_all_employees'):
            all_emp_ids = self.env['hr.employee'].sudo().search([('active', '=', True)]).ids
            vals['x_allowed_employee_ids'] = [(6, 0, all_emp_ids)]
        return super(AccountAnalyticAccount, self).write(vals)

    @api.onchange('x_allow_all_employees')
    def _onchange_allow_all_employees(self):
        """
        Keep the allowed employees list in sync with the toggle on the form.
        When allow-all is checked, populate with all active employees so names show immediately.
        When unchecked, clear the list (user can then pick specific employees).
        """
        for record in self:
            if record.x_allow_all_employees:
                all_emp_ids = record.env['hr.employee'].sudo().search([('active', '=', True)]).ids
                record.x_allowed_employee_ids = [(6, 0, all_emp_ids)]
            else:
                record.x_allowed_employee_ids = [(6, 0, [])]

    @api.model
    def default_get(self, fields_list):
        res = super(AccountAnalyticAccount, self).default_get(fields_list)
        res.setdefault('x_allow_all_employees', True)
        return res

    @api.model
    def init(self):
        """Ensure existing analytic accounts default to allow all employees."""
        self.env.cr.execute("""
            UPDATE account_analytic_account
            SET x_allow_all_employees = TRUE
            WHERE x_allow_all_employees IS NULL OR x_allow_all_employees = FALSE
        """)
