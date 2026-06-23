# -*- coding: utf-8 -*-
import base64
import json
import logging
import time
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from . import license_helper

_logger = logging.getLogger(__name__)
_FCM_PARAM_PREFIXES = (
    'odoo_attendance_app',
    'FIN_odoo_attendance_app',
    'fin_odoo_attendance_app',
)


def _get_fcm_param(env, suffix):
    icp = env['ir.config_parameter'].sudo()
    for prefix in _FCM_PARAM_PREFIXES:
        key = f'{prefix}.{suffix}'
        val = (icp.get_param(key, default='') or '').strip()
        if val:
            return val
    return ''

def _sanitize_fcm_data_key(key: str) -> str:
    """
    FCM HTTP v1 can reject some data payload keys (seen with underscores).
    Keep keys simple to maximize compatibility across devices/SDKs.
    """
    if not key:
        return ''

    normalized = str(key).strip().replace('_', '-')
    safe_chars = []
    for ch in normalized:
        if ('a' <= ch <= 'z') or ('A' <= ch <= 'Z') or ('0' <= ch <= '9') or ch == '-':
            safe_chars.append(ch)
        else:
            safe_chars.append('-')

    compacted = ''.join(safe_chars)
    while '--' in compacted:
        compacted = compacted.replace('--', '-')
    compacted = compacted.strip('-')
    return compacted


def get_fcm_server_key(env):
    return _get_fcm_param(env, 'fcm_server_key')

def _get_fcm_project_id(env):
    return _get_fcm_param(env, 'fcm_project_id')

def _get_fcm_service_account_json(env):
    return _get_fcm_param(env, 'fcm_service_account_json')

def _post_json(url, payload, headers, timeout_seconds=15):
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        url,
        data=data,
        headers=headers,
        method='POST',
    )
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        return resp.getcode(), raw


def _post_form(url, fields, headers=None, timeout_seconds=15):
    body = urlencode(fields).encode('utf-8')
    req = urlrequest.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            **(headers or {}),
        },
        method='POST',
    )
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        return resp.getcode(), raw


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


_ACCESS_TOKEN_CACHE = {
    # key: service_account_client_email, value: {'token': str, 'exp': int(epoch_seconds)}
}


def _get_fcm_v1_access_token(env):
    """
    Returns (token: str|None, error: str|None).

    Uses OAuth2 JWT Bearer flow with the Firebase Admin SDK service account.
    """
    raw_sa = _get_fcm_service_account_json(env)
    if not raw_sa:
        return None, 'FCM service account JSON is not configured'

    try:
        service_account = json.loads(raw_sa)
    except Exception:
        return None, 'Invalid FCM service account JSON'

    client_email = (service_account.get('client_email') or '').strip()
    private_key_pem = (service_account.get('private_key') or '').strip()
    project_id = (_get_fcm_project_id(env) or (service_account.get('project_id') or '')).strip()
    if not client_email or not private_key_pem or not project_id:
        return None, 'FCM service account JSON missing client_email/private_key/project_id'

    now = int(time.time())
    cached = _ACCESS_TOKEN_CACHE.get(client_email) or {}
    if cached.get('token') and int(cached.get('exp') or 0) > now + 60:
        return cached['token'], None

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception:
        return None, 'Missing Python dependency: cryptography (required for FCM HTTP v1)'

    try:
        key = serialization.load_pem_private_key(
            private_key_pem.encode('utf-8'),
            password=None,
        )
    except Exception:
        return None, 'Invalid private_key in service account JSON'

    header = _b64url(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode('utf-8'))
    iat = now
    exp = now + 3600
    claims = {
        'iss': client_email,
        'scope': 'https://www.googleapis.com/auth/firebase.messaging',
        'aud': 'https://oauth2.googleapis.com/token',
        'iat': iat,
        'exp': exp,
    }
    payload = _b64url(json.dumps(claims).encode('utf-8'))
    unsigned = f'{header}.{payload}'.encode('ascii')
    try:
        signature = key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return None, 'Failed to sign OAuth JWT for FCM'

    assertion = f'{header}.{payload}.{_b64url(signature)}'

    try:
        code, raw = _post_form(
            'https://oauth2.googleapis.com/token',
            {
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': assertion,
            },
            timeout_seconds=15,
        )
        if code != 200:
            _logger.warning('FCM v1 token non-200: %s body=%s', code, (raw or b'')[:500])
            return None, 'FCM OAuth token HTTP %s' % code

        data = json.loads((raw or b'{}').decode('utf-8'))
        token = (data.get('access_token') or '').strip()
        expires_in = int(data.get('expires_in') or 3600)
        if not token:
            _logger.warning('FCM v1 token missing access_token body=%s', (raw or b'')[:500])
            return None, 'FCM OAuth token response missing access_token'

        _ACCESS_TOKEN_CACHE[client_email] = {'token': token, 'exp': now + expires_in}
        return token, None
    except HTTPError as e:
        body = b''
        try:
            body = e.read() or b''
        except Exception:
            body = b''
        _logger.warning('FCM v1 token HTTPError: %s body=%s', e, body[:500])
        return None, 'FCM OAuth token HTTP error'
    except URLError as e:
        _logger.warning('FCM v1 token URLError: %s', e)
        return None, 'FCM OAuth token unreachable'
    except Exception as e:
        _logger.warning('FCM v1 token exception: %s', e)
        return None, 'FCM OAuth token exception'


def _send_fcm_push_v1(*, env, token, title, body, data=None, silent=False):
    raw_sa = _get_fcm_service_account_json(env)
    if not raw_sa:
        return False, 'FCM service account JSON is not configured'

    try:
        service_account = json.loads(raw_sa)
    except Exception:
        return False, 'Invalid FCM service account JSON'

    project_id = (_get_fcm_project_id(env) or (service_account.get('project_id') or '')).strip()
    if not project_id:
        return False, 'Missing FCM project_id'

    access_token, err = _get_fcm_v1_access_token(env)
    if not access_token:
        return False, err or 'Missing FCM access token'

    if not token:
        return False, 'Missing device token'

    # FCM v1 requires all data values to be strings.
    payload_data = {}
    for k, v in (data or {}).items():
        if v is None:
            continue
        safe_key = _sanitize_fcm_data_key(str(k))
        if not safe_key:
            continue
        payload_data[safe_key] = str(v)

    # Build message. For silent pushes, omit the 'notification' top-level so Android/iOS treat it as a data-only/background push.
    message = {
        'token': token,
        'data': payload_data,
        'android': {
            'priority': 'HIGH',
            'ttl': '86400s',
        },
    }

    if not silent:
        # Visible notification for foreground/background as usual
        message['notification'] = {'title': title or '', 'body': body or ''}
        message.setdefault('android', {}).setdefault('notification', {}).update(
            {
                'channelId': 'attendance_app_v2',
                'sound': 'default',
                'clickAction': 'FLUTTER_NOTIFICATION_CLICK',
                'notificationPriority': 'PRIORITY_MAX',
                'defaultSound': True,
                'defaultVibrateTimings': True,
            }
        )
        message.setdefault('apns', {}).setdefault('headers', {})['apns-priority'] = '10'
        message.setdefault('apns', {}).setdefault('headers', {})['apns-push-type'] = 'alert'
        aps = message.setdefault('apns', {}).setdefault('payload', {}).setdefault('aps', {})
        aps['sound'] = 'default'
        aps['alert'] = {'title': title or '', 'body': body or ''}
    else:
        # For iOS devices, signal a background content-available push so apps can wake to handle the payload
        message.setdefault('apns', {}).setdefault('headers', {})['apns-priority'] = '5'
        message.setdefault('apns', {}).setdefault('headers', {})['apns-push-type'] = 'background'
        message.setdefault('apns', {}).setdefault('payload', {})['aps'] = {'content-available': 1}

    payload = {'message': message}
    url = f'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'

    def _attempt_send(token_to_use):
        return _post_json(
            url,
            payload,
            headers={
                'Authorization': 'Bearer %s' % token_to_use,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            timeout_seconds=15,
        )

    try:
        code, raw = _attempt_send(access_token)
        if code == 401:
            # Token expired/invalid, refresh once and retry.
            _ACCESS_TOKEN_CACHE.pop((service_account.get('client_email') or '').strip(), None)
            access_token2, err2 = _get_fcm_v1_access_token(env)
            if not access_token2:
                return False, err2 or 'FCM OAuth refresh failed'
            code, raw = _attempt_send(access_token2)

        if code != 200:
            _logger.warning('FCM v1 push non-200: %s body=%s', code, (raw or b'')[:500])
            return False, 'FCM v1 HTTP %s' % code

        return True, 'sent'
    except HTTPError as e:
        body_raw = b''
        try:
            body_raw = e.read() or b''
        except Exception:
            body_raw = b''
        _logger.warning('FCM v1 push HTTPError: %s body=%s', e, body_raw[:500])
        return False, 'FCM v1 HTTP error'
    except URLError as e:
        _logger.warning('FCM v1 push URLError: %s', e)
        return False, 'FCM v1 unreachable'
    except Exception as e:
        _logger.warning('FCM v1 push exception: %s', e)
        return False, 'FCM v1 exception'


def send_fcm_push(*, env, token, title=None, body=None, data=None, silent=False):
    """
    Send a push notification using Firebase Cloud Messaging.

    - If `silent=True`, a data-only/background push is sent (no visible notification).
    - Prefer HTTP v1 (service account JSON) because Legacy HTTP is disabled for most new projects.
    - Fallback to Legacy HTTP only if a legacy server key is configured.

    Returns: (ok: bool, message: str)
    """
    ok, msg = license_helper.is_subscription_active(env, allow_refresh=True)
    if not ok:
        return False, msg or 'Subscription required'

    server_key = get_fcm_server_key(env)
    if _get_fcm_service_account_json(env):
        ok_v1, msg_v1 = _send_fcm_push_v1(env=env, token=token, title=title, body=body, data=data, silent=silent)
        if ok_v1:
            return True, msg_v1
        if not server_key:
            return False, msg_v1
        _logger.warning('FCM v1 failed, falling back to legacy HTTP API: %s', msg_v1)

    if not server_key:
        return False, 'FCM is not configured (set service account JSON or legacy server key)'

    if not token:
        return False, 'Missing device token'

    # Legacy payload: use data-only push for silent, otherwise include notification block.
    payload = {
        'to': token,
        'data': data or {},
        'priority': 'high',
        'time_to_live': 86400,
    }

    if not silent:
        payload['notification'] = {
            'title': title or '',
            'body': body or '',
            # Ensure the notification maps to the app-created channel on Android 8+
            # (FlutterLocalNotifications channel id: "attendance_app").
            'android_channel_id': 'attendance_app_v2',
            'sound': 'default',
            # Allows tapping the notification to open the app (common Flutter convention).
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
        }
    else:
        # Signal iOS that content is available for background processing
        payload['content_available'] = True

    try:
        code, raw = _post_json(
            'https://fcm.googleapis.com/fcm/send',
            payload,
            headers={
                'Authorization': 'key=%s' % server_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            timeout_seconds=15,
        )
        if code != 200:
            _logger.warning('FCM push non-200: %s body=%s', code, (raw or b'')[:500])
            return False, 'FCM HTTP %s' % code

        result = {}
        try:
            result = json.loads((raw or b'{}').decode('utf-8'))
        except Exception:
            result = {}

        failure = int(result.get('failure') or 0)
        if failure > 0:
            reason = ''
            try:
                results = result.get('results') or []
                if results and isinstance(results, list) and isinstance(results[0], dict):
                    reason = results[0].get('error') or ''
            except Exception:
                reason = ''
            _logger.warning('FCM push failure=%s reason=%s response=%s', failure, reason, (raw or b'')[:500])
            return False, reason or 'FCM push failed'

        return True, 'sent'
    except HTTPError as e:
        body = b''
        try:
            body = e.read() or b''
        except Exception:
            body = b''
        _logger.warning('FCM push HTTPError: %s body=%s', e, body[:500])
        return False, 'FCM HTTP error'
    except URLError as e:
        _logger.warning('FCM push URLError: %s', e)
        return False, 'FCM unreachable'
    except Exception as e:
        _logger.warning('FCM push exception: %s', e)
        return False, 'FCM push exception'
