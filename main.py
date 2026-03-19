"""
main.py — trading bot CLI
Full menu with bot lifecycle management, AI advisor, risk controls.
"""
import os
import sys
import time
import threading
import webbrowser
import logging
import io
from datetime import datetime
from contextlib import redirect_stdout, redirect_stderr
from colorama import Fore, Style, init
init(autoreset=True)

from config import (COINS, TESTNET, HL_ENABLED, HL_WALLET_ADDRESS, PAPER_CAPITAL, STOP_LOSS_PCT,
                    MIN_EDGE, MIN_ENTRY_QUALITY, OBI_GATE, VOL_MIN_RATIO,
                    DEBUG_MODE,
                    DEBUG_SCAN_LOGS,
                    MIN_CONFIDENCE,
                    AUTO_IMPORT_POSITIONS,
                    DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT,
                    MAX_HOLD_MINUTES,
                    LOW_VOLUME_EXTREME_RSI_LONG, LOW_VOLUME_EXTREME_RSI_SHORT,
                    LOW_VOLUME_EXTREME_CONFIDENCE_PENALTY, LOW_VOLUME_EXTREME_SIZE_SCALAR,
                    ALLOCATE_BEST_STRATEGY_PER_SYMBOL,
                    FUNDING_CONFLICT_PENALTY, FUNDING_CONTRARIAN_BONUS,
                    REQUIRE_OI_CONFIRMATION_FOR_TREND, SUPPRESS_TREND_ON_OI_DIVERGENCE,
                    USE_BTC_MARKET_FILTER, BTC_FILTER_SUPPRESS_ALTCOINS,
                    BTC_ALT_SIGNAL_CONFIDENCE_PENALTY,
                    USE_CASCADE_FILTER, CASCADE_TREND_CONFIDENCE_BONUS,
                    CASCADE_MR_ENTRY_QUALITY_BONUS, CASCADE_RISK_CONFIDENCE_PENALTY,
                    CASCADE_RISK_BLOCK_EXTREME,
                    USE_FUNDING_RATE_SIGNAL, USE_OPEN_INTEREST_SIGNAL,
                    AI_ENABLED, ENTRY_QUALITY_GATE, HURST_GATE)
from strategy import (
    get_indicators_for_coin, print_indicators, get_trend_bias,
    attach_derivatives_context, get_btc_market_filter, prefetch_scan_market_data,
    select_strategy_candidates,
)
from ai_advisor import get_decision, print_decision, _rule_based_signal
from risk_manager import RiskManager, save_state, reload_disabled_coins
from trader import (
    execute_trade, close_trade, emergency_close_all, print_positions,
    get_hl_account_info, get_hl_obi, get_hl_positions,
    get_hl_funding_rate, get_hl_open_interest, validate_hl_symbols,
    print_available_hl_symbols, validate_coin_risk_config, get_available_hl_symbols,
    sync_local_positions_with_hl, get_verified_hl_positions,
)
from trade_log import load_trades
from backtester import run_backtest, print_backtest_results, print_trade_list, run_friction_stress_test
from optimizer import (
    run_optimizer, run_walk_forward, run_walk_forward_friction,
    load_best, print_optimizer_results, apply_best_to_config,
)
from multi_timeframe_strategy import MultiTimeframeAnalyzer
from volatility_position_sizing import PositionSizer, RiskLevel
from market_regime_detector import MarketRegimeDetector, StrategyAdaptiveManager
from core.lifecycle import start_bot_lifecycle, stop_bot_lifecycle
from core.monitor_loop import run_monitor_loop
from core.scan_loop import run_bot_scan_loop
from core.startup import sync_positions_with_hl
from interfaces.cli_actions import open_dashboard_action, render_performance_report, render_view_positions
from interfaces.coin_management import apply_coin_overrides, manage_coin_overrides
import web_server

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
_bot_thread: threading.Thread | None = None
_monitor_thread: threading.Thread | None = None
_bot_running    = threading.Event()
_stop_event     = threading.Event()
_risk           = RiskManager()
_night_mode     = False
_live_mode      = False   # False = paper, True = live (requires explicit switch)

# Telegram two-way controller — initialised at process startup.
_tg_controller = None

BOT_INTERVAL_SEC     = 5 * 60    # scan every 5 minutes — aligned with 5m candle timeframe
MONITOR_INTERVAL_SEC = 15        # SL/TP monitor checks every 15 seconds for scalping

apply_coin_overrides(COINS)
reload_disabled_coins()   # restore circuit-breaker state from previous run
_risk.set_mode("paper")


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
    print(f"  [13] Manage Coins 🪙       [14] Run Friction Stress Test")
    print(f"  [15] List HL Symbols")
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


def _capture_silently(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        return fn(*args, **kwargs)


def _format_pnl(value: float) -> str:
    return f"{value:+,.2f}"


def _coin_lookup(raw_coin: str) -> tuple[str | None, dict | None]:
    coin = str(raw_coin or "").strip().upper()
    cfg = COINS.get(coin)
    if cfg:
        return coin, cfg
    return None, None


# ─── BOT LOOP ─────────────────────────────────────────────────────────────────

def _print_scan_summary(scan_results: list, scan_started_at=None) -> None:
    signals = sum(1 for item in scan_results if len(item) >= 3 and item[2] in ("long", "short"))
    executions = sum(1 for item in scan_results if len(item) >= 4 and item[3] == "filled")
    from datetime import datetime as _dt
    next_str = _dt.fromtimestamp(_dt.now().timestamp() + BOT_INTERVAL_SEC).strftime('%H:%M:%S')
    print(f"\n  {Fore.CYAN}{'─'*48}")
    print(f"  Done  │  signals:{signals} executions:{executions} │ next:{next_str}{Style.RESET_ALL}")


def _bot_loop():  # NOTE: bot loop updated to skip empty trades
    """Background thread: scan coins, get AI advice, execute trades."""
    run_bot_scan_loop(
        apply_best_configs=_apply_best_configs,
        active_coins=_active_coins,
        bot_running=_bot_running,
        stop_event=_stop_event,
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
        min_confidence=MIN_CONFIDENCE,
        entry_quality_gate=ENTRY_QUALITY_GATE,
        min_entry_quality=MIN_ENTRY_QUALITY,
        stop_loss_pct=STOP_LOSS_PCT,
        hl_enabled=HL_ENABLED,
        get_hl_obi=get_hl_obi,
        get_hl_funding_rate=get_hl_funding_rate,
        get_hl_open_interest=get_hl_open_interest,
        sync_local_positions_with_hl=sync_local_positions_with_hl,
        attach_derivatives_context=attach_derivatives_context,
        get_btc_market_filter=get_btc_market_filter,
        prefetch_scan_market_data=prefetch_scan_market_data,
        select_strategy_candidates=select_strategy_candidates,
        allocate_best_strategy_per_symbol=ALLOCATE_BEST_STRATEGY_PER_SYMBOL,
        use_funding_rate_signal=USE_FUNDING_RATE_SIGNAL,
        use_open_interest_signal=USE_OPEN_INTEREST_SIGNAL,
        require_oi_confirmation_for_trend=REQUIRE_OI_CONFIRMATION_FOR_TREND,
        suppress_trend_on_oi_divergence=SUPPRESS_TREND_ON_OI_DIVERGENCE,
        use_btc_market_filter=USE_BTC_MARKET_FILTER,
        btc_filter_suppress_altcoins=BTC_FILTER_SUPPRESS_ALTCOINS,
        btc_alt_signal_confidence_penalty=BTC_ALT_SIGNAL_CONFIDENCE_PENALTY,
        use_cascade_filter=USE_CASCADE_FILTER,
        cascade_trend_confidence_bonus=CASCADE_TREND_CONFIDENCE_BONUS,
        cascade_mr_entry_quality_bonus=CASCADE_MR_ENTRY_QUALITY_BONUS,
        cascade_risk_confidence_penalty=CASCADE_RISK_CONFIDENCE_PENALTY,
        cascade_risk_block_extreme=CASCADE_RISK_BLOCK_EXTREME,
        funding_conflict_penalty=FUNDING_CONFLICT_PENALTY,
        funding_contrarian_bonus=FUNDING_CONTRARIAN_BONUS,
        obi_gate=OBI_GATE,
        vol_min_ratio=VOL_MIN_RATIO,
        low_volume_extreme_rsi_long=LOW_VOLUME_EXTREME_RSI_LONG,
        low_volume_extreme_rsi_short=LOW_VOLUME_EXTREME_RSI_SHORT,
        low_volume_extreme_confidence_penalty=LOW_VOLUME_EXTREME_CONFIDENCE_PENALTY,
        low_volume_extreme_size_scalar=LOW_VOLUME_EXTREME_SIZE_SCALAR,
        close_trade=close_trade,
        execute_trade=execute_trade,
        add_log=web_server.add_log,
        print_scan_summary=_print_scan_summary,
        sleep=time.sleep,
        bot_interval_sec=BOT_INTERVAL_SEC,
        debug_scan_logs=DEBUG_SCAN_LOGS,
        print_fn=print,
        fore=Fore,
        style=Style,
    )


# ─── SL/TP MONITOR LOOP ────────────────────────────────────────────────────────

def _monitor_loop():
    """
    Background thread: check open positions every 2 minutes.
    Closes any position that has hit its stop-loss or take-profit level.
    Runs independently from the bot scan loop.
    """
    from trader import close_trade, get_hl_price
    from strategy import get_indicators_for_coin
    from config import COINS

    run_monitor_loop(
        bot_running=_bot_running,
        stop_event=_stop_event,
        risk_manager=_risk,
        hl_enabled=HL_ENABLED,
        get_hl_price=get_hl_price,
        get_indicator_price=lambda coin: (
            (get_indicators_for_coin(coin, COINS[coin]) if coin in COINS else None) or {}
        ).get("price"),
        close_trade=close_trade,
        monitor_interval_sec=MONITOR_INTERVAL_SEC,
        max_hold_minutes=MAX_HOLD_MINUTES,
        sleep=time.sleep,
        coins=COINS,
        print_fn=print,
        fore=Fore,
    )


# ─── MENU ACTIONS ─────────────────────────────────────────────────────────────

def _sync_positions_with_hl(quiet: bool = False) -> None:
    """
    Reconcile local paper_state positions with live HL positions on startup.
    - Local open, HL closed → HL closed it (TP/SL hit while bot was down).
      Remove from local state and log so the bot can re-enter.
    - HL open, local missing → opened externally or state file was wiped.
      Warn only — we don't have entry price/SL/TP to reconstruct the position.
    """
    return sync_positions_with_hl(
        hl_enabled=HL_ENABLED,
        risk=_risk,
        coins=COINS,
        get_hl_positions=get_hl_positions,
        save_state=save_state,
        auto_import_positions=AUTO_IMPORT_POSITIONS,
        default_stop_loss_pct=DEFAULT_STOP_LOSS_PCT,
        default_take_profit_pct=DEFAULT_TAKE_PROFIT_PCT,
        printer=print,
        fore=Fore,
        quiet=quiet,
    )


def _telegram_status_text() -> str:
    summary = _risk.get_summary()
    bot_status = "RUNNING" if _bot_running.is_set() else "STOPPED"
    mode = "live" if _live_mode else "paper"
    net = "testnet" if TESTNET else "mainnet"
    active = [coin for coin, cfg in COINS.items() if cfg.get("enabled", True)]
    active_str = ",".join(active) if active else "-"

    account_line = f"Capital ${summary['capital']:,.2f} | open {len(summary['positions'])} | pnl {_format_pnl(summary['total_pnl'])}"
    if HL_ENABLED:
        try:
            acct = get_hl_account_info()
            if acct:
                account_value = float(acct.get("account_value", 0) or 0)
                available_margin = float(acct.get("withdrawable", 0) or 0)
                hl_positions = acct.get("positions", []) or []
            else:
                hl_positions = []
                account_value = 0.0
                available_margin = 0.0
            unrealized_pnl = sum(
                float((wrapper.get("position") or {}).get("unrealizedPnl", 0) or 0)
                for wrapper in hl_positions
            )
            open_hl_positions = sum(
                1 for wrapper in hl_positions
                if abs(float((wrapper.get("position") or {}).get("szi", 0) or 0)) > 0
            )
            account_line = (
                f"HL ${account_value:,.2f} | avail ${available_margin:,.2f} | "
                f"uPnL {_format_pnl(unrealized_pnl)} | pos {open_hl_positions}"
            )
        except Exception:
            pass

    return (
        f"Bot {bot_status} | mode:{mode} | {net}\n"
        f"{account_line}\n"
        f"Coins {active_str}"
    )


def _telegram_mode(mode: str, confirmed: bool = False) -> str:
    global _live_mode
    if mode == "live":
        if not confirmed:
            return "Live mode requires confirmation."
        _live_mode = True
        _risk.set_mode("live")
        return "Mode set: live"
    _live_mode = False
    _risk.set_mode("paper")
    return "Mode set: paper"


def _telegram_set_capital(amount: float) -> str:
    if amount <= 0:
        return "Invalid capital."
    _risk.state["capital"] = amount
    _risk.state["equity_peak"] = max(float(_risk.state.get("equity_peak", 0) or 0), amount)
    save_state(_risk.state)
    return f"Capital set to ${amount:,.2f}"


def _telegram_coins(action: str, coin: str | None) -> str:
    if action == "list":
        active = [c for c, cfg in COINS.items() if cfg.get("enabled", True)]
        disabled = [c for c, cfg in COINS.items() if not cfg.get("enabled", True)]
        return f"Active: {', '.join(active) or '-'}\nDisabled: {', '.join(disabled) or '-'}"

    coin_key, cfg = _coin_lookup(coin)
    if not coin_key or cfg is None:
        return f"Unknown coin: {coin}"
    cfg["enabled"] = (action == "enable")
    status = validate_hl_symbols() if HL_ENABLED else {"active": [], "disabled": []}
    if action == "enable" and not cfg.get("enabled", False):
        return f"{coin_key} disabled: invalid HL symbol"
    merged = [row for row in status.get("merged", []) if row[0] == coin_key]
    if merged:
        primary = merged[0][3]
        return f"{coin_key} merged into {primary}"
    return f"{coin_key} {'enabled' if cfg.get('enabled', False) else 'disabled'}"


def _telegram_analyze(coin: str) -> str:
    coin_key, cfg = _coin_lookup(coin)
    if not coin_key or not cfg:
        return f"Unknown coin: {coin}"
    indicators = get_indicators_for_coin(coin_key, cfg)
    if not indicators:
        return f"{coin_key} skip\nNo indicators"
    daily_bias = get_trend_bias(coin_key, cfg)
    decision = get_decision(indicators, daily_bias=daily_bias) if AI_ENABLED else _rule_based_signal(indicators, daily_bias=daily_bias)
    action = str(decision.get("action", "hold")).upper()
    confidence = float(decision.get("confidence", 0) or 0)
    reason = str(decision.get("reason", ""))
    price = float(indicators.get("price", 0) or 0)
    return f"{coin_key} {action} conf={confidence:.2f}\nPrice {price:,.4f}\n{reason[:160]}"


def _telegram_backtest(coin: str) -> str:
    coin_key, cfg = _coin_lookup(coin)
    if not coin_key or not cfg:
        return f"Unknown coin: {coin}"
    stats = _capture_silently(run_backtest, coin_key, cfg, None, None, True)
    if not stats or stats.get("error"):
        return f"{coin_key} backtest failed\n{stats.get('error', 'no result') if isinstance(stats, dict) else 'no result'}"
    return (
        f"{coin_key} PF {stats.get('profit_factor', 0):.2f} | Sharpe {stats.get('sharpe_ratio', 0):.2f}\n"
        f"Trades {stats.get('total_trades', 0)} | PnL {_format_pnl(float(stats.get('total_pnl', 0) or 0))}"
    )


def _telegram_optimize() -> str:
    results = _capture_silently(run_optimizer)
    if not results:
        return "Optimize finished\nNo results"
    top = []
    for coin, rows in results.items():
        if rows:
            top.append(f"{coin}:{rows[0].get('profit_factor', 0):.2f}")
    return f"Optimize finished\nTop: {', '.join(top[:6]) or '-'}"


def _telegram_report() -> str:
    from hltrading.execution.trade_log import auto_disable_failing_components
    from trade_log import performance_report as _perf

    disable_logs = auto_disable_failing_components()
    report = _perf()
    if not report:
        return "No trade history."
    base = (
        f"Trades {report.get('total_trades', 0)} | WR {report.get('win_rate', 0):.1f}% | PF {report.get('profit_factor', 0)}\n"
        f"Since update {report.get('since_last_update', {}).get('total_trades', 0)} trades | "
        f"PF {report.get('since_last_update', {}).get('profit_factor', 0)} | "
        f"PnL {_format_pnl(float(report.get('since_last_update', {}).get('total_pnl', 0) or 0))}"
    )
    if disable_logs:
        return base + "\n" + disable_logs[0][:160]
    return base


def _telegram_stress(coin: str) -> str:
    coin_key, cfg = _coin_lookup(coin)
    if not coin_key or not cfg:
        return f"Unknown coin: {coin}"
    rows = _capture_silently(run_friction_stress_test, coin_key, cfg, None, None, None, True)
    if not rows:
        return f"{coin_key} stress failed"
    baseline = rows[0]
    survivors = sum(1 for row in rows if float(row.get("profit_factor", 0) or 0) >= 1 and float(row.get("total_pnl", 0) or 0) > 0)
    worst = min(float(row.get("profit_factor", 0) or 0) for row in rows)
    return (
        f"{coin_key} base PF {float(baseline.get('profit_factor', 0) or 0):.2f} | Sharpe {float(baseline.get('sharpe_ratio', 0) or 0):.2f}\n"
        f"Stress {survivors}/{len(rows)} survive | worst PF {worst:.2f}"
    )


def _telegram_dashboard() -> str:
    return "Dashboard\nhttp://localhost:5000"


def _telegram_symbols() -> str:
    symbols = get_available_hl_symbols()
    if not symbols:
        return "No HL symbols available."
    preview = ", ".join(symbols[:20])
    suffix = " ..." if len(symbols) > 20 else ""
    return f"HL symbols ({len(symbols)})\n{preview}{suffix}"


def _telegram_fetch() -> str:
    from strategy import get_market_data

    total = 0
    ok = 0
    for coin, cfg in _active_coins().items():
        total += 1
        df = get_market_data(
            coin,
            cfg["interval"],
            cfg["period"],
            asset_id=cfg.get("asset_id"),
            hl_symbol=cfg.get("hl_symbol", coin),
            warmup_bars=0,
        )
        if df is not None and not df.empty:
            ok += 1
    return f"Fetched {ok}/{total} active coins"


def _telegram_ask(text: str) -> str:
    from ai_advisor import _ask_ollama, _ask_openrouter

    summary = _risk.get_summary()
    prompt = (
        f"Portfolio: capital=${summary['capital']:,.2f}, drawdown={summary['drawdown']:.1f}%, "
        f"win_rate={summary['win_rate']:.1f}%, open_positions={list(summary['positions'].keys()) or 'none'}. "
        f"Question: {text}"
    )
    result = _ask_ollama(prompt)
    if result.get("confidence", 1) == 0:
        result = _ask_openrouter(prompt)
    answer = str(result.get("reason", result)).strip()
    return answer[:400] if len(answer) > 400 else answer


def _telegram_emergency() -> str:
    stop_bot(quiet=True)
    _risk.trigger_emergency_stop()
    emergency_close_all(_risk)
    return "Emergency stop executed."


def _build_telegram_callbacks() -> dict[str, callable]:
    return {
        "start": lambda: _telegram_start(),
        "stop": lambda: _telegram_stop(),
        "status": _telegram_status_text,
        "emergency": _telegram_emergency,
        "mode": _telegram_mode,
        "setcapital": _telegram_set_capital,
        "coins": _telegram_coins,
        "analyze": _telegram_analyze,
        "backtest": _telegram_backtest,
        "optimize": _telegram_optimize,
        "report": _telegram_report,
        "stress": _telegram_stress,
        "dashboard": _telegram_dashboard,
        "symbols": _telegram_symbols,
        "fetch": _telegram_fetch,
        "ask": _telegram_ask,
    }


def _ensure_telegram_controller() -> None:
    global _tg_controller
    if _tg_controller is not None:
        return
    from telegram_bot import TelegramController

    _tg_controller = TelegramController(
        risk_manager=_risk,
        callbacks=_build_telegram_callbacks(),
    )
    _tg_controller.start()


def _telegram_start() -> str:
    result = start_bot(quiet=True)
    if result.get("already_running"):
        return "Bot already running."
    if not result.get("ok"):
        return f"Start failed.\nSync: {'OK' if result.get('sync_ok') else 'FAIL'}"
    active = ", ".join(result.get("active", [])) or "-"
    return f"Bot started.\nActive: {active}\nInterval: {BOT_INTERVAL_SEC // 60}m"


def _telegram_stop() -> str:
    result = stop_bot(quiet=True)
    if result.get("already_stopped"):
        return "Bot already stopped."
    return "Bot stopped."


def start_bot(*, quiet: bool = False):
    global _bot_thread, _monitor_thread

    _ensure_telegram_controller()
    printer = (lambda *args, **kwargs: None) if quiet else print

    _bot_thread, _monitor_thread, init_status = start_bot_lifecycle(
        bot_running=_bot_running,
        stop_event=_stop_event,
        validate_coin_config=validate_coin_risk_config,
        validate_symbols=validate_hl_symbols,
        sync_positions=_sync_positions_with_hl,
        risk_manager=_risk,
        bot_loop=_bot_loop,
        monitor_loop=_monitor_loop,
        printer=printer,
        fore=Fore,
    )
    if init_status is None:
        return {"ok": False, "already_running": True}

    active = ", ".join(init_status.get("active", [])) or "-"
    disabled = ", ".join(init_status.get("disabled", [])) or "-"
    sync_status = "OK" if init_status.get("sync_ok") else "FAIL"
    if not quiet:
        for merged_coin, _symbol, asset_id, primary_coin in init_status.get("merged", []):
            print(f"merged {merged_coin} -> {primary_coin} (shared asset_id={asset_id})")
        print("[INIT]")
        print(f"Active: {active}")
        print(f"Disabled: {disabled}")
        print(f"Sync: {sync_status}")
        print(f"Interval: {BOT_INTERVAL_SEC//60}m")
    if not init_status.get("sync_ok"):
        if not quiet:
            print(Fore.RED + "Startup blocked")
        return {"ok": False, **init_status}
    if not quiet:
        print("\nBot started")
    return {"ok": True, **init_status}


def stop_bot(*, quiet: bool = False):
    global _bot_thread, _monitor_thread
    was_running = _bot_running.is_set()
    printer = (lambda *args, **kwargs: None) if quiet else print
    stop_bot_lifecycle(
        bot_running=_bot_running,
        stop_event=_stop_event,
        bot_thread=_bot_thread,
        monitor_thread=_monitor_thread,
        printer=printer,
        fore=Fore,
    )
    _bot_thread = None
    _monitor_thread = None
    return {"ok": was_running, "already_stopped": not was_running}


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
        _risk.set_mode("live")
        print(Fore.RED + "  Live mode activated.")
    else:
        print(Fore.YELLOW + "  Cancelled.")


def view_positions():
    render_view_positions(
        risk_manager=_risk,
        print_positions=print_positions,
        get_hl_account_info=get_hl_account_info,
        get_verified_hl_positions=get_verified_hl_positions,
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
    # SOL uses 5m. ETH/BTC use 1h.
    # Periods here override each coin's configured period for manual testing.
    print(f"  Select lookback period:")
    print(f"    [1] 7 days   [2] 30 days   [3] 60 days")
    print(f"    [4] 180 days (1h only)     [5] 365 days (1h only)")
    print(f"  Note: short-term coins use 5m candles; trend coins use 1h candles.")
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
    from strategy import get_market_data
    for coin, cfg in active.items():
        print(Fore.YELLOW + f"  Fetching {coin}…", end=" ")
        df = get_market_data(
            coin,
            cfg["interval"],
            cfg["period"],
            asset_id=cfg.get("asset_id"),
            hl_symbol=cfg.get("hl_symbol", coin),
            warmup_bars=0,
        )
        if df is not None:
            path = f"data_{coin.lower()}_{cfg['interval']}.csv"
            df.to_csv(path)
            print(Fore.GREEN + f"saved to {path} ({len(df)} bars)")
        else:
            print(Fore.RED + "failed")


def performance_report():
    from hltrading.execution.trade_log import auto_disable_failing_components
    from trade_log import performance_report as _perf, load_trades

    disable_logs = auto_disable_failing_components()
    render_performance_report(
        performance_report_fn=_perf,
        load_trades=load_trades,
        printer=print,
        fore=Fore,
        style=Style,
    )
    for line in disable_logs:
        print(Fore.RED + f"  {line}" + Style.RESET_ALL)


def manage_coins():
    manage_coin_overrides(
        COINS,
        input_fn=input,
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

    wf_friction = input("  Run walk-forward friction validation? [y/N]: ").strip().lower()
    if wf_friction in ("y", "yes"):
        default_coins = "ETH,SOL,DOGE,WIF,BONK,AVAX,LINK"
        selected = input(f"  Coins for friction validation [{default_coins}]: ").strip().upper()
        coins = [c.strip() for c in (selected or default_coins).split(",") if c.strip()]
        run_walk_forward_friction(selected_coins=coins)
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


def friction_stress_test():
    allowed = ["ETH", "SOL", "AVAX", "LINK", "WIF", "BONK", "DOGE"]
    prompt = ", ".join(allowed)
    coin = input(f"  Choose coin ({prompt}): ").strip().upper()
    if coin not in allowed:
        print(Fore.YELLOW + f"  Enter one of: {prompt}")
        return

    coin_cfg = COINS.get(coin)
    if not coin_cfg:
        print(Fore.RED + f"  {coin} is not configured in COINS.")
        return

    print(f"\n  {Fore.CYAN}Friction Stress Test — {coin}{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}Running 8 scenarios with fee, slippage, and delay stress…{Style.RESET_ALL}\n")
    results = run_friction_stress_test(coin, coin_cfg, silent=True)

    if not results:
        print(Fore.RED + "  No stress-test results returned.")
        return

    print(f"  {Fore.CYAN}{'─'*78}")
    print(f"  {'#':>2}  {'fee':>5}  {'slip%':>6}  {'in':>2}  {'out':>3}  {'pf':>6}  {'sharpe':>7}  {'trades':>6}  {'pnl':>10}")
    print(f"  {Fore.CYAN}{'─'*78}{Style.RESET_ALL}")

    survivors = 0
    for row in results:
        pf = row.get("profit_factor", 0)
        sharpe = row.get("sharpe_ratio", 0)
        trades = row.get("total_trades", 0)
        pnl = float(row.get("total_pnl", 0) or 0)
        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        pf_str = f"{pf:.2f}" if isinstance(pf, (int, float)) else str(pf)
        sharpe_str = f"{float(sharpe):.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
        if isinstance(pf, (int, float)) and pf >= 1.0 and pnl > 0:
            survivors += 1
        print(
            f"  {row['scenario']:>2}  "
            f"{row['fee']:>5.2f}  "
            f"{row['slippage']:>6.2f}  "
            f"{row['entry_delay']:>2}  "
            f"{row['exit_delay']:>3}  "
            f"{pf_str:>6}  "
            f"{sharpe_str:>7}  "
            f"{trades:>6}  "
            f"{pnl_color}${pnl:+9.2f}{Style.RESET_ALL}"
        )

    if survivors >= 6:
        verdict = Fore.GREEN + "robust under friction"
    elif survivors >= 4:
        verdict = Fore.YELLOW + "mixed under friction"
    else:
        verdict = Fore.RED + "fragile under friction"

    print(f"\n  Summary: {verdict}{Style.RESET_ALL}  "
          f"({survivors}/{len(results)} scenarios kept PF>=1 and positive PnL)")


def list_hl_symbols():
    print()
    print_available_hl_symbols()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    web_server.start()
    _ensure_telegram_controller()
    while True:
        _clear()
        _header()
        _risk._maybe_reset_daily()
        _menu()

        choice = input().strip().upper()

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
        elif choice == "13":
            manage_coins()
        elif choice == "14":
            friction_stress_test()
        elif choice == "15":
            list_hl_symbols()
        elif choice == "F":
            fetch_historical()
        elif choice == "E":
            emergency_stop()
        elif choice == "Q":
            if _bot_running.is_set():
                stop_bot(quiet=True)
            if _tg_controller:
                _tg_controller.stop()
            print(Fore.CYAN + "\n  Bye.\n")
            return
        else:
            print(Fore.RED + "  Invalid choice.")

        if choice == "1":
            continue
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
        _ensure_telegram_controller()
        start_bot()
        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            stop_bot(quiet=True)
            if _tg_controller:
                _tg_controller.stop()
            print(Fore.CYAN + "  Shutdown.")
    else:
        main()
