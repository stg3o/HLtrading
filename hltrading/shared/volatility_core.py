"""Shared low-level volatility helper primitives."""
from __future__ import annotations

import numpy as np
import pandas as pd


def annualized_log_volatility(close: pd.Series, lookback: int | None = None) -> float:
    """Calculate annualized volatility from log returns."""
    series = close if lookback is None else close.tail(lookback)
    log_returns = np.log(series / series.shift(1)).dropna()
    return log_returns.std() * np.sqrt(252)


def absolute_returns_autocorrelation(close: pd.Series, min_points: int) -> float:
    """Calculate lag-1 autocorrelation of absolute percentage returns."""
    returns = close.pct_change().dropna()
    abs_returns = abs(returns)
    if len(abs_returns) > min_points:
        correlation = abs_returns.autocorr(lag=1)
        return correlation if not pd.isna(correlation) else 0.0
    return 0.0


def atr_consistency_confidence(atr_values: dict[str, float] | list[float], zero_mean_default: float) -> float:
    """Measure confidence from consistency across ATR windows."""
    values = list(atr_values.values()) if isinstance(atr_values, dict) else list(atr_values)
    std_dev = np.std(values)
    mean_atr = np.mean(values)
    if mean_atr == 0:
        return zero_mean_default
    consistency = 1.0 - (std_dev / mean_atr)
    return max(0.0, min(1.0, consistency))


def simple_volatility_trend(atr_fast: float, atr_slow: float) -> str:
    """Two-window volatility trend classification."""
    if atr_fast > atr_slow:
        return "increasing"
    if atr_fast < atr_slow:
        return "decreasing"
    return "stable"


def multi_timeframe_volatility_trend(atr_fast: float, atr_mid: float, atr_slow: float) -> str:
    """Three-window volatility trend classification."""
    short_trend = "increasing" if atr_fast > atr_mid else "decreasing"
    medium_trend = "increasing" if atr_mid > atr_slow else "decreasing"
    if short_trend == "increasing" and medium_trend == "increasing":
        return "strongly_increasing"
    if short_trend == "decreasing" and medium_trend == "decreasing":
        return "strongly_decreasing"
    if short_trend != medium_trend:
        return "diverging"
    return "stable"


__all__ = [
    "annualized_log_volatility",
    "absolute_returns_autocorrelation",
    "atr_consistency_confidence",
    "simple_volatility_trend",
    "multi_timeframe_volatility_trend",
]
