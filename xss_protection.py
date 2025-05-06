"""
XSS protection utilities.
This module provides functions to sanitize user input to prevent XSS attacks.
"""
import re
from typing import Dict, Any, List, Union

# Tag whitelist for allowing specific HTML tags
ALLOWED_TAGS = {
    'a': ['href', 'title', 'target', 'rel'],
    'b': [],
    'br': [],
    'code': [],
    'div': ['class'],
    'em': [],
    'h1': [],
    'h2': [],
    'h3': [],
    'h4': [],
    'h5': [],
    'h6': [],
    'hr': [],
    'i': [],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'li': [],
    'ol': [],
    'p': ['class'],
    'pre': [],
    'span': ['class'],
    'strong': [],
    'table': ['border', 'cellpadding', 'cellspacing'],
    'tbody': [],
    'td': ['colspan', 'rowspan', 'style'],
    'th': ['colspan', 'rowspan', 'style'],
    'thead': [],
    'tr': [],
    'ul': []
}

# Regex for finding all HTML tags
TAG_PATTERN = re.compile(r'<(/?)(\w+)(\s+[^>]*)?>', re.IGNORECASE)

# Regex for finding attributes in a tag
ATTR_PATTERN = re.compile(r'(\w+)=["\'](.*?)["\']', re.IGNORECASE)

# URL scheme whitelist
ALLOWED_URL_SCHEMES = ['http', 'https', 'mailto', 'tel']


def _sanitize_attribute_value(attr_name: str, attr_value: str) -> str:
    """Sanitize an attribute value.
    
    Args:
        attr_name: The attribute name
        attr_value: The attribute value
        
    Returns:
        The sanitized attribute value
    """
    # Special handling for URLs
    if attr_name in ['href', 'src']:
        # Check for malicious URL schemes
        lower_value = attr_value.lower().strip()
        
        # Check if it's a relative URL (starts with / or ./)
        if lower_value.startswith(('/', './')):
            return attr_value
        
        # Check if it's an allowed scheme
        for scheme in ALLOWED_URL_SCHEMES:
            if lower_value.startswith(f"{scheme}:"):
                return attr_value
                
        # Default to a safe value if not allowed
        return "#"
    
    # Remove potentially malicious JavaScript events (on*)
    if attr_name.lower().startswith('on'):
        return ""
    
    # Encode HTML entities in attribute values
    attr_value = attr_value.replace('&', '&amp;')
    attr_value = attr_value.replace('<', '&lt;')
    attr_value = attr_value.replace('>', '&gt;')
    attr_value = attr_value.replace('"', '&quot;')
    attr_value = attr_value.replace("'", '&#x27;')
    
    return attr_value


def _sanitize_tag(tag_match) -> str:
    """Sanitize an HTML tag.
    
    Args:
        tag_match: Regex match object for the tag
        
    Returns:
        The sanitized tag or an empty string if the tag is disallowed
    """
    closing, tag_name, attrs_str = tag_match.groups()
    tag_name = tag_name.lower()
    
    # Check if the tag is allowed
    if tag_name not in ALLOWED_TAGS:
        return ""
    
    # For closing tags or void tags without attributes
    if closing or not attrs_str:
        return f"<{closing}{tag_name}>"
    
    # Process attributes
    allowed_attrs = ALLOWED_TAGS[tag_name]
    sanitized_attrs = []
    
    # Find all attributes in the tag
    attr_matches = ATTR_PATTERN.findall(attrs_str)
    for attr_name, attr_value in attr_matches:
        attr_name = attr_name.lower()
        
        # Check if the attribute is allowed
        if attr_name in allowed_attrs:
            # Sanitize the attribute value
            sanitized_value = _sanitize_attribute_value(attr_name, attr_value)
            sanitized_attrs.append(f'{attr_name}="{sanitized_value}"')
    
    # Rebuild the tag with sanitized attributes
    if sanitized_attrs:
        return f"<{tag_name} {' '.join(sanitized_attrs)}>"
    else:
        return f"<{tag_name}>"


def sanitize_html(html: str) -> str:
    """Sanitize HTML content to prevent XSS attacks.
    
    This function allows a whitelist of HTML tags and attributes,
    but removes any potentially dangerous tags and attributes.
    
    Args:
        html: The HTML content to sanitize
        
    Returns:
        The sanitized HTML content
    """
    if not html:
        return ""
    
    # Replace HTML entities first to prevent entity-based attacks
    html = html.replace('&', '&amp;')
    
    # Then restore the entities we need for tag processing
    html = html.replace('&amp;lt;', '&lt;')
    html = html.replace('&amp;gt;', '&gt;')
    
    # Process all tags in the HTML
    result = TAG_PATTERN.sub(lambda m: _sanitize_tag(m), html)
    
    return result


def strip_all_tags(html: str) -> str:
    """Strip all HTML tags from a string.
    
    Args:
        html: The HTML content to strip
        
    Returns:
        The text content without any HTML tags
    """
    if not html:
        return ""
    
    # Simple tag removal
    return TAG_PATTERN.sub('', html)


def sanitize_recursive(data: Any) -> Any:
    """Recursively sanitize a data structure (dict, list, str).
    
    Args:
        data: The data to sanitize
        
    Returns:
        The sanitized data
    """
    if isinstance(data, str):
        return strip_all_tags(data)
    elif isinstance(data, dict):
        return {k: sanitize_recursive(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_recursive(item) for item in data]
    else:
        return data