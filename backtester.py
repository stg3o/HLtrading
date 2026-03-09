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
import yfinance as yf
import pandas_ta as ta
from colorama import Fore, Style

from config import (
    KC_PERIOD, KC_SCALAR, MA_FAST, MA_SLOW, MA_TREND, RSI_PERIOD,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT, RISK_PER_TRADE, PAPER_CAPITAL,
    RSI_OVERSOLD, RSI_OVERBOUGHT, COINS,
)
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


# ─── SUPERTREND SIMULATION ────────────────────────────────────────────────────

def _run_supertrend_sim(df: pd.DataFrame, p: dict) -> tuple[list, float, list]:
    """
    Core Supertrend simulation loop.  Returns (trades, final_capital, equity_curve).

    Entry : confirmed flip bar (direction[i] != direction[i-1]).
    Exit 1: opposing flip — trend has reversed, take profit.
    Exit 2: hard stop-loss at entry × (1 ± stop_loss_pct) — safety net only.
    Exit 3: time stop after max_bars_in_trade bars.
    """
    high  = df["High"].to_numpy(dtype=float)
    low   = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)

    st_period     = int(p.get("st_period",      10))
    st_multiplier = float(p.get("st_multiplier", 3.0))
    stop_loss_pct = float(p.get("stop_loss_pct",  0.010))
    max_bars      = int(p.get("max_bars_in_trade", 168))

    direction, _ = _supertrend_arrays(high, low, close, st_period, st_multiplier)

    warmup       = st_period + 5
    capital      = float(PAPER_CAPITAL)
    equity_peak  = capital
    position     = None
    trades       = []
    equity_curve = [capital]

    for i in range(warmup, len(df)):
        bar_high  = high[i]
        bar_low   = low[i]
        bar_close = close[i]

        # ── Manage open position ───────────────────────────────────────────────
        if position:
            bars_held = i - position["bar_in"]
            hit = None

            # Exit 1: opposing flip (main exit — trend reversed)
            if position["side"] == "long"  and direction[i] == -1 and direction[i-1] == 1:
                hit = ("st_flip", bar_close)
            elif position["side"] == "short" and direction[i] ==  1 and direction[i-1] == -1:
                hit = ("st_flip", bar_close)

            # Exit 2: hard stop-loss (safety net)
            if hit is None:
                if position["side"] == "long"  and bar_low  <= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif position["side"] == "short" and bar_high >= position["sl"]:
                    hit = ("stop_loss", position["sl"])

            # Exit 3: time stop
            if hit is None and bars_held >= max_bars:
                hit = ("time_stop", bar_close)

            if hit:
                reason, exit_price = hit
                if position["side"] == "long":
                    pnl = (exit_price - position["entry"]) * position["size_units"]
                else:
                    pnl = (position["entry"] - exit_price) * position["size_units"]

                capital     += pnl
                equity_peak  = max(equity_peak, capital)
                trades.append({
                    "side":    position["side"],
                    "entry":   position["entry"],
                    "exit":    round(exit_price, 4),
                    "pnl":     round(pnl, 4),
                    "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
                    "reason":  reason,
                    "bars":    bars_held,
                })
                position = None

            equity_curve.append(capital)
            continue   # no re-entry on the bar a position closes

        # ── Look for entry: confirmed flip this bar ────────────────────────────
        if direction[i] == direction[i - 1]:
            equity_curve.append(capital)
            continue

        side = "long" if direction[i] == 1 else "short"
        sl   = (round(bar_close * (1 - stop_loss_pct), 6) if side == "long"
                else round(bar_close * (1 + stop_loss_pct), 6))

        risk_usd   = capital * RISK_PER_TRADE
        size_usd   = risk_usd / stop_loss_pct
        size_units = size_usd / bar_close if bar_close > 0 else 0

        position = {
            "side":       side,
            "entry":      bar_close,
            "size_usd":   size_usd,
            "size_units": size_units,
            "sl":         sl,
            "bar_in":     i,
        }
        equity_curve.append(capital)

    # Force-close at end of data
    if position:
        last_close = close[-1]
        if position["side"] == "long":
            pnl = (last_close - position["entry"]) * position["size_units"]
        else:
            pnl = (position["entry"] - last_close) * position["size_units"]
        capital += pnl
        trades.append({
            "side":    position["side"],
            "entry":   position["entry"],
            "exit":    round(last_close, 4),
            "pnl":     round(pnl, 4),
            "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
            "reason":  "end_of_data",
            "bars":    len(df) - 1 - position["bar_in"],
        })

    return trades, capital, equity_curve


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
    df = _fetch(ticker, interval, period)

    if df is None:
        return {"coin": coin, "total_trades": 0, "error": "data download failed"}

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

def _fetch(ticker: str, interval: str, period: str) -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, interval=interval, period=period,
                         auto_adjust=True, progress=False, timeout=30)
        if df is None or df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        return df
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
    period   : yfinance lookback string; defaults to coin_cfg["period"] if None
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
    df = _fetch(ticker, interval, period)

    if df is None:
        return {"coin": coin, "total_trades": 0, "error": "data download failed"}
    if len(df) < _WARMUP + 10:
        return {"coin": coin, "total_trades": 0,
                "error": f"only {len(df)} bars — need {_WARMUP + 10} minimum"}

    try:
        date_range_days = (df.index[-1] - df.index[0]).days
    except Exception:
        date_range_days = 60

    if not silent:
        print(f"  {Fore.WHITE}{len(df)} bars ({date_range_days}d).{Style.RESET_ALL}")

    capital       = float(PAPER_CAPITAL)
    equity_peak   = capital
    position      = None
    trades        = []
    equity_curve  = [capital]

    stop_loss_pct     = p["stop_loss_pct"]
    take_profit_pct   = p["take_profit_pct"]
    min_rr            = p["min_rr_ratio"]
    max_bars_in_trade = p["max_bars_in_trade"]

    for i in range(_WARMUP, len(df)):
        window    = df.iloc[:i + 1]
        row       = df.iloc[i]
        bar_high  = float(row["High"])
        bar_low   = float(row["Low"])
        bar_close = float(row["Close"])

        # ── Open position: check SL, dynamic KC midline TP, or time-stop ──────
        if position:
            bars_held      = i - position["bar_in"]
            current_kc_mid = _calc_kc_mid(window)   # dynamic TP target
            hit            = None

            if position["side"] == "long":
                if bar_low <= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif current_kc_mid > 0 and bar_high >= current_kc_mid:
                    hit = ("tp_midline", min(bar_high, current_kc_mid))
                elif bar_high >= position["tp_fallback"]:
                    hit = ("tp_fixed", position["tp_fallback"])
                elif bars_held >= max_bars_in_trade:
                    hit = ("time_stop", bar_close)
            else:  # short
                if bar_high >= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif current_kc_mid > 0 and bar_low <= current_kc_mid:
                    hit = ("tp_midline", max(bar_low, current_kc_mid))
                elif bar_low <= position["tp_fallback"]:
                    hit = ("tp_fixed", position["tp_fallback"])
                elif bars_held >= max_bars_in_trade:
                    hit = ("time_stop", bar_close)

            if hit:
                reason, exit_price = hit
                if position["side"] == "long":
                    pnl = (exit_price - position["entry"]) * position["size_units"]
                else:
                    pnl = (position["entry"] - exit_price) * position["size_units"]

                capital    += pnl
                equity_peak = max(equity_peak, capital)
                trades.append({
                    "side":    position["side"],
                    "entry":   position["entry"],
                    "exit":    round(exit_price, 4),
                    "pnl":     round(pnl, 4),
                    "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
                    "reason":  reason,
                    "bars":    bars_held,
                })
                position = None

            equity_curve.append(capital)
            continue  # no re-entry on the bar a position closes

        # ── No position: look for entry ───────────────────────────────────────
        action, reason, kc_mid, mat = _signal_for_window(window, p)

        if action in ("long", "short"):
            sl_dist = bar_close * stop_loss_pct

            if action == "long":
                tp_mid_dist = max(kc_mid - bar_close, 0)
                tp_fallback = round(bar_close * (1 + take_profit_pct), 6)
                tp_target   = kc_mid if tp_mid_dist >= bar_close * take_profit_pct else tp_fallback
            else:
                tp_mid_dist = max(bar_close - kc_mid, 0)
                tp_fallback = round(bar_close * (1 - take_profit_pct), 6)
                tp_target   = kc_mid if tp_mid_dist >= bar_close * take_profit_pct else tp_fallback

            tp_dist = abs(bar_close - tp_target) if tp_target else bar_close * take_profit_pct

            # R:R gate — skip low-quality setups
            if sl_dist > 0 and (tp_dist / sl_dist) < min_rr:
                equity_curve.append(capital)
                continue

            risk_usd   = capital * RISK_PER_TRADE
            size_usd   = risk_usd / stop_loss_pct
            size_units = size_usd / bar_close if bar_close > 0 else 0

            sl = round(bar_close * (1 - stop_loss_pct), 6) if action == "long" \
                 else round(bar_close * (1 + stop_loss_pct), 6)

            position = {
                "side":        action,
                "entry":       bar_close,
                "size_usd":    size_usd,
                "size_units":  size_units,
                "sl":          sl,
                "tp_fallback": tp_fallback,
                "bar_in":      i,
                "reason":      reason,
            }

        equity_curve.append(capital)

    # ── Force-close open position at last bar ─────────────────────────────────
    if position:
        last_close = float(df.iloc[-1]["Close"])
        if position["side"] == "long":
            pnl = (last_close - position["entry"]) * position["size_units"]
        else:
            pnl = (position["entry"] - last_close) * position["size_units"]
        capital += pnl
        trades.append({
            "side":    position["side"],
            "entry":   position["entry"],
            "exit":    round(last_close, 4),
            "pnl":     round(pnl, 4),
            "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
            "reason":  "end_of_data",
            "bars":    len(df) - 1 - position["bar_in"],
        })

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


# ─── METRICS ──────────────────────────────────────────────────────────────────

def _compute_stats(coin: str, trades: list, final_capital: float,
                   equity_curve: list, period: str,
                   date_range_days: int = 60) -> dict:
    if not trades:
        return {"coin": coin, "total_trades": 0, "period": period,
                "error": "no trades — setup too conservative or not enough data"}

    pnls     = [t["pnl"]     for t in trades]
    pnl_pcts = [t["pnl_pct"] / 100 for t in trades]

    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total  = len(pnls)

    win_rate      = len(wins) / total * 100 if total else 0
    total_pnl     = sum(pnls)
    pct_return    = total_pnl / PAPER_CAPITAL * 100
    avg_win       = sum(wins)   / len(wins)   if wins   else 0
    avg_loss      = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    exit_counts = {}
    for t in trades:
        r = t.get("reason", "unknown")
        exit_counts[r] = exit_counts.get(r, 0) + 1

    max_cl = cur = 0
    for p in pnls:
        cur    = cur + 1 if p <= 0 else 0
        max_cl = max(max_cl, cur)

    peak   = equity_curve[0] if equity_curve else float(PAPER_CAPITAL)
    max_dd = 0.0
    for v in equity_curve:
        peak   = max(peak, v)
        dd     = (peak - v) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    trades_per_year = max(1, int(total / max(date_range_days, 1) * 365))
    rf              = 0.0434 / trades_per_year
    excess          = [r - rf for r in pnl_pcts]
    n               = len(excess)
    mean_e          = sum(excess) / n
    var             = sum((x - mean_e) ** 2 for x in excess) / max(n - 1, 1)
    std_e           = math.sqrt(var) if var > 0 else 0.0
    sharpe          = math.sqrt(trades_per_year) * (mean_e / std_e) if std_e > 1e-8 else 0.0

    neg     = [x for x in excess if x < 0]
    if neg:
        ds      = math.sqrt(sum(x ** 2 for x in neg) / len(neg))
        sortino = math.sqrt(trades_per_year) * (mean_e / ds) if ds > 1e-8 else (
            float("inf") if mean_e > 0 else 0.0)
    else:
        sortino = float("inf") if mean_e > 0 else 0.0

    return {
        "coin":              coin,
        "period":            period,
        "total_trades":      total,
        "win_rate":          round(win_rate,      1),
        "total_pnl":         round(total_pnl,     2),
        "pct_return":        round(pct_return,    2),
        "avg_win":           round(avg_win,        2),
        "avg_loss":          round(avg_loss,       2),
        "profit_factor":     round(profit_factor,  2),
        "max_consec_losses": max_cl,
        "max_drawdown":      round(max_dd,         1),
        "sharpe_ratio":      round(sharpe,         3),
        "sortino_ratio":     round(sortino, 3) if sortino != float("inf") else "∞",
        "final_capital":     round(final_capital,  2),
        "exit_breakdown":    exit_counts,
        "trades":            trades,
    }


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
