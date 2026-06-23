# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

from odoo import http
from odoo.http import request

from ..utils import response_helper
from .employee import authenticate_request
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


class ExpenseController(http.Controller):
    EXPENSE_LABELS = {
        'draft': 'To Report',
        'reported': 'To Submit',
        'submit': 'Submitted',
        'approve': 'Approved',
        'done': 'Done',
        'refused': 'Refused',
        'cancel': 'Cancelled',
    }

    REPORT_LABELS = {
        'draft': 'To Submit',
        'submit': 'Submitted',
        'approve': 'Approved',
        'done': 'Done',
        'cancel': 'Cancelled',
    }

    def _auth(self):
        sub = require_active_subscription()
        if sub:
            return None, sub
        auth = authenticate_request()
        if not auth:
            return None, response_helper.unauthorized_response('Invalid or missing authentication token')
        return auth[1], None

    def _body(self):
        try:
            data = json.loads(request.httprequest.data or '{}')
            return data if isinstance(data, dict) else {}
        except Exception:
            return None

    def _to_int(self, value, default=None):
        try:
            return default if value in (None, '') else int(value)
        except Exception:
            return default

    def _to_float(self, value, default=None):
        try:
            return default if value in (None, '') else float(value)
        except Exception:
            return default

    def _to_date(self, value):
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').date() if value else None
        except Exception:
            return None

    def _sheet_field(self):
        model = request.env['hr.expense']
        return 'sheet_id' if 'sheet_id' in model._fields else ('expense_sheet_id' if 'expense_sheet_id' in model._fields else None)

    def _line_field(self):
        if 'hr.expense.sheet' not in request.env:
            return None
        model = request.env['hr.expense.sheet']
        return 'expense_line_ids' if 'expense_line_ids' in model._fields else ('expense_line_id' if 'expense_line_id' in model._fields else None)

    def _label(self, state, map_values):
        return map_values.get(state or '', (state or '').replace('_', ' ').title())

    def _expense_json(self, rec, with_attachments=False):
        amount = float(getattr(rec, 'total_amount', 0.0) or getattr(rec, 'total', 0.0) or 0.0)
        sheet_name = self._sheet_field()
        sheet = getattr(rec, sheet_name) if sheet_name else False
        payload = {
            'id': rec.id,
            'name': rec.name or '',
            'description': rec.description if 'description' in rec._fields else '',
            'date': rec.date.isoformat() if rec.date else None,
            'state': rec.state or '',
            'state_label': self._label(rec.state, self.EXPENSE_LABELS),
            'total_amount': round(amount, 2),
            'payment_mode': rec.payment_mode if 'payment_mode' in rec._fields else '',
            'can_edit': (rec.state or '') in ('draft', 'refused'),
            'can_delete': (rec.state or '') in ('draft', 'refused'),
            'product': {'id': rec.product_id.id, 'name': rec.product_id.display_name or rec.product_id.name or ''} if rec.product_id else None,
            'report': {'id': sheet.id, 'name': sheet.name or '', 'state': sheet.state or '', 'state_label': self._label(sheet.state, self.REPORT_LABELS)} if sheet else None,
        }
        if with_attachments:
            atts = request.env['ir.attachment'].sudo().search([('res_model', '=', 'hr.expense'), ('res_id', '=', rec.id)], order='id desc')
            payload['attachments'] = [{'id': a.id, 'name': a.name or '', 'mimetype': a.mimetype or '', 'url': f'/web/content/{a.id}?download=true'} for a in atts]
        return payload

    def _report_json(self, rec, with_lines=False):
        total = float(getattr(rec, 'total_amount', 0.0) or getattr(rec, 'total_amount_currency', 0.0) or getattr(rec, 'amount_total', 0.0) or 0.0)
        payload = {
            'id': rec.id,
            'name': rec.name or f'Expense Report {rec.id}',
            'state': rec.state or '',
            'state_label': self._label(rec.state, self.REPORT_LABELS),
            'total_amount': round(total, 2),
            'can_submit': (rec.state or '') == 'draft',
        }
        if with_lines:
            line_field = self._line_field()
            lines = getattr(rec, line_field) if line_field else request.env['hr.expense'].browse()
            payload['expenses'] = [self._expense_json(x, with_attachments=False) for x in lines]
            payload['expense_count'] = len(lines)
        return payload

    def _my_expense(self, expense_id, employee):
        rec = request.env['hr.expense'].sudo().browse(expense_id)
        if not rec.exists():
            return None
        if rec.employee_id.id != employee.id:
            return False
        return rec

    def _expense_vals(self, data, employee, for_update=False):
        Expense = request.env['hr.expense']
        vals = {}
        name = (data.get('name') or '').strip()
        if name:
            vals['name'] = name
        elif not for_update:
            raise ValueError('Missing required field: name')
        if 'employee_id' in Expense._fields and not for_update:
            vals['employee_id'] = employee.id
        if data.get('date') is not None:
            dt = self._to_date(data.get('date'))
            if not dt:
                raise ValueError('Invalid date format. Use YYYY-MM-DD')
            vals['date'] = dt
        if 'total_amount' in data:
            amt = self._to_float(data.get('total_amount'))
            if amt is None or amt < 0:
                raise ValueError('total_amount must be a positive number.')
            if 'total_amount' in Expense._fields:
                vals['total_amount'] = amt
            if 'unit_amount' in Expense._fields:
                vals['unit_amount'] = amt
            if 'quantity' in Expense._fields and not for_update:
                vals['quantity'] = 1.0
        if data.get('product_id'):
            vals['product_id'] = self._to_int(data.get('product_id'))
        if data.get('description') and 'description' in Expense._fields:
            vals['description'] = str(data.get('description')).strip()
        if data.get('payment_mode') and 'payment_mode' in Expense._fields:
            vals['payment_mode'] = str(data.get('payment_mode')).strip()
        if data.get('analytic_account_id') and 'analytic_distribution' in Expense._fields:
            aid = self._to_int(data.get('analytic_account_id'))
            if aid:
                vals['analytic_distribution'] = {str(aid): 100.0}
        return vals

    @http.route('/api/odoo-attendance/expenses/meta', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def expenses_meta(self, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense' not in request.env:
                return response_helper.validation_error_response('Expenses module is not enabled on this database.')
            Product = request.env['product.product'].sudo()
            domain = [('can_be_expensed', '=', True)] if 'can_be_expensed' in Product._fields else []
            products = Product.search(domain, limit=250, order='name asc')
            Analytic = request.env['account.analytic.account'].sudo()
            analytics = Analytic.search([('active', '=', True)] if 'active' in Analytic._fields else [], limit=250, order='name asc')
            payment_modes = []
            field = request.env['hr.expense']._fields.get('payment_mode')
            selection = field.selection(request.env['hr.expense']) if field and callable(field.selection) else (field.selection if field else [])
            for v, l in (selection or []):
                payment_modes.append({'value': v, 'label': str(l or v)})
            return response_helper.success_response({
                'categories': [{'id': p.id, 'name': p.display_name or p.name or ''} for p in products],
                'analytic_accounts': [{'id': a.id, 'name': a.name or '', 'code': a.code or ''} for a in analytics],
                'payment_modes': payment_modes,
                'currency': {'id': employee.company_id.currency_id.id, 'name': employee.company_id.currency_id.name or '', 'symbol': employee.company_id.currency_id.symbol or ''} if employee.company_id and employee.company_id.currency_id else None,
            })
        except Exception as e:
            _logger.exception('expenses_meta failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expenses', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def list_expenses(self, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense' not in request.env:
                return response_helper.validation_error_response('Expenses module is not enabled on this database.')
            Expense = request.env['hr.expense'].sudo()
            limit = max(1, min(self._to_int(request.params.get('limit'), 50), 200))
            offset = max(0, self._to_int(request.params.get('offset'), 0))
            domain = [('employee_id', '=', employee.id)]
            state = (request.params.get('state') or '').strip()
            if state:
                states = [s.strip() for s in state.split(',') if s.strip()]
                domain.append(('state', 'in', states))
            rows = Expense.search(domain, order='date desc, id desc', limit=limit, offset=offset)
            return response_helper.success_response({'items': [self._expense_json(r) for r in rows], 'limit': limit, 'offset': offset, 'total': Expense.search_count(domain)})
        except Exception as e:
            _logger.exception('list_expenses failed: %s', e)
            return response_helper.server_error_response('An error occurred')
    @http.route('/api/odoo-attendance/expenses/<int:expense_id>', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_expense(self, expense_id, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense' not in request.env:
                return response_helper.validation_error_response('Expenses module is not enabled on this database.')
            rec = self._my_expense(expense_id, employee)
            if rec is None:
                return response_helper.not_found_response('Expense not found')
            if rec is False:
                return response_helper.forbidden_response('You can only access your own expenses.')
            return response_helper.success_response(self._expense_json(rec, with_attachments=True))
        except Exception as e:
            _logger.exception('get_expense failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expenses', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_expense(self, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense' not in request.env:
                return response_helper.validation_error_response('Expenses module is not enabled on this database.')
            data = self._body()
            if data is None:
                return response_helper.validation_error_response('Invalid JSON in request body')
            try:
                vals = self._expense_vals(data, employee, for_update=False)
            except ValueError as ve:
                return response_helper.validation_error_response(str(ve))
            rec = request.env['hr.expense'].sudo().create(vals)
            for receipt in (data.get('receipts') or []):
                if not isinstance(receipt, dict):
                    continue
                raw = (receipt.get('base64') or '').strip()
                if raw.lower().startswith('data:') and ',' in raw:
                    raw = raw.split(',', 1)[1]
                if not raw:
                    continue
                request.env['ir.attachment'].sudo().create({
                    'name': receipt.get('name') or f'Receipt_{rec.id}.jpg',
                    'type': 'binary',
                    'datas': raw,
                    'mimetype': receipt.get('mimetype') or 'image/jpeg',
                    'res_model': 'hr.expense',
                    'res_id': rec.id,
                })
            return response_helper.success_response(self._expense_json(rec, with_attachments=True), message='Expense created successfully')
        except Exception as e:
            _logger.exception('create_expense failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expenses/<int:expense_id>', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def update_expense(self, expense_id, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            data = self._body()
            if data is None:
                return response_helper.validation_error_response('Invalid JSON in request body')
            rec = self._my_expense(expense_id, employee)
            if rec is None:
                return response_helper.not_found_response('Expense not found')
            if rec is False:
                return response_helper.forbidden_response('You can only update your own expenses.')
            if (rec.state or '') not in ('draft', 'refused'):
                return response_helper.forbidden_response('Only draft/refused expenses can be edited.')
            try:
                vals = self._expense_vals(data, employee, for_update=True)
            except ValueError as ve:
                return response_helper.validation_error_response(str(ve))
            if vals:
                rec.write(vals)
            remove_ids = [rid for rid in (self._to_int(x) for x in (data.get('remove_receipt_ids') or [])) if rid]
            if remove_ids:
                request.env['ir.attachment'].sudo().search([
                    ('id', 'in', remove_ids), ('res_model', '=', 'hr.expense'), ('res_id', '=', rec.id)
                ]).unlink()
            for receipt in (data.get('receipts') or []):
                if not isinstance(receipt, dict):
                    continue
                raw = (receipt.get('base64') or '').strip()
                if raw.lower().startswith('data:') and ',' in raw:
                    raw = raw.split(',', 1)[1]
                if not raw:
                    continue
                request.env['ir.attachment'].sudo().create({
                    'name': receipt.get('name') or f'Receipt_{rec.id}.jpg',
                    'type': 'binary',
                    'datas': raw,
                    'mimetype': receipt.get('mimetype') or 'image/jpeg',
                    'res_model': 'hr.expense',
                    'res_id': rec.id,
                })
            return response_helper.success_response(self._expense_json(rec, with_attachments=True), message='Expense updated successfully')
        except Exception as e:
            _logger.exception('update_expense failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expenses/<int:expense_id>/delete', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def delete_expense(self, expense_id, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            rec = self._my_expense(expense_id, employee)
            if rec is None:
                return response_helper.not_found_response('Expense not found')
            if rec is False:
                return response_helper.forbidden_response('You can only delete your own expenses.')
            if (rec.state or '') not in ('draft', 'refused'):
                return response_helper.forbidden_response('Only draft/refused expenses can be deleted.')
            rec.unlink()
            return response_helper.success_response(message='Expense deleted successfully')
        except Exception as e:
            _logger.exception('delete_expense failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expenses/<int:expense_id>/receipts', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def add_receipt(self, expense_id, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            data = self._body()
            if data is None:
                return response_helper.validation_error_response('Invalid JSON in request body')
            rec = self._my_expense(expense_id, employee)
            if rec is None:
                return response_helper.not_found_response('Expense not found')
            if rec is False:
                return response_helper.forbidden_response('You can only update your own expenses.')
            if (rec.state or '') not in ('draft', 'refused'):
                return response_helper.forbidden_response('Only draft/refused expenses can be edited.')
            raw = (data.get('base64') or '').strip()
            if raw.lower().startswith('data:') and ',' in raw:
                raw = raw.split(',', 1)[1]
            if not raw:
                return response_helper.validation_error_response('Missing receipt base64 data.')
            att = request.env['ir.attachment'].sudo().create({
                'name': data.get('name') or f'Receipt_{rec.id}.jpg',
                'type': 'binary',
                'datas': raw,
                'mimetype': data.get('mimetype') or 'image/jpeg',
                'res_model': 'hr.expense',
                'res_id': rec.id,
            })
            return response_helper.success_response({'id': att.id, 'name': att.name or '', 'mimetype': att.mimetype or '', 'url': f'/web/content/{att.id}?download=true'}, message='Receipt uploaded successfully')
        except Exception as e:
            _logger.exception('add_receipt failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expenses/<int:expense_id>/receipts/<int:attachment_id>/remove', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def remove_receipt(self, expense_id, attachment_id, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            rec = self._my_expense(expense_id, employee)
            if rec is None:
                return response_helper.not_found_response('Expense not found')
            if rec is False:
                return response_helper.forbidden_response('You can only update your own expenses.')
            if (rec.state or '') not in ('draft', 'refused'):
                return response_helper.forbidden_response('Only draft/refused expenses can be edited.')
            att = request.env['ir.attachment'].sudo().search([
                ('id', '=', attachment_id), ('res_model', '=', 'hr.expense'), ('res_id', '=', rec.id)
            ], limit=1)
            if not att:
                return response_helper.not_found_response('Receipt not found')
            att.unlink()
            return response_helper.success_response(message='Receipt removed successfully')
        except Exception as e:
            _logger.exception('remove_receipt failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expense-reports', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def list_reports(self, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense.sheet' not in request.env:
                return response_helper.validation_error_response('Expense reports are not enabled on this database.')
            Sheet = request.env['hr.expense.sheet'].sudo()
            limit = max(1, min(self._to_int(request.params.get('limit'), 50), 200))
            offset = max(0, self._to_int(request.params.get('offset'), 0))
            domain = [('employee_id', '=', employee.id)]
            state = (request.params.get('state') or '').strip()
            if state:
                domain.append(('state', 'in', [s.strip() for s in state.split(',') if s.strip()]))
            rows = Sheet.search(domain, order='id desc', limit=limit, offset=offset)
            return response_helper.success_response({'items': [self._report_json(r, with_lines=True) for r in rows], 'limit': limit, 'offset': offset, 'total': Sheet.search_count(domain)})
        except Exception as e:
            _logger.exception('list_reports failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expense-reports', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_report(self, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense' not in request.env or 'hr.expense.sheet' not in request.env:
                return response_helper.validation_error_response('Expenses module is not enabled on this database.')
            data = self._body()
            if data is None:
                return response_helper.validation_error_response('Invalid JSON in request body')
            raw_ids = data.get('expense_ids')
            if not isinstance(raw_ids, list) or not raw_ids:
                return response_helper.validation_error_response('expense_ids is required and must be a non-empty array.')
            ids = [x for x in (self._to_int(v) for v in raw_ids) if x]
            Expense = request.env['hr.expense'].sudo()
            expenses = Expense.search([('id', 'in', ids), ('employee_id', '=', employee.id)])
            if len(expenses) != len(set(ids)):
                return response_helper.forbidden_response('Some expenses were not found or do not belong to you.')
            bad = expenses.filtered(lambda x: (x.state or '') not in ('draft', 'refused'))
            if bad:
                return response_helper.forbidden_response('Only draft/refused expenses can be added to a report.')
            if hasattr(expenses, 'action_submit_expenses'):
                expenses.action_submit_expenses()
            sheet_name = self._sheet_field()
            sheet_ids = [s.id for s in expenses.mapped(sheet_name)] if sheet_name else []
            sheet_ids = [sid for sid in sheet_ids if sid]
            Sheet = request.env['hr.expense.sheet'].sudo()
            if not sheet_ids:
                line_field = self._line_field()
                if not line_field:
                    return response_helper.server_error_response('Unable to determine expense report line field.')
                report = Sheet.create({'name': (data.get('name') or '').strip() or f'Expense Report {employee.name or employee.id}', 'employee_id': employee.id, line_field: [(6, 0, expenses.ids)]})
                sheet_ids = [report.id]
                if sheet_name and sheet_name in Expense._fields:
                    expenses.write({sheet_name: report.id})
            reports = Sheet.browse(sheet_ids)
            custom_name = (data.get('name') or '').strip()
            if custom_name and len(reports) == 1 and 'name' in reports._fields:
                reports[0].write({'name': custom_name})
            return response_helper.success_response({'reports': [self._report_json(r, with_lines=True) for r in reports]}, message='Expense report created successfully')
        except Exception as e:
            _logger.exception('create_report failed: %s', e)
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/expense-reports/<int:report_id>/submit', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def submit_report(self, report_id, **kwargs):
        try:
            employee, auth_resp = self._auth()
            if auth_resp:
                return auth_resp
            if 'hr.expense.sheet' not in request.env:
                return response_helper.validation_error_response('Expense reports are not enabled on this database.')
            Sheet = request.env['hr.expense.sheet'].sudo()
            rec = Sheet.browse(report_id)
            if not rec.exists():
                return response_helper.not_found_response('Expense report not found')
            if rec.employee_id.id != employee.id:
                return response_helper.forbidden_response('You can only submit your own expense reports.')
            method = None
            for candidate in ('action_submit_sheet', 'action_submit_expenses', 'action_submit'):
                if hasattr(rec, candidate):
                    method = candidate
                    break
            if not method:
                return response_helper.server_error_response('Expense report submission is not available.')
            getattr(rec, method)()
            return response_helper.success_response(self._report_json(rec, with_lines=True), message='Expense report submitted successfully')
        except Exception as e:
            _logger.exception('submit_report failed: %s', e)
            return response_helper.server_error_response('An error occurred')
