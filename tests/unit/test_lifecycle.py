#!/usr/bin/env python3
"""Focused tests for bot lifecycle start/stop helpers."""
import threading
import types
import unittest
from unittest.mock import Mock

from core.lifecycle import start_bot_lifecycle, stop_bot_lifecycle


class TestLifecycle(unittest.TestCase):
    def test_start_bot_lifecycle_sets_event_and_threads(self):
        bot_running = threading.Event()
        stop_event = threading.Event()
        validate_coin_config = Mock(return_value=[])
        validate_symbols = Mock(return_value={"active": [("BTC", "BTC", 3)], "disabled": [], "merged": []})
        sync_positions = Mock()
        printer = Mock()
        call_order = []

        def bot_loop():
            call_order.append("bot_loop")

        def monitor_loop():
            call_order.append("monitor_loop")

        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        bot_thread, monitor_thread, init_status = start_bot_lifecycle(
            bot_running=bot_running,
            stop_event=stop_event,
            validate_coin_config=validate_coin_config,
            validate_symbols=validate_symbols,
            sync_positions=sync_positions,
            risk_manager="risk",
            bot_loop=bot_loop,
            monitor_loop=monitor_loop,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(bot_running.is_set())
        self.assertFalse(stop_event.is_set())
        sync_positions.assert_called_once_with(quiet=True)
        self.assertIsInstance(bot_thread, threading.Thread)
        self.assertIsInstance(monitor_thread, threading.Thread)
        self.assertTrue(init_status["sync_ok"])
        bot_thread.join(timeout=1)
        monitor_thread.join(timeout=1)
        self.assertEqual(call_order, ["bot_loop", "monitor_loop"])
        printer.assert_not_called()

    def test_start_bot_lifecycle_noops_when_already_running(self):
        bot_running = threading.Event()
        bot_running.set()
        stop_event = threading.Event()
        sync_positions = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        result = start_bot_lifecycle(
            bot_running=bot_running,
            stop_event=stop_event,
            validate_coin_config=Mock(),
            validate_symbols=Mock(),
            sync_positions=sync_positions,
            risk_manager=None,
            bot_loop=Mock(),
            monitor_loop=Mock(),
            printer=printer,
            fore=fore,
        )

        self.assertEqual(result, (None, None, None))
        sync_positions.assert_not_called()
        printer.assert_called_once_with("  Bot is already running.")

    def test_stop_bot_lifecycle_clears_event(self):
        bot_running = threading.Event()
        bot_running.set()
        stop_event = threading.Event()
        printer = Mock()
        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        stop_bot_lifecycle(
            bot_running=bot_running,
            stop_event=stop_event,
            bot_thread=None,
            monitor_thread=None,
            printer=printer,
            fore=fore,
        )

        self.assertFalse(bot_running.is_set())
        self.assertTrue(stop_event.is_set())
        printer.assert_called_once_with("  Stopping bot… (finishes current scan)")

    def test_stop_bot_lifecycle_noops_when_not_running(self):
        bot_running = threading.Event()
        stop_event = threading.Event()
        printer = Mock()
        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        stop_bot_lifecycle(
            bot_running=bot_running,
            stop_event=stop_event,
            bot_thread=None,
            monitor_thread=None,
            printer=printer,
            fore=fore,
        )

        printer.assert_called_once_with("  Bot is not running.")
