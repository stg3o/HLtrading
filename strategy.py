"""
strategy.py — pure technical analysis, no decisions
Returns indicator values only. AI advisor and risk manager make decisions.

Enhanced with ADX, Hurst Exponent, momentum score, and volatility regime
adapted from the ai-hedge-fund open-source project (virattt/ai-hedge-fund).
"""
import math
import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from colorama import Fore, Style
from config import KC_PERIOD, KC_SCALAR, MA_FAST, MA_SLOW, MA_TREND, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _safe(value, default=0.0) -> float:
    """Safely convert pandas/numpy scalar to float, returning default on NaN."""
    try:
        v = float(value)
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


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
        return _safe(adx.iloc[-1])
    except Exception:
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
        return _safe(reg[0], default=0.5)
    except Exception:
        return 0.5


def _momentum_score(close: pd.Series, volume: pd.Series | None = None) -> float:
    """
    Weighted multi-timeframe momentum score.
    Positive = bullish, Negative = bearish. Magnitude indicates strength.
    Periods in bars (4h bars): 1m≈30, 3m≈90, 6m≈180.
    """
    try:
        returns = close.pct_change()
        m1 = _safe(returns.rolling(30).sum().iloc[-1])
        m3 = _safe(returns.rolling(90).sum().iloc[-1])
        m6 = _safe(returns.rolling(180).sum().iloc[-1])
        score = 0.4 * m1 + 0.3 * m3 + 0.3 * m6

        if volume is not None and len(volume) > 21:
            vol_ratio = _safe(volume.iloc[-1] / volume.rolling(21).mean().iloc[-1], 1.0)
            score *= vol_ratio   # scale by volume confirmation

        return round(score, 4)
    except Exception:
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

        regime = (
            "high"   if current > average * 1.3 else
            "low"    if current < average * 0.7 else
            "normal"
        )
        return round(current, 4), regime
    except Exception:
        return 0.0, "normal"


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
            "price":           round(price,   4),
            "atr":             round(atr_val, 4),
            "ma_trend":        round(_safe(ma_trend.iloc[-1]), 4),
            "adx":             round(adx_value, 1),
            "hurst":           round(hurst_val, 3),
            "momentum":        momentum,
            "ann_vol":         ann_vol,
            "vol_regime":      vol_regime,
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
        latest["market_regime"]   = ("trending"       if hurst_val > 0.55 else
                                     "mean_reverting" if hurst_val < 0.45 else "ranging")
        latest["price_vs_st"]     = ("above ST line" if price > st_val else
                                     "below ST line" if price < st_val else "at ST line")
        return latest

    except Exception as e:
        print(Fore.RED + f"  Supertrend indicator error: {e}")
        return None


# ─── CORE INDICATOR CALCULATION ───────────────────────────────────────────────

def download_data(ticker: str, interval: str, period: str) -> pd.DataFrame | None:
    """Download OHLCV data from Yahoo Finance. Returns None on failure."""
    try:
        df = yf.download(ticker, interval=interval, period=period,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            print(Fore.RED + f"  No data returned for {ticker}")
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(Fore.RED + f"  Download error for {ticker}: {e}")
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

        # ── Volume ratio: current bar vs 20-bar rolling mean ──────────────
        # Used by Gate 5 (volume filter) to skip entries in thin/quiet markets.
        # mean-reversion works best when there's real participation; a bar with
        # < 50% of average volume is often noise rather than a real band touch.
        vol_ratio = 1.0   # neutral default if volume unavailable
        if volume is not None and len(volume) >= 20:
            vol_ma = volume.rolling(20).mean().iloc[-1]
            if vol_ma and vol_ma > 0:
                vol_ratio = round(_safe(volume.iloc[-1] / vol_ma, 1.0), 3)

        latest = {
            "price":    round(_safe(close.iloc[-1]),   4),
            "kc_upper": round(_safe(kc_upper.iloc[-1]), 4),
            "kc_mid":   round(_safe(ema_mid.iloc[-1]),  4),
            "kc_lower": round(_safe(kc_lower.iloc[-1]), 4),
            "atr":      round(_safe(atr.iloc[-1]),      4),
            "ma_fast":  round(_safe(ma_fast.iloc[-1]),  4),
            "ma_slow":  round(_safe(ma_slow.iloc[-1]),  4),
            "ma_trend": round(_safe(ma_trend.iloc[-1]), 4),
            "rsi":      round(_safe(rsi.iloc[-1]),      2),
            # ── new fields ─────────────────────────────────────────────────
            "adx":          round(adx_value, 1),
            "hurst":        round(hurst, 3),
            "momentum":     momentum,
            "ann_vol":      ann_vol,
            "vol_regime":   vol_regime,
            "vol_ratio":    vol_ratio,   # current bar vol / 20-bar avg vol
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
        latest["trend_strength"] = (
            "strong" if latest["adx"] > 25 else
            "weak"   if latest["adx"] < 15 else
            "moderate"
        )
        latest["market_regime"] = (
            "trending"      if latest["hurst"] > 0.55 else
            "mean_reverting" if latest["hurst"] < 0.45 else
            "ranging"
        )

        return latest

    except Exception as e:
        print(Fore.RED + f"  Indicator calculation error: {e}")
        return None


def get_indicators_for_coin(coin: str, coin_cfg: dict) -> dict | None:
    """
    Convenience wrapper: download + calculate for a coin config dict.
    Routes to supertrend or mean-reversion indicators based on strategy_type.
    """
    df = download_data(coin_cfg["ticker"], coin_cfg["interval"], coin_cfg["period"])
    if df is None:
        return None

    strategy_type = coin_cfg.get("strategy_type", "mean_reversion")

    if strategy_type == "supertrend":
        st_period     = coin_cfg.get("st_period",     10)
        st_multiplier = coin_cfg.get("st_multiplier", 3.0)
        indicators = calculate_supertrend_indicators(df, st_period, st_multiplier)
        if indicators:
            indicators["coin"]          = coin
            indicators["interval"]      = coin_cfg["interval"]
            indicators["strategy_type"] = "supertrend"
    else:
        coin_kc_scalar = coin_cfg.get("kc_scalar", KC_SCALAR)
        indicators = calculate_indicators(df, kc_scalar=coin_kc_scalar)
        if indicators:
            indicators["coin"]            = coin
            indicators["interval"]        = coin_cfg["interval"]
            indicators["strategy_type"]   = "mean_reversion"
            indicators["kc_scalar"]       = coin_kc_scalar
            indicators["ma_trend_filter"] = coin_cfg.get("ma_trend_filter", True)
            from config import RSI_OVERSOLD, RSI_OVERBOUGHT
            indicators["rsi_oversold"]    = coin_cfg.get("rsi_oversold",  RSI_OVERSOLD)
            indicators["rsi_overbought"]  = coin_cfg.get("rsi_overbought", RSI_OVERBOUGHT)
            rsi_val = indicators["rsi"]
            indicators["rsi_zone"] = (
                "oversold"   if rsi_val < indicators["rsi_oversold"]  else
                "overbought" if rsi_val > indicators["rsi_overbought"] else
                "neutral"
            )

    return indicators


def get_trend_bias(coin: str, coin_cfg: dict) -> dict:
    """
    Fetch the daily (1d) trend for a coin and return a simple bias dict.
    Used as higher-timeframe context for the AI advisor.
    """
    daily_cfg            = dict(coin_cfg)
    daily_cfg["interval"] = "1d"
    daily_cfg["period"]   = "90d"

    df = download_data(daily_cfg["ticker"], daily_cfg["interval"], daily_cfg["period"])
    if df is None or len(df) < 50:
        return {"coin": coin, "trend": "neutral", "rsi": 50.0,
                "ma_alignment": "mixed", "hurst": 0.5}

    ind = calculate_indicators(df)
    if not ind:
        return {"coin": coin, "trend": "neutral", "rsi": 50.0,
                "ma_alignment": "mixed", "hurst": 0.5}

    trend = (
        "bullish" if ind["ma_alignment"] == "bullish" and ind["rsi"] > 50 else
        "bearish" if ind["ma_alignment"] == "bearish" and ind["rsi"] < 50 else
        "neutral"
    )
    return {
        "coin":          coin,
        "trend":         trend,
        "rsi":           ind["rsi"],
        "ma_alignment":  ind["ma_alignment"],
        "price_vs_kc":   ind["price_vs_kc"],
        "hurst":         ind["hurst"],
        "market_regime": ind["market_regime"],
        "adx":           ind["adx"],
    }


# ─── DISPLAY ──────────────────────────────────────────────────────────────────

def print_indicators(indicators: dict) -> None:
    """Pretty-print indicator values to terminal. Branches on strategy_type."""
    c  = indicators["coin"]
    p  = indicators["price"]
    st = indicators.get("strategy_type", "mean_reversion")

    regime_color = (
        Fore.GREEN  if indicators.get("market_regime") == "mean_reverting" else
        Fore.YELLOW if indicators.get("market_regime") == "trending"       else
        Fore.WHITE
    )
    vol_color = (
        Fore.RED   if indicators.get("vol_regime") == "high" else
        Fore.GREEN if indicators.get("vol_regime") == "low"  else
        Fore.WHITE
    )

    print(f"\n  {Fore.CYAN}{'─'*52}")
    print(f"  {Fore.CYAN}{c}  {Fore.WHITE}${p:,.4f}  {Fore.YELLOW}[{indicators['interval']}]"
          f"  {Fore.CYAN}[{st.upper()}]{Style.RESET_ALL}")

    if st == "supertrend":
        d   = indicators.get("st_direction", 0)
        sig = indicators.get("st_signal", "hold")
        d_color = Fore.GREEN if d == 1 else Fore.RED
        sig_color = (Fore.GREEN if sig == "long" else
                     Fore.RED   if sig == "short" else Fore.YELLOW)
        flipped_str = "  ← FLIPPED" if indicators.get("st_flipped") else ""
        print(f"  ST   line={indicators['st_line']:,.4f}  "
              f"direction={d_color}{'UP' if d == 1 else 'DOWN'}{Style.RESET_ALL}"
              f"{Fore.YELLOW}{flipped_str}{Style.RESET_ALL}")
        print(f"  Signal: {sig_color}{sig.upper()}{Style.RESET_ALL}  |  "
              f"MA_trend={indicators['ma_trend']:,.4f}  ({indicators['trend_direction']})")
    else:
        r = indicators["rsi"]
        zone_color = (
            Fore.GREEN if indicators["rsi_zone"] == "oversold"   else
            Fore.RED   if indicators["rsi_zone"] == "overbought" else
            Fore.WHITE
        )
        kc_color = (
            Fore.GREEN if indicators["price_vs_kc"] == "below lower band" else
            Fore.RED   if indicators["price_vs_kc"] == "above upper band" else
            Fore.WHITE
        )
        print(f"  KC   upper={indicators['kc_upper']:,.4f}  mid={indicators['kc_mid']:,.4f}  "
              f"lower={indicators['kc_lower']:,.4f}")
        print(f"  MA   fast={indicators['ma_fast']:,.4f}  slow={indicators['ma_slow']:,.4f}  "
              f"trend={indicators['ma_trend']:,.4f}")
        print(f"  RSI  {zone_color}{r:.1f} ({indicators['rsi_zone']}){Style.RESET_ALL}  |  "
              f"KC {kc_color}{indicators['price_vs_kc']}{Style.RESET_ALL}  |  "
              f"MA {indicators['ma_alignment']}")

    print(f"  ADX  {indicators['adx']:.1f} ({indicators['trend_strength']})  |  "
          f"Regime {regime_color}{indicators.get('market_regime','?')}{Style.RESET_ALL}"
          f"  (H={indicators['hurst']:.3f})  |  "
          f"Vol {vol_color}{indicators.get('vol_regime','?')}{Style.RESET_ALL}"
          f" ({indicators.get('ann_vol',0)*100:.1f}% ann.)")
    mom = indicators.get("momentum", 0)
    mom_color = Fore.GREEN if mom > 0 else Fore.RED if mom < 0 else Fore.WHITE
    print(f"  Mom  {mom_color}{mom:+.4f}{Style.RESET_ALL}")
