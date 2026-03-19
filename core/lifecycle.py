"""Lifecycle helpers for starting and stopping the trading bot."""
from __future__ import annotations

import threading


def start_bot_lifecycle(
    *,
    bot_running,
    stop_event,
    validate_coin_config,
    validate_symbols,
    sync_positions,
    risk_manager,
    bot_loop,
    monitor_loop,
    printer=print,
    fore=None,
):
    """Start bot lifecycle components while preserving caller-owned state."""
    if bot_running.is_set():
        printer(fore.YELLOW + "  Bot is already running.")
        return None, None, None

    if getattr(risk_manager, "state", {}).get("emergency_stop") or getattr(risk_manager, "state", {}).get("trading_halted"):
        risk_manager.clear_emergency_stop()

    fixed_coin_configs = validate_coin_config() or []
    symbol_status = validate_symbols() or {"active": [], "disabled": []}
    disabled_symbols = list(symbol_status.get("disabled", []))
    merged_assets = list(symbol_status.get("merged", []))

    sync_ok = bool(sync_positions(quiet=True))
    if not sync_ok:
        return None, None, {
            "active": [coin for coin, _, _ in symbol_status.get("active", [])] if symbol_status.get("active") else [],
            "disabled": disabled_symbols,
            "merged": merged_assets,
            "sync_ok": False,
            "fixed_coin_configs": fixed_coin_configs,
        }

    stop_event.clear()
    bot_running.set()
    bot_thread = threading.Thread(target=bot_loop, name="bot-scan-loop")
    monitor_thread = threading.Thread(target=monitor_loop, name="bot-monitor-loop")
    bot_thread.start()
    monitor_thread.start()
    return bot_thread, monitor_thread, {
        "active": [coin for coin, _, _ in symbol_status.get("active", [])],
        "disabled": disabled_symbols,
        "merged": merged_assets,
        "sync_ok": True,
        "fixed_coin_configs": fixed_coin_configs,
    }


def stop_bot_lifecycle(
    *,
    bot_running,
    stop_event,
    bot_thread,
    monitor_thread,
    printer=print,
    fore=None,
):
    """Stop bot lifecycle components while preserving caller-owned state."""
    if not bot_running.is_set():
        printer(fore.YELLOW + "  Bot is not running.")
        return

    stop_event.set()
    bot_running.clear()

    printer(fore.YELLOW + "  Stopping bot… (finishes current scan)")
    for thread in (bot_thread, monitor_thread):
        if thread and thread.is_alive():
            thread.join(timeout=10)
