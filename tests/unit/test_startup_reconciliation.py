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

        sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"SOL": {"hl_symbol": "SOL"}},
            get_hl_positions=lambda: [],
            save_state=save_state,
            printer=printer,
            fore=fore,
        )

        self.assertEqual(risk.state["positions"], {})
        save_state.assert_called_once_with(risk.state)
        printer.assert_called_once()
        self.assertIn("SOL was closed on HL", printer.call_args.args[0])

    def test_warns_on_untracked_hl_positions_without_mutating_local_state(self):
        risk = types.SimpleNamespace(state={"positions": {}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="")

        sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={},
            get_hl_positions=lambda: [{"position": {"coin": "ETH", "szi": "1"}}],
            save_state=save_state,
            printer=printer,
            fore=fore,
        )

        self.assertEqual(risk.state["positions"], {})
        save_state.assert_not_called()
        self.assertIn("WARNING: ETH is open on HL but not tracked locally", printer.call_args.args[0])

    def test_reports_match_when_local_and_hl_positions_align(self):
        risk = types.SimpleNamespace(state={"positions": {"ETH": {"side": "long"}}})
        save_state = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(YELLOW="", GREEN="")

        sync_positions_with_hl(
            hl_enabled=True,
            risk=risk,
            coins={"ETH": {"hl_symbol": "ETH"}},
            get_hl_positions=lambda: [{"position": {"coin": "ETH", "szi": "1"}}],
            save_state=save_state,
            printer=printer,
            fore=fore,
        )

        save_state.assert_not_called()
        printer.assert_called_once_with("  [sync] Local state matches HL positions ✓")
