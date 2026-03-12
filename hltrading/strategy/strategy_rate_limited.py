#!/usr/bin/env python3
"""
strategy_rate_limited.py — Rate-limited strategy implementation
Integrates rate limiting with the existing strategy module to prevent API abuse
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import numpy as np
from scipy.stats import hurst_exponent
from rate_limiter import rate_limiter, rate_limit_ccxt_fetch_ticker, rate_limit_ccxt_fetch_orderbook
from input_validation import InputValidator, ValidationError

logger = logging.getLogger(__name__)

class RateLimitedStrategy:
    """Strategy wrapper with integrated rate limiting"""
    
    def __init__(self, strategy_config: Dict[str, Any]):
        """
        Initialize rate-limited strategy
        
        Args:
            strategy_config: Strategy configuration with rate limiting settings
        """
        self.config = strategy_config
        self.validator = InputValidator()
        self._setup_rate_limits()
    
    def _setup_rate_limits(self):
        """Configure strategy-specific rate limits"""
        # Strategy signal generation rate limits
        rate_limiter.set_limit("strategy_signal_generation", {
            "limit": 1000,          # 1000 signals per minute
            "window_seconds": 60,
            "burst_size": 50,
            "block_duration": 60
        })
        
        # Exchange data fetch limits
        rate_limiter.set_limit("exchange_data_fetch", {
            "limit": 100,           # 100 data fetches per minute
            "window_seconds": 60,
            "burst_size": 20,
            "block_duration": 120
        })
        
        # Order placement limits
        rate_limiter.set_limit("order_placement", {
            "limit": 50,            # 50 orders per minute
            "window_seconds": 60,
            "burst_size": 10,
            "block_duration": 300
        })
    
    @rate_limit_ccxt_fetch_ticker(wait_if_limited=True)
    async def fetch_ticker_data(self, symbol: str, exchange: Any) -> Dict[str, Any]:
        """
        Fetch ticker data with rate limiting
        
        Args:
            symbol: Trading symbol
            exchange: CCXT exchange instance
            
        Returns:
            Ticker data
        """
        try:
            # Validate inputs
            symbol = self.validator.validate_symbol(symbol, "symbol")
            
            # Fetch data with rate limiting
            ticker = await exchange.fetch_ticker(symbol)
            
            logger.debug(f"✅ Fetched ticker data for {symbol}")
            return ticker
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch ticker data for {symbol}: {e}")
            raise
    
    @rate_limit_ccxt_fetch_orderbook(wait_if_limited=True)
    async def fetch_orderbook_data(self, symbol: str, exchange: Any, limit: int = 100) -> Dict[str, Any]:
        """
        Fetch orderbook data with rate limiting
        
        Args:
            symbol: Trading symbol
            exchange: CCXT exchange instance
            limit: Number of order levels to fetch
            
        Returns:
            Orderbook data
        """
        try:
            # Validate inputs
            symbol = self.validator.validate_symbol(symbol, "symbol")
            limit = self.validator.validate_numeric(limit, "limit", min_val=1, max_val=1000)
            
            # Fetch data with rate limiting
            orderbook = await exchange.fetch_order_book(symbol, limit)
            
            logger.debug(f"✅ Fetched orderbook data for {symbol}")
            return orderbook
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch orderbook data for {symbol}: {e}")
            raise
    
    def check_strategy_rate_limit(self, strategy_name: str) -> bool:
        """
        Check if strategy signal generation is rate limited
        
        Args:
            strategy_name: Name of the strategy
            
        Returns:
            True if allowed, False if rate limited
        """
        result = rate_limiter.check_limit("strategy_signal_generation")
        
        if not result.allowed:
            logger.warning(f"Strategy {strategy_name} rate limited: {result.reason}")
            return False
        
        return True
    
    def check_order_rate_limit(self) -> bool:
        """
        Check if order placement is rate limited
        
        Returns:
            True if allowed, False if rate limited
        """
        result = rate_limiter.check_limit("order_placement")
        
        if not result.allowed:
            logger.warning(f"Order placement rate limited: {result.reason}")
            return False
        
        return True
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limit status for all strategy limits"""
        status = {}
        
        limit_keys = [
            "strategy_signal_generation",
            "exchange_data_fetch", 
            "order_placement",
            "ccxt_fetch_ticker",
            "ccxt_fetch_orderbook",
            "ccxt_create_order"
        ]
        
        for key in limit_keys:
            status[key] = rate_limiter.get_status(key)
        
        return status
    
    def reset_rate_limits(self):
        """Reset all strategy-related rate limits"""
        limit_keys = [
            "strategy_signal_generation",
            "exchange_data_fetch",
            "order_placement"
        ]
        
        for key in limit_keys:
            rate_limiter.reset_limit(key)
        
        logger.info("✅ Reset strategy rate limits")
    
    def apply_rate_limiting_to_strategy(self, strategy_func):
        """
        Decorator to apply rate limiting to strategy functions
        
        Args:
            strategy_func: Strategy function to wrap
            
        Returns:
            Rate-limited strategy function
        """
        def wrapper(*args, **kwargs):
            # Check strategy rate limit
            if not self.check_strategy_rate_limit(strategy_func.__name__):
                return None
            
            # Execute strategy function
            try:
                result = strategy_func(*args, **kwargs)
                return result
            except Exception as e:
                logger.error(f"Strategy function {strategy_func.__name__} failed: {e}")
                raise
        
        return wrapper


class RateLimitedIndicatorCalculator:
    """Rate-limited indicator calculations"""
    
    def __init__(self, rate_limiter_instance):
        self.rate_limiter = rate_limiter_instance
        self.validator = InputValidator()
    
    def calculate_indicators_with_rate_limit(self, data: pd.DataFrame, 
                                           symbol: str, 
                                           interval: str) -> Dict[str, Any]:
        """
        Calculate technical indicators with rate limiting
        
        Args:
            data: Price data
            symbol: Trading symbol
            interval: Time interval
            
        Returns:
            Calculated indicators
        """
        # Check rate limit for data processing
        result = self.rate_limiter.check_limit("exchange_data_fetch")
        if not result.allowed:
            logger.warning(f"Data processing rate limited for {symbol}: {result.reason}")
            return {}
        
        try:
            # Validate inputs
            symbol = self.validator.validate_symbol(symbol, "symbol")
            interval = self.validator.validate_string(interval, "interval", 
                                                    allowed_values=['1m', '5m', '15m', '1h', '4h', '1d'])
            
            # Calculate indicators
            indicators = self._calculate_indicators(data)
            
            logger.debug(f"✅ Calculated indicators for {symbol} {interval}")
            return indicators
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate indicators for {symbol}: {e}")
            raise
    
    def _calculate_indicators(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Calculate technical indicators"""
        if data.empty or len(data) < 20:
            return {}
        
        try:
            # Calculate basic indicators
            close = data['close'].astype(float)
            high = data['high'].astype(float)
            low = data['low'].astype(float)
            
            # Moving averages
            ma_fast = close.ewm(span=9, adjust=False).mean().iloc[-1]
            ma_slow = close.ewm(span=21, adjust=False).mean().iloc[-1]
            ma_trend = close.ewm(span=50, adjust=False).mean().iloc[-1]
            
            # RSI
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            # Keltner Channels
            atr = self._calculate_atr(high, low, close)
            kc_middle = ma_slow
            kc_upper = kc_middle + (2 * atr)
            kc_lower = kc_middle - (2 * atr)
            
            # ADX
            adx = self._calculate_adx(high, low, close)
            
            # Hurst exponent
            hurst = self._calculate_hurst_exponent(close)
            
            return {
                'ma_fast': ma_fast,
                'ma_slow': ma_slow,
                'ma_trend': ma_trend,
                'rsi': rsi,
                'kc_upper': kc_upper,
                'kc_middle': kc_middle,
                'kc_lower': kc_lower,
                'atr': atr,
                'adx': adx,
                'hurst': hurst,
                'current_price': close.iloc[-1]
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to calculate indicators: {e}")
            return {}
    
    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        """Calculate Average True Range"""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=14).mean().iloc[-1]
    
    def _calculate_adx(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        """Calculate Average Directional Index"""
        try:
            # Calculate directional movement
            plus_dm = high.diff()
            minus_dm = low.diff()
            plus_dm[plus_dm < 0] = 0
            minus_dm[minus_dm < 0] = 0
            
            # True Range
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            # Directional indicators
            tr_smooth = tr.rolling(window=14).mean()
            plus_di = 100 * (plus_dm.ewm(alpha=1/14).mean() / tr_smooth)
            minus_di = 100 * (minus_dm.ewm(alpha=1/14).mean() / tr_smooth)
            
            # ADX
            dx = (abs(plus_di - minus_di) / abs(plus_di + minus_di)) * 100
            adx = dx.ewm(alpha=1/14).mean().iloc[-1]
            
            return adx
        except:
            return 0.0
    
    def _calculate_hurst_exponent(self, prices: pd.Series) -> float:
        """Calculate Hurst exponent"""
        try:
            # Use scipy's hurst_exponent function if available
            if hasattr(hurst_exponent, '__call__'):
                return hurst_exponent(prices.values)
            else:
                # Fallback implementation
                lags = range(2, min(20, len(prices)//2))
                tau = [np.sqrt(np.std(np.subtract(prices[lag:], prices[:-lag]))) for lag in lags]
                poly = np.polyfit(np.log(lags), np.log(tau), 1)
                return poly[0]
        except:
            return 0.5  # Random walk default


# Integration with existing strategy module
def create_rate_limited_strategy_wrapper(original_strategy_class):
    """
    Create a rate-limited wrapper around an existing strategy class
    
    Args:
        original_strategy_class: Original strategy class
        
    Returns:
        Rate-limited strategy class
    """
    class RateLimitedStrategyWrapper(original_strategy_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.rate_limited_strategy = RateLimitedStrategy(self.config)
            self.indicator_calculator = RateLimitedIndicatorCalculator(rate_limiter)
        
        async def fetch_market_data(self, symbol: str, exchange: Any) -> Dict[str, Any]:
            """Fetch market data with rate limiting"""
            return await self.rate_limited_strategy.fetch_ticker_data(symbol, exchange)
        
        async def fetch_orderbook_data(self, symbol: str, exchange: Any, limit: int = 100) -> Dict[str, Any]:
            """Fetch orderbook data with rate limiting"""
            return await self.rate_limited_strategy.fetch_orderbook_data(symbol, exchange, limit)
        
        def calculate_indicators(self, data: pd.DataFrame, symbol: str, interval: str) -> Dict[str, Any]:
            """Calculate indicators with rate limiting"""
            return self.indicator_calculator.calculate_indicators_with_rate_limit(data, symbol, interval)
        
        def check_rate_limits(self) -> bool:
            """Check if strategy can proceed"""
            return self.rate_limited_strategy.check_strategy_rate_limit(self.__class__.__name__)
        
        def get_rate_limit_status(self) -> Dict[str, Any]:
            """Get rate limit status"""
            return self.rate_limited_strategy.get_rate_limit_status()
    
    return RateLimitedStrategyWrapper


if __name__ == "__main__":
    # Test the rate-limited strategy
    import pandas as pd
    
    # Create test data
    test_data = pd.DataFrame({
        'close': [100, 101, 99, 102, 101, 103, 102, 104, 103, 105],
        'high': [101, 102, 100, 103, 102, 104, 103, 105, 104, 106],
        'low': [99, 100, 98, 101, 100, 102, 101, 103, 102, 104]
    })
    
    # Test rate-limited indicator calculator
    calculator = RateLimitedIndicatorCalculator(rate_limiter)
    indicators = calculator.calculate_indicators_with_rate_limit(test_data, "ETH/USD", "1h")
    
    print(f"✅ Calculated indicators: {indicators}")
    
    # Test rate limit status
    status = rate_limiter.get_status("strategy_signal_generation")
    print(f"✅ Rate limit status: {status}")
    
    print("✅ Rate-limited strategy tests completed")