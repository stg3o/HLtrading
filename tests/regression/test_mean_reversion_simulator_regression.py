#!/usr/bin/env python3
"""Regression tests for shared mean-reversion simulator extraction."""
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


class TestMeanReversionSimulatorRegression(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2024-01-01", periods=12, freq="1h")
        self.df = pd.DataFrame(
            {
                "Open": [100.0] * 12,
                "High": [100.5, 100.5, 100.5, 100.5, 100.5, 100.5, 102.0, 102.0, 102.0, 102.0, 102.0, 102.0],
                "Low": [99.5] * 12,
                "Close": [100.0] * 12,
            },
            index=dates,
        )
        self.params = {
            "stop_loss_pct": 0.01,
            "take_profit_pct": 0.02,
            "min_rr_ratio": 1.2,
            "max_bars_in_trade": 10,
        }
        self.expected_pnl = round((102.0 - 100.0) * ((backtester.PAPER_CAPITAL * backtester.RISK_PER_TRADE / 0.01) / 100.0), 4)
        self.expected_capital = backtester.PAPER_CAPITAL + self.expected_pnl
        self.expected_equity = [
            float(backtester.PAPER_CAPITAL),
            float(backtester.PAPER_CAPITAL),
            float(backtester.PAPER_CAPITAL),
            float(self.expected_capital),
            float(self.expected_capital),
            float(self.expected_capital),
            float(self.expected_capital),
            float(self.expected_capital),
        ]
        self.expected_trade = {
            "side": "long",
            "entry": 100.0,
            "exit": 102.0,
            "pnl": self.expected_pnl,
            "pnl_pct": 2.0,
            "reason": "tp_midline",
            "bars": 1,
        }

    def test_backtester_mean_reversion_wrapper_preserves_trade_list_and_equity_curve(self):
        with patch.object(backtester, "_WARMUP", 5):
            with patch.object(backtester, "_signal_for_window", side_effect=[("hold", "none", 0.0, 0.0)] + [("long", "signal", 102.0, 0.0)] + [("hold", "none", 0.0, 0.0)] * 10):
                with patch.object(backtester, "_calc_kc_mid", return_value=102.0):
                    trades, final_capital, equity_curve = backtester._run_mean_reversion_sim(self.df, self.params)

        self.assertEqual(trades, [self.expected_trade])
        self.assertEqual(final_capital, self.expected_capital)
        self.assertEqual(equity_curve, self.expected_equity)

    def test_enhanced_mean_reversion_wrapper_preserves_trade_list_and_timestamps(self):
        with patch.object(backtester_enhanced, "_WARMUP", 5):
            with patch.object(backtester_enhanced, "_signal_for_window", side_effect=[("hold", "none", 0.0, 0.0)] + [("long", "signal", 102.0, 0.0)] + [("hold", "none", 0.0, 0.0)] * 10):
                with patch.object(backtester_enhanced, "_calc_kc_mid", return_value=102.0):
                    trades, final_capital, equity_curve = backtester_enhanced._run_mean_reversion_sim(self.df, self.params)

        expected_trade = dict(self.expected_trade)
        expected_trade["timestamp"] = self.df.index[7].isoformat()
        self.assertEqual(trades, [expected_trade])
        self.assertEqual(final_capital, self.expected_capital)
        self.assertEqual(equity_curve, self.expected_equity)


if __name__ == "__main__":
    unittest.main()
