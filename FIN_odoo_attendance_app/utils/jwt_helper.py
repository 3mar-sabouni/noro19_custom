# -*- coding: utf-8 -*-
import jwt
import hashlib
from datetime import datetime, timedelta
from odoo import api, SUPERUSER_ID
from odoo.exceptions import ValidationError


# JWT Configuration
JWT_ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRY_HOURS = 1
REFRESH_TOKEN_EXPIRY_DAYS = 30


def get_jwt_secret(env):
    """
    Get JWT secret from system parameters.
    Falls back to a database-specific default if not set.
    IMPORTANT: Set this in Odoo System Parameters for production!
    """
    IrConfigParameter = env['ir.config_parameter'].sudo()
    secret = IrConfigParameter.get_param('odoo_attendance_app.jwt_secret')
    
    if not secret:
        # Generate a default secret based on database UUID (not secure for production!)
        db_uuid = IrConfigParameter.get_param('database.uuid')
        secret = f"odoo-attendance-{db_uuid or 'default'}-secret"
        # Warning: Should set proper secret in production
    
    return secret


def generate_access_token(env, employee_app_id, employee_id, username, device_id):
    """
    Generate JWT access token (short-lived, 1 hour).
    
    Payload contains:
    - sub: employee_app_id
    - employee_id: Odoo hr.employee ID
    - username: app username
    - device_id: device identifier
    - iat: issued at
    - exp: expiration time
    """
    secret = get_jwt_secret(env)
    now = datetime.utcnow()
    
    payload = {
        'sub': str(employee_app_id),
        'employee_id': employee_id,
        'username': username,
        'device_id': device_id,
        'iat': now,
        'exp': now + timedelta(hours=ACCESS_TOKEN_EXPIRY_HOURS),
        'type': 'access'
    }
    
    token = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return token


def generate_refresh_token(env, employee_app_id, device_id):
    """
    Generate JWT refresh token (long-lived, 30 days).
    
    Payload contains:
    - sub: employee_app_id
    - device_id: device identifier
    - iat: issued at
    - exp: expiration time
    """
    secret = get_jwt_secret(env)
    now = datetime.utcnow()
    
    payload = {
        'sub': str(employee_app_id),
        'device_id': device_id,
        'iat': now,
        'exp': now + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS),
        'type': 'refresh'
    }
    
    token = jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)
    return token


def verify_token(env, token, expected_type='access'):
    """
    Verify and decode JWT token.
    
    Returns: decoded payload dictionary
    Raises: ValidationError if token is invalid
    """
    secret = get_jwt_secret(env)
    
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        
        # Verify token type
        if payload.get('type') != expected_type:
            raise ValidationError(f'Invalid token type. Expected {expected_type}.')
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise ValidationError('Token has expired.')
    except jwt.InvalidTokenError as e:
        raise ValidationError(f'Invalid token: {str(e)}')


def hash_refresh_token(refresh_token):
    """
    Hash refresh token for storage in database.
    Uses SHA256 for quick lookups.
    """
    return hashlib.sha256(refresh_token.encode()).hexdigest()


def extract_bearer_token(authorization_header):
    """
    Extract token from Authorization header.
    
    Expected format: "Bearer <token>"
    Returns: token string or None
    """
    if not authorization_header:
        return None
    
    parts = authorization_header.split(' ')
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    
    return parts[1]
