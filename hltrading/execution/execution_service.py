"""Execution service helpers extracted from trader.py."""
from __future__ import annotations

import json
import math
import traceback

from config import (
    DEBUG_MODE,
    HL_MAX_FILL_SLIPPAGE,
    HL_ORDER_RETRY_SLIPPAGE,
    HL_ORDER_SLIPPAGE,
    HL_ORACLE_DEVIATION_MAX,
)


def _first_status(payload: dict) -> dict:
    """Return the first HL status payload if present."""
    try:
        return payload["response"]["data"]["statuses"][0]
    except (KeyError, IndexError, TypeError):
        return {}


def _format_payload(payload) -> str:
    """Best-effort compact formatting for debug logs."""
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return repr(payload)


def _top_of_book(exchange, symbol: str) -> tuple[float | None, float | None]:
    """Return (best_bid, best_ask) from Hyperliquid L2, or (None, None) on failure."""
    try:
        snapshot = exchange.info.l2_snapshot(symbol)
        levels = snapshot.get("levels", [[], []]) if isinstance(snapshot, dict) else [[], []]
        bids = levels[0] if len(levels) > 0 else []
        asks = levels[1] if len(levels) > 1 else []
        best_bid = float(bids[0]["px"]) if bids else None
        best_ask = float(asks[0]["px"]) if asks else None
        return best_bid, best_ask
    except Exception:
        return None, None


def _raw_top_of_book(exchange, symbol: str):
    """Return the raw Hyperliquid L2 snapshot for debug logging."""
    try:
        return exchange.info.l2_snapshot(symbol)
    except Exception as exc:
        return {"error": str(exc), "symbol": symbol}


def _tick_decimals(exchange, asset_id: int) -> int:
    """Derive HL perp price decimals from the SDK's own rounding rule."""
    sz_decimals = int(exchange.info.asset_to_sz_decimals[asset_id])
    return max(0, 6 - sz_decimals)


def _tick_size(exchange, asset_id: int) -> float:
    """Return the inferred tick size for a perp asset."""
    return 10 ** (-_tick_decimals(exchange, asset_id))


def _format_tick_price(price: float, decimals: int) -> float:
    return float(f"{round(float(price), decimals):.{decimals}f}")


def _hl_price(price: float) -> float:
    return float(f"{float(price):.1f}")


def _is_valid_tick(price: float, tick_size: float) -> bool:
    steps = round(float(price) / tick_size)
    return abs(float(price) - (steps * tick_size)) < 1e-9


def _align_price_to_tick(price: float, tick_size: float, decimals: int, *, is_buy: bool) -> float:
    """Round a price onto the valid HL tick grid without losing crossing direction."""
    steps = price / tick_size
    aligned = math.ceil(steps) * tick_size if is_buy else math.floor(steps) * tick_size
    return _format_tick_price(aligned, decimals)


def _debug_print(enabled: bool, printer, message: str) -> None:
    if enabled:
        printer(message)


def _oracle_execution_guard(
    *,
    coin: str,
    get_hl_mark_oracle,
    printer,
    fore,
    quiet: bool = False,
) -> tuple[bool, str]:
    snapshot = get_hl_mark_oracle(coin) if get_hl_mark_oracle else None
    if not snapshot:
        return True, ""
    deviation = snapshot.get("deviation")
    try:
        deviation = float(deviation)
    except Exception:
        return True, ""
    if deviation <= HL_ORACLE_DEVIATION_MAX:
        return True, ""
    message = f"EXECUTION DISABLED: oracle deviation {deviation:.1%}"
    if not quiet:
        printer((fore.YELLOW if fore is not None else "") + f"  {message}")
    return False, f"oracle deviation {deviation:.1%}"


def _extract_verified_tpsl(
    open_orders: list[dict],
    symbol: str,
    *,
    side: str | None = None,
    entry_price: float | None = None,
) -> tuple[float | None, float | None]:
    stop_loss = None
    take_profit = None
    target = str(symbol).strip().upper()
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


def _place_verified_tpsl(
    *,
    exchange,
    symbol: str,
    asset_id: int,
    side: str,
    entry_price: float,
    size_units: float,
    stop_loss: float,
    take_profit: float,
    coin: str,
    get_hl_mark_oracle,
    get_hl_open_orders,
    printer,
    fore,
) -> dict:
    allowed, guard_reason = _oracle_execution_guard(
        coin=coin,
        get_hl_mark_oracle=get_hl_mark_oracle,
        printer=printer,
        fore=fore,
    )
    if not allowed:
        return {
            "confirmed": False,
            "stop_loss": None,
            "take_profit": None,
            "attempts": [{"error": guard_reason, "tpsl": "both"}],
        }
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
    printer(fore.CYAN + f"  Placing SL={stop_loss:,.4f} TP={take_profit:,.4f} (rounded, validated)")

    def _submit(trigger_px: float, *, tpsl: str, buffer_pct: float):
        aligned_trigger = _hl_price(trigger_px)
        limit_ref = aligned_trigger * (1 + buffer_pct) if close_is_buy else aligned_trigger * (1 - buffer_pct)
        limit_px = _hl_price(_align_price_to_tick(limit_ref, tick_size, decimals, is_buy=close_is_buy))
        if not _is_valid_tick(aligned_trigger, tick_size) or not _is_valid_tick(limit_px, tick_size):
            return {
                "ok": False,
                "response": {"error": "invalid_tick_precision", "triggerPx": aligned_trigger, "limit_px": limit_px},
                "error": "invalid_tick_precision",
                "tpsl": tpsl,
                "trigger_px": aligned_trigger,
                "limit_px": limit_px,
            }
        order = {
            "coin": symbol,
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
                "tpsl": tpsl,
                "trigger_px": aligned_trigger,
                "limit_px": limit_px,
            }
        printer(
            fore.CYAN +
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
            "tpsl": tpsl,
            "trigger_px": aligned_trigger,
            "limit_px": limit_px,
        }

    attempts = []
    for buffer_pct in (0.002, 0.004):
        sl_attempt = _submit(stop_loss, tpsl="sl", buffer_pct=buffer_pct)
        tp_attempt = _submit(take_profit, tpsl="tp", buffer_pct=buffer_pct)
        attempts.extend([sl_attempt, tp_attempt])
        verified_orders = get_hl_open_orders()
        verified_sl, verified_tp = _extract_verified_tpsl(
            verified_orders,
            symbol,
            side=side,
            entry_price=entry_price,
        )
        if verified_sl is not None and verified_tp is not None:
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


def cancel_open_orders(
    *,
    coin: str,
    hl_enabled: bool,
    hl_wallet_address: str,
    coins: dict,
    hl_post,
    get_hl_open_orders=None,
    hl_exchange_factory,
    cancel_protection: bool = False,
    printer=print,
    fore=None,
) -> int:
    """
    Cancel open orders for a coin on HL.
    By default, preserve reduce-only trigger protection orders.
    Returns number of orders cancelled.
    """
    if not hl_enabled:
        return 0
    try:
        if get_hl_open_orders is not None:
            open_orders = get_hl_open_orders()
        else:
            open_orders = hl_post("info", {"type": "openOrders", "user": hl_wallet_address})
        symbol = coins.get(coin, {}).get("hl_symbol", coin)

        def _is_protection_order(order: dict) -> bool:
            if not bool(order.get("reduceOnly", order.get("reduce_only", False))):
                return False
            trigger = order.get("orderType", {}).get("trigger") or order.get("trigger") or {}
            return bool(trigger)

        to_cancel = []
        for order in open_orders:
            if order.get("coin") != symbol:
                continue
            if not cancel_protection and _is_protection_order(order):
                continue
            oid = order.get("oid")
            if oid is None:
                continue
            to_cancel.append({"coin": symbol, "oid": oid})
        if not to_cancel:
            return 0
        exchange = hl_exchange_factory()
        exchange.bulk_cancel(to_cancel)
        return len(to_cancel)
    except Exception as exc:
        printer(fore.YELLOW + f"  Warning: could not cancel open orders for {coin}: {exc}")
        return 0


def execute_trade(
    *,
    coin: str,
    side: str,
    size: float,
    risk_manager,
    vol_regime: str,
    kc_mid: float,
    signal_price: float | None = None,
    ai_confidence: float | None,
    entry_tags: dict | None,
    coins: dict,
    stop_loss_pct: float,
    take_profit_pct: float,
    hl_enabled: bool,
    testnet: bool,
    hl_leverage: float,
    hl_max_position_usd: float,
    get_hl_price,
    get_indicator_price,
    get_hl_mark_oracle,
    hl_exchange_factory,
    get_hl_open_orders,
    sync_local_positions_with_hl,
    notify_trade_open,
    printer=print,
    fore=None,
    style=None,
    quiet: bool = False,
    return_result: bool = False,
):
    def _finish(success: bool, *, status: str, reason: str = "", fill_price: float | None = None):
        payload = {
            "success": success,
            "status": status,
            "reason": reason,
            "fill_price": fill_price,
        }
        return payload if return_result else success

    coin_cfg = coins.get(coin)
    if not coin_cfg:
        if not quiet:
            printer(fore.RED + f"  Unknown coin: {coin}")
        return _finish(False, status="skip", reason="unknown coin")

    allowed, reason = risk_manager.can_open_position(coin)
    if not allowed:
        if not quiet:
            printer(fore.YELLOW + f"  Trade blocked: {reason}")
        return _finish(False, status="skip", reason=reason)

    price = get_hl_price(coin) if hl_enabled else None
    if not price and not hl_enabled:
        indicator_data = get_indicator_price(coin, coin_cfg)
        price = indicator_data["price"] if indicator_data else None
    if not price:
        if not quiet:
            printer(fore.RED + f"  Cannot get price for {coin} — aborting")
        return _finish(False, status="skip", reason="no price")

    sl_pct = coin_cfg.get("stop_loss_pct", stop_loss_pct)
    tp_pct = coin_cfg.get("take_profit_pct", take_profit_pct)

    tp_price: float | None = None
    if kc_mid > 0 and price > 0:
        if side == "long":
            tp_mid_dist = max(kc_mid - price, 0.0)
            if tp_mid_dist >= price * tp_pct:
                tp_price = kc_mid
        else:
            tp_mid_dist = max(price - kc_mid, 0.0)
            if tp_mid_dist >= price * tp_pct:
                tp_price = kc_mid

    sizing = risk_manager.calculate_position(
        price,
        vol_regime=vol_regime,
        coin=coin,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        tp_price=tp_price,
        ai_confidence=ai_confidence,
    )
    mode_label = ("TESTNET" if testnet else fore.RED + "MAINNET" + style.RESET_ALL) if hl_enabled else "PAPER"

    if DEBUG_MODE and not quiet:
        printer(f"\n  {fore.CYAN}Executing {side.upper()} {coin}  [{mode_label}]")
        sl_pct_ = coin_cfg.get("stop_loss_pct", stop_loss_pct)
        tp_pct_ = coin_cfg.get("take_profit_pct", take_profit_pct)
        if side == "long":
            display_sl = round(price * (1 - sl_pct_), 4)
            display_tp = sizing.get("tp_price") or round(price * (1 + tp_pct_), 4)
        else:
            display_sl = round(price * (1 + sl_pct_), 4)
            display_tp = sizing.get("tp_price") or round(price * (1 - tp_pct_), 4)
        printer(f"  Price: ${price:,.4f}  Size: {sizing['size_units']} units (${sizing['size_usd']:.2f})")
        printer(f"  SL:    ${display_sl:,.4f}  TP: ${display_tp:,.4f}")
        kelly_str = f"  kelly={sizing['kelly_mult']:.2f}×" if abs(sizing.get("kelly_mult", 1.0) - 1.0) > 0.01 else ""
        printer(
            f"  Risk:  ${sizing['risk_amount']:.2f} ({sizing['risk_amount']/risk_manager.state['capital']*100:.1f}%)"
            f"  vol_scalar={sizing['vol_scalar']:.2f}  corr_scalar={sizing['corr_scalar']:.2f}{kelly_str}"
        )

    if hl_enabled:
        try:
            allowed, guard_reason = _oracle_execution_guard(
                coin=coin_cfg["hl_symbol"],
                get_hl_mark_oracle=get_hl_mark_oracle,
                printer=printer,
                fore=fore,
                quiet=quiet,
            )
            if not allowed:
                return _finish(False, status="skip", reason=guard_reason)
            exchange = hl_exchange_factory()
            asset_id = coin_cfg.get("asset_id")
            _debug_print(
                DEBUG_MODE,
                printer,
                fore.CYAN +
                f"  HL asset check: coin={coin} symbol={coin_cfg['hl_symbol']} asset_id={asset_id}"
            )
            if not isinstance(asset_id, int) or asset_id <= 0:
                if not quiet:
                    printer(fore.RED + f"  Invalid stored HL asset id for {coin} ({coin_cfg['hl_symbol']}): {asset_id}")
                return _finish(False, status="skip", reason="invalid asset")
            raw_book = _raw_top_of_book(exchange, coin_cfg["hl_symbol"])
            _debug_print(DEBUG_MODE, printer, fore.CYAN + f"  HL raw book: {_format_payload(raw_book)}")
            best_bid, best_ask = _top_of_book(exchange, coin_cfg["hl_symbol"])
            if best_bid is None or best_ask is None:
                if not quiet:
                    printer(fore.RED + f"  Missing HL bid/ask for {coin_cfg['hl_symbol']} — aborting")
                return _finish(False, status="skip", reason="no price")
            book_mid = (best_bid + best_ask) / 2.0
            signal_ref = float(signal_price if signal_price is not None else price)
            divergence = abs(signal_ref - book_mid) / max(book_mid, 1e-8)
            _debug_print(
                DEBUG_MODE,
                printer,
                fore.CYAN +
                f"  HL signal check: best_bid={best_bid:.6f} best_ask={best_ask:.6f} "
                f"mid={book_mid:.6f} signal_price={signal_ref:.6f} divergence={divergence:.4%}"
            )
            if divergence > 0.01:
                if not quiet:
                    printer(fore.RED + f"  Signal price diverges from HL mid by {divergence:.4%} — aborting {coin}")
                return _finish(False, status="skip", reason=f"price mismatch {divergence:.1%}")
            leverage = coin_cfg.get("hl_leverage", hl_leverage)
            lev_result = exchange.update_leverage(leverage, coin_cfg["hl_symbol"], is_cross=True)
            if lev_result and lev_result.get("status") != "ok":
                printer(fore.YELLOW + f"  Leverage set warning: {lev_result}")
            kelly_mult = sizing.get("kelly_mult", 1.0)
            target_usd = min(sizing.get("size_usd", 0) * kelly_mult, hl_max_position_usd)
            target_sz = target_usd / price
            min_sz = float(size or coin_cfg["hl_size"])
            hl_sz = max(target_sz, min_sz)
            sz_dec = coin_cfg.get("sz_decimals", 3)
            if sz_dec == 0:
                hl_sz = int(math.floor(hl_sz))
            else:
                hl_sz = round(hl_sz, sz_dec)

            def _attempt_market_open(*, px, slippage, label):
                request_payload = {
                    "coin": coin_cfg["hl_symbol"],
                    "asset_id": asset_id,
                    "is_buy": side == "long",
                    "sz": hl_sz,
                    "order_type": label,
                    "slippage": slippage,
                    "px": px,
                    "reduce_only": False,
                }
                _debug_print(
                    DEBUG_MODE,
                    printer,
                    fore.CYAN +
                    f"  HL order attempt: type={label} side={side.upper()} sz={hl_sz} "
                    f"asset={asset_id} symbol={coin_cfg['hl_symbol']} slippage={slippage:.4f}"
                )
                _debug_print(DEBUG_MODE, printer, fore.CYAN + f"  HL request ({label}): {_format_payload(request_payload)}")
                result_payload = exchange.market_open(
                    coin_cfg["hl_symbol"],
                    side == "long",
                    hl_sz,
                    px=px,
                    slippage=slippage,
                )
                _debug_print(DEBUG_MODE, printer, fore.CYAN + f"  HL response ({label}): {_format_payload(result_payload)}")
                return result_payload, _first_status(result_payload)

            def _attempt_direct_market_fallback():
                best_bid, best_ask = _top_of_book(exchange, coin_cfg["hl_symbol"])
                expected_px = best_ask if side == "long" else best_bid
                if expected_px is None:
                    printer(fore.RED + f"  No top-of-book available for {coin_cfg['hl_symbol']} — aborting market fallback")
                    return {"status": "error", "error": "no_top_of_book"}, {}, None, best_bid, best_ask
                spread = (best_ask - best_bid) / best_ask if best_bid and best_ask else None
                _debug_print(
                    DEBUG_MODE,
                    printer,
                    fore.CYAN +
                    f"  HL book: best_bid={best_bid} best_ask={best_ask} "
                    f"spread={spread:.4%}" if spread is not None else
                    fore.CYAN + f"  HL book: best_bid={best_bid} best_ask={best_ask} spread=n/a"
                )
                if spread is None or spread <= 0 or spread > 0.05:
                    printer(fore.RED + f"  Invalid/wide spread for {coin_cfg['hl_symbol']} — aborting market fallback")
                    return {"status": "error", "error": "bad_spread"}, {}, expected_px, best_bid, best_ask
                decimals = _tick_decimals(exchange, asset_id)
                tick_size = _tick_size(exchange, asset_id)
                raw_px = best_ask if side == "long" else best_bid
                limit_px = _align_price_to_tick(raw_px, tick_size, decimals, is_buy=(side == "long"))
                order_type = {"limit": {"tif": "Ioc"}}
                request_payload = {
                    "coin": coin_cfg["hl_symbol"],
                    "asset_id": asset_id,
                    "is_buy": side == "long",
                    "sz": hl_sz,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread": spread,
                    "tick_size": tick_size,
                    "limit_px": limit_px,
                    "order_type": order_type,
                    "reduce_only": False,
                    "fallback": "book_ioc_cross",
                }
                _debug_print(
                    DEBUG_MODE,
                    printer,
                    fore.CYAN +
                    f"  HL order attempt: type=market side={side.upper()} sz={hl_sz} "
                    f"asset={asset_id} symbol={coin_cfg['hl_symbol']} reduce_only=False limit_px={limit_px}"
                )
                _debug_print(DEBUG_MODE, printer, fore.CYAN + f"  HL request (market): {_format_payload(request_payload)}")
                result_payload = exchange.order(
                    coin_cfg["hl_symbol"],
                    side == "long",
                    hl_sz,
                    limit_px,
                    order_type,
                    reduce_only=False,
                )
                _debug_print(DEBUG_MODE, printer, fore.CYAN + f"  HL response (market): {_format_payload(result_payload)}")
                return result_payload, _first_status(result_payload), expected_px, best_bid, best_ask

            result, inner = _attempt_market_open(px=price, slippage=HL_ORDER_SLIPPAGE, label="ioc")
            if "filled" not in inner:
                printer(fore.YELLOW + f"  IOC not filled: {_format_payload(inner)}")
                retry, inner = _attempt_market_open(px=price, slippage=HL_ORDER_RETRY_SLIPPAGE, label="ioc_retry")
                if "filled" not in inner:
                    printer(fore.YELLOW + f"  IOC retry not filled: {_format_payload(inner)}")
                    fallback, inner, expected_px, best_bid, best_ask = _attempt_direct_market_fallback()
                    if fallback.get("status") != "ok" or "filled" not in inner:
                        if not quiet:
                            printer(
                                fore.RED +
                                f"  Order failed after market fallback. "
                                f"request={{side:{side},sz:{hl_sz},asset:{asset_id},symbol:{coin_cfg['hl_symbol']},order_type:market,reduce_only:false}} "
                                f"response={_format_payload(fallback)}"
                            )
                        return _finish(False, status="skip", reason="order failed")
            fill_px = float(inner["filled"].get("avgPx", price))
            fill_sz = float(inner["filled"].get("totalSz", min_sz))
            if 'expected_px' in locals() and expected_px:
                fill_slippage = abs(fill_px - expected_px) / expected_px
                _debug_print(
                    DEBUG_MODE,
                    printer,
                    fore.CYAN + f"  HL fill check: best_bid={best_bid} best_ask={best_ask} "
                    f"fill_px={fill_px:.6f} slippage={fill_slippage:.4%}"
                )
                if fill_slippage > HL_MAX_FILL_SLIPPAGE:
                    if not quiet:
                        printer(
                            fore.RED +
                            f"  Fill slippage {fill_slippage:.4%} exceeds guard {HL_MAX_FILL_SLIPPAGE:.2%} — closing immediately"
                        )
                    try:
                        close_result = exchange.market_close(
                            coin_cfg["hl_symbol"],
                            sz=fill_sz,
                            slippage=HL_ORDER_RETRY_SLIPPAGE,
                        )
                        printer(fore.RED + f"  HL close response (slippage guard): {_format_payload(close_result)}")
                    except Exception as exc:
                        printer(fore.RED + f"  Failed to close slippage-guarded fill: {exc}")
                    return _finish(False, status="skip", reason="slippage guard")
            if not quiet:
                printer(fore.GREEN + f"  Order filled ✓  avg_px=${fill_px:,.4f}  sz={fill_sz}")
            sizing = dict(sizing)
            sizing["size_units"] = fill_sz
            sizing["size_usd"] = round(fill_sz * fill_px, 2)
            price = fill_px

            close_is_buy = (side == "short")
            native_sl = None
            native_tp = None
            if sl_pct and sl_pct > 0:
                native_sl = round(fill_px * (1 + sl_pct), 4) if side == "short" else round(fill_px * (1 - sl_pct), 4)
            else:
                printer(fore.YELLOW + "  Warning: stop-loss pct missing/invalid — skipping native SL override")
            if sizing.get("tp_price"):
                native_tp = round(float(sizing["tp_price"]), 4)
            elif tp_pct and tp_pct > 0:
                native_tp = round(fill_px * (1 - tp_pct), 4) if side == "short" else round(fill_px * (1 + tp_pct), 4)
            else:
                printer(fore.YELLOW + "  Warning: take-profit pct missing/invalid — skipping native TP override")

            if native_sl is not None and native_tp is not None and side == "long":
                if native_sl >= fill_px:
                    native_sl = round(fill_px * (1 - sl_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted SL for long: ${native_sl}")
                if native_tp <= fill_px:
                    native_tp = round(fill_px * (1 + tp_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted TP for long: ${native_tp}")
            elif native_sl is not None and native_tp is not None:
                if native_sl <= fill_px:
                    native_sl = round(fill_px * (1 + sl_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted SL for short: ${native_sl}")
                if native_tp >= fill_px:
                    native_tp = round(fill_px * (1 - tp_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted TP for short: ${native_tp}")

            try:
                if native_sl is None or native_tp is None:
                    raise ValueError("native TP/SL skipped due to missing SL/TP inputs")
                placement = _place_verified_tpsl(
                    exchange=exchange,
                    symbol=coin_cfg["hl_symbol"],
                    asset_id=asset_id,
                    side=side,
                    entry_price=fill_px,
                    size_units=fill_sz,
                    stop_loss=native_sl,
                    take_profit=native_tp,
                    coin=coin_cfg["hl_symbol"],
                    get_hl_mark_oracle=get_hl_mark_oracle,
                    get_hl_open_orders=get_hl_open_orders,
                    printer=printer,
                    fore=fore,
                )
                if placement.get("confirmed"):
                    native_sl = float(placement.get("stop_loss") or native_sl)
                    native_tp = float(placement.get("take_profit") or native_tp)
                    if not quiet:
                        printer(fore.GREEN + f"  ✅ Native SL @ ${native_sl:,.4f}  TP @ ${native_tp:,.4f}  ✓")
                        printer(fore.GREEN + "  🛡️  Position protected - orders confirmed on Hyperliquid")
                else:
                    for attempt in placement.get("attempts", []):
                        if attempt.get("error") and not quiet:
                            printer(fore.RED + f"  HL {attempt['tpsl'].upper()} response: {_format_payload(attempt.get('response'))}")
                    if not quiet:
                        printer(fore.RED + f"  CRITICAL: SL/TP placement failed for {coin_cfg['hl_symbol']}")
            except Exception as tp_err:
                if not quiet:
                    printer(fore.RED + f"  ❌ Critical error placing native TP/SL: {tp_err}")
                if native_sl is not None and native_tp is not None:
                    if not quiet:
                        traceback.print_exc()
                        printer(fore.RED + "  🚨 POSITION NOT PROTECTED - Monitor manually!")
                        printer(fore.RED + "  💡 Consider setting TP/SL manually on Hyperliquid interface")
        except Exception as exc:
            if not quiet:
                printer(fore.RED + f"  Execution error: {exc}")
                traceback.print_exc()
            return _finish(False, status="skip", reason="execution error")

    if hl_enabled:
        sync_local_positions_with_hl(
            risk_manager,
            only_coin=coin,
            print_fn=printer,
            fore=fore,
        )
    else:
        risk_manager.open_position(coin, side, price, sizing, entry_tags=entry_tags)

    stored = risk_manager.state["positions"].get(coin, {})
    if not stored and hl_enabled:
        sizing = dict(sizing)
        sizing["size_units"] = fill_sz if 'fill_sz' in locals() else sizing.get("size_units")
        sizing["size_usd"] = round((fill_sz if 'fill_sz' in locals() else sizing.get("size_units", 0)) * price, 2)
        risk_manager.open_position(coin, side, price, sizing, entry_tags=entry_tags)
        sync_local_positions_with_hl(
            risk_manager,
            only_coin=coin,
            print_fn=printer,
            fore=fore,
        )
        stored = risk_manager.state["positions"].get(coin, {})

    notify_trade_open(
        coin,
        side,
        stored.get("entry_price", price),
        stored.get("size_usd", sizing["size_usd"]),
        stored.get("stop_loss", sizing["stop_loss"]),
        stored.get("take_profit", sizing["take_profit"]),
    )
    if not quiet:
        printer(fore.GREEN + "  Position recorded ✓")
    return _finish(True, status="filled", fill_price=price)


def close_trade(
    *,
    coin: str,
    risk_manager,
    reason: str,
    coins: dict,
    hl_enabled: bool,
    get_hl_price,
    get_indicator_price,
    get_hl_mark_oracle,
    cancel_open_orders_fn,
    hl_exchange_factory,
    notify_trade_close,
    log_trade,
    printer=print,
    fore=None,
    style=None,
) -> bool:
    """Close an open position for a coin."""
    pos_data = risk_manager.state.get("positions", {}).get(coin)
    if not pos_data:
        printer(fore.YELLOW + f"  No open position for {coin}")
        return False

    coin_cfg = coins.get(coin)
    price = get_hl_price(coin) if hl_enabled else None
    if not price:
        indicator_data = get_indicator_price(coin, coin_cfg) if coin_cfg else None
        price = indicator_data["price"] if indicator_data else None
    if not price:
        printer(fore.RED + f"  Cannot get exit price for {coin}")
        return False

    if hl_enabled:
        try:
            allowed, _guard_reason = _oracle_execution_guard(
                coin=coin_cfg["hl_symbol"],
                get_hl_mark_oracle=get_hl_mark_oracle,
                printer=printer,
                fore=fore,
            )
            if not allowed:
                return False
            exchange = hl_exchange_factory()
            result = exchange.market_close(coin_cfg["hl_symbol"])
            if result is None:
                printer(fore.YELLOW + f"  HL position already closed (native SL/TP fired) — syncing state.")
            elif result.get("status") != "ok":
                printer(fore.RED + f"  Close order failed: {result}")
                return False
        except Exception as exc:
            printer(fore.RED + f"  Close error: {exc}")
            traceback.print_exc()
            return False
        cancelled = cancel_open_orders_fn(coin, cancel_protection=True)
        if cancelled:
            printer(fore.CYAN + f"  Cancelled {cancelled} open order(s) for {coin} ✓")

    saved_pos = dict(pos_data)
    saved_pos["coin"] = coin

    summary = risk_manager.close_position(coin, price)
    pnl = summary.get("pnl", 0)
    gross_pnl = summary.get("gross_pnl", pnl)
    fees = summary.get("fees", 0.0)

    log_trade(saved_pos, price, pnl, reason, risk_manager.state["capital"], gross_pnl=gross_pnl, fees=fees)
    notify_trade_close(coin, saved_pos["side"], saved_pos["entry_price"], price, pnl, reason)

    pnl_color = fore.GREEN if pnl >= 0 else fore.RED
    fee_str = f"  {fore.YELLOW}(fees: ${fees:.4f}){style.RESET_ALL}" if fees else ""
    printer(f"\n  {fore.CYAN}Closed {coin}  [{reason}]")
    printer(f"  Entry: ${summary['entry_price']:,.4f}  Exit: ${summary['exit_price']:,.4f}")
    printer(f"  P&L:   {pnl_color}${pnl:+,.2f} ({summary['pnl_pct']:+.2f}%){style.RESET_ALL}{fee_str}")
    return True
