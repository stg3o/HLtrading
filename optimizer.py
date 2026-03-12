"""
optimizer.py — per-coin parameter grid-search for the KC scalping strategy.

Each coin is optimized independently using its own timeframe from config:
  - ETH: 1h / 365d  — hourly mean-reversion on a full year of data
  - BTC: 1h / 365d  — same
  - SOL: 5m / 60d   — fast scalp timeframe

Grid sweeps 72 combos per coin:
  kc_scalar       : [1.0, 1.25, 1.5, 2.0]
  rsi_oversold    : [35, 40, 45]         (rsi_overbought = 100 - rsi_oversold)
  ma_trend_filter : [True, False]
  stop_loss_pct   : [0.002, 0.003, 0.004]   (0.1% removed — unrealistic live)
  hurst_cap       : [0.45]               (pinned — all 4 cap values produced identical
                                          results across 9 coins in the Mar-2026 run;
                                          Hurst never exceeded 0.45 in any 60d window.
                                          Restore to [0.45, 0.50, 0.55, 0.65] if regime
                                          conditions change significantly.)
= 4 × 3 × 2 × 3 × 1 = 72 combos per coin

Performance: O(n) per simulation — all indicators precomputed as numpy arrays.
Each bar is a pure Python comparison + arithmetic; no pandas_ta inside the loop.

Scoring: per-coin, independently.
  A combo qualifies if total_trades >= MIN_TRADES and total_pnl > 0.
  Score = profit_factor (tiebreaker: win_rate).

Results saved to best_configs.json as {coin: [top_N_result_dicts]}.
"""
import json
import time
import itertools
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from colorama import Fore, Style

from backtester import _fetch, _DEFAULT_SIM_PARAMS
from config import COINS, PAPER_CAPITAL, RISK_PER_TRADE, BEST_CONFIGS_FILE, HL_MAX_POSITION_USD
from config import KC_PERIOD, MA_TREND, RSI_PERIOD


# ─── OPTIMIZER SETTINGS ───────────────────────────────────────────────────────

MIN_TRADES_5M = 30     # minimum trades for 5m coins (60d of data).
                       # 30 trades over 60d = ~1 trade/2 days — minimum for
                       # any statistical claim.  5 was too low: 13-trade configs
                       # were "winning" with ±25pp margin of error on win rate.
MIN_TRADES_1H = 15     # minimum trades for 1h coins (365d of data).
                       # Not binding for supertrend (generates 100-280 trades).
#   ↑ BTC produced 6-trade configs that ranked #1 purely by pf; 15 gates those out.
TOP_N         = 10     # top results stored per coin
_HURST_WINDOW = 100    # bars for rolling Hurst estimate
_HURST_LAGS   = 20     # max lag for Hurst calculation

GRID = {
    "kc_scalar":       [1.0, 1.25, 1.5, 2.0],
    "rsi_oversold":    [35, 40, 45],
    "ma_trend_filter": [True, False],
    "stop_loss_pct":   [0.002, 0.003, 0.004],
    "hurst_cap":       [0.45],   # pinned — see docstring above
}

# Supertrend grid: period × multiplier × sl = 3 × 4 × 3 = 36 combos
# SL is a safety-net hard stop; primary exit is the Supertrend flip.
SUPERTREND_GRID = {
    "st_period":     [7, 10, 14],
    "st_multiplier": [2.0, 2.5, 3.0, 3.5],
    "stop_loss_pct": [0.008, 0.012, 0.018],
}

# Per-coin parameter overrides — any key here is pinned to the given value
# instead of being swept. The grid still runs for all other keys.
#
# SOL: two full runs showed kc_scalar 1.0/1.25/1.5/2.0 all produce identical
# results (same trades, same pf). RSI<40 + MA_filter is the real gate on 5m
# SOL; price is already near the KC lower band whenever RSI hits that level.
# Sweeping kc_scalar wastes 4x compute for zero information. Pin at 1.0.
GRID_OVERRIDES: dict[str, dict] = {
    "SOL": {"kc_scalar": 1.0},
}

# hurst_cap is now a grid parameter — see GRID above.
# Default fallback if a caller omits it (e.g. walk-forward baseline):
_DEFAULT_HURST_CAP = 0.65


# ─── PRECOMPUTED COIN CACHE ───────────────────────────────────────────────────

@dataclass
class _CoinCache:
    """All indicator arrays for one coin, precomputed from the full DataFrame."""
    coin:            str
    interval:        str
    period:          str
    n:               int
    date_range_days: int

    close:    np.ndarray
    high:     np.ndarray
    low:      np.ndarray

    ema_mid:  np.ndarray   # EMA(close, KC_PERIOD)  — KC midline + TP target
    atr:      np.ndarray   # ATR(high,low,close, KC_PERIOD)
    rsi:      np.ndarray   # RSI(close, RSI_PERIOD)
    ma_tr:    np.ndarray   # EMA(close, MA_TREND)
    hurst:    np.ndarray   # rolling Hurst[i] over bars [i-WINDOW, i]

    warmup:   int = 0      # first valid bar index


def _ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average (Wilder-smoothed)."""
    k   = 2.0 / (period + 1)
    out = np.full(len(arr), np.nan)
    seed_end = period - 1
    if seed_end >= len(arr):
        return out
    out[seed_end] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi_np(close: np.ndarray, period: int) -> np.ndarray:
    """Wilder-smoothed RSI."""
    out    = np.full(len(close), np.nan)
    delta  = np.diff(close)
    gains  = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    if len(gains) < period:
        return out

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs       = avg_gain / avg_loss if avg_loss > 1e-10 else 1e10
        out[i + 1] = 100 - 100 / (1 + rs)

    return out


def _atr_np(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder-smoothed ATR."""
    n   = len(close)
    out = np.full(n, np.nan)
    tr  = np.zeros(n)

    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i]  - close[i - 1]))

    if n < period:
        return out

    out[period - 1] = np.mean(tr[:period])
    k = 1.0 / period
    for i in range(period, n):
        out[i] = tr[i] * k + out[i - 1] * (1 - k)

    return out


def _rolling_hurst(close: np.ndarray, window: int, max_lag: int) -> np.ndarray:
    """
    Rolling Hurst exponent.
    out[i] = Hurst estimated from close[i-window : i+1], NaN if insufficient data.
    """
    n        = len(close)
    out      = np.full(n, np.nan)
    lags     = list(range(2, max_lag))
    log_lags = np.log(lags)

    for i in range(window - 1, n):
        seg = close[i - window + 1: i + 1]
        try:
            tau = [
                max(1e-8, float(np.sqrt(np.std(seg[lag:] - seg[:-lag]))))
                for lag in lags
            ]
            coef   = np.polyfit(log_lags, np.log(tau), 1)
            out[i] = coef[0]
        except Exception:
            out[i] = 0.5

    return out


def _precompute(coin: str, interval: str, df, period: str) -> "_CoinCache | None":
    """
    Build a _CoinCache from a downloaded DataFrame.
    Returns None if data is insufficient.
    """
    close = df["Close"].values.astype(float)
    high  = df["High"].values.astype(float)
    low   = df["Low"].values.astype(float)
    n     = len(close)

    warmup = max(MA_TREND, KC_PERIOD, RSI_PERIOD, _HURST_WINDOW) + 10
    if n < warmup + 10:
        return None

    try:
        date_range_days = (df.index[-1] - df.index[0]).days
    except Exception:
        date_range_days = 60

    ema_mid = _ema_np(close, KC_PERIOD)
    atr_arr = _atr_np(high, low, close, KC_PERIOD)
    rsi_arr = _rsi_np(close, RSI_PERIOD)
    ma_arr  = _ema_np(close, MA_TREND)
    h_arr   = _rolling_hurst(close, _HURST_WINDOW, _HURST_LAGS)

    return _CoinCache(
        coin=coin, interval=interval, period=period, n=n,
        date_range_days=date_range_days,
        close=close, high=high, low=low,
        ema_mid=ema_mid, atr=atr_arr,
        rsi=rsi_arr, ma_tr=ma_arr,
        hurst=h_arr, warmup=warmup,
    )


# ─── FAST SIMULATION (O(n) per combo) ────────────────────────────────────────

def _fast_sim(cache: "_CoinCache", params: dict,
              start_i: int | None = None,
              end_i:   int | None = None) -> dict:
    """
    Walk-forward simulation using precomputed indicator arrays.
    No pandas_ta calls inside the loop — pure numpy/Python comparisons.
    """
    from backtester import _compute_stats

    p = {**_DEFAULT_SIM_PARAMS, **params}

    kc_scalar  = float(p["kc_scalar"])
    rsi_os     = float(p["rsi_oversold"])
    rsi_ob     = float(p["rsi_overbought"])
    hurst_cap  = float(p.get("hurst_cap", _DEFAULT_HURST_CAP))
    ma_filter  = bool(p["ma_trend_filter"])
    sl_pct     = float(p["stop_loss_pct"])
    tp_pct     = float(p["take_profit_pct"])
    min_rr     = float(p["min_rr_ratio"])
    max_bars   = int(p["max_bars_in_trade"])

    close    = cache.close
    high     = cache.high
    low      = cache.low
    ema_mid  = cache.ema_mid
    atr      = cache.atr
    rsi      = cache.rsi
    ma_tr    = cache.ma_tr
    hurst    = cache.hurst
    n        = cache.n
    warmup   = cache.warmup

    _start = start_i if start_i is not None else warmup
    _end   = end_i   if end_i   is not None else n

    capital      = float(PAPER_CAPITAL)
    equity_peak  = capital
    position     = None
    trades       = []
    equity_curve = [capital]

    for i in range(_start, _end):
        bar_close = close[i]
        bar_high  = high[i]
        bar_low   = low[i]
        mid_i     = ema_mid[i]
        atr_i     = atr[i]

        # ── Manage open position ──────────────────────────────────────────────
        if position is not None:
            bars_held      = i - position["bar_in"]
            current_kc_mid = mid_i if not np.isnan(mid_i) else 0.0
            hit            = None

            if position["side"] == "long":
                if bar_low <= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif current_kc_mid > 0 and bar_high >= current_kc_mid:
                    hit = ("tp_midline", min(bar_high, current_kc_mid))
                elif bar_high >= position["tp_fallback"]:
                    hit = ("tp_fixed", position["tp_fallback"])
                elif bars_held >= max_bars:
                    hit = ("time_stop", bar_close)
            else:
                if bar_high >= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif current_kc_mid > 0 and bar_low <= current_kc_mid:
                    hit = ("tp_midline", max(bar_low, current_kc_mid))
                elif bar_low <= position["tp_fallback"]:
                    hit = ("tp_fixed", position["tp_fallback"])
                elif bars_held >= max_bars:
                    hit = ("time_stop", bar_close)

            if hit:
                reason, exit_price = hit
                pnl = ((exit_price - position["entry"]) * position["size_units"]
                       if position["side"] == "long"
                       else (position["entry"] - exit_price) * position["size_units"])
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
            continue

        # ── Look for entry ────────────────────────────────────────────────────
        if np.isnan(mid_i) or np.isnan(atr_i):
            equity_curve.append(capital)
            continue

        kc_upper_i = mid_i + kc_scalar * atr_i
        kc_lower_i = mid_i - kc_scalar * atr_i

        rsi_i   = rsi[i]
        mat_i   = ma_tr[i]
        hurst_i = hurst[i]

        if np.isnan(rsi_i) or np.isnan(mat_i) or np.isnan(hurst_i):
            equity_curve.append(capital)
            continue

        # Regime filter
        if hurst_i > hurst_cap:
            equity_curve.append(capital)
            continue

        # Direction filter
        above_trend = bar_close > mat_i
        below_trend = bar_close < mat_i

        action = "hold"
        if bar_close < kc_lower_i and rsi_i < rsi_os:
            if (not ma_filter) or above_trend:
                action = "long"
        elif bar_close > kc_upper_i and rsi_i > rsi_ob:
            if (not ma_filter) or below_trend:
                action = "short"

        if action in ("long", "short"):
            sl_dist = bar_close * sl_pct

            if action == "long":
                tp_mid_dist = max(mid_i - bar_close, 0.0)
                tp_fallback = bar_close * (1 + tp_pct)
                tp_target   = mid_i if tp_mid_dist >= bar_close * tp_pct else tp_fallback
            else:
                tp_mid_dist = max(bar_close - mid_i, 0.0)
                tp_fallback = bar_close * (1 - tp_pct)
                tp_target   = mid_i if tp_mid_dist >= bar_close * tp_pct else tp_fallback

            tp_dist = abs(bar_close - tp_target)

            if sl_dist > 0 and (tp_dist / sl_dist) < min_rr:
                equity_curve.append(capital)
                continue

            # Fixed-capital sizing: use starting PAPER_CAPITAL, not running equity.
            # Prevents compounding from inflating notional (and thus PnL) across
            # thousands of trades.  Cap at HL_MAX_POSITION_USD to match live bot.
            risk_usd   = float(PAPER_CAPITAL) * RISK_PER_TRADE
            size_usd   = min(risk_usd / sl_pct, HL_MAX_POSITION_USD)
            size_units = size_usd / bar_close if bar_close > 0 else 0

            sl = (bar_close * (1 - sl_pct) if action == "long"
                  else bar_close * (1 + sl_pct))

            position = {
                "side":        action,
                "entry":       bar_close,
                "size_usd":    size_usd,
                "size_units":  size_units,
                "sl":          sl,
                "tp_fallback": tp_fallback,
                "bar_in":      i,
            }

        equity_curve.append(capital)

    # Force-close open position at last bar
    if position is not None:
        last_close = close[-1]
        pnl = ((last_close - position["entry"]) * position["size_units"]
               if position["side"] == "long"
               else (position["entry"] - last_close) * position["size_units"])
        capital += pnl
        trades.append({
            "side":    position["side"],
            "entry":   position["entry"],
            "exit":    round(last_close, 4),
            "pnl":     round(pnl, 4),
            "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
            "reason":  "end_of_data",
            "bars":    n - 1 - position["bar_in"],
        })

    return _compute_stats(cache.coin, trades, capital, equity_curve,
                          cache.period, cache.date_range_days)


def _fast_sim_supertrend(cache: "_CoinCache", params: dict,
                         start_i: int | None = None,
                         end_i:   int | None = None) -> dict:
    """
    O(n) Supertrend simulation.
    Entry: on the bar when Supertrend direction flips.
    Primary exit: on the next opposing flip.
    Secondary exit: hard stop-loss (safety net).
    Tertiary exit: max_bars_in_trade time stop.
    """
    from backtester import _compute_stats

    st_period     = int(params.get("st_period",     10))
    st_multiplier = float(params.get("st_multiplier", 3.0))
    sl_pct        = float(params.get("stop_loss_pct",  0.01))
    max_bars      = int(params.get("max_bars_in_trade", 168))

    close  = cache.close
    high   = cache.high
    low    = cache.low
    n      = cache.n
    warmup = cache.warmup

    _start = start_i if start_i is not None else warmup
    _end   = end_i   if end_i   is not None else n

    # ── Compute Supertrend arrays for the full series ─────────────────────────
    # (Always use full series so band memory is correct even for sub-windows)
    prev_c = np.concatenate(([close[0]], close[:-1]))
    tr     = np.maximum(high - low,
             np.maximum(np.abs(high - prev_c),
                        np.abs(low  - prev_c)))
    atr    = np.full(n, np.nan)
    if st_period <= n:
        atr[st_period - 1] = np.mean(tr[:st_period])
        for i in range(st_period, n):
            atr[i] = (atr[i - 1] * (st_period - 1) + tr[i]) / st_period

    mid         = (high + low) / 2.0
    upper_basic = mid + st_multiplier * atr
    lower_basic = mid - st_multiplier * atr
    upper       = np.copy(upper_basic)
    lower       = np.copy(lower_basic)
    direction   = np.zeros(n, dtype=np.int8)
    st_line     = np.full(n, np.nan)

    s = st_period
    if s < n:
        direction[s] = 1
        st_line[s]   = lower[s]
        for i in range(s + 1, n):
            if np.isnan(upper[i]) or np.isnan(lower[i]):
                direction[i] = direction[i - 1]
                continue
            upper[i] = (min(upper_basic[i], upper[i - 1])
                        if close[i - 1] <= upper[i - 1] else upper_basic[i])
            lower[i] = (max(lower_basic[i], lower[i - 1])
                        if close[i - 1] >= lower[i - 1] else lower_basic[i])
            if   close[i] > upper[i - 1]: direction[i] =  1
            elif close[i] < lower[i - 1]: direction[i] = -1
            else:                          direction[i]  = direction[i - 1]
            st_line[i] = lower[i] if direction[i] == 1 else upper[i]

    # ── Walk-forward simulation ───────────────────────────────────────────────
    capital      = float(PAPER_CAPITAL)
    equity_peak  = capital
    position     = None
    trades       = []
    equity_curve = [capital]

    for i in range(max(_start, s + 1), _end):
        bar_close = close[i]
        d_now     = direction[i]
        d_prev    = direction[i - 1]
        flipped   = d_now != d_prev

        # ── Manage open position ──────────────────────────────────────────────
        if position is not None:
            bars_held = i - position["bar_in"]
            hit       = None

            if position["side"] == "long":
                if bar_close <= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif d_now == -1 and flipped:           # ST flipped bearish
                    hit = ("st_flip", bar_close)
                elif bars_held >= max_bars:
                    hit = ("time_stop", bar_close)
            else:  # short
                if bar_close >= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif d_now == 1 and flipped:            # ST flipped bullish
                    hit = ("st_flip", bar_close)
                elif bars_held >= max_bars:
                    hit = ("time_stop", bar_close)

            if hit:
                reason, exit_price = hit
                pnl = ((exit_price - position["entry"]) * position["size_units"]
                       if position["side"] == "long"
                       else (position["entry"] - exit_price) * position["size_units"])
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
            continue

        # ── Look for entry: only on a confirmed flip ──────────────────────────
        if not flipped or np.isnan(st_line[i]):
            equity_curve.append(capital)
            continue

        action = "long" if d_now == 1 else "short"
        sl     = (bar_close * (1 - sl_pct) if action == "long"
                  else bar_close * (1 + sl_pct))
        # Fixed-capital sizing — same fix as mean-reversion sim above.
        risk_usd   = float(PAPER_CAPITAL) * RISK_PER_TRADE
        size_usd   = min(risk_usd / sl_pct, HL_MAX_POSITION_USD)
        size_units = size_usd / bar_close if bar_close > 0 else 0

        position = {
            "side":       action,
            "entry":      bar_close,
            "size_usd":   size_usd,
            "size_units": size_units,
            "sl":         sl,
            "bar_in":     i,
        }
        equity_curve.append(capital)

    # Close any open position at end of window
    if position is not None:
        last_close = close[_end - 1]
        pnl = ((last_close - position["entry"]) * position["size_units"]
               if position["side"] == "long"
               else (position["entry"] - last_close) * position["size_units"])
        capital += pnl
        trades.append({
            "side":    position["side"],
            "entry":   position["entry"],
            "exit":    round(last_close, 4),
            "pnl":     round(pnl, 4),
            "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
            "reason":  "end_of_data",
            "bars":    (_end - 1) - position["bar_in"],
        })

    return _compute_stats(cache.coin, trades, capital, equity_curve,
                          cache.period, cache.date_range_days)


# ─── SCORING ──────────────────────────────────────────────────────────────────

def _min_trades_for(interval: str) -> int:
    """Per-timeframe minimum trade count.

    5m / 60d window: floor raised to 30 (≈1 trade per 2 days).
    Below this, win-rate confidence intervals are ±25 pp or worse —
    the optimizer would be selecting lucky streaks, not real edge.
    If no config passes 30 trades on SOL, mean-reversion is structurally
    too selective on the current 5m window.

    1h / 365d: floor stays at 15 — not binding for supertrend coins which
    generate 100–280 trades, just a sanity gate against empty results.
    """
    return MIN_TRADES_1H if interval in ("1h", "4h", "1d") else MIN_TRADES_5M


def _score_single(result: dict, min_trades: int = MIN_TRADES_5M) -> tuple:
    """Score a single coin's result.

    Returns (profit_factor, win_rate, sharpe) — all three used as sort keys
    in descending order:
      1. profit_factor — primary score
      2. win_rate      — tiebreaker (more consistent is better)
      3. sharpe        — second tiebreaker (risk-adjusted return, can be negative)

    Returns (0, 0, 0) if the result fails any qualification gate.
    """
    if result.get("total_trades", 0) < min_trades:
        return 0.0, 0.0, 0.0
    if result.get("total_pnl", -1) < 0:
        return 0.0, 0.0, 0.0
    pf = result.get("profit_factor", 0)
    if pf == float("inf") or str(pf) == "inf":
        pf = 10.0
    sharpe = _safe_float(result.get("sharpe_ratio", 0))
    return float(pf), float(result.get("win_rate", 0)), sharpe


def _fmt_pf(pf) -> str:
    """Format a profit_factor value for display (handles inf strings from JSON)."""
    try:
        val = float(pf)
        return "∞" if val >= 10.0 else f"{val:.2f}"
    except (ValueError, TypeError):
        return str(pf)


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def _build_grid(coin: str) -> tuple[list, list]:
    """
    Return (keys, combos) for a specific coin.
    Routes to SUPERTREND_GRID or mean-reversion GRID based on strategy_type.
    GRID_OVERRIDES only apply to mean-reversion coins.
    """
    strategy_type = COINS[coin].get("strategy_type", "mean_reversion")
    if strategy_type == "supertrend":
        keys   = list(SUPERTREND_GRID.keys())
        combos = list(itertools.product(*[SUPERTREND_GRID[k] for k in keys]))
        return keys, combos

    overrides = GRID_OVERRIDES.get(coin, {})
    coin_grid = {
        k: ([overrides[k]] if k in overrides else v)
        for k, v in GRID.items()
    }
    keys   = list(coin_grid.keys())
    combos = list(itertools.product(*[coin_grid[k] for k in keys]))
    return keys, combos


def run_optimizer() -> dict:
    """
    Run per-coin independent grid search.
    Each coin uses its own interval/period from COINS config.
    Returns {coin: [top_N_result_dicts]}.
    """
    print(f"\n  {Fore.CYAN}{'═'*58}")
    print(f"  {Fore.CYAN}  PER-COIN STRATEGY OPTIMIZER")
    print(f"  {Fore.CYAN}{'═'*58}{Style.RESET_ALL}")

    # Preview combo counts per coin
    for coin in COINS:
        _, combos = _build_grid(coin)
        ov = GRID_OVERRIDES.get(coin, {})
        ov_str = f"  (overrides: {ov})" if ov else ""
        print(f"  {coin}: {len(combos)} combos{ov_str}")
    print()

    all_results: dict = {}

    for coin, cfg in COINS.items():
        ticker   = cfg["ticker"]
        interval = cfg["interval"]
        period   = cfg["period"]

        print(f"\n  {Fore.CYAN}{'─'*58}")
        print(f"  {Fore.CYAN}  {coin}  ({interval} / {period})")
        print(f"  {Fore.CYAN}{'─'*58}{Style.RESET_ALL}")

        # ── Download + precompute ──────────────────────────────────────────
        print(f"  Downloading {coin} ({ticker}, {interval}, {period})…",
              end="", flush=True)
        t0 = time.time()
        df = _fetch(ticker, interval, period)
        if df is None or df.empty:
            print(Fore.RED + " download FAILED — skipping" + Style.RESET_ALL)
            all_results[coin] = []
            continue

        cache = _precompute(coin, interval, df, period)
        if cache is None:
            print(Fore.RED + " insufficient data — skipping" + Style.RESET_ALL)
            all_results[coin] = []
            continue

        elapsed = time.time() - t0
        print(Fore.GREEN
              + f" {cache.n:,} bars  ({cache.date_range_days}d)  "
              + f"precomputed in {elapsed:.1f}s"
              + Style.RESET_ALL)

        # ── Grid sweep ─────────────────────────────────────────────────────
        keys, combos = _build_grid(coin)
        total        = len(combos)
        min_trades   = _min_trades_for(interval)
        print(f"\n  Sweeping {total} combos  (min_trades={min_trades})…\n")

        best: list = []
        passed     = 0
        start      = time.time()

        strategy_type = cfg.get("strategy_type", "mean_reversion")

        for idx, values in enumerate(combos, 1):
            params = dict(zip(keys, values))
            if strategy_type == "mean_reversion":
                params["rsi_overbought"] = 100 - params["rsi_oversold"]

            if strategy_type == "supertrend":
                params["max_bars_in_trade"] = cfg.get("max_bars_in_trade", 168)
                result = _fast_sim_supertrend(cache, params)
            else:
                result = _fast_sim(cache, params)
            score, wr, sharpe  = _score_single(result, min_trades)

            if score > 0:
                passed += 1
                entry = {
                    "rank":     passed,
                    "score":    round(score, 4),
                    "win_rate": round(wr, 1),
                    "sharpe":   round(sharpe, 3),
                    "params":   params,
                    "coin":     coin,
                    "interval": interval,
                    "period":   period,
                    "stats": {
                        "trades":        result["total_trades"],
                        "win_rate":      round(result.get("win_rate", 0), 1),
                        "profit_factor": result.get("profit_factor", 0),
                        "total_pnl":     result.get("total_pnl", 0),
                        "sharpe":        result.get("sharpe_ratio", 0),
                    },
                }
                best.append(entry)
                best.sort(
                    key=lambda x: (x["score"], x["win_rate"], x["sharpe"]),
                    reverse=True,
                )
                best = best[:TOP_N]

            if idx % 50 == 0 or idx == total:
                elapsed_s = time.time() - start
                rate      = idx / elapsed_s if elapsed_s > 0 else 1
                remaining = (total - idx) / rate
                done      = int(40 * idx / total)
                bar_str   = "█" * done + "░" * (40 - done)
                print(f"\r  [{bar_str}] {idx}/{total}  "
                      f"passed: {passed}  ETA: {remaining:.0f}s   ",
                      end="", flush=True)

        elapsed_s = time.time() - start
        print(f"\n\n  Done in {elapsed_s:.1f}s  |  {total} combos  |  "
              f"{passed} passed.\n")

        for i, e in enumerate(best, 1):
            e["rank"] = i

        all_results[coin] = best

    _save_best(all_results)
    return all_results


# ─── PERSISTENCE ──────────────────────────────────────────────────────────────

def _save_best(results_by_coin: dict) -> None:
    path = Path(BEST_CONFIGS_FILE)
    # Load existing file, then overwrite only the coin keys we just ran
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    # Strip out old period-keyed entries (legacy format) so they don't pollute
    clean = {k: v for k, v in existing.items() if k in COINS}
    clean.update(results_by_coin)
    path.write_text(json.dumps(clean, indent=2, default=str))
    summary = "  ".join(f"{c}:{len(v)}" for c, v in results_by_coin.items() if v)
    print(f"  {Fore.GREEN}Saved → {path.name}  ({summary}){Style.RESET_ALL}")


def load_best(coin: str = None):
    """
    Load cached per-coin optimization results.
      coin=None  → returns {coin: [results]} dict for all COINS keys.
      coin="ETH" → returns [results] list for that coin.
    """
    path = Path(BEST_CONFIGS_FILE)
    if not path.exists():
        return {} if coin is None else []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {} if coin is None else []

    # Only return entries whose key matches a known coin (ignore old period keys)
    coin_data = {k: v for k, v in data.items() if k in COINS}

    if coin is None:
        return coin_data
    return coin_data.get(coin, [])


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def print_optimizer_results(results_by_coin: dict, top_n: int = 5) -> None:
    if not results_by_coin or not any(results_by_coin.values()):
        print(f"  {Fore.YELLOW}No qualifying configurations found.{Style.RESET_ALL}")
        print(f"  Tip: try running with MA_filter=OFF or loosen RSI thresholds.\n")
        return

    print(f"\n  {Fore.CYAN}{'═'*62}")
    print(f"  {Fore.CYAN}  PER-COIN OPTIMIZATION RESULTS  "
          f"(top {top_n} per coin, scored by profit factor)")
    print(f"  {Fore.CYAN}{'═'*62}{Style.RESET_ALL}\n")

    for coin, best in results_by_coin.items():
        if not best:
            print(f"  {Fore.YELLOW}{coin}: no qualifying configurations found.{Style.RESET_ALL}\n")
            continue

        interval = best[0].get("interval", "?")
        period   = best[0].get("period",   "?")

        print(f"  {Fore.CYAN}{'─'*54}")
        print(f"  {Fore.CYAN}  {coin}  ({interval} / {period})  "
              f"— {len(best)} configs passed")
        print(f"  {Fore.CYAN}{'─'*54}{Style.RESET_ALL}")

        for e in best[:top_n]:
            rank  = e["rank"]
            p     = e["params"]
            s     = e["stats"]
            rc    = (Fore.GREEN  if rank == 1
                     else Fore.CYAN if rank <= 3
                     else Fore.WHITE)
            f_str = "ON" if p.get("ma_trend_filter") else "OFF"
            pnl   = s.get("total_pnl", 0)
            pf    = s.get("profit_factor", 0)
            pc    = Fore.GREEN if float(pnl) >= 0 else Fore.RED
            fc    = (Fore.GREEN  if _safe_float(pf) >= 1.5
                     else Fore.YELLOW if _safe_float(pf) >= 1.0
                     else Fore.RED)

            print(f"  {rc}#{rank}  pf={fc}{_fmt_pf(pf)}{Style.RESET_ALL}{rc}  "
                  f"wr={s.get('win_rate', 0):.0f}%  "
                  f"trades={s.get('trades', 0)}  "
                  f"pnl={pc}${float(pnl):+.2f}{Style.RESET_ALL}{rc}  "
                  f"sharpe={_safe_float(s.get('sharpe', 0)):.2f}"
                  f"{Style.RESET_ALL}")
            if "st_period" in p:   # supertrend coin
                print(f"  {Fore.WHITE}st_period={p['st_period']}  "
                      f"st_mult={p['st_multiplier']}  "
                      f"sl={p['stop_loss_pct'] * 100:.1f}%{Style.RESET_ALL}")
            else:                  # mean-reversion coin
                print(f"  {Fore.WHITE}kc={p['kc_scalar']}  "
                      f"rsi={p['rsi_oversold']}/{p['rsi_overbought']}  "
                      f"hurst_cap={p.get('hurst_cap', _DEFAULT_HURST_CAP)}  "
                      f"sl={p['stop_loss_pct'] * 100:.1f}%  "
                      f"MA_filter={f_str}{Style.RESET_ALL}")
        print()

    print(f"  {Fore.YELLOW}Tip: use [A]pply from the optimizer menu to see "
          f"config.py lines for any coin.{Style.RESET_ALL}\n")


def _safe_float(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return default if (v != v) else v   # NaN check
    except (TypeError, ValueError):
        return default


def run_walk_forward(train_frac: float = 0.70) -> None:
    """
    Walk-forward validation: find the best config on the first train_frac of bars,
    then re-simulate that exact config on the unseen holdout window.

    A config is considered ROBUST if its validation profit_factor is ≥ 80% of
    its training profit_factor AND the validation window produced ≥ 2 trades.
    If it fails either gate it is flagged as OVERFIT — the backtest result was
    likely lucky on that particular window and should not be trusted.
    """
    print(f"\n  {Fore.CYAN}{'═'*58}")
    print(f"  {Fore.CYAN}  WALK-FORWARD VALIDATION"
          f"  (train {int(train_frac*100)}% / validate {int((1-train_frac)*100)}%)")
    print(f"  {Fore.CYAN}{'═'*58}{Style.RESET_ALL}\n")

    for coin, cfg in COINS.items():
        if not cfg.get("enabled", False):
            continue

        ticker   = cfg["ticker"]
        interval = cfg["interval"]
        period   = cfg["period"]

        print(f"  {Fore.CYAN}{'─'*58}")
        print(f"  {Fore.CYAN}  {coin}  ({interval} / {period})")
        print(f"  {Fore.CYAN}{'─'*58}{Style.RESET_ALL}")

        print(f"  Downloading {coin} ({ticker})…", end="", flush=True)
        df = _fetch(ticker, interval, period)
        if df is None or df.empty:
            print(Fore.RED + " FAILED — skipping" + Style.RESET_ALL)
            continue

        cache = _precompute(coin, interval, df, period)
        if cache is None:
            print(Fore.RED + " insufficient data — skipping" + Style.RESET_ALL)
            continue

        n_valid = cache.n - cache.warmup
        split_i = cache.warmup + int(n_valid * train_frac)
        print(Fore.GREEN + f" {cache.n:,} bars  (split at bar {split_i})" + Style.RESET_ALL)

        # Approximate dates for display
        try:
            train_end = df.index[split_i - 1].strftime("%Y-%m-%d")
            val_end   = df.index[-1].strftime("%Y-%m-%d")
        except Exception:
            train_end = val_end = "?"
        print(f"  Train: bars {cache.warmup}–{split_i - 1}  (ends {train_end})")
        print(f"  Valid: bars {split_i}–{cache.n - 1}  (ends {val_end})\n")

        # ── Train: grid-search on first train_frac of bars ────────────────────
        strategy_type            = cfg.get("strategy_type", "mean_reversion")
        keys, combos             = _build_grid(coin)
        min_trades_train         = max(3, int(_min_trades_for(interval) * train_frac))
        best_params: dict | None = None
        best_score               = 0.0
        best_train_result: dict  = {}

        for values in combos:
            params = dict(zip(keys, values))
            if strategy_type == "mean_reversion":
                params["rsi_overbought"] = 100 - params["rsi_oversold"]
                result = _fast_sim(cache, params, end_i=split_i)
            else:
                result = _fast_sim_supertrend(cache, params, end_i=split_i)
            score, _, _ = _score_single(result, min_trades_train)
            if score > 0 and score > best_score:
                best_score        = score
                best_params       = params
                best_train_result = result

        if best_params is None:
            print(Fore.YELLOW
                  + f"  No config passed min_trades={min_trades_train} on training window\n"
                  + Style.RESET_ALL)
            continue

        # ── Validate: replay winning config on holdout window ─────────────────
        if strategy_type == "mean_reversion":
            val_result = _fast_sim(cache, best_params, start_i=split_i)
        else:
            val_result = _fast_sim_supertrend(cache, best_params, start_i=split_i)

        # ── Display ───────────────────────────────────────────────────────────
        p = best_params
        print(f"  Best train config:")
        if strategy_type == "supertrend":
            print(f"  Supertrend({p.get('st_period')},{p.get('st_multiplier')})  "
                  f"sl={p.get('stop_loss_pct', 0)*100:.1f}%\n")
        else:
            hurst_str = f"hurst≤{p.get('hurst_cap', _DEFAULT_HURST_CAP)}"
            ma_str    = "MA_filter=ON" if p.get("ma_trend_filter") else "MA_filter=OFF"
            print(f"  kc={p.get('kc_scalar')}  "
                  f"rsi={int(p.get('rsi_oversold'))}/{int(p.get('rsi_overbought'))}  "
                  f"sl={p.get('stop_loss_pct', 0)*100:.1f}%  {hurst_str}  {ma_str}\n")

        t_pf  = best_train_result.get("profit_factor",  0)
        v_pf  = val_result.get("profit_factor",  0)
        t_sh  = best_train_result.get("sharpe_ratio",   0)
        v_sh  = val_result.get("sharpe_ratio",   0)
        t_n   = best_train_result.get("total_trades",   0)
        v_n   = val_result.get("total_trades",   0)
        t_pnl = best_train_result.get("total_pnl",      0)
        v_pnl = val_result.get("total_pnl",      0)

        # Safe-format profit_factor (can be "inf" string)
        def _fmt(v) -> str:
            try:
                f = float(v)
                return "∞" if f >= 999 else f"{f:.2f}"
            except Exception:
                return str(v)

        print(f"  {'':12}  {'pf':>6}  {'sharpe':>7}  {'trades':>7}  {'pnl':>11}")
        print(f"  {'train':12}  {_fmt(t_pf):>6}  {_safe_float(t_sh):>7.2f}  "
              f"{t_n:>7}  ${t_pnl:>+10.2f}")
        print(f"  {'validate':12}  {_fmt(v_pf):>6}  {_safe_float(v_sh):>7.2f}  "
              f"{v_n:>7}  ${v_pnl:>+10.2f}")

        # Robustness verdict
        try:
            v_pf_f = float(v_pf)
            t_pf_f = float(t_pf)
            decay_pct = ((v_pf_f - t_pf_f) / t_pf_f * 100) if t_pf_f > 0 else -100
        except Exception:
            v_pf_f = t_pf_f = 0.0
            decay_pct = -100

        robust = v_pf_f >= t_pf_f * 0.80 and v_n >= 2
        if robust:
            direction = "above" if decay_pct >= 0 else "below"
            verdict = (Fore.GREEN
                       + f"  ✓ ROBUST  (val pf is {abs(decay_pct):.0f}% {direction} train)")
        else:
            verdict = (Fore.RED
                       + f"  ✗ OVERFIT  (val pf is {abs(decay_pct):.0f}% below train"
                       + (f", only {v_n} trades in holdout" if v_n < 2 else "")
                       + ")")
        print(f"\n{verdict}{Style.RESET_ALL}\n")


def apply_best_to_config(coin: str, entry: dict) -> None:
    """Print config.py lines to apply the best entry for a specific coin."""
    from config import COINS as _COINS
    p            = entry["params"]
    s            = entry.get("stats", {})
    pf_str       = _fmt_pf(s.get("profit_factor", 0))
    strategy_type = _COINS.get(coin, {}).get("strategy_type", "mean_reversion")

    print(f"\n  {Fore.CYAN}Best config for {coin} "
          f"(rank #{entry['rank']}  pf={pf_str}  "
          f"trades={s.get('trades', 0)}  "
          f"wr={s.get('win_rate', 0):.0f}%):{Style.RESET_ALL}")

    if strategy_type == "supertrend":
        print(f"  {Fore.WHITE}"
              f"# config.py — COINS['{coin}'] supertrend params:\n"
              f"  'st_period':     {p.get('st_period', 10)},\n"
              f"  'st_multiplier': {p.get('st_multiplier', 3.0)},\n"
              f"  'stop_loss_pct': {p.get('stop_loss_pct', 0.010)},"
              f"{Style.RESET_ALL}\n")
    else:
        print(f"  {Fore.WHITE}"
              f"# config.py — global defaults (apply cautiously; "
              f"other coins may differ):\n"
              f"  KC_SCALAR      = {p['kc_scalar']}\n"
              f"  RSI_OVERSOLD   = {p['rsi_oversold']}\n"
              f"  RSI_OVERBOUGHT = {p['rsi_overbought']}\n"
              f"  STOP_LOSS_PCT  = {p['stop_loss_pct']}\n"
              f"  # In backtester._DEFAULT_SIM_PARAMS (strategy logic):\n"
              f"  #   hurst_cap       = {p['hurst_cap']}\n"
              f"  #   ma_trend_filter = {p['ma_trend_filter']}"
              f"{Style.RESET_ALL}\n")
