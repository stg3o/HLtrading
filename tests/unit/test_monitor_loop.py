#!/usr/bin/env python3
"""Focused regression tests for monitor-loop orchestration."""
import types
import unittest
from unittest.mock import Mock

from core.monitor_loop import run_monitor_loop


class _StopAfterWaitEvent:
    def __init__(self):
        self._set = True

    def is_set(self):
        return self._set

    def clear(self):
        self._set = False


class TestMonitorLoop(unittest.TestCase):
    def _base_kwargs(self):
        return {
            "bot_running": _StopAfterWaitEvent(),
            "risk_manager": types.SimpleNamespace(state={"positions": {}}),
            "hl_enabled": True,
            "get_hl_price": Mock(return_value=None),
            "get_indicator_price": Mock(return_value=None),
            "close_trade": Mock(),
            "monitor_interval_sec": 1,
            "sleep": Mock(),
            "print_fn": Mock(),
            "fore": types.SimpleNamespace(YELLOW=""),
        }

    def test_uses_indicator_price_fallback_when_hl_price_missing(self):
        kwargs = self._base_kwargs()
        kwargs["risk_manager"].state["positions"] = {
            "SOL": {"side": "long", "stop_loss": 100.0, "take_profit": 120.0}
        }
        kwargs["get_indicator_price"].return_value = 99.0
        kwargs["sleep"].side_effect = lambda _: kwargs["bot_running"].clear()

        run_monitor_loop(**kwargs)

        kwargs["get_hl_price"].assert_called_once_with("SOL")
        kwargs["get_indicator_price"].assert_called_once_with("SOL")
        kwargs["close_trade"].assert_called_once_with("SOL", kwargs["risk_manager"], reason="stop loss")

    def test_skips_indicator_fallback_when_hl_price_available(self):
        kwargs = self._base_kwargs()
        kwargs["risk_manager"].state["positions"] = {
            "ETH": {"side": "short", "stop_loss": 110.0, "take_profit": 90.0}
        }
        kwargs["get_hl_price"].return_value = 89.0
        kwargs["sleep"].side_effect = lambda _: kwargs["bot_running"].clear()

        run_monitor_loop(**kwargs)

        kwargs["get_hl_price"].assert_called_once_with("ETH")
        kwargs["get_indicator_price"].assert_not_called()
        kwargs["close_trade"].assert_called_once_with("ETH", kwargs["risk_manager"], reason="take profit")

    def test_continues_when_price_lookup_raises(self):
        kwargs = self._base_kwargs()
        kwargs["risk_manager"].state["positions"] = {
            "BTC": {"side": "long", "stop_loss": 100.0, "take_profit": 120.0}
        }
        kwargs["get_hl_price"].side_effect = RuntimeError("boom")
        kwargs["sleep"].side_effect = lambda _: kwargs["bot_running"].clear()

        run_monitor_loop(**kwargs)

        kwargs["close_trade"].assert_not_called()
        kwargs["get_indicator_price"].assert_not_called()

