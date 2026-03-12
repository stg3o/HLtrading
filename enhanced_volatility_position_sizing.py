"""
enhanced_volatility_position_sizing.py — Enhanced volatility-based position sizing with dynamic adaptation
Implements advanced volatility regime detection, time-of-day optimization, and execution quality modeling
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime, timedelta
import pytz
from shared.volatility_core import (
    annualized_log_volatility,
    absolute_returns_autocorrelation,
    atr_consistency_confidence,
    multi_timeframe_volatility_trend,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class VolatilityRegime(Enum):
    """Enhanced market volatility regime classifications."""
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    NORMAL = "NORMAL"
    MODERATE_HIGH = "MODERATE_HIGH"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    CHAOTIC = "CHAOTIC"


class TimeOfDayRegime(Enum):
    """Crypto market session classifications."""
    ASIA_SESSION = "ASIA_SESSION"
    EUROPE_SESSION = "EUROPE_SESSION"
    US_SESSION = "US_SESSION"
    WEEKEND_LOW = "WEEKEND_LOW"
    HOLIDAY_LOW = "HOLIDAY_LOW"


class ExecutionQuality(Enum):
    """Execution quality classifications."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    VERY_POOR = "VERY_POOR"


@dataclass
class EnhancedPositionSize:
    """Enhanced position sizing calculation result with execution modeling."""
    asset: str
    direction: str
    position_size: float  # As percentage of portfolio
    dollar_amount: float
    shares_or_contracts: float
    stop_loss_distance: float
    take_profit_distance: float
    risk_amount: float
    risk_percentage: float
    volatility_regime: VolatilityRegime
    time_of_day_regime: TimeOfDayRegime
    execution_quality: ExecutionQuality
    confidence_score: float
    slippage_estimate: float
    liquidity_score: float
    optimal_entry_window: Tuple[str, str]
    position_adjustment_factor: float


@dataclass
class ExecutionModel:
    """Execution quality and slippage modeling."""
    asset: str
    estimated_slippage: float
    liquidity_score: float
    optimal_execution_time: str
    volume_profile: Dict[str, float]
    order_book_depth: Dict[str, float]
    market_impact_estimate: float


class EnhancedVolatilityAnalyzer:
    """Advanced volatility analysis with multi-regime detection and time-based modeling."""
    
    def __init__(self):
        # Enhanced volatility calculation parameters
        self.atr_periods = [7, 14, 21, 50, 100]
        self.garch_window = 50
        self.volatility_lookback = 252  # Annualized volatility
        
        # Enhanced volatility regime thresholds (adaptive based on historical percentiles)
        self.volatility_thresholds = {
            VolatilityRegime.VERY_LOW: 0.2,
            VolatilityRegime.LOW: 0.4,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.MODERATE_HIGH: 1.8,
            VolatilityRegime.HIGH: 3.0,
            VolatilityRegime.EXTREME: 5.0,
            VolatilityRegime.CHAOTIC: 8.0
        }
        
        # Time-of-day volatility patterns (based on crypto market analysis)
        self.time_volatility_multipliers = {
            TimeOfDayRegime.ASIA_SESSION: 0.8,      # 00:00-08:00 UTC
            TimeOfDayRegime.EUROPE_SESSION: 1.0,    # 08:00-16:00 UTC
            TimeOfDayRegime.US_SESSION: 1.2,        # 16:00-00:00 UTC
            TimeOfDayRegime.WEEKEND_LOW: 0.6,       # Saturday-Sunday
            TimeOfDayRegime.HOLIDAY_LOW: 0.4        # Major holidays
        }
        
        # Risk parameters with enhanced volatility scaling
        self.base_risk_per_trade = 0.01  # 1% of portfolio per trade
        self.max_risk_per_trade = 0.05   # 5% maximum risk per trade
        
    def analyze_enhanced_volatility(self, data: pd.DataFrame, 
                                  asset: str = "UNKNOWN") -> Dict[str, Any]:
        """Comprehensive enhanced volatility analysis."""
        
        if len(data) < 100:
            return self._get_default_enhanced_volatility_analysis()
        
        try:
            # Calculate multiple ATR periods
            atr_values = self._calculate_multi_period_atr(data)
            
            # Calculate historical volatility with different methods
            hist_vol = self._calculate_historical_volatility(data)
            garch_vol = self._calculate_garch_volatility(data)
            
            # Calculate volatility clustering and persistence
            vol_clustering = self._analyze_volatility_clustering(data)
            vol_persistence = self._calculate_volatility_persistence(data)
            
            # Determine volatility regime with enhanced classification
            regime = self._determine_enhanced_volatility_regime(atr_values, hist_vol, vol_clustering)
            
            # Analyze volatility trends and momentum
            vol_trend = self._analyze_volatility_trend(atr_values)
            vol_momentum = self._calculate_volatility_momentum(atr_values)
            
            # Calculate time-of-day effects
            time_regime = self._determine_time_of_day_regime()
            time_adjustment = self.time_volatility_multipliers[time_regime]
            
            # Calculate volatility confidence and stability
            vol_confidence = self._calculate_volatility_confidence(atr_values, hist_vol, vol_clustering)
            vol_stability = self._calculate_volatility_stability(atr_values)
            
            return {
                'current_atr': atr_values['atr_14'],
                'atr_7': atr_values['atr_7'],
                'atr_21': atr_values['atr_21'],
                'atr_50': atr_values['atr_50'],
                'atr_100': atr_values['atr_100'],
                'historical_volatility': hist_vol,
                'garch_volatility': garch_vol,
                'volatility_regime': regime,
                'volatility_trend': vol_trend,
                'volatility_momentum': vol_momentum,
                'volatility_clustering': vol_clustering,
                'volatility_persistence': vol_persistence,
                'volatility_confidence': vol_confidence,
                'volatility_stability': vol_stability,
                'time_of_day_regime': time_regime,
                'time_adjustment': time_adjustment,
                'normalized_volatility': self._normalize_enhanced_volatility(atr_values['atr_14'], hist_vol),
                'volatility_skew': self._calculate_volatility_skew(data),
                'volatility_kurtosis': self._calculate_volatility_kurtosis(data)
            }
            
        except Exception as e:
            logger.error(f"Error in enhanced volatility analysis for {asset}: {e}")
            return self._get_default_enhanced_volatility_analysis()
    
    def _calculate_multi_period_atr(self, data: pd.DataFrame) -> Dict[str, float]:
        """Calculate ATR for multiple periods."""
        high = data['high']
        low = data['low']
        close = data['close']
        
        # True Range calculation
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        
        atr_7 = tr.rolling(window=7).mean().iloc[-1]
        atr_14 = tr.rolling(window=14).mean().iloc[-1]
        atr_21 = tr.rolling(window=21).mean().iloc[-1]
        atr_50 = tr.rolling(window=50).mean().iloc[-1]
        atr_100 = tr.rolling(window=100).mean().iloc[-1]
        
        return {
            'atr_7': atr_7,
            'atr_14': atr_14,
            'atr_21': atr_21,
            'atr_50': atr_50,
            'atr_100': atr_100
        }
    
    def _calculate_historical_volatility(self, data: pd.DataFrame) -> float:
        """Calculate historical volatility using log returns with multiple timeframes."""
        close = data['close']
        vol_20 = annualized_log_volatility(close, lookback=20)
        vol_60 = annualized_log_volatility(close, lookback=60)
        vol_120 = annualized_log_volatility(close, lookback=120)
        
        # Weighted average of different timeframes
        weighted_vol = (vol_20 * 0.5 + vol_60 * 0.3 + vol_120 * 0.2)
        return weighted_vol
    
    def _calculate_garch_volatility(self, data: pd.DataFrame) -> float:
        """Calculate GARCH(1,1) volatility estimate."""
        try:
            close = data['close']
            returns = np.log(close / close.shift(1)).dropna()
            
            # Simple GARCH(1,1) approximation
            omega = 0.000002
            alpha = 0.1
            beta = 0.85
            
            # Initialize variance
            variance = returns.var()
            
            # GARCH recursion
            for r in returns.tail(50):
                variance = omega + alpha * (r ** 2) + beta * variance
            
            return np.sqrt(variance) * np.sqrt(252)
        except:
            return 0.2  # Default volatility
    
    def _analyze_volatility_clustering(self, data: pd.DataFrame) -> float:
        """Analyze volatility clustering using absolute returns correlation."""
        return absolute_returns_autocorrelation(data['close'], min_points=20)
    
    def _calculate_volatility_persistence(self, data: pd.DataFrame) -> float:
        """Calculate volatility persistence using ATR momentum."""
        atr_values = self._calculate_multi_period_atr(data)
        atr_series = pd.Series(list(atr_values.values()))
        
        # Calculate ATR momentum (trend persistence)
        atr_momentum = atr_series.pct_change().tail(5).mean()
        return atr_momentum
    
    def _determine_enhanced_volatility_regime(self, atr_values: Dict[str, float], 
                                            hist_vol: float, clustering: float) -> VolatilityRegime:
        """Determine enhanced volatility regime with multiple factors."""
        
        # Calculate composite volatility score
        avg_atr = np.mean(list(atr_values.values()))
        volatility_score = avg_atr * (1 + clustering)  # Adjust for clustering
        
        # Enhanced regime classification
        if volatility_score < 0.3:
            return VolatilityRegime.VERY_LOW
        elif volatility_score < 0.6:
            return VolatilityRegime.LOW
        elif volatility_score < 1.2:
            return VolatilityRegime.NORMAL
        elif volatility_score < 2.5:
            return VolatilityRegime.MODERATE_HIGH
        elif volatility_score < 4.0:
            return VolatilityRegime.HIGH
        elif volatility_score < 6.0:
            return VolatilityRegime.EXTREME
        else:
            return VolatilityRegime.CHAOTIC
    
    def _analyze_volatility_trend(self, atr_values: Dict[str, float]) -> str:
        """Analyze volatility trend direction with multiple timeframes."""
        return multi_timeframe_volatility_trend(
            atr_values['atr_14'],
            atr_values['atr_21'],
            atr_values['atr_50'],
        )
    
    def _calculate_volatility_momentum(self, atr_values: Dict[str, float]) -> float:
        """Calculate volatility momentum indicator."""
        atr_series = pd.Series(list(atr_values.values()))
        momentum = atr_series.pct_change().mean()
        return momentum
    
    def _determine_time_of_day_regime(self) -> TimeOfDayRegime:
        """Determine current time-of-day market regime."""
        utc_now = datetime.now(pytz.UTC)
        hour = utc_now.hour
        day_of_week = utc_now.weekday()  # 0=Monday, 6=Sunday
        
        # Weekend detection
        if day_of_week >= 5:  # Saturday or Sunday
            return TimeOfDayRegime.WEEKEND_LOW
        
        # Holiday detection (simplified - major US holidays)
        date_str = utc_now.strftime('%m-%d')
        holidays = ['01-01', '07-04', '12-25']  # New Year's, Independence Day, Christmas
        if date_str in holidays:
            return TimeOfDayRegime.HOLIDAY_LOW
        
        # Session classification
        if 0 <= hour < 8:
            return TimeOfDayRegime.ASIA_SESSION
        elif 8 <= hour < 16:
            return TimeOfDayRegime.EUROPE_SESSION
        else:
            return TimeOfDayRegime.US_SESSION
    
    def _calculate_volatility_confidence(self, atr_values: Dict[str, float], 
                                       hist_vol: float, clustering: float) -> float:
        """Calculate confidence in volatility measurement."""
        consistency = atr_consistency_confidence(atr_values, zero_mean_default=0.3)
        
        # Adjust for clustering (too much clustering reduces confidence)
        clustering_adjustment = 1.0 - abs(clustering - 0.2)  # Optimal clustering around 0.2
        clustering_adjustment = max(0.1, min(1.0, clustering_adjustment))
        
        confidence = (consistency * 0.6) + (clustering_adjustment * 0.4)
        return max(0.1, min(1.0, confidence))
    
    def _calculate_volatility_stability(self, atr_values: Dict[str, float]) -> float:
        """Calculate volatility stability indicator."""
        atr_series = pd.Series(list(atr_values.values()))
        stability = 1.0 / (1.0 + atr_series.std() / atr_series.mean())
        return max(0.0, min(1.0, stability))
    
    def _normalize_enhanced_volatility(self, current_atr: float, hist_vol: float) -> float:
        """Normalize enhanced volatility to a 0-1 scale."""
        # Enhanced normalization considering multiple factors
        normalized = min(current_atr / 10.0, 1.0)  # Cap at 10.0 ATR
        return max(normalized, 0.0)
    
    def _calculate_volatility_skew(self, data: pd.DataFrame) -> float:
        """Calculate volatility skew (asymmetry in returns distribution)."""
        close = data['close']
        returns = np.log(close / close.shift(1)).dropna()
        return returns.skew()
    
    def _calculate_volatility_kurtosis(self, data: pd.DataFrame) -> float:
        """Calculate volatility kurtosis (fat tails indicator)."""
        close = data['close']
        returns = np.log(close / close.shift(1)).dropna()
        return returns.kurtosis()
    
    def _get_default_enhanced_volatility_analysis(self) -> Dict[str, Any]:
        """Return default enhanced volatility analysis for insufficient data."""
        return {
            'current_atr': 1.0,
            'atr_7': 1.0,
            'atr_21': 1.0,
            'atr_50': 1.0,
            'atr_100': 1.0,
            'historical_volatility': 0.2,
            'garch_volatility': 0.2,
            'volatility_regime': VolatilityRegime.NORMAL,
            'volatility_trend': 'stable',
            'volatility_momentum': 0.0,
            'volatility_clustering': 0.0,
            'volatility_persistence': 0.0,
            'volatility_confidence': 0.5,
            'volatility_stability': 0.5,
            'time_of_day_regime': TimeOfDayRegime.NORMAL,
            'time_adjustment': 1.0,
            'normalized_volatility': 0.5,
            'volatility_skew': 0.0,
            'volatility_kurtosis': 3.0
        }


class EnhancedPositionSizer:
    """Enhanced position sizing with dynamic adaptation and execution modeling."""
    
    def __init__(self):
        self.volatility_analyzer = EnhancedVolatilityAnalyzer()
        
        # Enhanced risk management parameters with volatility scaling
        self.risk_parameters = {
            'conservative': {
                'base_risk': 0.005,    # 0.5% per trade
                'max_position': 0.03,  # 3% max position
                'atr_multiplier_sl': 2.5,
                'atr_multiplier_tp': 4.0,
                'volatility_adjustment': {
                    VolatilityRegime.VERY_LOW: 2.0,
                    VolatilityRegime.LOW: 1.5,
                    VolatilityRegime.NORMAL: 1.0,
                    VolatilityRegime.MODERATE_HIGH: 0.7,
                    VolatilityRegime.HIGH: 0.4,
                    VolatilityRegime.EXTREME: 0.2,
                    VolatilityRegime.CHAOTIC: 0.1
                }
            },
            'moderate': {
                'base_risk': 0.01,     # 1% per trade
                'max_position': 0.08,  # 8% max position
                'atr_multiplier_sl': 2.0,
                'atr_multiplier_tp': 3.5,
                'volatility_adjustment': {
                    VolatilityRegime.VERY_LOW: 1.8,
                    VolatilityRegime.LOW: 1.3,
                    VolatilityRegime.NORMAL: 1.0,
                    VolatilityRegime.MODERATE_HIGH: 0.8,
                    VolatilityRegime.HIGH: 0.5,
                    VolatilityRegime.EXTREME: 0.3,
                    VolatilityRegime.CHAOTIC: 0.15
                }
            },
            'aggressive': {
                'base_risk': 0.02,     # 2% per trade
                'max_position': 0.15,  # 15% max position
                'atr_multiplier_sl': 1.5,
                'atr_multiplier_tp': 3.0,
                'volatility_adjustment': {
                    VolatilityRegime.VERY_LOW: 1.5,
                    VolatilityRegime.LOW: 1.2,
                    VolatilityRegime.NORMAL: 1.0,
                    VolatilityRegime.MODERATE_HIGH: 0.9,
                    VolatilityRegime.HIGH: 0.6,
                    VolatilityRegime.EXTREME: 0.4,
                    VolatilityRegime.CHAOTIC: 0.2
                }
            }
        }
        
        # Time-of-day position sizing adjustments
        self.time_adjustments = {
            TimeOfDayRegime.ASIA_SESSION: 0.9,      # Slightly reduced
            TimeOfDayRegime.EUROPE_SESSION: 1.0,    # Standard
            TimeOfDayRegime.US_SESSION: 1.1,        # Slightly increased
            TimeOfDayRegime.WEEKEND_LOW: 0.6,       # Reduced
            TimeOfDayRegime.HOLIDAY_LOW: 0.4        # Significantly reduced
        }
        
        # Execution quality adjustments
        self.execution_adjustments = {
            ExecutionQuality.EXCELLENT: 1.0,
            ExecutionQuality.GOOD: 0.95,
            ExecutionQuality.FAIR: 0.85,
            ExecutionQuality.POOR: 0.7,
            ExecutionQuality.VERY_POOR: 0.5
        }
    
    def calculate_enhanced_position_size(self, 
                                       data: pd.DataFrame,
                                       entry_price: float,
                                       direction: str,
                                       portfolio_value: float,
                                       risk_level: str = 'moderate',
                                       confidence_score: float = 0.5,
                                       asset: str = "UNKNOWN") -> EnhancedPositionSize:
        """Calculate enhanced position size with dynamic adaptation."""
        
        # Analyze current enhanced volatility
        vol_analysis = self.volatility_analyzer.analyze_enhanced_volatility(data, asset)
        
        # Get risk parameters for the selected risk level
        risk_params = self.risk_parameters[risk_level]
        
        # Calculate base risk amount
        base_risk_amount = portfolio_value * risk_params['base_risk']
        
        # Apply volatility regime adjustment
        vol_regime = vol_analysis['volatility_regime']
        vol_adjustment = risk_params['volatility_adjustment'][vol_regime]
        adjusted_risk_amount = base_risk_amount * vol_adjustment
        
        # Apply time-of-day adjustment
        time_regime = vol_analysis['time_of_day_regime']
        time_adjustment = self.time_adjustments[time_regime]
        adjusted_risk_amount *= time_adjustment
        
        # Apply execution quality adjustment
        execution_quality = self._assess_execution_quality(vol_analysis)
        exec_adjustment = self.execution_adjustments[execution_quality]
        adjusted_risk_amount *= exec_adjustment
        
        # Apply confidence adjustment
        confidence_adjustment = 0.5 + (confidence_score * 0.5)  # 0.5 to 1.0
        final_risk_amount = adjusted_risk_amount * confidence_adjustment
        
        # Calculate stop loss distance using ATR with enhanced multi-period analysis
        atr_14 = vol_analysis['current_atr']
        atr_21 = vol_analysis['atr_21']
        atr_50 = vol_analysis['atr_50']
        
        # Weighted ATR for more stable SL calculation
        weighted_atr = (atr_14 * 0.5 + atr_21 * 0.3 + atr_50 * 0.2)
        sl_distance = weighted_atr * risk_params['atr_multiplier_sl']
        
        # Calculate position size in shares/contracts
        if direction.upper() == 'LONG':
            stop_loss_price = entry_price - sl_distance
        else:  # SHORT
            stop_loss_price = entry_price + sl_distance
        
        risk_per_unit = abs(entry_price - stop_loss_price)
        
        if risk_per_unit <= 0:
            # Fallback to minimum risk per unit
            risk_per_unit = entry_price * 0.01  # 1% minimum
        
        units = final_risk_amount / risk_per_unit
        
        # Calculate position value
        position_value = units * entry_price
        
        # Calculate position size as percentage of portfolio
        position_size_pct = position_value / portfolio_value
        
        # Apply maximum position size constraint
        max_position_pct = risk_params['max_position']
        if position_size_pct > max_position_pct:
            position_size_pct = max_position_pct
            position_value = portfolio_value * position_size_pct
            units = position_value / entry_price
        
        # Calculate take profit distance with volatility scaling
        tp_distance = weighted_atr * risk_params['atr_multiplier_tp']
        
        # Adjust TP based on volatility regime and trend
        vol_trend = vol_analysis['volatility_trend']
        if vol_trend == 'increasing':
            tp_distance *= 1.1  # Wider targets in increasing volatility
        elif vol_trend == 'decreasing':
            tp_distance *= 0.9  # Tighter targets in decreasing volatility
        
        if direction.upper() == 'LONG':
            take_profit_price = entry_price + tp_distance
        else:  # SHORT
            take_profit_price = entry_price - tp_distance
        
        # Calculate slippage estimate
        slippage_estimate = self._estimate_slippage(vol_analysis, direction)
        
        # Calculate liquidity score
        liquidity_score = self._calculate_liquidity_score(vol_analysis)
        
        # Determine optimal entry window
        optimal_window = self._determine_optimal_entry_window(vol_analysis)
        
        # Calculate position adjustment factor
        adjustment_factor = self._calculate_position_adjustment_factor(vol_analysis, confidence_score)
        
        return EnhancedPositionSize(
            asset=asset,
            direction=direction,
            position_size=position_size_pct,
            dollar_amount=position_value,
            shares_or_contracts=units,
            stop_loss_distance=sl_distance,
            take_profit_distance=tp_distance,
            risk_amount=final_risk_amount,
            risk_percentage=position_size_pct,
            volatility_regime=vol_regime,
            time_of_day_regime=time_regime,
            execution_quality=execution_quality,
            confidence_score=confidence_score,
            slippage_estimate=slippage_estimate,
            liquidity_score=liquidity_score,
            optimal_entry_window=optimal_window,
            position_adjustment_factor=adjustment_factor
        )
    
    def _assess_execution_quality(self, vol_analysis: Dict[str, Any]) -> ExecutionQuality:
        """Assess execution quality based on volatility and market conditions."""
        
        vol_regime = vol_analysis['volatility_regime']
        vol_confidence = vol_analysis['volatility_confidence']
        vol_stability = vol_analysis['volatility_stability']
        
        # Base quality from volatility regime
        quality_scores = {
            VolatilityRegime.VERY_LOW: 0.9,
            VolatilityRegime.LOW: 0.8,
            VolatilityRegime.NORMAL: 0.7,
            VolatilityRegime.MODERATE_HIGH: 0.6,
            VolatilityRegime.HIGH: 0.4,
            VolatilityRegime.EXTREME: 0.2,
            VolatilityRegime.CHAOTIC: 0.1
        }
        
        base_score = quality_scores.get(vol_regime, 0.5)
        
        # Adjust for confidence and stability
        adjusted_score = base_score * vol_confidence * vol_stability
        
        # Map to execution quality enum
        if adjusted_score >= 0.8:
            return ExecutionQuality.EXCELLENT
        elif adjusted_score >= 0.6:
            return ExecutionQuality.GOOD
        elif adjusted_score >= 0.4:
            return ExecutionQuality.FAIR
        elif adjusted_score >= 0.2:
            return ExecutionQuality.POOR
        else:
            return ExecutionQuality.VERY_POOR
    
    def _estimate_slippage(self, vol_analysis: Dict[str, Any], direction: str) -> float:
        """Estimate slippage based on volatility and market conditions."""
        
        vol_regime = vol_analysis['volatility_regime']
        vol_trend = vol_analysis['volatility_trend']
        time_regime = vol_analysis['time_of_day_regime']
        
        # Base slippage estimates
        base_slippage = {
            VolatilityRegime.VERY_LOW: 0.0005,    # 0.05%
            VolatilityRegime.LOW: 0.001,          # 0.1%
            VolatilityRegime.NORMAL: 0.002,       # 0.2%
            VolatilityRegime.MODERATE_HIGH: 0.005, # 0.5%
            VolatilityRegime.HIGH: 0.01,          # 1.0%
            VolatilityRegime.EXTREME: 0.02,       # 2.0%
            VolatilityRegime.CHAOTIC: 0.05        # 5.0%
        }
        
        slippage = base_slippage.get(vol_regime, 0.002)
        
        # Adjust for volatility trend
        if vol_trend == 'increasing':
            slippage *= 1.5
        elif vol_trend == 'decreasing':
            slippage *= 0.8
        
        # Adjust for time of day
        if time_regime in [TimeOfDayRegime.WEEKEND_LOW, TimeOfDayRegime.HOLIDAY_LOW]:
            slippage *= 1.2
        
        # Adjust for direction (short positions often have higher slippage)
        if direction.upper() == 'SHORT':
            slippage *= 1.2
        
        return slippage
    
    def _calculate_liquidity_score(self, vol_analysis: Dict[str, Any]) -> float:
        """Calculate liquidity score based on volatility characteristics."""
        
        vol_regime = vol_analysis['volatility_regime']
        vol_confidence = vol_analysis['volatility_confidence']
        vol_stability = vol_analysis['volatility_stability']
        
        # Liquidity scores based on volatility regime
        liquidity_scores = {
            VolatilityRegime.VERY_LOW: 0.9,
            VolatilityRegime.LOW: 0.8,
            VolatilityRegime.NORMAL: 0.7,
            VolatilityRegime.MODERATE_HIGH: 0.5,
            VolatilityRegime.HIGH: 0.3,
            VolatilityRegime.EXTREME: 0.15,
            VolatilityRegime.CHAOTIC: 0.05
        }
        
        base_score = liquidity_scores.get(vol_regime, 0.5)
        
        # Adjust for confidence and stability
        final_score = base_score * vol_confidence * vol_stability
        
        return max(0.0, min(1.0, final_score))
    
    def _determine_optimal_entry_window(self, vol_analysis: Dict[str, Any]) -> Tuple[str, str]:
        """Determine optimal entry time window based on volatility patterns."""
        
        time_regime = vol_analysis['time_of_day_regime']
        vol_trend = vol_analysis['volatility_trend']
        
        # Base time windows for each regime
        base_windows = {
            TimeOfDayRegime.ASIA_SESSION: ("00:00", "08:00"),
            TimeOfDayRegime.EUROPE_SESSION: ("08:00", "16:00"),
            TimeOfDayRegime.US_SESSION: ("16:00", "00:00"),
            TimeOfDayRegime.WEEKEND_LOW: ("00:00", "23:59"),
            TimeOfDayRegime.HOLIDAY_LOW: ("00:00", "23:59")
        }
        
        base_start, base_end = base_windows.get(time_regime, ("00:00", "23:59"))
        
        # Adjust window based on volatility trend
        if vol_trend == 'increasing':
            # Move to earlier part of window when volatility is rising
            return (base_start, base_start[:-2] + "12")  # First half
        elif vol_trend == 'decreasing':
            # Move to later part of window when volatility is falling
            return (base_start[:-2] + "12", base_end)  # Second half
        else:
            return (base_start, base_end)
    
    def _calculate_position_adjustment_factor(self, vol_analysis: Dict[str, Any], 
                                            confidence_score: float) -> float:
        """Calculate dynamic position adjustment factor."""
        
        vol_regime = vol_analysis['volatility_regime']
        vol_confidence = vol_analysis['volatility_confidence']
        vol_stability = vol_analysis['volatility_stability']
        
        # Base adjustment factors
        base_factors = {
            VolatilityRegime.VERY_LOW: 1.2,
            VolatilityRegime.LOW: 1.1,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.MODERATE_HIGH: 0.8,
            VolatilityRegime.HIGH: 0.6,
            VolatilityRegime.EXTREME: 0.4,
            VolatilityRegime.CHAOTIC: 0.2
        }
        
        base_factor = base_factors.get(vol_regime, 1.0)
        
        # Adjust for confidence and stability
        adjustment = base_factor * vol_confidence * vol_stability * confidence_score
        
        return max(0.1, min(2.0, adjustment))


class ExecutionQualityModel:
    """Advanced execution quality and slippage modeling."""
    
    def __init__(self):
        self.order_book_data = {}
        self.volume_profile_data = {}
        
    def model_execution_quality(self, asset: str, order_size: float, 
                               current_price: float, direction: str) -> ExecutionModel:
        """Model execution quality for a given order."""
        
        # Simulate order book depth (in practice, this would come from real order book data)
        order_book_depth = self._simulate_order_book(asset, current_price, direction)
        
        # Simulate volume profile
        volume_profile = self._simulate_volume_profile(asset)
        
        # Calculate market impact
        market_impact = self._calculate_market_impact(order_size, order_book_depth, direction)
        
        # Estimate slippage
        estimated_slippage = self._estimate_execution_slippage(
            order_size, order_book_depth, market_impact, direction
        )
        
        # Calculate liquidity score
        liquidity_score = self._calculate_execution_liquidity_score(order_book_depth, volume_profile)
        
        # Determine optimal execution time
        optimal_time = self._determine_optimal_execution_time(asset)
        
        return ExecutionModel(
            asset=asset,
            estimated_slippage=estimated_slippage,
            liquidity_score=liquidity_score,
            optimal_execution_time=optimal_time,
            volume_profile=volume_profile,
            order_book_depth=order_book_depth,
            market_impact_estimate=market_impact
        )
    
    def _simulate_order_book(self, asset: str, price: float, direction: str) -> Dict[str, float]:
        """Simulate order book depth for demonstration."""
        # In practice, this would use real order book data from the exchange
        if direction.upper() == 'LONG':
            # Simulate bid side
            return {
                'best_bid': price * 0.9995,
                'bid_depth_1': price * 0.999,
                'bid_depth_2': price * 0.998,
                'bid_depth_3': price * 0.997,
                'bid_liquidity': 1000000  # USD equivalent
            }
        else:
            # Simulate ask side
            return {
                'best_ask': price * 1.0005,
                'ask_depth_1': price * 1.001,
                'ask_depth_2': price * 1.002,
                'ask_depth_3': price * 1.003,
                'ask_liquidity': 1000000  # USD equivalent
            }
    
    def _simulate_volume_profile(self, asset: str) -> Dict[str, float]:
        """Simulate volume profile across different price levels."""
        # In practice, this would use real volume data
        return {
            'support_1': 0.8,
            'support_2': 0.6,
            'resistance_1': 0.7,
            'resistance_2': 0.5,
            'pivot': 1.0
        }
    
    def _calculate_market_impact(self, order_size: float, order_book_depth: Dict[str, float], 
                               direction: str) -> float:
        """Calculate estimated market impact of the order."""
        liquidity = order_book_depth.get('bid_liquidity' if direction.upper() == 'LONG' else 'ask_liquidity', 1000000)
        
        # Simple market impact model
        impact = (order_size / liquidity) * 0.01  # 1% base impact per 100% of liquidity
        
        return impact
    
    def _estimate_execution_slippage(self, order_size: float, order_book_depth: Dict[str, float], 
                                   market_impact: float, direction: str) -> float:
        """Estimate execution slippage."""
        base_slippage = 0.001  # 0.1% base slippage
        
        # Add market impact
        total_slippage = base_slippage + market_impact
        
        # Adjust for order size
        if order_size > 100000:  # Large orders
            total_slippage *= 1.5
        elif order_size < 10000:  # Small orders
            total_slippage *= 0.8
        
        return total_slippage
    
    def _calculate_execution_liquidity_score(self, order_book_depth: Dict[str, float], 
                                           volume_profile: Dict[str, float]) -> float:
        """Calculate liquidity score for execution."""
        bid_liquidity = order_book_depth.get('bid_liquidity', 0)
        ask_liquidity = order_book_depth.get('ask_liquidity', 0)
        
        avg_liquidity = (bid_liquidity + ask_liquidity) / 2
        
        # Normalize liquidity score (0 to 1)
        liquidity_score = min(avg_liquidity / 10000000, 1.0)
        
        # Adjust for volume profile
        pivot_volume = volume_profile.get('pivot', 0.5)
        liquidity_score *= (0.5 + pivot_volume)
        
        return max(0.0, min(1.0, liquidity_score))
    
    def _determine_optimal_execution_time(self, asset: str) -> str:
        """Determine optimal execution time based on historical patterns."""
        # In practice, this would analyze historical execution data
        current_hour = datetime.now().hour
        
        # Simple heuristic: avoid market open/close times for better liquidity
        if 9 <= current_hour <= 15:  # US market hours
            return "optimal"
        elif current_hour in [8, 16]:  # Near market open/close
            return "caution"
        else:
            return "suboptimal"


def main():
    """Demonstrate enhanced volatility-based position sizing functionality."""
    print("Starting Enhanced Volatility-Based Position Sizing Demonstration...")
    
    # Create sample market data with different volatility regimes
    dates = pd.date_range('2024-01-01', periods=300, freq='1H')
    np.random.seed(42)
    
    # Generate sample price data with different volatility regimes
    base_price = 100
    prices = [base_price]
    
    for i in range(1, 300):
        # Simulate different volatility regimes
        if i < 50:
            volatility = 0.3  # Very low volatility
        elif i < 100:
            volatility = 0.6  # Low volatility
        elif i < 150:
            volatility = 1.2  # Normal volatility
        elif i < 200:
            volatility = 2.0  # Moderate high volatility
        elif i < 250:
            volatility = 3.5  # High volatility
        else:
            volatility = 6.0  # Extreme volatility
            
        noise = np.random.normal(0, volatility)
        new_price = prices[-1] * (1 + noise / 100)
        prices.append(new_price)
    
    # Create DataFrame
    data = pd.DataFrame({
        'open': prices[:-1],
        'high': [p * (1 + abs(np.random.normal(0, 0.2))/100) for p in prices[:-1]],
        'low': [p * (1 - abs(np.random.normal(0, 0.2))/100) for p in prices[:-1]],
        'close': prices[1:],
        'volume': np.random.randint(1000, 10000, 299)
    }, index=dates[:-1])
    
    # Test enhanced volatility analysis
    analyzer = EnhancedVolatilityAnalyzer()
    vol_analysis = analyzer.analyze_enhanced_volatility(data, "SOL")
    
    print(f"Enhanced Volatility Analysis Results:")
    print(f"  Current ATR: {vol_analysis['current_atr']:.2f}")
    print(f"  Volatility Regime: {vol_analysis['volatility_regime'].value}")
    print(f"  Time of Day Regime: {vol_analysis['time_of_day_regime'].value}")
    print(f"  Volatility Trend: {vol_analysis['volatility_trend']}")
    print(f"  Volatility Confidence: {vol_analysis['volatility_confidence']:.2f}")
    print(f"  Volatility Stability: {vol_analysis['volatility_stability']:.2f}")
    print(f"  Time Adjustment: {vol_analysis['time_adjustment']:.2f}")
    
    # Test enhanced position sizing
    sizer = EnhancedPositionSizer()
    portfolio_value = 100000  # $100k portfolio
    
    enhanced_position = sizer.calculate_enhanced_position_size(
        data=data,
        entry_price=100.0,
        direction='LONG',
        portfolio_value=portfolio_value,
        risk_level='moderate',
        confidence_score=0.8,
        asset="SOL"
    )
    
    print(f"\nEnhanced Position Sizing Results:")
    print(f"  Position Size: {enhanced_position.position_size:.2%}")
    print(f"  Dollar Amount: ${enhanced_position.dollar_amount:,.2f}")
    print(f"  Shares: {enhanced_position.shares_or_contracts:.2f}")
    print(f"  Risk Amount: ${enhanced_position.risk_amount:,.2f}")
    print(f"  Volatility Regime: {enhanced_position.volatility_regime.value}")
    print(f"  Time of Day Regime: {enhanced_position.time_of_day_regime.value}")
    print(f"  Execution Quality: {enhanced_position.execution_quality.value}")
    print(f"  Slippage Estimate: {enhanced_position.slippage_estimate:.4f}")
    print(f"  Liquidity Score: {enhanced_position.liquidity_score:.2f}")
    print(f"  Optimal Entry Window: {enhanced_position.optimal_entry_window}")
    print(f"  Position Adjustment Factor: {enhanced_position.position_adjustment_factor:.2f}")
    
    # Test execution quality modeling
    execution_model = ExecutionQualityModel()
    execution = execution_model.model_execution_quality(
        asset="SOL",
        order_size=50000,
        current_price=100.0,
        direction='LONG'
    )
    
    print(f"\nExecution Quality Modeling Results:")
    print(f"  Estimated Slippage: {execution.estimated_slippage:.4f}")
    print(f"  Liquidity Score: {execution.liquidity_score:.2f}")
    print(f"  Optimal Execution Time: {execution.optimal_execution_time}")
    print(f"  Market Impact: {execution.market_impact_estimate:.4f}")
    
    print("\nEnhanced volatility-based position sizing demonstration completed!")
    
    return {
        'enhanced_volatility_analysis': vol_analysis,
        'enhanced_position_size': enhanced_position,
        'execution_model': execution
    }


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        print(f"Error in enhanced volatility-based position sizing demonstration: {e}")
        import traceback
        traceback.print_exc()
