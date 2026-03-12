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

from config import (COINS, TESTNET, HL_ENABLED, PAPER_CAPITAL, STOP_LOSS_PCT,
                    MIN_EDGE, MIN_ENTRY_QUALITY, OBI_GATE, VOL_MIN_RATIO,
                    AI_ENABLED, ENTRY_QUALITY_GATE, HURST_GATE)
from strategy import get_indicators_for_coin, print_indicators, get_trend_bias
from ai_advisor import get_decision, print_decision, _rule_based_signal
from risk_manager import RiskManager, save_state
from trader import execute_trade, close_trade, emergency_close_all, print_positions, get_hl_account_info, get_hl_obi, get_hl_positions
from trade_log import load_trades
from backtester import run_backtest, print_backtest_results, print_trade_list
from optimizer import run_optimizer, run_walk_forward, load_best, print_optimizer_results, apply_best_to_config
from multi_timeframe_strategy import MultiTimeframeAnalyzer
from volatility_position_sizing import PositionSizer, RiskLevel
from market_regime_detector import MarketRegimeDetector, StrategyAdaptiveManager
from core.lifecycle import start_bot_lifecycle, stop_bot_lifecycle
from core.monitor_loop import run_monitor_loop
from core.scan_loop import run_bot_scan_loop
from core.startup import sync_positions_with_hl
from interfaces.cli_actions import open_dashboard_action, render_performance_report, render_view_positions
import web_server

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
_bot_thread: threading.Thread | None = None
_monitor_thread: threading.Thread | None = None
_bot_running    = threading.Event()
_risk           = RiskManager()
_night_mode     = False
_live_mode      = False   # False = paper, True = live (requires explicit switch)

# Telegram two-way controller — initialised in start_bot(), None until then.
_tg_controller = None

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

def _print_scan_summary(scan_results: list) -> None:
    """
    Print a compact end-of-scan line showing signal count + proximity table.

    For KC coins that held, shows how close price and RSI are to the signal
    threshold so the operator knows whether signals are imminent or distant.

    Format (per KC coin):
      COIN(L/S)  KC=+1.2%  RSI=43/40
      - L/S  = direction of closer setup
      - KC   = % gap between price and the relevant band
                positive = price not yet at band  (needs to move further)
                negative = price already past band (KC cond met)
      - RSI  = current RSI / threshold  (signal fires when cond met for direction)
    """
    from datetime import datetime as _dt

    n_sigs = sum(1 for _, _, a in scan_results if a in ("long", "short"))
    next_ts = _dt.now().timestamp() + BOT_INTERVAL_SEC
    next_str = _dt.fromtimestamp(next_ts).strftime('%H:%M:%S')

    sig_color = Fore.GREEN if n_sigs else Fore.YELLOW
    print(f"\n  {Fore.CYAN}{'─'*48}")
    print(f"  Scan done  {sig_color}{n_sigs} signal{'s' if n_sigs != 1 else ''}{Style.RESET_ALL}"
          f"  │  Next: {next_str}")

    # ── Proximity table: KC mean-reversion holds only ──────────────────────
    rows = []
    for coin, ind, action in scan_results:
        if action in ("long", "short"):
            continue                           # already fired
        if ind.get("strategy_type") != "mean_reversion":
            continue

        price    = ind.get("price",    0)
        kc_lower = ind.get("kc_lower", 0)
        kc_upper = ind.get("kc_upper", 0)
        rsi      = ind.get("rsi",      50)
        rsi_os   = ind.get("rsi_oversold",   40)
        rsi_ob   = ind.get("rsi_overbought", 60)

        if not price:
            continue

        # Gap: positive = not yet at band, negative = already past band
        long_kc_gap  = (price - kc_lower) / price * 100 if kc_lower else 99
        short_kc_gap = (kc_upper - price) / price * 100 if kc_upper else 99
        long_rsi_gap  = rsi - rsi_os    # positive = above threshold (need to fall)
        short_rsi_gap = rsi_ob - rsi    # positive = below threshold (need to rise)

        # Pick the side with the smaller combined distance
        long_score  = long_kc_gap  + max(0, long_rsi_gap)  * 0.5
        short_score = short_kc_gap + max(0, short_rsi_gap) * 0.5

        if long_score <= short_score:
            side, kc_gap, cur_rsi, thresh = "L", long_kc_gap,  rsi, rsi_os
        else:
            side, kc_gap, cur_rsi, thresh = "S", short_kc_gap, rsi, rsi_ob

        rows.append((long_score if side == "L" else short_score,
                     coin, side, kc_gap, cur_rsi, thresh))

    if not rows:
        return

    rows.sort(key=lambda r: r[0])
    parts = []
    for _, coin, side, kc_gap, cur_rsi, thresh in rows[:5]:
        # Colour by proximity: green ≤ 0.5% away, yellow ≤ 1.5%, white otherwise
        kc_color  = (Fore.GREEN  if kc_gap  <= 0.0 else
                     Fore.GREEN  if kc_gap  <= 0.5 else
                     Fore.YELLOW if kc_gap  <= 1.5 else Fore.WHITE)
        rsi_color = (Fore.GREEN  if (side == "L" and cur_rsi <= thresh) or
                                    (side == "S" and cur_rsi >= thresh) else
                     Fore.YELLOW if abs(cur_rsi - thresh) <= 3          else Fore.WHITE)
        kc_str  = f"{kc_gap:+.1f}%" if kc_gap > 0 else f"{kc_gap:.1f}%"
        parts.append(f"{Fore.CYAN}{coin}{Style.RESET_ALL}({side})"
                     f" KC={kc_color}{kc_str}{Style.RESET_ALL}"
                     f" RSI={rsi_color}{cur_rsi:.0f}/{thresh}{Style.RESET_ALL}")

    print(f"  Watching:  {'  │  '.join(parts)}")


def _bot_loop():  # NOTE: bot loop updated to skip empty trades
    """Background thread: scan coins, get AI advice, execute trades."""
    run_bot_scan_loop(
        apply_best_configs=_apply_best_configs,
        active_coins=_active_coins,
        bot_running=_bot_running,
        risk_manager=_risk,
        tg_controller=_tg_controller,
        web_is_paused=web_server.is_paused,
        ai_enabled=AI_ENABLED,
        load_trades=load_trades,
        get_indicators_for_coin=get_indicators_for_coin,
        print_indicators=print_indicators,
        get_trend_bias=get_trend_bias,
        get_decision=get_decision,
        rule_based_signal=_rule_based_signal,
        print_decision=print_decision,
        min_edge=MIN_EDGE,
        entry_quality_gate=ENTRY_QUALITY_GATE,
        min_entry_quality=MIN_ENTRY_QUALITY,
        stop_loss_pct=STOP_LOSS_PCT,
        hl_enabled=HL_ENABLED,
        get_hl_obi=get_hl_obi,
        obi_gate=OBI_GATE,
        vol_min_ratio=VOL_MIN_RATIO,
        close_trade=close_trade,
        execute_trade=execute_trade,
        add_log=web_server.add_log,
        print_scan_summary=_print_scan_summary,
        sleep=time.sleep,
        bot_interval_sec=BOT_INTERVAL_SEC,
        print_fn=print,
        fore=Fore,
        style=Style,
    )


# ─── SL/TP MONITOR LOOP ────────────────────────────────────────────────────────

def _monitor_loop():
    """
    Daemon thread: check open positions every 2 minutes.
    Closes any position that has hit its stop-loss or take-profit level.
    Runs independently from the bot scan loop.
    """
    from trader import close_trade, get_hl_price
    from strategy import get_indicators_for_coin
    from config import COINS

    run_monitor_loop(
        bot_running=_bot_running,
        risk_manager=_risk,
        hl_enabled=HL_ENABLED,
        get_hl_price=get_hl_price,
        get_indicator_price=lambda coin: (
            (get_indicators_for_coin(coin, COINS[coin]) if coin in COINS else None) or {}
        ).get("price"),
        close_trade=close_trade,
        monitor_interval_sec=MONITOR_INTERVAL_SEC,
        sleep=time.sleep,
        print_fn=print,
        fore=Fore,
    )


# ─── MENU ACTIONS ─────────────────────────────────────────────────────────────

def _sync_positions_with_hl() -> None:
    """
    Reconcile local paper_state positions with live HL positions on startup.
    - Local open, HL closed → HL closed it (TP/SL hit while bot was down).
      Remove from local state and log so the bot can re-enter.
    - HL open, local missing → opened externally or state file was wiped.
      Warn only — we don't have entry price/SL/TP to reconstruct the position.
    """
    sync_positions_with_hl(
        hl_enabled=HL_ENABLED,
        risk=_risk,
        coins=COINS,
        get_hl_positions=get_hl_positions,
        save_state=save_state,
        printer=print,
        fore=Fore,
    )


def start_bot():
    global _bot_thread, _monitor_thread, _tg_controller
    from telegram_bot import TelegramController
    from trader import close_trade, emergency_close_all

    _bot_thread, _monitor_thread, _tg_controller = start_bot_lifecycle(
        bot_running=_bot_running,
        sync_positions=_sync_positions_with_hl,
        telegram_controller_factory=TelegramController,
        risk_manager=_risk,
        close_fn=close_trade,
        closeall_fn=emergency_close_all,
        bot_loop=_bot_loop,
        monitor_loop=_monitor_loop,
        printer=print,
        fore=Fore,
    )


def stop_bot():
    global _tg_controller
    _tg_controller = stop_bot_lifecycle(
        bot_running=_bot_running,
        tg_controller=_tg_controller,
        printer=print,
        fore=Fore,
    )


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
    render_view_positions(
        risk_manager=_risk,
        print_positions=print_positions,
        get_hl_account_info=get_hl_account_info,
        testnet=TESTNET,
        printer=print,
        fore=Fore,
        style=Style,
    )


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
            save_state(_risk.state)
            print(Fore.GREEN + f"  Capital updated to ${val:,.2f}")
    except ValueError:
        print(Fore.RED + "  Invalid amount.")


def market_analysis():
    active = _active_coins()
    disabled = [c for c in COINS if c not in active]
    coin_keys = list(active.keys())

    # ── Coin selection ────────────────────────────────────────────────────────
    disabled_str = (f"  ({Fore.YELLOW}disabled: {', '.join(disabled)}{Fore.CYAN})"
                    if disabled else "")
    print(f"\n  {Fore.CYAN}Market Analysis{disabled_str}{Style.RESET_ALL}")
    print(f"  Active coins: {', '.join(coin_keys)}")
    print(f"  Enter coin(s) comma-separated, or A for all, or Q to cancel:")
    raw = input("  > ").strip().upper()

    if raw in ("Q", ""):
        return

    if raw == "A":
        selected = coin_keys
    else:
        selected = [c.strip() for c in raw.split(",") if c.strip() in active]
        if not selected:
            print(Fore.RED + "  No valid coins entered.")
            return

    for coin in selected:
        cfg = active[coin]
        print(Fore.YELLOW + f"\n  Fetching {coin}…")
        indicators = get_indicators_for_coin(coin, cfg)
        if not indicators:
            print(Fore.RED + f"  Failed to fetch {coin}")
            continue
        print_indicators(indicators)
        daily_bias = get_trend_bias(coin, cfg)
        decision   = get_decision(indicators, daily_bias=daily_bias)
        print_decision(decision, daily_bias=daily_bias)


def toggle_night_mode():
    global _night_mode
    _night_mode = not _night_mode
    print(Fore.CYAN + f"  Night mode {'ON 🌙' if _night_mode else 'OFF ☀️'}")


def open_dashboard():
    """Open the enhanced live dashboard in the default browser."""
    import webbrowser

    open_dashboard_action(
        module_file=__file__,
        browser_open=webbrowser.open,
        printer=print,
        fore=Fore,
    )


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
    render_performance_report(
        performance_report_fn=_perf,
        load_trades=load_trades,
        printer=print,
        fore=Fore,
        style=Style,
    )


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
    web_server.start()   # live dashboard available at http://localhost:5000
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


# ── Wire web server (module level — runs whether bot is started or not) ────────
web_server.init(
    risk         = _risk,
    bot_running  = _bot_running,
    start_fn     = start_bot,
    stop_fn      = stop_bot,
    close_fn     = close_trade,
    emergency_fn = emergency_close_all,
)

if __name__ == "__main__":
    # When launched by launchd (non-interactively), auto-start the bot loop
    # and keep the process alive. Pass --autostart to enable this mode.
    if "--autostart" in sys.argv:
        print(Fore.GREEN + "  [autostart] Starting bot in non-interactive mode…")
        web_server.start()
        start_bot()
        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            stop_bot()
            print(Fore.CYAN + "  Shutdown.")
    else:
        main()
