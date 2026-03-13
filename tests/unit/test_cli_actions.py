#!/usr/bin/env python3
"""Focused tests for extracted CLI action helpers."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from interfaces.cli_actions import open_dashboard_action, render_performance_report, render_view_positions


class TestCliActions(unittest.TestCase):
    def setUp(self):
        self.fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="", RED="", WHITE="")
        self.style = types.SimpleNamespace(RESET_ALL="")

    def test_render_performance_report_preserves_visible_sections(self):
        printer = Mock()
        render_performance_report(
            performance_report_fn=lambda: {
                "total_trades": 2,
                "win_rate": 50.0,
                "total_pnl": 10.0,
                "total_fees": 0.5,
                "avg_win": 20.0,
                "avg_loss": -10.0,
                "profit_factor": 2.0,
                "max_drawdown": 3.0,
                "max_consec_losses": 1,
                "best_trade": 20.0,
                "worst_trade": -10.0,
                "sharpe_ratio": 1.2,
                "sortino_ratio": 1.8,
                "brier_score": 0.14,
                "calibrated_trades": 7,
            },
            load_trades=lambda: [{"timestamp": "2024-01-01 10:00:00", "coin": "SOL", "side": "long", "pnl": "10.0", "reason": "tp"}],
            printer=printer,
            fore=self.fore,
            style=self.style,
        )
        output = "\n".join(call.args[0] for call in printer.call_args_list)
        self.assertIn("Performance Report", output)
        self.assertIn("Sharpe ratio:", output)
        self.assertIn("Brier score:", output)
        self.assertIn("Last 1 trades:", output)

    def test_render_view_positions_shows_wallet_and_positions(self):
        printer = Mock()
        risk_manager = Mock()
        render_view_positions(
            risk_manager=risk_manager,
            print_positions=Mock(),
            get_hl_account_info=lambda: {
                "account_value": 1000.0,
                "spot_usdc": 100.0,
                "perps_equity": 900.0,
                "margin_used": 50.0,
                "withdrawable": 950.0,
                "positions": [{"position": {"coin": "ETH", "szi": "1", "unrealizedPnl": "12.5", "entryPx": "2000"}}],
            },
            testnet=True,
            printer=printer,
            fore=self.fore,
            style=self.style,
        )
        output = "\n".join(call.args[0] for call in printer.call_args_list)
        self.assertIn("Hyperliquid Wallet [TESTNET]", output)
        self.assertIn("Open on-chain  :", output)
        self.assertIn("ETH", output)

    def test_open_dashboard_prefers_live_web_dashboard_then_falls_back(self):
        printer = Mock()
        browser_open = Mock()
        with patch("hltrading.interfaces.cli_actions._url_available", return_value=True), \
             tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "main.py"
            module_file.write_text("", encoding="utf-8")
            open_dashboard_action(
                module_file=str(module_file),
                browser_open=browser_open,
                printer=printer,
                fore=self.fore,
            )

            browser_open.assert_called_once_with("http://localhost:5000")

        printer = Mock()
        browser_open = Mock()
        with patch("hltrading.interfaces.cli_actions._url_available", return_value=False), \
             tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "main.py"
            module_file.write_text("", encoding="utf-8")
            enhanced = Path(tmpdir) / "enhanced_dashboard.html"
            enhanced.write_text("<html></html>", encoding="utf-8")

            open_dashboard_action(
                module_file=str(module_file),
                browser_open=browser_open,
                printer=printer,
                fore=self.fore,
            )

            browser_open.assert_called_once()
            self.assertTrue(browser_open.call_args.args[0].startswith("file://"))

    def test_open_dashboard_reports_clear_error_when_live_and_static_unavailable(self):
        printer = Mock()
        browser_open = Mock()

        with patch("hltrading.interfaces.cli_actions._url_available", return_value=False), \
             tempfile.TemporaryDirectory() as tmpdir:
            module_file = Path(tmpdir) / "main.py"
            module_file.write_text("", encoding="utf-8")

            open_dashboard_action(
                module_file=str(module_file),
                browser_open=browser_open,
                printer=printer,
                fore=self.fore,
            )

        output = "\n".join(call.args[0] for call in printer.call_args_list)
        browser_open.assert_not_called()
        self.assertIn("No dashboard could be opened.", output)


if __name__ == "__main__":
    unittest.main()
