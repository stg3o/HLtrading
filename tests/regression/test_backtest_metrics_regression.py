#!/usr/bin/env python3
"""Regression tests for shared backtest metrics extraction."""
import sys
import types
import unittest

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


class TestBacktestMetricsRegression(unittest.TestCase):
    def setUp(self):
        self.trades = [
            {"pnl": 10.0, "pnl_pct": 1.0, "reason": "tp_midline", "bars": 2},
            {"pnl": -5.0, "pnl_pct": -0.5, "reason": "stop_loss", "bars": 1},
            {"pnl": 8.0, "pnl_pct": 0.8, "reason": "tp_fixed", "bars": 3},
        ]
        self.equity_curve = [672.0, 682.0, 677.0, 685.0]

    def test_base_stats_shape_and_values_are_preserved(self):
        result = backtester._compute_stats("SOL", self.trades, 685.0, self.equity_curve, "60d", 60)

        self.assertEqual(result["coin"], "SOL")
        self.assertEqual(result["total_trades"], 3)
        self.assertEqual(result["win_rate"], 66.7)
        self.assertEqual(result["total_pnl"], 13.0)
        self.assertEqual(result["pct_return"], round(13.0 / backtester.PAPER_CAPITAL * 100, 2))
        self.assertEqual(result["exit_breakdown"], {"tp_midline": 1, "stop_loss": 1, "tp_fixed": 1})
        self.assertIn("sortino_ratio", result)

    def test_enhanced_stats_preserve_base_fields_and_enhanced_additions(self):
        result = backtester_enhanced._compute_enhanced_stats(
            "SOL", self.trades, 685.0, self.equity_curve, "60d", 60
        )

        self.assertEqual(result["coin"], "SOL")
        self.assertEqual(result["total_trades"], 3)
        self.assertEqual(result["exit_breakdown"], {"tp_midline": 1, "stop_loss": 1, "tp_fixed": 1})
        self.assertIn("max_drawdown_duration", result)
        self.assertIn("calmar_ratio", result)
        self.assertIn("ulcer_index", result)
        self.assertTrue(result["enhanced_metrics"])


if __name__ == "__main__":
    unittest.main()
