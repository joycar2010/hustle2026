"""Log sanitization utilities"""
import re
from typing import Any, Dict, List


# Sensitive field patterns
SENSITIVE_FIELDS = {
    "password",
    "password_hash",
    "api_key",
    "api_secret",
    "secret_key",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_credential",
    "private_key",
    "secret",
    "credential",
}

# Patterns to detect sensitive data in strings
SENSITIVE_PATTERNS = [
    (re.compile(r'"password"\s*:\s*"[^"]*"'), '"password":"***"'),
    (re.compile(r'"api_key"\s*:\s*"[^"]*"'), '"api_key":"***"'),
    (re.compile(r'"api_secret"\s*:\s*"[^"]*"'), '"api_secret":"***"'),
    (re.compile(r'"token"\s*:\s*"[^"]*"'), '"token":"***"'),
    (re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*'), 'Bearer ***'),
    (re.compile(r'[A-Za-z0-9]{32,}'), '***'),  # Long alphanumeric strings (likely keys)
]


def sanitize_dict(data: Dict[str, Any], mask: str = "***") -> Dict[str, Any]:
    """
    Sanitize sensitive fields in dictionary

    Args:
        data: Dictionary to sanitize
        mask: Mask string to replace sensitive values

    Returns:
        Sanitized dictionary
    """
    if not isinstance(data, dict):
        return data

    sanitized = {}
    for key, value in data.items():
        # Check if key is sensitive
        if key.lower() in SENSITIVE_FIELDS:
            sanitized[key] = mask
        # Recursively sanitize nested dicts
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value, mask)
        # Recursively sanitize lists
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_dict(item, mask) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value

    return sanitized


def sanitize_string(text: str, mask: str = "***") -> str:
    """
    Sanitize sensitive patterns in string

    Args:
        text: String to sanitize
        mask: Mask string to replace sensitive values

    Returns:
        Sanitized string
    """
    if not isinstance(text, str):
        return text

    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized


def sanitize_log(data: Any, mask: str = "***") -> Any:
    """
    Sanitize any data type for logging

    Args:
        data: Data to sanitize (dict, str, list, etc.)
        mask: Mask string to replace sensitive values

    Returns:
        Sanitized data
    """
    if isinstance(data, dict):
        return sanitize_dict(data, mask)
    elif isinstance(data, str):
        return sanitize_string(data, mask)
    elif isinstance(data, list):
        return [sanitize_log(item, mask) for item in data]
    else:
        return data


class SanitizingFormatter:
    """Custom log formatter that sanitizes sensitive data"""

    def __init__(self, original_formatter):
        self.original_formatter = original_formatter

    def format(self, record):
        """Format log record with sanitization"""
        # Sanitize message
        if hasattr(record, 'msg'):
            record.msg = sanitize_string(str(record.msg))

        # Sanitize args
        if hasattr(record, 'args') and record.args:
            record.args = tuple(sanitize_log(arg) for arg in record.args)

        return self.original_formatter.format(record)
