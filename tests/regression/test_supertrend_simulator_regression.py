#!/usr/bin/env python3
"""Regression tests for the shared Supertrend simulator extraction."""
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

import backtester

if "scipy" not in sys.modules:
    scipy_module = types.ModuleType("scipy")
    scipy_module.stats = types.SimpleNamespace()
    sys.modules["scipy"] = scipy_module

if "sklearn" not in sys.modules:
    sklearn_module = types.ModuleType("sklearn")
    sklearn_model_selection = types.ModuleType("sklearn.model_selection")
    sklearn_model_selection.TimeSeriesSplit = object
    sklearn_metrics = types.ModuleType("sklearn.metrics")
    sklearn_metrics.mean_squared_error = lambda *args, **kwargs: 0.0
    sklearn_module.model_selection = sklearn_model_selection
    sklearn_module.metrics = sklearn_metrics
    sys.modules["sklearn"] = sklearn_module
    sys.modules["sklearn.model_selection"] = sklearn_model_selection
    sys.modules["sklearn.metrics"] = sklearn_metrics

import backtester_enhanced


class TestSupertrendSimulatorRegression(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=11, freq="1h")
        self.df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 95.0, 90.0, 90.0],
                "High": [101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 96.0, 91.0, 91.0],
                "Low": [99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 99.0, 94.0, 89.0, 89.0],
                "Close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 95.0, 90.0, 90.0],
            },
            index=dates,
        )
        self.params = {"st_period": 2, "st_multiplier": 3.0, "stop_loss_pct": 0.1, "max_bars_in_trade": 10}
        self.direction = [1, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1]
        self.expected_pnl = round(
            (100.0 - 90.0) * ((backtester.PAPER_CAPITAL * backtester.RISK_PER_TRADE / 0.1) / 100.0),
            4,
        )
        self.expected_final_capital = backtester.PAPER_CAPITAL + self.expected_pnl
        self.expected_equity = [
            float(backtester.PAPER_CAPITAL),
            float(backtester.PAPER_CAPITAL),
            float(backtester.PAPER_CAPITAL),
            float(self.expected_final_capital),
            float(self.expected_final_capital),
        ]
        self.expected_base_trade = {
            "side": "short",
            "entry": 100.0,
            "exit": 90.0,
            "pnl": self.expected_pnl,
            "pnl_pct": 10.0,
            "reason": "st_flip",
            "bars": 2,
        }

    def test_backtester_supertrend_wrapper_preserves_trade_list_and_equity_curve(self):
        with patch.object(backtester, "_supertrend_arrays", return_value=(self.direction, None)):
            trades, final_capital, equity_curve = backtester._run_supertrend_sim(self.df, self.params)

        self.assertEqual(trades, [self.expected_base_trade])
        self.assertEqual(final_capital, self.expected_final_capital)
        self.assertEqual(equity_curve, self.expected_equity)

    def test_enhanced_supertrend_wrapper_preserves_trade_list_and_timestamps(self):
        with patch.object(backtester_enhanced, "_supertrend_arrays", return_value=(self.direction, None)):
            trades, final_capital, equity_curve = backtester_enhanced._run_supertrend_sim(self.df, self.params)

        expected_trade = dict(self.expected_base_trade)
        expected_trade["timestamp"] = self.df.index[9].isoformat()

        self.assertEqual(trades, [expected_trade])
        self.assertEqual(final_capital, self.expected_final_capital)
        self.assertEqual(equity_curve, self.expected_equity)


if __name__ == "__main__":
    unittest.main()
