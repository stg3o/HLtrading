#!/usr/bin/env python3
"""
Unit tests for strategy indicator calculations
"""
import unittest
import math
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
import sys
import os

# Add the project root to the path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from strategy import (
    calculate_indicators, calculate_supertrend_indicators,
    get_market_data, get_indicators_for_coin, get_trend_bias,
    _adx, _hurst, _momentum_score, _vol_regime, _trend_slope, _classify_regime_gate,
    attach_derivatives_context, get_btc_market_filter,
    select_strategy_candidates, strategy_matches_regime,
)
from ai_advisor import _rule_based_signal


class TestIndicatorCalculations(unittest.TestCase):
    """Test cases for technical indicator calculations"""
    
    def setUp(self):
        """Set up test data"""
        # Create synthetic OHLCV data
        dates = pd.date_range('2024-01-01', periods=100, freq='4h')
        np.random.seed(42)
        
        # Generate price data with some trend
        close_prices = [100.0]
        for i in range(1, 100):
            change = np.random.normal(0.1, 1.0)  # slight upward drift
            close_prices.append(close_prices[-1] * (1 + change/100))
        
        # Create OHLC data
        self.test_data = pd.DataFrame({
            'Open': close_prices,
            'High': [p * (1 + np.random.uniform(0, 0.01)) for p in close_prices],
            'Low': [p * (1 - np.random.uniform(0, 0.01)) for p in close_prices],
            'Close': close_prices,
            'Volume': np.random.randint(1000, 10000, 100)
        }, index=dates)
    
    def test_adx_calculation(self):
        """Test ADX calculation"""
        adx_result = _adx(self.test_data)
        self.assertIsInstance(adx_result, float)
        self.assertGreaterEqual(adx_result, 0)
        self.assertLessEqual(adx_result, 100)
    
    def test_hurst_exponent(self):
        """Test Hurst Exponent calculation"""
        hurst_result = _hurst(self.test_data['Close'])
        self.assertIsInstance(hurst_result, float)
        self.assertGreaterEqual(hurst_result, 0)
        self.assertLessEqual(hurst_result, 1)
    
    def test_momentum_score(self):
        """Test momentum score calculation"""
        momentum_result = _momentum_score(self.test_data['Close'], self.test_data['Volume'])
        self.assertIsInstance(momentum_result, float)
    
    def test_momentum_score_no_volume(self):
        """Test momentum score calculation without volume"""
        momentum_result = _momentum_score(self.test_data['Close'])
        self.assertIsInstance(momentum_result, float)

    def test_momentum_score_clamps_volume_spike_scaling(self):
        """Volume spikes should not explosively amplify momentum."""
        close = pd.Series(np.linspace(100, 130, 220))
        volume = pd.Series([1000] * 219 + [1000000])
        base = _momentum_score(close)
        boosted = _momentum_score(close, volume)
        self.assertLessEqual(abs(boosted), abs(base) * math.sqrt(2) + 1e-4)
    
    def test_volatility_regime(self):
        """Test volatility regime calculation"""
        vol_result, regime = _vol_regime(self.test_data['Close'])
        self.assertIsInstance(vol_result, float)
        self.assertGreaterEqual(vol_result, 0)
        self.assertIn(regime, ['high', 'normal', 'low'])

    def test_trend_slope(self):
        """Test trend slope calculation"""
        slope = _trend_slope(self.test_data['Close'])
        self.assertIsInstance(slope, float)

    def test_regime_gate(self):
        """Test explicit regime gate classification"""
        self.assertEqual(_classify_regime_gate(30.0, 0.60), ('trend', 'trending'))
        self.assertEqual(_classify_regime_gate(18.0, 0.40), ('mean_reversion', 'mean_reverting'))
        self.assertEqual(_classify_regime_gate(24.0, 0.50), ('neutral', 'neutral'))
    
    def test_calculate_indicators(self):
        """Test full indicator calculation"""
        indicators = calculate_indicators(self.test_data)
        
        self.assertIsInstance(indicators, dict)
        self.assertIn('price', indicators)
        self.assertIn('kc_upper', indicators)
        self.assertIn('kc_lower', indicators)
        self.assertIn('rsi', indicators)
        self.assertIn('adx', indicators)
        self.assertIn('hurst', indicators)
        self.assertIn('momentum', indicators)
        self.assertIn('ann_vol', indicators)
        self.assertIn('vol_regime', indicators)
        self.assertIn('trend_slope', indicators)
        self.assertIn('trend_slope_label', indicators)
        self.assertIn('regime_gate', indicators)
        self.assertIn('entry_quality', indicators)
        self.assertIn('entry_quality_side', indicators)
        
        # Check that derived labels are present
        self.assertIn('price_vs_kc', indicators)
        self.assertIn('ma_alignment', indicators)
        self.assertIn('rsi_zone', indicators)
        self.assertIn('trend_direction', indicators)
        self.assertIn('trend_strength', indicators)
        self.assertIn('market_regime', indicators)
        self.assertIn(indicators['regime_gate'], ['trend', 'mean_reversion', 'neutral'])
        self.assertGreaterEqual(indicators['entry_quality'], 0.0)
        self.assertIn(indicators['entry_quality_side'], ['long', 'short', 'neutral'])
    
    def test_calculate_indicators_custom_kc_scalar(self):
        """Test indicator calculation with custom KC scalar"""
        indicators = calculate_indicators(self.test_data, kc_scalar=2.0)
        self.assertIsInstance(indicators, dict)
        self.assertIn('kc_upper', indicators)
        self.assertIn('kc_lower', indicators)
        self.assertIn('atr_pct', indicators)

    def test_attach_derivatives_context_marks_extreme_funding_and_oi_confirmation(self):
        indicators = {
            "price": 101.0,
            "strategy_regime_match": True,
            "mtf_alignment": True,
            "entry_quality": 0.5,
            "regime": "trend",
            "atr_pct": 0.01,
            "band_width_pct": 0.02,
        }
        attach_derivatives_context("BTC_TEST", {"price": 100.0}, funding_rate=0.0, open_interest=1000.0)
        enriched = attach_derivatives_context("BTC_TEST", indicators, funding_rate=0.0008, open_interest=1020.0)
        self.assertTrue(enriched["funding_extreme"])
        self.assertEqual(enriched["funding_bias"], "short")
        self.assertEqual(enriched["oi_signal"], "trend_up_confirmed")
        self.assertTrue(enriched["trend_oi_confirmed"])

    def test_calculate_indicators_detects_cascade_exhaustion(self):
        data = self.test_data.copy()
        idx = data.index[-2]
        data.loc[idx, "Open"] = 100.0
        data.loc[idx, "Low"] = 99.0
        data.loc[idx, "High"] = 108.0
        data.loc[idx, "Close"] = 104.0
        data.loc[idx, "Volume"] = data["Volume"].iloc[:-1].mean() * 6
        indicators = calculate_indicators(data, kc_scalar=1.0)
        self.assertIn("cascade_event", indicators)
        self.assertIn("cascade_exhaustion", indicators)
        self.assertIn("extreme_cascade", indicators)

    def test_select_strategy_candidates_prefers_regime_match(self):
        candidates = [
            ("BTC", {"hl_symbol": "BTC"}, {"strategy_regime_match": False, "allocator_score": 0.9}),
            ("BTC_RANGE", {"hl_symbol": "BTC"}, {"strategy_regime_match": True, "allocator_score": 0.2}),
            ("SOL", {"hl_symbol": "SOL"}, {"strategy_regime_match": True, "allocator_score": 0.5}),
        ]
        selected = select_strategy_candidates(candidates)
        self.assertEqual([coin for coin, _, _ in selected], ["BTC_RANGE", "SOL"])

    def test_strategy_matches_regime_uses_defaults(self):
        self.assertTrue(strategy_matches_regime({"strategy_type": "mean_reversion"}, "range"))
        self.assertFalse(strategy_matches_regime({"strategy_type": "mean_reversion"}, "trend"))

    @patch("strategy.get_market_data")
    @patch("strategy.calculate_indicators")
    def test_get_btc_market_filter_flags_risk_off(self, mock_calc, mock_download):
        mock_download.return_value = self.test_data
        mock_calc.return_value = {
            "adx": 35.0,
            "atr_pct": 0.035,
            "trend_direction": "up",
            "vol_regime": "high",
            "band_width_pct": 0.07,
        }
        result = get_btc_market_filter()
        self.assertTrue(result["risk_off"])
        self.assertTrue(result["trend_spike"])


class TestSupertrendCalculations(unittest.TestCase):
    """Test cases for Supertrend indicator calculations"""
    
    def setUp(self):
        """Set up test data"""
        dates = pd.date_range('2024-01-01', periods=50, freq='1h')
        np.random.seed(42)
        
        # Generate price data
        close_prices = [100.0]
        for i in range(1, 50):
            change = np.random.normal(0, 1.0)
            close_prices.append(close_prices[-1] * (1 + change/100))
        
        self.test_data = pd.DataFrame({
            'Open': close_prices,
            'High': [p * (1 + np.random.uniform(0, 0.02)) for p in close_prices],
            'Low': [p * (1 - np.random.uniform(0, 0.02)) for p in close_prices],
            'Close': close_prices,
            'Volume': np.random.randint(1000, 5000, 50)
        }, index=dates)
    
    def test_supertrend_indicators(self):
        """Test Supertrend indicator calculation"""
        indicators = calculate_supertrend_indicators(self.test_data, st_period=10, st_multiplier=2.0)
        
        self.assertIsInstance(indicators, dict)
        self.assertIn('price', indicators)
        self.assertIn('st_line', indicators)
        self.assertIn('st_direction', indicators)
        self.assertIn('st_signal', indicators)
        self.assertIn('st_flipped', indicators)
        self.assertIn('adx', indicators)
        self.assertIn('hurst', indicators)
        self.assertIn('momentum', indicators)
        self.assertIn('ann_vol', indicators)
        self.assertIn('vol_regime', indicators)
        self.assertIn('trend_slope', indicators)
        self.assertIn('trend_slope_label', indicators)
        self.assertIn('regime_gate', indicators)
        
        # Check derived labels
        self.assertIn('trend_direction', indicators)
        self.assertIn('trend_strength', indicators)
        self.assertIn('market_regime', indicators)
        self.assertIn(indicators['regime_gate'], ['trend', 'mean_reversion', 'neutral'])

    def test_rule_based_signal_holds_in_non_mean_reversion_regime(self):
        indicators = {
            'strategy_type': 'mean_reversion',
            'price': 95.0,
            'rsi': 30.0,
            'kc_lower': 96.0,
            'kc_upper': 104.0,
            'ma_trend': 90.0,
            'hurst': 0.58,
            'adx': 28.0,
            'regime_gate': 'trend',
            'entry_quality': 0.8,
            'entry_quality_side': 'long',
            'entry_quality_min': 0.25,
            'trend_slope': 0.001,
            'ma_trend_filter': True,
            'rsi_oversold': 40,
            'rsi_overbought': 60,
        }
        result = _rule_based_signal(indicators)
        self.assertEqual(result['action'], 'hold')
        self.assertIn('regime', result['reason'])

    def test_rule_based_signal_requires_deeper_band_penetration(self):
        indicators = {
            'strategy_type': 'mean_reversion',
            'price': 95.8,
            'rsi': 30.0,
            'kc_lower': 96.0,
            'kc_upper': 104.0,
            'ma_trend': 90.0,
            'hurst': 0.40,
            'adx': 18.0,
            'regime_gate': 'mean_reversion',
            'entry_quality': 0.10,
            'entry_quality_side': 'long',
            'entry_quality_min': 0.25,
            'trend_slope': 0.0005,
            'ma_trend_filter': True,
            'rsi_oversold': 40,
            'rsi_overbought': 60,
            'atr': 1.0,
        }
        result = _rule_based_signal(indicators)
        self.assertEqual(result['action'], 'hold')
        self.assertIn('too shallow', result['reason'])
    
    def test_supertrend_direction_values(self):
        """Test that Supertrend direction values are correct"""
        indicators = calculate_supertrend_indicators(self.test_data, st_period=10, st_multiplier=2.0)
        
        # Direction should be +1 (bullish) or -1 (bearish)
        self.assertIn(indicators['st_direction'], [1, -1])
        self.assertIn(indicators['st_direction_prev'], [1, -1])
    
    def test_supertrend_signal_values(self):
        """Test that Supertrend signal values are correct"""
        indicators = calculate_supertrend_indicators(self.test_data, st_period=10, st_multiplier=2.0)
        
        # Signal should be 'long', 'short', or 'hold'
        self.assertIn(indicators['st_signal'], ['long', 'short', 'hold'])


class TestMarketData(unittest.TestCase):
    """Test cases for Hyperliquid candle retrieval."""
    
    @patch('strategy.resolve_asset_id', return_value=1)
    @patch('strategy.get_hl_candles_df')
    def test_get_market_data_success(self, mock_get_hl_candles_df, _mock_resolve_asset_id):
        """Test successful HL candle download."""
        dates = pd.date_range('2024-01-01', periods=3, freq='1h', tz='UTC')
        mock_df = pd.DataFrame({
            'ts': dates,
            'open': [100, 101, 102],
            'high': [101, 102, 103],
            'low': [99, 100, 101],
            'close': [100.5, 101.5, 102.5],
            'volume': [1000, 2000, 3000]
        })
        mock_get_hl_candles_df.return_value = mock_df

        result = get_market_data('BTC', '1h', '7d', hl_symbol='BTC')

        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 3)
        self.assertIn('Close', result.columns)
        mock_get_hl_candles_df.assert_called_once()

    @patch('strategy.resolve_asset_id', return_value=1)
    @patch('strategy.get_hl_candles_df')
    def test_get_market_data_empty(self, mock_get_hl_candles_df, _mock_resolve_asset_id):
        """Test data download with empty result."""
        mock_get_hl_candles_df.return_value = None

        result = get_market_data('BTC', '1h', '7d', hl_symbol='BTC')

        self.assertIsNone(result)

    @patch('strategy.resolve_asset_id', return_value=1)
    @patch('strategy.get_hl_candles_df')
    def test_get_market_data_exception(self, mock_get_hl_candles_df, _mock_resolve_asset_id):
        """Test data download with exception."""
        mock_get_hl_candles_df.side_effect = Exception("Network error")

        result = get_market_data('BTC', '1h', '7d', hl_symbol='BTC')

        self.assertIsNone(result)

    @patch('strategy.resolve_asset_id', return_value=1)
    @patch('strategy.get_hl_candles_df')
    def test_get_market_data_reuses_scan_cache(self, mock_get_hl_candles_df, _mock_resolve_asset_id):
        """Test per-scan cache reuse for repeated timeframe requests."""
        dates = pd.date_range('2024-01-01', periods=10, freq='1h', tz='UTC')
        mock_df = pd.DataFrame({
            'ts': dates,
            'open': range(10),
            'high': range(1, 11),
            'low': range(10),
            'close': range(10),
            'volume': [100] * 10,
        })
        mock_get_hl_candles_df.return_value = mock_df
        scan_cache = {}

        result_1 = get_market_data('BTC', '1h', 5, hl_symbol='BTC', scan_cache=scan_cache)
        result_2 = get_market_data('BTC', '1h', 3, hl_symbol='BTC', scan_cache=scan_cache)

        self.assertEqual(len(result_1), 5)
        self.assertEqual(len(result_2), 3)
        mock_get_hl_candles_df.assert_called_once()


class TestCoinIndicators(unittest.TestCase):
    """Test cases for coin-specific indicator calculations"""
    
    def setUp(self):
        """Set up test configuration"""
        self.coin_config = {
            'ticker': 'BTC',
            'hl_symbol': 'BTC',
            'interval': '1h',
            'period': '7d',
            'strategy_type': 'mean_reversion',
            'kc_scalar': 1.5,
            'ma_trend_filter': True,
            'rsi_oversold': 30,
            'rsi_overbought': 70
        }
    
    @patch('strategy.get_market_data')
    def test_get_indicators_for_coin_mean_reversion(self, mock_download):
        """Test getting indicators for mean-reversion strategy"""
        # Create mock data
        dates = pd.date_range('2024-01-01', periods=50, freq='1h')
        mock_df = pd.DataFrame({
            'Open': [100] * 50,
            'High': [101] * 50,
            'Low': [99] * 50,
            'Close': [100.5] * 50,
            'Volume': [1000] * 50
        }, index=dates)
        mock_download.return_value = mock_df
        
        indicators = get_indicators_for_coin('BTC', self.coin_config)
        
        self.assertIsInstance(indicators, dict)
        self.assertEqual(indicators['coin'], 'BTC')
        self.assertEqual(indicators['interval'], '1h')
        self.assertEqual(indicators['strategy_type'], 'mean_reversion')
        self.assertEqual(indicators['kc_scalar'], 1.5)
        self.assertEqual(indicators['rsi_oversold'], 30)
        self.assertEqual(indicators['rsi_overbought'], 70)
    
    @patch('strategy.get_market_data')
    def test_get_indicators_for_coin_supertrend(self, mock_download):
        """Test getting indicators for Supertrend strategy"""
        supertrend_config = {
            'ticker': 'BTC',
            'hl_symbol': 'BTC',
            'interval': '1h',
            'period': '7d',
            'strategy_type': 'supertrend',
            'st_period': 14,
            'st_multiplier': 2.0
        }
        
        # Create mock data
        dates = pd.date_range('2024-01-01', periods=50, freq='1h')
        mock_df = pd.DataFrame({
            'Open': [100] * 50,
            'High': [101] * 50,
            'Low': [99] * 50,
            'Close': [100.5] * 50,
            'Volume': [1000] * 50
        }, index=dates)
        mock_download.return_value = mock_df
        
        indicators = get_indicators_for_coin('BTC', supertrend_config)
        
        self.assertIsInstance(indicators, dict)
        self.assertEqual(indicators['coin'], 'BTC')
        self.assertEqual(indicators['interval'], '1h')
        self.assertEqual(indicators['strategy_type'], 'supertrend')
        self.assertIn('st_line', indicators)
        self.assertIn('st_direction', indicators)
        self.assertIn('st_signal', indicators)


class TestTrendBias(unittest.TestCase):
    """Test cases for trend bias calculation"""
    
    @patch('strategy.get_market_data')
    def test_get_trend_bias(self, mock_download):
        """Test getting daily trend bias"""
        # Create mock daily data
        dates = pd.date_range('2024-01-01', periods=60, freq='1D')
        mock_df = pd.DataFrame({
            'Open': [100] * 60,
            'High': [102] * 60,
            'Low': [98] * 60,
            'Close': [101] * 60,
            'Volume': [1000] * 60
        }, index=dates)
        mock_download.return_value = mock_df
        
        coin_config = {
            'ticker': 'BTC',
            'hl_symbol': 'BTC',
            'interval': '1h',
            'period': '7d'
        }
        
        bias = get_trend_bias('BTC', coin_config)
        
        self.assertIsInstance(bias, dict)
        self.assertEqual(bias['coin'], 'BTC')
        self.assertIn('trend', bias)
        self.assertIn('rsi', bias)
        self.assertIn('ma_alignment', bias)
        self.assertIn('hurst', bias)
        self.assertIn('market_regime', bias)
        self.assertIn('adx', bias)
    
    @patch('strategy.get_market_data')
    def test_get_trend_bias_insufficient_data(self, mock_download):
        """Test trend bias with insufficient data"""
        mock_download.return_value = None
        
        coin_config = {
            'ticker': 'BTC',
            'hl_symbol': 'BTC',
            'interval': '1h',
            'period': '7d'
        }
        
        bias = get_trend_bias('BTC', coin_config)
        
        self.assertIsInstance(bias, dict)
        self.assertEqual(bias['trend'], 'neutral')
        self.assertEqual(bias['rsi'], 50.0)


class TestHelperFunctions(unittest.TestCase):
    """Test cases for helper functions"""
    
    def test_safe_function(self):
        """Test the _safe helper function"""
        from strategy import _safe
        
        # Test normal values
        self.assertEqual(_safe(5.0), 5.0)
        self.assertEqual(_safe(0), 0)
        
        # Test NaN values
        self.assertEqual(_safe(float('nan')), 0.0)
        self.assertEqual(_safe(float('nan'), 1.0), 1.0)
        
        # Test infinity values
        self.assertEqual(_safe(float('inf')), 0.0)
        self.assertEqual(_safe(float('-inf')), 0.0)
        
        # Test invalid types
        self.assertEqual(_safe("invalid"), 0.0)
        self.assertEqual(_safe(None), 0.0)
    
    def test_round_price_function(self):
        """Test the _round_price helper function"""
        from strategy import _round_price
        
        # Test normal prices
        self.assertEqual(_round_price(100.123456), 100.1235)
        self.assertEqual(_round_price(1.234567), 1.2346)
        
        # Test sub-cent prices
        self.assertEqual(_round_price(0.001234), 0.001234)
        self.assertEqual(_round_price(0.000123), 0.000123)
        self.assertEqual(_round_price(0.000012), 0.000012)


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)
