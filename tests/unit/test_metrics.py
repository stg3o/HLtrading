#!/usr/bin/env python3
"""
Regression tests for shared reporting metrics.
"""
import json
import unittest


class TestSharedMetrics(unittest.TestCase):
    def test_build_equity_series_respects_starting_capital_and_label_width(self):
        from shared.metrics import build_equity_series

        trades = [
            {"timestamp": "2026-03-12 10:11", "pnl": "5.257"},
            {"timestamp": "2026-03-13 14:15", "pnl": -2},
        ]

        daily = build_equity_series(trades, starting_capital=100.0, timestamp_chars=10)
        intraday = build_equity_series(trades, starting_capital=100.0, timestamp_chars=16)

        self.assertEqual(daily, {
            "labels": ["2026-03-12", "2026-03-13"],
            "values": [105.26, 103.26],
        })
        self.assertEqual(intraday, {
            "labels": ["2026-03-12 10:11", "2026-03-13 14:15"],
            "values": [105.26, 103.26],
        })

    def test_aggregate_coin_pnl_preserves_order_and_rounding(self):
        from shared.metrics import aggregate_coin_pnl

        trades = [
            {"coin": "ETH", "pnl": "1.234"},
            {"coin": "BTC", "pnl": -2},
            {"coin": "ETH", "pnl": "0.331"},
        ]

        result = aggregate_coin_pnl(trades)

        self.assertEqual(result, {
            "labels": ["ETH", "BTC"],
            "values": [1.56, -2.0],
        })

    def test_dashboard_style_json_serialization_stays_compatible(self):
        from shared.metrics import aggregate_coin_pnl, build_equity_series

        trades = [{"timestamp": "2026-03-12 10:11", "coin": "SOL", "pnl": 3}]

        equity_json = json.dumps(build_equity_series(trades, starting_capital=50.0, timestamp_chars=10))
        coin_json = json.dumps(aggregate_coin_pnl(trades))

        self.assertEqual(json.loads(equity_json), {"labels": ["2026-03-12"], "values": [53.0]})
        self.assertEqual(json.loads(coin_json), {"labels": ["SOL"], "values": [3.0]})
