#!/usr/bin/env python3
"""Regression tests for shared volatility helper extraction."""
import unittest

import numpy as np
import pandas as pd

from enhanced_volatility_position_sizing import EnhancedVolatilityAnalyzer
from volatility_position_sizing import VolatilityAnalyzer


class TestVolatilityHelpers(unittest.TestCase):
    def setUp(self):
        np.random.seed(7)
        dates = pd.date_range("2024-01-01", periods=160, freq="1D")
        close = pd.Series(np.linspace(100, 130, 160) + np.sin(np.arange(160)) * 2, index=dates)
        self.data = pd.DataFrame({
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.linspace(1000, 5000, 160),
        }, index=dates)

    def test_base_analyzer_helper_outputs_on_fixed_frame(self):
        analyzer = VolatilityAnalyzer()
        atr_values = {"atr_14": 1.4, "atr_21": 1.2, "atr_50": 1.0}

        hist_vol = analyzer._calculate_historical_volatility(self.data)
        trend = analyzer._analyze_volatility_trend(atr_values)
        clustering = analyzer._analyze_volatility_clustering(self.data)
        confidence = analyzer._calculate_volatility_confidence(atr_values, hist_vol)

        self.assertAlmostEqual(hist_vol, 0.1891984823, places=8)
        self.assertEqual(trend, "increasing")
        self.assertAlmostEqual(clustering, -0.3165357304, places=8)
        self.assertAlmostEqual(confidence, 0.8639172365, places=8)

    def test_enhanced_analyzer_helper_outputs_on_fixed_frame(self):
        analyzer = EnhancedVolatilityAnalyzer()
        atr_values = {"atr_7": 1.6, "atr_14": 1.4, "atr_21": 1.2, "atr_50": 1.0, "atr_100": 0.8}

        hist_vol = analyzer._calculate_historical_volatility(self.data)
        clustering = analyzer._analyze_volatility_clustering(self.data)
        trend = analyzer._analyze_volatility_trend(atr_values)
        confidence = analyzer._calculate_volatility_confidence(atr_values, hist_vol, clustering)

        self.assertAlmostEqual(hist_vol, 0.1750107552, places=8)
        self.assertAlmostEqual(clustering, -0.3165357304, places=8)
        self.assertEqual(trend, "strongly_increasing")
        self.assertAlmostEqual(confidence, 0.6519643516, places=8)


if __name__ == "__main__":
    unittest.main()
