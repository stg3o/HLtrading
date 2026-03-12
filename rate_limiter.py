#!/usr/bin/env python3
"""
rate_limiter.py — Rate limiting system for API calls and bot operations
Prevents abuse, respects exchange rate limits, and protects against DoS attacks
"""
import time
import threading
import logging
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class RateLimitType(Enum):
    """Types of rate limits"""
    EXCHANGE_API = "exchange_api"      # Exchange API rate limits
    BOT_OPERATION = "bot_operation"    # Bot internal operations
    USER_ACTION = "user_action"        # User-triggered actions
    NOTIFICATION = "notification"      # Notification sending
    STRATEGY = "strategy"              # Strategy-specific limits

@dataclass
class RateLimitConfig:
    """Configuration for a rate limit"""
    limit: int                    # Maximum number of requests
    window_seconds: int          # Time window in seconds
    burst_size: int = 1          # Maximum burst size (for token bucket)
    block_duration: int = 60     # How long to block after limit exceeded
    enabled: bool = True         # Whether this limit is active

@dataclass
class RateLimitResult:
    """Result of a rate limit check"""
    allowed: bool
    wait_time: float = 0.0
    current_count: int = 0
    reset_time: float = 0.0
    reason: str = ""

class RateLimiter:
    """Thread-safe rate limiter with multiple algorithms"""
    
    def __init__(self):
        self._limits: Dict[str, RateLimitConfig] = {}
        self._counters: Dict[str, deque] = {}
        self._token_buckets: Dict[str, Dict] = {}
        self._blocked: Dict[str, float] = {}
        self._lock = threading.RLock()
        
        # Default rate limits
        self._setup_default_limits()
    
    def _setup_default_limits(self):
        """Set up default rate limits for common operations"""
        self.set_limit("ccxt_fetch_ticker", RateLimitConfig(
            limit=120,           # Binance: 120 requests per 10 seconds
            window_seconds=10,
            burst_size=10,
            block_duration=60
        ))
        
        self.set_limit("ccxt_fetch_orderbook", RateLimitConfig(
            limit=50,            # Binance: 50 requests per 10 seconds
            window_seconds=10,
            burst_size=5,
            block_duration=60
        ))
        
        self.set_limit("ccxt_create_order", RateLimitConfig(
            limit=20,            # Binance: 20 orders per 10 seconds
            window_seconds=10,
            burst_size=3,
            block_duration=120
        ))
        
        self.set_limit("ccxt_cancel_order", RateLimitConfig(
            limit=20,            # Binance: 20 cancels per 10 seconds
            window_seconds=10,
            burst_size=3,
            block_duration=120
        ))
        
        self.set_limit("ccxt_fetch_balance", RateLimitConfig(
            limit=60,            # Binance: 60 requests per 10 seconds
            window_seconds=10,
            burst_size=5,
            block_duration=60
        ))
        
        self.set_limit("hyperliquid_place_order", RateLimitConfig(
            limit=100,           # Hyperliquid: 100 requests per minute
            window_seconds=60,
            burst_size=10,
            block_duration=120
        ))
        
        self.set_limit("hyperliquid_cancel_order", RateLimitConfig(
            limit=100,           # Hyperliquid: 100 requests per minute
            window_seconds=60,
            burst_size=10,
            block_duration=120
        ))
        
        self.set_limit("telegram_send_message", RateLimitConfig(
            limit=30,            # Telegram: 30 messages per second
            window_seconds=1,
            burst_size=5,
            block_duration=300
        ))
        
        self.set_limit("ai_api_request", RateLimitConfig(
            limit=60,            # OpenRouter: 60 requests per minute
            window_seconds=60,
            burst_size=5,
            block_duration=300
        ))
        
        self.set_limit("strategy_signal_generation", RateLimitConfig(
            limit=1000,          # Strategy: 1000 signals per minute
            window_seconds=60,
            burst_size=50,
            block_duration=60
        ))
        
        self.set_limit("user_manual_trade", RateLimitConfig(
            limit=10,            # User: 10 manual trades per minute
            window_seconds=60,
            burst_size=2,
            block_duration=300
        ))
    
    def set_limit(self, key: str, config: RateLimitConfig):
        """Set or update a rate limit configuration"""
        with self._lock:
            self._limits[key] = config
            # Initialize counters if needed
            if key not in self._counters:
                self._counters[key] = deque()
            if key not in self._token_buckets:
                self._token_buckets[key] = {
                    'tokens': config.burst_size,
                    'last_refill': time.time()
                }
    
    def get_limit(self, key: str) -> Optional[RateLimitConfig]:
        """Get the rate limit configuration for a key"""
        with self._lock:
            return self._limits.get(key)
    
    def check_limit(self, key: str, algorithm: str = "sliding_window") -> RateLimitResult:
        """
        Check if a request is allowed under the rate limit
        
        Args:
            key: Rate limit key
            algorithm: Algorithm to use ("sliding_window", "fixed_window", "token_bucket")
            
        Returns:
            RateLimitResult with allowance status and details
        """
        with self._lock:
            config = self._limits.get(key)
            if not config or not config.enabled:
                return RateLimitResult(allowed=True, reason="No limit configured")
            
            # Check if blocked
            current_time = time.time()
            if key in self._blocked and current_time < self._blocked[key]:
                block_remaining = self._blocked[key] - current_time
                return RateLimitResult(
                    allowed=False,
                    wait_time=block_remaining,
                    reason=f"Blocked for {block_remaining:.1f}s"
                )
            
            if algorithm == "sliding_window":
                return self._check_sliding_window(key, config, current_time)
            elif algorithm == "fixed_window":
                return self._check_fixed_window(key, config, current_time)
            elif algorithm == "token_bucket":
                return self._check_token_bucket(key, config, current_time)
            else:
                raise ValueError(f"Unknown algorithm: {algorithm}")
    
    def _check_sliding_window(self, key: str, config: RateLimitConfig, current_time: float) -> RateLimitResult:
        """Sliding window rate limiting algorithm"""
        counter = self._counters[key]
        
        # Remove expired entries
        cutoff_time = current_time - config.window_seconds
        while counter and counter[0] <= cutoff_time:
            counter.popleft()
        
        current_count = len(counter)
        
        if current_count >= config.limit:
            # Calculate wait time until oldest request expires
            oldest_request = counter[0] if counter else current_time
            wait_time = oldest_request + config.window_seconds - current_time
            return RateLimitResult(
                allowed=False,
                wait_time=max(0, wait_time),
                current_count=current_count,
                reset_time=oldest_request + config.window_seconds,
                reason=f"Sliding window limit exceeded: {current_count}/{config.limit}"
            )
        
        # Allow request
        counter.append(current_time)
        return RateLimitResult(
            allowed=True,
            current_count=current_count + 1,
            reset_time=current_time + config.window_seconds,
            reason="Sliding window check passed"
        )
    
    def _check_fixed_window(self, key: str, config: RateLimitConfig, current_time: float) -> RateLimitResult:
        """Fixed window rate limiting algorithm"""
        window_start = int(current_time // config.window_seconds) * config.window_seconds
        window_key = f"{key}:{window_start}"
        
        if window_key not in self._counters:
            self._counters[window_key] = deque()
        
        counter = self._counters[window_key]
        
        # Remove expired entries (shouldn't happen in fixed window, but just in case)
        cutoff_time = window_start
        while counter and counter[0] < cutoff_time:
            counter.popleft()
        
        current_count = len(counter)
        
        if current_count >= config.limit:
            # Wait until next window
            next_window_start = window_start + config.window_seconds
            wait_time = next_window_start - current_time
            return RateLimitResult(
                allowed=False,
                wait_time=max(0, wait_time),
                current_count=current_count,
                reset_time=next_window_start,
                reason=f"Fixed window limit exceeded: {current_count}/{config.limit}"
            )
        
        # Allow request
        counter.append(current_time)
        return RateLimitResult(
            allowed=True,
            current_count=current_count + 1,
            reset_time=window_start + config.window_seconds,
            reason="Fixed window check passed"
        )
    
    def _check_token_bucket(self, key: str, config: RateLimitConfig, current_time: float) -> RateLimitResult:
        """Token bucket rate limiting algorithm"""
        bucket = self._token_buckets[key]
        
        # Calculate tokens to add based on time elapsed
        time_elapsed = current_time - bucket['last_refill']
        tokens_to_add = (time_elapsed / config.window_seconds) * config.limit
        
        # Update bucket
        bucket['tokens'] = min(config.burst_size, bucket['tokens'] + tokens_to_add)
        bucket['last_refill'] = current_time
        
        current_count = config.burst_size - bucket['tokens']
        
        if bucket['tokens'] < 1.0:
            # Calculate wait time for next token
            tokens_needed = 1.0 - bucket['tokens']
            wait_time = (tokens_needed / config.limit) * config.window_seconds
            return RateLimitResult(
                allowed=False,
                wait_time=wait_time,
                current_count=int(current_count),
                reset_time=current_time + wait_time,
                reason=f"Token bucket empty: {bucket['tokens']:.2f} tokens"
            )
        
        # Allow request
        bucket['tokens'] -= 1.0
        return RateLimitResult(
            allowed=True,
            current_count=int(current_count + 1),
            reset_time=current_time + config.window_seconds,
            reason="Token bucket check passed"
        )
    
    def record_violation(self, key: str):
        """Record a rate limit violation and apply blocking"""
        with self._lock:
            config = self._limits.get(key)
            if config:
                self._blocked[key] = time.time() + config.block_duration
                logger.warning(f"Rate limit violation for {key}, blocking for {config.block_duration}s")
    
    def reset_limit(self, key: str):
        """Reset the rate limit counter for a key"""
        with self._lock:
            if key in self._counters:
                self._counters[key].clear()
            if key in self._token_buckets:
                config = self._limits.get(key)
                if config:
                    self._token_buckets[key] = {
                        'tokens': config.burst_size,
                        'last_refill': time.time()
                    }
            if key in self._blocked:
                del self._blocked[key]
    
    def get_status(self, key: str) -> Dict:
        """Get current status of a rate limit"""
        with self._lock:
            config = self._limits.get(key)
            if not config:
                return {"error": "Rate limit not configured"}
            
            counter = self._counters.get(key, deque())
            current_time = time.time()
            cutoff_time = current_time - config.window_seconds
            
            # Count active requests
            active_count = sum(1 for t in counter if t > cutoff_time)
            
            # Get bucket status
            bucket = self._token_buckets.get(key, {})
            
            # Get block status
            blocked_until = self._blocked.get(key, 0)
            is_blocked = blocked_until > current_time
            
            return {
                "key": key,
                "limit": config.limit,
                "window_seconds": config.window_seconds,
                "burst_size": config.burst_size,
                "active_count": active_count,
                "tokens_available": bucket.get('tokens', 0),
                "is_blocked": is_blocked,
                "blocked_until": blocked_until,
                "block_remaining": max(0, blocked_until - current_time) if is_blocked else 0
            }
    
    def list_limits(self) -> List[str]:
        """List all configured rate limits"""
        with self._lock:
            return list(self._limits.keys())
    
    def cleanup(self):
        """Clean up expired entries and old data"""
        with self._lock:
            current_time = time.time()
            
            # Clean up counters
            for key, counter in self._counters.items():
                config = self._limits.get(key)
                if config:
                    cutoff_time = current_time - config.window_seconds
                    while counter and counter[0] <= cutoff_time:
                        counter.popleft()
            
            # Clean up blocked entries
            self._blocked = {k: v for k, v in self._blocked.items() if v > current_time}


class RateLimitMiddleware:
    """Middleware for applying rate limits to function calls"""
    
    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter
    
    def __call__(self, limit_key: str, algorithm: str = "sliding_window", 
                 wait_if_limited: bool = False, max_wait_time: float = 5.0):
        """
        Decorator to apply rate limiting to functions
        
        Args:
            limit_key: Rate limit key to use
            algorithm: Rate limiting algorithm
            wait_if_limited: Whether to wait if rate limited
            max_wait_time: Maximum time to wait for rate limit to clear
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                # Check rate limit
                result = self.rate_limiter.check_limit(limit_key, algorithm)
                
                if not result.allowed:
                    if wait_if_limited and result.wait_time <= max_wait_time:
                        logger.info(f"Rate limited for {limit_key}, waiting {result.wait_time:.2f}s")
                        time.sleep(result.wait_time)
                        # Re-check after waiting
                        result = self.rate_limiter.check_limit(limit_key, algorithm)
                        if not result.allowed:
                            logger.warning(f"Still rate limited after waiting for {limit_key}")
                            return None
                    else:
                        logger.warning(f"Rate limit exceeded for {limit_key}: {result.reason}")
                        self.rate_limiter.record_violation(limit_key)
                        return None
                
                # Execute function
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Record violation on errors that might indicate abuse
                    if "rate limit" in str(e).lower() or "too many requests" in str(e).lower():
                        logger.error(f"Rate limit error in {func.__name__}: {e}")
                        self.rate_limiter.record_violation(limit_key)
                    raise
            
            return wrapper
        return decorator


# Global rate limiter instance
rate_limiter = RateLimiter()
rate_limit_middleware = RateLimitMiddleware(rate_limiter)

# Convenience decorators for common operations
def rate_limit_ccxt_fetch_ticker(wait_if_limited: bool = True):
    """Rate limit CCXT ticker fetch operations"""
    return rate_limit_middleware("ccxt_fetch_ticker", wait_if_limited=wait_if_limited)

def rate_limit_ccxt_fetch_orderbook(wait_if_limited: bool = True):
    """Rate limit CCXT orderbook fetch operations"""
    return rate_limit_middleware("ccxt_fetch_orderbook", wait_if_limited=wait_if_limited)

def rate_limit_ccxt_create_order(wait_if_limited: bool = True):
    """Rate limit CCXT order creation operations"""
    return rate_limit_middleware("ccxt_create_order", wait_if_limited=wait_if_limited)

def rate_limit_ccxt_cancel_order(wait_if_limited: bool = True):
    """Rate limit CCXT order cancellation operations"""
    return rate_limit_middleware("ccxt_cancel_order", wait_if_limited=wait_if_limited)

def rate_limit_hyperliquid_place_order(wait_if_limited: bool = True):
    """Rate limit Hyperliquid order placement operations"""
    return rate_limit_middleware("hyperliquid_place_order", wait_if_limited=wait_if_limited)

def rate_limit_telegram_send(wait_if_limited: bool = True):
    """Rate limit Telegram message sending"""
    return rate_limit_middleware("telegram_send_message", wait_if_limited=wait_if_limited)

def rate_limit_ai_request(wait_if_limited: bool = True):
    """Rate limit AI API requests"""
    return rate_limit_middleware("ai_api_request", wait_if_limited=wait_if_limited)

def rate_limit_strategy_signal(wait_if_limited: bool = True):
    """Rate limit strategy signal generation"""
    return rate_limit_middleware("strategy_signal_generation", wait_if_limited=wait_if_limited)

def rate_limit_user_action(wait_if_limited: bool = True):
    """Rate limit user-triggered actions"""
    return rate_limit_middleware("user_manual_trade", wait_if_limited=wait_if_limited)


if __name__ == "__main__":
    # Test the rate limiter
    import asyncio
    
    async def test_rate_limiter():
        print("Testing rate limiter...")
        
        # Test basic rate limiting
        result = rate_limiter.check_limit("test_limit")
        print(f"Initial check: {result}")
        
        # Test multiple requests
        for i in range(5):
            result = rate_limiter.check_limit("test_limit")
            print(f"Request {i+1}: allowed={result.allowed}, count={result.current_count}")
            time.sleep(0.1)
        
        # Test with decorator
        @rate_limit_ccxt_fetch_ticker()
        def test_function():
            return "Function executed"
        
        print("\nTesting decorator...")
        for i in range(3):
            result = test_function()
            print(f"Decorated function call {i+1}: {result}")
        
        # Test status
        print(f"\nStatus: {rate_limiter.get_status('ccxt_fetch_ticker')}")
        
        print("✅ Rate limiter tests completed")
    
    # Run tests
    asyncio.run(test_rate_limiter())