"""
order_flow_analyzer.py — Order flow analysis and volume profile integration
Implements order book analysis, volume profile generation, and execution quality optimization
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging
import asyncio
import websockets
import json
from datetime import datetime, timedelta
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class OrderFlowDirection(Enum):
    """Order flow direction classifications."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    REVERSAL = "REVERSAL"


class VolumeProfileType(Enum):
    """Volume profile types."""
    FIXED_RANGE = "FIXED_RANGE"
    VARIABLE_RANGE = "VARIABLE_RANGE"
    TIME_BASED = "TIME_BASED"


class LiquidityLevel(Enum):
    """Liquidity level classifications."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    DRY = "DRY"


@dataclass
class OrderBookSnapshot:
    """Order book snapshot at a specific time."""
    timestamp: datetime
    bids: Dict[float, float]  # price -> volume
    asks: Dict[float, float]  # price -> volume
    mid_price: float
    spread: float
    total_bid_volume: float
    total_ask_volume: float
    order_flow_imbalance: float


@dataclass
class VolumeProfile:
    """Volume profile analysis result."""
    price_levels: Dict[float, float]  # price -> volume
    pocs: List[float]  # Point of Control
    value_areas: List[Tuple[float, float]]  # (low, high) ranges
    high_volume_nodes: List[float]
    low_volume_nodes: List[float]
    profile_type: VolumeProfileType
    profile_skew: float  # -1 to 1, negative = bearish, positive = bullish


@dataclass
class OrderFlowAnalysis:
    """Order flow analysis result."""
    timestamp: datetime
    direction: OrderFlowDirection
    strength: float  # 0 to 1
    volume_profile: VolumeProfile
    order_flow_imbalance: float
    absorption_levels: List[float]
    support_levels: List[float]
    resistance_levels: List[float]
    liquidity_score: float
    execution_recommendation: str


class OrderBookAnalyzer:
    """Advanced order book analysis and order flow detection."""
    
    def __init__(self, symbol: str, exchange: str = "hyperliquid"):
        self.symbol = symbol
        self.exchange = exchange
        self.snapshots: List[OrderBookSnapshot] = []
        self.max_snapshots = 1000
        
        # Order flow analysis parameters
        self.imbalance_threshold = 0.1  # 10% imbalance threshold
        self.volume_threshold = 0.05    # 5% volume threshold for significant moves
        self.time_window = 300          # 5-minute analysis window
        
    async def connect_order_book(self) -> None:
        """Connect to order book websocket and start collecting data."""
        try:
            if self.exchange.lower() == "hyperliquid":
                await self._connect_hyperliquid_order_book()
            elif self.exchange.lower() == "binance":
                await self._connect_binance_order_book()
            else:
                logger.warning(f"Exchange {self.exchange} not supported for real-time order book")
        except Exception as e:
            logger.error(f"Failed to connect to order book: {e}")
    
    async def _connect_hyperliquid_order_book(self) -> None:
        """Connect to Hyperliquid order book websocket."""
        # This is a placeholder - in practice, you would use the actual Hyperliquid API
        logger.info(f"Connecting to Hyperliquid order book for {self.symbol}")
        
        # Simulate order book updates for demonstration
        while True:
            snapshot = self._generate_mock_order_book_snapshot()
            self.add_snapshot(snapshot)
            await asyncio.sleep(1)  # Update every second
    
    async def _connect_binance_order_book(self) -> None:
        """Connect to Binance order book websocket."""
        # This is a placeholder - in practice, you would use the actual Binance API
        logger.info(f"Connecting to Binance order book for {self.symbol}")
        
        # Simulate order book updates for demonstration
        while True:
            snapshot = self._generate_mock_order_book_snapshot()
            self.add_snapshot(snapshot)
            await asyncio.sleep(1)  # Update every second
    
    def _generate_mock_order_book_snapshot(self) -> OrderBookSnapshot:
        """Generate mock order book snapshot for demonstration."""
        current_time = datetime.now()
        
        # Generate mock bid/ask data
        base_price = 100.0
        spread = 0.1
        
        # Generate bids
        bids = {}
        for i in range(10):
            price = base_price - (i * 0.01)
            volume = np.random.uniform(10, 100)
            bids[price] = volume
        
        # Generate asks
        asks = {}
        for i in range(10):
            price = base_price + spread + (i * 0.01)
            volume = np.random.uniform(10, 100)
            asks[price] = volume
        
        mid_price = (base_price + base_price + spread) / 2
        
        total_bid_volume = sum(bids.values())
        total_ask_volume = sum(asks.values())
        
        order_flow_imbalance = (total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume)
        
        return OrderBookSnapshot(
            timestamp=current_time,
            bids=bids,
            asks=asks,
            mid_price=mid_price,
            spread=spread,
            total_bid_volume=total_bid_volume,
            total_ask_volume=total_ask_volume,
            order_flow_imbalance=order_flow_imbalance
        )
    
    def add_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Add a new order book snapshot."""
        self.snapshots.append(snapshot)
        
        # Keep only recent snapshots
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots.pop(0)
    
    def analyze_order_flow(self) -> OrderFlowAnalysis:
        """Analyze order flow from recent snapshots."""
        if len(self.snapshots) < 10:
            return self._get_default_order_flow_analysis()
        
        try:
            # Get recent snapshots
            recent_snapshots = self.snapshots[-min(len(self.snapshots), 100):]
            
            # Calculate order flow metrics
            order_flow_imbalance = np.mean([s.order_flow_imbalance for s in recent_snapshots])
            
            # Analyze volume distribution
            volume_profile = self._calculate_volume_profile(recent_snapshots)
            
            # Detect absorption levels
            absorption_levels = self._detect_absorption_levels(recent_snapshots)
            
            # Detect support/resistance levels
            support_levels, resistance_levels = self._detect_support_resistance(recent_snapshots)
            
            # Calculate liquidity score
            liquidity_score = self._calculate_liquidity_score(recent_snapshots)
            
            # Determine order flow direction
            direction = self._determine_order_flow_direction(order_flow_imbalance, recent_snapshots)
            
            # Calculate strength
            strength = abs(order_flow_imbalance)
            
            # Generate execution recommendation
            recommendation = self._generate_execution_recommendation(
                direction, strength, liquidity_score, absorption_levels
            )
            
            return OrderFlowAnalysis(
                timestamp=datetime.now(),
                direction=direction,
                strength=strength,
                volume_profile=volume_profile,
                order_flow_imbalance=order_flow_imbalance,
                absorption_levels=absorption_levels,
                support_levels=support_levels,
                resistance_levels=resistance_levels,
                liquidity_score=liquidity_score,
                execution_recommendation=recommendation
            )
            
        except Exception as e:
            logger.error(f"Error in order flow analysis: {e}")
            return self._get_default_order_flow_analysis()
    
    def _calculate_volume_profile(self, snapshots: List[OrderBookSnapshot]) -> VolumeProfile:
        """Calculate volume profile from order book snapshots."""
        price_levels = {}
        
        # Aggregate volume across all snapshots
        for snapshot in snapshots:
            for price, volume in snapshot.bids.items():
                if price in price_levels:
                    price_levels[price] += volume
                else:
                    price_levels[price] = volume
            
            for price, volume in snapshot.asks.items():
                if price in price_levels:
                    price_levels[price] += volume
                else:
                    price_levels[price] = volume
        
        # Find Point of Control (POC)
        if price_levels:
            poc = max(price_levels, key=price_levels.get)
            pocs = [poc]
        else:
            pocs = []
        
        # Calculate value areas (70% of volume)
        total_volume = sum(price_levels.values())
        sorted_levels = sorted(price_levels.items(), key=lambda x: x[1], reverse=True)
        
        value_area_volume = 0
        value_areas = []
        current_range = None
        
        for price, volume in sorted_levels:
            if value_area_volume < total_volume * 0.7:
                if current_range is None:
                    current_range = [price, price]
                else:
                    current_range[0] = min(current_range[0], price)
                    current_range[1] = max(current_range[1], price)
                value_area_volume += volume
            else:
                if current_range:
                    value_areas.append((current_range[0], current_range[1]))
                    current_range = None
        
        if current_range:
            value_areas.append((current_range[0], current_range[1]))
        
        # Find high and low volume nodes
        avg_volume = total_volume / len(price_levels) if price_levels else 0
        high_volume_nodes = [p for p, v in price_levels.items() if v > avg_volume * 2]
        low_volume_nodes = [p for p, v in price_levels.items() if v < avg_volume * 0.5]
        
        # Calculate profile skew
        mid_price = sum(price_levels.keys()) / len(price_levels) if price_levels else 0
        bullish_volume = sum(v for p, v in price_levels.items() if p > mid_price)
        bearish_volume = sum(v for p, v in price_levels.items() if p < mid_price)
        profile_skew = (bullish_volume - bearish_volume) / (bullish_volume + bearish_volume) if (bullish_volume + bearish_volume) > 0 else 0
        
        return VolumeProfile(
            price_levels=price_levels,
            pocs=pocs,
            value_areas=value_areas,
            high_volume_nodes=high_volume_nodes,
            low_volume_nodes=low_volume_nodes,
            profile_type=VolumeProfileType.TIME_BASED,
            profile_skew=profile_skew
        )
    
    def _detect_absorption_levels(self, snapshots: List[OrderBookSnapshot]) -> List[float]:
        """Detect absorption levels where large orders are being absorbed."""
        absorption_levels = []
        
        if len(snapshots) < 5:
            return absorption_levels
        
        # Look for price levels where volume persists despite price movement
        price_volumes = {}
        
        for snapshot in snapshots:
            for price, volume in snapshot.bids.items():
                if price not in price_volumes:
                    price_volumes[price] = []
                price_volumes[price].append(volume)
            
            for price, volume in snapshot.asks.items():
                if price not in price_volumes:
                    price_volumes[price] = []
                price_volumes[price].append(volume)
        
        # Find levels with consistently high volume
        for price, volumes in price_volumes.items():
            if len(volumes) >= 5:
                avg_volume = np.mean(volumes)
                std_volume = np.std(volumes)
                
                # High volume with low volatility (indicating absorption)
                if avg_volume > 50 and std_volume / avg_volume < 0.3:
                    absorption_levels.append(price)
        
        return sorted(absorption_levels)
    
    def _detect_support_resistance(self, snapshots: List[OrderBookSnapshot]) -> Tuple[List[float], List[float]]:
        """Detect support and resistance levels from order book data."""
        support_levels = []
        resistance_levels = []
        
        if not snapshots:
            return support_levels, resistance_levels
        
        # Get price range
        all_prices = []
        for snapshot in snapshots:
            all_prices.extend(snapshot.bids.keys())
            all_prices.extend(snapshot.asks.keys())
        
        if not all_prices:
            return support_levels, resistance_levels
        
        min_price = min(all_prices)
        max_price = max(all_prices)
        price_range = max_price - min_price
        
        # Create price buckets
        bucket_size = price_range / 20  # 20 buckets
        buckets = {}
        
        for snapshot in snapshots:
            for price in snapshot.bids.keys():
                bucket = int((price - min_price) / bucket_size)
                if bucket not in buckets:
                    buckets[bucket] = {'bid_volume': 0, 'ask_volume': 0}
                buckets[bucket]['bid_volume'] += snapshot.bids[price]
            
            for price in snapshot.asks.keys():
                bucket = int((price - min_price) / bucket_size)
                if bucket not in buckets:
                    buckets[bucket] = {'bid_volume': 0, 'ask_volume': 0}
                buckets[bucket]['ask_volume'] += snapshot.asks[price]
        
        # Find support levels (high bid volume)
        for bucket, data in buckets.items():
            if data['bid_volume'] > data['ask_volume'] * 2:
                price = min_price + (bucket * bucket_size)
                support_levels.append(price)
        
        # Find resistance levels (high ask volume)
        for bucket, data in buckets.items():
            if data['ask_volume'] > data['bid_volume'] * 2:
                price = min_price + (bucket * bucket_size)
                resistance_levels.append(price)
        
        return sorted(support_levels), sorted(resistance_levels)
    
    def _calculate_liquidity_score(self, snapshots: List[OrderBookSnapshot]) -> float:
        """Calculate liquidity score based on order book depth and stability."""
        if not snapshots:
            return 0.5
        
        # Calculate average spread
        spreads = [s.spread for s in snapshots]
        avg_spread = np.mean(spreads)
        
        # Calculate order book depth stability
        depths = []
        for snapshot in snapshots:
            bid_depth = sum(list(snapshot.bids.values())[:5])  # Top 5 levels
            ask_depth = sum(list(snapshot.asks.values())[:5])  # Top 5 levels
            depths.append((bid_depth + ask_depth) / 2)
        
        depth_stability = 1.0 / (1.0 + np.std(depths) / np.mean(depths))
        
        # Calculate liquidity score (0 to 1)
        # Lower spread and higher stability = higher liquidity
        spread_score = max(0, 1 - (avg_spread / 0.5))  # Normalize spread to 0-1
        liquidity_score = (spread_score * 0.6) + (depth_stability * 0.4)
        
        return max(0.0, min(1.0, liquidity_score))
    
    def _determine_order_flow_direction(self, imbalance: float, snapshots: List[OrderBookSnapshot]) -> OrderFlowDirection:
        """Determine order flow direction based on imbalance and recent trends."""
        if abs(imbalance) < self.imbalance_threshold:
            return OrderFlowDirection.NEUTRAL
        
        # Check recent trend
        if len(snapshots) >= 10:
            recent_imbalances = [s.order_flow_imbalance for s in snapshots[-10:]]
            trend = np.mean(recent_imbalances)
            
            if trend > self.imbalance_threshold:
                return OrderFlowDirection.BULLISH
            elif trend < -self.imbalance_threshold:
                return OrderFlowDirection.BEARISH
        
        # Fallback to current imbalance
        if imbalance > self.imbalance_threshold:
            return OrderFlowDirection.BULLISH
        elif imbalance < -self.imbalance_threshold:
            return OrderFlowDirection.BEARISH
        else:
            return OrderFlowDirection.NEUTRAL
    
    def _generate_execution_recommendation(self, direction: OrderFlowDirection, 
                                          strength: float, liquidity_score: float,
                                          absorption_levels: List[float]) -> str:
        """Generate execution recommendation based on order flow analysis."""
        
        if liquidity_score < 0.3:
            return "Poor liquidity - consider smaller order size or wait for better conditions"
        
        if strength < 0.2:
            return "Weak order flow - be cautious with entry"
        
        if direction == OrderFlowDirection.BULLISH:
            if absorption_levels:
                return f"Bullish order flow with absorption at {absorption_levels[0]:.2f} - consider long entry"
            else:
                return "Bullish order flow detected - consider long entry"
        elif direction == OrderFlowDirection.BEARISH:
            if absorption_levels:
                return f"Bearish order flow with absorption at {absorption_levels[0]:.2f} - consider short entry"
            else:
                return "Bearish order flow detected - consider short entry"
        else:
            return "Neutral order flow - wait for clearer direction"
    
    def _get_default_order_flow_analysis(self) -> OrderFlowAnalysis:
        """Return default order flow analysis for insufficient data."""
        return OrderFlowAnalysis(
            timestamp=datetime.now(),
            direction=OrderFlowDirection.NEUTRAL,
            strength=0.0,
            volume_profile=VolumeProfile(
                price_levels={},
                pocs=[],
                value_areas=[],
                high_volume_nodes=[],
                low_volume_nodes=[],
                profile_type=VolumeProfileType.TIME_BASED,
                profile_skew=0.0
            ),
            order_flow_imbalance=0.0,
            absorption_levels=[],
            support_levels=[],
            resistance_levels=[],
            liquidity_score=0.5,
            execution_recommendation="Insufficient data for analysis"
        )


class VolumeProfileAnalyzer:
    """Advanced volume profile analysis for trading decisions."""
    
    def __init__(self):
        self.profile_cache = {}
        self.cache_ttl = 300  # 5 minutes
    
    def analyze_volume_profile(self, price_data: pd.DataFrame, 
                             volume_data: pd.Series,
                             profile_type: VolumeProfileType = VolumeProfileType.TIME_BASED,
                             time_frame: str = "1H") -> VolumeProfile:
        """Analyze volume profile from historical price and volume data."""
        
        try:
            # Create price buckets based on the data range
            min_price = price_data.min()
            max_price = price_data.max()
            price_range = max_price - min_price
            
            if price_range == 0:
                return self._get_default_volume_profile()
            
            # Determine bucket size based on time frame
            if time_frame == "1H":
                bucket_size = price_range / 50  # 50 buckets for 1 hour
            elif time_frame == "4H":
                bucket_size = price_range / 100  # 100 buckets for 4 hours
            elif time_frame == "1D":
                bucket_size = price_range / 200  # 200 buckets for 1 day
            else:
                bucket_size = price_range / 100  # Default
            
            # Create volume buckets
            buckets = {}
            
            for i, price in enumerate(price_data):
                volume = volume_data.iloc[i]
                bucket = int((price - min_price) / bucket_size)
                
                if bucket not in buckets:
                    buckets[bucket] = 0
                buckets[bucket] += volume
            
            # Convert buckets to price levels
            price_levels = {}
            for bucket, volume in buckets.items():
                price = min_price + (bucket * bucket_size)
                price_levels[price] = volume
            
            # Find Point of Control (POC)
            if price_levels:
                poc = max(price_levels, key=price_levels.get)
                pocs = [poc]
            else:
                pocs = []
            
            # Calculate value areas
            total_volume = sum(price_levels.values())
            sorted_levels = sorted(price_levels.items(), key=lambda x: x[1], reverse=True)
            
            value_area_volume = 0
            value_areas = []
            current_range = None
            
            for price, volume in sorted_levels:
                if value_area_volume < total_volume * 0.7:
                    if current_range is None:
                        current_range = [price, price]
                    else:
                        current_range[0] = min(current_range[0], price)
                        current_range[1] = max(current_range[1], price)
                    value_area_volume += volume
                else:
                    if current_range:
                        value_areas.append((current_range[0], current_range[1]))
                        current_range = None
            
            if current_range:
                value_areas.append((current_range[0], current_range[1]))
            
            # Find high and low volume nodes
            avg_volume = total_volume / len(price_levels) if price_levels else 0
            high_volume_nodes = [p for p, v in price_levels.items() if v > avg_volume * 2]
            low_volume_nodes = [p for p, v in price_levels.items() if v < avg_volume * 0.5]
            
            # Calculate profile skew
            mid_price = sum(price_levels.keys()) / len(price_levels) if price_levels else 0
            bullish_volume = sum(v for p, v in price_levels.items() if p > mid_price)
            bearish_volume = sum(v for p, v in price_levels.items() if p < mid_price)
            profile_skew = (bullish_volume - bearish_volume) / (bullish_volume + bearish_volume) if (bullish_volume + bearish_volume) > 0 else 0
            
            return VolumeProfile(
                price_levels=price_levels,
                pocs=pocs,
                value_areas=value_areas,
                high_volume_nodes=high_volume_nodes,
                low_volume_nodes=low_volume_nodes,
                profile_type=profile_type,
                profile_skew=profile_skew
            )
            
        except Exception as e:
            logger.error(f"Error in volume profile analysis: {e}")
            return self._get_default_volume_profile()
    
    def identify_key_levels(self, volume_profile: VolumeProfile) -> Dict[str, List[float]]:
        """Identify key trading levels from volume profile."""
        
        key_levels = {
            'support': [],
            'resistance': [],
            'poc': volume_profile.pocs,
            'high_volume_nodes': volume_profile.high_volume_nodes,
            'low_volume_nodes': volume_profile.low_volume_nodes
        }
        
        # Add value area boundaries as support/resistance
        for low, high in volume_profile.value_areas:
            key_levels['support'].append(low)
            key_levels['resistance'].append(high)
        
        # Sort and deduplicate
        for level_type in ['support', 'resistance']:
            key_levels[level_type] = sorted(list(set(key_levels[level_type])))
        
        return key_levels
    
    def calculate_volume_profile_signals(self, current_price: float, 
                                       volume_profile: VolumeProfile) -> Dict[str, Any]:
        """Calculate trading signals based on volume profile analysis."""
        
        signals = {
            'signal_type': 'NEUTRAL',
            'strength': 0.0,
            'target_levels': [],
            'stop_loss_levels': [],
            'confidence': 0.0,
            'rationale': ''
        }
        
        if not volume_profile.pocs:
            return signals
        
        poc = volume_profile.pocs[0]
        
        # Determine signal based on price relative to POC and profile skew
        price_distance_from_poc = (current_price - poc) / poc
        
        if volume_profile.profile_skew > 0.3:  # Bullish skew
            if current_price < poc:
                signals['signal_type'] = 'BUY'
                signals['strength'] = 0.7 + (abs(price_distance_from_poc) * 0.3)
                signals['target_levels'] = [p for p in volume_profile.high_volume_nodes if p > current_price]
                signals['stop_loss_levels'] = [p for p in volume_profile.low_volume_nodes if p < current_price]
                signals['rationale'] = f"Price below POC in bullish profile (skew: {volume_profile.profile_skew:.2f})"
            else:
                signals['signal_type'] = 'BUY'
                signals['strength'] = 0.5
                signals['rationale'] = f"Price above POC in bullish profile (skew: {volume_profile.profile_skew:.2f})"
        
        elif volume_profile.profile_skew < -0.3:  # Bearish skew
            if current_price > poc:
                signals['signal_type'] = 'SELL'
                signals['strength'] = 0.7 + (abs(price_distance_from_poc) * 0.3)
                signals['target_levels'] = [p for p in volume_profile.high_volume_nodes if p < current_price]
                signals['stop_loss_levels'] = [p for p in volume_profile.low_volume_nodes if p > current_price]
                signals['rationale'] = f"Price above POC in bearish profile (skew: {volume_profile.profile_skew:.2f})"
            else:
                signals['signal_type'] = 'SELL'
                signals['strength'] = 0.5
                signals['rationale'] = f"Price below POC in bearish profile (skew: {volume_profile.profile_skew:.2f})"
        
        else:  # Neutral profile
            signals['rationale'] = f"Neutral profile (skew: {volume_profile.profile_skew:.2f})"
        
        # Calculate confidence based on volume concentration
        if volume_profile.pocs:
            poc_volume = volume_profile.price_levels.get(poc, 0)
            total_volume = sum(volume_profile.price_levels.values())
            signals['confidence'] = poc_volume / total_volume if total_volume > 0 else 0.0
        
        return signals
    
    def _get_default_volume_profile(self) -> VolumeProfile:
        """Return default volume profile for insufficient data."""
        return VolumeProfile(
            price_levels={},
            pocs=[],
            value_areas=[],
            high_volume_nodes=[],
            low_volume_nodes=[],
            profile_type=VolumeProfileType.TIME_BASED,
            profile_skew=0.0
        )


class ExecutionOptimizer:
    """Optimize execution based on order flow and volume profile analysis."""
    
    def __init__(self):
        self.order_book_analyzer = None
        self.volume_profile_analyzer = VolumeProfileAnalyzer()
    
    def optimize_execution(self, symbol: str, order_size: float, 
                          current_price: float, direction: str,
                          time_frame: str = "1H") -> Dict[str, Any]:
        """Optimize execution strategy based on market microstructure."""
        
        optimization_result = {
            'recommended_size': order_size,
            'execution_strategy': 'MARKET',
            'timing_recommendation': 'IMMEDIATE',
            'expected_slippage': 0.0,
            'liquidity_score': 0.5,
            'key_levels': {},
            'rationale': ''
        }
        
        try:
            # Analyze volume profile from historical data
            # In practice, this would use real historical data
            price_data = pd.Series([current_price * (1 + np.random.normal(0, 0.01)) for _ in range(100)])
            volume_data = pd.Series(np.random.uniform(10, 100, 100))
            
            volume_profile = self.volume_profile_analyzer.analyze_volume_profile(
                price_data, volume_data, time_frame=time_frame
            )
            
            key_levels = self.volume_profile_analyzer.identify_key_levels(volume_profile)
            
            # Analyze order flow (if real-time data available)
            if self.order_book_analyzer:
                order_flow_analysis = self.order_book_analyzer.analyze_order_flow()
                liquidity_score = order_flow_analysis.liquidity_score
                order_flow_direction = order_flow_analysis.direction
                order_flow_strength = order_flow_analysis.strength
            else:
                liquidity_score = 0.7
                order_flow_direction = OrderFlowDirection.NEUTRAL
                order_flow_strength = 0.0
            
            # Determine optimal execution strategy
            if liquidity_score < 0.4:
                optimization_result['execution_strategy'] = 'LIMIT'
                optimization_result['timing_recommendation'] = 'WAIT_FOR_BETTER_LIQUIDITY'
                optimization_result['expected_slippage'] = 0.005  # 0.5%
                optimization_result['rationale'] = "Poor liquidity - use limit orders and wait"
            
            elif order_flow_strength > 0.5 and order_flow_direction != OrderFlowDirection.NEUTRAL:
                optimization_result['execution_strategy'] = 'MARKET'
                optimization_result['timing_recommendation'] = 'IMMEDIATE'
                optimization_result['expected_slippage'] = 0.001  # 0.1%
                optimization_result['rationale'] = f"Strong {order_flow_direction.value.lower()} order flow - execute immediately"
            
            elif order_size > 100000:  # Large order
                optimization_result['execution_strategy'] = 'VWAP'
                optimization_result['timing_recommendation'] = 'SPREAD_OVER_TIME'
                optimization_result['expected_slippage'] = 0.003  # 0.3%
                optimization_result['rationale'] = "Large order size - use VWAP to minimize market impact"
            
            else:
                optimization_result['execution_strategy'] = 'LIMIT'
                optimization_result['timing_recommendation'] = 'NEAR_KEY_LEVELS'
                optimization_result['expected_slippage'] = 0.002  # 0.2%
                optimization_result['rationale'] = "Moderate conditions - use limit orders near key levels"
            
            # Adjust order size based on liquidity
            if liquidity_score < 0.3:
                optimization_result['recommended_size'] = order_size * 0.5
            elif liquidity_score > 0.8:
                optimization_result['recommended_size'] = order_size * 1.2
            
            optimization_result['liquidity_score'] = liquidity_score
            optimization_result['key_levels'] = key_levels
            
        except Exception as e:
            logger.error(f"Error in execution optimization: {e}")
            optimization_result['rationale'] = "Error in optimization - use standard execution"
        
        return optimization_result


def main():
    """Demonstrate order flow analysis and volume profile functionality."""
    print("Starting Order Flow Analysis and Volume Profile Demonstration...")
    
    # Test order book analyzer
    print("\n1. Order Book Analysis:")
    order_book_analyzer = OrderBookAnalyzer("SOL/USDT", "hyperliquid")
    
    # Simulate collecting some snapshots
    for _ in range(50):
        snapshot = order_book_analyzer._generate_mock_order_book_snapshot()
        order_book_analyzer.add_snapshot(snapshot)
        time.sleep(0.1)  # Small delay
    
    order_flow_analysis = order_book_analyzer.analyze_order_flow()
    
    print(f"  Order Flow Direction: {order_flow_analysis.direction.value}")
    print(f"  Order Flow Strength: {order_flow_analysis.strength:.2f}")
    print(f"  Liquidity Score: {order_flow_analysis.liquidity_score:.2f}")
    print(f"  Absorption Levels: {[f'{p:.2f}' for p in order_flow_analysis.absorption_levels[:3]]}")
    print(f"  Support Levels: {[f'{p:.2f}' for p in order_flow_analysis.support_levels[:3]]}")
    print(f"  Resistance Levels: {[f'{p:.2f}' for p in order_flow_analysis.resistance_levels[:3]]}")
    print(f"  Execution Recommendation: {order_flow_analysis.execution_recommendation}")
    
    # Test volume profile analyzer
    print("\n2. Volume Profile Analysis:")
    volume_analyzer = VolumeProfileAnalyzer()
    
    # Generate sample price and volume data
    base_price = 100.0
    prices = [base_price * (1 + np.random.normal(0, 0.02)) for _ in range(200)]
    volumes = [np.random.uniform(50, 200) for _ in range(200)]
    
    price_data = pd.Series(prices)
    volume_data = pd.Series(volumes)
    
    volume_profile = volume_analyzer.analyze_volume_profile(price_data, volume_data, time_frame="1H")
    
    print(f"  Point of Control: {volume_profile.pocs[0] if volume_profile.pocs else 'N/A'}")
    print(f"  Profile Skew: {volume_profile.profile_skew:.2f}")
    print(f"  High Volume Nodes: {[f'{p:.2f}' for p in volume_profile.high_volume_nodes[:3]]}")
    print(f"  Low Volume Nodes: {[f'{p:.2f}' for p in volume_profile.low_volume_nodes[:3]]}")
    print(f"  Value Areas: {[(f'{low:.2f}', f'{high:.2f}') for low, high in volume_profile.value_areas[:2]]}")
    
    # Test execution optimization
    print("\n3. Execution Optimization:")
    execution_optimizer = ExecutionOptimizer()
    
    optimization = execution_optimizer.optimize_execution(
        symbol="SOL/USDT",
        order_size=50000,
        current_price=100.0,
        direction="LONG",
        time_frame="1H"
    )
    
    print(f"  Recommended Size: ${optimization['recommended_size']:,.2f}")
    print(f"  Execution Strategy: {optimization['execution_strategy']}")
    print(f"  Timing Recommendation: {optimization['timing_recommendation']}")
    print(f"  Expected Slippage: {optimization['expected_slippage']:.4f}")
    print(f"  Liquidity Score: {optimization['liquidity_score']:.2f}")
    print(f"  Rationale: {optimization['rationale']}")
    
    print("\nOrder flow analysis and volume profile demonstration completed!")
    
    return {
        'order_flow_analysis': order_flow_analysis,
        'volume_profile': volume_profile,
        'execution_optimization': optimization
    }


if __name__ == "__main__":
    try:
        result = main()
    except Exception as e:
        print(f"Error in order flow analysis demonstration: {e}")
        import traceback
        traceback.print_exc()