"""
market_regime_detector.py — Market regime detection and strategy adaptation
Implements ADX-based market regime detection with automatic strategy switching
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classifications."""
    STRONG_TREND_UP = "STRONG_TREND_UP"
    MODERATE_TREND_UP = "MODERATE_TREND_UP"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    MODERATE_TREND_DOWN = "MODERATE_TREND_DOWN"
    RANGE_BOUND = "RANGE_BOUND"
    VOLATILE_REVERSAL = "VOLATILE_REVERSAL"
    UNCERTAIN = "UNCERTAIN"


class StrategyType(Enum):
    """Strategy types for different market regimes."""
    MOMENTUM_LONG = "MOMENTUM_LONG"
    MOMENTUM_SHORT = "MOMENTUM_SHORT"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    VOLATILITY_SCALPING = "VOLATILITY_SCALPING"
    COUNTER_TREND = "COUNTER_TREND"
    HOLD_CASH = "HOLD_CASH"


@dataclass
class RegimeAnalysis:
    """Market regime analysis result."""
    timestamp: pd.Timestamp
    regime: MarketRegime
    confidence: float
    adx_value: float
    di_plus: float
    di_minus: float
    trend_strength: float
    volatility_regime: str
    volume_trend: str
    suggested_strategy: StrategyType
    strategy_confidence: float
    parameters_adjustment: dict[str, float]


@dataclass
class StrategyAdaptation:
    """Strategy adaptation parameters."""
    strategy_type: StrategyType
    entry_threshold: float
    exit_threshold: float
    position_size_multiplier: float
    stop_loss_multiplier: float
    take_profit_multiplier: float
    time_filter_active: bool
    filter_parameters: dict[str, object]


class ADXIndicator:
    """Advanced ADX (Average Directional Index) indicator implementation."""

    def __init__(self, period: int = 14):
        self.period = period

    def calculate_adx(self, data: pd.DataFrame) -> dict[str, pd.Series]:
        """Calculate ADX, +DI, and -DI indicators."""
        if len(data) < self.period:
            return self._get_default_adx_values()

        high = data['high']
        low = data['low']
        close = data['close']

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)

        plus_dm = high.diff()
        minus_dm = low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = abs(minus_dm)

        both_true = (plus_dm > minus_dm) & (minus_dm > 0)
        plus_dm[both_true] = 0
        minus_dm[both_true] = 0

        tr_smooth = tr.ewm(alpha=1/self.period, adjust=False).mean()
        plus_di_smooth = plus_dm.ewm(alpha=1/self.period, adjust=False).mean()
        minus_di_smooth = minus_dm.ewm(alpha=1/self.period, adjust=False).mean()

        plus_di = (plus_di_smooth / tr_smooth) * 100
        minus_di = (minus_di_smooth / tr_smooth) * 100

        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
        adx = dx.ewm(alpha=1/self.period, adjust=False).mean()

        return {
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'dx': dx
        }

    def _get_default_adx_values(self) -> dict[str, pd.Series]:
        """Return default ADX values for insufficient data."""
        return {
            'adx': pd.Series([20.0]),
            'plus_di': pd.Series([25.0]),
            'minus_di': pd.Series([25.0]),
            'dx': pd.Series([0.0])
        }


class MarketRegimeDetector:
    """Advanced market regime detection using multiple indicators."""

    def __init__(self):
        self.adx_indicator = ADXIndicator(period=14)
        self.regime_thresholds = {
            'strong_trend': 25.0,
            'moderate_trend': 20.0,
            'range_bound': 15.0,
            'volatile_reversal': 35.0,
        }
        self.direction_thresholds = {
            'strong_up': 25.0,
            'moderate_up': 15.0,
            'strong_down': 25.0,
            'moderate_down': 15.0,
        }

    def analyze_market_regime(self, data: pd.DataFrame) -> RegimeAnalysis:
        """Comprehensive market regime analysis."""
        if len(data) < 50:
            return self._get_default_regime_analysis(data.index[-1] if not data.empty else pd.Timestamp.now())

        try:
            adx_data = self.adx_indicator.calculate_adx(data)
            adx = adx_data['adx'].iloc[-1]
            plus_di = adx_data['plus_di'].iloc[-1]
            minus_di = adx_data['minus_di'].iloc[-1]

            volatility_regime = self._analyze_volatility_regime(data)
            volume_trend = self._analyze_volume_trend(data)
            trend_strength = self._calculate_trend_strength(plus_di, minus_di, adx)
            regime, confidence = self._classify_market_regime(adx, plus_di, minus_di, volatility_regime)
            strategy, strategy_confidence = self._suggest_strategy(regime, volatility_regime, volume_trend)
            parameters_adjustment = self._calculate_parameter_adjustments(regime, adx, volatility_regime)

            return RegimeAnalysis(
                timestamp=data.index[-1],
                regime=regime,
                confidence=confidence,
                adx_value=adx,
                di_plus=plus_di,
                di_minus=minus_di,
                trend_strength=trend_strength,
                volatility_regime=volatility_regime,
                volume_trend=volume_trend,
                suggested_strategy=strategy,
                strategy_confidence=strategy_confidence,
                parameters_adjustment=parameters_adjustment
            )

        except Exception as e:
            logger.error(f"Error in market regime analysis: {e}")
            return self._get_default_regime_analysis(data.index[-1] if not data.empty else pd.Timestamp.now())

    def _analyze_volatility_regime(self, data: pd.DataFrame) -> str:
        """Analyze current volatility regime."""
        close = data['close']
        returns = close.pct_change().dropna()
        rolling_vol = returns.rolling(window=20).std()
        current_vol = rolling_vol.iloc[-1]
        historical_vol = returns.rolling(window=100).std().dropna()
        if len(historical_vol) > 0:
            vol_percentile = (current_vol > historical_vol).mean()
            if vol_percentile > 0.8:
                return "HIGH"
            if vol_percentile > 0.3:
                return "NORMAL"
            return "LOW"
        return "NORMAL"

    def _analyze_volume_trend(self, data: pd.DataFrame) -> str:
        """Analyze volume trend direction."""
        volume = data['volume']
        if len(volume) < 20:
            return "NEUTRAL"

        vol_ma_short = volume.rolling(window=5).mean()
        vol_ma_long = volume.rolling(window=20).mean()
        current_vol = volume.iloc[-1]
        short_ma = vol_ma_short.iloc[-1]
        long_ma = vol_ma_long.iloc[-1]

        if current_vol > short_ma > long_ma:
            return "INCREASING"
        if current_vol < short_ma < long_ma:
            return "DECREASING"
        return "NEUTRAL"

    def _calculate_trend_strength(self, plus_di: float, minus_di: float, adx: float) -> float:
        """Calculate overall trend strength."""
        di_diff = abs(plus_di - minus_di)
        trend_strength = (adx * 0.6) + (di_diff * 0.4)
        return min(trend_strength, 100.0)

    def _classify_market_regime(self, adx: float, plus_di: float, minus_di: float, volatility_regime: str):
        """Classify market regime based on ADX and directional indicators."""
        di_diff = plus_di - minus_di
        if adx >= self.regime_thresholds['strong_trend']:
            if di_diff >= self.direction_thresholds['strong_up']:
                return MarketRegime.STRONG_TREND_UP, 0.9
            if di_diff <= -self.direction_thresholds['strong_down']:
                return MarketRegime.STRONG_TREND_DOWN, 0.9
        elif adx >= self.regime_thresholds['moderate_trend']:
            if di_diff >= self.direction_thresholds['moderate_up']:
                return MarketRegime.MODERATE_TREND_UP, 0.7
            if di_diff <= -self.direction_thresholds['moderate_down']:
                return MarketRegime.MODERATE_TREND_DOWN, 0.7
        elif adx <= self.regime_thresholds['range_bound']:
            if volatility_regime == "HIGH":
                return MarketRegime.VOLATILE_REVERSAL, 0.6
            return MarketRegime.RANGE_BOUND, 0.8
        elif adx >= self.regime_thresholds['volatile_reversal'] and volatility_regime == "HIGH":
            return MarketRegime.VOLATILE_REVERSAL, 0.7
        return MarketRegime.UNCERTAIN, 0.4

    def _suggest_strategy(self, regime: MarketRegime, volatility_regime: str, volume_trend: str):
        """Suggest optimal strategy based on market regime."""
        strategy_confidence = 0.8
        if regime == MarketRegime.STRONG_TREND_UP:
            return StrategyType.MOMENTUM_LONG, strategy_confidence
        if regime == MarketRegime.STRONG_TREND_DOWN:
            return StrategyType.MOMENTUM_SHORT, strategy_confidence
        if regime in [MarketRegime.MODERATE_TREND_UP, MarketRegime.MODERATE_TREND_DOWN]:
            if volatility_regime == "HIGH":
                return StrategyType.BREAKOUT, 0.7
            return StrategyType.MOMENTUM_LONG if regime == MarketRegime.MODERATE_TREND_UP else StrategyType.MOMENTUM_SHORT, 0.7
        if regime == MarketRegime.RANGE_BOUND:
            return StrategyType.MEAN_REVERSION, 0.8
        if regime == MarketRegime.VOLATILE_REVERSAL:
            if volume_trend == "INCREASING":
                return StrategyType.VOLATILITY_SCALPING, 0.6
            return StrategyType.COUNTER_TREND, 0.6
        return StrategyType.HOLD_CASH, 0.5

    def _calculate_parameter_adjustments(self, regime: MarketRegime, adx: float, volatility_regime: str) -> dict[str, float]:
        """Calculate parameter adjustments for current regime."""
        adjustments = {
            'entry_threshold': 1.0,
            'exit_threshold': 1.0,
            'position_size': 1.0,
            'stop_loss': 1.0,
            'take_profit': 1.0
        }
        if adx > 30:
            adjustments['position_size'] = 1.2
            adjustments['take_profit'] = 1.3
        elif adx < 15:
            adjustments['position_size'] = 0.7
            adjustments['stop_loss'] = 0.8

        if volatility_regime == "HIGH":
            adjustments['stop_loss'] = 1.5
            adjustments['entry_threshold'] = 1.2
        elif volatility_regime == "LOW":
            adjustments['stop_loss'] = 0.7
            adjustments['entry_threshold'] = 0.8

        if regime in [MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN]:
            adjustments['exit_threshold'] = 0.8
        elif regime == MarketRegime.RANGE_BOUND:
            adjustments['exit_threshold'] = 1.2
        return adjustments

    def _get_default_regime_analysis(self, timestamp: pd.Timestamp) -> RegimeAnalysis:
        """Return default regime analysis for insufficient data."""
        return RegimeAnalysis(
            timestamp=timestamp,
            regime=MarketRegime.UNCERTAIN,
            confidence=0.3,
            adx_value=15.0,
            di_plus=20.0,
            di_minus=20.0,
            trend_strength=0.0,
            volatility_regime="NORMAL",
            volume_trend="NEUTRAL",
            suggested_strategy=StrategyType.HOLD_CASH,
            strategy_confidence=0.3,
            parameters_adjustment={
                'entry_threshold': 1.0,
                'exit_threshold': 1.0,
                'position_size': 0.5,
                'stop_loss': 1.0,
                'take_profit': 1.0
            }
        )


class StrategyAdaptiveManager:
    """Strategy adaptation manager that switches strategies based on market regime."""

    def __init__(self):
        self.regime_detector = MarketRegimeDetector()
        self.current_strategy = StrategyType.HOLD_CASH
        self.strategy_history = []
        self.strategy_parameters = {
            StrategyType.MOMENTUM_LONG: {
                'entry_indicator': 'rsi',
                'entry_threshold': 30,
                'exit_threshold': 70,
                'time_filter': True,
                'min_trend_strength': 20
            },
            StrategyType.MOMENTUM_SHORT: {
                'entry_indicator': 'rsi',
                'entry_threshold': 70,
                'exit_threshold': 30,
                'time_filter': True,
                'min_trend_strength': 20
            },
            StrategyType.MEAN_REVERSION: {
                'entry_indicator': 'bb_position',
                'entry_threshold': 0.2,
                'exit_threshold': 0.8,
                'time_filter': False,
                'min_trend_strength': 0
            },
            StrategyType.BREAKOUT: {
                'entry_indicator': 'price',
                'entry_threshold': 1.0,
                'exit_threshold': 0.95,
                'time_filter': True,
                'min_trend_strength': 15
            },
            StrategyType.VOLATILITY_SCALPING: {
                'entry_indicator': 'atr',
                'entry_threshold': 1.5,
                'exit_threshold': 0.5,
                'time_filter': False,
                'min_trend_strength': 0
            },
            StrategyType.COUNTER_TREND: {
                'entry_indicator': 'rsi',
                'entry_threshold': 80,
                'exit_threshold': 20,
                'time_filter': False,
                'min_trend_strength': 25
            },
            StrategyType.HOLD_CASH: {
                'entry_indicator': None,
                'entry_threshold': 0,
                'exit_threshold': 0,
                'time_filter': False,
                'min_trend_strength': 0
            }
        }

    def adapt_strategy(self, data: pd.DataFrame) -> StrategyAdaptation:
        """Adapt strategy based on current market regime."""
        regime_analysis = self.regime_detector.analyze_market_regime(data)
        should_switch = self._should_switch_strategy(regime_analysis)
        if should_switch:
            self.current_strategy = regime_analysis.suggested_strategy
            self.strategy_history.append({
                'timestamp': regime_analysis.timestamp,
                'previous_strategy': self.current_strategy,
                'new_strategy': regime_analysis.suggested_strategy,
                'regime': regime_analysis.regime.value,
                'confidence': regime_analysis.confidence
            })
            logger.info(f"Switched strategy to {self.current_strategy.value} due to {regime_analysis.regime.value}")
        return self._calculate_strategy_adaptation(regime_analysis)

    def _should_switch_strategy(self, regime_analysis: RegimeAnalysis) -> bool:
        """Determine if we should switch strategies."""
        if regime_analysis.confidence < 0.5:
            return False
        if self.current_strategy == regime_analysis.suggested_strategy and regime_analysis.strategy_confidence > 0.7:
            return False
        if self.current_strategy == StrategyType.HOLD_CASH and regime_analysis.suggested_strategy != StrategyType.HOLD_CASH:
            return True
        if regime_analysis.strategy_confidence > 0.7:
            return True
        return False

    def _calculate_strategy_adaptation(self, regime_analysis: RegimeAnalysis) -> StrategyAdaptation:
        """Calculate adapted strategy parameters."""
        base_params = self.strategy_parameters[self.current_strategy]
        adjustments = regime_analysis.parameters_adjustment
        adapted_params = {
            'entry_threshold': base_params['entry_threshold'] * adjustments['entry_threshold'],
            'exit_threshold': base_params['exit_threshold'] * adjustments['exit_threshold'],
            'position_size_multiplier': adjustments['position_size'],
            'stop_loss_multiplier': adjustments['stop_loss'],
            'take_profit_multiplier': adjustments['take_profit'],
            'time_filter_active': base_params['time_filter'],
            'filter_parameters': {
                'min_trend_strength': base_params['min_trend_strength'],
                'volatility_regime': regime_analysis.volatility_regime,
                'volume_trend': regime_analysis.volume_trend
            }
        }
        return StrategyAdaptation(strategy_type=self.current_strategy, **adapted_params)

    def get_strategy_performance(self) -> dict[str, object]:
        """Get performance metrics for strategy switching."""
        if not self.strategy_history:
            return {
                'total_switches': 0,
                'current_strategy': self.current_strategy.value,
                'strategy_duration': 0
            }
        current_strategy_info = self.strategy_history[-1] if self.strategy_history else None
        return {
            'total_switches': len(self.strategy_history),
            'current_strategy': self.current_strategy.value,
            'last_switch_time': current_strategy_info['timestamp'] if current_strategy_info else None,
            'strategy_history': self.strategy_history[-10:],
            'strategy_distribution': self._calculate_strategy_distribution()
        }

    def _calculate_strategy_distribution(self) -> dict[str, int]:
        """Calculate distribution of strategy usage."""
        distribution = {}
        for switch in self.strategy_history:
            strategy = switch['new_strategy'].value
            distribution[strategy] = distribution.get(strategy, 0) + 1
        return distribution


def main():
    """Demonstrate market regime detection and strategy adaptation."""
    print("Starting Market Regime Detection Demonstration...")
    dates = pd.date_range('2024-01-01', periods=200, freq='1H')
    np.random.seed(42)

    base_price = 100
    prices = [base_price]
    volumes = []
    for i in range(1, 200):
        if i < 50:
            noise = np.random.normal(0, 0.2)
        elif i < 100:
            noise = np.random.normal(0.5, 0.3)
        elif i < 150:
            noise = np.random.normal(0, 1.0) * np.sin(i * 0.1)
        else:
            noise = np.random.normal(-0.3, 0.4)
        new_price = prices[-1] * (1 + noise / 100)
        prices.append(new_price)
        volumes.append(np.random.randint(1000, 5000))

    data = pd.DataFrame({
        'open': prices[:-1],
        'high': [p * (1 + abs(np.random.normal(0, 0.2))/100) for p in prices[:-1]],
        'low': [p * (1 - abs(np.random.normal(0, 0.2))/100) for p in prices[:-1]],
        'close': prices[1:],
        'volume': volumes
    }, index=dates[:-1])

    detector = MarketRegimeDetector()
    regime_analysis = detector.analyze_market_regime(data)
    print(f"Market Regime Analysis Results:")
    print(f"  Regime: {regime_analysis.regime.value}")
    print(f"  Confidence: {regime_analysis.confidence:.2f}")
    print(f"  ADX: {regime_analysis.adx_value:.2f}")
    print(f"  +DI: {regime_analysis.di_plus:.2f}")
    print(f"  -DI: {regime_analysis.di_minus:.2f}")
    print(f"  Trend Strength: {regime_analysis.trend_strength:.2f}")
    print(f"  Volatility Regime: {regime_analysis.volatility_regime}")
    print(f"  Volume Trend: {regime_analysis.volume_trend}")
    print(f"  Suggested Strategy: {regime_analysis.suggested_strategy.value}")
    print(f"  Strategy Confidence: {regime_analysis.strategy_confidence:.2f}")

    adapter = StrategyAdaptiveManager()
    adaptation = adapter.adapt_strategy(data)
    print(f"\nStrategy Adaptation Results:")
    print(f"  Current Strategy: {adaptation.strategy_type.value}")
    print(f"  Entry Threshold: {adaptation.entry_threshold:.2f}")
    print(f"  Exit Threshold: {adaptation.exit_threshold:.2f}")
    print(f"  Position Size Multiplier: {adaptation.position_size_multiplier:.2f}")
    print(f"  Stop Loss Multiplier: {adaptation.stop_loss_multiplier:.2f}")
    print(f"  Take Profit Multiplier: {adaptation.take_profit_multiplier:.2f}")
    print(f"  Time Filter Active: {adaptation.time_filter_active}")

    print(f"\nTesting Regime Switching:")
    for i, segment_name in [("First 50", data.iloc[:50]), ("Next 50", data.iloc[50:100]),
                           ("High Volatility", data.iloc[100:150]), ("Down Trend", data.iloc[150:])]:
        segment_analysis = detector.analyze_market_regime(segment_name)
        print(f"  {i}: {segment_analysis.regime.value} -> {segment_analysis.suggested_strategy.value}")

    print("\nMarket regime detection demonstration completed!")
    return {
        'regime_analysis': regime_analysis,
        'adaptation': adaptation,
        'performance': adapter.get_strategy_performance()
    }


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
