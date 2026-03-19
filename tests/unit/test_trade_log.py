#!/usr/bin/env python3
"""Focused unit tests for trade-log analytics helpers."""
import sys
import types
import unittest

if "dotenv" not in sys.modules:
    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *args, **kwargs: None
    sys.modules["dotenv"] = dotenv_module

from hltrading.execution.trade_log import (
    analyze_pnl_by_coin,
    analyze_pnl_by_entry_context,
    analyze_pnl_by_hour,
    analyze_pnl_by_strategy_type,
    analyze_pnl_by_weekday,
    performance_breakdown_by_coin_and_context,
)


class TestTradeLogAnalytics(unittest.TestCase):
    def test_core_analytics_helpers_group_deterministically(self):
        trades = [
            {"timestamp": "2026-03-09 09:10:00", "coin": "SOL", "pnl": "10", "cascade_assisted": "True"},
            {"timestamp": "2026-03-09 10:10:00", "coin": "SOL_ST", "pnl": "-5", "cascade_assisted": "False"},
            {"timestamp": "2026-03-10 09:10:00", "coin": "SOL", "pnl": "4", "cascade_assisted": "True"},
        ]

        self.assertEqual(
            analyze_pnl_by_coin(trades),
            [
                {"coin": "SOL", "trade_count": 2, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 7.0, "total_pnl": 14.0},
                {"coin": "SOL_ST", "trade_count": 1, "win_rate": 0.0, "profit_factor": 0.0, "avg_pnl": -5.0, "total_pnl": -5.0},
            ],
        )
        self.assertEqual(
            analyze_pnl_by_strategy_type(trades),
            [
                {"strategy_type": "mean_reversion", "trade_count": 2, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 7.0, "total_pnl": 14.0},
                {"strategy_type": "supertrend", "trade_count": 1, "win_rate": 0.0, "profit_factor": 0.0, "avg_pnl": -5.0, "total_pnl": -5.0},
            ],
        )
        self.assertEqual(
            analyze_pnl_by_entry_context(trades),
            [
                {"entry_context": "cascade", "trade_count": 2, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 7.0, "total_pnl": 14.0},
                {"entry_context": "normal", "trade_count": 1, "win_rate": 0.0, "profit_factor": 0.0, "avg_pnl": -5.0, "total_pnl": -5.0},
            ],
        )
        self.assertEqual(
            analyze_pnl_by_hour(trades),
            [
                {"hour": 9, "trade_count": 2, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 7.0, "total_pnl": 14.0},
                {"hour": 10, "trade_count": 1, "win_rate": 0.0, "profit_factor": 0.0, "avg_pnl": -5.0, "total_pnl": -5.0},
            ],
        )
        self.assertEqual(
            analyze_pnl_by_weekday(trades),
            [
                {"weekday": "Monday", "trade_count": 2, "win_rate": 50.0, "profit_factor": 2.0, "avg_pnl": 2.5, "total_pnl": 5.0},
                {"weekday": "Tuesday", "trade_count": 1, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 4.0, "total_pnl": 4.0},
            ],
        )

    def test_performance_breakdown_groups_by_coin_and_cascade_context(self):
        trades = [
            {"coin": "SOL", "pnl": "10", "cascade_assisted": "True"},
            {"coin": "SOL", "pnl": "-5", "cascade_assisted": "False"},
            {"coin": "SOL", "pnl": "4", "cascade_assisted": "True"},
            {"coin": "BTC", "pnl": "3", "cascade_assisted": "False"},
        ]

        result = performance_breakdown_by_coin_and_context(trades)

        self.assertEqual(
            result,
            [
                {"coin": "BTC", "entry_context": "normal", "trade_count": 1, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 3.0},
                {"coin": "SOL", "entry_context": "cascade", "trade_count": 2, "win_rate": 100.0, "profit_factor": "∞", "avg_pnl": 7.0},
                {"coin": "SOL", "entry_context": "normal", "trade_count": 1, "win_rate": 0.0, "profit_factor": 0.0, "avg_pnl": -5.0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
