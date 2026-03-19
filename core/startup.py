"""Startup-only reconciliation helpers for the trading runtime."""

from __future__ import annotations


class _NoColor:
    YELLOW = ""
    GREEN = ""
    RED = ""


def _parse_hl_position(wrapper: dict) -> dict | None:
    """Extract the normalized HL position payload from a wrapper object."""
    position = wrapper.get("position", wrapper) if isinstance(wrapper, dict) else {}
    if not isinstance(position, dict):
        return None
    coin = str(position.get("coin", "")).strip().upper()
    try:
        size = float(position.get("szi", 0) or 0)
    except Exception:
        size = 0.0
    if not coin or size == 0:
        return None
    try:
        entry_price = float(position.get("entryPx", 0) or 0)
    except Exception:
        entry_price = 0.0
    return {
        "coin": coin,
        "size": size,
        "entry_price": entry_price,
    }


def _build_hl_symbol_map(coins: dict) -> dict[str, str]:
    """Build a reverse lookup of HL symbol -> local coin key."""
    mapping: dict[str, str] = {}
    for coin, cfg in coins.items():
        hl_symbol = str(cfg.get("hl_symbol", coin)).strip().upper()
        if hl_symbol and hl_symbol not in mapping:
            mapping[hl_symbol] = coin
    return mapping


def _build_imported_position(
    *,
    side: str,
    entry_price: float,
    size_units: float,
    sl_pct: float,
    tp_pct: float,
) -> dict:
    """Create the local monitored position payload for an imported HL position."""
    stop_loss = round(entry_price * (1 - sl_pct), 4) if side == "long" \
        else round(entry_price * (1 + sl_pct), 4)
    take_profit = round(entry_price * (1 + tp_pct), 4) if side == "long" \
        else round(entry_price * (1 - tp_pct), 4)
    return {
        "side": side,
        "entry_price": entry_price,
        "size_units": size_units,
        "size_usd": round(size_units * entry_price, 2),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "opened_at": "",
        "ai_confidence": None,
        "cascade_assisted": False,
        "entry_context": "imported_startup",
    }


def sync_positions_with_hl(
    *,
    hl_enabled: bool,
    risk,
    coins: dict,
    get_hl_positions,
    save_state,
    auto_import_positions: bool,
    default_stop_loss_pct: float,
    default_take_profit_pct: float,
    printer=print,
    fore=None,
    quiet: bool = False,
) -> bool:
    """
    Reconcile locally tracked positions against live Hyperliquid positions.

    This keeps the startup logic isolated from the CLI/runtime module while
    preserving the exact sequence and messages used by the caller.
    """
    if not hl_enabled:
        return True

    fore = fore or _NoColor()
    def _emit(message: str) -> None:
        if not quiet:
            printer(message)
    try:
        hl_positions = get_hl_positions()
        parsed_positions = {}
        for wrapper in hl_positions:
            parsed = _parse_hl_position(wrapper)
            if parsed:
                parsed_positions[parsed["coin"]] = parsed
        hl_coins = set(parsed_positions)
        local_coins = set(risk.state.get("positions", {}).keys())
        hl_symbol_to_coin = _build_hl_symbol_map(coins)

        local_hl_symbols = {
            str(cfg.get("hl_symbol", coin)).strip().upper(): coin
            for coin, cfg in coins.items()
            if coin in local_coins
        }

        for hl_symbol, local_coin in local_hl_symbols.items():
            if hl_symbol not in hl_coins:
                risk.state["positions"].pop(local_coin, None)
                save_state(risk.state)
                _emit(
                    fore.YELLOW + f"  [sync] {local_coin} was closed on HL while bot "
                    f"was down — removed from local state. Bot will re-enter on next signal."
                )

        for hl_symbol in hl_coins:
            if hl_symbol not in local_hl_symbols:
                if not auto_import_positions:
                    _emit(
                        fore.RED + f"  [sync] BLOCKED: {hl_symbol} is open on HL but not "
                        f"tracked locally. Close it manually or enable AUTO_IMPORT_POSITIONS."
                    )
                    return False

                local_coin = hl_symbol_to_coin.get(hl_symbol)
                if not local_coin:
                    _emit(
                        fore.YELLOW + f"  [sync] WARNING: {hl_symbol} is open on HL but no local "
                        f"coin config maps to it. Skipping import; close it manually or add hl_symbol mapping."
                    )
                    continue

                coin_cfg = coins.get(local_coin, {})
                live_pos = parsed_positions[hl_symbol]
                entry_price = float(live_pos.get("entry_price") or 0)
                if entry_price <= 0:
                    _emit(
                        fore.RED + f"  [sync] BLOCKED: {hl_symbol} is open on HL but entry price "
                        f"is missing. Close it manually before starting the bot."
                    )
                    return False

                side = "long" if live_pos["size"] > 0 else "short"
                size_units = abs(float(live_pos["size"]))
                sl_pct = coin_cfg.get("stop_loss_pct")
                tp_pct = coin_cfg.get("take_profit_pct")
                if sl_pct is None or tp_pct is None:
                    _emit(
                        fore.YELLOW + f"  [sync] WARNING: {local_coin} maps to {hl_symbol} but "
                        f"stop_loss_pct/take_profit_pct is missing. Applying defaults "
                        f"(sl={default_stop_loss_pct:.4f}, tp={default_take_profit_pct:.4f})."
                    )
                    sl_pct = default_stop_loss_pct if sl_pct is None else sl_pct
                    tp_pct = default_take_profit_pct if tp_pct is None else tp_pct
                try:
                    sl_pct = float(sl_pct)
                    tp_pct = float(tp_pct)
                except Exception:
                    _emit(
                        fore.YELLOW + f"  [sync] WARNING: {local_coin} has invalid stop_loss_pct/"
                        f"take_profit_pct values. Applying defaults "
                        f"(sl={default_stop_loss_pct:.4f}, tp={default_take_profit_pct:.4f})."
                    )
                    sl_pct = default_stop_loss_pct
                    tp_pct = default_take_profit_pct
                imported = _build_imported_position(
                    side=side,
                    entry_price=entry_price,
                    size_units=size_units,
                    sl_pct=sl_pct,
                    tp_pct=tp_pct,
                )
                risk.state.setdefault("positions", {})[local_coin] = imported
                save_state(risk.state)
                _emit(
                    fore.GREEN + f"  [sync] Imported {hl_symbol} into local state as {local_coin}: "
                    f"{side} {size_units:g} @ ${entry_price:,.4f} "
                    f"(SL ${imported['stop_loss']:,.4f} / TP ${imported['take_profit']:,.4f})"
                )

        if not (hl_coins ^ set(local_hl_symbols)):
            _emit(fore.GREEN + "  [sync] Local state matches HL positions ✓")
    except Exception as exc:
        _emit(fore.YELLOW + f"  [sync] Could not sync with HL on startup: {exc}")
        return False
    return True
