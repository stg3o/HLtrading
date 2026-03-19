"""
backtester.py — walk-forward backtester for KC mean-reversion and Supertrend.

Routes automatically based on coin_cfg["strategy_type"]:
  • "mean_reversion" (SOL)  — KC+RSI bands, KC midline TP, MA trend filter
  • "supertrend"    (ETH/BTC) — ATR Supertrend flip entry/exit, hard SL only

Mean-reversion improvements:
  1. TP = KC midline (dynamic) — natural mean-reversion exit.
     Fallback: if midline is closer than take_profit_pct, use fixed TP instead.
  2. MA_TREND direction filter — longs only above MA_TREND, shorts only below.
  3. RSI thresholds loosened to 40/60 — more signals on the 5m timeframe.
  4. R:R gate: skip entry if KC midline distance < 1.2× SL distance.

Supertrend trade logic:
  - Entry: confirmed directional flip (this bar only).
  - Exit 1: opposing flip (trend reversal — main profit exit).
  - Exit 2: hard stop-loss (safety net, not primary exit).
  - Exit 3: max_bars_in_trade time stop (prevents zombie positions).
  - No fixed TP — letting the trend run IS the edge.

Parameter overrides
-------------------
All tunable parameters are bundled into a ``params`` dict so the optimizer can
sweep combinations without touching globals.  The defaults mirror config.py.
Pass a partial dict — only keys you want to override need to be present.
"""
import math
import numpy as np
import pandas as pd
import pandas_ta as ta
from colorama import Fore, Style

from config import (
    KC_PERIOD, KC_SCALAR, MA_FAST, MA_SLOW, MA_TREND, RSI_PERIOD,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, RISK_PER_TRADE, PAPER_CAPITAL,
    RSI_OVERSOLD, RSI_OVERBOUGHT, COINS,
)
from research.metrics import compute_core_backtest_stats
from research.simulator import run_mean_reversion_simulation, run_supertrend_simulation
from strategy import _safe, _hurst, _supertrend_arrays


# ─── DEFAULT SIMULATION PARAMETERS ───────────────────────────────────────────
# These mirror the config globals so existing callers work unchanged.
# The optimizer overrides individual keys per combo.

_DEFAULT_SIM_PARAMS: dict = {
    "kc_scalar":         KC_SCALAR,          # ATR multiplier for KC bands
    "rsi_oversold":      RSI_OVERSOLD,       # long entry threshold
    "rsi_overbought":    RSI_OVERBOUGHT,     # short entry threshold
    "hurst_cap":         0.62,               # skip fades above this Hurst value
    "ma_trend_filter":   True,               # require price above/below MA_TREND
    "stop_loss_pct":     STOP_LOSS_PCT,      # tight SL for scalping
    "take_profit_pct":   TAKE_PROFIT_PCT,    # fallback TP when midline is too close
    "min_rr_ratio":      1.2,               # minimum required (tp_dist / sl_dist)
    "max_bars_in_trade": 36,                 # 3 hours on 5m — force-exit stale trades
}

_WARMUP = max(MA_TREND, KC_PERIOD, RSI_PERIOD) + 10

FRICTION_STRESS_SCENARIOS = [
    {"fee": 0.09, "slippage": 0.00, "entry_delay": 0, "exit_delay": 0},
    {"fee": 0.12, "slippage": 0.00, "entry_delay": 0, "exit_delay": 0},
    {"fee": 0.18, "slippage": 0.00, "entry_delay": 0, "exit_delay": 0},
    {"fee": 0.09, "slippage": 0.03, "entry_delay": 0, "exit_delay": 0},
    {"fee": 0.12, "slippage": 0.03, "entry_delay": 0, "exit_delay": 0},
    {"fee": 0.09, "slippage": 0.00, "entry_delay": 1, "exit_delay": 0},
    {"fee": 0.09, "slippage": 0.00, "entry_delay": 0, "exit_delay": 1},
    {"fee": 0.18, "slippage": 0.06, "entry_delay": 1, "exit_delay": 1},
]


# ─── SUPERTREND SIMULATION ────────────────────────────────────────────────────

def _run_supertrend_sim(df: pd.DataFrame, p: dict) -> tuple[list, float, list]:
    """Compatibility wrapper for the shared Supertrend simulation loop."""
    return run_supertrend_simulation(
        df,
        p,
        paper_capital=PAPER_CAPITAL,
        risk_per_trade=RISK_PER_TRADE,
        supertrend_arrays=_supertrend_arrays,
        include_timestamps=False,
    )


def _run_backtest_st(coin: str, coin_cfg: dict, period: str = "365d",
                     params: dict | None = None, silent: bool = False) -> dict:
    """
    Full Supertrend backtest: fetch data, validate, simulate, compute stats.
    Public API is always run_backtest() — this is the supertrend delegate.
    """
    p        = {**(params or {})}
    ticker   = coin_cfg["ticker"]
    interval = coin_cfg["interval"]

    # Apply per-coin defaults for keys the caller did not override
    _explicit = set(params or {})
    for key, default in [
        ("st_period",       coin_cfg.get("st_period",       10)),
        ("st_multiplier",   coin_cfg.get("st_multiplier",   3.0)),
        ("stop_loss_pct",   coin_cfg.get("stop_loss_pct",   0.010)),
        ("max_bars_in_trade", coin_cfg.get("max_bars_in_trade", 168)),
    ]:
        if key not in _explicit:
            p[key] = default

    if not silent:
        print(f"  {Fore.CYAN}Fetching {coin} ({ticker}, {interval}, {period})…"
              f"{Style.RESET_ALL}")
    df = _fetch(ticker, interval, period, hl_symbol=coin_cfg.get("hl_symbol", coin))

    if df is None:
        return {"coin": coin, "total_trades": 0, "error": "candle fetch failed"}

    min_bars = int(p["st_period"]) + 20
    if len(df) < min_bars:
        return {"coin": coin, "total_trades": 0,
                "error": f"only {len(df)} bars — need {min_bars} minimum"}

    try:
        date_range_days = (df.index[-1] - df.index[0]).days
    except Exception:
        date_range_days = 365

    if not silent:
        print(f"  {Fore.WHITE}{len(df)} bars ({date_range_days}d).{Style.RESET_ALL}")

    trades, final_capital, equity_curve = _run_supertrend_sim(df, p)

    stats = _compute_stats(coin, trades, final_capital, equity_curve,
                           period, date_range_days)
    stats["strategy_type"]     = "supertrend"
    stats["interval"]          = interval
    stats["st_period"]         = p["st_period"]
    stats["st_multiplier"]     = p["st_multiplier"]
    stats["stop_loss_pct"]     = p["stop_loss_pct"]
    stats["max_bars_in_trade"] = p["max_bars_in_trade"]
    return stats


# ─── DATA ─────────────────────────────────────────────────────────────────────

def _fetch(ticker: str, interval: str, period: str, hl_symbol: str | None = None) -> pd.DataFrame | None:
    """
    Fetch OHLCV via the Hyperliquid candle pipeline only.
    """
    try:
        from strategy import get_market_data
        return get_market_data(
            hl_symbol or ticker,
            interval,
            period,
            hl_symbol=hl_symbol,
            warmup_bars=250,
        )
    except Exception as e:
        print(Fore.RED + f"  Download error for {ticker}: {e}")
        return None


# ─── INDICATOR HELPERS ────────────────────────────────────────────────────────

def _calc_kc_mid(df: pd.DataFrame) -> float:
    """Return the current KC midline (EMA of Close) for this window."""
    try:
        return float(_safe(ta.ema(df["Close"], length=KC_PERIOD).iloc[-1]))
    except Exception:
        return 0.0


def _calc_ma_trend(df: pd.DataFrame) -> float:
    try:
        return float(_safe(ta.ema(df["Close"], length=MA_TREND).iloc[-1]))
    except Exception:
        return 0.0


# ─── SIGNAL LOGIC (param-aware) ───────────────────────────────────────────────

def _signal_for_window(df: pd.DataFrame, p: dict) -> tuple[str, str, float, float]:
    """
    Calculate indicators and return (action, reason, kc_mid, ma_trend_val).
    action: "long" | "short" | "hold"
    kc_mid: current KC midline value (used as TP target)
    ma_trend_val: current MA_TREND value (direction filter)

    p: merged params dict — keys: kc_scalar, rsi_oversold, rsi_overbought,
                                   hurst_cap, ma_trend_filter
    """
    try:
        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]

        ema_mid  = ta.ema(close, length=KC_PERIOD)
        atr      = ta.atr(high, low, close, length=KC_PERIOD)
        kc_upper = ema_mid + p["kc_scalar"] * atr
        kc_lower = ema_mid - p["kc_scalar"] * atr
        ma_trend = ta.ema(close, length=MA_TREND)
        rsi      = ta.rsi(close, length=RSI_PERIOD)

        price   = _safe(close.iloc[-1])
        kc_u    = _safe(kc_upper.iloc[-1])
        kc_l    = _safe(kc_lower.iloc[-1])
        kc_m    = _safe(ema_mid.iloc[-1])
        rsi_val = _safe(rsi.iloc[-1])
        mat     = _safe(ma_trend.iloc[-1])
        hurst   = _hurst(close)

        # ── Regime filter: skip fades in trending markets ─────────────────────
        if hurst > p["hurst_cap"]:
            return "hold", f"trending (H={hurst:.2f})", kc_m, mat

        # ── MA_TREND direction filter (optional) ──────────────────────────────
        if p["ma_trend_filter"]:
            price_above_trend = price > mat
            price_below_trend = price < mat
        else:
            # With filter off, we only need RSI + KC band — any direction is ok
            price_above_trend = True
            price_below_trend = True

        if price < kc_l and rsi_val < p["rsi_oversold"] and price_above_trend:
            return "long",  f"below KC lower, RSI {rsi_val:.1f}", kc_m, mat

        if price > kc_u and rsi_val > p["rsi_overbought"] and price_below_trend:
            return "short", f"above KC upper, RSI {rsi_val:.1f}", kc_m, mat

        return "hold", "no signal", kc_m, mat

    except Exception as e:
        return "hold", f"calc error: {e}", 0.0, 0.0


# ─── SIMULATION ───────────────────────────────────────────────────────────────

def _run_mean_reversion_sim(df: pd.DataFrame, p: dict) -> tuple[list, float, list]:
    """Compatibility wrapper for the shared mean-reversion simulation loop."""
    return run_mean_reversion_simulation(
        df,
        p,
        paper_capital=PAPER_CAPITAL,
        risk_per_trade=RISK_PER_TRADE,
        warmup=_WARMUP,
        calc_kc_mid=_calc_kc_mid,
        signal_for_window=_signal_for_window,
        include_timestamps=False,
    )

def run_backtest(coin: str, coin_cfg: dict, period: str | None = None,
                 params: dict | None = None, silent: bool = False) -> dict:
    """
    Walk-forward backtest for one coin. Returns performance metrics + trades.

    Routes automatically based on coin_cfg["strategy_type"]:
      • "supertrend"    → Supertrend flip entry/exit (ETH, BTC)
      • "mean_reversion" → KC+RSI scalp with midline TP (SOL, default)

    Parameters
    ----------
    coin     : coin label, e.g. "ETH"
    coin_cfg : entry from COINS dict (ticker, interval, period …)
    period   : configured lookback string; defaults to coin_cfg["period"] if None
    params   : optional dict of parameter overrides
    silent   : suppress console output (used by optimizer)
    """
    if period is None:
        period = coin_cfg.get("period", "60d")

    # Route supertrend coins to dedicated simulation
    if coin_cfg.get("strategy_type") == "supertrend":
        return _run_backtest_st(coin, coin_cfg, period, params, silent)

    p        = {**_DEFAULT_SIM_PARAMS, **(params or {})}
    ticker   = coin_cfg["ticker"]
    interval = coin_cfg["interval"]

    # Apply per-coin overrides from the COINS config entry — but only for keys
    # the caller did not explicitly set.  This lets the optimizer pass its own
    # values without being clobbered, while a plain run_backtest() call gets the
    # correct per-coin RSI thresholds and MA filter flag automatically.
    _explicit = set(params or {})
    if "rsi_oversold"      not in _explicit:
        p["rsi_oversold"]      = coin_cfg.get("rsi_oversold",      p["rsi_oversold"])
    if "rsi_overbought"    not in _explicit:
        p["rsi_overbought"]    = coin_cfg.get("rsi_overbought",    p["rsi_overbought"])
    if "ma_trend_filter"   not in _explicit:
        p["ma_trend_filter"]   = coin_cfg.get("ma_trend_filter",   p["ma_trend_filter"])
    if "stop_loss_pct"     not in _explicit:
        p["stop_loss_pct"]     = coin_cfg.get("stop_loss_pct",     p["stop_loss_pct"])
    if "take_profit_pct"   not in _explicit:
        p["take_profit_pct"]   = coin_cfg.get("take_profit_pct",   p["take_profit_pct"])
    if "max_bars_in_trade" not in _explicit:
        p["max_bars_in_trade"] = coin_cfg.get("max_bars_in_trade", p["max_bars_in_trade"])

    if not silent:
        print(f"  {Fore.CYAN}Fetching {coin} ({ticker}, {interval}, {period})…{Style.RESET_ALL}")
    df = _fetch(ticker, interval, period, hl_symbol=coin_cfg.get("hl_symbol", coin))

    if df is None:
        return {"coin": coin, "total_trades": 0, "error": "candle fetch failed"}
    if len(df) < _WARMUP + 10:
        return {"coin": coin, "total_trades": 0,
                "error": f"only {len(df)} bars — need {_WARMUP + 10} minimum"}

    try:
        date_range_days = (df.index[-1] - df.index[0]).days
    except Exception:
        date_range_days = 60

    if not silent:
        print(f"  {Fore.WHITE}{len(df)} bars ({date_range_days}d).{Style.RESET_ALL}")

    trades, capital, equity_curve = _run_mean_reversion_sim(df, p)

    stats = _compute_stats(coin, trades, capital, equity_curve,
                           period, date_range_days)
    # Attach effective params so the display layer can report them accurately
    # instead of relying on hardcoded strings.
    stats["interval"]          = interval
    stats["rsi_oversold"]      = p["rsi_oversold"]
    stats["rsi_overbought"]    = p["rsi_overbought"]
    stats["ma_trend_filter"]   = p["ma_trend_filter"]
    stats["stop_loss_pct"]     = p["stop_loss_pct"]
    stats["take_profit_pct"]   = p["take_profit_pct"]
    stats["max_bars_in_trade"] = p["max_bars_in_trade"]
    return stats


def run_friction_stress_test(
    coin: str,
    coin_cfg: dict,
    period: str | None = None,
    params: dict | None = None,
    scenarios: list[dict] | None = None,
    silent: bool = False,
) -> list[dict]:
    """Run the fixed friction stress-test matrix for one coin."""
    scenario_list = scenarios or FRICTION_STRESS_SCENARIOS
    results = []
    for idx, scenario in enumerate(scenario_list, start=1):
        stress_params = {
            **(params or {}),
            "fixed_round_trip_fee": scenario["fee"],
            "slippage_pct": scenario["slippage"],
            "entry_delay_bars": scenario["entry_delay"],
            "exit_delay_bars": scenario["exit_delay"],
        }
        stats = run_backtest(coin, coin_cfg, period=period, params=stress_params, silent=silent)
        results.append({
            "scenario": idx,
            "fee": scenario["fee"],
            "slippage": scenario["slippage"],
            "entry_delay": scenario["entry_delay"],
            "exit_delay": scenario["exit_delay"],
            "profit_factor": stats.get("profit_factor", 0),
            "sharpe_ratio": stats.get("sharpe_ratio", 0),
            "total_trades": stats.get("total_trades", 0),
            "total_pnl": stats.get("total_pnl", 0),
        })
    return results


# ─── METRICS ──────────────────────────────────────────────────────────────────

def _compute_stats(coin: str, trades: list, final_capital: float,
                   equity_curve: list, period: str,
                   date_range_days: int = 60) -> dict:
    return compute_core_backtest_stats(
        coin=coin,
        trades=trades,
        final_capital=final_capital,
        equity_curve=equity_curve,
        period=period,
        date_range_days=date_range_days,
        starting_capital=PAPER_CAPITAL,
    )


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def print_backtest_results(results: list[dict], period: str) -> None:
    print(f"\n  {Fore.CYAN}{'═'*54}")
    print(f"  {Fore.CYAN}  BACKTEST RESULTS  —  period: {period}")
    print(f"  {Fore.CYAN}{'═'*54}{Style.RESET_ALL}")

    any_result = False
    for r in results:
        coin = r.get("coin", "?")
        if r.get("total_trades", 0) == 0:
            print(f"\n  {Fore.YELLOW}{coin}: {r.get('error', 'no trades')}{Style.RESET_ALL}")
            continue

        any_result = True
        pnl_c = Fore.GREEN if r["total_pnl"] >= 0  else Fore.RED
        dd_c  = (Fore.RED    if r["max_drawdown"] > 10
                 else Fore.YELLOW if r["max_drawdown"] > 5
                 else Fore.GREEN)
        pf_c  = (Fore.GREEN  if r["profit_factor"] >= 1.5
                 else Fore.YELLOW if r["profit_factor"] >= 1.0
                 else Fore.RED)

        exits    = r.get("exit_breakdown", {})
        exit_str = "  ".join(f"{k}:{v}" for k, v in sorted(exits.items()))

        ivl      = r.get("interval", "?")
        sl_pct   = r.get("stop_loss_pct", 0)
        sl_str   = f"{sl_pct*100:.1f}%" if isinstance(sl_pct, float) else "?"
        max_bars = r.get("max_bars_in_trade", "?")
        print(f"\n  {Fore.CYAN}── {coin} {'─'*(48 - len(coin))}{Style.RESET_ALL}")

        if r.get("strategy_type") == "supertrend":
            st_p    = r.get("st_period", "?")
            st_mult = r.get("st_multiplier", "?")
            print(f"  {Fore.WHITE}[{ivl}]  Supertrend({st_p},{st_mult})  "
                  f"SL {sl_str}  max_bars={max_bars}  exit=ST-flip{Style.RESET_ALL}")
        else:
            rsi_os   = r.get("rsi_oversold",  "?")
            rsi_ob   = r.get("rsi_overbought", "?")
            tp_pct   = r.get("take_profit_pct", 0)
            tp_str   = f"{tp_pct*100:.1f}%" if isinstance(tp_pct, float) else "?"
            ma_label = "MA_filter=ON" if r.get("ma_trend_filter", True) else "MA_filter=OFF"
            print(f"  {Fore.WHITE}[{ivl}]  RSI {rsi_os}/{rsi_ob}  "
                  f"SL {sl_str}  TP {tp_str}  max_bars={max_bars}  {ma_label}{Style.RESET_ALL}")
        print(f"  Trades         : {r['total_trades']}   "
              f"Win rate : {r['win_rate']:.1f}%")
        print(f"  Total P&L      : {pnl_c}${r['total_pnl']:+,.2f}  "
              f"({r['pct_return']:+.1f}%){Style.RESET_ALL}")
        print(f"  Avg win / loss : ${r['avg_win']:+.2f} / ${r['avg_loss']:+.2f}   "
              f"Profit factor: {pf_c}{r['profit_factor']}{Style.RESET_ALL}")
        print(f"  Max drawdown   : {dd_c}{r['max_drawdown']:.1f}%{Style.RESET_ALL}   "
              f"Max consec losses: {r['max_consec_losses']}")
        print(f"  Sharpe         : {r['sharpe_ratio']}   "
              f"Sortino: {r['sortino_ratio']}")
        print(f"  Final capital  : ${r['final_capital']:,.2f}   "
              f"(started ${PAPER_CAPITAL:,.2f})")
        print(f"  Exit breakdown : {exit_str}")

    if any_result:
        valid        = [r for r in results if r.get("total_trades", 0) > 0]
        combined_pnl = sum(r["total_pnl"] for r in valid)
        avg_wr       = sum(r["win_rate"]   for r in valid) / len(valid)
        pnl_c        = Fore.GREEN if combined_pnl >= 0 else Fore.RED
        print(f"\n  {Fore.CYAN}── COMBINED {'─'*39}{Style.RESET_ALL}")
        print(f"  Combined P&L   : {pnl_c}${combined_pnl:+,.2f}{Style.RESET_ALL}   "
              f"Avg win rate: {avg_wr:.1f}%")

    print(f"\n  {Fore.CYAN}{'═'*54}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}ST coins: flip entry/exit · MR coins: KC midline TP")
    print(f"  No slippage/fees. Signal quality check only.\n")


def print_trade_list(results: list[dict], max_per_coin: int = 10) -> None:
    for r in results:
        if r.get("total_trades", 0) == 0:
            continue
        coin   = r["coin"]
        trades = r.get("trades", [])[-max_per_coin:]
        if not trades:
            continue
        print(f"\n  {Fore.CYAN}Last {len(trades)} trades — {coin}{Style.RESET_ALL}")
        print(f"  {'Side':<6} {'Entry':>10} {'Exit':>10} {'P&L':>8} {'%':>7}  {'Bars':>5}  Reason")
        print(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*8} {'─'*7}  {'─'*5}  {'─'*14}")
        for t in trades:
            pnl_c  = Fore.GREEN if t["pnl"] >= 0 else Fore.RED
            side_c = Fore.GREEN if t["side"] == "long" else Fore.RED
            print(f"  {side_c}{t['side']:<6}{Style.RESET_ALL} "
                  f"{t['entry']:>10.4f} {t['exit']:>10.4f} "
                  f"{pnl_c}{t['pnl']:>+8.2f} {t['pnl_pct']:>+6.2f}%{Style.RESET_ALL}  "
                  f"{t['bars']:>5}  {t['reason']}")
