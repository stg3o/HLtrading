"""Compatibility facade for rate-limited strategy helpers."""

from hltrading.strategy import strategy_rate_limited as _impl
from hltrading.strategy.strategy_rate_limited import *  # noqa: F401,F403

asyncio = _impl.asyncio
logging = _impl.logging
time = _impl.time
Dict = _impl.Dict
List = _impl.List
Optional = _impl.Optional
Tuple = _impl.Tuple
Any = _impl.Any
pd = _impl.pd
np = _impl.np
hurst_exponent = _impl.hurst_exponent
rate_limiter = _impl.rate_limiter
rate_limit_ccxt_fetch_ticker = _impl.rate_limit_ccxt_fetch_ticker
rate_limit_ccxt_fetch_orderbook = _impl.rate_limit_ccxt_fetch_orderbook
InputValidator = _impl.InputValidator
ValidationError = _impl.ValidationError
logger = _impl.logger
