#!/usr/bin/env python3
"""Focused tests for bot lifecycle start/stop helpers."""
import threading
import types
import unittest
from unittest.mock import Mock

from core.lifecycle import start_bot_lifecycle, stop_bot_lifecycle


class TestLifecycle(unittest.TestCase):
    def test_start_bot_lifecycle_starts_controller_sets_event_and_threads(self):
        bot_running = threading.Event()
        sync_positions = Mock()
        printer = Mock()
        call_order = []

        def bot_loop():
            call_order.append("bot_loop")

        def monitor_loop():
            call_order.append("monitor_loop")

        controller = Mock()

        def controller_factory(**kwargs):
            call_order.append(("factory", kwargs))
            return controller

        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        bot_thread, monitor_thread, tg_controller = start_bot_lifecycle(
            bot_running=bot_running,
            sync_positions=sync_positions,
            telegram_controller_factory=controller_factory,
            risk_manager="risk",
            close_fn="close",
            closeall_fn="closeall",
            bot_loop=bot_loop,
            monitor_loop=monitor_loop,
            printer=printer,
            fore=fore,
        )

        self.assertTrue(bot_running.is_set())
        sync_positions.assert_called_once_with()
        controller.start.assert_called_once_with()
        self.assertIs(tg_controller, controller)
        self.assertIsInstance(bot_thread, threading.Thread)
        self.assertIsInstance(monitor_thread, threading.Thread)
        bot_thread.join(timeout=1)
        monitor_thread.join(timeout=1)
        self.assertEqual(call_order[0][0], "factory")
        self.assertEqual(call_order[1:], ["bot_loop", "monitor_loop"])
        self.assertEqual(
            printer.call_args_list,
            [
                unittest.mock.call("  Syncing local state with HL positions…"),
                unittest.mock.call("  SL/TP monitor started (checks every 2 min)."),
            ],
        )

    def test_start_bot_lifecycle_noops_when_already_running(self):
        bot_running = threading.Event()
        bot_running.set()
        sync_positions = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        result = start_bot_lifecycle(
            bot_running=bot_running,
            sync_positions=sync_positions,
            telegram_controller_factory=Mock(),
            risk_manager=None,
            close_fn=None,
            closeall_fn=None,
            bot_loop=Mock(),
            monitor_loop=Mock(),
            printer=printer,
            fore=fore,
        )

        self.assertEqual(result, (None, None, None))
        sync_positions.assert_not_called()
        printer.assert_called_once_with("  Bot is already running.")

    def test_stop_bot_lifecycle_clears_event_and_stops_controller(self):
        bot_running = threading.Event()
        bot_running.set()
        controller = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        result = stop_bot_lifecycle(
            bot_running=bot_running,
            tg_controller=controller,
            printer=printer,
            fore=fore,
        )

        self.assertFalse(bot_running.is_set())
        controller.stop.assert_called_once_with()
        self.assertIsNone(result)
        printer.assert_called_once_with("  Stopping bot… (finishes current scan)")

    def test_stop_bot_lifecycle_noops_when_not_running(self):
        bot_running = threading.Event()
        controller = Mock()
        printer = Mock()
        fore = types.SimpleNamespace(CYAN="", GREEN="", YELLOW="")

        result = stop_bot_lifecycle(
            bot_running=bot_running,
            tg_controller=controller,
            printer=printer,
            fore=fore,
        )

        controller.stop.assert_not_called()
        self.assertIs(result, controller)
        printer.assert_called_once_with("  Bot is not running.")

