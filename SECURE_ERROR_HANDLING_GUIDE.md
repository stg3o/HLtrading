# Secure Error Handling Implementation Guide

This guide explains how to implement and use the secure error handling system to prevent information disclosure in error messages and stack traces.

## Overview

The secure error handling system provides:
- **Information disclosure prevention** - Sanitizes sensitive data from error messages
- **Error classification** - Categorizes errors for appropriate handling
- **User-friendly messages** - Provides safe error messages for end users
- **Secure logging** - Logs errors without exposing sensitive information
- **Correlation tracking** - Tracks errors across the system with unique IDs
- **Security event logging** - Separate logging for security-related events

## Quick Start

### 1. Basic Error Handling

```python
from secure_error_handler import secure_error_handler, handle_api_error

try:
    # Risky operation
    result = risky_operation()
except Exception as e:
    # Handle securely
    error_response = handle_api_error(e, "API operation")
    print(f"User message: {error_response['message']}")
    print(f"Error ID: {error_response['error_id']}")
```

### 2. Using Context Manager

```python
from secure_error_handler import SecureErrorContext

with SecureErrorContext("Data processing"):
    # Operations that might fail
    process_data()
    # Errors are automatically handled securely
```

### 3. Custom Error Handling

```python
from secure_error_handler import SecureErrorHandler

handler = SecureErrorHandler(enable_detailed_logging=True)

try:
    sensitive_operation()
except Exception as e:
    secure_error = handler.handle_exception(e, "Sensitive operation")
    response = handler.format_error_response(secure_error)
    
    # Log for debugging (development only)
    if handler.enable_detailed_logging:
        print(f"Debug: {response.get('debug_info', {})}")
```

## Error Classification

### Automatic Classification

The system automatically classifies errors based on:
- **Exception type** (ValueError, ConnectionError, etc.)
- **Error message content** (keywords like "auth", "network", etc.)
- **Context** (where the error occurred)

### Error Categories

1. **Authentication** - Login, credential, auth failures
2. **Authorization** - Permission, access denied errors
3. **Validation** - Input validation, data format errors
4. **Network** - Connection, timeout, network issues
5. **Data** - Database, SQL, data processing errors
6. **Configuration** - Config, setting, environment errors
7. **External API** - Third-party service failures
8. **System** - System, runtime, memory errors

### Error Severity Levels

- **CRITICAL** - System exit, keyboard interrupt
- **HIGH** - Auth/authz failures, connection errors
- **MEDIUM** - Validation errors, data issues
- **LOW** - Minor operational issues

## Sensitive Data Detection

### Automatically Detected Patterns

The system detects and sanitizes:
- **API keys** - `sk_test_1234567890abcdef`
- **Private keys** - Wallet keys, cryptographic keys
- **Wallet addresses** - `0x1234...5678`, `1A1zP1...`
- **Passwords** - Any password-like strings
- **Tokens** - Access tokens, bearer tokens
- **Database URLs** - Connection strings with credentials
- **File paths** - System paths that reveal directory structure
- **IP addresses** - Internal network information
- **Email addresses** - User contact information

### Sanitization Examples

```python
from secure_error_handler import SecureErrorHandler

handler = SecureErrorHandler()

# Before sanitization
"API key sk_live_1234567890abcdef is invalid"
"Database connection failed: mysql://user:password@localhost/db"
"File not found: /home/user/secrets.txt"

# After sanitization
"API key sk_live_1234...5678 is invalid"
"Database connection failed: mysql://[REDACTED]@localhost/db"
"File not found: [REDACTED_PATH]/secrets.txt"
```

## Integration Examples

### With Web Framework (Flask/FastAPI)

```python
from flask import Flask, jsonify
from secure_error_handler import handle_api_error

app = Flask(__name__)

@app.errorhandler(Exception)
def handle_error(error):
    """Global error handler"""
    error_response = handle_api_error(error, "Web API")
    return jsonify(error_response), 500

@app.route('/api/data')
def get_data():
    try:
        # API logic here
        data = fetch_data()
        return jsonify({'data': data})
    except Exception as e:
        # Specific error handling
        error_response = handle_api_error(e, "Data fetch")
        return jsonify(error_response), 400
```

### With Trading Bot

```python
from secure_error_handler import handle_system_error, log_security_violation

class TradingBot:
    async def execute_trade(self, symbol, amount, price):
        try:
            # Trading logic
            order = await self.exchange.create_order(symbol, 'limit', 'buy', amount, price)
            return order
        except Exception as e:
            # Handle trading errors securely
            if "insufficient" in str(e).lower():
                log_security_violation("INSUFFICIENT_FUNDS", {
                    'symbol': symbol,
                    'amount': amount,
                    'error': str(e)
                })
            
            error_response = handle_system_error(e, "Trade execution")
            self.logger.error(f"Trade failed: {error_response['message']}")
            return None
```

### With Strategy Module

```python
from secure_error_handler import handle_validation_error, SecureErrorContext

class Strategy:
    def validate_parameters(self, params):
        try:
            with SecureErrorContext("Parameter validation"):
                # Validation logic
                if params['risk'] > 0.1:
                    raise ValueError("Risk parameter too high")
                
                if not params['symbol']:
                    raise ValueError("Symbol cannot be empty")
                
                return True
        except Exception as e:
            error_response = handle_validation_error(e, "Strategy validation")
            self.logger.warning(f"Validation failed: {error_response['message']}")
            return False
```

### With Configuration Loading

```python
from secure_error_handler import handle_system_error

def load_configuration():
    try:
        # Config loading logic
        config = load_config_from_file('config.json')
        validate_config(config)
        return config
    except FileNotFoundError as e:
        error_response = handle_system_error(e, "Config file loading")
        logger.error(f"Config file not found: {error_response['message']}")
        return get_default_config()
    except Exception as e:
        error_response = handle_system_error(e, "Config validation")
        logger.error(f"Config validation failed: {error_response['message']}")
        raise
```

## Secure Logging

### Error Log Format

```python
# Secure error logs include:
# - Error ID for tracking
# - Category and severity
# - Correlation ID for request tracing
# - Sanitized error message

# Example log entry:
# 2026-03-10 21:23:30,123 - secure_errors - ERROR - 
# CorrelationID: err_a1b2c3d4e5f6g7h8 - 
# Error ID: a1b2c3d4e5f6g7h8, Category: authentication, 
# Severity: high, Context: API validation
```

### Security Event Logging

```python
from secure_error_handler import log_security_violation

# Log security violations
log_security_violation("INVALID_API_KEY", {
    'api_key': 'sk_test_1234567890abcdef',
    'ip_address': '192.168.1.100',
    'user_agent': 'Mozilla/5.0...',
    'timestamp': '2026-03-10T21:23:30Z'
})

log_security_violation("UNAUTHORIZED_ACCESS", {
    'endpoint': '/api/admin',
    'user_id': 'user123',
    'attempted_action': 'delete_user'
})
```

## Development vs Production

### Development Mode

```python
# Enable detailed logging for development
handler = SecureErrorHandler(enable_detailed_logging=True)

try:
    risky_operation()
except Exception as e:
    secure_error = handler.handle_exception(e, "Development test")
    response = handler.format_error_response(secure_error, include_debug_info=True)
    
    # Debug information available
    debug_info = response.get('debug_info', {})
    print(f"Original message: {debug_info.get('original_message')}")
    print(f"Sanitized: {debug_info.get('sanitized')}")
```

### Production Mode

```python
# Production - minimal information disclosure
handler = SecureErrorHandler(enable_detailed_logging=False)

try:
    production_operation()
except Exception as e:
    secure_error = handler.handle_exception(e, "Production operation")
    response = handler.format_error_response(secure_error)
    
    # Only safe information exposed
    print(f"User message: {response['message']}")
    print(f"Error ID: {response['error_id']}")  # For support tickets
```

## Error Response Format

### Standard Error Response

```python
{
    "error": True,
    "error_id": "a1b2c3d4e5f6g7h8",
    "message": "Authentication failed. Please check your credentials and try again.",
    "severity": "high",
    "category": "authentication",
    "timestamp": "2026-03-10T21:23:30.123456",
    "correlation_id": "err_a1b2c3d4e5f6g7h8",
    "technical_message": "API key sk_live_1234...5678 is invalid"  # Only for high/critical severity
}
```

### Development Error Response

```python
{
    "error": True,
    "error_id": "a1b2c3d4e5f6g7h8",
    "message": "Authentication failed. Please check your credentials and try again.",
    "severity": "high",
    "category": "authentication",
    "timestamp": "2026-03-10T21:23:30.123456",
    "correlation_id": "err_a1b2c3d4e5f6g7h8",
    "technical_message": "API key sk_live_1234...5678 is invalid",
    "debug_info": {
        "original_message": "API key sk_live_1234567890abcdef is invalid",
        "sanitized": True
    }
}
```

## Best Practices

### 1. Always Use Secure Error Handling

```python
# ❌ DON'T do this
try:
    risky_operation()
except Exception as e:
    return {"error": str(e)}  # Exposes sensitive information

# ✅ DO this
try:
    risky_operation()
except Exception as e:
    return handle_api_error(e, "Operation context")
```

### 2. Provide Context

```python
# ❌ Generic context
handle_api_error(e, "Error")

# ✅ Specific context
handle_api_error(e, "User authentication")
handle_api_error(e, "Database connection")
handle_api_error(e, "API rate limit exceeded")
```

### 3. Log Security Events

```python
# Log potential security issues
if "unauthorized" in str(e).lower():
    log_security_violation("UNAUTHORIZED_ACCESS", {
        'error': str(e),
        'context': context,
        'timestamp': datetime.now().isoformat()
    })
```

### 4. Use Appropriate Severity

```python
# For user-facing errors
handle_validation_error(e, context)

# For system errors
handle_system_error(e, context)

# For API errors
handle_api_error(e, context)
```

### 5. Track Errors for Support

```python
# Include error ID in user messages
error_response = handle_api_error(e, context)
user_message = f"{error_response['message']} (Error ID: {error_response['error_id']})"

# Users can provide error ID for support
print(f"Contact support with Error ID: {error_response['error_id']}")
```

## Monitoring and Alerting

### Error Rate Monitoring

```python
from collections import defaultdict
import time

class ErrorMonitor:
    def __init__(self):
        self.error_counts = defaultdict(int)
        self.last_reset = time.time()
    
    def record_error(self, error_response):
        """Record error for monitoring"""
        category = error_response.get('category')
        severity = error_response.get('severity')
        
        key = f"{category}_{severity}"
        self.error_counts[key] += 1
        
        # Alert on high error rates
        if self.error_counts[key] > 10:
            self.send_alert(f"High error rate: {key} - {self.error_counts[key]} errors")
    
    def send_alert(self, message):
        """Send alert (email, Slack, etc.)"""
        # Implementation depends on your alerting system
        pass
```

### Security Event Monitoring

```python
class SecurityMonitor:
    def __init__(self):
        self.security_events = []
    
    def log_security_event(self, event_type, details):
        """Log security events for monitoring"""
        event = {
            'type': event_type,
            'details': details,
            'timestamp': time.time()
        }
        self.security_events.append(event)
        
        # Alert on security violations
        if event_type.startswith('SECURITY_VIOLATION'):
            self.send_security_alert(event)
    
    def send_security_alert(self, event):
        """Send security alert"""
        # Implementation depends on your security monitoring
        pass
```

## Testing Error Handling

### Unit Tests

```python
import unittest
from secure_error_handler import SecureErrorHandler

class TestSecureErrorHandling(unittest.TestCase):
    def setUp(self):
        self.handler = SecureErrorHandler()
    
    def test_sensitive_data_sanitization(self):
        """Test that sensitive data is properly sanitized"""
        test_cases = [
            ("API key sk_test_1234567890abcdef", "API key sk_test_1234...5678"),
            ("Password: secret123", "Password: [REDACTED]"),
            ("File: /home/user/secrets.txt", "File: [REDACTED_PATH]/secrets.txt")
        ]
        
        for original, expected in test_cases:
            sanitized = self.handler.sanitize_message(original)
            self.assertIn(expected, sanitized)
    
    def test_error_classification(self):
        """Test error classification"""
        auth_error = ValueError("Authentication failed")
        category = self.handler.classify_error(auth_error)
        self.assertEqual(category, ErrorCategory.AUTHENTICATION)
    
    def test_user_message_generation(self):
        """Test user-friendly message generation"""
        secure_error = self.handler.handle_exception(
            ValueError("Invalid input"), 
            "Test context"
        )
        self.assertIn("Please check your entries", secure_error.user_friendly_message)

if __name__ == '__main__':
    unittest.main()
```

### Integration Tests

```python
def test_api_error_handling():
    """Test API error handling integration"""
    from flask import Flask
    from secure_error_handler import handle_api_error
    
    app = Flask(__name__)
    
    @app.route('/test')
    def test_endpoint():
        raise ValueError("API key sk_test_1234567890abcdef is invalid")
    
    with app.test_client() as client:
        response = client.get('/test')
        data = response.get_json()
        
        # Verify error response structure
        assert data['error'] is True
        assert 'error_id' in data
        assert 'message' in data
        assert 'correlation_id' in data
        
        # Verify sensitive data is sanitized
        assert 'sk_test_1234567890abcdef' not in data['message']
        assert 'sk_test_1234...5678' in data['message']

if __name__ == '__main__':
    test_api_error_handling()
```

This secure error handling system ensures that sensitive information is never exposed in error messages while providing adequate debugging information for developers and helpful guidance for end users.