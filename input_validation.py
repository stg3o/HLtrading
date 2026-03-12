#!/usr/bin/env python3
"""
input_validation.py — Comprehensive input validation for all user inputs and configuration values
Provides validation functions to prevent injection attacks, malformed data, and configuration errors.
"""
import re
import ipaddress
import logging
from typing import Any, Dict, List, Optional, Union, Callable
from urllib.parse import urlparse
import os

logger = logging.getLogger(__name__)

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

class InputValidator:
    """Comprehensive input validation class"""
    
    # Common patterns
    SAFE_STRING_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]+$')
    ALPHANUMERIC_PATTERN = re.compile(r'^[a-zA-Z0-9]+$')
    NUMERIC_PATTERN = re.compile(r'^[0-9]+(\.[0-9]+)?$')
    
    # Crypto-specific patterns
    WALLET_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')
    SYMBOL_PATTERN = re.compile(r'^[A-Z0-9_]+$')
    
    # Network patterns
    URL_PATTERN = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:[-\w.]|(?:%[\da-fA-F]{2}))+'  # domain name
        r'(?::\d+)?'  # optional port
        r'(?:[/?:].*)?$'  # optional path, query, fragment
    )
    
    @staticmethod
    def validate_string(value: Any, field_name: str, max_length: int = 255, 
                       pattern: Optional[re.Pattern] = None, 
                       required: bool = True) -> str:
        """
        Validate string input
        
        Args:
            value: Input value to validate
            field_name: Name of the field for error messages
            max_length: Maximum allowed length
            pattern: Optional regex pattern to match against
            required: Whether the field is required
            
        Returns:
            Validated string value
            
        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            if required:
                raise ValidationError(f"{field_name} is required")
            return ""
        
        if not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string")
        
        # Strip whitespace
        value = value.strip()
        
        if not value and required:
            raise ValidationError(f"{field_name} cannot be empty")
        
        if len(value) > max_length:
            raise ValidationError(f"{field_name} cannot exceed {max_length} characters")
        
        # Check for dangerous characters
        dangerous_chars = ['<', '>', '&', '"', "'", '\\', '\0', '\n', '\r', '\t']
        for char in dangerous_chars:
            if char in value:
                raise ValidationError(f"{field_name} contains invalid character: {char}")
        
        # Check pattern if provided
        if pattern and not pattern.match(value):
            raise ValidationError(f"{field_name} contains invalid characters")
        
        return value
    
    @staticmethod
    def validate_numeric(value: Any, field_name: str, min_val: Optional[float] = None,
                        max_val: Optional[float] = None, required: bool = True) -> float:
        """
        Validate numeric input
        
        Args:
            value: Input value to validate
            field_name: Name of the field for error messages
            min_val: Minimum allowed value
            max_val: Maximum allowed value
            required: Whether the field is required
            
        Returns:
            Validated numeric value
            
        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            if required:
                raise ValidationError(f"{field_name} is required")
            return 0.0
        
        # Convert to float
        try:
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    if required:
                        raise ValidationError(f"{field_name} cannot be empty")
                    return 0.0
                value = float(value)
            elif isinstance(value, (int, float)):
                value = float(value)
            else:
                raise ValidationError(f"{field_name} must be a number")
        except (ValueError, TypeError):
            raise ValidationError(f"{field_name} must be a valid number")
        
        # Check bounds
        if min_val is not None and value < min_val:
            raise ValidationError(f"{field_name} must be at least {min_val}")
        
        if max_val is not None and value > max_val:
            raise ValidationError(f"{field_name} cannot exceed {max_val}")
        
        # Check for infinity or NaN
        if not (float('-inf') < value < float('inf')):
            raise ValidationError(f"{field_name} must be a finite number")
        
        return value
    
    @staticmethod
    def validate_boolean(value: Any, field_name: str, required: bool = True) -> bool:
        """
        Validate boolean input
        
        Args:
            value: Input value to validate
            field_name: Name of the field for error messages
            required: Whether the field is required
            
        Returns:
            Validated boolean value
            
        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            if required:
                raise ValidationError(f"{field_name} is required")
            return False
        
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            value = value.strip().lower()
            if value in ['true', '1', 'yes', 'on']:
                return True
            elif value in ['false', '0', 'no', 'off']:
                return False
        
        if isinstance(value, (int, float)):
            return bool(value)
        
        raise ValidationError(f"{field_name} must be a boolean value")
    
    @staticmethod
    def validate_wallet_address(address: Any, field_name: str = "wallet_address") -> str:
        """
        Validate cryptocurrency wallet address
        
        Args:
            address: Wallet address to validate
            field_name: Name of the field for error messages
            
        Returns:
            Validated wallet address
            
        Raises:
            ValidationError: If validation fails
        """
        address = InputValidator.validate_string(address, field_name, max_length=64)
        
        if not InputValidator.WALLET_ADDRESS_PATTERN.match(address):
            raise ValidationError(f"{field_name} is not a valid wallet address")
        
        return address.lower()
    
    @staticmethod
    def validate_symbol(symbol: Any, field_name: str = "symbol") -> str:
        """
        Validate trading symbol
        
        Args:
            symbol: Trading symbol to validate
            field_name: Name of the field for error messages
            
        Returns:
            Validated symbol
            
        Raises:
            ValidationError: If validation fails
        """
        symbol = InputValidator.validate_string(symbol, field_name, max_length=20)
        
        if not InputValidator.SYMBOL_PATTERN.match(symbol):
            raise ValidationError(f"{field_name} contains invalid characters")
        
        return symbol.upper()
    
    @staticmethod
    def validate_url(url: Any, field_name: str = "url") -> str:
        """
        Validate URL input
        
        Args:
            url: URL to validate
            field_name: Name of the field for error messages
            
        Returns:
            Validated URL
            
        Raises:
            ValidationError: If validation fails
        """
        url = InputValidator.validate_string(url, field_name, max_length=500)
        
        if not InputValidator.URL_PATTERN.match(url):
            raise ValidationError(f"{field_name} is not a valid URL")
        
        # Parse URL to validate components
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValidationError(f"{field_name} must have a valid scheme and domain")
        
        # Check for dangerous schemes
        if parsed.scheme not in ['http', 'https']:
            raise ValidationError(f"{field_name} must use http or https scheme")
        
        return url
    
    @staticmethod
    def validate_file_path(path: Any, field_name: str = "file_path", 
                          must_exist: bool = False, must_be_file: bool = True) -> str:
        """
        Validate file path
        
        Args:
            path: File path to validate
            field_name: Name of the field for error messages
            must_exist: Whether the file/directory must exist
            must_be_file: Whether it must be a file (vs directory)
            
        Returns:
            Validated file path
            
        Raises:
            ValidationError: If validation fails
        """
        path = InputValidator.validate_string(path, field_name, max_length=500)
        
        # Prevent directory traversal attacks
        normalized_path = os.path.normpath(path)
        if '..' in normalized_path or normalized_path.startswith('/'):
            raise ValidationError(f"{field_name} contains invalid path characters")
        
        if must_exist:
            if must_be_file and not os.path.isfile(path):
                raise ValidationError(f"{field_name} does not exist or is not a file")
            elif not must_be_file and not os.path.exists(path):
                raise ValidationError(f"{field_name} does not exist")
        
        return path
    
    @staticmethod
    def validate_config_value(value: Any, field_name: str, value_type: str,
                            min_val: Optional[float] = None, max_val: Optional[float] = None,
                            allowed_values: Optional[List] = None) -> Any:
        """
        Validate configuration value based on type
        
        Args:
            value: Value to validate
            field_name: Name of the field for error messages
            value_type: Type of the value ('string', 'number', 'boolean', 'list', 'dict')
            min_val: Minimum allowed value (for numbers)
            max_val: Maximum allowed value (for numbers)
            allowed_values: List of allowed values
            
        Returns:
            Validated value
            
        Raises:
            ValidationError: If validation fails
        """
        if value_type == 'string':
            validated = InputValidator.validate_string(value, field_name)
        elif value_type == 'number':
            validated = InputValidator.validate_numeric(value, field_name, min_val, max_val)
        elif value_type == 'boolean':
            validated = InputValidator.validate_boolean(value, field_name)
        elif value_type == 'list':
            if not isinstance(value, list):
                raise ValidationError(f"{field_name} must be a list")
            validated = value
        elif value_type == 'dict':
            if not isinstance(value, dict):
                raise ValidationError(f"{field_name} must be a dictionary")
            validated = value
        else:
            raise ValidationError(f"Unknown validation type: {value_type}")
        
        # Check allowed values
        if allowed_values is not None and validated not in allowed_values:
            raise ValidationError(f"{field_name} must be one of: {', '.join(map(str, allowed_values))}")
        
        return validated
    
    @staticmethod
    def sanitize_sql_input(value: str) -> str:
        """
        Sanitize input for SQL queries (additional protection)
        
        Args:
            value: Input value to sanitize
            
        Returns:
            Sanitized value
        """
        if not isinstance(value, str):
            value = str(value)
        
        # Remove SQL injection patterns
        sql_injection_patterns = [
            r"(\b(select|insert|update|delete|drop|create|alter|exec|execute)\b)",
            r"(\b(union|or|and)\b\s*\d+\s*=\s*\d+)",
            r"('.*'|\".*\")",
            r"(--|#|\/\*|\*\/)",
        ]
        
        for pattern in sql_injection_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise ValidationError("Input contains potentially dangerous SQL patterns")
        
        return value
    
    @staticmethod
    def validate_risk_parameters(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate risk management parameters
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Validated configuration
            
        Raises:
            ValidationError: If validation fails
        """
        validated_config = {}
        
        # Validate risk per trade
        risk_per_trade = InputValidator.validate_numeric(
            config.get('RISK_PER_TRADE'), 
            'RISK_PER_TRADE', 
            min_val=0.001,  # Minimum 0.1%
            max_val=0.10,   # Maximum 10%
        )
        validated_config['RISK_PER_TRADE'] = risk_per_trade
        
        # Validate stop loss percentage
        stop_loss_pct = InputValidator.validate_numeric(
            config.get('STOP_LOSS_PCT'),
            'STOP_LOSS_PCT',
            min_val=0.0001,  # Minimum 0.01%
            max_val=0.20,    # Maximum 20%
        )
        validated_config['STOP_LOSS_PCT'] = stop_loss_pct
        
        # Validate take profit percentage
        take_profit_pct = InputValidator.validate_numeric(
            config.get('TAKE_PROFIT_PCT'),
            'TAKE_PROFIT_PCT',
            min_val=0.0001,  # Minimum 0.01%
            max_val=0.50,    # Maximum 50%
        )
        validated_config['TAKE_PROFIT_PCT'] = take_profit_pct
        
        # Validate maximum open positions
        max_open_positions = InputValidator.validate_numeric(
            config.get('MAX_OPEN_POSITIONS'),
            'MAX_OPEN_POSITIONS',
            min_val=1,
            max_val=50,
        )
        validated_config['MAX_OPEN_POSITIONS'] = int(max_open_positions)
        
        # Validate maximum daily loss
        max_daily_loss = InputValidator.validate_numeric(
            config.get('MAX_DAILY_LOSS'),
            'MAX_DAILY_LOSS',
            min_val=0.01,   # Minimum 1%
            max_val=0.50,   # Maximum 50%
        )
        validated_config['MAX_DAILY_LOSS'] = max_daily_loss
        
        # Validate maximum drawdown
        max_drawdown = InputValidator.validate_numeric(
            config.get('MAX_DRAWDOWN'),
            'MAX_DRAWDOWN',
            min_val=0.01,   # Minimum 1%
            max_val=0.80,   # Maximum 80%
        )
        validated_config['MAX_DRAWDOWN'] = max_drawdown
        
        return validated_config
    
    @staticmethod
    def validate_trading_parameters(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate trading parameters
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Validated configuration
            
        Raises:
            ValidationError: If validation fails
        """
        validated_config = {}
        
        # Validate testnet flag
        testnet = InputValidator.validate_boolean(
            config.get('TESTNET'),
            'TESTNET'
        )
        validated_config['TESTNET'] = testnet
        
        # Validate trading mode
        trading_mode = InputValidator.validate_string(
            config.get('TRADING_MODE', 'live'),
            'TRADING_MODE',
            allowed_values=['live', 'paper', 'backtest']
        )
        validated_config['TRADING_MODE'] = trading_mode
        
        return validated_config
    
    @staticmethod
    def validate_api_credentials(credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate API credentials
        
        Args:
            credentials: Dictionary containing API credentials
            
        Returns:
            Validated credentials
            
        Raises:
            ValidationError: If validation fails
        """
        validated_credentials = {}
        
        # Validate wallet address
        if 'HL_WALLET_ADDRESS' in credentials:
            wallet_address = InputValidator.validate_wallet_address(
                credentials['HL_WALLET_ADDRESS'],
                'HL_WALLET_ADDRESS'
            )
            validated_credentials['HL_WALLET_ADDRESS'] = wallet_address
        
        # Validate private key (basic format check)
        if 'HL_PRIVATE_KEY' in credentials:
            private_key = InputValidator.validate_string(
                credentials['HL_PRIVATE_KEY'],
                'HL_PRIVATE_KEY',
                max_length=100
            )
            # Basic format validation (should be hex string)
            if not re.match(r'^[a-fA-F0-9]+$', private_key):
                raise ValidationError("HL_PRIVATE_KEY must be a hexadecimal string")
            validated_credentials['HL_PRIVATE_KEY'] = private_key
        
        # Validate API keys
        if 'OPENROUTER_API_KEY' in credentials:
            api_key = InputValidator.validate_string(
                credentials['OPENROUTER_API_KEY'],
                'OPENROUTER_API_KEY',
                max_length=200
            )
            validated_credentials['OPENROUTER_API_KEY'] = api_key
        
        if 'TELEGRAM_BOT_TOKEN' in credentials:
            bot_token = InputValidator.validate_string(
                credentials['TELEGRAM_BOT_TOKEN'],
                'TELEGRAM_BOT_TOKEN',
                max_length=100
            )
            validated_credentials['TELEGRAM_BOT_TOKEN'] = bot_token
        
        if 'TELEGRAM_CHAT_ID' in credentials:
            chat_id = InputValidator.validate_string(
                credentials['TELEGRAM_CHAT_ID'],
                'TELEGRAM_CHAT_ID',
                max_length=50
            )
            validated_credentials['TELEGRAM_CHAT_ID'] = chat_id
        
        return validated_credentials
    
    @staticmethod
    def validate_coin_config(coin_config: Dict[str, Any], coin_name: str) -> Dict[str, Any]:
        """
        Validate individual coin configuration
        
        Args:
            coin_config: Coin configuration dictionary
            coin_name: Name of the coin
            
        Returns:
            Validated coin configuration
            
        Raises:
            ValidationError: If validation fails
        """
        validated_config = {}
        
        # Validate ticker symbol
        ticker = InputValidator.validate_symbol(
            coin_config.get('ticker'),
            f'{coin_name}.ticker'
        )
        validated_config['ticker'] = ticker
        
        # Validate interval
        interval = InputValidator.validate_string(
            coin_config.get('interval'),
            f'{coin_name}.interval',
            allowed_values=['1m', '5m', '15m', '1h', '4h', '1d']
        )
        validated_config['interval'] = interval
        
        # Validate period
        period = InputValidator.validate_string(
            coin_config.get('period'),
            f'{coin_name}.period',
            allowed_values=['7d', '30d', '60d', '90d', '365d']
        )
        validated_config['period'] = period
        
        # Validate strategy type
        strategy_type = InputValidator.validate_string(
            coin_config.get('strategy_type'),
            f'{coin_name}.strategy_type',
            allowed_values=['mean_reversion', 'supertrend']
        )
        validated_config['strategy_type'] = strategy_type
        
        # Validate numeric parameters
        if 'hl_size' in coin_config:
            hl_size = InputValidator.validate_numeric(
                coin_config['hl_size'],
                f'{coin_name}.hl_size',
                min_val=0.0001,
                max_val=10000
            )
            validated_config['hl_size'] = hl_size
        
        if 'stop_loss_pct' in coin_config:
            stop_loss = InputValidator.validate_numeric(
                coin_config['stop_loss_pct'],
                f'{coin_name}.stop_loss_pct',
                min_val=0.0001,
                max_val=0.20
            )
            validated_config['stop_loss_pct'] = stop_loss
        
        if 'take_profit_pct' in coin_config:
            take_profit = InputValidator.validate_numeric(
                coin_config['take_profit_pct'],
                f'{coin_name}.take_profit_pct',
                min_val=0.0001,
                max_val=0.50
            )
            validated_config['take_profit_pct'] = take_profit
        
        return validated_config
    
    @staticmethod
    def validate_entire_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate entire configuration dictionary
        
        Args:
            config: Complete configuration dictionary
            
        Returns:
            Validated configuration
            
        Raises:
            ValidationError: If validation fails
        """
        validated_config = {}
        
        # Validate risk parameters
        if any(key in config for key in ['RISK_PER_TRADE', 'STOP_LOSS_PCT', 'TAKE_PROFIT_PCT']):
            validated_config.update(InputValidator.validate_risk_parameters(config))
        
        # Validate trading parameters
        if any(key in config for key in ['TESTNET', 'TRADING_MODE']):
            validated_config.update(InputValidator.validate_trading_parameters(config))
        
        # Validate API credentials
        credentials = {k: v for k, v in config.items() if k in [
            'HL_WALLET_ADDRESS', 'HL_PRIVATE_KEY', 'OPENROUTER_API_KEY',
            'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'
        ]}
        if credentials:
            validated_config.update(InputValidator.validate_api_credentials(credentials))
        
        # Validate coin configurations
        if 'COINS' in config:
            validated_coins = {}
            for coin_name, coin_config in config['COINS'].items():
                if isinstance(coin_config, dict):
                    validated_coins[coin_name] = InputValidator.validate_coin_config(
                        coin_config, coin_name
                    )
            validated_config['COINS'] = validated_coins
        
        # Copy other validated values
        for key, value in config.items():
            if key not in validated_config and key not in ['COINS']:
                validated_config[key] = value
        
        logger.info("✅ Configuration validation completed successfully")
        return validated_config


def validate_and_sanitize_config(config_module):
    """
    Decorator to validate and sanitize configuration modules
    
    Args:
        config_module: Configuration module to validate
        
    Returns:
        Validated configuration module
        
    Raises:
        ValidationError: If validation fails
    """
    try:
        # Extract configuration values
        config_dict = {}
        for attr in dir(config_module):
            if not attr.startswith('_'):
                value = getattr(config_module, attr)
                if isinstance(value, (str, int, float, bool, dict, list)):
                    config_dict[attr] = value
        
        # Validate the configuration
        validated_config = InputValidator.validate_entire_config(config_dict)
        
        # Update the module with validated values
        for key, value in validated_config.items():
            setattr(config_module, key, value)
        
        logger.info("✅ Configuration module validation completed")
        return config_module
        
    except ValidationError as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error during configuration validation: {e}")
        raise ValidationError(f"Configuration validation error: {e}")


# Example usage and testing
if __name__ == "__main__":
    # Test basic validation
    validator = InputValidator()
    
    try:
        # Test string validation
        result = validator.validate_string("test_string", "test_field")
        print(f"✅ String validation: {result}")
        
        # Test numeric validation
        result = validator.validate_numeric(0.05, "risk", min_val=0.001, max_val=0.1)
        print(f"✅ Numeric validation: {result}")
        
        # Test wallet address validation
        result = validator.validate_wallet_address("0x1234567890abcdef1234567890abcdef12345678")
        print(f"✅ Wallet validation: {result}")
        
        print("✅ All validation tests passed")
        
    except ValidationError as e:
        print(f"❌ Validation error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")