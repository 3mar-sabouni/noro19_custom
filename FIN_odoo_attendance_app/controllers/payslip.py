# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

from ..utils import response_helper
from .employee import authenticate_request
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


class PayslipController(http.Controller):
    @http.route(
        '/api/odoo-attendance/payslips',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        cors='*',
    )
    def list_payslips(self, **kwargs):
        """
        List payslips for the authenticated employee.
        Requires hr_payroll to be installed.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            if 'hr.payslip' not in request.env:
                return response_helper.validation_error_response('Payroll is not enabled on this database.')

            limit = int(kwargs.get('limit') or 24)
            offset = int(kwargs.get('offset') or 0)
            limit = max(1, min(limit, 100))
            offset = max(0, offset)

            Payslip = request.env['hr.payslip'].sudo()
            slips = Payslip.search(
                [('employee_id', '=', hr_employee.id)],
                limit=limit,
                offset=offset,
                order='date_to desc, id desc',
            )

            items = []
            for slip in slips:
                items.append(
                    {
                        'id': slip.id,
                        'name': slip.name or slip.number or f'Payslip {slip.id}',
                        'date_from': slip.date_from.isoformat() if slip.date_from else None,
                        'date_to': slip.date_to.isoformat() if slip.date_to else None,
                        'state': getattr(slip, 'state', '') or '',
                    }
                )

            return response_helper.success_response(
                {
                    'items': items,
                    'limit': limit,
                    'offset': offset,
                }
            )
        except Exception as e:
            _logger.exception(f'Error in payslips list: {e}')
            return response_helper.server_error_response('An error occurred')

    @http.route(
        '/api/odoo-attendance/payslips/<int:payslip_id>/pdf',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        cors='*',
    )
    def download_payslip_pdf(self, payslip_id, **kwargs):
        """
        Download a payslip PDF for the authenticated employee.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            if 'hr.payslip' not in request.env:
                return response_helper.validation_error_response('Payroll is not enabled on this database.')

            slip = request.env['hr.payslip'].sudo().browse(payslip_id)
            if not slip.exists() or slip.employee_id.id != hr_employee.id:
                return response_helper.forbidden_response('Payslip not found')

            report_ref = 'hr_payroll.action_report_payslip'
            report = request.env.ref(report_ref, raise_if_not_found=False)
            if not report:
                return response_helper.server_error_response('Payslip report is not available.')

            pdf_content, _content_type = report.sudo()._render_qweb_pdf(report_ref, res_ids=[slip.id])
            filename = (slip.name or slip.number or f'payslip_{slip.id}').replace('/', '-') + '.pdf'
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'attachment; filename=\"{filename}\"'),
            ]
            return request.make_response(pdf_content, headers=headers)
        except Exception as e:
            _logger.exception(f'Error in payslip pdf: {e}')
            return response_helper.server_error_response('An error occurred')

