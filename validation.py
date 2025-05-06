"""
Input validation utilities for API endpoints.
This module provides functions to validate and sanitize user input.
"""
import re
import json
import uuid
from typing import Dict, List, Any, Optional, Union, Tuple, Callable
from datetime import datetime

# Regex patterns for common fields
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
URL_PATTERN = re.compile(r'^https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+')

class ValidationError(Exception):
    """Exception raised for validation errors."""
    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


def validate_required(data: Dict[str, Any], fields: List[str]) -> None:
    """Validate that all required fields are present in the data.
    
    Args:
        data: The data to validate
        fields: List of required field names
        
    Raises:
        ValidationError: If any required field is missing
    """
    missing_fields = [field for field in fields if field not in data]
    if missing_fields:
        raise ValidationError(
            f"Missing required fields: {', '.join(missing_fields)}",
            field=missing_fields[0] if missing_fields else None
        )


def validate_string(value: Any, field: str, min_length: int = 1, max_length: Optional[int] = None) -> str:
    """Validate and sanitize a string value.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        min_length: Minimum allowed length
        max_length: Maximum allowed length, or None for unlimited
        
    Returns:
        The validated and sanitized string
        
    Raises:
        ValidationError: If the value is not a valid string
    """
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string", field=field)
    
    # Trim whitespace
    value = value.strip()
    
    # Check length
    if len(value) < min_length:
        raise ValidationError(
            f"Field '{field}' must be at least {min_length} characters long",
            field=field
        )
    
    if max_length is not None and len(value) > max_length:
        raise ValidationError(
            f"Field '{field}' cannot exceed {max_length} characters",
            field=field
        )
    
    return value


def validate_email(value: Any, field: str) -> str:
    """Validate an email address.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        
    Returns:
        The validated email address
        
    Raises:
        ValidationError: If the value is not a valid email address
    """
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string", field=field)
    
    value = value.strip().lower()
    
    if not EMAIL_PATTERN.match(value):
        raise ValidationError(f"Field '{field}' must be a valid email address", field=field)
    
    return value


def validate_uuid(value: Any, field: str) -> str:
    """Validate a UUID string.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        
    Returns:
        The validated UUID string
        
    Raises:
        ValidationError: If the value is not a valid UUID
    """
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string", field=field)
    
    value = value.strip().lower()
    
    if not UUID_PATTERN.match(value):
        raise ValidationError(f"Field '{field}' must be a valid UUID", field=field)
    
    return value


def validate_url(value: Any, field: str) -> str:
    """Validate a URL.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        
    Returns:
        The validated URL
        
    Raises:
        ValidationError: If the value is not a valid URL
    """
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string", field=field)
    
    value = value.strip()
    
    if not URL_PATTERN.match(value):
        raise ValidationError(f"Field '{field}' must be a valid URL", field=field)
    
    return value


def validate_integer(value: Any, field: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """Validate an integer value.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        min_value: Minimum allowed value, or None for no minimum
        max_value: Maximum allowed value, or None for no maximum
        
    Returns:
        The validated integer
        
    Raises:
        ValidationError: If the value is not a valid integer
    """
    try:
        if isinstance(value, str):
            value = int(value.strip())
        elif isinstance(value, (int, float)):
            value = int(value)
        else:
            raise ValueError("Not a number")
    except (ValueError, TypeError):
        raise ValidationError(f"Field '{field}' must be a valid integer", field=field)
    
    if min_value is not None and value < min_value:
        raise ValidationError(
            f"Field '{field}' must be at least {min_value}",
            field=field
        )
    
    if max_value is not None and value > max_value:
        raise ValidationError(
            f"Field '{field}' cannot exceed {max_value}",
            field=field
        )
    
    return value


def validate_boolean(value: Any, field: str) -> bool:
    """Validate a boolean value.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        
    Returns:
        The validated boolean
        
    Raises:
        ValidationError: If the value is not a valid boolean
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        if value_lower in ('true', 'yes', '1', 'y'):
            return True
        if value_lower in ('false', 'no', '0', 'n'):
            return False
    
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    
    raise ValidationError(f"Field '{field}' must be a valid boolean", field=field)


def validate_datetime(value: Any, field: str) -> datetime:
    """Validate a datetime value.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        
    Returns:
        The validated datetime
        
    Raises:
        ValidationError: If the value is not a valid datetime
    """
    if isinstance(value, datetime):
        return value
    
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a valid datetime string", field=field)
    
    value = value.strip()
    
    try:
        # Try ISO format first
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    
    # Try various common formats
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%m/%d/%Y',
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    
    raise ValidationError(f"Field '{field}' must be a valid datetime", field=field)


def validate_list(
    value: Any, 
    field: str, 
    item_validator: Optional[Callable[[Any, str], Any]] = None,
    min_length: int = 0,
    max_length: Optional[int] = None
) -> List[Any]:
    """Validate a list value.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        item_validator: Optional function to validate each item in the list
        min_length: Minimum allowed length
        max_length: Maximum allowed length, or None for unlimited
        
    Returns:
        The validated list
        
    Raises:
        ValidationError: If the value is not a valid list
    """
    if not isinstance(value, list):
        raise ValidationError(f"Field '{field}' must be a list", field=field)
    
    # Check length
    if len(value) < min_length:
        raise ValidationError(
            f"Field '{field}' must contain at least {min_length} items",
            field=field
        )
    
    if max_length is not None and len(value) > max_length:
        raise ValidationError(
            f"Field '{field}' cannot contain more than {max_length} items",
            field=field
        )
    
    # Validate items if a validator is provided
    if item_validator:
        for i, item in enumerate(value):
            try:
                value[i] = item_validator(item, f"{field}[{i}]")
            except ValidationError as e:
                # Re-raise with updated field name
                raise ValidationError(e.message, field=f"{field}[{i}]")
    
    return value


def validate_dict(
    value: Any,
    field: str,
    required_keys: Optional[List[str]] = None,
    key_validators: Optional[Dict[str, Callable[[Any, str], Any]]] = None
) -> Dict[str, Any]:
    """Validate a dictionary value.
    
    Args:
        value: The value to validate
        field: The name of the field (for error messages)
        required_keys: Optional list of required keys
        key_validators: Optional dictionary of validators for specific keys
        
    Returns:
        The validated dictionary
        
    Raises:
        ValidationError: If the value is not a valid dictionary
    """
    if not isinstance(value, dict):
        raise ValidationError(f"Field '{field}' must be an object", field=field)
    
    # Check required keys
    if required_keys:
        missing_keys = [key for key in required_keys if key not in value]
        if missing_keys:
            raise ValidationError(
                f"Field '{field}' is missing required keys: {', '.join(missing_keys)}",
                field=f"{field}.{missing_keys[0]}" if missing_keys else field
            )
    
    # Validate specific keys if validators are provided
    if key_validators:
        for key, validator in key_validators.items():
            if key in value:
                try:
                    value[key] = validator(value[key], f"{field}.{key}")
                except ValidationError as e:
                    # Use the field name from the validation error
                    raise ValidationError(e.message, field=e.field or f"{field}.{key}")
    
    return value


def sanitize_html(value: str) -> str:
    """Remove HTML tags from a string.
    
    Args:
        value: The string to sanitize
        
    Returns:
        The sanitized string
    """
    # Simple HTML tag removal - for production use a proper HTML sanitizer library
    return re.sub(r'<[^>]*>', '', value)


def sanitize_sql(value: str) -> str:
    """Sanitize a string to prevent SQL injection.
    
    Args:
        value: The string to sanitize
        
    Returns:
        The sanitized string
    """
    # Basic SQL injection prevention
    return value.replace("'", "''").replace(";", "")


def validate_request_data(request_data: Dict[str, Any], validator_schema: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Validate and sanitize request data according to a schema.
    
    Args:
        request_data: The data to validate
        validator_schema: A dictionary defining the validation rules for each field
            {
                'field_name': {
                    'type': 'string|email|uuid|integer|boolean|datetime|list|dict',
                    'required': True|False,
                    'min_length': 1,  # For strings and lists
                    'max_length': 100,  # For strings and lists
                    'min_value': 0,  # For integers
                    'max_value': 100,  # For integers
                    'item_validator': callable,  # For lists
                    'required_keys': ['key1', 'key2'],  # For dicts
                    'key_validators': {'key1': callable},  # For dicts
                }
            }
        
    Returns:
        The validated and sanitized data
        
    Raises:
        ValidationError: If validation fails
    """
    validated_data = {}
    
    # First, check all required fields
    for field_name, rules in validator_schema.items():
        if rules.get('required', False) and field_name not in request_data:
            raise ValidationError(f"Required field '{field_name}' is missing", field=field_name)
    
    # Then validate each field
    for field_name, rules in validator_schema.items():
        # Skip if field is not in request data and not required
        if field_name not in request_data:
            continue
        
        field_type = rules.get('type', 'string')
        value = request_data[field_name]
        
        # Validate based on type
        if field_type == 'string':
            validated_data[field_name] = validate_string(
                value, field_name, 
                min_length=rules.get('min_length', 1), 
                max_length=rules.get('max_length')
            )
        elif field_type == 'email':
            validated_data[field_name] = validate_email(value, field_name)
        elif field_type == 'uuid':
            validated_data[field_name] = validate_uuid(value, field_name)
        elif field_type == 'url':
            validated_data[field_name] = validate_url(value, field_name)
        elif field_type == 'integer':
            validated_data[field_name] = validate_integer(
                value, field_name, 
                min_value=rules.get('min_value'), 
                max_value=rules.get('max_value')
            )
        elif field_type == 'boolean':
            validated_data[field_name] = validate_boolean(value, field_name)
        elif field_type == 'datetime':
            validated_data[field_name] = validate_datetime(value, field_name)
        elif field_type == 'list':
            validated_data[field_name] = validate_list(
                value, field_name, 
                item_validator=rules.get('item_validator'),
                min_length=rules.get('min_length', 0),
                max_length=rules.get('max_length')
            )
        elif field_type == 'dict':
            validated_data[field_name] = validate_dict(
                value, field_name, 
                required_keys=rules.get('required_keys'),
                key_validators=rules.get('key_validators')
            )
    
    return validated_data