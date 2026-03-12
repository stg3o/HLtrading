"""
volatility_position_sizing.py — Volatility-based position sizing and SL/TP adjustment
Implements ATR-based position sizing and dynamic risk management
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging
from shared.volatility_core import (
    annualized_log_volatility,
    absolute_returns_autocorrelation,
    atr_consistency_confidence,
    simple_volatility_trend,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level classifications."""
    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


class VolatilityRegime(Enum):
    """Market volatility regime classifications."""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass
class PositionSize:
    """Position sizing calculation result."""
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
    confidence_score: float


@dataclass
class DynamicSLTP:
    """Dynamic stop loss and take profit levels."""
    asset: str
    entry_price: float
    stop_loss: float
    take_profit: float
    trailing_stop: Optional[float]
    risk_reward_ratio: float
    volatility_adjusted: bool
    time_adjusted: bool


class VolatilityAnalyzer:
    """Advanced volatility analysis and regime detection."""
    
    def __init__(self):
        # Volatility calculation parameters
        self.atr_periods = [14, 21, 50]
        self.std_periods = [20, 50, 200]
        self.vix_lookback = 30
        
        # Volatility regime thresholds (multipliers of normal volatility)
        self.volatility_thresholds = {
            VolatilityRegime.LOW: 0.5,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.HIGH: 2.0,
            VolatilityRegime.EXTREME: 4.0
        }
        
        # Risk parameters
        self.base_risk_per_trade = 0.01  # 1% of portfolio per trade
        self.max_risk_per_trade = 0.05   # 5% maximum risk per trade
        
    def analyze_volatility(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Comprehensive volatility analysis."""
        
        if len(data) < 50:
            return self._get_default_volatility_analysis()
        
        try:
            # Calculate ATR (Average True Range)
            atr_values = self._calculate_atr(data)
            
            # Calculate historical volatility
            hist_vol = self._calculate_historical_volatility(data)
            
            # Calculate volatility regime
            regime = self._determine_volatility_regime(atr_values, hist_vol)
            
            # Calculate volatility trends
            vol_trend = self._analyze_volatility_trend(atr_values)
            
            # Calculate volatility clustering
            vol_clustering = self._analyze_volatility_clustering(data)
            
            return {
                'current_atr': atr_values['atr_14'],
                'atr_21': atr_values['atr_21'],
                'atr_50': atr_values['atr_50'],
                'historical_volatility': hist_vol,
                'volatility_regime': regime,
                'volatility_trend': vol_trend,
                'volatility_clustering': vol_clustering,
                'normalized_volatility': self._normalize_volatility(atr_values['atr_14'], hist_vol),
                'volatility_confidence': self._calculate_volatility_confidence(atr_values, hist_vol)
            }
            
        except Exception as e:
            logger.error(f"Error in volatility analysis: {e}")
            return self._get_default_volatility_analysis()
    
    def _calculate_atr(self, data: pd.DataFrame) -> Dict[str, float]:
        """Calculate Average True Range for multiple periods."""
        high = data['high']
        low = data['low']
        close = data['close']
        
        # True Range calculation
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        
        atr_14 = tr.rolling(window=14).mean().iloc[-1]
        atr_21 = tr.rolling(window=21).mean().iloc[-1]
        atr_50 = tr.rolling(window=50).mean().iloc[-1]
        
        return {
            'atr_14': atr_14,
            'atr_21': atr_21,
            'atr_50': atr_50
        }
    
    def _calculate_historical_volatility(self, data: pd.DataFrame) -> float:
        """Calculate historical volatility using log returns."""
        return annualized_log_volatility(data['close'])
    
    def _determine_volatility_regime(self, atr_values: Dict[str, float], 
                                   hist_vol: float) -> VolatilityRegime:
        """Determine current volatility regime."""
        
        # Calculate average ATR as reference
        avg_atr = np.mean(list(atr_values.values()))
        
        # Compare with historical average (simplified)
        # In practice, this would compare with long-term averages
        if avg_atr < 0.5:
            return VolatilityRegime.LOW
        elif avg_atr < 1.5:
            return VolatilityRegime.NORMAL
        elif avg_atr < 3.0:
            return VolatilityRegime.HIGH
        else:
            return VolatilityRegime.EXTREME
    
    def _analyze_volatility_trend(self, atr_values: Dict[str, float]) -> str:
        """Analyze volatility trend direction."""
        return simple_volatility_trend(atr_values['atr_14'], atr_values['atr_21'])
    
    def _analyze_volatility_clustering(self, data: pd.DataFrame) -> float:
        """Analyze volatility clustering (GARCH-like behavior)."""
        return absolute_returns_autocorrelation(data['close'], min_points=10)
    
    def _normalize_volatility(self, current_atr: float, hist_vol: float) -> float:
        """Normalize volatility to a 0-1 scale."""
        # Normalize based on historical range (simplified)
        # In practice, this would use long-term volatility percentiles
        normalized = min(current_atr / 5.0, 1.0)  # Cap at 5.0 ATR
        return max(normalized, 0.0)
    
    def _calculate_volatility_confidence(self, atr_values: Dict[str, float], 
                                       hist_vol: float) -> float:
        """Calculate confidence in volatility measurement."""
        return atr_consistency_confidence(atr_values, zero_mean_default=0.5)
    
    def _get_default_volatility_analysis(self) -> Dict[str, Any]:
        """Return default volatility analysis for insufficient data."""
        return {
            'current_atr': 1.0,
            'atr_21': 1.0,
            'atr_50': 1.0,
            'historical_volatility': 0.2,
            'volatility_regime': VolatilityRegime.NORMAL,
            'volatility_trend': 'stable',
            'volatility_clustering': 0.0,
            'normalized_volatility': 0.5,
            'volatility_confidence': 0.5
        }


class PositionSizer:
    """Advanced position sizing based on volatility and risk management."""
    
    def __init__(self):
        self.volatility_analyzer = VolatilityAnalyzer()
        
        # Risk management parameters
        self.risk_parameters = {
            RiskLevel.CONSERVATIVE: {
                'base_risk': 0.005,    # 0.5% per trade
                'max_position': 0.05,  # 5% max position
                'atr_multiplier_sl': 2.0,
                'atr_multiplier_tp': 3.0
            },
            RiskLevel.MODERATE: {
                'base_risk': 0.01,     # 1% per trade
                'max_position': 0.10,  # 10% max position
                'atr_multiplier_sl': 1.5,
                'atr_multiplier_tp': 2.5
            },
            RiskLevel.AGGRESSIVE: {
                'base_risk': 0.02,     # 2% per trade
                'max_position': 0.20,  # 20% max position
                'atr_multiplier_sl': 1.0,
                'atr_multiplier_tp': 2.0
            }
        }
        
        # Volatility adjustment factors
        self.volatility_adjustments = {
            VolatilityRegime.LOW: 1.5,      # Increase position in low vol
            VolatilityRegime.NORMAL: 1.0,   # Standard position
            VolatilityRegime.HIGH: 0.7,     # Reduce position in high vol
            VolatilityRegime.EXTREME: 0.3   # Significantly reduce in extreme vol
        }
    
    def calculate_position_size(self, 
                              data: pd.DataFrame,
                              entry_price: float,
                              direction: str,
                              portfolio_value: float,
                              risk_level: RiskLevel = RiskLevel.MODERATE,
                              confidence_score: float = 0.5) -> PositionSize:
        """Calculate optimal position size based on volatility and risk."""
        
        # Analyze current volatility
        vol_analysis = self.volatility_analyzer.analyze_volatility(data)
        
        # Get risk parameters for the selected risk level
        risk_params = self.risk_parameters[risk_level]
        
        # Calculate base risk amount
        base_risk_amount = portfolio_value * risk_params['base_risk']
        
        # Adjust risk based on volatility regime
        vol_adjustment = self.volatility_adjustments[vol_analysis['volatility_regime']]
        adjusted_risk_amount = base_risk_amount * vol_adjustment
        
        # Adjust risk based on confidence score
        confidence_adjustment = 0.5 + (confidence_score * 0.5)  # 0.5 to 1.0
        final_risk_amount = adjusted_risk_amount * confidence_adjustment
        
        # Calculate stop loss distance using ATR
        atr_14 = vol_analysis['current_atr']
        sl_distance = atr_14 * risk_params['atr_multiplier_sl']
        
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
        
        # Calculate take profit distance
        tp_distance = atr_14 * risk_params['atr_multiplier_tp']
        if direction.upper() == 'LONG':
            take_profit_price = entry_price + tp_distance
        else:  # SHORT
            take_profit_price = entry_price - tp_distance
        
        return PositionSize(
            asset=data.name if hasattr(data, 'name') else 'UNKNOWN',
            direction=direction,
            position_size=position_size_pct,
            dollar_amount=position_value,
            shares_or_contracts=units,
            stop_loss_distance=sl_distance,
            take_profit_distance=tp_distance,
            risk_amount=final_risk_amount,
            risk_percentage=position_size_pct,
            volatility_regime=vol_analysis['volatility_regime'],
            confidence_score=confidence_score
        )
    
    def calculate_dynamic_sl_tp(self, 
                              data: pd.DataFrame,
                              entry_price: float,
                              direction: str,
                              position_size: PositionSize,
                              time_horizon_hours: int = 24) -> DynamicSLTP:
        """Calculate dynamic stop loss and take profit levels."""
        
        vol_analysis = self.volatility_analyzer.analyze_volatility(data)
        atr_14 = vol_analysis['current_atr']
        
        # Base SL/TP using ATR
        base_sl_multiplier = 1.5
        base_tp_multiplier = 2.5
        
        # Time-based adjustments
        time_adjustment = self._calculate_time_adjustment(time_horizon_hours, vol_analysis['volatility_trend'])
        
        # Volatility-based adjustments
        vol_adjustment = self._calculate_volatility_adjustment(vol_analysis['volatility_regime'])
        
        # Calculate final multipliers
        sl_multiplier = base_sl_multiplier * time_adjustment * vol_adjustment
        tp_multiplier = base_tp_multiplier * time_adjustment * vol_adjustment
        
        # Calculate SL/TP prices
        sl_distance = atr_14 * sl_multiplier
        tp_distance = atr_14 * tp_multiplier
        
        if direction.upper() == 'LONG':
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:  # SHORT
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance
        
        # Calculate trailing stop (50% of ATR)
        trailing_stop_distance = atr_14 * 0.5
        if direction.upper() == 'LONG':
            trailing_stop = entry_price + trailing_stop_distance
        else:
            trailing_stop = entry_price - trailing_stop_distance
        
        # Calculate risk-reward ratio
        risk_amount = abs(entry_price - stop_loss)
        reward_amount = abs(take_profit - entry_price)
        risk_reward_ratio = reward_amount / risk_amount if risk_amount > 0 else 1.0
        
        return DynamicSLTP(
            asset=position_size.asset,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop=trailing_stop,
            risk_reward_ratio=risk_reward_ratio,
            volatility_adjusted=True,
            time_adjusted=True
        )
    
    def _calculate_time_adjustment(self, time_horizon: int, vol_trend: str) -> float:
        """Calculate time-based adjustment for SL/TP."""
        # Shorter time horizons get tighter stops
        if time_horizon <= 4:  # Intraday
            base_adjustment = 0.8
        elif time_horizon <= 24:  # Daily
            base_adjustment = 1.0
        else:  # Multi-day
            base_adjustment = 1.2
        
        # Adjust based on volatility trend
        if vol_trend == 'increasing':
            trend_adjustment = 1.1
        elif vol_trend == 'decreasing':
            trend_adjustment = 0.9
        else:
            trend_adjustment = 1.0
        
        return base_adjustment * trend_adjustment
    
    def _calculate_volatility_adjustment(self, vol_regime: VolatilityRegime) -> float:
        """Calculate volatility-based adjustment for SL/TP."""
        adjustments = {
            VolatilityRegime.LOW: 1.2,      # Wider stops in low vol
            VolatilityRegime.NORMAL: 1.0,   # Standard stops
            VolatilityRegime.HIGH: 0.8,     # Tighter stops in high vol
            VolatilityRegime.EXTREME: 0.5   # Very tight stops in extreme vol
        }
        return adjustments.get(vol_regime, 1.0)


class VolatilityBasedRiskManager:
    """Comprehensive risk management using volatility-based position sizing."""
    
    def __init__(self):
        self.position_sizer = PositionSizer()
        self.active_positions = {}
        
    def assess_portfolio_risk(self, 
                            portfolio_value: float,
                            market_data: Dict[str, pd.DataFrame],
                            risk_level: RiskLevel = RiskLevel.MODERATE) -> Dict[str, Any]:
        """Assess overall portfolio risk based on current positions and market conditions."""
        
        total_risk = 0.0
        position_risks = {}
        
        for asset, data in market_data.items():
            if asset in self.active_positions:
                position = self.active_positions[asset]
                vol_analysis = self.position_sizer.volatility_analyzer.analyze_volatility(data)
                
                # Calculate current position risk
                current_risk = self._calculate_current_position_risk(position, vol_analysis)
                position_risks[asset] = current_risk
                total_risk += current_risk
        
        # Calculate portfolio-level risk metrics
        portfolio_risk_score = min(total_risk / portfolio_value, 1.0)
        
        return {
            'total_portfolio_risk': total_risk,
            'portfolio_risk_percentage': portfolio_risk_score * 100,
            'position_risks': position_risks,
            'recommended_actions': self._generate_risk_recommendations(portfolio_risk_score, risk_level),
            'volatility_impact': self._assess_volatility_impact(market_data)
        }
    
    def _calculate_current_position_risk(self, position: PositionSize, 
                                       vol_analysis: Dict[str, Any]) -> float:
        """Calculate current risk of an active position."""
        
        # Base risk is position size times volatility factor
        base_risk = position.position_size
        
        # Adjust for current volatility regime
        vol_factor = {
            VolatilityRegime.LOW: 0.8,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.HIGH: 1.5,
            VolatilityRegime.EXTREME: 2.5
        }
        
        current_vol_factor = vol_factor.get(vol_analysis['volatility_regime'], 1.0)
        
        # Adjust for position direction and market trend
        trend_factor = 1.0
        if vol_analysis['volatility_trend'] == 'increasing':
            trend_factor = 1.2  # Higher risk in increasing volatility
        
        return base_risk * current_vol_factor * trend_factor
    
    def _generate_risk_recommendations(self, portfolio_risk: float, 
                                     risk_level: RiskLevel) -> List[str]:
        """Generate risk management recommendations."""
        
        recommendations = []
        
        risk_limits = {
            RiskLevel.CONSERVATIVE: 0.10,  # 10% max portfolio risk
            RiskLevel.MODERATE: 0.20,      # 20% max portfolio risk
            RiskLevel.AGGRESSIVE: 0.35     # 35% max portfolio risk
        }
        
        max_risk = risk_limits[risk_level]
        
        if portfolio_risk > max_risk:
            recommendations.append(f"Reduce portfolio risk - current: {portfolio_risk:.1%}, max: {max_risk:.1%}")
            recommendations.append("Consider reducing position sizes or exiting high-risk positions")
        
        if portfolio_risk < max_risk * 0.5:
            recommendations.append("Portfolio risk is conservative - consider increasing position sizes")
        
        return recommendations
    
    def _assess_volatility_impact(self, market_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Assess the impact of current volatility on the portfolio."""
        
        vol_regimes = []
        avg_volatility = 0.0
        
        for asset, data in market_data.items():
            vol_analysis = self.position_sizer.volatility_analyzer.analyze_volatility(data)
            vol_regimes.append(vol_analysis['volatility_regime'].value)
            avg_volatility += vol_analysis['normalized_volatility']
        
        avg_volatility /= len(market_data) if market_data else 1
        
        # Determine overall market volatility state
        extreme_count = vol_regimes.count(VolatilityRegime.EXTREME.value)
        high_count = vol_regimes.count(VolatilityRegime.HIGH.value)
        
        if extreme_count > len(market_data) * 0.3:
            market_state = "EXTREME_VOLATILITY"
        elif high_count > len(market_data) * 0.5:
            market_state = "HIGH_VOLATILITY"
        else:
            market_state = "NORMAL_VOLATILITY"
        
        return {
            'average_volatility': avg_volatility,
            'market_volatility_state': market_state,
            'volatility_regimes': vol_regimes,
            'recommendation': self._get_volatility_recommendation(market_state)
        }
    
    def _get_volatility_recommendation(self, market_state: str) -> str:
        """Get recommendation based on market volatility state."""
        
        recommendations = {
            "EXTREME_VOLATILITY": "Reduce position sizes significantly and use very tight stops",
            "HIGH_VOLATILITY": "Reduce position sizes and use tighter stops than usual",
            "NORMAL_VOLATILITY": "Use standard position sizing and stop loss levels"
        }
        
        return recommendations.get(market_state, "Monitor volatility levels closely")


def main():
    """Demonstrate volatility-based position sizing functionality."""
    print("Starting Volatility-Based Position Sizing Demonstration...")
    
    # Create sample market data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    np.random.seed(42)
    
    # Generate sample price data with different volatility regimes
    base_price = 100
    prices = [base_price]
    
    for i in range(1, 100):
        # Simulate different volatility regimes
        if i < 30:
            volatility = 0.5  # Low volatility
        elif i < 70:
            volatility = 1.5  # Normal to high volatility
        else:
            volatility = 3.0  # High volatility
            
        noise = np.random.normal(0, volatility)
        new_price = prices[-1] * (1 + noise / 100)
        prices.append(new_price)
    
    # Create DataFrame
    data = pd.DataFrame({
        'open': prices[:-1],
        'high': [p * (1 + abs(np.random.normal(0, 0.1))/100) for p in prices[:-1]],
        'low': [p * (1 - abs(np.random.normal(0, 0.1))/100) for p in prices[:-1]],
        'close': prices[1:],
        'volume': np.random.randint(1000, 5000, 99)
    }, index=dates[:-1])
    
    # Test volatility analysis
    analyzer = VolatilityAnalyzer()
    vol_analysis = analyzer.analyze_volatility(data)
    
    print(f"Volatility Analysis Results:")
    print(f"  Current ATR: {vol_analysis['current_atr']:.2f}")
    print(f"  Volatility Regime: {vol_analysis['volatility_regime'].value}")
    print(f"  Volatility Trend: {vol_analysis['volatility_trend']}")
    print(f"  Normalized Volatility: {vol_analysis['normalized_volatility']:.2f}")
    
    # Test position sizing
    sizer = PositionSizer()
    portfolio_value = 100000  # $100k portfolio
    
    position_size = sizer.calculate_position_size(
        data=data,
        entry_price=100.0,
        direction='LONG',
        portfolio_value=portfolio_value,
        risk_level=RiskLevel.MODERATE,
        confidence_score=0.8
    )
    
    print(f"\nPosition Sizing Results:")
    print(f"  Position Size: {position_size.position_size:.2%}")
    print(f"  Dollar Amount: ${position_size.dollar_amount:,.2f}")
    print(f"  Shares: {position_size.shares_or_contracts:.2f}")
    print(f"  Risk Amount: ${position_size.risk_amount:,.2f}")
    print(f"  Volatility Regime: {position_size.volatility_regime.value}")
    
    # Test dynamic SL/TP
    dynamic_sltp = sizer.calculate_dynamic_sl_tp(
        data=data,
        entry_price=100.0,
        direction='LONG',
        position_size=position_size,
        time_horizon_hours=24
    )
    
    print(f"\nDynamic SL/TP Results:")
    print(f"  Stop Loss: ${dynamic_sltp.stop_loss:.2f}")
    print(f"  Take Profit: ${dynamic_sltp.take_profit:.2f}")
    print(f"  Trailing Stop: ${dynamic_sltp.trailing_stop:.2f}")
    print(f"  Risk-Reward Ratio: {dynamic_sltp.risk_reward_ratio:.2f}")
    
    # Test portfolio risk assessment
    risk_manager = VolatilityBasedRiskManager()
    market_data = {'SOL': data, 'ETH': data, 'BTC': data}  # Simplified
    
    risk_assessment = risk_manager.assess_portfolio_risk(
        portfolio_value=portfolio_value,
        market_data=market_data,
        risk_level=RiskLevel.MODERATE
    )
    
    print(f"\nPortfolio Risk Assessment:")
    print(f"  Total Portfolio Risk: ${risk_assessment['total_portfolio_risk']:,.2f}")
    print(f"  Portfolio Risk %: {risk_assessment['portfolio_risk_percentage']:.1f}%")
    print(f"  Market Volatility State: {risk_assessment['volatility_impact']['market_volatility_state']}")
    
    print("\nVolatility-based position sizing demonstration completed!")
    
    return {
        'volatility_analysis': vol_analysis,
        'position_size': position_size,
        'dynamic_sltp': dynamic_sltp,
        'risk_assessment': risk_assessment
    }


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        print(f"Error in volatility-based position sizing demonstration: {e}")
        import traceback
        traceback.print_exc()
