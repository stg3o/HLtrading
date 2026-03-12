#!/usr/bin/env python3
"""
config_validator.py — Runtime configuration validation wrapper
Provides runtime validation for configuration changes and user inputs
"""
import logging
from typing import Any, Dict, List, Optional, Union
from input_validation import InputValidator, ValidationError

logger = logging.getLogger(__name__)

class ConfigValidator:
    """Runtime configuration validator"""
    
    def __init__(self):
        self.validator = InputValidator()
        self.validation_rules = self._load_validation_rules()
    
    def _load_validation_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load validation rules for all configuration parameters"""
        return {
            # Risk Management
            'RISK_PER_TRADE': {
                'type': 'number',
                'min_val': 0.001,  # Minimum 0.1%
                'max_val': 0.10,   # Maximum 10%
                'description': 'Risk per trade percentage'
            },
            'STOP_LOSS_PCT': {
                'type': 'number',
                'min_val': 0.0001,  # Minimum 0.01%
                'max_val': 0.20,    # Maximum 20%
                'description': 'Stop loss percentage'
            },
            'TAKE_PROFIT_PCT': {
                'type': 'number',
                'min_val': 0.0001,  # Minimum 0.01%
                'max_val': 0.50,    # Maximum 50%
                'description': 'Take profit percentage'
            },
            'MAX_OPEN_POSITIONS': {
                'type': 'number',
                'min_val': 1,
                'max_val': 50,
                'description': 'Maximum open positions'
            },
            'MAX_DAILY_LOSS': {
                'type': 'number',
                'min_val': 0.01,   # Minimum 1%
                'max_val': 0.50,   # Maximum 50%
                'description': 'Maximum daily loss percentage'
            },
            'MAX_DRAWDOWN': {
                'type': 'number',
                'min_val': 0.01,   # Minimum 1%
                'max_val': 0.80,   # Maximum 80%
                'description': 'Maximum drawdown percentage'
            },
            
            # Trading Parameters
            'TESTNET': {
                'type': 'boolean',
                'description': 'Testnet mode flag'
            },
            'TRADING_MODE': {
                'type': 'string',
                'allowed_values': ['live', 'paper', 'backtest'],
                'description': 'Trading mode'
            },
            
            # Strategy Parameters
            'KC_PERIOD': {
                'type': 'number',
                'min_val': 5,
                'max_val': 50,
                'description': 'Keltner Channel period'
            },
            'KC_SCALAR': {
                'type': 'number',
                'min_val': 0.5,
                'max_val': 3.0,
                'description': 'Keltner Channel scalar'
            },
            'MA_FAST': {
                'type': 'number',
                'min_val': 3,
                'max_val': 50,
                'description': 'Fast EMA period'
            },
            'MA_SLOW': {
                'type': 'number',
                'min_val': 10,
                'max_val': 100,
                'description': 'Slow EMA period'
            },
            'MA_TREND': {
                'type': 'number',
                'min_val': 20,
                'max_val': 200,
                'description': 'Trend EMA period'
            },
            'RSI_PERIOD': {
                'type': 'number',
                'min_val': 5,
                'max_val': 50,
                'description': 'RSI period'
            },
            'RSI_OVERSOLD': {
                'type': 'number',
                'min_val': 10,
                'max_val': 50,
                'description': 'RSI oversold threshold'
            },
            'RSI_OVERBOUGHT': {
                'type': 'number',
                'min_val': 50,
                'max_val': 90,
                'description': 'RSI overbought threshold'
            },
            
            # AI Parameters
            'AI_CONFIDENCE_THRESHOLD': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 1.0,
                'description': 'AI confidence threshold'
            },
            'AI_LOCAL_FALLBACK_THRESHOLD': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 1.0,
                'description': 'AI local fallback threshold'
            },
            
            # Regime Detection
            'ADX_MR_MAX': {
                'type': 'number',
                'min_val': 10,
                'max_val': 50,
                'description': 'ADX maximum for mean reversion'
            },
            'HURST_MR_MAX': {
                'type': 'number',
                'min_val': 0.4,
                'max_val': 0.8,
                'description': 'Hurst maximum for mean reversion'
            },
            
            # Edge and Kelly Parameters
            'MIN_EDGE': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 0.2,
                'description': 'Minimum edge for trade entry'
            },
            'KELLY_FRACTION': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 1.0,
                'description': 'Kelly fraction for position sizing'
            },
            'MIN_ENTRY_QUALITY': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 1.0,
                'description': 'Minimum entry quality score'
            },
            'OBI_GATE': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 1.0,
                'description': 'Order book imbalance gate threshold'
            },
            'VOL_MIN_RATIO': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 2.0,
                'description': 'Minimum volume ratio'
            },
            
            # HL Parameters
            'HL_MAX_POSITION_USD': {
                'type': 'number',
                'min_val': 10.0,
                'max_val': 10000.0,
                'description': 'Maximum position size in USD'
            },
            'HL_LEVERAGE': {
                'type': 'number',
                'min_val': 1,
                'max_val': 20,
                'description': 'Hyperliquid leverage'
            },
            'HL_FEE_RATE': {
                'type': 'number',
                'min_val': 0.0,
                'max_val': 0.01,  # Maximum 1%
                'description': 'Hyperliquid fee rate'
            },
            
            # File Paths
            'STATE_FILE': {
                'type': 'string',
                'description': 'State file path'
            },
            'TRADES_FILE': {
                'type': 'string',
                'description': 'Trades file path'
            },
            'SIGNALS_LOG': {
                'type': 'string',
                'description': 'Signals log file path'
            },
            'BEST_CONFIGS_FILE': {
                'type': 'string',
                'description': 'Best configs file path'
            },
        }
    
    def validate_parameter(self, param_name: str, value: Any) -> Any:
        """
        Validate a single configuration parameter
        
        Args:
            param_name: Name of the parameter
            value: Value to validate
            
        Returns:
            Validated value
            
        Raises:
            ValidationError: If validation fails
        """
        if param_name not in self.validation_rules:
            logger.warning(f"Unknown parameter: {param_name}")
            return value
        
        rule = self.validation_rules[param_name]
        
        try:
            validated_value = self.validator.validate_config_value(
                value=value,
                field_name=param_name,
                value_type=rule['type'],
                min_val=rule.get('min_val'),
                max_val=rule.get('max_val'),
                allowed_values=rule.get('allowed_values')
            )
            
            logger.debug(f"✅ Validated {param_name}: {validated_value}")
            return validated_value
            
        except ValidationError as e:
            logger.error(f"❌ Validation failed for {param_name}: {e}")
            raise
    
    def validate_coin_parameter(self, coin_name: str, param_name: str, value: Any) -> Any:
        """
        Validate a coin-specific parameter
        
        Args:
            coin_name: Name of the coin
            param_name: Name of the parameter
            value: Value to validate
            
        Returns:
            Validated value
            
        Raises:
            ValidationError: If validation fails
        """
        full_param_name = f"{coin_name}.{param_name}"
        
        # Coin-specific validation rules
        coin_rules = {
            'ticker': {
                'type': 'string',
                'allowed_values': ['1m', '5m', '15m', '1h', '4h', '1d'],
                'description': 'Trading interval'
            },
            'interval': {
                'type': 'string',
                'allowed_values': ['1m', '5m', '15m', '1h', '4h', '1d'],
                'description': 'Trading interval'
            },
            'period': {
                'type': 'string',
                'allowed_values': ['7d', '30d', '60d', '90d', '365d'],
                'description': 'Data period'
            },
            'strategy_type': {
                'type': 'string',
                'allowed_values': ['mean_reversion', 'supertrend'],
                'description': 'Strategy type'
            },
            'hl_size': {
                'type': 'number',
                'min_val': 0.0001,
                'max_val': 10000,
                'description': 'HL position size'
            },
            'stop_loss_pct': {
                'type': 'number',
                'min_val': 0.0001,
                'max_val': 0.20,
                'description': 'Coin-specific stop loss'
            },
            'take_profit_pct': {
                'type': 'number',
                'min_val': 0.0001,
                'max_val': 0.50,
                'description': 'Coin-specific take profit'
            },
            'st_period': {
                'type': 'number',
                'min_val': 5,
                'max_val': 50,
                'description': 'SuperTrend period'
            },
            'st_multiplier': {
                'type': 'number',
                'min_val': 1.0,
                'max_val': 5.0,
                'description': 'SuperTrend multiplier'
            },
            'rsi_oversold': {
                'type': 'number',
                'min_val': 10,
                'max_val': 50,
                'description': 'Coin-specific RSI oversold'
            },
            'rsi_overbought': {
                'type': 'number',
                'min_val': 50,
                'max_val': 90,
                'description': 'Coin-specific RSI overbought'
            },
            'kc_scalar': {
                'type': 'number',
                'min_val': 0.5,
                'max_val': 3.0,
                'description': 'Coin-specific KC scalar'
            },
            'ma_trend_filter': {
                'type': 'boolean',
                'description': 'Coin-specific MA trend filter'
            },
            'enabled': {
                'type': 'boolean',
                'description': 'Coin enabled flag'
            },
            'max_bars_in_trade': {
                'type': 'number',
                'min_val': 1,
                'max_val': 1000,
                'description': 'Maximum bars in trade'
            },
        }
        
        if param_name not in coin_rules:
            logger.warning(f"Unknown coin parameter: {full_param_name}")
            return value
        
        rule = coin_rules[param_name]
        
        try:
            validated_value = self.validator.validate_config_value(
                value=value,
                field_name=full_param_name,
                value_type=rule['type'],
                min_val=rule.get('min_val'),
                max_val=rule.get('max_val'),
                allowed_values=rule.get('allowed_values')
            )
            
            logger.debug(f"✅ Validated {full_param_name}: {validated_value}")
            return validated_value
            
        except ValidationError as e:
            logger.error(f"❌ Validation failed for {full_param_name}: {e}")
            raise
    
    def validate_entire_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate entire configuration dictionary
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            Validated configuration
            
        Raises:
            ValidationError: If validation fails
        """
        validated_config = {}
        
        # Validate top-level parameters
        for param_name, value in config.items():
            if param_name in self.validation_rules:
                validated_config[param_name] = self.validate_parameter(param_name, value)
            else:
                validated_config[param_name] = value
        
        # Validate coin configurations
        if 'COINS' in config:
            validated_coins = {}
            for coin_name, coin_config in config['COINS'].items():
                if isinstance(coin_config, dict):
                    validated_coin = {}
                    for param_name, value in coin_config.items():
                        validated_coin[param_name] = self.validate_coin_parameter(
                            coin_name, param_name, value
                        )
                    validated_coins[coin_name] = validated_coin
                else:
                    validated_coins[coin_name] = coin_config
            validated_config['COINS'] = validated_coins
        
        logger.info("✅ Configuration validation completed successfully")
        return validated_config
    
    def validate_runtime_change(self, param_name: str, old_value: Any, new_value: Any) -> Any:
        """
        Validate a runtime configuration change
        
        Args:
            param_name: Name of the parameter being changed
            old_value: Current value
            new_value: New value to set
            
        Returns:
            Validated new value
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            validated_value = self.validate_parameter(param_name, new_value)
            
            # Additional runtime-specific checks
            if param_name == 'RISK_PER_TRADE':
                if new_value > old_value * 2:
                    logger.warning(f"⚠️  Large increase in RISK_PER_TRADE: {old_value} → {new_value}")
            
            if param_name == 'MAX_OPEN_POSITIONS':
                if new_value > old_value * 1.5:
                    logger.warning(f"⚠️  Large increase in MAX_OPEN_POSITIONS: {old_value} → {new_value}")
            
            logger.info(f"✅ Runtime change validated: {param_name} = {validated_value}")
            return validated_value
            
        except ValidationError as e:
            logger.error(f"❌ Runtime change validation failed for {param_name}: {e}")
            raise
    
    def validate_user_input(self, input_type: str, value: Any, context: str = "") -> Any:
        """
        Validate user input from CLI or web interface
        
        Args:
            input_type: Type of input ('number', 'string', 'boolean', etc.)
            value: User input value
            context: Context for error messages
            
        Returns:
            Validated value
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            validated_value = self.validator.validate_config_value(
                value=value,
                field_name=context or input_type,
                value_type=input_type
            )
            
            logger.debug(f"✅ User input validated: {validated_value}")
            return validated_value
            
        except ValidationError as e:
            logger.error(f"❌ User input validation failed: {e}")
            raise
    
    def get_validation_report(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a validation report for the configuration
        
        Args:
            config: Configuration to analyze
            
        Returns:
            Validation report with status and issues
        """
        report = {
            'status': 'valid',
            'issues': [],
            'warnings': [],
            'validated_parameters': 0,
            'total_parameters': 0
        }
        
        # Count total parameters
        total_params = len(config)
        if 'COINS' in config:
            total_params += sum(len(coin_config) for coin_config in config['COINS'].values() 
                              if isinstance(coin_config, dict))
        
        report['total_parameters'] = total_params
        
        try:
            validated_config = self.validate_entire_config(config)
            report['validated_parameters'] = len([k for k in validated_config.keys() 
                                                if k in self.validation_rules])
            
            # Check for potential issues
            if 'RISK_PER_TRADE' in validated_config:
                risk = validated_config['RISK_PER_TRADE']
                if risk > 0.05:  # More than 5%
                    report['warnings'].append(f"High RISK_PER_TRADE: {risk}")
            
            if 'MAX_OPEN_POSITIONS' in validated_config:
                max_pos = validated_config['MAX_OPEN_POSITIONS']
                if max_pos > 10:
                    report['warnings'].append(f"High MAX_OPEN_POSITIONS: {max_pos}")
            
            if 'COINS' in validated_config:
                enabled_coins = [name for name, config in validated_config['COINS'].items() 
                               if config.get('enabled', False)]
                if len(enabled_coins) > 10:
                    report['warnings'].append(f"Many enabled coins: {len(enabled_coins)}")
        
        except ValidationError as e:
            report['status'] = 'invalid'
            report['issues'].append(str(e))
        
        return report


# Global validator instance
config_validator = ConfigValidator()

# Convenience functions for common validation tasks
def validate_config_parameter(param_name: str, value: Any) -> Any:
    """Validate a single configuration parameter"""
    return config_validator.validate_parameter(param_name, value)

def validate_coin_parameter(coin_name: str, param_name: str, value: Any) -> Any:
    """Validate a coin-specific parameter"""
    return config_validator.validate_coin_parameter(coin_name, param_name, value)

def validate_runtime_config_change(param_name: str, old_value: Any, new_value: Any) -> Any:
    """Validate a runtime configuration change"""
    return config_validator.validate_runtime_change(param_name, old_value, new_value)

def validate_user_input(input_type: str, value: Any, context: str = "") -> Any:
    """Validate user input from CLI or web interface"""
    return config_validator.validate_user_input(input_type, value, context)

def get_config_validation_report(config: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a validation report for the configuration"""
    return config_validator.get_validation_report(config)


if __name__ == "__main__":
    # Test the validator
    validator = ConfigValidator()
    
    # Test parameter validation
    try:
        result = validator.validate_parameter('RISK_PER_TRADE', 0.05)
        print(f"✅ RISK_PER_TRADE validation: {result}")
        
        result = validator.validate_parameter('TESTNET', True)
        print(f"✅ TESTNET validation: {result}")
        
        # Test coin parameter validation
        result = validator.validate_coin_parameter('ETH', 'ticker', 'ETH-USD')
        print(f"✅ ETH.ticker validation: {result}")
        
        # Test validation report
        test_config = {
            'RISK_PER_TRADE': 0.05,
            'TESTNET': True,
            'COINS': {
                'ETH': {'ticker': 'ETH-USD', 'enabled': True}
            }
        }
        
        report = validator.get_validation_report(test_config)
        print(f"✅ Validation report: {report}")
        
        print("✅ All validation tests passed")
        
    except ValidationError as e:
        print(f"❌ Validation error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")