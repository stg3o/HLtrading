"""Compatibility facade for low-level volatility helpers."""

from hltrading.shared.volatility_core import (
    absolute_returns_autocorrelation,
    annualized_log_volatility,
    atr_consistency_confidence,
    multi_timeframe_volatility_trend,
    simple_volatility_trend,
)

__all__ = [
    "annualized_log_volatility",
    "absolute_returns_autocorrelation",
    "atr_consistency_confidence",
    "simple_volatility_trend",
    "multi_timeframe_volatility_trend",
]
