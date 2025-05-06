"""
CSRF protection for Flask applications.
This module provides functions to generate and validate CSRF tokens.
"""
import os
import time
import hmac
import hashlib
import base64
from typing import Optional, Tuple
from functools import wraps
from flask import request, session, abort, jsonify

# How long a CSRF token is valid (in seconds)
TOKEN_VALIDITY = 3600  # 1 hour


def _get_csrf_secret() -> str:
    """Get the CSRF secret key.
    
    Returns:
        A secret key for CSRF token generation
    """
    return os.environ.get('SESSION_SECRET', 'default-csrf-secret-key')


def generate_csrf_token() -> str:
    """Generate a new CSRF token and store it in the session.
    
    Returns:
        A CSRF token string
    """
    # Generate a unique token using os.urandom
    random_bytes = os.urandom(32)
    csrf_token_value = base64.b64encode(random_bytes).decode('utf-8')
    
    # Generate a timestamp
    timestamp = int(time.time())
    
    # Store in session with timestamp
    session['csrf_token'] = csrf_token_value
    session['csrf_token_time'] = timestamp
    
    return csrf_token_value


def _validate_csrf_token(token: str) -> bool:
    """Validate a CSRF token against the one stored in the session.
    
    Args:
        token: The CSRF token to validate
        
    Returns:
        True if the token is valid, False otherwise
    """
    # Get the token from the session
    session_token = session.get('csrf_token')
    token_time = session.get('csrf_token_time', 0)
    
    # Check if the token exists and is still valid
    if not session_token:
        return False
    
    # Check if the token has expired
    current_time = int(time.time())
    if current_time - token_time > TOKEN_VALIDITY:
        return False
    
    # Check if the tokens match
    return hmac.compare_digest(session_token, token)


def validate_csrf_token() -> bool:
    """Validate the CSRF token from the request.
    
    The token can be provided in:
    - A form field named "_csrf_token"
    - A request header named "X-CSRF-Token"
    
    Returns:
        True if the token is valid, False otherwise
    """
    # Get the token from the request
    token = None
    
    # Check form data
    if request.form:
        token = request.form.get('_csrf_token')
    
    # Check JSON data
    if token is None and request.is_json:
        token = request.json.get('_csrf_token')
    
    # Check headers
    if token is None:
        token = request.headers.get('X-CSRF-Token')
    
    # No token found
    if token is None:
        return False
    
    return _validate_csrf_token(token)


def generate_signed_token(data: str, expires_in: int = 3600) -> str:
    """Generate a signed token containing data.
    
    Args:
        data: The data to include in the token
        expires_in: Token validity in seconds (default: 1 hour)
        
    Returns:
        A signed token string
    """
    # Create token parts
    timestamp = int(time.time()) + expires_in
    payload = f"{data}:{timestamp}"
    
    # Sign the payload
    secret = _get_csrf_secret().encode('utf-8')
    signature = hmac.new(secret, payload.encode('utf-8'), hashlib.sha256).hexdigest()
    
    # Combine and encode
    token = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(token.encode('utf-8')).decode('utf-8')


def validate_signed_token(token: str) -> Optional[str]:
    """Validate a signed token and extract the data.
    
    Args:
        token: The signed token to validate
        
    Returns:
        The data from the token if valid, None otherwise
    """
    try:
        # Decode the token
        decoded = base64.urlsafe_b64decode(token.encode('utf-8')).decode('utf-8')
        
        # Split into parts
        parts = decoded.split(':')
        if len(parts) != 3:
            return None
        
        data, timestamp_str, signature = parts
        
        # Check expiration
        timestamp = int(timestamp_str)
        current_time = int(time.time())
        if current_time > timestamp:
            return None
        
        # Verify signature
        payload = f"{data}:{timestamp_str}"
        secret = _get_csrf_secret().encode('utf-8')
        expected_signature = hmac.new(secret, payload.encode('utf-8'), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return None
        
        return data
        
    except Exception:
        return None


def csrf_protect(f):
    """Decorator to require a valid CSRF token for POST, PUT, DELETE requests.
    
    Usage:
        @app.route('/example', methods=['POST'])
        @csrf_protect
        def example():
            return "Protected from CSRF"
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Skip validation for methods that should be idempotent
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not validate_csrf_token():
                response = {
                    "error": "CSRF token validation failed",
                    "message": "The form session has expired or the security token is invalid."
                }
                return jsonify(response), 403
        return f(*args, **kwargs)
    return decorated_function