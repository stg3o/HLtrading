"""Lifecycle helpers for starting and stopping the trading bot."""
from __future__ import annotations

import threading


def start_bot_lifecycle(
    *,
    bot_running,
    sync_positions,
    telegram_controller_factory,
    risk_manager,
    close_fn,
    closeall_fn,
    bot_loop,
    monitor_loop,
    printer=print,
    fore=None,
):
    """Start bot lifecycle components while preserving caller-owned state."""
    if bot_running.is_set():
        printer(fore.YELLOW + "  Bot is already running.")
        return None, None, None

    printer(fore.CYAN + "  Syncing local state with HL positions…")
    sync_positions()

    tg_controller = telegram_controller_factory(
        risk_manager=risk_manager,
        close_fn=close_fn,
        closeall_fn=closeall_fn,
    )
    tg_controller.start()

    bot_running.set()
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    bot_thread.start()
    monitor_thread.start()
    printer(fore.GREEN + "  SL/TP monitor started (checks every 2 min).")
    return bot_thread, monitor_thread, tg_controller


def stop_bot_lifecycle(
    *,
    bot_running,
    tg_controller,
    printer=print,
    fore=None,
):
    """Stop bot lifecycle components while preserving caller-owned state."""
    if not bot_running.is_set():
        printer(fore.YELLOW + "  Bot is not running.")
        return tg_controller

    bot_running.clear()
    if tg_controller:
        tg_controller.stop()
        return_controller = None
    else:
        return_controller = tg_controller

    printer(fore.YELLOW + "  Stopping bot… (finishes current scan)")
    return return_controller
