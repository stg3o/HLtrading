# Rate Limiting Implementation Guide

This guide explains how to implement and use the rate limiting system for the crypto futures scalping bot.

## Overview

The rate limiting system provides:
- **Exchange API protection** - Prevents hitting exchange rate limits
- **Bot operation limits** - Controls internal bot operations
- **User action limits** - Prevents user abuse
- **Multiple algorithms** - Sliding window, fixed window, and token bucket
- **Automatic blocking** - Blocks after violations for recovery
- **Thread-safe operations** - Safe for concurrent bot operations

## Quick Start

### 1. Basic Rate Limiting

```python
from rate_limiter import rate_limiter

# Check if a request is allowed
result = rate_limiter.check_limit("ccxt_fetch_ticker")
if result.allowed:
    # Make the API call
    ticker = await exchange.fetch_ticker("ETH/USD")
else:
    print(f"Rate limited: wait {result.wait_time} seconds")
```

### 2. Using Decorators

```python
from rate_limiter import rate_limit_ccxt_fetch_ticker

@rate_limit_ccxt_fetch_ticker()
async def fetch_eth_ticker():
    return await exchange.fetch_ticker("ETH/USD")

# The decorator automatically handles rate limiting
ticker = await fetch_eth_ticker()
```

### 3. Rate-Limited Strategy

```python
from strategy_rate_limited import RateLimitedStrategy

# Create rate-limited strategy
strategy_config = {"strategy_type": "mean_reversion"}
rate_limited_strategy = RateLimitedStrategy(strategy_config)

# Fetch data with rate limiting
ticker = await rate_limited_strategy.fetch_ticker_data("ETH/USD", exchange)
```

## Rate Limiting Algorithms

### Sliding Window (Recommended)
- **Best for**: Exchange API calls, real-time operations
- **Advantages**: Smooth rate limiting, no burst at window boundaries
- **Example**: 120 requests per 10 seconds

### Fixed Window
- **Best for**: Batch operations, predictable limits
- **Advantages**: Simple to understand, predictable reset times
- **Example**: 1000 requests per minute

### Token Bucket
- **Best for**: Bursty traffic with sustained limits
- **Advantages**: Allows bursts while maintaining average rate
- **Example**: 100 tokens, refill 10 per second

## Default Rate Limits

### Exchange API Limits
- **Binance ticker fetch**: 120/10s (burst: 10)
- **Binance orderbook**: 50/10s (burst: 5)
- **Binance order creation**: 20/10s (burst: 3)
- **Binance order cancellation**: 20/10s (burst: 3)
- **Binance balance fetch**: 60/10s (burst: 5)

### Hyperliquid Limits
- **Order placement**: 100/60s (burst: 10)
- **Order cancellation**: 100/60s (burst: 10)

### Bot Operation Limits
- **Strategy signals**: 1000/60s (burst: 50)
- **User manual trades**: 10/60s (burst: 2)

### External Service Limits
- **Telegram messages**: 30/1s (burst: 5)
- **AI API requests**: 60/60s (burst: 5)

## Configuration

### Custom Rate Limits

```python
from rate_limiter import rate_limiter
from rate_limiter import RateLimitConfig

# Set custom rate limit
rate_limiter.set_limit("custom_operation", RateLimitConfig(
    limit=50,              # Maximum requests
    window_seconds=60,     # Time window
    burst_size=10,         # Burst allowance
    block_duration=120,    # Block time after violation
    enabled=True           # Enable/disable
))
```

### Strategy-Specific Limits

```python
from strategy_rate_limited import RateLimitedStrategy

# Configure strategy limits
strategy_config = {
    "rate_limits": {
        "signal_generation": {"limit": 500, "window": 60},
        "data_fetching": {"limit": 200, "window": 60},
        "order_placement": {"limit": 25, "window": 60}
    }
}

rate_limited_strategy = RateLimitedStrategy(strategy_config)
```

## Integration Examples

### With Existing Strategy Module

```python
from strategy_rate_limited import create_rate_limited_strategy_wrapper
from strategy import MeanReversionStrategy

# Wrap existing strategy
RateLimitedMeanReversion = create_rate_limited_strategy_wrapper(MeanReversionStrategy)

# Use as normal
strategy = RateLimitedMeanReversion(config)
ticker = await strategy.fetch_market_data("ETH/USD", exchange)
```

### With Trading Bot

```python
from rate_limiter import rate_limit_ccxt_create_order

class TradingBot:
    @rate_limit_ccxt_create_order()
    async def place_order(self, symbol, side, amount, price):
        """Place order with rate limiting"""
        return await self.exchange.create_order(symbol, 'limit', side, amount, price)
    
    async def execute_strategy(self):
        """Execute strategy with rate limiting checks"""
        if not self.rate_limiter.check_limit("strategy_signal_generation").allowed:
            return
        
        # Strategy logic here
        signal = self.generate_signal()
        if signal:
            await self.place_order(signal.symbol, signal.side, signal.amount, signal.price)
```

### With Notification System

```python
from rate_limiter import rate_limit_telegram_send

class NotificationManager:
    @rate_limit_telegram_send()
    async def send_trade_notification(self, message):
        """Send notification with rate limiting"""
        return await self.telegram_bot.send_message(self.chat_id, message)
    
    async def send_error_notification(self, error):
        """Send error notification (lower priority)"""
        # Use different rate limit for errors
        result = self.rate_limiter.check_limit("error_notification")
        if result.allowed:
            await self.send_trade_notification(f"ERROR: {error}")
```

## Monitoring and Management

### Check Rate Limit Status

```python
# Get status for specific limit
status = rate_limiter.get_status("ccxt_fetch_ticker")
print(f"Active count: {status['active_count']}")
print(f"Limit: {status['limit']}")
print(f"Is blocked: {status['is_blocked']}")

# List all configured limits
limits = rate_limiter.list_limits()
print(f"Configured limits: {limits}")

# Get all strategy-related status
strategy_status = rate_limited_strategy.get_rate_limit_status()
```

### Reset Rate Limits

```python
# Reset specific limit
rate_limiter.reset_limit("ccxt_fetch_ticker")

# Reset all strategy limits
rate_limited_strategy.reset_rate_limits()

# Clean up expired data
rate_limiter.cleanup()
```

### Handle Rate Limit Violations

```python
try:
    result = rate_limiter.check_limit("critical_operation")
    if not result.allowed:
        # Handle rate limiting
        if result.wait_time < 5.0:  # Wait if reasonable
            await asyncio.sleep(result.wait_time)
            # Retry operation
        else:
            # Skip operation or use cached data
            logger.warning(f"Operation skipped due to rate limiting")
            return None
    else:
        # Proceed with operation
        return await perform_operation()
        
except Exception as e:
    # Record violation on API errors
    if "rate limit" in str(e).lower():
        rate_limiter.record_violation("critical_operation")
        raise
```

## Best Practices

### 1. Use Appropriate Algorithms
- **Sliding window** for exchange APIs (smooth limiting)
- **Token bucket** for bursty operations (allows spikes)
- **Fixed window** for batch operations (predictable)

### 2. Set Conservative Limits
- Start with exchange documentation limits
- Add safety margin (20-30% below max)
- Monitor and adjust based on actual usage

### 3. Handle Violations Gracefully
- Implement retry logic with backoff
- Use cached data when rate limited
- Log violations for monitoring

### 4. Monitor Rate Limit Usage
- Log rate limit status periodically
- Alert on frequent violations
- Track effectiveness of limits

### 5. Test Rate Limiting
- Simulate high-frequency scenarios
- Test violation handling
- Verify blocking and recovery

## Troubleshooting

### Common Issues

**"Rate limit exceeded" errors:**
- Check if limits are too conservative
- Verify algorithm choice (sliding vs fixed window)
- Monitor actual API usage patterns

**Frequent blocking:**
- Increase block_duration for recovery
- Add more conservative safety margins
- Check for runaway loops causing excessive calls

**Performance impact:**
- Use async rate limiting for I/O operations
- Cache rate limit checks when possible
- Consider local rate limiting for high-frequency operations

### Debug Rate Limiting

```python
# Enable debug logging
import logging
logging.getLogger('rate_limiter').setLevel(logging.DEBUG)

# Monitor rate limit usage
import time

def monitor_rate_limits():
    while True:
        status = rate_limiter.get_status("ccxt_fetch_ticker")
        print(f"Ticker limit: {status['active_count']}/{status['limit']}")
        time.sleep(10)
```

## Security Considerations

### 1. Prevent DoS Attacks
- Set reasonable burst sizes
- Implement blocking after violations
- Monitor for unusual traffic patterns

### 2. Protect Sensitive Operations
- Use stricter limits for order placement
- Add additional validation for user actions
- Log all rate limit violations

### 3. Avoid Rate Limit Bypass
- Don't expose rate limit status to users
- Validate all inputs before rate limit checks
- Use consistent rate limit keys

## Performance Optimization

### 1. Batch Operations
```python
# Instead of individual calls
for symbol in symbols:
    await fetch_ticker(symbol)  # Rate limited individually

# Use batch operations when possible
await fetch_multiple_tickers(symbols)  # Single rate limit check
```

### 2. Cache Results
```python
from functools import lru_cache

@lru_cache(maxsize=100)
@rate_limit_ccxt_fetch_ticker()
async def fetch_cached_ticker(symbol):
    return await exchange.fetch_ticker(symbol)
```

### 3. Parallel Rate Limiting
```python
# Use different rate limit keys for parallel operations
@rate_limit_ccxt_fetch_ticker()
async def fetch_ticker_primary(symbol):
    return await exchange.fetch_ticker(symbol)

@rate_limit_ccxt_fetch_ticker()
async def fetch_ticker_secondary(symbol):
    return await backup_exchange.fetch_ticker(symbol)
```

## Integration with Monitoring

### Prometheus Metrics
```python
from prometheus_client import Counter, Gauge

# Rate limit violation counter
rate_limit_violations = Counter('rate_limit_violations_total', 
                               ['limit_type', 'exchange'])

# Current active requests gauge
active_requests = Gauge('active_requests', 
                       ['limit_type'])

def record_rate_limit_violation(limit_type, exchange):
    rate_limit_violations.labels(limit_type=limit_type, exchange=exchange).inc()
```

### Health Checks
```python
def check_rate_limit_health():
    """Check if rate limits are healthy"""
    critical_limits = [
        "ccxt_fetch_ticker",
        "ccxt_create_order", 
        "hyperliquid_place_order"
    ]
    
    for limit in critical_limits:
        status = rate_limiter.get_status(limit)
        if status['active_count'] > status['limit'] * 0.8:
            logger.warning(f"Rate limit {limit} at 80% capacity")
```

This rate limiting system provides comprehensive protection against API abuse while maintaining bot performance and reliability.