"""Execution service helpers extracted from trader.py."""
from __future__ import annotations

import math
import traceback


def cancel_open_orders(
    *,
    coin: str,
    hl_enabled: bool,
    hl_wallet_address: str,
    coins: dict,
    hl_post,
    hl_exchange_factory,
    printer=print,
    fore=None,
) -> int:
    """
    Cancel all open orders for a coin on HL (clears orphaned TP/SL triggers).
    Called by close_trade() so native orders don't outlive the position.
    Returns number of orders cancelled.
    """
    if not hl_enabled:
        return 0
    try:
        open_orders = hl_post("info", {"type": "openOrders", "user": hl_wallet_address})
        symbol = coins.get(coin, {}).get("hl_symbol", coin)
        to_cancel = [{"coin": symbol, "oid": order["oid"]}
                     for order in open_orders if order.get("coin") == symbol]
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
    ai_confidence: float | None,
    coins: dict,
    stop_loss_pct: float,
    take_profit_pct: float,
    hl_enabled: bool,
    testnet: bool,
    hl_leverage: float,
    hl_max_position_usd: float,
    get_hl_price,
    get_indicator_price,
    hl_exchange_factory,
    notify_trade_open,
    printer=print,
    fore=None,
    style=None,
) -> bool:
    coin_cfg = coins.get(coin)
    if not coin_cfg:
        printer(fore.RED + f"  Unknown coin: {coin}")
        return False

    allowed, reason = risk_manager.can_open_position(coin)
    if not allowed:
        printer(fore.YELLOW + f"  Trade blocked: {reason}")
        return False

    price = get_hl_price(coin) if hl_enabled else None
    if not price:
        indicator_data = get_indicator_price(coin, coin_cfg)
        price = indicator_data["price"] if indicator_data else None
    if not price:
        printer(fore.RED + f"  Cannot get price for {coin} — aborting")
        return False

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
            exchange = hl_exchange_factory()
            leverage = coin_cfg.get("hl_leverage", hl_leverage)
            lev_result = exchange.update_leverage(leverage, coin_cfg["hl_symbol"], is_cross=True)
            if lev_result and lev_result.get("status") != "ok":
                printer(fore.YELLOW + f"  Leverage set warning: {lev_result}")
            kelly_mult = sizing.get("kelly_mult", 1.0)
            target_usd = min(sizing.get("size_usd", 0) * kelly_mult, hl_max_position_usd)
            target_sz = target_usd / price
            hl_sz = max(target_sz, coin_cfg["hl_size"])
            sz_dec = coin_cfg.get("sz_decimals", 3)
            if sz_dec == 0:
                hl_sz = int(math.floor(hl_sz))
            else:
                hl_sz = round(hl_sz, sz_dec)
            result = exchange.market_open(coin_cfg["hl_symbol"], side == "long", hl_sz, px=price, slippage=0.03)
            if result.get("status") != "ok":
                printer(fore.RED + f"  Order failed: {result}")
                return False
            try:
                inner = result["response"]["data"]["statuses"][0]
            except (KeyError, IndexError, TypeError):
                inner = {}
            if "filled" not in inner:
                printer(fore.RED + f"  Order not filled (IoC cancelled): {inner}")
                printer(fore.YELLOW + "  Tip: slippage too tight or market moved — consider increasing slippage")
                return False
            fill_px = float(inner["filled"].get("avgPx", price))
            fill_sz = float(inner["filled"].get("totalSz", coin_cfg["hl_size"]))
            printer(fore.GREEN + f"  Order filled ✓  avg_px=${fill_px:,.4f}  sz={fill_sz}")
            sizing = dict(sizing)
            sizing["size_units"] = fill_sz
            sizing["size_usd"] = round(fill_sz * fill_px, 2)
            price = fill_px

            close_is_buy = (side == "short")
            stored_pos = risk_manager.state["positions"].get(coin, {})
            native_sl = stored_pos.get("stop_loss", fill_px * (1 + _sl_pct if side == "short" else 1 - _sl_pct))
            native_tp = stored_pos.get("take_profit", fill_px * (1 - _tp_pct if side == "short" else 1 + _tp_pct))

            if side == "long":
                if native_sl >= fill_px:
                    native_sl = round(fill_px * (1 - _sl_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted SL for long: ${native_sl}")
                if native_tp <= fill_px:
                    native_tp = round(fill_px * (1 + _tp_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted TP for long: ${native_tp}")
            else:
                if native_sl <= fill_px:
                    native_sl = round(fill_px * (1 + _sl_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted SL for short: ${native_sl}")
                if native_tp >= fill_px:
                    native_tp = round(fill_px * (1 - _tp_pct), 4)
                    printer(fore.YELLOW + f"  Adjusted TP for short: ${native_tp}")

            try:
                tpsl_slippage = 0.02
                if close_is_buy:
                    sl_limit = round(native_sl * (1 + tpsl_slippage), 4)
                    tp_limit = round(native_tp * (1 + tpsl_slippage), 4)
                else:
                    sl_limit = round(native_sl * (1 - tpsl_slippage), 4)
                    tp_limit = round(native_tp * (1 - tpsl_slippage), 4)

                tpsl_orders = [
                    {
                        "coin": coin_cfg["hl_symbol"],
                        "is_buy": close_is_buy,
                        "sz": fill_sz,
                        "limit_px": sl_limit,
                        "reduce_only": True,
                        "order_type": {
                            "trigger": {
                                "triggerPx": native_sl,
                                "isMarket": True,
                                "tpsl": "sl"
                            }
                        }
                    },
                    {
                        "coin": coin_cfg["hl_symbol"],
                        "is_buy": close_is_buy,
                        "sz": fill_sz,
                        "limit_px": tp_limit,
                        "reduce_only": True,
                        "order_type": {
                            "trigger": {
                                "triggerPx": native_tp,
                                "isMarket": True,
                                "tpsl": "tp"
                            }
                        }
                    }
                ]

                printer(fore.CYAN + "  Placing native TP/SL orders on Hyperliquid...")
                printer(fore.CYAN + f"    SL: ${native_sl:,.4f} (limit: ${sl_limit:,.4f})")
                printer(fore.CYAN + f"    TP: ${native_tp:,.4f} (limit: ${tp_limit:,.4f})")
                printer(fore.CYAN + f"    Size: {fill_sz} units, Side: {'BUY' if close_is_buy else 'SELL'}")

                tpsl_result = exchange.bulk_orders(tpsl_orders, grouping="positionTpsl")

                if tpsl_result and tpsl_result.get("status") == "ok":
                    printer(fore.GREEN + f"  ✅ Native SL @ ${native_sl:,.4f}  TP @ ${native_tp:,.4f}  ✓")
                    printer(fore.GREEN + "  🛡️  Position protected - orders will execute even if bot disconnects!")
                else:
                    printer(fore.RED + f"  ❌ Native TP/SL failed: {tpsl_result}")
                    printer(fore.YELLOW + "  ⚠️  Bot will still monitor locally — manual monitoring required")
            except Exception as tp_err:
                printer(fore.RED + f"  ❌ Critical error placing native TP/SL: {tp_err}")
                traceback.print_exc()
                printer(fore.RED + "  🚨 POSITION NOT PROTECTED - Monitor manually!")
                printer(fore.RED + "  💡 Consider setting TP/SL manually on Hyperliquid interface")
        except Exception as exc:
            printer(fore.RED + f"  Execution error: {exc}")
            traceback.print_exc()
            return False

    risk_manager.open_position(coin, side, price, sizing)
    stored = risk_manager.state["positions"].get(coin, {})
    notify_trade_open(
        coin,
        side,
        price,
        sizing["size_usd"],
        stored.get("stop_loss", sizing["stop_loss"]),
        stored.get("take_profit", sizing["take_profit"]),
    )
    printer(fore.GREEN + "  Position recorded ✓")
    return True


def close_trade(
    *,
    coin: str,
    risk_manager,
    reason: str,
    coins: dict,
    hl_enabled: bool,
    get_hl_price,
    get_indicator_price,
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

    cancelled = cancel_open_orders_fn(coin)
    if cancelled:
        printer(fore.CYAN + f"  Cancelled {cancelled} open order(s) for {coin} ✓")

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
