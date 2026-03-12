#!/usr/bin/env python3
"""
Focused render tests for dashboard HTML generation.
"""
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


class TestDashboardRender(unittest.TestCase):
    def test_run_writes_dashboard_html_with_expected_sections_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            original_config = sys.modules.get("config")
            original_dashboard = sys.modules.get("dashboard")
            self.addCleanup(
                lambda: sys.modules.__setitem__("config", original_config)
                if original_config is not None
                else sys.modules.pop("config", None)
            )
            self.addCleanup(
                lambda: sys.modules.__setitem__("dashboard", original_dashboard)
                if original_dashboard is not None
                else sys.modules.pop("dashboard", None)
            )

            sys.modules["config"] = _stub_module("config", BASE_DIR=base_dir, PAPER_CAPITAL=100.0)
            sys.modules.pop("dashboard", None)

            dashboard = importlib.import_module("dashboard")

            state = {
                "capital": 110.5,
                "equity_peak": 112.0,
                "positions": {
                    "ETH": {
                        "entry_price": 100.0,
                        "stop_loss": 95.0,
                        "take_profit": 110.0,
                        "size_units": 1.0,
                        "side": "long",
                        "opened_at": "2026-03-12 10:00",
                    }
                },
                "emergency_stop": False,
                "trading_halted": False,
            }
            trades = [
                {
                    "timestamp": "2026-03-12 10:00",
                    "coin": "ETH",
                    "side": "long",
                    "entry_price": 100.0,
                    "exit_price": 105.0,
                    "pnl": 10.5,
                    "pnl_pct": 10.5,
                    "duration_min": 30,
                    "reason": "take_profit",
                }
            ]

            with patch.object(dashboard, "_load_state", return_value=state), \
                 patch.object(dashboard, "_load_trades", return_value=trades), \
                 patch.object(dashboard, "_get_live_prices", return_value={"ETH": 106.0}), \
                 patch.object(dashboard, "_get_live_fees", return_value={}):
                out = dashboard.run()

            html = out.read_text(encoding="utf-8")

        self.assertEqual(out, base_dir / "dashboard.html")
        self.assertIn("ArbyBot Dashboard", html)
        self.assertIn("Per-Coin Performance", html)
        self.assertIn("Open Positions", html)
        self.assertIn('const eq = {"labels": ["2026-03-12"], "values": [110.5]};', html)
        self.assertIn('const co = {"labels": ["ETH"], "values": [10.5]};', html)
        self.assertIn("$110.50", html)
