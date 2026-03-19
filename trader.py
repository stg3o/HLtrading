"""
trader.py — trade execution layer
Handles both paper trading and live Hyperliquid trading.
Never makes decisions — only executes what risk_manager approves.
"""
import json
import math
import traceback
from datetime import datetime
from colorama import Fore, Style
from config import (TESTNET, HL_ENABLED, HL_WALLET_ADDRESS, HL_PRIVATE_KEY,
                    COINS, STOP_LOSS_PCT, TAKE_PROFIT_PCT, HL_MAX_POSITION_USD,
                    HL_LEVERAGE, DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT,
                    HL_ORACLE_DEVIATION_MAX)
from execution.account_service import (
    get_hl_account_info as _account_service_get_hl_account_info,
    get_hl_fees as _account_service_get_hl_fees,
    get_hl_positions as _account_service_get_hl_positions,
)
from execution.execution_service import (
    cancel_open_orders as _service_cancel_open_orders,
    close_trade as _service_close_trade,
    execute_trade as _service_execute_trade,
)
from execution.hyperliquid_client import (
    _hl_post as _hl_post_client,
    get_hl_funding_rate as _get_hl_funding_rate,
    get_hl_mark_oracle as _get_hl_mark_oracle,
    get_hl_obi as _get_hl_obi,
    get_hl_open_interest as _get_hl_open_interest,
    get_hl_open_orders as _get_hl_open_orders,
    get_hl_price as _get_hl_price,
)
from risk_manager import RiskManager, save_state


# ── HYPERLIQUID DIRECT API ─────────────────────────────────────────────────────

def _hl_post(endpoint: str, payload: dict):
    """Compatibility wrapper for the shared Hyperliquid REST client."""
    return _hl_post_client(endpoint, payload)


def _hl_exchange():
    """Return an authenticated Exchange object for order placement."""
    import eth_account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    base_url = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL
    account  = eth_account.Account.from_key(HL_PRIVATE_KEY)
    # Pass empty spot_meta to skip testnet spot-token fetch: the SDK tries to index
    # spot_meta["tokens"][base] but testnet's token list has mismatched indices.
    # We only trade perp futures, so spot metadata is never needed.
    return Exchange(account, base_url, account_address=HL_WALLET_ADDRESS,
                    spot_meta={"universe": [], "tokens": []})


def _available_hl_symbols(exchange=None) -> list[str]:
    """Return sorted available HL perp symbols for validation/reference."""
    exchange = exchange or _hl_exchange()
    symbols: set[str] = set()
    name_to_coin = getattr(exchange.info, "name_to_coin", None)
    if isinstance(name_to_coin, dict):
        for name in name_to_coin.keys():
            symbol = str(name).strip().upper()
            if symbol:
                symbols.add(symbol)
    try:
        meta = exchange.info.meta()
        if isinstance(meta, dict):
            for asset in meta.get("universe", []):
                name = str(asset.get("name", "")).strip().upper()
                if name:
                    symbols.add(name)
    except Exception:
        pass
    return sorted(symbols)


def _resolve_hl_symbol(coin: str, cfg: dict, valid_symbols: set[str]) -> str | None:
    """Resolve a configured coin onto a valid HL symbol with simple variants."""
    coin_name = str(coin).strip().upper()
    configured = str(cfg.get("hl_symbol", coin)).strip().upper()

    def _base(symbol: str) -> str:
        if symbol.endswith("-PERP"):
            return symbol[:-5]
        return symbol

    candidates: list[str] = []
    for raw in (configured, coin_name, _base(configured), _base(coin_name)):
        if not raw:
            continue
        for candidate in (raw, f"{raw}-PERP", f"K{raw}"):
            if candidate not in candidates:
                candidates.append(candidate)

    for candidate in candidates:
        if candidate in valid_symbols:
            return candidate

    for symbol in sorted(valid_symbols):
        if _base(symbol) in {_base(configured), _base(coin_name)}:
            return symbol

    return None


def _asset_priority_key(coin: str) -> tuple[int, str]:
    """Sort primary coin keys ahead of strategy variants sharing one asset."""
    normalized = str(coin).strip().upper()
    is_variant = 1 if "_" in normalized else 0
    return (is_variant, normalized)


def _dedupe_active_assets(active_rows: list[tuple[str, str, int]]) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int, str]]]:
    """Keep one active coin per asset_id and mark secondary variants for merge/disable."""
    grouped: dict[int, list[tuple[str, str, int]]] = {}
    for row in active_rows:
        grouped.setdefault(row[2], []).append(row)

    deduped: list[tuple[str, str, int]] = []
    merged: list[tuple[str, str, int, str]] = []
    for asset_id, rows in grouped.items():
        rows = sorted(rows, key=lambda row: _asset_priority_key(row[0]))
        primary = rows[0]
        deduped.append(primary)
        for secondary in rows[1:]:
            merged.append((secondary[0], secondary[1], asset_id, primary[0]))
    deduped.sort(key=lambda row: _asset_priority_key(row[0]))
    merged.sort(key=lambda row: (_asset_priority_key(row[3]), _asset_priority_key(row[0])))
    return deduped, merged


def print_available_hl_symbols() -> None:
    """Print all known Hyperliquid perp symbols for mapping/debugging."""
    if not HL_ENABLED:
        print(Fore.YELLOW + "  Hyperliquid mode is disabled.")
        return
    try:
        symbols = get_available_hl_symbols()
    except Exception as exc:
        print(Fore.RED + f"  Failed to fetch Hyperliquid symbols: {exc}")
        return
    if not symbols:
        print(Fore.YELLOW + "  No Hyperliquid symbols returned.")
        return
    print(Fore.CYAN + f"  Hyperliquid perp symbols ({len(symbols)}):")
    print("  " + ", ".join(symbols))


def get_available_hl_symbols() -> list[str]:
    """Return available Hyperliquid perp symbols for non-CLI callers."""
    if not HL_ENABLED:
        return []
    return _available_hl_symbols()


def validate_hl_symbols() -> dict:
    """Normalize and validate enabled HL symbols before the bot starts."""
    if not HL_ENABLED:
        return {"active": [], "disabled": []}
    exchange = _hl_exchange()
    available = set(_available_hl_symbols(exchange))
    disabled: list[str] = []
    active_rows: list[tuple[str, str, int]] = []
    merged: list[tuple[str, str, int, str]] = []
    for coin, cfg in COINS.items():
        if not cfg.get("enabled", False):
            continue
        symbol = _resolve_hl_symbol(coin, cfg, available)
        if not symbol:
            cfg.pop("asset_id", None)
            cfg["enabled"] = False
            disabled.append(coin)
            continue
        original = str(cfg.get("hl_symbol", coin)).strip().upper()
        cfg["hl_symbol"] = symbol
        try:
            asset_id = exchange.info.name_to_asset(symbol)
            name_to_coin = getattr(exchange.info, "name_to_coin", None)
            if callable(name_to_coin):
                name_to_coin(symbol)
            if asset_id in (None, "", 0):
                raise ValueError(f"invalid asset_id={asset_id}")
            cfg["asset_id"] = int(asset_id)
            active_rows.append((coin, symbol, cfg["asset_id"]))
        except Exception as exc:
            cfg.pop("asset_id", None)
            cfg["enabled"] = False
            disabled.append(coin)
    deduped_rows, merged = _dedupe_active_assets(active_rows)
    merged_coins = {coin for coin, _, _, _ in merged}
    for coin, _symbol, _asset_id, _primary in merged:
        cfg = COINS.get(coin, {})
        cfg["enabled"] = False
        disabled.append(coin)
    disabled = sorted(set(disabled), key=_asset_priority_key)
    return {"active": deduped_rows, "disabled": disabled, "merged": merged}


def validate_coin_risk_config() -> list[str]:
    """Ensure each coin has valid SL/TP config before startup."""
    fixed: list[str] = []
    for coin, cfg in COINS.items():
        changed = False
        try:
            sl_pct = float(cfg.get("stop_loss_pct"))
            if sl_pct <= 0:
                raise ValueError
        except Exception:
            cfg["stop_loss_pct"] = DEFAULT_STOP_LOSS_PCT
            changed = True
        try:
            tp_pct = float(cfg.get("take_profit_pct"))
            if tp_pct <= 0:
                raise ValueError
        except Exception:
            cfg["take_profit_pct"] = DEFAULT_TAKE_PROFIT_PCT
            changed = True
        if changed:
            fixed.append(coin)
    return fixed


def get_hl_price(coin: str) -> float | None:
    """Compatibility wrapper for the shared Hyperliquid price helper."""
    return _get_hl_price(coin)


def get_hl_obi(coin: str, levels: int = 10) -> float | None:
    """Compatibility wrapper for the shared Hyperliquid OBI helper."""
    return _get_hl_obi(coin, levels=levels)


def get_hl_funding_rate(coin: str) -> float | None:
    """Compatibility wrapper for the shared Hyperliquid funding helper."""
    return _get_hl_funding_rate(coin)


def get_hl_open_interest(coin: str) -> float | None:
    """Compatibility wrapper for the shared Hyperliquid OI helper."""
    return _get_hl_open_interest(coin)


def get_hl_mark_oracle(coin: str) -> dict | None:
    """Compatibility wrapper for the shared Hyperliquid mark/oracle helper."""
    return _get_hl_mark_oracle(coin)


def _oracle_execution_guard(coin: str) -> tuple[bool, str]:
    snapshot = get_hl_mark_oracle(coin)
    if not snapshot:
        return True, ""
    deviation = snapshot.get("deviation")
    try:
        deviation = float(deviation)
    except Exception:
        return True, ""
    if deviation <= HL_ORACLE_DEVIATION_MAX:
        return True, ""
    print(Fore.YELLOW + f"  EXECUTION DISABLED: oracle deviation {deviation:.1%}")
    return False, f"oracle deviation {deviation:.1%}"


def cancel_open_orders(coin: str, cancel_protection: bool = False) -> int:
    """Compatibility wrapper for execution-service order cancellation."""
    return _service_cancel_open_orders(
        coin=coin,
        hl_enabled=HL_ENABLED,
        hl_wallet_address=HL_WALLET_ADDRESS,
        coins=COINS,
        hl_post=_hl_post,
        get_hl_open_orders=get_hl_open_orders,
        hl_exchange_factory=_hl_exchange,
        cancel_protection=cancel_protection,
        printer=print,
        fore=Fore,
    )


def get_hl_positions() -> list:
    """Compatibility wrapper for the shared account service positions helper."""
    return _account_service_get_hl_positions()


def get_hl_open_orders() -> list:
    """Return raw open orders for the configured HL wallet."""
    return _get_hl_open_orders() if HL_ENABLED else []


def _hl_symbol_to_coin_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for coin, cfg in COINS.items():
        symbol = str(cfg.get("hl_symbol", "")).strip().upper()
        if symbol and symbol not in mapping:
            mapping[symbol] = coin
    return mapping


def _extract_verified_tpsl(
    open_orders: list[dict],
    hl_symbol: str,
    *,
    side: str | None = None,
    entry_price: float | None = None,
) -> tuple[float | None, float | None]:
    stop_loss = None
    take_profit = None
    target = str(hl_symbol).strip().upper()
    for order in open_orders:
        if str(order.get("coin", "")).strip().upper() != target:
            continue
        if not bool(order.get("reduceOnly", order.get("reduce_only", False))):
            continue
        trigger = order.get("orderType", {}).get("trigger") or order.get("trigger") or {}
        if not trigger:
            continue
        trigger_px = order.get("triggerPx", trigger.get("triggerPx"))
        try:
            px = float(trigger_px)
        except Exception:
            continue
        if side and entry_price:
            if side == "short":
                if px > entry_price:
                    stop_loss = px
                elif px < entry_price:
                    take_profit = px
            else:
                if px < entry_price:
                    stop_loss = px
                elif px > entry_price:
                    take_profit = px
            continue
        tpsl = str(trigger.get("tpsl") or order.get("tpsl") or "").lower()
        if tpsl == "sl":
            stop_loss = px
        elif tpsl == "tp":
            take_profit = px
    return stop_loss, take_profit


def _format_payload(payload) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return repr(payload)


def _first_status(payload: dict) -> dict:
    try:
        return payload["response"]["data"]["statuses"][0]
    except (KeyError, IndexError, TypeError):
        return {}


def _tick_decimals(exchange, asset_id: int) -> int:
    sz_decimals = int(exchange.info.asset_to_sz_decimals[asset_id])
    return max(0, 6 - sz_decimals)


def _tick_size(exchange, asset_id: int) -> float:
    return 10 ** (-_tick_decimals(exchange, asset_id))


def _format_tick_price(price: float, decimals: int) -> float:
    return float(f"{round(float(price), decimals):.{decimals}f}")


def _hl_price(price: float) -> float:
    return float(f"{float(price):.1f}")


def _is_valid_tick(price: float, tick_size: float) -> bool:
    steps = round(float(price) / tick_size)
    return abs(float(price) - (steps * tick_size)) < 1e-9


def _align_price_to_tick(price: float, tick_size: float, decimals: int, *, is_buy: bool) -> float:
    steps = price / tick_size
    aligned = math.ceil(steps) * tick_size if is_buy else math.floor(steps) * tick_size
    return _format_tick_price(aligned, decimals)


def _prepare_protection_prices(
    *,
    entry_price: float,
    side: str,
    stop_loss: float,
    take_profit: float,
    tick_size: float,
    decimals: int,
) -> tuple[float, float] | None:
    buffer_pct = 0.001
    if side == "long":
        stop_loss = min(float(stop_loss), entry_price * (1 - buffer_pct))
        take_profit = max(float(take_profit), entry_price * (1 + buffer_pct))
        aligned_sl = _align_price_to_tick(stop_loss, tick_size, decimals, is_buy=False)
        aligned_tp = _align_price_to_tick(take_profit, tick_size, decimals, is_buy=True)
        if not (aligned_sl < entry_price and aligned_tp > entry_price):
            return None
        return aligned_sl, aligned_tp

    stop_loss = max(float(stop_loss), entry_price * (1 + buffer_pct))
    take_profit = min(float(take_profit), entry_price * (1 - buffer_pct))
    aligned_sl = _align_price_to_tick(stop_loss, tick_size, decimals, is_buy=True)
    aligned_tp = _align_price_to_tick(take_profit, tick_size, decimals, is_buy=False)
    if not (aligned_sl > entry_price and aligned_tp < entry_price):
        return None
    return aligned_sl, aligned_tp


def _place_hl_protection_orders(
    *,
    coin: str,
    hl_symbol: str,
    side: str,
    size_units: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> dict:
    allowed, guard_reason = _oracle_execution_guard(hl_symbol)
    if not allowed:
        return {
            "confirmed": False,
            "stop_loss": None,
            "take_profit": None,
            "attempts": [{"error": guard_reason, "tpsl": "both"}],
        }
    exchange = _hl_exchange()
    asset_id = int(COINS.get(coin, {}).get("asset_id", 0) or 0)
    close_is_buy = (side == "short")
    decimals = _tick_decimals(exchange, asset_id)
    tick_size = _tick_size(exchange, asset_id)
    prepared = _prepare_protection_prices(
        entry_price=entry_price,
        side=side,
        stop_loss=stop_loss,
        take_profit=take_profit,
        tick_size=tick_size,
        decimals=decimals,
    )
    if prepared is None:
        return {
            "confirmed": False,
            "stop_loss": None,
            "take_profit": None,
            "attempts": [{"error": "invalid protection prices", "tpsl": "both"}],
        }
    stop_loss, take_profit = prepared
    print(Fore.CYAN + f"  Placing SL={stop_loss:,.4f} TP={take_profit:,.4f} (rounded, validated)")

    def _submit(trigger_px: float, *, tpsl: str, buffer_pct: float):
        aligned_trigger = _hl_price(trigger_px)
        limit_ref = aligned_trigger * (1 + buffer_pct) if close_is_buy else aligned_trigger * (1 - buffer_pct)
        limit_px = _hl_price(_align_price_to_tick(limit_ref, tick_size, decimals, is_buy=close_is_buy))
        if not _is_valid_tick(aligned_trigger, tick_size) or not _is_valid_tick(limit_px, tick_size):
            return {
                "ok": False,
                "response": {"error": "invalid_tick_precision", "triggerPx": aligned_trigger, "limit_px": limit_px},
                "error": "invalid_tick_precision",
                "trigger_px": aligned_trigger,
                "limit_px": limit_px,
                "tpsl": tpsl,
            }
        order = {
            "coin": hl_symbol,
            "is_buy": close_is_buy,
            "sz": size_units,
            "limit_px": limit_px,
            "reduce_only": True,
            "order_type": {
                "trigger": {
                    "triggerPx": aligned_trigger,
                    "isMarket": True,
                    "tpsl": tpsl,
                }
            },
        }
        if "trigger" not in order["order_type"]:
            return {
                "ok": False,
                "response": {"error": "invalid_order_type", "order": order},
                "error": "invalid_order_type",
                "trigger_px": aligned_trigger,
                "limit_px": limit_px,
                "tpsl": tpsl,
            }
        print(
            Fore.CYAN +
            f"  FINAL SEND triggerPx={aligned_trigger} limit_px={limit_px}"
        )
        response = exchange.bulk_orders([order], grouping="positionTpsl")
        status = _first_status(response)
        error = None
        if response.get("error") or "error" in _format_payload(response).lower():
            error = response.get("error") or _format_payload(response)
        elif status.get("error") or status.get("rejected"):
            error = status.get("error") or status.get("rejected")
        return {
            "ok": error is None,
            "response": response,
            "error": error,
            "trigger_px": aligned_trigger,
            "limit_px": limit_px,
            "tpsl": tpsl,
        }

    attempts = []
    for buffer_pct in (0.002, 0.004):
        sl_attempt = _submit(stop_loss, tpsl="sl", buffer_pct=buffer_pct)
        tp_attempt = _submit(take_profit, tpsl="tp", buffer_pct=buffer_pct)
        attempts.extend([sl_attempt, tp_attempt])
        open_orders = get_hl_open_orders()
        verified_sl, verified_tp = _extract_verified_tpsl(open_orders, hl_symbol)
        confirmed = verified_sl is not None and verified_tp is not None
        if confirmed:
            return {
                "confirmed": True,
                "stop_loss": verified_sl,
                "take_profit": verified_tp,
                "attempts": attempts,
            }

    return {
        "confirmed": False,
        "stop_loss": None,
        "take_profit": None,
        "attempts": attempts,
    }


def get_verified_hl_positions(*, protect_missing: bool = True, print_fn=print, fore=None) -> list[dict]:
    """Return HL positions with SL/TP derived from exchange orders, optionally repairing missing protection."""
    if not HL_ENABLED:
        return []

    hl_positions = get_hl_positions()
    open_orders = get_hl_open_orders()
    rows: list[dict] = []

    for wrapper in hl_positions:
        pos = wrapper.get("position") or {}
        try:
            size = float(pos.get("szi", 0) or 0)
        except Exception:
            continue
        if abs(size) <= 0:
            continue

        hl_symbol = str(pos.get("coin", "")).strip().upper()
        coin = _hl_symbol_to_coin_map().get(hl_symbol, hl_symbol)
        try:
            entry_price = float(pos.get("entryPx", 0) or 0)
        except Exception:
            entry_price = 0.0
        side = "long" if size > 0 else "short"
        stop_loss, take_profit = _extract_verified_tpsl(
            open_orders,
            hl_symbol,
            side=side,
            entry_price=entry_price,
        )
        protected = stop_loss is not None and take_profit is not None

        if protect_missing and not protected:
            cfg = COINS.get(coin, {})
            try:
                sl_pct = float(cfg.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT))
            except Exception:
                sl_pct = DEFAULT_STOP_LOSS_PCT
            try:
                tp_pct = float(cfg.get("take_profit_pct", DEFAULT_TAKE_PROFIT_PCT))
            except Exception:
                tp_pct = DEFAULT_TAKE_PROFIT_PCT
            calc_sl = round(entry_price * (1 - sl_pct), 4) if side == "long" else round(entry_price * (1 + sl_pct), 4)
            calc_tp = round(entry_price * (1 + tp_pct), 4) if side == "long" else round(entry_price * (1 - tp_pct), 4)
            try:
                placement = _place_hl_protection_orders(
                    coin=coin,
                    hl_symbol=hl_symbol,
                    side=side,
                    size_units=abs(size),
                    entry_price=entry_price,
                    stop_loss=calc_sl,
                    take_profit=calc_tp,
                )
                open_orders = get_hl_open_orders()
                stop_loss, take_profit = _extract_verified_tpsl(
                    open_orders,
                    hl_symbol,
                    side=side,
                    entry_price=entry_price,
                )
                protected = bool(placement.get("confirmed"))
                if protected:
                    print_fn(fore.YELLOW + f"  ⚠ Missing SL/TP -> protection orders confirmed for {hl_symbol}")
                else:
                    print_fn(fore.RED + f"  CRITICAL: SL/TP placement failed for {hl_symbol}")
                    for attempt in placement.get("attempts", []):
                        if attempt.get("error"):
                            print_fn(fore.YELLOW + f"  {hl_symbol} {attempt['tpsl'].upper()} error: {_format_payload(attempt.get('response'))}")
            except Exception as exc:
                print_fn(fore.RED + f"  CRITICAL: SL/TP placement failed for {hl_symbol}: {exc}")

        rows.append({
            "coin": coin,
            "hl_symbol": hl_symbol,
            "side": side,
            "size_units": abs(size),
            "entry_price": entry_price,
            "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "protected": protected,
        })

    return rows


def _local_position_snapshot(position: dict) -> dict:
    return {
        "side": str(position.get("side", "")),
        "entry_price": round(float(position.get("entry_price", 0) or 0), 8),
        "size_units": round(abs(float(position.get("size_units", 0) or 0)), 8),
        "stop_loss": round(float(position.get("stop_loss", 0) or 0), 8) if position.get("stop_loss") not in (None, "") else None,
        "take_profit": round(float(position.get("take_profit", 0) or 0), 8) if position.get("take_profit") not in (None, "") else None,
    }


def sync_local_positions_with_hl(
    risk_manager: RiskManager,
    *,
    only_coin: str | None = None,
    print_fn=print,
    fore=None,
) -> dict:
    """Overwrite local positions from live HL positions and verified HL TP/SL orders."""
    if not HL_ENABLED:
        return {"synced": False, "positions": dict(risk_manager.state.get("positions", {}))}

    existing_positions = dict(risk_manager.state.get("positions", {}))
    hl_positions = get_hl_positions()
    open_orders = get_hl_open_orders()
    symbol_to_coin = _hl_symbol_to_coin_map()
    desired_positions: dict[str, dict] = {}

    for wrapper in hl_positions:
        position = wrapper.get("position") or {}
        try:
            size = float(position.get("szi", 0) or 0)
        except Exception:
            continue
        if abs(size) <= 0:
            continue
        hl_symbol = str(position.get("coin", "")).strip().upper()
        coin = symbol_to_coin.get(hl_symbol)
        if not coin:
            continue
        if only_coin and coin != only_coin:
            continue
        try:
            entry_price = float(position.get("entryPx", 0) or 0)
        except Exception:
            entry_price = 0.0
        stop_loss, take_profit = _extract_verified_tpsl(open_orders, hl_symbol)
        local_existing = existing_positions.get(coin, {})
        desired_positions[coin] = {
            "side": "long" if size > 0 else "short",
            "entry_price": entry_price,
            "size_units": abs(size),
            "size_usd": round(abs(size) * entry_price, 2),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "opened_at": local_existing.get("opened_at") or str(datetime.now()),
            "ai_confidence": local_existing.get("ai_confidence"),
            "cascade_assisted": bool(local_existing.get("cascade_assisted", False)),
            "entry_context": local_existing.get("entry_context", "normal"),
        }

    if only_coin:
        new_positions = dict(existing_positions)
        if only_coin in desired_positions:
            new_positions[only_coin] = desired_positions[only_coin]
        else:
            new_positions.pop(only_coin, None)
    else:
        new_positions = desired_positions

    mismatch = False
    existing_keys = {only_coin} if only_coin else set(existing_positions.keys()) | set(new_positions.keys())
    for coin in existing_keys:
        left = existing_positions.get(coin)
        right = new_positions.get(coin)
        if left is None and right is None:
            continue
        if left is None or right is None:
            mismatch = True
            break
        if _local_position_snapshot(left) != _local_position_snapshot(right):
            mismatch = True
            break

    if mismatch:
        print_fn(fore.YELLOW + "DESYNC DETECTED: local vs HL → correcting")
        risk_manager.state["positions"] = new_positions
        save_state(risk_manager.state)
    elif existing_positions != new_positions:
        risk_manager.state["positions"] = new_positions
        save_state(risk_manager.state)

    return {"synced": True, "positions": new_positions}


def get_hl_account_info() -> dict:
    """Compatibility wrapper for the shared account service helper."""
    return _account_service_get_hl_account_info()


def get_hl_fees() -> dict:
    """Compatibility wrapper for the shared account service fee helper."""
    return _account_service_get_hl_fees()


# ── TRADE EXECUTION ────────────────────────────────────────────────────────────

def execute_trade(coin: str, side: str, size: float, risk_manager: RiskManager,
                  vol_regime: str = "normal",
                  kc_mid: float = 0.0,
                  signal_price: float | None = None,
                  ai_confidence: float | None = None,
                  entry_tags: dict | None = None,
                  quiet: bool = False,
                  return_result: bool = False):
    from notifier import notify_trade_open
    from strategy import get_indicators_for_coin

    return _service_execute_trade(
        coin=coin,
        side=side,
        size=size,
        risk_manager=risk_manager,
        vol_regime=vol_regime,
        kc_mid=kc_mid,
        signal_price=signal_price,
        ai_confidence=ai_confidence,
        entry_tags=entry_tags,
        coins=COINS,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        hl_enabled=HL_ENABLED,
        testnet=TESTNET,
        hl_leverage=HL_LEVERAGE,
        hl_max_position_usd=HL_MAX_POSITION_USD,
        get_hl_price=get_hl_price,
        get_indicator_price=get_indicators_for_coin,
        get_hl_mark_oracle=get_hl_mark_oracle,
        hl_exchange_factory=_hl_exchange,
        get_hl_open_orders=get_hl_open_orders,
        sync_local_positions_with_hl=sync_local_positions_with_hl,
        notify_trade_open=notify_trade_open,
        printer=print,
        fore=Fore,
        style=Style,
        quiet=quiet,
        return_result=return_result,
    )


def close_trade(coin: str, risk_manager: RiskManager, reason: str = "manual") -> bool:
    from notifier  import notify_trade_close
    from trade_log import log_trade
    from strategy import get_indicators_for_coin

    return _service_close_trade(
        coin=coin,
        risk_manager=risk_manager,
        reason=reason,
        coins=COINS,
        hl_enabled=HL_ENABLED,
        get_hl_price=get_hl_price,
        get_indicator_price=get_indicators_for_coin,
        get_hl_mark_oracle=get_hl_mark_oracle,
        cancel_open_orders_fn=cancel_open_orders,
        hl_exchange_factory=_hl_exchange,
        notify_trade_close=notify_trade_close,
        log_trade=log_trade,
        printer=print,
        fore=Fore,
        style=Style,
    )


def emergency_close_all(risk_manager: RiskManager) -> None:
    """Close all open positions immediately."""
    from notifier import notify_emergency
    positions = list(risk_manager.state.get("positions", {}).keys())
    if not positions:
        print(Fore.YELLOW + "  No open positions to close.")
        risk_manager.trigger_emergency_stop()
        return
    print(Fore.RED + f"\n  ⚠  EMERGENCY CLOSE — {len(positions)} position(s)")
    for coin in positions:
        close_trade(coin, risk_manager, reason="emergency stop")
    risk_manager.trigger_emergency_stop()
    notify_emergency("Manual emergency stop triggered")
    print(Fore.RED + "  Emergency stop active. Trading halted.")


def print_positions(risk_manager: RiskManager) -> None:
    """Print all open positions with live P&L."""
    def fmt_price(value) -> str:
        if value in (None, ""):
            return "—"
        try:
            return f"${float(value):,.4f}"
        except Exception:
            return "—"

    positions = risk_manager.state.get("positions", {})
    if not positions:
        print(Fore.YELLOW + "  No open positions.")
        return

    print(f"\n  {Fore.CYAN}{'─'*44}")
    print(f"  {Fore.CYAN}OPEN POSITIONS")
    for coin, pos in positions.items():
        price = get_hl_price(coin) if HL_ENABLED else None
        if price:
            live_pnl  = ((price - pos["entry_price"]) if pos["side"] == "long"
                         else (pos["entry_price"] - price)) * pos["size_units"]
            pnl_color = Fore.GREEN if live_pnl >= 0 else Fore.RED
            pnl_str   = f"{pnl_color}${live_pnl:+,.2f}{Style.RESET_ALL}"
        else:
            pnl_str = Fore.YELLOW + "N/A"

        if pos.get("stop_loss") is None or pos.get("take_profit") is None:
            print(Fore.YELLOW + f"  WARNING: Missing SL/TP for {coin}")

        print(
            f"  {coin:4}  {pos['side'].upper():5}  entry={fmt_price(pos.get('entry_price'))}"
            f"  SL={fmt_price(pos.get('stop_loss'))}  TP={fmt_price(pos.get('take_profit'))}  P&L={pnl_str}"
        )
