"""Compatibility facade for shared backtesting simulation helpers."""

from hltrading.research.simulator import (
    run_mean_reversion_simulation,
    run_supertrend_simulation,
)

__all__ = [
    "run_supertrend_simulation",
    "run_mean_reversion_simulation",
]
