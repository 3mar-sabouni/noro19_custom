# -*- coding: utf-8 -*-
from odoo.http import request
from ..utils import license_helper, response_helper


def require_active_subscription():
    """
    Returns an Odoo Response if subscription is not valid, otherwise None.
    """
    ok, msg = license_helper.is_subscription_active(request.env, allow_refresh=True)
    if ok:
        return None
    return response_helper.payment_required_response(msg or 'Subscription required')

