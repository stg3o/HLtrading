"""
multi_timeframe_strategy.py — Multi-timeframe confirmation strategy
Implements multi-timeframe analysis for better signal validation and entry timing
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Timeframe(Enum):
    """Available timeframes for analysis."""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


class SignalDirection(Enum):
    """Signal direction types."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass
class Signal:
    """Trading signal data structure."""
    timestamp: pd.Timestamp
    direction: SignalDirection
    strength: float  # 0.0 to 1.0
    timeframe: Timeframe
    indicators: Dict[str, float]
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class MultiTimeframeSignal:
    """Multi-timeframe signal with confirmation levels."""
    timestamp: pd.Timestamp
    primary_direction: SignalDirection
    confirmation_score: float  # 0.0 to 1.0
    primary_signal: Signal
    supporting_signals: List[Signal]
    conflicting_signals: List[Signal]
    recommended_position_size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class MultiTimeframeAnalyzer:
    """Multi-timeframe analysis engine."""
    
    def __init__(self):
        # Timeframe hierarchy for different assets
        self.timeframe_hierarchy = {
            'SOL': [Timeframe.M15, Timeframe.H1, Timeframe.H4],
            'ETH': [Timeframe.H1, Timeframe.H4, Timeframe.D1],
            'BTC': [Timeframe.H4, Timeframe.D1, Timeframe.W1],
            'default': [Timeframe.M15, Timeframe.H1, Timeframe.H4]
        }
        
        # Confirmation thresholds
        self.confirmation_thresholds = {
            'minimum': 0.6,    # Minimum confirmation score for entry
            'strong': 0.8,      # Strong confirmation for larger position
            'very_strong': 0.9  # Very strong confirmation for maximum position
        }
    
    def get_timeframes_for_asset(self, asset: str) -> List[Timeframe]:
        """Get appropriate timeframes for a specific asset."""
        return self.timeframe_hierarchy.get(asset, self.timeframe_hierarchy['default'])
    
    def analyze_multi_timeframe(self, 
                              data_dict: Dict[Timeframe, pd.DataFrame],
                              asset: str) -> Optional[MultiTimeframeSignal]:
        """Analyze multiple timeframes and generate consolidated signal."""
        
        timeframes = self.get_timeframes_for_asset(asset)
        signals = []
        
        # Generate signals for each timeframe
        for timeframe in timeframes:
            if timeframe in data_dict and not data_dict[timeframe].empty:
                signal = self._generate_signal(data_dict[timeframe], timeframe)
                if signal:
                    signals.append(signal)
        
        if not signals:
            return None
        
        # Consolidate signals
        return self._consolidate_signals(signals, asset)
    
    def _generate_signal(self, data: pd.DataFrame, timeframe: Timeframe) -> Optional[Signal]:
        """Generate signal for a single timeframe."""
        if len(data) < 50:  # Need minimum data points
            return None
        
        try:
            # Calculate indicators
            indicators = self._calculate_indicators(data)
            
            # Determine signal direction and strength
            direction, strength = self._determine_signal_direction(indicators, timeframe)
            
            if direction == SignalDirection.NEUTRAL:
                return None
            
            current_price = data['close'].iloc[-1]
            
            # Calculate dynamic stop loss and take profit
            sl_tp = self._calculate_sl_tp(data, direction, current_price)
            
            return Signal(
                timestamp=data.index[-1],
                direction=direction,
                strength=strength,
                timeframe=timeframe,
                indicators=indicators,
                price=current_price,
                stop_loss=sl_tp['stop_loss'],
                take_profit=sl_tp['take_profit']
            )
            
        except Exception as e:
            logger.error(f"Error generating signal for {timeframe.value}: {e}")
            return None
    
    def _calculate_indicators(self, data: pd.DataFrame) -> Dict[str, float]:
        """Calculate technical indicators for signal generation."""
        close = data['close']
        high = data['high']
        low = data['low']
        
        # Moving Averages
        ma_20 = close.rolling(window=20).mean().iloc[-1]
        ma_50 = close.rolling(window=50).mean().iloc[-1]
        ma_200 = close.rolling(window=200).mean().iloc[-1] if len(data) >= 200 else np.nan
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        # MACD
        exp1 = close.ewm(span=12).mean()
        exp2 = close.ewm(span=26).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=9).mean()
        macd_histogram = macd - signal_line
        macd_val = macd.iloc[-1]
        macd_signal = signal_line.iloc[-1]
        macd_hist = macd_histogram.iloc[-1]
        
        # Bollinger Bands
        bb_middle = close.rolling(window=20).mean().iloc[-1]
        bb_std = close.rolling(window=20).std().iloc[-1]
        bb_upper = bb_middle + (bb_std * 2)
        bb_lower = bb_middle - (bb_std * 2)
        bb_position = (close.iloc[-1] - bb_lower) / (bb_upper - bb_lower)
        
        # ATR for volatility
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        atr = tr.rolling(window=14).mean().iloc[-1]
        
        # Support/Resistance levels (simplified)
        recent_high = high.rolling(window=20).max().iloc[-1]
        recent_low = low.rolling(window=20).min().iloc[-1]
        
        return {
            'ma_20': ma_20,
            'ma_50': ma_50,
            'ma_200': ma_200,
            'rsi': rsi,
            'macd': macd_val,
            'macd_signal': macd_signal,
            'macd_histogram': macd_hist,
            'bb_position': bb_position,
            'atr': atr,
            'recent_high': recent_high,
            'recent_low': recent_low,
            'price': close.iloc[-1]
        }
    
    def _determine_signal_direction(self, indicators: Dict[str, float], 
                                  timeframe: Timeframe) -> Tuple[SignalDirection, float]:
        """Determine signal direction and strength based on indicators."""
        
        price = indicators['price']
        ma_20 = indicators['ma_20']
        ma_50 = indicators['ma_50']
        rsi = indicators['rsi']
        macd = indicators['macd']
        macd_signal = indicators['macd_signal']
        macd_hist = indicators['macd_histogram']
        bb_position = indicators['bb_position']
        
        # Initialize scores
        long_score = 0.0
        short_score = 0.0
        total_score = 0.0
        
        # Moving Average alignment (trend following)
        if price > ma_20 > ma_50:
            long_score += 0.3
            total_score += 0.3
        elif price < ma_20 < ma_50:
            short_score += 0.3
            total_score += 0.3
        
        # RSI (momentum)
        if rsi < 30:  # Oversold
            long_score += 0.2
            total_score += 0.2
        elif rsi > 70:  # Overbought
            short_score += 0.2
            total_score += 0.2
        
        # MACD (momentum)
        if macd > macd_signal and macd_hist > 0:
            long_score += 0.25
            total_score += 0.25
        elif macd < macd_signal and macd_hist < 0:
            short_score += 0.25
            total_score += 0.25
        
        # Bollinger Bands (mean reversion)
        if bb_position < 0.2:  # Near lower band
            long_score += 0.15
            total_score += 0.15
        elif bb_position > 0.8:  # Near upper band
            short_score += 0.15
            total_score += 0.15
        
        # Timeframe weighting (higher timeframes get more weight)
        timeframe_multiplier = {
            Timeframe.M15: 1.0,
            Timeframe.H1: 1.2,
            Timeframe.H4: 1.5,
            Timeframe.D1: 1.8,
            Timeframe.W1: 2.0
        }
        
        multiplier = timeframe_multiplier.get(timeframe, 1.0)
        long_score *= multiplier
        short_score *= multiplier
        total_score *= multiplier
        
        # Determine direction and strength
        if long_score > short_score:
            strength = long_score / total_score if total_score > 0 else 0.5
            return SignalDirection.LONG, min(strength, 1.0)
        elif short_score > long_score:
            strength = short_score / total_score if total_score > 0 else 0.5
            return SignalDirection.SHORT, min(strength, 1.0)
        else:
            return SignalDirection.NEUTRAL, 0.0
    
    def _calculate_sl_tp(self, data: pd.DataFrame, direction: SignalDirection, 
                        entry_price: float) -> Dict[str, float]:
        """Calculate dynamic stop loss and take profit levels."""
        
        # Calculate ATR for volatility-based SL/TP
        high = data['high']
        low = data['low']
        close = data['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        atr = tr.rolling(window=14).mean().iloc[-1]
        
        # Risk-reward ratios based on timeframe
        timeframe_risk_reward = {
            'short_term': 1.5,    # M15, H1
            'medium_term': 2.0,   # H4, D1
            'long_term': 3.0      # W1
        }
        
        # Calculate SL and TP
        if direction == SignalDirection.LONG:
            stop_loss = entry_price - (atr * 1.5)
            take_profit = entry_price + (atr * 1.5 * timeframe_risk_reward['medium_term'])
        else:  # SHORT
            stop_loss = entry_price + (atr * 1.5)
            take_profit = entry_price - (atr * 1.5 * timeframe_risk_reward['medium_term'])
        
        return {
            'stop_loss': stop_loss,
            'take_profit': take_profit
        }
    
    def _consolidate_signals(self, signals: List[Signal], 
                           asset: str) -> MultiTimeframeSignal:
        """Consolidate signals from multiple timeframes."""
        
        # Sort signals by timeframe (higher timeframes get priority)
        timeframe_priority = {
            Timeframe.W1: 5,
            Timeframe.D1: 4,
            Timeframe.H4: 3,
            Timeframe.H1: 2,
            Timeframe.M30: 1.5,
            Timeframe.M15: 1,
            Timeframe.M5: 0.5,
            Timeframe.M1: 0.1
        }
        
        signals.sort(key=lambda x: timeframe_priority.get(x.timeframe, 0), reverse=True)
        
        # Determine primary direction (highest timeframe signal)
        primary_signal = signals[0]
        primary_direction = primary_signal.direction
        
        # Calculate confirmation score
        supporting_signals = []
        conflicting_signals = []
        
        for signal in signals:
            if signal.direction == primary_direction:
                supporting_signals.append(signal)
            else:
                conflicting_signals.append(signal)
        
        # Calculate weighted confirmation score
        total_weight = 0
        supporting_weight = 0
        
        for signal in signals:
            weight = timeframe_priority.get(signal.timeframe, 0.1)
            total_weight += weight
            
            if signal.direction == primary_direction:
                supporting_weight += weight * signal.strength
        
        confirmation_score = supporting_weight / total_weight if total_weight > 0 else 0.0
        
        # Calculate recommended position size based on confirmation
        position_size = self._calculate_position_size(confirmation_score, asset)
        
        # Calculate consolidated SL/TP (weighted average)
        sl_values = [s.stop_loss for s in supporting_signals if s.stop_loss]
        tp_values = [s.take_profit for s in supporting_signals if s.take_profit]
        
        consolidated_sl = np.mean(sl_values) if sl_values else None
        consolidated_tp = np.mean(tp_values) if tp_values else None
        
        return MultiTimeframeSignal(
            timestamp=primary_signal.timestamp,
            primary_direction=primary_direction,
            confirmation_score=confirmation_score,
            primary_signal=primary_signal,
            supporting_signals=supporting_signals,
            conflicting_signals=conflicting_signals,
            recommended_position_size=position_size,
            stop_loss=consolidated_sl,
            take_profit=consolidated_tp
        )
    
    def _calculate_position_size(self, confirmation_score: float, asset: str) -> float:
        """Calculate position size based on confirmation score and asset volatility."""
        
        # Base position size
        base_size = 0.02  # 2% of portfolio
        
        # Confirmation score multiplier
        if confirmation_score >= self.confirmation_thresholds['very_strong']:
            size_multiplier = 2.0
        elif confirmation_score >= self.confirmation_thresholds['strong']:
            size_multiplier = 1.5
        elif confirmation_score >= self.confirmation_thresholds['minimum']:
            size_multiplier = 1.0
        else:
            size_multiplier = 0.1  # Very small position or no trade
        
        # Asset-specific volatility adjustment
        volatility_multipliers = {
            'SOL': 0.8,    # Higher volatility, smaller position
            'ETH': 1.0,    # Standard position
            'BTC': 1.2,    # Lower volatility, larger position
        }
        
        volatility_multiplier = volatility_multipliers.get(asset, 1.0)
        
        position_size = base_size * size_multiplier * volatility_multiplier
        
        # Cap maximum position size
        return min(position_size, 0.1)  # Max 10% of portfolio


class MultiTimeframeStrategy:
    """Main multi-timeframe strategy implementation."""
    
    def __init__(self):
        self.analyzer = MultiTimeframeAnalyzer()
        self.active_positions = {}
        
    def generate_signal(self, market_data: Dict[str, Dict[Timeframe, pd.DataFrame]]) -> Dict[str, MultiTimeframeSignal]:
        """Generate multi-timeframe signals for all assets."""
        
        signals = {}
        
        for asset, data_dict in market_data.items():
            try:
                signal = self.analyzer.analyze_multi_timeframe(data_dict, asset)
                if signal and signal.confirmation_score >= self.analyzer.confirmation_thresholds['minimum']:
                    signals[asset] = signal
                    logger.info(f"Generated signal for {asset}: {signal.primary_direction.value} "
                              f"(confirmation: {signal.confirmation_score:.2f}, "
                              f"position size: {signal.recommended_position_size:.2%})")
            except Exception as e:
                logger.error(f"Error generating signal for {asset}: {e}")
        
        return signals
    
    def should_enter_position(self, signal: MultiTimeframeSignal) -> bool:
        """Determine if we should enter a position based on the signal."""
        
        # Check confirmation threshold
        if signal.confirmation_score < self.analyzer.confirmation_thresholds['minimum']:
            return False
        
        # Check for too many conflicting signals
        max_conflicts = 1  # Allow at most 1 conflicting signal
        if len(signal.conflicting_signals) > max_conflicts:
            return False
        
        # Additional filters could be added here
        # - Market regime filters
        # - Volatility filters
        # - Time-of-day filters
        
        return True
    
    def should_exit_position(self, asset: str, current_price: float, 
                           entry_price: float, direction: SignalDirection) -> bool:
        """Determine if we should exit a position."""
        
        # Check stop loss
        if asset in self.active_positions:
            position = self.active_positions[asset]
            if direction == SignalDirection.LONG:
                if current_price <= position['stop_loss']:
                    return True
            else:  # SHORT
                if current_price >= position['stop_loss']:
                    return True
        
        # Additional exit criteria could be added here
        # - Take profit targets
        # - Trailing stops
        # - Signal reversal
        
        return False
    
    def manage_position(self, asset: str, signal: MultiTimeframeSignal, 
                       current_price: float) -> Dict[str, Any]:
        """Manage an active position based on current signal."""
        
        if asset not in self.active_positions:
            # New position
            if self.should_enter_position(signal):
                position = {
                    'asset': asset,
                    'direction': signal.primary_direction,
                    'entry_price': current_price,
                    'position_size': signal.recommended_position_size,
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit,
                    'timestamp': signal.timestamp
                }
                self.active_positions[asset] = position
                return {'action': 'ENTER', 'position': position}
        
        else:
            # Manage existing position
            position = self.active_positions[asset]
            
            # Check if we should exit due to stop loss
            if self.should_exit_position(asset, current_price, position['entry_price'], position['direction']):
                del self.active_positions[asset]
                return {'action': 'EXIT', 'reason': 'STOP_LOSS'}
            
            # Check for signal reversal
            if signal.primary_direction != position['direction'] and signal.confirmation_score >= 0.8:
                # Exit current position and enter new one
                del self.active_positions[asset]
                if self.should_enter_position(signal):
                    new_position = {
                        'asset': asset,
                        'direction': signal.primary_direction,
                        'entry_price': current_price,
                        'position_size': signal.recommended_position_size,
                        'stop_loss': signal.stop_loss,
                        'take_profit': signal.take_profit,
                        'timestamp': signal.timestamp
                    }
                    self.active_positions[asset] = new_position
                    return {'action': 'REVERSE', 'position': new_position}
        
        return {'action': 'HOLD'}


def main():
    """Demonstrate multi-timeframe strategy functionality."""
    print("Starting Multi-Timeframe Strategy Demonstration...")
    
    # Create sample data for demonstration
    analyzer = MultiTimeframeAnalyzer()
    
    # Generate sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    np.random.seed(42)
    
    # Sample data for different timeframes
    data_m15 = pd.DataFrame({
        'open': np.random.normal(100, 1, 100),
        'high': np.random.normal(101, 1, 100),
        'low': np.random.normal(99, 1, 100),
        'close': np.random.normal(100, 1, 100),
        'volume': np.random.randint(1000, 5000, 100)
    }, index=dates)
    
    data_h1 = pd.DataFrame({
        'open': np.random.normal(100, 2, 50),
        'high': np.random.normal(102, 2, 50),
        'low': np.random.normal(98, 2, 50),
        'close': np.random.normal(100, 2, 50),
        'volume': np.random.randint(2000, 8000, 50)
    }, index=dates[::2])
    
    data_h4 = pd.DataFrame({
        'open': np.random.normal(100, 3, 25),
        'high': np.random.normal(103, 3, 25),
        'low': np.random.normal(97, 3, 25),
        'close': np.random.normal(100, 3, 25),
        'volume': np.random.randint(3000, 10000, 25)
    }, index=dates[::8])
    
    # Test multi-timeframe analysis
    data_dict = {
        Timeframe.M15: data_m15,
        Timeframe.H1: data_h1,
        Timeframe.H4: data_h4
    }
    
    signal = analyzer.analyze_multi_timeframe(data_dict, 'SOL')
    
    if signal:
        print(f"Generated Multi-Timeframe Signal:")
        print(f"  Asset: SOL")
        print(f"  Direction: {signal.primary_direction.value}")
        print(f"  Confirmation Score: {signal.confirmation_score:.2f}")
        print(f"  Position Size: {signal.recommended_position_size:.2%}")
        print(f"  Stop Loss: {signal.stop_loss:.2f}")
        print(f"  Take Profit: {signal.take_profit:.2f}")
        print(f"  Supporting Signals: {len(signal.supporting_signals)}")
        print(f"  Conflicting Signals: {len(signal.conflicting_signals)}")
    else:
        print("No signal generated")
    
    print("Multi-timeframe strategy demonstration completed!")
    
    return signal


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        print(f"Error in multi-timeframe strategy demonstration: {e}")
        import traceback
        traceback.print_exc()