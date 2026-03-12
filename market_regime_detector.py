"""Compatibility facade for market-regime helpers."""

from hltrading.strategy.market_regime_detector import (
    ADXIndicator,
    MarketRegime,
    MarketRegimeDetector,
    RegimeAnalysis,
    StrategyAdaptation,
    StrategyAdaptiveManager,
    StrategyType,
    logger,
    main,
    np,
    pd,
)

__all__ = [
    "pd",
    "np",
    "logger",
    "MarketRegime",
    "StrategyType",
    "RegimeAnalysis",
    "StrategyAdaptation",
    "ADXIndicator",
    "MarketRegimeDetector",
    "StrategyAdaptiveManager",
    "main",
]
