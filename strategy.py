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
import logging
from colorama import Fore, Style
from hltrading.shared.hyperliquid_candles import (
    bars_for_lookback,
    get_hl_candles as get_hl_candles_df,
    resolve_asset_id,
)
from config import (
    COINS,
    KC_PERIOD, KC_SCALAR, MA_FAST, MA_SLOW, MA_TREND, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    HURST_MR_MAX, MTF_TIMEFRAME_DEFAULTS, STRATEGY_ALLOWED_REGIMES,
    REGIME_TREND_ADX_MIN, REGIME_RANGE_ADX_MAX, REGIME_HIGH_VOL_ATR_PCT,
    REGIME_VOL_EXPANSION_BANDWIDTH, EXTREME_VOL_ATR_PCT,
    FUNDING_EXTREME_ABS, FUNDING_HARD_BLOCK_ABS, OI_MIN_PCT_CHANGE,
    BTC_FILTER_INTERVAL, BTC_FILTER_PERIOD, BTC_FILTER_TREND_ADX,
    BTC_FILTER_EXTREME_VOL_ATR_PCT,
    CASCADE_VOLUME_SPIKE_MIN, CASCADE_RANGE_ATR_MIN, CASCADE_BREAKOUT_LOOKBACK,
    CASCADE_BREAKOUT_ATR_BUFFER, CASCADE_EXTREME_VOLUME_SPIKE, CASCADE_EXTREME_RANGE_ATR,
)

# Configure logging
logger = logging.getLogger(__name__)

_DATA_CACHE: dict[tuple[str, str, str], dict] = {}
_INDICATOR_CACHE: dict[tuple, dict] = {}
_TREND_BIAS_CACHE: dict[tuple, dict] = {}
_TF_CONTEXT_CACHE: dict[tuple, dict] = {}
_DERIVATIVES_SNAPSHOT_CACHE: dict[str, dict] = {}
_BTC_FILTER_CACHE: dict[tuple, dict] = {}


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
            avg_vol = _safe(volume.rolling(21).mean().iloc[-1], 0.0)
            if np.isfinite(avg_vol) and avg_vol > 0:
                vol_ratio = _safe(volume.iloc[-1] / avg_vol, 1.0)
            else:
                vol_ratio = 1.0
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


def _default_period_for_interval(interval: str) -> str:
    if interval.endswith("m"):
        minutes = int(interval[:-1])
        if minutes <= 5:
            return "60d"
        if minutes <= 15:
            return "90d"
        return "180d"
    if interval.endswith("h"):
        hours = int(interval[:-1])
        return "365d" if hours <= 4 else "730d"
    if interval.endswith("d"):
        return "730d"
    return "180d"


def _normalize_mtf_config(coin_cfg: dict) -> dict[str, dict[str, str]]:
    configured = coin_cfg.get("timeframes", {}) or {}
    entry_interval = configured.get("entry") or coin_cfg.get("interval", "5m")
    entry_period = coin_cfg.get("period") or _default_period_for_interval(entry_interval)

    result = {
        "higher": dict(MTF_TIMEFRAME_DEFAULTS.get("higher", {})),
        "mid": dict(MTF_TIMEFRAME_DEFAULTS.get("mid", {})),
        "entry": dict(MTF_TIMEFRAME_DEFAULTS.get("entry", {})),
    }
    for key in ("higher", "mid"):
        cfg_value = configured.get(key)
        if isinstance(cfg_value, dict):
            result[key].update({k: v for k, v in cfg_value.items() if v})
        elif cfg_value:
            result[key]["interval"] = cfg_value
        result[key]["period"] = result[key].get("period") or _default_period_for_interval(result[key]["interval"])

    entry_cfg = configured.get("entry")
    if isinstance(entry_cfg, dict):
        entry_interval = entry_cfg.get("interval") or entry_interval
        entry_period = entry_cfg.get("period") or entry_period
    elif entry_cfg:
        entry_interval = entry_cfg
    result["entry"] = {"interval": entry_interval, "period": entry_period}
    return result


def _resolve_allowed_regimes(coin_cfg: dict) -> tuple[str, ...]:
    explicit = coin_cfg.get("allowed_regimes")
    if explicit:
        return tuple(explicit)
    strategy_type = coin_cfg.get("strategy_type", "mean_reversion")
    return tuple(STRATEGY_ALLOWED_REGIMES.get(strategy_type, ("trend", "range", "high_volatility")))


def _indicator_trend_label(indicators: dict) -> str:
    if indicators.get("strategy_type") == "supertrend":
        direction = indicators.get("st_direction", 0)
        return "bullish" if direction == 1 else "bearish" if direction == -1 else "neutral"
    ma_alignment = indicators.get("ma_alignment")
    if ma_alignment == "bullish":
        return "bullish"
    if ma_alignment == "bearish":
        return "bearish"
    trend_direction = indicators.get("trend_direction", "flat")
    if trend_direction == "up":
        return "bullish"
    if trend_direction == "down":
        return "bearish"
    return "neutral"


def _build_tf_snapshot(coin: str, coin_cfg: dict, tf_name: str, interval: str, period: str) -> dict:
    cache_key = (coin, tf_name, interval, period)
    df = get_market_data(
        coin,
        interval,
        period,
        asset_id=coin_cfg.get("asset_id"),
        hl_symbol=coin_cfg.get("hl_symbol", coin),
        warmup_bars=120,
        scan_cache=coin_cfg.get("_scan_market_data_cache"),
    )
    if df is None or df.empty:
        return {"interval": interval, "period": period, "trend": "neutral", "available": False}

    signature = _data_signature(df)
    cached = _TF_CONTEXT_CACHE.get(cache_key)
    if cached and cached["signature"] == signature:
        return dict(cached["snapshot"])

    indicators = calculate_indicators(df)
    if not indicators:
        return {"interval": interval, "period": period, "trend": "neutral", "available": False}

    snapshot = {
        "interval": interval,
        "period": period,
        "trend": _indicator_trend_label(indicators),
        "adx": indicators.get("adx", 0.0),
        "ma_alignment": indicators.get("ma_alignment", "mixed"),
        "trend_direction": indicators.get("trend_direction", "flat"),
        "market_regime": indicators.get("market_regime", "neutral"),
        "price": indicators.get("price", 0.0),
        "ma_trend": indicators.get("ma_trend", 0.0),
        "available": True,
    }
    _TF_CONTEXT_CACHE[cache_key] = {"signature": signature, "snapshot": dict(snapshot)}
    return snapshot


def _build_multi_timeframe_context(coin: str, coin_cfg: dict, market_data_cache: dict | None = None) -> dict:
    if market_data_cache is not None and coin_cfg.get("_scan_market_data_cache") is not market_data_cache:
        coin_cfg = dict(coin_cfg)
        coin_cfg["_scan_market_data_cache"] = market_data_cache
    tf_cfg = _normalize_mtf_config(coin_cfg)
    higher = _build_tf_snapshot(coin, coin_cfg, "higher", tf_cfg["higher"]["interval"], tf_cfg["higher"]["period"])
    mid = _build_tf_snapshot(coin, coin_cfg, "mid", tf_cfg["mid"]["interval"], tf_cfg["mid"]["period"])
    higher_trend = higher.get("trend", "neutral")
    mid_trend = mid.get("trend", "neutral")
    aligned = higher_trend != "neutral" and higher_trend == mid_trend
    direction = higher_trend if aligned else mid_trend if mid_trend != "neutral" else higher_trend
    return {
        "higher": higher,
        "mid": mid,
        "entry": tf_cfg["entry"],
        "direction": direction if direction in ("bullish", "bearish") else "neutral",
        "aligned": aligned,
    }


def _classify_trading_regime(indicators: dict, mtf_context: dict | None = None) -> str:
    adx = float(indicators.get("adx", 0.0))
    atr = float(indicators.get("atr", 0.0))
    price = max(float(indicators.get("price", 0.0)), 1e-8)
    vol_regime = indicators.get("vol_regime", "normal")
    atr_pct = atr / price
    band_width_pct = float(indicators.get("band_width_pct", 0.0))
    mtf_direction = (mtf_context or {}).get("direction", "neutral")
    mtf_aligned = bool((mtf_context or {}).get("aligned", False))

    if (vol_regime == "high" and atr_pct >= REGIME_HIGH_VOL_ATR_PCT) or band_width_pct >= REGIME_VOL_EXPANSION_BANDWIDTH:
        return "volatility_expansion"
    if adx >= REGIME_TREND_ADX_MIN and mtf_direction in ("bullish", "bearish"):
        return "trend"
    if adx <= REGIME_RANGE_ADX_MAX and float(indicators.get("hurst", 0.5)) <= HURST_MR_MAX:
        return "range"
    if mtf_aligned and mtf_direction in ("bullish", "bearish"):
        return "trend"
    return "volatility_expansion" if vol_regime == "high" else "range"


def strategy_matches_regime(coin_cfg: dict, regime: str) -> bool:
    return regime in _resolve_allowed_regimes(coin_cfg)


def _build_btc_market_filter_snapshot(
    btc_cfg: dict | None = None,
    market_data_cache: dict | None = None,
) -> dict:
    """Return a compact BTC market-state snapshot for altcoin gating."""
    btc_cfg = dict(btc_cfg or get_coin_config("BTC") or {})
    btc_cfg.setdefault("hl_symbol", "BTC")
    btc_cfg["interval"] = BTC_FILTER_INTERVAL
    btc_cfg["period"] = BTC_FILTER_PERIOD
    if not isinstance(btc_cfg.get("asset_id"), int):
        btc_cfg["asset_id"] = resolve_asset_id(btc_cfg["hl_symbol"])
    logger.debug(
        "BTC filter cfg: %s",
        {
            "hl_symbol": btc_cfg.get("hl_symbol"),
            "asset_id": btc_cfg.get("asset_id"),
            "interval": btc_cfg.get("interval"),
            "period": btc_cfg.get("period"),
            "timeframes": btc_cfg.get("timeframes"),
        },
    )
    if not btc_cfg.get("hl_symbol") or not btc_cfg.get("interval") or not btc_cfg.get("period"):
        return {
            "available": False,
            "risk_off": False,
            "trend_spike": False,
            "vol_spike": False,
            "atr_pct": 0.0,
            "adx": 0.0,
            "regime": "unknown",
        }
    cache_key = ("BTC", BTC_FILTER_INTERVAL, BTC_FILTER_PERIOD)
    df = get_market_data(
        "BTC",
        btc_cfg["interval"],
        btc_cfg["period"],
        asset_id=btc_cfg.get("asset_id"),
        hl_symbol=btc_cfg["hl_symbol"],
        warmup_bars=120,
        scan_cache=market_data_cache,
    )
    if df is None or df.empty:
        return {
            "available": False,
            "risk_off": False,
            "trend_spike": False,
            "vol_spike": False,
            "atr_pct": 0.0,
            "adx": 0.0,
            "regime": "unknown",
        }

    signature = _data_signature(df)
    cached = _BTC_FILTER_CACHE.get(cache_key)
    if cached and cached["signature"] == signature:
        return dict(cached["snapshot"])

    indicators = calculate_indicators(df)
    mtf_context = _build_multi_timeframe_context("BTC", btc_cfg, market_data_cache=market_data_cache)
    regime = _classify_trading_regime(indicators or {}, mtf_context) if indicators else "unknown"
    adx = float((indicators or {}).get("adx", 0.0))
    atr_pct = float((indicators or {}).get("atr_pct", 0.0))
    trend_spike = adx >= BTC_FILTER_TREND_ADX
    vol_spike = atr_pct >= BTC_FILTER_EXTREME_VOL_ATR_PCT or regime == "volatility_expansion"
    snapshot = {
        "available": indicators is not None,
        "risk_off": trend_spike or vol_spike,
        "trend_spike": trend_spike,
        "vol_spike": vol_spike,
        "atr_pct": round(atr_pct, 4),
        "adx": round(adx, 1),
        "regime": regime,
        "trend_direction": (indicators or {}).get("trend_direction", "flat"),
    }
    _BTC_FILTER_CACHE[cache_key] = {"signature": signature, "snapshot": dict(snapshot)}
    return snapshot


def get_btc_market_filter(btc_cfg: dict | None = None, market_data_cache: dict | None = None) -> dict:
    return _build_btc_market_filter_snapshot(btc_cfg, market_data_cache=market_data_cache)


def _detect_liquidation_cascade(
    df: pd.DataFrame,
    *,
    price: float,
    atr_value: float,
    kc_upper: float | None = None,
    kc_lower: float | None = None,
) -> dict:
    """Detect a likely forced-liquidation move using current OHLCV structure only."""
    default = {
        "cascade_event": False,
        "cascade_direction": "neutral",
        "cascade_volume_spike": 1.0,
        "cascade_range_atr": 0.0,
        "cascade_breakout": False,
        "cascade_exhaustion": False,
        "extreme_cascade": False,
    }
    try:
        if len(df) < max(CASCADE_BREAKOUT_LOOKBACK + 2, 25) or atr_value <= 0:
            return default

        completed = df.iloc[:-1]
        last_bar = completed.iloc[-1]
        recent = completed.iloc[-(CASCADE_BREAKOUT_LOOKBACK + 1):-1]
        if recent.empty:
            return default

        bar_open = _safe(last_bar.get("Open", price), price)
        bar_close = _safe(last_bar.get("Close", price), price)
        bar_high = _safe(last_bar.get("High", price), price)
        bar_low = _safe(last_bar.get("Low", price), price)
        bar_range = max(0.0, bar_high - bar_low)
        candle_body = bar_close - bar_open

        volume = completed.get("Volume")
        vol_spike = 1.0
        if volume is not None and len(volume) >= 21:
            vol_ma = volume.rolling(20).mean().iloc[-2]
            if vol_ma and vol_ma > 0:
                vol_spike = _safe(volume.iloc[-1] / vol_ma, 1.0)

        range_atr = bar_range / max(atr_value, 1e-8)
        recent_high = _safe(recent["High"].max(), bar_high)
        recent_low = _safe(recent["Low"].min(), bar_low)
        breakout_up = bar_high >= recent_high + CASCADE_BREAKOUT_ATR_BUFFER * atr_value
        breakout_down = bar_low <= recent_low - CASCADE_BREAKOUT_ATR_BUFFER * atr_value

        direction = "neutral"
        if breakout_up and candle_body >= 0:
            direction = "up"
        elif breakout_down and candle_body <= 0:
            direction = "down"

        cascade_event = (
            vol_spike >= CASCADE_VOLUME_SPIKE_MIN and
            range_atr >= CASCADE_RANGE_ATR_MIN and
            direction in ("up", "down")
        )

        close_off_high = (bar_high - bar_close) / max(bar_range, 1e-8)
        close_off_low = (bar_close - bar_low) / max(bar_range, 1e-8)
        exhaustion = False
        if cascade_event and direction == "up":
            exhaustion = bool(kc_upper and price > kc_upper and close_off_high >= 0.35)
        elif cascade_event and direction == "down":
            exhaustion = bool(kc_lower and price < kc_lower and close_off_low >= 0.35)

        extreme = (
            cascade_event and
            vol_spike >= CASCADE_EXTREME_VOLUME_SPIKE and
            range_atr >= CASCADE_EXTREME_RANGE_ATR
        )

        return {
            "cascade_event": cascade_event,
            "cascade_direction": direction,
            "cascade_volume_spike": round(vol_spike, 3),
            "cascade_range_atr": round(range_atr, 3),
            "cascade_breakout": breakout_up or breakout_down,
            "cascade_exhaustion": exhaustion,
            "extreme_cascade": extreme,
        }
    except Exception:
        return default


def select_strategy_candidates(candidates: list[tuple[str, dict, dict]]) -> list[tuple[str, dict, dict]]:
    """Pick at most one candidate per underlying symbol, preferring regime-compatible setups."""
    grouped: dict[str, list[tuple[str, dict, dict]]] = {}
    for coin, cfg, indicators in candidates:
        key = cfg.get("hl_symbol", coin)
        grouped.setdefault(key, []).append((coin, cfg, indicators))

    selected: list[tuple[str, dict, dict]] = []
    for group in grouped.values():
        compatible = [item for item in group if item[2].get("strategy_regime_match", False)]
        if not compatible:
            continue
        pool = compatible
        pool.sort(
            key=lambda item: (
                1 if item[2].get("strategy_regime_match", False) else 0,
                item[2].get("allocator_score", 0.0),
                item[2].get("entry_quality", 0.0),
            ),
            reverse=True,
        )
        selected.append(pool[0])
    return selected


def attach_derivatives_context(coin: str, indicators: dict,
                               funding_rate: float | None = None,
                               open_interest: float | None = None) -> dict:
    """Add funding/OI context without forcing callers to manage state."""
    price = float(indicators.get("price", 0.0))
    snapshot = _DERIVATIVES_SNAPSHOT_CACHE.get(coin, {})
    prev_price = float(snapshot.get("price", price))
    prev_oi = snapshot.get("open_interest")
    oi_delta_pct = 0.0
    if open_interest is not None and prev_oi not in (None, 0):
        oi_delta_pct = (float(open_interest) - float(prev_oi)) / abs(float(prev_oi))
    price_delta_pct = 0.0
    if prev_price:
        price_delta_pct = (price - prev_price) / prev_price

    oi_signal = "neutral"
    if open_interest is not None and abs(oi_delta_pct) >= OI_MIN_PCT_CHANGE:
        if price_delta_pct > 0 and oi_delta_pct > 0:
            oi_signal = "trend_up_confirmed"
        elif price_delta_pct < 0 and oi_delta_pct > 0:
            oi_signal = "trend_down_confirmed"
        elif price_delta_pct > 0 and oi_delta_pct < 0:
            oi_signal = "short_covering"
        elif price_delta_pct < 0 and oi_delta_pct < 0:
            oi_signal = "long_liquidation"

    funding_extreme = funding_rate is not None and abs(float(funding_rate)) >= FUNDING_EXTREME_ABS
    funding_hard_block = funding_rate is not None and abs(float(funding_rate)) >= FUNDING_HARD_BLOCK_ABS
    funding_bias = "neutral"
    if funding_extreme:
        funding_bias = "short" if float(funding_rate) > 0 else "long"

    indicators["funding_rate"] = float(funding_rate) if funding_rate is not None else None
    indicators["funding_extreme"] = funding_extreme
    indicators["funding_hard_block"] = funding_hard_block
    indicators["funding_bias"] = funding_bias
    indicators["open_interest"] = float(open_interest) if open_interest is not None else None
    indicators["oi_delta_pct"] = round(oi_delta_pct, 4)
    indicators["price_delta_pct"] = round(price_delta_pct, 4)
    indicators["oi_signal"] = oi_signal
    indicators["trend_confirmation"] = (
        "bullish" if oi_signal == "trend_up_confirmed" else
        "bearish" if oi_signal == "trend_down_confirmed" else
        "weakening"
    )
    indicators["trend_oi_confirmed"] = oi_signal in ("trend_up_confirmed", "trend_down_confirmed")
    indicators["trend_oi_divergence"] = oi_signal in ("short_covering", "long_liquidation")
    indicators["extreme_volatility"] = (
        indicators.get("regime") == "volatility_expansion" and
        float(indicators.get("atr_pct", 0.0)) >= EXTREME_VOL_ATR_PCT
    )
    indicators["allocator_score"] = round(
        (0.4 if indicators.get("strategy_regime_match") else 0.0) +
        (0.3 if indicators.get("mtf_alignment") else 0.0) +
        (0.2 if oi_signal in ("trend_up_confirmed", "trend_down_confirmed") else 0.0) +
        (0.1 if funding_extreme else 0.0),
        4,
    )

    _DERIVATIVES_SNAPSHOT_CACHE[coin] = {
        "price": price,
        "open_interest": open_interest,
    }
    return indicators


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
            "atr_pct":         round((atr_val / price) if price else 0.0, 4),
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

        latest.update(
            _detect_liquidation_cascade(
                df,
                price=price,
                atr_value=atr_val,
            )
        )

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

def get_market_data(
    coin: str,
    timeframe: str,
    lookback: str | int,
    *,
    asset_id: int | None = None,
    hl_symbol: str | None = None,
    warmup_bars: int = 0,
    scan_cache: dict | None = None,
) -> pd.DataFrame | None:
    """Fetch Hyperliquid candles and normalize them for the indicator engine."""
    symbol = str(hl_symbol or coin).strip().upper()
    resolved_asset_id = asset_id if isinstance(asset_id, int) and asset_id >= 0 else resolve_asset_id(symbol)
    limit = bars_for_lookback(timeframe, lookback, warmup_bars=warmup_bars)
    scan_key = (resolved_asset_id, timeframe)
    if scan_cache is not None and isinstance(resolved_asset_id, int) and resolved_asset_id >= 0:
        cached_scan = scan_cache.get(scan_key)
        if cached_scan and cached_scan.get("limit", 0) >= limit:
            return cached_scan["df"].tail(limit).copy()
    cache_key = (symbol, resolved_asset_id or -1, timeframe, str(lookback), warmup_bars)
    cache_ttl = 0
    now = time.monotonic()
    cached = _DATA_CACHE.get(cache_key)
    if cache_ttl > 0 and cached and (now - cached["fetched_at"] < cache_ttl):
        logger.debug(f"Using cached HL candles for {symbol} [{timeframe}]")
        return cached["df"].copy()
    if not isinstance(resolved_asset_id, int) or resolved_asset_id < 0:
        logger.warning(f"HL candles skipped for {coin}: invalid asset_id for {symbol}")
        return None
    try:
        raw_df = get_hl_candles_df(resolved_asset_id, timeframe, limit)
    except Exception as exc:
        logger.warning(f"HL candles failed for {coin}: {exc}")
        return None
    if raw_df is None or raw_df.empty:
        logger.warning(f"HL candles unavailable for {coin}")
        return None
    df = raw_df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).copy()
    df.index = pd.DatetimeIndex(raw_df["ts"])
    if limit > 0:
        df = df.tail(limit).copy()
    if scan_cache is not None:
        existing = scan_cache.get(scan_key)
        if not existing or existing.get("limit", 0) < limit:
            scan_cache[scan_key] = {"limit": limit, "df": df.copy()}
    _DATA_CACHE[cache_key] = {"fetched_at": now, "df": df.copy()}
    return df


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
        # The last row in a live candle snapshot is the still-forming current candle;
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
            "atr_pct":  round((atr_now / price_now) if price_now else 0.0, 4),
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
            "band_width_pct": round(
                ((_safe(kc_upper.iloc[-1]) - _safe(kc_lower.iloc[-1])) / price_now)
                if price_now else 0.0,
                4,
            ),
        }

        latest.update(
            _detect_liquidation_cascade(
                df,
                price=price_now,
                atr_value=atr_now,
                kc_upper=_safe(kc_upper.iloc[-1]),
                kc_lower=_safe(kc_lower.iloc[-1]),
            )
        )

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


def get_indicators_for_coin(coin: str, coin_cfg: dict, market_data_cache: dict | None = None) -> dict | None:
    """
    Convenience wrapper: fetch HL candles + calculate for a coin config dict.
    Routes to supertrend or mean-reversion indicators based on strategy_type.
    """
    logger.debug(f"Getting indicators for {coin}")
    df = get_market_data(
        coin,
        coin_cfg["interval"],
        coin_cfg["period"],
        asset_id=coin_cfg.get("asset_id"),
        hl_symbol=coin_cfg.get("hl_symbol", coin),
        warmup_bars=250,
        scan_cache=market_data_cache,
    )
    if df is None:
        logger.warning(f"Failed to fetch HL candles for {coin}")
        return None
    cache_key = (
        coin,
        coin_cfg["interval"],
        coin_cfg["period"],
        coin_cfg.get("strategy_type", "mean_reversion"),
        str(coin_cfg.get("timeframes", {})),
        tuple(coin_cfg.get("allowed_regimes", ()) or ()),
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
        mtf_context = _build_multi_timeframe_context(coin, coin_cfg, market_data_cache=market_data_cache)
        indicators["mtf"] = mtf_context
        indicators["htf_trend"] = mtf_context["higher"].get("trend", "neutral")
        indicators["mid_tf_trend"] = mtf_context["mid"].get("trend", "neutral")
        indicators["entry_tf"] = mtf_context["entry"].get("interval", coin_cfg.get("interval"))
        indicators["mtf_direction"] = mtf_context.get("direction", "neutral")
        indicators["mtf_alignment"] = mtf_context.get("aligned", False)
        indicators["regime"] = _classify_trading_regime(indicators, mtf_context)
        indicators["allowed_regimes"] = _resolve_allowed_regimes(coin_cfg)
        indicators["strategy_regime_match"] = strategy_matches_regime(coin_cfg, indicators["regime"])
        _INDICATOR_CACHE[cache_key] = {"signature": signature, "indicators": dict(indicators)}
    else:
        logger.warning(f"Failed to calculate indicators for {coin}")
    
    return indicators


def get_trend_bias(coin: str, coin_cfg: dict, market_data_cache: dict | None = None) -> dict:
    """
    Fetch the daily (1d) trend for a coin and return a simple bias dict.
    Used as higher-timeframe context for the AI advisor.
    """
    logger.info(f"Getting daily trend bias for {coin}")
    daily_cfg            = dict(coin_cfg)
    daily_cfg["interval"] = "1d"
    daily_cfg["period"]   = "90d"

    df = get_market_data(
        coin,
        daily_cfg["interval"],
        daily_cfg["period"],
        asset_id=daily_cfg.get("asset_id", coin_cfg.get("asset_id")),
        hl_symbol=daily_cfg.get("hl_symbol", coin_cfg.get("hl_symbol", coin)),
        warmup_bars=120,
        scan_cache=market_data_cache,
    )
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
        "regime":        _classify_trading_regime(
            ind,
            _build_multi_timeframe_context(coin, daily_cfg, market_data_cache=market_data_cache),
        ),
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
def get_coin_config(coin: str) -> dict | None:
    """Return a shallow copy of a coin config with resolved HL identifiers."""
    cfg = COINS.get(coin)
    if not isinstance(cfg, dict):
        return None
    resolved = dict(cfg)
    resolved.setdefault("hl_symbol", coin)
    if not isinstance(resolved.get("asset_id"), int):
        asset_id = resolve_asset_id(resolved["hl_symbol"])
        if isinstance(asset_id, int):
            resolved["asset_id"] = asset_id
    return resolved


def prefetch_scan_market_data(
    active_coins: dict[str, dict],
    *,
    ai_enabled: bool = False,
    include_btc_filter: bool = False,
) -> dict:
    """
    Preload all candle frames needed for a scan into a scan-scoped cache.
    Each (asset_id, timeframe) is fetched once using the largest required lookback.
    """
    requests: dict[tuple[int, str], dict] = {}

    def _register_request(
        coin: str,
        cfg: dict,
        timeframe: str,
        lookback: str | int,
        warmup_bars: int,
    ) -> None:
        hl_symbol = str(cfg.get("hl_symbol", coin)).strip().upper()
        asset_id = cfg.get("asset_id")
        if not isinstance(asset_id, int):
            asset_id = resolve_asset_id(hl_symbol)
        if not isinstance(asset_id, int) or asset_id < 0:
            return
        limit = bars_for_lookback(timeframe, lookback, warmup_bars=warmup_bars)
        if limit <= 0:
            return
        key = (asset_id, timeframe)
        existing = requests.get(key)
        if not existing or existing["limit"] < limit:
            requests[key] = {
                "coin": coin,
                "hl_symbol": hl_symbol,
                "asset_id": asset_id,
                "timeframe": timeframe,
                "lookback": lookback,
                "warmup_bars": warmup_bars,
                "limit": limit,
            }

    for coin, cfg in active_coins.items():
        _register_request(coin, cfg, cfg.get("interval", "5m"), cfg.get("period", "60d"), 250)
        tf_cfg = _normalize_mtf_config(cfg)
        for tf_name in ("higher", "mid"):
            tf = tf_cfg[tf_name]
            _register_request(coin, cfg, tf["interval"], tf["period"], 120)
        if ai_enabled:
            _register_request(coin, cfg, "1d", "90d", 120)

    if include_btc_filter:
        btc_cfg = get_coin_config("BTC") or {"hl_symbol": "BTC"}
        btc_cfg["interval"] = BTC_FILTER_INTERVAL
        btc_cfg["period"] = BTC_FILTER_PERIOD
        _register_request("BTC", btc_cfg, btc_cfg["interval"], btc_cfg["period"], 120)
        btc_tf_cfg = _normalize_mtf_config(btc_cfg)
        for tf_name in ("higher", "mid"):
            tf = btc_tf_cfg[tf_name]
            _register_request("BTC", btc_cfg, tf["interval"], tf["period"], 120)

    scan_cache: dict = {}
    for request in sorted(requests.values(), key=lambda item: item["limit"], reverse=True):
        get_market_data(
            request["coin"],
            request["timeframe"],
            request["lookback"],
            asset_id=request["asset_id"],
            hl_symbol=request["hl_symbol"],
            warmup_bars=request["warmup_bars"],
            scan_cache=scan_cache,
        )
    return scan_cache
