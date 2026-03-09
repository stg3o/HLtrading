"""
trader.py — trade execution layer
Handles both paper trading and live Hyperliquid trading.
Never makes decisions — only executes what risk_manager approves.
"""
import json
import traceback
import urllib.request
from colorama import Fore, Style
from config import (TESTNET, HL_ENABLED, HL_WALLET_ADDRESS, HL_PRIVATE_KEY,
                    COINS, STOP_LOSS_PCT, TAKE_PROFIT_PCT, HL_MAX_POSITION_USD)
from risk_manager import RiskManager


# ── HYPERLIQUID DIRECT API ─────────────────────────────────────────────────────

def _hl_post(endpoint: str, payload: dict):
    """Direct HTTP call to Hyperliquid REST API — bypasses broken SDK Info class."""
    from hyperliquid.utils import constants
    base = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL
    url  = base.rstrip("/") + "/" + endpoint.lstrip("/")
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


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


def get_hl_price(coin: str) -> float | None:
    """Fetch current mid price via direct API — no SDK Info needed."""
    try:
        mids = _hl_post("info", {"type": "allMids"})
        val  = mids.get(coin)
        return float(val) if val else None
    except Exception as e:
        print(Fore.RED + f"  Price fetch error ({coin}): {e}")
        return None


def get_hl_obi(coin: str, levels: int = 10) -> float | None:
    """
    Order Book Imbalance for top `levels` of the HL L2 book.
    OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol), range [-1, +1].
      +1 = pure bid pressure (buyers dominating)
      -1 = pure ask pressure (sellers dominating)
    Returns None on any fetch/parse error — caller should treat as neutral.
    """
    try:
        book   = _hl_post("info", {"type": "l2Book", "coin": coin})
        bids   = book.get("levels", [[], []])[0][:levels]
        asks   = book.get("levels", [[], []])[1][:levels]
        bid_vol = sum(float(b["sz"]) for b in bids)
        ask_vol = sum(float(a["sz"]) for a in asks)
        total   = bid_vol + ask_vol
        if total == 0:
            return None
        return (bid_vol - ask_vol) / total
    except Exception:
        return None


def cancel_open_orders(coin: str) -> int:
    """
    Cancel all open orders for a coin on HL (clears orphaned TP/SL triggers).
    Called by close_trade() so native orders don't outlive the position.
    Returns number of orders cancelled.
    """
    if not HL_ENABLED:
        return 0
    try:
        open_orders = _hl_post("info", {"type": "openOrders", "user": HL_WALLET_ADDRESS})
        symbol      = COINS.get(coin, {}).get("hl_symbol", coin)
        to_cancel   = [{"coin": symbol, "oid": o["oid"]}
                       for o in open_orders if o.get("coin") == symbol]
        if not to_cancel:
            return 0
        exchange = _hl_exchange()
        exchange.bulk_cancel(to_cancel)
        return len(to_cancel)
    except Exception as e:
        print(Fore.YELLOW + f"  Warning: could not cancel open orders for {coin}: {e}")
        return 0


def get_hl_positions() -> list:
    """Fetch open perps positions via direct API."""
    try:
        state = _hl_post("info", {"type": "clearinghouseState", "user": HL_WALLET_ADDRESS})
        return state.get("assetPositions", [])
    except Exception as e:
        print(Fore.RED + f"  Position fetch error: {e}")
        return []


def get_hl_account_info() -> dict:
    """Fetch unified account info (perps equity + spot USDC)."""
    try:
        perps  = _hl_post("info", {"type": "clearinghouseState", "user": HL_WALLET_ADDRESS})
        margin = perps.get("crossMarginSummary") or perps.get("marginSummary") or {}

        spot      = _hl_post("info", {"type": "spotClearinghouseState", "user": HL_WALLET_ADDRESS})
        spot_usdc = sum(
            float(b["total"]) for b in spot.get("balances", [])
            if b.get("coin") == "USDC"
        )
        perps_equity = float(margin.get("accountValue", 0))
        withdrawable = float(perps.get("withdrawable", 0))

        return {
            "account_value": perps_equity + spot_usdc,
            "perps_equity":  perps_equity,
            "spot_usdc":     spot_usdc,
            "margin_used":   float(margin.get("totalMarginUsed", 0)),
            "withdrawable":  withdrawable + spot_usdc,
            "positions":     perps.get("assetPositions", []),
            "spot_balances": spot.get("balances", []),
        }
    except Exception as e:
        print(Fore.RED + f"  Account info error: {e}")
        return {}


# ── TRADE EXECUTION ────────────────────────────────────────────────────────────

def execute_trade(coin: str, side: str, size: float, risk_manager: RiskManager,
                  vol_regime: str = "normal",
                  kc_mid: float = 0.0,
                  ai_confidence: float | None = None) -> bool:
    """
    Execute a trade. Checks risk_manager before doing anything.
    Returns True if trade was placed (paper or live), False otherwise.
    vol_regime: 'high' | 'normal' | 'low' — adjusts position size automatically.
    kc_mid: KC midline price at signal time, used as TP target (same logic as
            backtester). Falls back to fixed take_profit_pct if not provided or
            midline is too close / on the wrong side of entry.
    """
    from notifier import notify_trade_open

    coin_cfg = COINS.get(coin)
    if not coin_cfg:
        print(Fore.RED + f"  Unknown coin: {coin}")
        return False

    allowed, reason = risk_manager.can_open_position(coin)
    if not allowed:
        print(Fore.YELLOW + f"  Trade blocked: {reason}")
        return False

    # Get current price
    price = get_hl_price(coin) if HL_ENABLED else None
    if not price:
        from strategy import get_indicators_for_coin
        ind   = get_indicators_for_coin(coin, coin_cfg)
        price = ind["price"] if ind else None
    if not price:
        print(Fore.RED + f"  Cannot get price for {coin} — aborting")
        return False

    sl_pct = coin_cfg.get("stop_loss_pct",   STOP_LOSS_PCT)
    tp_pct = coin_cfg.get("take_profit_pct", TAKE_PROFIT_PCT)

    # ── TP target: KC midline (same fallback logic as backtester) ─────────────
    # Use kc_mid if it's at least tp_pct away from entry on the correct side.
    # Otherwise fall back to fixed-% TP (tp_price=None → calculate_position
    # computes it from tp_pct as usual).
    tp_price: float | None = None
    if kc_mid > 0 and price > 0:
        if side == "long":
            tp_mid_dist = max(kc_mid - price, 0.0)
            if tp_mid_dist >= price * tp_pct:
                tp_price = kc_mid
        else:  # short
            tp_mid_dist = max(price - kc_mid, 0.0)
            if tp_mid_dist >= price * tp_pct:
                tp_price = kc_mid

    sizing = risk_manager.calculate_position(price, vol_regime=vol_regime, coin=coin,
                                             sl_pct=sl_pct, tp_pct=tp_pct,
                                             tp_price=tp_price,
                                             ai_confidence=ai_confidence)
    mode_label = ("TESTNET" if TESTNET else Fore.RED + "MAINNET" + Style.RESET_ALL) if HL_ENABLED else "PAPER"

    print(f"\n  {Fore.CYAN}Executing {side.upper()} {coin}  [{mode_label}]")
    # Derive correct display SL/TP for the actual side
    # (calculate_position always returns long-formula values; open_position corrects them)
    sl_pct_ = coin_cfg.get("stop_loss_pct", STOP_LOSS_PCT)
    tp_pct_ = coin_cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
    if side == "long":
        display_sl = round(price * (1 - sl_pct_), 4)
        display_tp = sizing.get("tp_price") or round(price * (1 + tp_pct_), 4)
    else:
        display_sl = round(price * (1 + sl_pct_), 4)
        display_tp = sizing.get("tp_price") or round(price * (1 - tp_pct_), 4)
    print(f"  Price: ${price:,.4f}  Size: {sizing['size_units']} units (${sizing['size_usd']:.2f})")
    print(f"  SL:    ${display_sl:,.4f}  TP: ${display_tp:,.4f}")
    kelly_str = f"  kelly={sizing['kelly_mult']:.2f}×" if abs(sizing.get("kelly_mult", 1.0) - 1.0) > 0.01 else ""
    print(f"  Risk:  ${sizing['risk_amount']:.2f} ({sizing['risk_amount']/risk_manager.state['capital']*100:.1f}%)"
          f"  vol_scalar={sizing['vol_scalar']:.2f}  corr_scalar={sizing['corr_scalar']:.2f}{kelly_str}")

    if HL_ENABLED:
        try:
            exchange = _hl_exchange()
            # ── Dynamic HL position sizing ─────────────────────────────────────
            # Derive order size from risk_manager output (sizing["size_usd"]) scaled
            # by Kelly multiplier, then:
            #   1. Cap at HL_MAX_POSITION_USD (e.g. $200) — prevents over-leveraging
            #   2. Floor at coin_cfg["hl_size"] — satisfies HL's $10 minimum order
            # Previously hl_size was the only driver; now it is only the floor.
            kelly_mult  = sizing.get("kelly_mult", 1.0)
            target_usd  = min(sizing.get("size_usd", 0) * kelly_mult, HL_MAX_POSITION_USD)
            target_sz   = target_usd / price
            hl_sz       = max(target_sz, coin_cfg["hl_size"])  # never below HL minimum
            hl_sz       = round(hl_sz, 3)                      # 3dp precision (HL accepts)
            result   = exchange.market_open(coin_cfg["hl_symbol"], side == "long",
                                            hl_sz, px=price, slippage=0.03)
            if result.get("status") != "ok":
                print(Fore.RED + f"  Order failed: {result}")
                return False
            # market_open is an IoC limit — "ok" means received, not necessarily filled.
            # Check the inner fill status: statuses[0] must be {"filled": {...}}.
            try:
                inner = result["response"]["data"]["statuses"][0]
            except (KeyError, IndexError, TypeError):
                inner = {}
            if "filled" not in inner:
                # Could be {"error": "..."} or {"cancelled": {...}} — order did not fill
                print(Fore.RED + f"  Order not filled (IoC cancelled): {inner}")
                print(Fore.YELLOW + "  Tip: slippage too tight or market moved — consider increasing slippage")
                return False
            fill_px  = float(inner["filled"].get("avgPx", price))
            fill_sz  = float(inner["filled"].get("totalSz", coin_cfg["hl_size"]))
            print(Fore.GREEN + f"  Order filled ✓  avg_px=${fill_px:,.4f}  sz={fill_sz}")
            # Reconcile sizing with what actually filled on HL.
            # sizing['size_units'] is the Kelly-calculated amount; hl_size is what we
            # actually sent. P&L must track the real fill, not the theoretical size.
            sizing = dict(sizing)  # don't mutate original
            sizing["size_units"] = fill_sz
            sizing["size_usd"]   = round(fill_sz * fill_px, 2)
            price = fill_px       # use actual fill price for entry tracking

            # ── Place native TP/SL orders on HL ──────────────────────────────
            # If the bot disconnects, HL will still close the position at our levels.
            # close side: long entry → sell to close; short entry → buy to close
            close_is_buy = (side == "short")
            # Use corrected display SL/TP (already computed above, re-derive from fill)
            _sl_pct = coin_cfg.get("stop_loss_pct",   STOP_LOSS_PCT)
            _tp_pct = coin_cfg.get("take_profit_pct", TAKE_PROFIT_PCT)
            native_sl = round(fill_px * (1 + _sl_pct) if side == "short"
                              else fill_px * (1 - _sl_pct), 4)
            native_tp = sizing.get("tp_price") or (
                round(fill_px * (1 - _tp_pct) if side == "short"
                      else fill_px * (1 + _tp_pct), 4))
            try:
                # HL requires both TP and SL submitted together as bulk_orders with
                # grouping="positionTpsl" for them to appear in the Positions TP/SL column.
                # Two separate order() calls use grouping="na" and show as unlinked
                # trigger orders in Open Orders only — not visible in the position row.
                #
                # limit_px = worst acceptable fill price when triggered (market order):
                #   close_is_buy (short → buy to close): pay up to 5% above trigger
                #   close_is_sell (long → sell to close): accept down to 5% below trigger
                TPSL_SLIPPAGE = 0.05
                if close_is_buy:
                    sl_limit = round(native_sl * (1 + TPSL_SLIPPAGE), 4)
                    tp_limit = round(native_tp * (1 + TPSL_SLIPPAGE), 4)
                else:
                    sl_limit = round(native_sl * (1 - TPSL_SLIPPAGE), 4)
                    tp_limit = round(native_tp * (1 - TPSL_SLIPPAGE), 4)

                tpsl_result = exchange.bulk_orders([
                    {"coin": coin_cfg["hl_symbol"], "is_buy": close_is_buy,
                     "sz": fill_sz, "limit_px": sl_limit, "reduce_only": True,
                     "order_type": {"trigger": {"triggerPx": native_sl,
                                                "isMarket": True, "tpsl": "sl"}}},
                    {"coin": coin_cfg["hl_symbol"], "is_buy": close_is_buy,
                     "sz": fill_sz, "limit_px": tp_limit, "reduce_only": True,
                     "order_type": {"trigger": {"triggerPx": native_tp,
                                                "isMarket": True, "tpsl": "tp"}}},
                ], grouping="positionTpsl")

                ok = tpsl_result.get("status") == "ok"
                if ok:
                    print(Fore.GREEN + f"  Native SL @ ${native_sl:,.4f}  TP @ ${native_tp:,.4f}  ✓")
                else:
                    print(Fore.RED + f"  Native TP/SL failed: {tpsl_result}")
            except Exception as tp_err:
                print(Fore.YELLOW + f"  Warning: native TP/SL placement failed: {tp_err}")
                traceback.print_exc()
                print(Fore.YELLOW + "  Bot will still monitor locally — but restart protection is off")
        except Exception as e:
            print(Fore.RED + f"  Execution error: {e}")
            traceback.print_exc()
            return False

    risk_manager.open_position(coin, side, price, sizing)
    notify_trade_open(coin, side, price, sizing["size_usd"],
                      sizing["stop_loss"], sizing["take_profit"])
    print(Fore.GREEN + "  Position recorded ✓")
    return True


def close_trade(coin: str, risk_manager: RiskManager, reason: str = "manual") -> bool:
    """Close an open position for a coin."""
    from notifier  import notify_trade_close
    from trade_log import log_trade

    pos_data = risk_manager.state.get("positions", {}).get(coin)
    if not pos_data:
        print(Fore.YELLOW + f"  No open position for {coin}")
        return False

    # Cancel any native TP/SL trigger orders before closing.
    # Without this, orphaned reduce_only orders remain on HL and would
    # immediately close the NEXT position opened for the same coin.
    cancelled = cancel_open_orders(coin)
    if cancelled:
        print(Fore.CYAN + f"  Cancelled {cancelled} open order(s) for {coin} ✓")

    coin_cfg = COINS.get(coin)
    price    = get_hl_price(coin) if HL_ENABLED else None
    if not price:
        from strategy import get_indicators_for_coin
        ind   = get_indicators_for_coin(coin, coin_cfg) if coin_cfg else None
        price = ind["price"] if ind else None
    if not price:
        print(Fore.RED + f"  Cannot get exit price for {coin}")
        return False

    if HL_ENABLED:
        try:
            exchange = _hl_exchange()
            result   = exchange.market_close(coin_cfg["hl_symbol"])
            if result.get("status") != "ok":
                print(Fore.RED + f"  Close order failed: {result}")
                return False
        except Exception as e:
            print(Fore.RED + f"  Close error: {e}")
            traceback.print_exc()
            return False

    # Save position data before closing (close_position pops it)
    saved_pos = dict(pos_data)
    saved_pos["coin"] = coin

    summary = risk_manager.close_position(coin, price)
    pnl     = summary.get("pnl", 0)

    # Log to CSV and notify
    log_trade(saved_pos, price, pnl, reason, risk_manager.state["capital"])
    notify_trade_close(coin, saved_pos["side"], saved_pos["entry_price"], price, pnl, reason)

    pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
    print(f"\n  {Fore.CYAN}Closed {coin}  [{reason}]")
    print(f"  Entry: ${summary['entry_price']:,.4f}  Exit: ${summary['exit_price']:,.4f}")
    print(f"  P&L:   {pnl_color}${pnl:+,.2f} ({summary['pnl_pct']:+.2f}%){Style.RESET_ALL}")
    return True


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

        print(f"  {coin:4}  {pos['side'].upper():5}  entry=${pos['entry_price']:,.4f}"
              f"  SL=${pos['stop_loss']:,.4f}  TP=${pos['take_profit']:,.4f}  P&L={pnl_str}")
