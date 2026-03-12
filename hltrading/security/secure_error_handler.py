#!/usr/bin/env python3
"""
secure_error_handler.py — Secure error handling and logging system
Prevents information disclosure in error messages and stack traces
"""
import logging
import traceback
import os
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import hashlib
import secrets
from datetime import datetime

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for classification"""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    SYSTEM = "system"
    NETWORK = "network"
    DATA = "data"
    CONFIGURATION = "configuration"
    EXTERNAL_API = "external_api"
    UNKNOWN = "unknown"


@dataclass
class SecureError:
    """Secure error representation"""
    error_id: str
    message: str
    severity: ErrorSeverity
    category: ErrorCategory
    timestamp: datetime
    user_friendly_message: str
    technical_details: Optional[str] = None
    stack_trace: Optional[str] = None
    sensitive_data_removed: bool = True
    correlation_id: Optional[str] = None


class SecureErrorHandler:
    """Secure error handling system that prevents information disclosure"""

    def __init__(self, enable_detailed_logging: bool = False):
        self.enable_detailed_logging = enable_detailed_logging
        self.error_patterns = self._compile_patterns()
        self.sensitive_keywords = self._get_sensitive_keywords()
        self._setup_logging()

    def _setup_logging(self):
        """Set up secure logging configuration"""
        error_log_file = os.path.join(os.path.dirname(__file__), 'logs', 'secure_errors.log')
        os.makedirs(os.path.dirname(error_log_file), exist_ok=True)

        self.error_logger = logging.getLogger('secure_errors')
        self.error_logger.setLevel(logging.ERROR)

        file_handler = logging.FileHandler(error_log_file, mode='a')
        file_handler.setLevel(logging.ERROR)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - CorrelationID: %(correlation_id)s - %(message)s'
        )
        file_handler.setFormatter(formatter)

        self.error_logger.addHandler(file_handler)
        self.error_logger.propagate = False

    def _compile_patterns(self) -> Dict[str, re.Pattern]:
        """Compile regex patterns for detecting sensitive information"""
        return {
            'api_keys': re.compile(r'(?:api[_-]?key|apikey|api[_-]?token)\s*[:=]\s*["\']?([a-zA-Z0-9]{20,})["\']?', re.IGNORECASE),
            'private_keys': re.compile(r'(?:private[_-]?key|privatekey|pk)\s*[:=]\s*["\']?([a-zA-Z0-9]{32,})["\']?', re.IGNORECASE),
            'wallet_addresses': re.compile(r'\b(0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b'),
            'secrets': re.compile(r'(?:secret|password|pwd|pass)\s*[:=]\s*["\']?([^"\'\s]{8,})["\']?', re.IGNORECASE),
            'tokens': re.compile(r'(?:token|access[_-]?token|bearer)\s+([a-zA-Z0-9\-_\.]{20,})', re.IGNORECASE),
            'urls_with_auth': re.compile(r'(https?://[^:\s]+):([^@\s]+)@([^/\s]+)', re.IGNORECASE),
            'database_urls': re.compile(r'(?:mysql|postgres|mongodb)://[^/\s]+:[^@\s]+@[^/\s]+', re.IGNORECASE),
            'file_paths': re.compile(r'(/(?:home|Users|C:\\Users|/var)/[^/\s]+(?:/[^/\s]+)*)', re.IGNORECASE),
            'ip_addresses': re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
            'emails': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        }

    def _get_sensitive_keywords(self) -> List[str]:
        """Get list of sensitive keywords to filter"""
        return [
            'password', 'secret', 'key', 'token', 'auth', 'credential',
            'private', 'wallet', 'address', 'seed', 'mnemonic', 'phrase',
            'api_key', 'api_secret', 'access_token', 'refresh_token',
            'session', 'cookie', 'bearer', 'basic', 'digest'
        ]

    def sanitize_message(self, message: str) -> str:
        """Sanitize error message to remove sensitive information"""
        if not message:
            return "An error occurred"

        sanitized = message

        for pattern_name, pattern in self.error_patterns.items():
            sanitized = pattern.sub(lambda m: self._mask_sensitive_data(m.group(0)), sanitized)

        for keyword in self.sensitive_keywords:
            keyword_pattern = re.compile(rf'({keyword}\s*[:=]\s*)[^,\s]+', re.IGNORECASE)
            sanitized = keyword_pattern.sub(rf'\1[REDACTED]', sanitized)

        path_pattern = re.compile(r'(/[^/\s]+(?:/[^/\s]+)*)')
        sanitized = path_pattern.sub(lambda m: self._mask_path(m.group(0)), sanitized)

        if len(sanitized) > 500:
            sanitized = sanitized[:497] + "..."

        return sanitized.strip()

    def _mask_sensitive_data(self, data: str) -> str:
        """Mask sensitive data while preserving structure"""
        if not data:
            return "[REDACTED]"

        if re.match(r'^[a-zA-Z0-9]{20,}$', data):
            if len(data) > 8:
                return f"{data[:4]}...{data[-4:]}"
            return "[REDACTED]"

        if re.match(r'^(0x[a-fA-F0-9]{40}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$', data):
            if data.startswith('0x'):
                return f"{data[:6]}...{data[-6:]}"
            return f"{data[:4]}...{data[-4:]}"

        if len(data) > 3:
            return f"{data[0]}{'*' * (len(data) - 2)}{data[-1]}"
        return "[REDACTED]"

    def _mask_path(self, path: str) -> str:
        """Mask file paths to prevent directory disclosure"""
        if not path:
            return "[REDACTED_PATH]"

        parts = path.split('/')
        if len(parts) > 1:
            return f"[REDACTED_PATH]/{parts[-1]}"
        return "[REDACTED_PATH]"

    def classify_error(self, exception: Exception) -> ErrorCategory:
        """Classify error based on exception type and message"""
        exception_type = type(exception).__name__.lower()
        message = str(exception).lower()

        if any(keyword in message for keyword in ['auth', 'login', 'credential', 'unauthorized']):
            return ErrorCategory.AUTHENTICATION
        if any(keyword in message for keyword in ['forbidden', 'permission', 'access denied']):
            return ErrorCategory.AUTHORIZATION
        if any(keyword in exception_type for keyword in ['validation', 'valueerror', 'typeerror']):
            return ErrorCategory.VALIDATION
        if any(keyword in exception_type for keyword in ['connection', 'timeout', 'network']):
            return ErrorCategory.NETWORK
        if any(keyword in exception_type for keyword in ['database', 'sql', 'data']):
            return ErrorCategory.DATA
        if any(keyword in message for keyword in ['config', 'setting', 'environment']):
            return ErrorCategory.CONFIGURATION
        if any(keyword in message for keyword in ['api', 'external', 'service']):
            return ErrorCategory.EXTERNAL_API
        if any(keyword in exception_type for keyword in ['system', 'runtime', 'memory']):
            return ErrorCategory.SYSTEM
        return ErrorCategory.UNKNOWN

    def get_severity(self, exception: Exception, category: ErrorCategory) -> ErrorSeverity:
        """Determine error severity based on exception and category"""
        exception_type = type(exception).__name__.lower()

        if any(keyword in exception_type for keyword in ['systemexit', 'keyboardinterrupt']):
            return ErrorSeverity.CRITICAL
        if category in [ErrorCategory.AUTHENTICATION, ErrorCategory.AUTHORIZATION]:
            return ErrorSeverity.HIGH
        if any(keyword in exception_type for keyword in ['connectionerror', 'timeouterror']):
            return ErrorSeverity.HIGH
        if any(keyword in exception_type for keyword in ['valueerror', 'keyerror', 'indexerror']):
            return ErrorSeverity.MEDIUM
        return ErrorSeverity.LOW

    def generate_user_message(self, category: ErrorCategory, severity: ErrorSeverity) -> str:
        """Generate user-friendly error message based on category and severity"""
        messages = {
            ErrorCategory.AUTHENTICATION: {
                ErrorSeverity.HIGH: "Authentication failed. Please check your credentials and try again.",
                ErrorSeverity.MEDIUM: "There was an issue with your authentication. Please try again.",
                ErrorSeverity.LOW: "Authentication temporarily unavailable. Please try again in a moment."
            },
            ErrorCategory.AUTHORIZATION: {
                ErrorSeverity.HIGH: "You don't have permission to perform this action.",
                ErrorSeverity.MEDIUM: "Access denied for this operation.",
                ErrorSeverity.LOW: "Permission check failed. Please contact support if this persists."
            },
            ErrorCategory.VALIDATION: {
                ErrorSeverity.HIGH: "Invalid input provided. Please check your data and try again.",
                ErrorSeverity.MEDIUM: "Input validation failed. Please review your entries.",
                ErrorSeverity.LOW: "Some input values are not valid. Please correct them."
            },
            ErrorCategory.NETWORK: {
                ErrorSeverity.HIGH: "Network connection issue. Please check your internet connection.",
                ErrorSeverity.MEDIUM: "Temporary network problem. Please try again.",
                ErrorSeverity.LOW: "Network request timed out. Please retry the operation."
            },
            ErrorCategory.DATA: {
                ErrorSeverity.HIGH: "Data processing error. Please contact support.",
                ErrorSeverity.MEDIUM: "Unable to process data at this time.",
                ErrorSeverity.LOW: "Data temporarily unavailable. Please try again later."
            },
            ErrorCategory.CONFIGURATION: {
                ErrorSeverity.HIGH: "Configuration error detected. Please check your settings.",
                ErrorSeverity.MEDIUM: "System configuration issue. Please review your settings.",
                ErrorSeverity.LOW: "Configuration temporarily unavailable."
            },
            ErrorCategory.EXTERNAL_API: {
                ErrorSeverity.HIGH: "External service unavailable. Please try again later.",
                ErrorSeverity.MEDIUM: "Service temporarily experiencing issues.",
                ErrorSeverity.LOW: "External API request failed. Please retry."
            },
            ErrorCategory.SYSTEM: {
                ErrorSeverity.HIGH: "System error occurred. Please restart the application.",
                ErrorSeverity.MEDIUM: "System temporarily unavailable.",
                ErrorSeverity.LOW: "System operation failed. Please try again."
            }
        }

        return messages.get(category, {}).get(severity, "An unexpected error occurred.")

    def handle_exception(self, exception: Exception, context: Optional[str] = None) -> SecureError:
        """Handle exception securely and return sanitized error information"""
        error_id = self._generate_error_id(exception, context)
        correlation_id = self._generate_correlation_id()
        category = self.classify_error(exception)
        severity = self.get_severity(exception, category)
        user_message = self.generate_user_message(category, severity)
        sanitized_message = self.sanitize_message(str(exception))

        secure_error = SecureError(
            error_id=error_id,
            message=sanitized_message,
            severity=severity,
            category=category,
            timestamp=datetime.now(),
            user_friendly_message=user_message,
            correlation_id=correlation_id
        )

        self._log_secure_error(secure_error, exception, context)
        return secure_error

    def _generate_error_id(self, exception: Exception, context: Optional[str]) -> str:
        """Generate unique error ID for tracking"""
        error_data = f"{type(exception).__name__}:{str(exception)[:100]}:{context or ''}"
        return hashlib.sha256(error_data.encode()).hexdigest()[:16]

    def _generate_correlation_id(self) -> str:
        """Generate correlation ID for request tracking"""
        return f"err_{secrets.token_hex(8)}"

    def _log_secure_error(self, secure_error: SecureError, original_exception: Exception, context: Optional[str]):
        """Log error securely with appropriate detail level"""
        log_message = (
            f"Error ID: {secure_error.error_id}, "
            f"Category: {secure_error.category.value}, "
            f"Severity: {secure_error.severity.value}, "
            f"Context: {context or 'Unknown'}"
        )

        extra = {
            'correlation_id': secure_error.correlation_id,
            'error_id': secure_error.error_id,
            'category': secure_error.category.value,
            'severity': secure_error.severity.value
        }

        self.error_logger.error(log_message, extra=extra)

        if self.enable_detailed_logging:
            technical_details = self._extract_technical_details(original_exception, context)
            self.error_logger.error(f"Technical Details: {technical_details}", extra=extra)

    def _extract_technical_details(self, exception: Exception, context: Optional[str]) -> str:
        """Extract technical details for debugging (development only)"""
        details = {
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'context': context,
            'timestamp': datetime.now().isoformat(),
            'stack_trace': traceback.format_exc()
        }
        return str(details)

    def format_error_response(self, secure_error: SecureError, include_debug_info: bool = False) -> Dict[str, Any]:
        """Format error response for API or user display"""
        response = {
            'error': True,
            'error_id': secure_error.error_id,
            'message': secure_error.user_friendly_message,
            'severity': secure_error.severity.value,
            'category': secure_error.category.value,
            'timestamp': secure_error.timestamp.isoformat(),
            'correlation_id': secure_error.correlation_id
        }

        if secure_error.severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
            response['technical_message'] = secure_error.message

        if include_debug_info and self.enable_detailed_logging:
            response['debug_info'] = {
                'original_message': secure_error.message,
                'sanitized': not secure_error.sensitive_data_removed
            }

        return response

    def log_security_event(self, event_type: str, details: Dict[str, Any], severity: ErrorSeverity = ErrorSeverity.MEDIUM):
        """Log security events separately"""
        security_logger = logging.getLogger('security_events')
        security_logger.warning(
            f"Security Event: {event_type}, Details: {details}",
            extra={'correlation_id': self._generate_correlation_id()}
        )


secure_error_handler = SecureErrorHandler(enable_detailed_logging=False)


def handle_api_error(exception: Exception, context: Optional[str] = None) -> Dict[str, Any]:
    """Handle API errors and return formatted response"""
    secure_error = secure_error_handler.handle_exception(exception, context)
    return secure_error_handler.format_error_response(secure_error)


def handle_validation_error(exception: Exception, context: Optional[str] = None) -> Dict[str, Any]:
    """Handle validation errors with user-friendly messages"""
    secure_error = secure_error_handler.handle_exception(exception, context)
    secure_error.user_friendly_message = "Invalid input data. Please check your entries and try again."
    return secure_error_handler.format_error_response(secure_error)


def handle_system_error(exception: Exception, context: Optional[str] = None) -> Dict[str, Any]:
    """Handle system errors with appropriate user message"""
    secure_error = secure_error_handler.handle_exception(exception, context)
    secure_error.user_friendly_message = "System error occurred. Please try again or contact support."
    return secure_error_handler.format_error_response(secure_error)


def log_security_violation(violation_type: str, details: Dict[str, Any]):
    """Log security violations"""
    secure_error_handler.log_security_event(f"SECURITY_VIOLATION_{violation_type.upper()}", details, ErrorSeverity.HIGH)


class SecureErrorContext:
    """Context manager for secure error handling"""

    def __init__(self, context: str, handler: SecureErrorHandler = None):
        self.context = context
        self.handler = handler or secure_error_handler

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            secure_error = self.handler.handle_exception(exc_val, self.context)
            logger.error(f"Error in {self.context}: {secure_error.user_friendly_message}")
            return False
        return True


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
