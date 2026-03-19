#!/usr/bin/env python3
"""
Focused tests for startup reconciliation behavior.
"""
import types
import unittest
from unittest.mock import Mock

from core.startup import sync_positions_with_hl


class TestStartupReconciliation(unittest.TestCase):
    def test_removes_local_positions_missing_on_hl_and_persists_state(self):
        risk = types.SimpleNamespace(state={"positions": {"SOL": {"side": "long"}}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="")

        result = sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"SOL": {"hl_symbol": "SOL"}},
            get_hl_positions=lambda: [],
            save_state=save_state,
            auto_import_positions=True,
            default_stop_loss_pct=0.005,
            default_take_profit_pct=0.01,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(result)
        self.assertEqual(risk.state["positions"], {})
        save_state.assert_called_once_with(risk.state)
        printer.assert_called_once()
        self.assertIn("SOL was closed on HL", printer.call_args.args[0])

    def test_imports_untracked_hl_positions_when_auto_import_enabled(self):
        risk = types.SimpleNamespace(state={"positions": {}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="")

        result = sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"ETH": {"hl_symbol": "ETH", "stop_loss_pct": 0.008, "take_profit_pct": 0.02}},
            get_hl_positions=lambda: [{"position": {"coin": "ETH", "szi": "1", "entryPx": "2000"}}],
            save_state=save_state,
            auto_import_positions=True,
            default_stop_loss_pct=0.005,
            default_take_profit_pct=0.01,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(result)
        self.assertIn("ETH", risk.state["positions"])
        self.assertEqual(risk.state["positions"]["ETH"]["side"], "long")
        self.assertEqual(risk.state["positions"]["ETH"]["entry_price"], 2000.0)
        self.assertEqual(risk.state["positions"]["ETH"]["stop_loss"], 1984.0)
        self.assertEqual(risk.state["positions"]["ETH"]["take_profit"], 2040.0)
        save_state.assert_called_once_with(risk.state)
        self.assertIn("Imported ETH into local state as ETH", printer.call_args.args[0])

    def test_blocks_startup_on_untracked_hl_positions_when_auto_import_disabled(self):
        risk = types.SimpleNamespace(state={"positions": {}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="", RED="")

        result = sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"ETH": {"hl_symbol": "ETH"}},
            get_hl_positions=lambda: [{"position": {"coin": "ETH", "szi": "1", "entryPx": "2000"}}],
            save_state=save_state,
            auto_import_positions=False,
            default_stop_loss_pct=0.005,
            default_take_profit_pct=0.01,
            printer=printer,
            fore=fore,
        )

        self.assertFalse(result)
        self.assertEqual(risk.state["positions"], {})
        save_state.assert_not_called()
        self.assertIn("BLOCKED: ETH is open on HL but not tracked locally", printer.call_args.args[0])

    def test_reports_match_when_local_and_hl_positions_align(self):
        risk = types.SimpleNamespace(state={"positions": {"ETH": {"side": "long"}}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="")

        result = sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"ETH": {"hl_symbol": "ETH"}},
            get_hl_positions=lambda: [{"position": {"coin": "ETH", "szi": "1"}}],
            save_state=save_state,
            auto_import_positions=True,
            default_stop_loss_pct=0.005,
            default_take_profit_pct=0.01,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(result)
        save_state.assert_not_called()
        printer.assert_called_once_with("  [sync] Local state matches HL positions ✓")

    def test_imports_with_defaults_when_coin_mapping_has_no_risk_config(self):
        risk = types.SimpleNamespace(state={"positions": {}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="", RED="")

        result = sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"ETH": {"hl_symbol": "ETH"}},
            get_hl_positions=lambda: [{"position": {"coin": "ETH", "szi": "1", "entryPx": "2000"}}],
            save_state=save_state,
            auto_import_positions=True,
            default_stop_loss_pct=0.005,
            default_take_profit_pct=0.01,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(result)
        self.assertIn("ETH", risk.state["positions"])
        self.assertEqual(risk.state["positions"]["ETH"]["stop_loss"], 1990.0)
        self.assertEqual(risk.state["positions"]["ETH"]["take_profit"], 2020.0)
        save_state.assert_called_once_with(risk.state)
        self.assertTrue(any("Applying defaults" in call.args[0] for call in printer.call_args_list))

    def test_imports_using_reverse_hl_symbol_mapping(self):
        risk = types.SimpleNamespace(state={"positions": {}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="", RED="")

        result = sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"SOL_ST": {"hl_symbol": "SOL", "stop_loss_pct": 0.008, "take_profit_pct": 0.05}},
            get_hl_positions=lambda: [{"position": {"coin": "SOL", "szi": "-2", "entryPx": "150"}}],
            save_state=save_state,
            auto_import_positions=True,
            default_stop_loss_pct=0.005,
            default_take_profit_pct=0.01,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(result)
        self.assertIn("SOL_ST", risk.state["positions"])
        self.assertEqual(risk.state["positions"]["SOL_ST"]["side"], "short")
        self.assertEqual(risk.state["positions"]["SOL_ST"]["stop_loss"], 151.2)
        self.assertEqual(risk.state["positions"]["SOL_ST"]["take_profit"], 142.5)
        save_state.assert_called_once_with(risk.state)
