"""
strategy.py — pure technical analysis, no decisions
Returns indicator values only. AI advisor and risk manager make decisions.

Enhanced with ADX, Hurst Exponent, momentum score, and volatility regime
adapted from the ai-hedge-fund open-source project (virattt/ai-hedge-fund).
"""
import math
import time
import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import logging
from colorama import Fore, Style
from config import KC_PERIOD, KC_SCALAR, MA_FAST, MA_SLOW, MA_TREND, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT

# Configure logging
logger = logging.getLogger(__name__)

_DATA_CACHE: dict[tuple[str, str, str], dict] = {}
_INDICATOR_CACHE: dict[tuple, dict] = {}
_TREND_BIAS_CACHE: dict[tuple, dict] = {}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _safe(value, default=0.0) -> float:
    """Safely convert pandas/numpy scalar to float, returning default on NaN."""
    try:
        v = float(value)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


def _round_price(p: float) -> float:
    """Round price to appropriate decimal places based on magnitude.

    Prevents sub-cent tokens (BONK $0.000022, SHIB $0.000013) from being
    rounded to 0.0 when stored in indicator dicts.
      ≥ $1.00   → 4 dp  (e.g. $85.4317)
      ≥ $0.001  → 6 dp  (e.g. $0.091500)
      ≥ $0.0001 → 8 dp  (e.g. $0.000022)
      < $0.0001 → 10 dp (e.g. $0.000000013)
    """
    if p >= 1.0:
        return round(p, 4)
    elif p >= 0.001:
        return round(p, 6)
    elif p >= 0.0001:
        return round(p, 8)
    else:
        return round(p, 10)


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    """Average Directional Index — measures trend STRENGTH (0-100). >25 = strong trend."""
    try:
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"]

        up_move   = high.diff()
        down_move = -low.diff()

        plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # True Range
        hl  = high - low
        hc  = (high - close.shift()).abs()
        lc  = (low  - close.shift()).abs()
        tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)

        atr14  = tr.ewm(span=period, adjust=False).mean()
        pdi    = 100 * pd.Series(plus_dm,  index=df.index).ewm(span=period, adjust=False).mean() / atr14
        mdi    = 100 * pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean() / atr14
        dx     = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).fillna(0)
        adx    = dx.ewm(span=period, adjust=False).mean()
        result = _safe(adx.iloc[-1])
        logger.debug(f"ADX calculation result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error calculating ADX: {e}")
        return 0.0


def _hurst(close: pd.Series, max_lag: int = 20) -> float:
    """
    Hurst Exponent — characterises the time-series memory.
      H < 0.5  →  mean-reverting  (good for Keltner fade trades)
      H ≈ 0.5  →  random walk
      H > 0.5  →  trending        (counter-trend trades are riskier)
    """
    try:
        lags = range(2, max_lag)
        tau  = [
            max(1e-8, np.sqrt(np.std(np.subtract(close.values[lag:], close.values[:-lag]))))
            for lag in lags
        ]
        reg = np.polyfit(np.log(list(lags)), np.log(tau), 1)
        result = _safe(reg[0], default=0.5)
        logger.debug(f"Hurst Exponent calculation result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error calculating Hurst Exponent: {e}")
        return 0.5


def _momentum_score(close: pd.Series, volume: pd.Series | None = None) -> float:
    """
    Weighted multi-timeframe momentum score.
    Positive = bullish, Negative = bearish. Magnitude indicates strength.
    Periods in bars (4h bars): 30≈5d, 90≈15d, 180≈30d.
    """
    try:
        returns = close.pct_change()
        mom_5d = _safe(returns.rolling(30).sum().iloc[-1])
        mom_15d = _safe(returns.rolling(90).sum().iloc[-1])
        mom_30d = _safe(returns.rolling(180).sum().iloc[-1])
        score = 0.4 * mom_5d + 0.3 * mom_15d + 0.3 * mom_30d

        if volume is not None and len(volume) > 21:
            vol_ratio = _safe(volume.iloc[-1] / volume.rolling(21).mean().iloc[-1], 1.0)
            vol_ratio = min(max(vol_ratio, 0.5), 2.0)
            volume_boost = math.sqrt(vol_ratio)
            score *= volume_boost
            logger.debug(f"Momentum score scaled by clamped volume boost: {volume_boost}")

        result = round(score, 4)
        logger.debug(f"Momentum score calculation result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error calculating momentum score: {e}")
        return 0.0


def _vol_regime(close: pd.Series) -> tuple[float, str]:
    """
    Returns (annualised_volatility, regime_label).
    regime_label: 'high' | 'normal' | 'low'
    Uses 21-bar rolling std vs 63-bar rolling average of std.
    """
    try:
        returns  = close.pct_change()
        # Annualise: 4h bars → ~6 per day → 252*6 = 1512 bars/year
        bars_per_year = 252 * 6
        hist_vol = returns.rolling(21).std() * math.sqrt(bars_per_year)
        vol_ma   = hist_vol.rolling(63).mean()
        current  = _safe(hist_vol.iloc[-1])
        average  = _safe(vol_ma.iloc[-1], current)  # fallback to current if no avg yet

        vol_ratio = current / max(average, 1e-8)
        regime = (
            "high"   if vol_ratio > 1.45 else
            "low"    if vol_ratio < 0.80 else
            "normal"
        )
        result = (round(current, 4), regime)
        logger.debug(f"Volatility regime calculation result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error calculating volatility regime: {e}")
        return 0.0, "normal"


def _trend_slope(close: pd.Series, ema_length: int = MA_TREND, lookback: int = 6) -> float:
    """Normalized EMA slope per bar for directional trend quality."""
    try:
        ema = ta.ema(close, length=ema_length)
        if ema is None:
            return 0.0
        ema = ema.dropna()
        if len(ema) <= lookback:
            return 0.0
        start = _safe(ema.iloc[-(lookback + 1)])
        end = _safe(ema.iloc[-1])
        if abs(start) < 1e-8:
            return 0.0
        result = round((end - start) / abs(start) / lookback, 6)
        logger.debug(f"Trend slope calculation result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error calculating trend slope: {e}")
        return 0.0


def _classify_regime_gate(adx: float, hurst: float) -> tuple[str, str]:
    """Explicit regime gate: trend, mean_reversion, or neutral."""
    if adx >= 25 and hurst >= 0.55:
        return "trend", "trending"
    if adx <= 22 and hurst <= 0.45:
        return "mean_reversion", "mean_reverting"
    return "neutral", "neutral"


def _trend_slope_label(slope: float) -> str:
    if slope > 0.0008:
        return "rising"
    if slope < -0.0008:
        return "falling"
    return "flat"


def _interval_seconds(interval: str) -> int:
    unit = interval[-1].lower()
    value = int(interval[:-1])
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return 300


def _data_signature(df: pd.DataFrame) -> tuple:
    idx = -2 if len(df) > 1 else -1
    row = df.iloc[idx]
    ts = df.index[idx]
    return (
        str(ts),
        len(df),
        _round_price(_safe(row["Close"])),
        round(_safe(row.get("Volume", 0.0)), 4),
    )


# ─── SUPERTREND ───────────────────────────────────────────────────────────────

def _supertrend_arrays(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                       period: int, multiplier: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Vectorised Supertrend calculation.
    Returns (direction, line) arrays of length n.
      direction[i]: +1 = bullish (price above ST line), -1 = bearish
      line[i]:      the actual Supertrend stop/support level
    """
    n = len(close)
    prev_close = np.concatenate(([close[0]], close[:-1]))

    # Wilder ATR
    tr  = np.maximum(high - low,
          np.maximum(np.abs(high - prev_close),
                     np.abs(low  - prev_close)))
    atr = np.full(n, np.nan)
    if period <= n:
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    mid         = (high + low) / 2.0
    upper_basic = mid + multiplier * atr
    lower_basic = mid - multiplier * atr

    upper     = np.copy(upper_basic)
    lower     = np.copy(lower_basic)
    direction = np.zeros(n, dtype=np.int8)
    line      = np.full(n, np.nan)

    start = period   # first bar with valid ATR
    if start >= n:
        return direction, line

    direction[start] = 1
    line[start]      = lower[start]

    for i in range(start + 1, n):
        if np.isnan(upper[i]) or np.isnan(lower[i]):
            direction[i] = direction[i - 1]
            continue

        # Bands only move in the direction of the current trend
        upper[i] = (min(upper_basic[i], upper[i - 1])
                    if close[i - 1] <= upper[i - 1] else upper_basic[i])
        lower[i] = (max(lower_basic[i], lower[i - 1])
                    if close[i - 1] >= lower[i - 1] else lower_basic[i])

        if   close[i] > upper[i - 1]:  direction[i] =  1
        elif close[i] < lower[i - 1]:  direction[i] = -1
        else:                           direction[i]  = direction[i - 1]

        line[i] = lower[i] if direction[i] == 1 else upper[i]

    return direction, line


def calculate_supertrend_indicators(df: pd.DataFrame,
                                    st_period: int,
                                    st_multiplier: float) -> dict | None:
    """
    Calculate Supertrend-specific indicators for a OHLCV dataframe.
    Returns a flat dict of the latest values, or None on failure.
    Includes shared fields (price, ATR, vol_regime, hurst, momentum) so the
    live bot and AI advisor have full context.
    """
    try:
        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df.get("Volume")

        h_arr = high.to_numpy(dtype=float)
        l_arr = low.to_numpy(dtype=float)
        c_arr = close.to_numpy(dtype=float)

        direction, st_line = _supertrend_arrays(h_arr, l_arr, c_arr,
                                                st_period, st_multiplier)

        # Shared base indicators
        atr_series   = ta.atr(high, low, close, length=st_period)
        ma_trend     = ta.ema(close, length=MA_TREND)
        adx_value    = _adx(df)
        hurst_val    = _hurst(close)
        momentum     = _momentum_score(close, volume)
        ann_vol, vol_regime = _vol_regime(close)
        trend_slope  = _trend_slope(close)
        regime_gate, market_regime = _classify_regime_gate(adx_value, hurst_val)

        d_cur  = int(direction[-1])
        d_prev = int(direction[-2]) if len(direction) >= 2 else d_cur
        flipped = d_cur != d_prev

        # Signal: only fire on the actual flip bar
        if flipped:
            st_signal = "long" if d_cur == 1 else "short"
        else:
            st_signal = "hold"

        price   = _safe(close.iloc[-1])
        st_val  = _safe(st_line[-1])
        atr_val = _safe(atr_series.iloc[-1]) if atr_series is not None else 0.0

        latest = {
            "price":           _round_price(price),
            "atr":             round(atr_val, 4),
            "ma_trend":        round(_safe(ma_trend.iloc[-1]), 4),
            "adx":             round(adx_value, 1),
            "hurst":           round(hurst_val, 3),
            "momentum":        momentum,
            "ann_vol":         ann_vol,
            "vol_regime":      vol_regime,
            "trend_slope":     trend_slope,
            "trend_slope_label": _trend_slope_label(trend_slope),
            "regime_gate":     regime_gate,
            # Supertrend-specific
            "st_line":         round(st_val, 4),
            "st_direction":    d_cur,          # +1 = bullish, -1 = bearish
            "st_direction_prev": d_prev,
            "st_signal":       st_signal,      # "long"|"short"|"hold"
            "st_flipped":      flipped,
        }

        # Derived labels
        latest["trend_direction"] = "up"   if d_cur ==  1 else "down"
        latest["trend_strength"]  = ("strong"   if latest["adx"] > 25 else
                                     "weak"     if latest["adx"] < 15 else "moderate")
        latest["market_regime"]   = market_regime
        latest["price_vs_st"]     = ("above ST line" if price > st_val else
                                     "below ST line" if price < st_val else "at ST line")
        return latest

    except Exception as e:
        print(Fore.RED + f"  Supertrend indicator error: {e}")
        return None


# ─── CORE INDICATOR CALCULATION ───────────────────────────────────────────────

def download_data(ticker: str, interval: str, period: str) -> pd.DataFrame | None:
    """Download OHLCV data from Yahoo Finance. Returns None on failure."""
    cache_key = (ticker, interval, period)
    cache_ttl = max(15, min(_interval_seconds(interval) // 2, 3600))
    now = time.monotonic()
    cached = _DATA_CACHE.get(cache_key)
    if cached and (now - cached["fetched_at"] < cache_ttl):
        logger.debug(f"Using cached data for {ticker} [{interval}/{period}]")
        return cached["df"].copy()
    try:
        logger.debug(f"Downloading data for {ticker} with interval {interval} and period {period}")
        df = yf.download(ticker, interval=interval, period=period,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            logger.warning(f"No data returned for {ticker}")
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        logger.debug(f"Successfully downloaded {len(df)} rows for {ticker}")
        _DATA_CACHE[cache_key] = {"fetched_at": now, "df": df.copy()}
        return df
    except Exception as e:
        logger.error(f"Download error for {ticker}: {e}")
        return None


def calculate_indicators(df: pd.DataFrame, kc_scalar: float | None = None) -> dict | None:
    """
    Calculate all technical indicators for a given OHLCV dataframe.
    Returns a flat dict of the latest values, or None if calculation fails.

    kc_scalar: per-coin Keltner Channel width multiplier.  Defaults to the
               global KC_SCALAR if not provided.  Pass coin_cfg["kc_scalar"]
               to allow each coin to use its optimizer-validated band width.
    """
    if kc_scalar is None:
        kc_scalar = KC_SCALAR
    try:
        logger.debug(f"Calculating indicators with kc_scalar={kc_scalar}")
        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df.get("Volume")

        # ── Keltner Channel ────────────────────────────────────────────────
        ema_mid  = ta.ema(close, length=KC_PERIOD)
        atr      = ta.atr(high, low, close, length=KC_PERIOD)
        kc_upper = ema_mid + kc_scalar * atr
        kc_lower = ema_mid - kc_scalar * atr

        # ── Moving averages ────────────────────────────────────────────────
        ma_fast  = ta.ema(close, length=MA_FAST)
        ma_slow  = ta.ema(close, length=MA_SLOW)
        ma_trend = ta.ema(close, length=MA_TREND)

        # ── RSI ────────────────────────────────────────────────────────────
        rsi = ta.rsi(close, length=RSI_PERIOD)

        # ── ADX — trend strength ───────────────────────────────────────────
        adx_value = _adx(df)

        # ── Hurst Exponent — market regime ─────────────────────────────────
        hurst = _hurst(close)

        # ── Momentum score — multi-timeframe ──────────────────────────────
        momentum = _momentum_score(close, volume)

        # ── Volatility regime ──────────────────────────────────────────────
        ann_vol, vol_regime = _vol_regime(close)
        trend_slope = _trend_slope(close)
        regime_gate, market_regime = _classify_regime_gate(adx_value, hurst)

        # ── Volume ratio: last COMPLETED bar vs 20-bar rolling mean ──────────
        # Used by Gate 5 (volume filter) to skip entries in thin/quiet markets.
        # mean-reversion works best when there's real participation; a bar with
        # < 50% of average volume is often noise rather than a real band touch.
        #
        # IMPORTANT: use iloc[-2] (most recently completed bar) NOT iloc[-1].
        # The last bar returned by yfinance is the still-forming current candle;
        # its volume fraction of a full bar makes vol_ratio ≈ 0 and trips the
        # gate on every coin, falsely blocking all legitimate signals.
        vol_ratio = 1.0   # neutral default if volume unavailable
        if volume is not None and len(volume) >= 21:
            completed = volume.iloc[:-1]            # exclude the open (partial) bar
            vol_ma    = completed.rolling(20).mean().iloc[-1]
            if vol_ma and vol_ma > 0:
                vol_ratio = round(_safe(completed.iloc[-1] / vol_ma, 1.0), 3)

        price_now = _safe(close.iloc[-1])
        atr_now = _safe(atr.iloc[-1])
        long_entry_quality = 0.0
        short_entry_quality = 0.0
        if atr_now > 1e-8:
            long_entry_quality = max(0.0, (float(kc_lower.iloc[-1]) - price_now) / atr_now)
            short_entry_quality = max(0.0, (price_now - float(kc_upper.iloc[-1])) / atr_now)
        entry_quality = round(max(long_entry_quality, short_entry_quality), 4)
        entry_quality_side = (
            "long" if long_entry_quality > short_entry_quality else
            "short" if short_entry_quality > long_entry_quality else
            "neutral"
        )

        latest = {
            "price":    _round_price(price_now),
            "kc_upper": _round_price(_safe(kc_upper.iloc[-1])),
            "kc_mid":   _round_price(_safe(ema_mid.iloc[-1])),
            "kc_lower": _round_price(_safe(kc_lower.iloc[-1])),
            "atr":      round(atr_now, 6),   # ATR also sub-cent for BONK/SHIB
            "ma_fast":  _round_price(_safe(ma_fast.iloc[-1])),
            "ma_slow":  _round_price(_safe(ma_slow.iloc[-1])),
            "ma_trend": _round_price(_safe(ma_trend.iloc[-1])),
            "rsi":      round(_safe(rsi.iloc[-1]),      2),
            # ── new fields ─────────────────────────────────────────────────
            "adx":          round(adx_value, 1),
            "hurst":        round(hurst, 3),
            "momentum":     momentum,
            "ann_vol":      ann_vol,
            "vol_regime":   vol_regime,
            "trend_slope":  trend_slope,
            "vol_ratio":    vol_ratio,   # current bar vol / 20-bar avg vol
            "entry_quality": entry_quality,
            "entry_quality_side": entry_quality_side,
        }

        # ── Derived labels for AI prompt readability ───────────────────────
        latest["price_vs_kc"] = (
            "above upper band" if latest["price"] > latest["kc_upper"] else
            "below lower band" if latest["price"] < latest["kc_lower"] else
            "inside channel"
        )
        latest["ma_alignment"] = (
            "bullish" if latest["ma_fast"] > latest["ma_slow"] > latest["ma_trend"] else
            "bearish" if latest["ma_fast"] < latest["ma_slow"] < latest["ma_trend"] else
            "mixed"
        )
        latest["rsi_zone"] = (
            "oversold"   if latest["rsi"] < RSI_OVERSOLD  else
            "overbought" if latest["rsi"] > RSI_OVERBOUGHT else
            "neutral"
        )
        latest["trend_direction"] = (
            "up"   if latest["price"] > latest["ma_trend"] else
            "down" if latest["price"] < latest["ma_trend"] else
            "flat"
        )
        latest["trend_slope_label"] = _trend_slope_label(trend_slope)
        latest["trend_strength"] = (
            "strong" if latest["adx"] > 25 else
            "weak"   if latest["adx"] < 15 else
            "moderate"
        )
        latest["regime_gate"] = regime_gate
        latest["market_regime"] = market_regime

        logger.debug(f"Successfully calculated indicators for {len(df)} rows")
        return latest

    except Exception as e:
        logger.error(f"Indicator calculation error: {e}")
        return None


def get_indicators_for_coin(coin: str, coin_cfg: dict) -> dict | None:
    """
    Convenience wrapper: download + calculate for a coin config dict.
    Routes to supertrend or mean-reversion indicators based on strategy_type.
    """
    logger.debug(f"Getting indicators for {coin}")
    df = download_data(coin_cfg["ticker"], coin_cfg["interval"], coin_cfg["period"])
    if df is None:
        logger.warning(f"Failed to download data for {coin}")
        return None
    cache_key = (
        coin,
        coin_cfg["interval"],
        coin_cfg["period"],
        coin_cfg.get("strategy_type", "mean_reversion"),
        coin_cfg.get("kc_scalar", KC_SCALAR),
        coin_cfg.get("st_period"),
        coin_cfg.get("st_multiplier"),
        coin_cfg.get("ma_trend_filter", True),
        coin_cfg.get("rsi_oversold", RSI_OVERSOLD),
        coin_cfg.get("rsi_overbought", RSI_OVERBOUGHT),
    )
    signature = _data_signature(df)
    cached = _INDICATOR_CACHE.get(cache_key)
    if cached and cached["signature"] == signature:
        logger.debug(f"Using cached indicators for {coin}")
        return dict(cached["indicators"])

    strategy_type = coin_cfg.get("strategy_type", "mean_reversion")
    logger.debug(f"{coin} using strategy type: {strategy_type}")

    if strategy_type == "supertrend":
        st_period     = coin_cfg.get("st_period",     10)
        st_multiplier = coin_cfg.get("st_multiplier", 3.0)
        logger.debug(f"{coin} Supertrend parameters: period={st_period}, multiplier={st_multiplier}")
        indicators = calculate_supertrend_indicators(df, st_period, st_multiplier)
        if indicators:
            indicators["coin"]          = coin
            indicators["interval"]      = coin_cfg["interval"]
            indicators["strategy_type"] = "supertrend"
    else:
        coin_kc_scalar = coin_cfg.get("kc_scalar", KC_SCALAR)
        logger.debug(f"{coin} KC scalar: {coin_kc_scalar}")
        indicators = calculate_indicators(df, kc_scalar=coin_kc_scalar)
        if indicators:
            indicators["coin"]            = coin
            indicators["interval"]        = coin_cfg["interval"]
            indicators["strategy_type"]   = "mean_reversion"
            indicators["kc_scalar"]       = coin_kc_scalar
            indicators["entry_quality_min"] = coin_cfg.get("entry_quality_min", 0.25)
            indicators["ma_trend_filter"] = coin_cfg.get("ma_trend_filter", True)
            indicators["rsi_oversold"]    = coin_cfg.get("rsi_oversold",  RSI_OVERSOLD)
            indicators["rsi_overbought"]  = coin_cfg.get("rsi_overbought", RSI_OVERBOUGHT)
            rsi_val = indicators["rsi"]
            indicators["rsi_zone"] = (
                "oversold"   if rsi_val < indicators["rsi_oversold"]  else
                "overbought" if rsi_val > indicators["rsi_overbought"] else
                "neutral"
            )

    if indicators:
        logger.debug(f"Successfully calculated indicators for {coin}")
        _INDICATOR_CACHE[cache_key] = {"signature": signature, "indicators": dict(indicators)}
    else:
        logger.warning(f"Failed to calculate indicators for {coin}")
    
    return indicators


def get_trend_bias(coin: str, coin_cfg: dict) -> dict:
    """
    Fetch the daily (1d) trend for a coin and return a simple bias dict.
    Used as higher-timeframe context for the AI advisor.
    """
    logger.info(f"Getting daily trend bias for {coin}")
    daily_cfg            = dict(coin_cfg)
    daily_cfg["interval"] = "1d"
    daily_cfg["period"]   = "90d"

    df = download_data(daily_cfg["ticker"], daily_cfg["interval"], daily_cfg["period"])
    if df is None or len(df) < 50:
        logger.warning(f"Insufficient daily data for {coin}")
        return {"coin": coin, "trend": "neutral", "rsi": 50.0,
                "ma_alignment": "mixed", "hurst": 0.5}
    cache_key = (coin, daily_cfg["ticker"], daily_cfg["interval"], daily_cfg["period"])
    signature = _data_signature(df)
    cached = _TREND_BIAS_CACHE.get(cache_key)
    if cached and cached["signature"] == signature:
        logger.debug(f"Using cached daily trend bias for {coin}")
        return dict(cached["bias"])

    ind = calculate_indicators(df)
    if not ind:
        logger.warning(f"Failed to calculate daily indicators for {coin}")
        return {"coin": coin, "trend": "neutral", "rsi": 50.0,
                "ma_alignment": "mixed", "hurst": 0.5}

    trend = (
        "bullish" if ind["ma_alignment"] == "bullish" and ind["rsi"] > 50 else
        "bearish" if ind["ma_alignment"] == "bearish" and ind["rsi"] < 50 else
        "neutral"
    )
    
    result = {
        "coin":          coin,
        "trend":         trend,
        "rsi":           ind["rsi"],
        "ma_alignment":  ind["ma_alignment"],
        "price_vs_kc":   ind["price_vs_kc"],
        "hurst":         ind["hurst"],
        "market_regime": ind["market_regime"],
        "adx":           ind["adx"],
    }
    _TREND_BIAS_CACHE[cache_key] = {"signature": signature, "bias": dict(result)}
    
    logger.info(f"Daily trend bias for {coin}: {trend}")
    return result


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def print_indicators(indicators: dict) -> None:
    """
    Compact 1-line indicator summary per coin.

    Supertrend:  COIN  $price  [tf·ST]  ▲UP=line  ADX=N(str)  H=0.xxx  Mom=+/-
    Mean-rev:    COIN  $price  [tf·KC]  RSI=N(zon)  pos  MA=align  ADX=N(str)  Vol×N
    """
    c        = indicators["coin"]
    p        = indicators["price"]
    st       = indicators.get("strategy_type", "mean_reversion")
    interval = indicators.get("interval", "?")
    tag      = "ST" if st == "supertrend" else "KC"
    adx      = indicators.get("adx", 0)
    # Abbreviate trend_strength to 3 chars: str / mod / wea
    adx_s    = {"strong": "str", "moderate": "mod", "weak": "wea"}.get(
                    indicators.get("trend_strength", "moderate"), "mod")

    # Dynamic price precision: 4 dp for normal prices, more for sub-cent tokens
    if p >= 1.0:
        price_str = f"${p:>12,.4f}"
    elif p >= 0.001:
        price_str = f"${p:>12,.6f}"
    else:
        price_str = f"${p:>12,.8f}"

    header = (f"  {Fore.CYAN}{c:<5}{Style.RESET_ALL}"
              f"{price_str}"
              f"  {Fore.YELLOW}[{interval}·{tag}]{Style.RESET_ALL}")

    if st == "supertrend":
        d       = indicators.get("st_direction", 0)
        st_val  = indicators.get("st_line", 0)
        flipped = indicators.get("st_flipped", False)
        hurst   = indicators.get("hurst", 0.5)
        mom     = indicators.get("momentum", 0)
        vol     = indicators.get("vol_regime", "normal")

        d_color   = Fore.GREEN if d == 1 else Fore.RED
        d_sym     = "▲" if d == 1 else "▼"
        d_str     = "UP" if d == 1 else "DN"
        mom_color = Fore.GREEN if mom > 0 else Fore.RED if mom < 0 else Fore.WHITE
        flip_tag  = f"  {Fore.YELLOW}← FLIP!{Style.RESET_ALL}" if flipped else ""
        vol_tag   = f"  {Fore.RED}⚠HighVol{Style.RESET_ALL}" if vol == "high" else ""

        print(f"\n{header}"
              f"  {d_color}{d_sym}{d_str}={st_val:,.4f}{Style.RESET_ALL}"
              f"  ADX={adx:.0f}({adx_s})"
              f"  H={hurst:.3f}"
              f"  Mom={mom_color}{mom:+.4f}{Style.RESET_ALL}"
              f"{flip_tag}{vol_tag}")

    else:
        rsi      = indicators.get("rsi", 50)
        rsi_zone = indicators.get("rsi_zone", "neutral")
        pos      = indicators.get("price_vs_kc", "inside channel")
        ma_align = indicators.get("ma_alignment", "mixed")
        vol_r    = indicators.get("vol_ratio", 1.0)
        vol_reg  = indicators.get("vol_regime", "normal")

        # Abbreviate zone to 3 chars: ovs / ovb / neu
        zone_abbr = {"oversold": "ovs", "overbought": "ovb", "neutral": "neu"}.get(
                        rsi_zone, "neu")
        rsi_color = (Fore.GREEN if rsi_zone == "oversold"   else
                     Fore.RED   if rsi_zone == "overbought" else Fore.WHITE)
        pos_short = ("↓belowKC" if "below lower" in pos else
                     "↑aboveKC" if "above upper" in pos else "insideKC")
        pos_color = (Fore.GREEN if "below lower" in pos else
                     Fore.RED   if "above upper" in pos else Fore.WHITE)
        # Abbreviate MA alignment to 4 chars: bull / bear / mix
        ma_abbr   = {"bullish": "bull", "bearish": "bear", "mixed": "mix "}.get(
                        ma_align, "mix ")
        ma_color  = (Fore.GREEN if ma_align == "bullish" else
                     Fore.RED   if ma_align == "bearish" else Fore.WHITE)
        vol_warn  = f"  {Fore.RED}⚠HighVol{Style.RESET_ALL}" if vol_reg == "high" else ""

        print(f"\n{header}"
              f"  RSI={rsi_color}{rsi:.1f}({zone_abbr}){Style.RESET_ALL}"
              f"  {pos_color}{pos_short}{Style.RESET_ALL}"
              f"  MA={ma_color}{ma_abbr}{Style.RESET_ALL}"
              f"  ADX={adx:.0f}({adx_s})"
              f"  Vol×{vol_r:.1f}{vol_warn}")
