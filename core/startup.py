"""Startup-only reconciliation helpers for the trading runtime."""

from __future__ import annotations


class _NoColor:
    YELLOW = ""
    GREEN = ""


def sync_positions_with_hl(
    *,
    hl_enabled: bool,
    risk,
    coins: dict,
    get_hl_positions,
    save_state,
    printer=print,
    fore=None,
) -> None:
    """
    Reconcile locally tracked positions against live Hyperliquid positions.

    This keeps the startup logic isolated from the CLI/runtime module while
    preserving the exact sequence and messages used by the caller.
    """
    if not hl_enabled:
        return

    fore = fore or _NoColor()
    try:
        hl_positions = get_hl_positions()
        hl_coins = {
            position["position"]["coin"]
            for position in hl_positions
            if float(position["position"].get("szi", 0)) != 0
        }
        local_coins = set(risk.state.get("positions", {}).keys())

        local_hl_symbols = {
            cfg.get("hl_symbol", coin): coin
            for coin, cfg in coins.items()
            if coin in local_coins
        }

        for hl_symbol, local_coin in local_hl_symbols.items():
            if hl_symbol not in hl_coins:
                risk.state["positions"].pop(local_coin, None)
                save_state(risk.state)
                printer(
                    fore.YELLOW + f"  [sync] {local_coin} was closed on HL while bot "
                    f"was down — removed from local state. Bot will re-enter on next signal."
                )

        for hl_symbol in hl_coins:
            if hl_symbol not in local_hl_symbols:
                printer(
                    fore.YELLOW + f"  [sync] WARNING: {hl_symbol} is open on HL but not "
                    f"tracked locally. Close it manually in HL or it will be unmonitored."
                )

        if not (hl_coins ^ set(local_hl_symbols)):
            printer(fore.GREEN + "  [sync] Local state matches HL positions ✓")
    except Exception as exc:
        printer(fore.YELLOW + f"  [sync] Could not sync with HL on startup: {exc}")
