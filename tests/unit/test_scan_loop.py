#!/usr/bin/env python3
"""Focused regression tests for scan-loop orchestration."""
import types
import unittest
from unittest.mock import Mock

from core.scan_loop import run_bot_scan_loop


class _OneShotEvent:
    def __init__(self):
        self._set = True
        self.wait_calls = []

    def is_set(self):
        return self._set

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        self._set = False


class TestScanLoop(unittest.TestCase):
    def _base_kwargs(self):
        event = _OneShotEvent()
        risk = Mock()
        risk.state = {"positions": {}}
        risk.is_halted.return_value = (False, "")
        risk.can_open_position.return_value = (False, "blocked")
        return {
            "apply_best_configs": Mock(),
            "active_coins": Mock(return_value={}),
            "bot_running": event,
            "risk_manager": risk,
            "tg_controller": None,
            "web_is_paused": Mock(return_value=False),
            "ai_enabled": False,
            "load_trades": Mock(return_value=[]),
            "get_indicators_for_coin": Mock(),
            "print_indicators": Mock(),
            "get_trend_bias": Mock(),
            "get_decision": Mock(),
            "rule_based_signal": Mock(),
            "print_decision": Mock(),
            "min_edge": 0.0,
            "entry_quality_gate": False,
            "min_entry_quality": 0.0,
            "stop_loss_pct": 0.01,
            "hl_enabled": False,
            "get_hl_obi": Mock(),
            "obi_gate": 0.0,
            "vol_min_ratio": 0.0,
            "close_trade": Mock(),
            "execute_trade": Mock(),
            "add_log": Mock(),
            "print_scan_summary": Mock(side_effect=lambda results: event.wait(0)),
            "sleep": Mock(),
            "bot_interval_sec": 1,
            "print_fn": Mock(),
            "fore": types.SimpleNamespace(CYAN="", GREEN="", YELLOW="", RED=""),
            "style": types.SimpleNamespace(RESET_ALL=""),
        }

    def test_halt_gate_short_circuits_pause_checks_and_waits(self):
        kwargs = self._base_kwargs()
        kwargs["risk_manager"].is_halted.return_value = (True, "halted")
        kwargs["tg_controller"] = Mock()

        run_bot_scan_loop(**kwargs)

        kwargs["risk_manager"].is_halted.assert_called_once_with()
        kwargs["tg_controller"].is_paused.assert_not_called()
        kwargs["web_is_paused"].assert_not_called()
        self.assertEqual(kwargs["bot_running"].wait_calls, [1])

    def test_telegram_pause_short_circuits_web_pause_and_coin_scan(self):
        kwargs = self._base_kwargs()
        kwargs["tg_controller"] = Mock()
        kwargs["tg_controller"].is_paused.return_value = True

        run_bot_scan_loop(**kwargs)

        kwargs["tg_controller"].is_paused.assert_called_once_with()
        kwargs["web_is_paused"].assert_not_called()
        kwargs["get_indicators_for_coin"].assert_not_called()
        self.assertEqual(kwargs["bot_running"].wait_calls, [1])

    def test_web_pause_skips_coin_scan_and_waits(self):
        kwargs = self._base_kwargs()
        kwargs["tg_controller"] = Mock()
        kwargs["tg_controller"].is_paused.return_value = False
        kwargs["web_is_paused"].return_value = True

        run_bot_scan_loop(**kwargs)

        kwargs["tg_controller"].is_paused.assert_called_once_with()
        kwargs["web_is_paused"].assert_called_once_with()
        kwargs["get_indicators_for_coin"].assert_not_called()
        self.assertEqual(kwargs["bot_running"].wait_calls, [1])

