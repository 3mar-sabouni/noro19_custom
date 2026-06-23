# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class FinEmployeeTaskDashboardReport(models.Model):
    _name = 'fin.employee.task.dashboard.report'
    _description = 'Task Dashboard Report'
    _auto = False
    _rec_name = 'task_id'
    _order = 'target_end_date desc, id desc'

    task_id = fields.Many2one('fin.employee.task', string='Task', readonly=True)
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        readonly=True,
    )
    primary_employee_id = fields.Many2one(
        'hr.employee',
        string='Primary Employee',
        readonly=True,
    )
    assignee_employee_id = fields.Many2one(
        'hr.employee',
        string='Assignee',
        readonly=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    manager_id = fields.Many2one('hr.employee', string='Assigned By', readonly=True)
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('in_process', 'In Process'),
            ('done', 'Done'),
        ],
        string='Status',
        readonly=True,
    )
    progress_pct = fields.Float(
        string='Average Progress (%)',
        readonly=True,
        aggregator='avg',
    )
    task_count = fields.Integer(
        string='Tasks',
        readonly=True,
        aggregator='sum',
    )
    target_start_date = fields.Datetime(string='Target Start Date', readonly=True)
    target_end_date = fields.Datetime(string='Target End Date', readonly=True)
    last_update_at = fields.Datetime(string='Last Update At', readonly=True)
    priority = fields.Selection(
        [
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
        ],
        string='Priority',
        readonly=True,
    )
    active = fields.Boolean(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW fin_employee_task_dashboard_report AS (
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY
                            t.target_end_date DESC NULLS LAST,
                            t.id DESC,
                            COALESCE(rel.employee_id, t.employee_id)
                    ) AS id,
                    t.id AS task_id,
                    t.analytic_account_id AS analytic_account_id,
                    COALESCE(rel.employee_id, t.employee_id) AS employee_id,
                    t.manager_id AS manager_id,
                    CASE
                        WHEN COALESCE(t.progress, 0) <= 0 THEN 'pending'
                        WHEN COALESCE(t.progress, 0) < 100 THEN 'in_process'
                        ELSE 'done'
                    END AS status,
                    COALESCE(t.progress, 0)::double precision AS progress_pct,
                    1 AS task_count,
                    t.target_start_date AS target_start_date,
                    t.target_end_date AS target_end_date,
                    t.last_update_at AS last_update_at,
                    t.priority AS priority,
                    t.active AS active,
                    t.employee_id AS primary_employee_id,
                    COALESCE(rel.employee_id, t.employee_id) AS assignee_employee_id
                FROM fin_employee_task t
                LEFT JOIN fin_employee_task_assignee_rel rel
                    ON rel.task_id = t.id
            )
            """
        )
