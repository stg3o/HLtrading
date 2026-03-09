"""
main.py — trading bot CLI
Full menu with bot lifecycle management, AI advisor, risk controls.
"""
import os
import sys
import time
import threading
import webbrowser
from datetime import datetime
from colorama import Fore, Style, init
init(autoreset=True)

from config import COINS, TESTNET, HL_ENABLED, PAPER_CAPITAL, STOP_LOSS_PCT, MIN_EDGE, MIN_ENTRY_QUALITY, OBI_GATE, VOL_MIN_RATIO
from strategy import get_indicators_for_coin, print_indicators, get_trend_bias
from ai_advisor import get_decision, print_decision
from risk_manager import RiskManager
from trader import execute_trade, close_trade, emergency_close_all, print_positions, get_hl_account_info, get_hl_obi, get_hl_positions
from trade_log import load_trades
from backtester import run_backtest, print_backtest_results, print_trade_list
from optimizer import run_optimizer, run_walk_forward, load_best, print_optimizer_results, apply_best_to_config

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
_bot_thread: threading.Thread | None = None
_monitor_thread: threading.Thread | None = None
_bot_running    = threading.Event()
_risk           = RiskManager()
_night_mode     = False
_live_mode      = False   # False = paper, True = live (requires explicit switch)

BOT_INTERVAL_SEC     = 5 * 60    # scan every 5 minutes — aligned with 5m candle timeframe
MONITOR_INTERVAL_SEC = 15        # SL/TP monitor checks every 15 seconds for scalping


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def _clear():
    os.system("clear" if os.name == "posix" else "cls")


def _pad(label: str, width: int) -> str:
    """Pad a string to width, ignoring invisible ANSI escape codes."""
    import re
    visible_len = len(re.sub(r'\x1b\[[0-9;]*m', '', label))
    return label + " " * max(0, width - visible_len)

def _header():
    mode_str   = (Fore.RED + "⚠  LIVE" if _live_mode else Fore.CYAN + "PAPER") + Style.RESET_ALL
    status_str = (Fore.GREEN + "RUNNING" if _bot_running.is_set() else Fore.YELLOW + "STOPPED") + Style.RESET_ALL
    net_str    = (Fore.RED + "MAINNET" if not TESTNET else Fore.YELLOW + "TESTNET") + Style.RESET_ALL
    bg = Fore.BLACK if _night_mode else ""
    print(bg + Fore.CYAN + "╔══════════════════════════════════════════════╗")
    print(bg + Fore.CYAN + "║   🤖  KELTNER AI TRADING BOT                 ║")
    print(bg + Fore.CYAN + "║   Mode: " + _pad(mode_str, 30) + Fore.CYAN + "║")
    print(bg + Fore.CYAN + "║   Bot:  " + _pad(status_str, 30) + Fore.CYAN + "║")
    print(bg + Fore.CYAN + "║   Net:  " + _pad(net_str, 30)    + Fore.CYAN + "║")
    print(bg + Fore.CYAN + "╚══════════════════════════════════════════════╝" + Style.RESET_ALL)


def _menu():
    print(f"\n  {Fore.WHITE}[1] Start Bot        [2] Stop Bot")
    print(f"  [3] Switch to Live Mode ⚠️   [4] View Open Positions")
    print(f"  [5] Set Capital Allocation  [6] Market Analysis 🔍")
    print(f"  [7] Night Mode 🌙           [8] Open Dashboard in Browser")
    print(f"  [9] Ask the Bot 💬          [10] Backtest 📊")
    print(f"  [11] Performance Report 📈  [12] Optimize Strategy 🔬")
    print(f"  [F] Fetch Historical Data 💾")
    print(f"  {Fore.RED}[E] EMERGENCY STOP 🔴{Style.RESET_ALL}")
    print(f"  [Q] Quit\n")


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _active_coins() -> dict:
    """Return only coins with enabled=True (or no enabled key — defaults to True)."""
    return {c: cfg for c, cfg in COINS.items() if cfg.get("enabled", True)}


def _apply_best_configs() -> None:
    """
    Load per-coin optimizer results from best_configs.json and apply the top
    params (rank-1) into the COINS dict in memory.  Called at bot startup so
    optimizer runs automatically take effect on the next restart — no manual
    config.py edits required.

    Signal-quality params only (rsi, ma_filter, kc_scalar).
    SL/TP are deliberate live-safety choices kept in config.py.
    """
    _APPLY_KEYS = ("rsi_oversold", "rsi_overbought", "ma_trend_filter", "kc_scalar",
                   "st_period", "st_multiplier")
    try:
        best = load_best()   # {coin: [results]}
    except Exception:
        return
    if not best:
        return
    applied = []
    for coin, results in best.items():
        if not results or coin not in COINS:
            continue
        top = results[0]     # rank-1 result
        for key in _APPLY_KEYS:
            if key in top:
                COINS[coin][key] = top[key]
        applied.append(coin)
    if applied:
        print(Fore.CYAN + f"  [optimizer] Applied best signal configs for: {', '.join(applied)}")


# ─── BOT LOOP ─────────────────────────────────────────────────────────────────

def _bot_loop():
    """Background thread: scan coins, get AI advice, execute trades."""
    _apply_best_configs()   # pull latest optimizer results into COINS in-memory
    active = _active_coins()
    coin_list = ", ".join(active) or "none"
    print(Fore.GREEN + f"\n  Bot started — active coins: {coin_list}  "
          f"(scanning every {BOT_INTERVAL_SEC//60}m)")
    while _bot_running.is_set():
        print(f"\n  {Fore.CYAN}[{datetime.now().strftime('%H:%M:%S')}] Scanning…")

        halted, reason = _risk.is_halted()
        if halted:
            print(Fore.RED + f"  Trading halted: {reason}")
            _bot_running.wait(BOT_INTERVAL_SEC)
            continue

        for coin, cfg in active.items():
            if not _bot_running.is_set():
                break

            indicators = get_indicators_for_coin(coin, cfg)
            if not indicators:
                continue

            print_indicators(indicators)

            # Get daily trend bias for multi-timeframe context
            daily_bias = get_trend_bias(coin, cfg)
            if daily_bias["trend"] != "neutral":
                bias_color = Fore.GREEN if daily_bias["trend"] == "bullish" else Fore.RED
                print(f"  Daily bias: {bias_color}{daily_bias['trend'].upper()}{Style.RESET_ALL}"
                      f"  (RSI {daily_bias['rsi']:.1f}, MA {daily_bias['ma_alignment']})")

            # Get AI decision — pass last 20 closed trades so the AI can
            # factor in recent win/loss streak when sizing conviction.
            recent = load_trades()[-20:]
            decision = get_decision(indicators, recent, daily_bias=daily_bias)
            print_decision(decision)

            action        = decision.get("action", "hold")
            confidence    = float(decision.get("confidence", 0.5))
            strategy_type = cfg.get("strategy_type", "mean_reversion")

            # ── Gate 1: Edge gate — confidence must exceed base win rate ─────
            # Adapts the prediction-market "trade only when edge > 0.04" rule.
            # Base rate = observed win rate from recent history (≥10 trades),
            # otherwise defaults to 50%.  Prevents entering when the AI is
            # barely beating chance.
            if action in ("long", "short"):
                recent_trades = load_trades()
                if len(recent_trades) >= 10:
                    wins_hist = sum(1 for t in recent_trades if float(t["pnl"]) > 0)
                    base_wr   = wins_hist / len(recent_trades)
                else:
                    base_wr = 0.50
                edge = confidence - base_wr
                if edge < MIN_EDGE:
                    print(Fore.YELLOW + f"  {coin}: Edge gate — conf {confidence:.2f} "
                          f"− base_wr {base_wr:.2f} = {edge:+.2f} < {MIN_EDGE:.2f} — skipping")
                    action = "hold"

            # ── Gate 2: Entry quality z-score (mean-reversion only) ──────────
            # Ensures price is meaningfully outside the KC band, not just
            # touching the edge.  z = ATRs beyond the band at entry.
            if action in ("long", "short") and strategy_type == "mean_reversion":
                price_now  = indicators.get("price", 0)
                kc_upper   = indicators.get("kc_upper", 0)
                kc_lower   = indicators.get("kc_lower", 0)
                atr_val    = indicators.get("atr", 0)
                if atr_val and atr_val > 0 and price_now > 0:
                    if action == "short" and kc_upper:
                        z_score = (price_now - kc_upper) / atr_val
                    elif action == "long" and kc_lower:
                        z_score = (kc_lower - price_now) / atr_val
                    else:
                        z_score = MIN_ENTRY_QUALITY   # can't compute — pass through
                    if z_score < MIN_ENTRY_QUALITY:
                        print(Fore.YELLOW + f"  {coin}: Entry quality gate — "
                              f"z={z_score:.3f} ATRs outside band "
                              f"(need ≥{MIN_ENTRY_QUALITY:.2f}) — skipping")
                        action = "hold"

            # ── Gate 3: R:R / flip-close (existing logic) ────────────────────
            if action in ("long", "short"):
                if strategy_type == "mean_reversion":
                    # R:R gate: KC midline must be ≥ 1.2× SL away
                    price_now = indicators.get("price", 0)
                    kc_mid    = indicators.get("kc_mid", 0)
                    sl_pct    = cfg.get("stop_loss_pct", STOP_LOSS_PCT)
                    sl_dist   = price_now * sl_pct
                    tp_dist   = abs(kc_mid - price_now) if kc_mid else 0
                    if kc_mid and tp_dist < 1.2 * sl_dist:
                        print(Fore.YELLOW + f"  {coin}: R:R gate — midline "
                              f"{tp_dist/price_now*100:.2f}% away, need "
                              f"≥{1.2*sl_pct*100:.2f}% — skipping")
                        action = "hold"
                else:
                    # Supertrend: flip-close existing opposite position
                    open_pos  = _risk.state.get("positions", {}).get(coin)
                    open_side = open_pos.get("side") if open_pos else None
                    if open_side and open_side != action:
                        print(Fore.YELLOW + f"  {coin}: ST flip — closing "
                              f"{open_side} before opening {action}")
                        close_trade(coin, _risk, reason="st_flip")

            # ── Gate 4: Order Book Imbalance (microstructure agreement) ─────────
            # OBI = (bid_vol - ask_vol) / total across top 10 book levels.
            # If the order book strongly disagrees with signal direction, skip:
            #   SHORT signal + heavy bid pressure (OBI > OBI_GATE) → skip
            #   LONG  signal + heavy ask pressure (OBI < -OBI_GATE) → skip
            # Falls through if OBI is unavailable (don't block on data errors).
            if action in ("long", "short") and HL_ENABLED:
                hl_sym = cfg.get("hl_symbol", coin)
                obi    = get_hl_obi(hl_sym)
                if obi is not None:
                    obi_blocks = ((action == "short" and obi >  OBI_GATE) or
                                  (action == "long"  and obi < -OBI_GATE))
                    obi_color  = Fore.RED if obi_blocks else Fore.GREEN
                    print(f"  {coin}: OBI={obi_color}{obi:+.3f}{Style.RESET_ALL}"
                          f"  ({'blocks' if obi_blocks else 'agrees'})")
                    if obi_blocks:
                        print(Fore.YELLOW + f"  {coin}: OBI gate — book pressure "
                              f"opposes {action} (OBI={obi:+.3f}, gate=±{OBI_GATE}) — skipping")
                        action = "hold"

            # ── Gate 5: Volume filter (mean-reversion only) ───────────────────
            # Skip entries on thin/quiet bars where a KC band touch is likely
            # noise.  vol_ratio = current bar volume / 20-bar average volume.
            # Low-volume band touches have a much higher false-positive rate.
            if action in ("long", "short") and strategy_type == "mean_reversion":
                vol_ratio = indicators.get("vol_ratio", 1.0)
                if vol_ratio < VOL_MIN_RATIO:
                    print(Fore.YELLOW + f"  {coin}: Volume gate — bar volume only "
                          f"{vol_ratio:.2f}× avg (need ≥{VOL_MIN_RATIO}×) — skipping")
                    action = "hold"

            if action in ("long", "short"):
                allowed, reason = _risk.can_open_position(coin)
                if allowed:
                    execute_trade(coin, action, cfg["hl_size"], _risk,
                                  vol_regime=indicators.get("vol_regime", "normal"),
                                  kc_mid=indicators.get("kc_mid", 0.0),
                                  ai_confidence=confidence)
                else:
                    print(Fore.YELLOW + f"  Skipping {coin}: {reason}")
            else:
                print(Fore.YELLOW + f"  {coin}: holding — {decision.get('reason', '')}")

            time.sleep(2)  # small delay between coins to avoid rate limits

        # Wait for next interval (interruptible)
        for _ in range(BOT_INTERVAL_SEC):
            if not _bot_running.is_set():
                break
            time.sleep(1)

    print(Fore.YELLOW + "\n  Bot stopped.")


# ─── SL/TP MONITOR LOOP ────────────────────────────────────────────────────────

def _monitor_loop():
    """
    Daemon thread: check open positions every 2 minutes.
    Closes any position that has hit its stop-loss or take-profit level.
    Runs independently from the bot scan loop.
    """
    while _bot_running.is_set():
        positions = dict(_risk.state.get("positions", {}))  # snapshot
        for coin, pos in positions.items():
            price = None
            try:
                from trader import get_hl_price
                price = get_hl_price(coin) if HL_ENABLED else None
                if not price:
                    from strategy import get_indicators_for_coin
                    from config import COINS
                    ind   = get_indicators_for_coin(coin, COINS[coin]) if coin in COINS else None
                    price = ind["price"] if ind else None
            except Exception:
                pass

            if not price:
                continue

            sl = pos.get("stop_loss")
            tp = pos.get("take_profit")
            side = pos.get("side", "long")

            hit = None
            if side == "long":
                if sl and price <= sl:
                    hit = "stop loss"
                elif tp and price >= tp:
                    hit = "take profit"
            else:  # short
                if sl and price >= sl:
                    hit = "stop loss"
                elif tp and price <= tp:
                    hit = "take profit"

            if hit:
                print(f"\n  {Fore.YELLOW}[Monitor] {coin} hit {hit} at ${price:,.4f} — closing…")
                from trader import close_trade
                close_trade(coin, _risk, reason=hit)

        # Wait interruptibly
        for _ in range(MONITOR_INTERVAL_SEC):
            if not _bot_running.is_set():
                return
            time.sleep(1)


# ─── MENU ACTIONS ─────────────────────────────────────────────────────────────

def _sync_positions_with_hl() -> None:
    """
    Reconcile local paper_state positions with live HL positions on startup.
    - Local open, HL closed → HL closed it (TP/SL hit while bot was down).
      Remove from local state and log so the bot can re-enter.
    - HL open, local missing → opened externally or state file was wiped.
      Warn only — we don't have entry price/SL/TP to reconstruct the position.
    """
    if not HL_ENABLED:
        return
    try:
        hl_positions = get_hl_positions()
        hl_coins     = {p["position"]["coin"]
                        for p in hl_positions
                        if float(p["position"].get("szi", 0)) != 0}
        local_coins  = set(_risk.state.get("positions", {}).keys())

        # Map local coin names → HL symbols for comparison
        local_hl_symbols = {cfg.get("hl_symbol", c): c
                            for c, cfg in COINS.items()
                            if c in local_coins}

        # Local open but not on HL → was closed externally
        for hl_sym, local_coin in local_hl_symbols.items():
            if hl_sym not in hl_coins:
                _risk.state["positions"].pop(local_coin, None)
                _risk._save_state()
                print(Fore.YELLOW + f"  [sync] {local_coin} was closed on HL while bot "
                      f"was down — removed from local state. Bot will re-enter on next signal.")

        # On HL but not locally tracked → warn
        for hl_sym in hl_coins:
            if hl_sym not in local_hl_symbols:
                print(Fore.YELLOW + f"  [sync] WARNING: {hl_sym} is open on HL but not "
                      f"tracked locally. Close it manually in HL or it will be unmonitored.")

        if not (hl_coins ^ set(local_hl_symbols)):
            print(Fore.GREEN + "  [sync] Local state matches HL positions ✓")

    except Exception as e:
        print(Fore.YELLOW + f"  [sync] Could not sync with HL on startup: {e}")


def start_bot():
    global _bot_thread, _monitor_thread
    if _bot_running.is_set():
        print(Fore.YELLOW + "  Bot is already running.")
        return
    print(Fore.CYAN + "  Syncing local state with HL positions…")
    _sync_positions_with_hl()
    _bot_running.set()
    _bot_thread     = threading.Thread(target=_bot_loop,    daemon=True)
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
    _bot_thread.start()
    _monitor_thread.start()
    print(Fore.GREEN + "  SL/TP monitor started (checks every 2 min).")


def stop_bot():
    if not _bot_running.is_set():
        print(Fore.YELLOW + "  Bot is not running.")
        return
    _bot_running.clear()
    print(Fore.YELLOW + "  Stopping bot… (finishes current scan)")


def switch_to_live():
    global _live_mode
    if _live_mode:
        print(Fore.YELLOW + "  Already in live mode.")
        return
    print(Fore.RED + "\n  ⚠  WARNING: Live mode uses REAL MONEY.")
    print(Fore.RED +  "  Testnet is currently: " + ("ON" if TESTNET else "OFF"))
    if TESTNET:
        print(Fore.YELLOW + "  Note: TESTNET=True in config.py — trades will go to testnet, not mainnet.")
    confirm = input(Fore.RED + "  Type YES to confirm live mode: " + Style.RESET_ALL).strip()
    if confirm == "YES":
        _live_mode = True
        print(Fore.RED + "  Live mode activated.")
    else:
        print(Fore.YELLOW + "  Cancelled.")


def view_positions():
    print_positions(_risk)
    _risk.print_summary()

    # Show live Hyperliquid wallet balance
    print(f"\n  {Fore.CYAN}{'─'*44}")
    net_label = Fore.YELLOW + "TESTNET" if TESTNET else Fore.RED + "MAINNET"
    print(f"  {Fore.CYAN}Hyperliquid Wallet [{net_label}{Fore.CYAN}]" + Style.RESET_ALL)
    acct = get_hl_account_info()
    if acct:
        print(f"  Total equity   : {Fore.GREEN}${acct.get('account_value', 0):,.2f}{Style.RESET_ALL}")
        print(f"    Spot USDC    : ${acct.get('spot_usdc', 0):,.2f}")
        print(f"    Perps equity : ${acct.get('perps_equity', 0):,.2f}")
        print(f"  Margin used    : ${acct.get('margin_used', 0):,.2f}")
        print(f"  Withdrawable   : ${acct.get('withdrawable', 0):,.2f}")
        hl_positions = acct.get("positions", [])
        if hl_positions:
            print(f"  Open on-chain  :")
            for p in hl_positions:
                pos       = p.get("position", {})
                coin      = pos.get("coin", "?")
                size      = pos.get("szi", "0")
                pnl       = float(pos.get("unrealizedPnl", 0))
                entry     = float(pos.get("entryPx", 0))
                pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
                print(f"    {coin:4}  size={size}  entry=${entry:,.4f}  "
                      f"uPnL={pnl_color}${pnl:+,.2f}{Style.RESET_ALL}")
        else:
            print(f"  Open on-chain  : none")
    else:
        print(Fore.RED + "  Could not fetch wallet info — check credentials and connection.")


def set_capital():
    print(f"\n  Current capital: ${_risk.state['capital']:,.2f}")
    try:
        val = float(input("  New capital amount (USD): $").strip())
        if val <= 0:
            print(Fore.RED + "  Must be positive.")
            return
        confirm = input(f"  Set capital to ${val:,.2f}? (y/n): ").strip().lower()
        if confirm == "y":
            _risk.state["capital"]     = val
            _risk.state["equity_peak"] = max(_risk.state["equity_peak"], val)
            from risk_manager import save_state
            save_state(_risk.state)
            print(Fore.GREEN + f"  Capital updated to ${val:,.2f}")
    except ValueError:
        print(Fore.RED + "  Invalid amount.")


def market_analysis():
    active = _active_coins()
    disabled = [c for c in COINS if c not in active]
    label = "active coins"
    if disabled:
        label += f"  ({Fore.YELLOW}disabled: {', '.join(disabled)}{Fore.CYAN})"
    print(f"\n  {Fore.CYAN}Market Analysis — {label}{Style.RESET_ALL}")
    for coin, cfg in active.items():
        print(Fore.YELLOW + f"\n  Fetching {coin}…")
        indicators = get_indicators_for_coin(coin, cfg)
        if not indicators:
            print(Fore.RED + f"  Failed to fetch {coin}")
            continue
        print_indicators(indicators)
        daily_bias = get_trend_bias(coin, cfg)
        if daily_bias["trend"] != "neutral":
            bias_color = Fore.GREEN if daily_bias["trend"] == "bullish" else Fore.RED
            print(f"  Daily bias: {bias_color}{daily_bias['trend'].upper()}{Style.RESET_ALL}"
                  f"  (RSI {daily_bias['rsi']:.1f}, MA {daily_bias['ma_alignment']})")
        decision = get_decision(indicators, daily_bias=daily_bias)
        print_decision(decision)


def toggle_night_mode():
    global _night_mode
    _night_mode = not _night_mode
    print(Fore.CYAN + f"  Night mode {'ON 🌙' if _night_mode else 'OFF ☀️'}")


def open_dashboard():
    try:
        import dashboard
        path = dashboard.run()
        if path and path.exists():
            url = f"file://{path}"
            webbrowser.open(url)
            print(Fore.GREEN + f"  Dashboard opened → {path.name}")
        else:
            print(Fore.RED + "  Dashboard generation failed.")
    except Exception as e:
        print(Fore.RED + f"  Dashboard error: {e}")


def ask_bot():
    print(f"\n  {Fore.CYAN}Ask the Bot — type your question (or 'back' to return)")
    from ai_advisor import _ask_ollama, _ask_openrouter, SYSTEM_PROMPT
    import json, urllib.request

    while True:
        q = input(Fore.WHITE + "  > " + Style.RESET_ALL).strip()
        if q.lower() in ("back", "exit", "q", ""):
            break

        # Build a freeform prompt with current portfolio context
        summary = _risk.get_summary()
        context = (f"Portfolio: capital=${summary['capital']:,.2f}, "
                   f"drawdown={summary['drawdown']:.1f}%, "
                   f"win rate={summary['win_rate']:.1f}%, "
                   f"open positions: {list(summary['positions'].keys()) or 'none'}. "
                   f"Question: {q}")

        print(Fore.YELLOW + "  Thinking…")
        result = _ask_ollama(context)
        if result.get("confidence", 1) == 0:   # error fallback
            result = _ask_openrouter(context)

        # For freeform questions, just print the raw reason/content
        print(f"\n  {Fore.GREEN}{result.get('reason', result)}{Style.RESET_ALL}\n")


def backtest():
    print(f"\n  {Fore.CYAN}Backtest — Per-Coin Strategy Simulation{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}Supertrend (ETH/BTC) · KC Mean-Reversion (SOL) · No LLM calls.{Style.RESET_ALL}\n")

    # ── Period selection ──────────────────────────────────────────────────────
    # SOL uses 5m (yfinance cap: 60d). ETH/BTC use 1h (yfinance cap: ~730d).
    # Periods here override each coin's configured period for manual testing.
    print(f"  Select lookback period:")
    print(f"    [1] 7 days   [2] 30 days   [3] 60 days")
    print(f"    [4] 180 days (1h only)     [5] 365 days (1h only)")
    print(f"  Note: SOL uses 5m (capped at 60d). ETH/BTC use 1h (up to 365d).")
    choice = input("  Your choice [default 3]: ").strip()
    period_map = {"1": "7d", "2": "30d", "3": "60d", "4": "180d", "5": "365d"}
    period = period_map.get(choice, "60d")

    # ── Coin selection ────────────────────────────────────────────────────────
    coin_keys = list(COINS.keys())
    print(f"\n  Select coins (comma-separated) or A for all [{', '.join(coin_keys)}]:")
    raw = input("  Your choice [default A]: ").strip().upper()
    if raw in ("", "A"):
        selected_coins = coin_keys
    else:
        selected_coins = [c.strip() for c in raw.split(",") if c.strip() in COINS]
        if not selected_coins:
            print(Fore.RED + "  No valid coins entered — running all.")
            selected_coins = coin_keys

    print(f"\n  Running backtest for {', '.join(selected_coins)} over {period}…\n")

    # ── Run ───────────────────────────────────────────────────────────────────
    results = []
    for coin in selected_coins:
        r = run_backtest(coin, COINS[coin], period=period)
        results.append(r)

    print_backtest_results(results, period)

    # ── Optional trade list ───────────────────────────────────────────────────
    show = input("  Show last 10 trades per coin? [y/N]: ").strip().lower()
    if show == "y":
        print_trade_list(results, max_per_coin=10)


def fetch_historical():
    active = _active_coins()
    print(f"\n  {Fore.CYAN}Fetch Historical Data")
    print("  Active coins:", ", ".join(active.keys()))
    confirm = input("  Download active coin data? (y/n): ").strip().lower()
    if confirm != "y":
        return
    for coin, cfg in active.items():
        print(Fore.YELLOW + f"  Fetching {coin}…", end=" ")
        from strategy import download_data
        df = download_data(cfg["ticker"], cfg["interval"], cfg["period"])
        if df is not None:
            path = f"data_{coin.lower()}_{cfg['interval']}.csv"
            df.to_csv(path)
            print(Fore.GREEN + f"saved to {path} ({len(df)} bars)")
        else:
            print(Fore.RED + "failed")


def performance_report():
    from trade_log import performance_report as _perf, load_trades
    print(f"\n  {Fore.CYAN}Performance Report")
    print(f"  {Fore.CYAN}{'─'*44}")

    stats = _perf()
    if not stats:
        print(Fore.YELLOW + "  No closed trades yet.")
        return

    pnl_color = Fore.GREEN if stats["total_pnl"] >= 0 else Fore.RED
    pf_str    = (f"{stats['profit_factor']:.2f}"
                 if stats["profit_factor"] != float("inf") else "∞")

    print(f"  Trades:          {stats['total_trades']}")
    print(f"  Win rate:        {Fore.GREEN if stats['win_rate'] >= 50 else Fore.RED}"
          f"{stats['win_rate']:.1f}%{Style.RESET_ALL}")
    print(f"  Total P&L:       {pnl_color}${stats['total_pnl']:+,.2f}{Style.RESET_ALL}")
    print(f"  Avg win:         {Fore.GREEN}${stats['avg_win']:,.2f}{Style.RESET_ALL}")
    print(f"  Avg loss:        {Fore.RED}${stats['avg_loss']:,.2f}{Style.RESET_ALL}")
    print(f"  Profit factor:   {pf_str}")
    print(f"  Max drawdown:    {Fore.RED}{stats['max_drawdown']:.1f}%{Style.RESET_ALL}")
    print(f"  Max consec loss: {stats['max_consec_losses']}")
    print(f"  Best trade:      {Fore.GREEN}${stats['best_trade']:+,.2f}{Style.RESET_ALL}")
    print(f"  Worst trade:     {Fore.RED}${stats['worst_trade']:+,.2f}{Style.RESET_ALL}")

    sharpe  = stats.get("sharpe_ratio", 0)
    sortino = stats.get("sortino_ratio", 0)
    s_color = Fore.GREEN if sharpe  >= 1.0 else Fore.YELLOW if sharpe  > 0 else Fore.RED
    o_color = Fore.GREEN if sortino >= 1.5 else Fore.YELLOW if sortino > 0 else Fore.RED
    sortino_str = f"{sortino:.3f}" if sortino != float("inf") else "∞"
    print(f"  Sharpe ratio:    {s_color}{sharpe:.3f}{Style.RESET_ALL}"
          f"  {'✓ good' if sharpe >= 1.0 else '○ target ≥ 1.0'}")
    print(f"  Sortino ratio:   {o_color}{sortino_str}{Style.RESET_ALL}"
          f"  {'✓ good' if sortino >= 1.5 else '○ target ≥ 1.5'}")

    # Brier Score — AI confidence calibration (lower = better)
    brier = stats.get("brier_score")
    n_cal = stats.get("calibrated_trades", 0)
    if brier is not None:
        # 0.25 = random, <0.20 = decent, <0.15 = well calibrated
        b_color = (Fore.GREEN  if brier < 0.15 else
                   Fore.YELLOW if brier < 0.20 else Fore.RED)
        b_grade = ("✓ well calibrated" if brier < 0.15 else
                   "○ decent"          if brier < 0.20 else
                   "✗ overconfident / poorly calibrated")
        print(f"  Brier score:     {b_color}{brier:.4f}{Style.RESET_ALL}"
              f"  {b_grade}  (n={n_cal}, 0=perfect, 0.25=random)")
    else:
        print(f"  Brier score:     {Fore.YELLOW}— (need ≥5 trades with confidence logged){Style.RESET_ALL}")

    # Show last 5 trades
    trades = load_trades()[-5:]
    if trades:
        print(f"\n  {Fore.CYAN}Last {len(trades)} trades:")
        for t in trades:
            pnl = float(t["pnl"])
            c   = Fore.GREEN if pnl >= 0 else Fore.RED
            print(f"  {t['timestamp'][:16]}  {t['coin']:4} {t['side'].upper():5} "
                  f"{c}${pnl:+,.2f}{Style.RESET_ALL}  ({t['reason']})")


def optimize():
    """
    Per-coin grid-search optimizer — sweeps 288 combos per coin
    (72 for SOL, kc_scalar fixed) using each coin's own timeframe.
    """
    print(f"\n  {Fore.CYAN}Strategy Optimizer — Per-Coin Parameter Grid Search{Style.RESET_ALL}")
    print(f"  Each coin is optimized independently on its own timeframe:")
    for coin, cfg in COINS.items():
        print(f"    {Fore.WHITE}{coin}: {cfg['interval']} / {cfg['period']}{Style.RESET_ALL}")
    print(f"  Grid: kc_scalar × RSI × MA_filter × stop_loss × hurst_cap"
          f"  (288 combos/coin, 72 for SOL)\n")

    # ── Walk-forward option ────────────────────────────────────────────────────
    wf = input("  Run walk-forward validation first? [y/N]: ").strip().lower()
    if wf in ("y", "yes"):
        run_walk_forward()
        print()

    # ── Check for cached results ───────────────────────────────────────────────
    cached = load_best()           # {coin: [results]}
    cached_coins = [c for c in COINS if cached.get(c)]

    if cached_coins:
        print(f"  {Fore.YELLOW}Cached results found for: "
              f"{', '.join(cached_coins)}{Style.RESET_ALL}")
        use_cached = input("  Use cached results? [Y/n]: ").strip().lower()
        if use_cached not in ("n", "no"):
            print_optimizer_results({c: cached[c] for c in cached_coins})
            _optimizer_apply_prompt({c: cached[c] for c in cached_coins})
            return

    # ── Run fresh optimization ─────────────────────────────────────────────────
    coins_str = ", ".join(
        f"{c} ({cfg['interval']}/{cfg['period']})"
        for c, cfg in COINS.items()
    )
    print(f"\n  Running fresh optimization for: {coins_str}")
    print(f"  {Fore.YELLOW}This will take a few minutes per coin…{Style.RESET_ALL}\n")

    results_by_coin = run_optimizer()
    print_optimizer_results(results_by_coin)
    _optimizer_apply_prompt(results_by_coin)


def _optimizer_apply_prompt(results_by_coin: dict) -> None:
    """Ask which coin's top config to display as config.py lines."""
    if not results_by_coin:
        return
    coins_with_results = [c for c, v in results_by_coin.items() if v]
    if not coins_with_results:
        return
    prompt_str = ", ".join(coins_with_results)
    show = input(f"  Show config.py lines for top result? "
                 f"Enter one coin ({prompt_str}) or N: ").strip().upper()
    if show in coins_with_results and results_by_coin.get(show):
        apply_best_to_config(show, results_by_coin[show][0])
    elif show not in ("N", ""):
        print(Fore.YELLOW + f"  Enter one of: {prompt_str}")


def emergency_stop():
    print(Fore.RED + "\n  ⚠  EMERGENCY STOP")
    confirm = input(Fore.RED + "  Type YES to close all positions and halt trading: " + Style.RESET_ALL).strip()
    if confirm == "YES":
        stop_bot()
        emergency_close_all(_risk)
    else:
        print(Fore.YELLOW + "  Cancelled.")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    while True:
        _clear()
        _header()
        _risk._maybe_reset_daily()
        _menu()

        choice = input("  Your choice: ").strip().upper()

        if choice == "1":
            start_bot()
        elif choice == "2":
            stop_bot()
        elif choice == "3":
            switch_to_live()
        elif choice == "4":
            view_positions()
        elif choice == "5":
            set_capital()
        elif choice == "6":
            market_analysis()
        elif choice == "7":
            toggle_night_mode()
        elif choice == "8":
            open_dashboard()
        elif choice == "9":
            ask_bot()
        elif choice == "10":
            backtest()
        elif choice == "11":
            performance_report()
        elif choice == "12":
            optimize()
        elif choice == "F":
            fetch_historical()
        elif choice == "E":
            emergency_stop()
        elif choice == "Q":
            if _bot_running.is_set():
                stop_bot()
            print(Fore.CYAN + "\n  Bye.\n")
            sys.exit(0)
        else:
            print(Fore.RED + "  Invalid choice.")

        input(f"\n  {Fore.WHITE}Press Enter to continue…{Style.RESET_ALL}")


if __name__ == "__main__":
    # When launched by launchd (non-interactively), auto-start the bot loop
    # and keep the process alive. Pass --autostart to enable this mode.
    if "--autostart" in sys.argv:
        print(Fore.GREEN + "  [autostart] Starting bot in non-interactive mode…")
        start_bot()
        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            stop_bot()
            print(Fore.CYAN + "  Shutdown.")
    else:
        main()
