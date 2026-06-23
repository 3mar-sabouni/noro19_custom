# -*- coding: utf-8 -*-
import logging
from odoo import http, fields
from odoo.http import request, Response
from .employee import authenticate_request
from ..utils import response_helper
from .subscription import require_active_subscription

_logger = logging.getLogger(__name__)


def _build_analytic_access_domain(hr_employee):
    return [
        ('active', '=', True),
    ]


def _fetch_analytic_accounts(env, hr_employee, search_query, limit):
    AnalyticAccount = env['account.analytic.account'].sudo()
    domain = _build_analytic_access_domain(hr_employee)
    if search_query:
        domain.extend(['|', ('name', 'ilike', search_query), ('code', 'ilike', search_query)])
    limit_value = limit or False
    accounts = AnalyticAccount.search(domain, limit=limit_value, order='name')
    return accounts


def _serialize_analytic_accounts(accounts):
    return [
        {
            'id': account.id,
            'name': f'[{(account.code or str(account.id)).strip()}] {account.name}'
            if account.name
            else f'[{(account.code or str(account.id)).strip()}]',
            'code': account.code or '',
            'source': 'analytic_account',
        }
        for account in accounts
    ]


def _build_etag_for_accounts(accounts):
    if not accounts:
        return 'W/"0"'
    max_write = max(accounts.mapped('write_date')) if accounts else None
    max_write_str = fields.Datetime.to_string(max_write) if max_write else '0'
    return f'W/"{len(accounts)}-{max_write_str}"'

class AnalyticsController(http.Controller):
    """
    Analytic account search endpoints.
    """
    
    @http.route('/api/odoo-attendance/analytics/search', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def search_analytics(self, **kwargs):
        """
        Search analytic accounts filtered by employee access.
        
        GET /api/odoo-attendance/analytics/search?q=project&limit=20
        Authorization: Bearer <access_token>
        
        Query parameters:
        - q: search query (optional)
        - limit: max results (default 20)
        
        Response:
        {
            "success": true,
            "data": [
                {"id": 1, "name": "Project Alpha", "code": "PA001"},
                ...
            ]
        }
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            # Authenticate
            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')
            
            employee_app, hr_employee = auth_result
            
            # Get query parameters
            search_query = request.params.get('q', '').strip()
            limit = int(request.params.get('limit', 0))
            
            # Search analytic accounts
            accounts = _fetch_analytic_accounts(request.env, hr_employee, search_query, limit)
            results = _serialize_analytic_accounts(accounts)

            return response_helper.success_response(results)

        except Exception as e:
            _logger.exception(f'Error in search_analytics endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

    @http.route('/api/odoo-attendance/analytics/sync', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def sync_analytics(self, **kwargs):
        """
        Sync analytic accounts for offline cache.

        GET /api/odoo-attendance/analytics/sync
        Optional query params:
        - limit: max results (default 0 = no limit)

        Supports If-None-Match / ETag for lightweight caching.
        """
        try:
            sub_resp = require_active_subscription()
            if sub_resp:
                return sub_resp

            auth_result = authenticate_request()
            if not auth_result:
                return response_helper.unauthorized_response('Invalid or missing authentication token')

            _employee_app, hr_employee = auth_result

            limit = int(request.params.get('limit', 0))

            accounts = _fetch_analytic_accounts(request.env, hr_employee, '', limit)
            etag = _build_etag_for_accounts(accounts)

            if_none_match = request.httprequest.headers.get('If-None-Match')
            if if_none_match and etag and if_none_match == etag:
                return Response(status=304, headers={'ETag': etag})

            results = _serialize_analytic_accounts(accounts)
            resp = response_helper.success_response({'results': results})
            if etag:
                resp.headers['ETag'] = etag
            return resp

        except Exception as e:
            _logger.exception(f'Error in sync_analytics endpoint: {str(e)}')
            return response_helper.server_error_response('An error occurred')

