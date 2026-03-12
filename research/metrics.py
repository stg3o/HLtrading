"""Compatibility facade for shared backtest metrics helpers."""

from hltrading.research.metrics import (
    build_exit_breakdown,
    compute_core_backtest_stats,
    max_consecutive_losses,
    max_drawdown,
    risk_adjusted_metrics,
)

__all__ = [
    "build_exit_breakdown",
    "max_consecutive_losses",
    "max_drawdown",
    "risk_adjusted_metrics",
    "compute_core_backtest_stats",
]
