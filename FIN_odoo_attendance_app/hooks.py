# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def _safe_unlink(env, xmlid):
    record = env.ref(xmlid, raise_if_not_found=False)
    if record and record.exists():
        record.unlink()


def post_init_cleanup_transfer_actions(env_or_cr, registry=None):
    """
    Accept both Odoo 18 signature (cr, registry) and Odoo 19 signature (env).
    """
    if registry is None and hasattr(env_or_cr, 'registry'):
        env = env_or_cr
    else:
        env = api.Environment(env_or_cr, SUPERUSER_ID, {})
    _safe_unlink(env, 'odoo_attendance_app.action_attendance_timesheet_transfer_wizard')
    _safe_unlink(env, 'odoo_attendance_app.action_attendance_timesheet_transfer_from_list')
    _safe_unlink(env, 'odoo_attendance_app.menu_odoo_attendance_timesheet_transfer')
