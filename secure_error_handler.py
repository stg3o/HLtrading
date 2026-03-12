"""Compatibility facade for secure error handling helpers."""

from hltrading.security.secure_error_handler import (
    ErrorCategory,
    ErrorSeverity,
    SecureError,
    SecureErrorContext,
    SecureErrorHandler,
    handle_api_error,
    handle_system_error,
    handle_validation_error,
    log_security_violation,
    logger,
    secure_error_handler,
)

__all__ = [
    "logger",
    "ErrorSeverity",
    "ErrorCategory",
    "SecureError",
    "SecureErrorHandler",
    "secure_error_handler",
    "handle_api_error",
    "handle_validation_error",
    "handle_system_error",
    "log_security_violation",
    "SecureErrorContext",
]
