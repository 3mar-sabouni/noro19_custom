# -*- coding: utf-8 -*-
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
import psycopg2
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError


_logger = logging.getLogger(__name__)

# Minimum time between license refresh attempts (prevents hammering the license server).
# Lower this if you want configuration changes (e.g., fixing an invalid license) to take effect faster.
LICENSE_REFRESH_MIN_INTERVAL_SECONDS = 30


def _utcnow():
    # Odoo expects naive datetimes for fields.Datetime (UTC stored without tzinfo).
    return datetime.utcnow()


def _parse_dt(value):
    if not value:
        return None
    try:
        # Accept ISO8601, with or without timezone
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            # Treat naive timestamps as UTC
            return dt
        # Convert to UTC and drop tzinfo (naive UTC)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _format_dt(dt):
    if not dt:
        return ''
    # Store as ISO8601 Zulu; treat naive datetimes as UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _get_icp(env):
    return env['ir.config_parameter'].sudo()


def get_db_uuid(env):
    return _get_icp(env).get_param('database.uuid', default='') or ''


def get_base_url(env):
    return (_get_icp(env).get_param('web.base.url', default='') or '').strip()


def get_module_version(env):
    try:
        mod = env['ir.module.module'].sudo().search([('name', '=', 'odoo_attendance_app')], limit=1)
        return (mod.latest_version or mod.installed_version or '').strip()
    except Exception:
        return ''


def get_employee_count(env):
    return env['odoo.attendance.employee'].sudo().search_count([('is_active', '=', True)])


def get_license_config(env):
    icp = _get_icp(env)
    return {
        'license_key': (icp.get_param('odoo_attendance_app.license_key', default='') or '').strip(),
        'license_server_url': (icp.get_param('odoo_attendance_app.license_server_url', default='') or '').strip(),
        'grace_days': int(icp.get_param('odoo_attendance_app.license_grace_days', default='7') or 7),
    }


def get_cached_license_state(env):
    icp = _get_icp(env)
    valid_until = _parse_dt(icp.get_param('odoo_attendance_app.license_valid_until', default='') or '')
    employee_limit_raw = icp.get_param('odoo_attendance_app.license_employee_limit', default='')
    try:
        employee_limit = int(employee_limit_raw) if employee_limit_raw not in (None, '') else None
    except Exception:
        employee_limit = None
    status = (icp.get_param('odoo_attendance_app.license_status', default='unconfigured') or 'unconfigured').strip()
    last_error = icp.get_param('odoo_attendance_app.license_last_error', default='') or ''
    last_check = _parse_dt(icp.get_param('odoo_attendance_app.license_last_check', default='') or '')
    return {
        'status': status,
        'valid_until': valid_until,
        'employee_limit': employee_limit,
        'last_error': last_error,
        'last_check': last_check,
    }


def get_cached_license_token(env):
    icp = _get_icp(env)
    return (icp.get_param('odoo_attendance_app.license_token', default='') or '').strip()


def _set_cached_license_state(
    env,
    *,
    status=None,
    valid_until=None,
    employee_limit=None,
    last_error=None,
    last_check=None,
    license_token=None,
    clear_valid_until=False,
):
    icp = _get_icp(env)

    def _safe_set_param(key, value):
        # Avoid aborting requests when ICP rows are updated concurrently.
        for attempt in range(2):
            try:
                with env.cr.savepoint():
                    icp.set_param(key, value)
                return
            except psycopg2.errors.SerializationFailure:
                _logger.warning('License cache update conflict on %s (attempt %s).', key, attempt + 1)
        _logger.warning('License cache update skipped for %s after retries.', key)

    if status is not None:
        _safe_set_param('odoo_attendance_app.license_status', status)
    if clear_valid_until:
        _safe_set_param('odoo_attendance_app.license_valid_until', '')
    if valid_until is not None:
        _safe_set_param('odoo_attendance_app.license_valid_until', _format_dt(valid_until))
    if employee_limit is not None:
        _safe_set_param('odoo_attendance_app.license_employee_limit', str(employee_limit))
    if last_error is not None:
        _safe_set_param('odoo_attendance_app.license_last_error', last_error)
    if last_check is not None:
        _safe_set_param('odoo_attendance_app.license_last_check', _format_dt(last_check))
    if license_token is not None:
        _safe_set_param('odoo_attendance_app.license_token', license_token)


def _post_json(url, payload, timeout_seconds=10):
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        return json.loads(raw.decode('utf-8'))


def refresh_license_from_server(env):
    """
    Contacts your licensing server and refreshes cached license state.
    Expected response (example):
      {
        "success": true,
        "data": {
          "status": "active",
          "employee_limit": 50,
          "valid_until": "2026-01-31T00:00:00Z",
          "license_token": "eyJ..." // optional signed token (JWT/JWS) for the mobile app
        }
      }
    """
    cfg = get_license_config(env)
    license_key = cfg['license_key']
    server_url = cfg['license_server_url']

    if not license_key:
        _set_cached_license_state(
            env,
            status='unconfigured',
            last_error='Missing license key',
            last_check=_utcnow(),
            license_token='',
            clear_valid_until=True,
        )
        return False, 'Missing license key'

    if not server_url:
        _set_cached_license_state(
            env,
            status='unconfigured',
            last_error='Missing license server URL',
            last_check=_utcnow(),
            license_token='',
            clear_valid_until=True,
        )
        return False, 'Missing license server URL'

    db_uuid = get_db_uuid(env)
    employee_count = get_employee_count(env)
    base_url = get_base_url(env)
    module_version = get_module_version(env)

    try:
        resp = _post_json(
            server_url.rstrip('/') + '/v1/licenses/check',
            {
                'license_key': license_key,
                'db_uuid': db_uuid,
                'employee_count': employee_count,
                'base_url': base_url,
                'module_version': module_version,
            },
            timeout_seconds=15,
        )
    except HTTPError as e:
        msg = f'License server HTTP error: {e.code}'
        _set_cached_license_state(env, status='error', last_error=msg, last_check=_utcnow(), license_token='')
        _logger.warning(msg)
        return False, msg
    except URLError as e:
        msg = f'License server unreachable: {e}'
        _set_cached_license_state(env, status='error', last_error=msg, last_check=_utcnow(), license_token='')
        _logger.warning(msg)
        return False, msg
    except Exception as e:
        msg = f'License check failed: {e}'
        _set_cached_license_state(env, status='error', last_error=msg, last_check=_utcnow(), license_token='')
        _logger.exception(msg)
        return False, msg

    if not isinstance(resp, dict) or not resp.get('success'):
        msg = (resp.get('error') if isinstance(resp, dict) else None) or 'Invalid response from license server'
        # If the license is invalid, immediately clear any previously cached signed token
        # so the mobile app can't keep working with stale data.
        _set_cached_license_state(
            env,
            status='error',
            last_error=msg,
            last_check=_utcnow(),
            license_token='',
            clear_valid_until=True,
        )
        return False, msg

    data = resp.get('data') or {}
    status = (data.get('status') or 'error').strip()
    employee_limit = data.get('employee_limit')
    valid_until = _parse_dt(data.get('valid_until'))
    license_token = (data.get('license_token') or data.get('token') or '').strip()

    if employee_limit is None:
        employee_limit = 0
    try:
        employee_limit = int(employee_limit)
    except Exception:
        employee_limit = 0

    if not valid_until:
        # If server doesn't provide, consider invalid
        _set_cached_license_state(
            env,
            status='error',
            employee_limit=employee_limit,
            last_error='Missing valid_until',
            last_check=_utcnow(),
            license_token='',
            clear_valid_until=True,
        )
        return False, 'Missing valid_until'

    _set_cached_license_state(
        env,
        status=status,
        employee_limit=employee_limit,
        valid_until=valid_until,
        last_error='',
        last_check=_utcnow(),
        license_token=license_token,
    )
    return True, ''


def is_subscription_active(env, *, allow_refresh=True):
    """
    Returns (ok: bool, message: str).
    Applies 7-day grace window after valid_until.
    Also enforces employee_limit against active mobile app employees.
    """
    cfg = get_license_config(env)
    grace_days = max(int(cfg.get('grace_days') or 7), 0)
    now = _utcnow()

    cached = get_cached_license_state(env)
    valid_until = cached['valid_until']
    status = cached['status']
    employee_limit = cached['employee_limit']
    last_check = cached['last_check']

    if not cfg['license_key'] or not cfg['license_server_url']:
        return False, 'Subscription is not configured. Please contact your administrator.'

    if status in ('revoked', 'blocked'):
        return False, 'Subscription is blocked. Please contact your administrator.'

    # If we have no cached state (or previous error), attempt refresh once.
    if allow_refresh and (not valid_until or status in ('unconfigured', 'error')):
        should_refresh = (last_check is None) or (now - last_check > timedelta(seconds=LICENSE_REFRESH_MIN_INTERVAL_SECONDS))
        if should_refresh:
            refresh_license_from_server(env)
            cached = get_cached_license_state(env)
            valid_until = cached['valid_until']
            status = cached['status']
            employee_limit = cached['employee_limit']
            last_check = cached['last_check']

    # If the last refresh yielded an error or an unconfigured state, fail closed.
    # This prevents the app from continuing to work on a stale cached valid_until/token
    # after the customer replaces the license key with an invalid one.
    if status in ('unconfigured', 'error'):
        return False, 'Subscription verification failed. Please contact your administrator.'

    if not valid_until:
        return False, 'Subscription verification failed. Please contact your administrator.'

    grace_until = valid_until + timedelta(days=grace_days)
    if now > grace_until:
        # If the license was just renewed on the server, the cache might still be stale.
        # Refresh at most once per few minutes when we're already considered expired.
        if allow_refresh:
            should_refresh = (last_check is None) or (now - last_check > timedelta(seconds=LICENSE_REFRESH_MIN_INTERVAL_SECONDS))
            if should_refresh:
                refresh_license_from_server(env)
                cached = get_cached_license_state(env)
                valid_until = cached['valid_until']
                employee_limit = cached['employee_limit']
                last_check = cached['last_check']
                if valid_until:
                    grace_until = valid_until + timedelta(days=grace_days)
                    if now <= grace_until:
                        # Renewal detected; continue checks below.
                        pass
                    else:
                        return False, 'Subscription expired. Please renew and try again.'
                else:
                    return False, 'Subscription verification failed. Please contact your administrator.'
            else:
                return False, 'Subscription expired. Please renew and try again.'
        else:
            return False, 'Subscription expired. Please renew and try again.'

    # Enforce employee limit (0 means unlimited)
    if employee_limit is None:
        employee_limit = 0
    if employee_limit > 0:
        employee_count = get_employee_count(env)
        if employee_count > employee_limit:
            return False, f'Subscription limit reached ({employee_limit} employees). Please upgrade your plan.'

    return True, ''


def get_signed_license_token(env, *, allow_refresh=True):
    """
    Returns (token: str|None, message: str).

    The token is expected to be issued (signed) by the external license server and cached
    in system parameters under `odoo_attendance_app.license_token`.
    """
    ok, msg = is_subscription_active(env, allow_refresh=allow_refresh)
    if not ok:
        return None, msg

    token = get_cached_license_token(env)
    if token and not _is_license_token_expired(token):
        return token, ''
    if token:
        # Clear an expired/invalid token so we don't keep returning it.
        _set_cached_license_state(env, license_token='')

    if allow_refresh:
        refresh_license_from_server(env)
        token = get_cached_license_token(env)
        if token and not _is_license_token_expired(token):
            return token, ''
        if token:
            _set_cached_license_state(env, license_token='')

    return None, 'License token is missing or expired. Please contact your administrator.'


def _is_license_token_expired(token, *, skew_seconds=120):
    """
    Best-effort check for JWT expiry (without verifying the signature).

    Returns allowing a token that's close to expiry can lead to the mobile app failing shortly after.
    We treat tokens expiring within `skew_seconds` as expired to force refresh.
    """
    payload = _try_decode_jwt_payload(token)
    if not payload:
        return True

    exp = payload.get('exp')
    if exp is None:
        return True

    try:
        exp = int(exp)
    except Exception:
        return True

    now_ts = int(datetime.utcnow().timestamp())
    return now_ts >= (exp - int(skew_seconds))


def _try_decode_jwt_payload(token):
    """
    Decodes JWT payload as a dict without validating the signature.
    Returns None if token is not a JWT or payload can't be parsed.
    """
    try:
        parts = (token or '').split('.')
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        payload_raw = _b64url_decode(payload_b64)
        return json.loads(payload_raw.decode('utf-8'))
    except Exception:
        return None


def _b64url_decode(data):
    if not data:
        return b''
    # Base64url padding
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
