#!/usr/bin/env python3
"""Deterministic tests for research validation helpers."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from research.validation import (
    RobustnessTester,
    StatisticalSignificanceTester,
    WalkForwardValidator,
    calculate_overall_score,
)


class TestResearchValidation(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(
            {"Close": np.arange(48, dtype=float)},
            index=pd.date_range("2024-01-01", periods=48, freq="1D"),
        )
        self.coin_cfg = {"ticker": "TEST", "interval": "1d", "strategy_type": "supertrend"}

    def test_walk_forward_aggregates_results_with_fixed_data(self):
        def simulate_backtest(df, coin_cfg, params):
            trade_count = len(df)
            trades = [{"pnl": 1.0, "pnl_pct": 1.0, "reason": "x", "bars": 1}] * max(1, trade_count // 5)
            return trades, 1100.0 + trade_count, [1000.0, 1100.0 + trade_count]

        def compute_metrics(df, trades, final_capital, equity_curve, label):
            return {
                "pct_return": float(len(df)),
                "sharpe_ratio": float(len(trades)),
                "max_drawdown": 1.0,
            }

        validator = WalkForwardValidator(
            "TEST",
            self.coin_cfg,
            simulate_backtest,
            compute_metrics,
            total_bars=24,
            lookback_bars=12,
            test_bars=12,
        )

        with patch.object(validator, "_fetch_extended_data", return_value=self.df.copy()):
            result = validator.run_walk_forward(silent=True)

        self.assertEqual(result["iterations"], 2)
        self.assertIn("results", result)
        self.assertIn("is_oos_correlation", result)

    def test_robustness_tester_returns_expected_shape(self):
        tester = RobustnessTester(
            "TEST",
            self.coin_cfg,
            simulate_backtest=lambda df, coin_cfg, params: ([{"pnl": 1.0, "pnl_pct": 1.0, "reason": "x", "bars": 1}] * 11, 1100.0, [1000.0, 1100.0]),
            compute_metrics=lambda df, trades, final_capital, equity_curve, label: {
                "total_trades": len(trades),
                "pct_return": 5.0,
                "sharpe_ratio": 1.2,
                "max_drawdown": 2.0,
                "win_rate": 60.0,
            },
        )

        with patch("research.validation.yf.download", return_value=self.df.copy()):
            with patch("research.validation.np.random.uniform", side_effect=lambda a, b: (a + b) / 2):
                result = tester.run_robustness_test({}, num_scenarios=2)

        self.assertEqual(result["scenarios_tested"], 2)
        self.assertIn("robustness_score", result)
        self.assertIn("return_stats", result)

    def test_significance_tester_returns_expected_fields(self):
        tester = StatisticalSignificanceTester(
            "TEST",
            self.coin_cfg,
            simulate_backtest=lambda df, coin_cfg, params: ([{"pnl": 1.0, "pnl_pct": 1.0, "reason": "x", "bars": 1}] * 11, 1100.0, [1000.0, 1100.0]),
            compute_metrics=lambda df, trades, final_capital, equity_curve, label: {
                "pct_return": 5.0 if label == "baseline" else 4.0,
            },
        )

        with patch("research.validation.yf.download", return_value=self.df.copy()):
            with patch("research.validation.np.random.shuffle", side_effect=lambda blocks: None):
                result = tester.run_significance_test({}, num_bootstraps=2)

        self.assertEqual(result["bootstrap_samples"], 2)
        self.assertIn("p_value", result)
        self.assertIn("confidence_interval_95", result)

    def test_overall_score_shape_is_preserved(self):
        score = calculate_overall_score(
            {"total_trades": 12, "pct_return": 5.0, "sharpe_ratio": 1.2, "max_drawdown": 2.0},
            {"is_oos_correlation": 0.5, "performance_decay": 0.8, "overfitting_score": 20.0},
            {"robustness_score": 70.0},
            {"significant_95": True, "p_value": 0.01},
        )
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
