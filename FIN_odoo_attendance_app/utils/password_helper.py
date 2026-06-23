# -*- coding: utf-8 -*-
import bcrypt


def hash_password(plain_password):
    """
    Hash password using bcrypt.
    
    Args:
        plain_password (str): Plain text password
    
    Returns:
        str: bcrypt hashed password
    """
    if isinstance(plain_password, str):
        plain_password = plain_password.encode('utf-8')
    
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password, hashed_password):
    """
    Verify password against bcrypt hash.
    
    Args:
        plain_password (str): Plain text password to verify
        hashed_password (str): bcrypt hash from database
    
    Returns:
        bool: True if password matches, False otherwise
    """
    if isinstance(plain_password, str):
        plain_password = plain_password.encode('utf-8')
    
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode('utf-8')
    
    return bcrypt.checkpw(plain_password, hashed_password)
