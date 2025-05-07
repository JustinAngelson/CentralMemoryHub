"""
Secure API utilities for Flask routes.
This module combines rate limiting, API key validation, input validation, 
and other security measures for API endpoints.
"""
import json
import logging
import functools
from typing import Dict, Any, List, Callable, Optional, Tuple, Union

from flask import request, jsonify, Response
import api_keys
from api_keys import ApiKey, ApiRequestLog
from validation import ValidationError, validate_request_data
from xss_protection import sanitize_recursive

# Type aliases
ValidatorSchema = Dict[str, Dict[str, Any]]
Handler = Callable[..., Tuple[Dict[str, Any], int]]
JsonResponse = Tuple[Response, int]


def secure_endpoint(
    validator_schema: Optional[ValidatorSchema] = None,
    require_api_key: bool = True,
    sanitize_input: bool = True,
    rate_limit: Optional[int] = None,
    log_request: bool = True
):
    """Decorator for securing API endpoints with validation, sanitization, and authentication.
    
    This decorator combines multiple security measures:
    - API key validation (if required)
    - Rate limiting (specific to this endpoint)
    - Input validation against a schema
    - Input sanitization to prevent XSS
    - Request logging
    - Error handling
    
    Usage:
        @app.route('/api/example', methods=['POST'])
        @secure_endpoint(
            validator_schema={
                'name': {'type': 'string', 'required': True, 'min_length': 3},
                'age': {'type': 'integer', 'required': True, 'min_value': 0}
            },
            rate_limit=10  # Override the default rate limit for this endpoint
        )
        def example_endpoint():
            # Access validated data using request.validated_data
            name = request.validated_data['name']
            return {'message': f'Hello, {name}!'}, 200
    
    Args:
        validator_schema: Schema for validating request data
        require_api_key: Whether to require an API key for this endpoint
        sanitize_input: Whether to sanitize input to prevent XSS
        rate_limit: Custom rate limit for this endpoint (requests per minute)
        log_request: Whether to log this request
        
    Returns:
        The decorated function
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            # Variables for response and tracking
            status_code = 200
            api_key_id = None
            response_data = {}
            
            try:
                # Handle preflight OPTIONS requests
                if request.method == 'OPTIONS':
                    return '', 200
                
                # API key validation
                if require_api_key:
                    # Check for API key in headers, case-insensitive (supports X-API-KEY, x-api-key, etc.)
                    api_key_header = None
                    for header_name in request.headers:
                        if header_name.lower() == 'x-api-key':
                            api_key_header = request.headers[header_name]
                            break
                    
                    if not api_key_header:
                        status_code = 401
                        return jsonify({"error": "Unauthorized. Missing API key. Please provide X-API-KEY header."}), status_code
                    
                    # Get the API key
                    api_key = _get_api_key(api_key_header)
                    if not api_key:
                        status_code = 401
                        return jsonify({"error": "Unauthorized. Invalid API key."}), status_code
                    
                    api_key_id = api_key.key_id
                    
                    # Check rate limiting
                    endpoint_rate_limit = rate_limit or api_key.rate_limit
                    if _is_rate_limited(api_key_id, endpoint_rate_limit, request.path):
                        status_code = 429
                        return jsonify({
                            "error": "Too Many Requests",
                            "message": f"Rate limit of {endpoint_rate_limit} requests per minute exceeded for this endpoint."
                        }), status_code
                    
                    # Update last used timestamp
                    api_key.update_last_used()
                
                # Parse request data
                request_data = _get_request_data()
                
                # Sanitize input if enabled
                if sanitize_input and request_data:
                    request_data = sanitize_recursive(request_data)
                
                # Validate input if schema provided
                if validator_schema and request_data:
                    try:
                        validated_data = validate_request_data(request_data, validator_schema)
                        # Attach validated data to the request for the handler to use
                        request.validated_data = validated_data
                    except ValidationError as e:
                        status_code = 400
                        return jsonify({
                            "error": "Validation Error",
                            "message": e.message,
                            "field": e.field
                        }), status_code
                
                # Call the actual endpoint function
                response = f(*args, **kwargs)
                
                # Process the response
                if isinstance(response, tuple) and len(response) > 1:
                    response_data, status_code = response
                else:
                    response_data = response
                
                # Return the response as JSON
                return jsonify(response_data), status_code
                
            except Exception as e:
                # Log the error
                logging.exception(f"Error in secure endpoint {request.path}: {str(e)}")
                
                # Return a 500 error
                status_code = 500
                response_data = {
                    "error": "Internal Server Error",
                    "message": "An unexpected error occurred while processing your request."
                }
                return jsonify(response_data), status_code
                
            finally:
                # Log the request if enabled and we have an API key ID
                if log_request and api_key_id:
                    try:
                        ApiRequestLog.log_request(
                            api_key_id=api_key_id,
                            request=request,
                            status_code=status_code,
                            include_data=False  # Avoid logging sensitive data
                        )
                    except Exception as e:
                        # Don't fail the request if logging fails
                        logging.error(f"Failed to log API request: {str(e)}")
        
        return decorated_function
    
    return decorator


def _get_api_key(api_key_value: str) -> Optional[ApiKey]:
    """Get an API key by its value.
    
    Args:
        api_key_value: The API key value
        
    Returns:
        The API key object if found and valid, None otherwise
    """
    # Legacy API key support
    from routes import DEFAULT_API_KEY
    if api_key_value == DEFAULT_API_KEY:
        # Create a temporary API key object for the default key
        key = ApiKey(
            key_id="default",
            api_key=DEFAULT_API_KEY,
            name="Default API Key",
            rate_limit=200,
            is_active=True
        )
        return key
    
    # Look up the key in the database
    from app import db
    api_key = db.session.query(ApiKey).filter_by(api_key=api_key_value).first()
    
    if not api_key or not api_key.is_valid():
        return None
    
    return api_key


def _is_rate_limited(api_key_id: str, limit: int, endpoint: str) -> bool:
    """Check if a request should be rate limited.
    
    Args:
        api_key_id: The API key ID
        limit: The rate limit (requests per minute)
        endpoint: The API endpoint being accessed
        
    Returns:
        True if the request should be rate limited, False otherwise
    """
    # Use the rate limiter from routes.py
    from routes import rate_limiter
    
    # Create a unique key for this endpoint and API key
    # This allows per-endpoint rate limiting
    endpoint_key = f"{api_key_id}:{endpoint}"
    
    return rate_limiter.is_rate_limited(endpoint_key, limit)


def _get_request_data() -> Dict[str, Any]:
    """Extract data from the request (JSON or form data).
    
    Returns:
        The request data as a dictionary
    """
    if request.is_json:
        return request.get_json() or {}
    elif request.form:
        return {key: request.form[key] for key in request.form}
    elif request.args:
        return {key: request.args[key] for key in request.args}
    else:
        return {}