"""Hyperliquid candle access for runtime indicator and backtest inputs."""
import logging
import math
import time

import pandas as pd

from execution.hyperliquid_client import _hl_post

logger = logging.getLogger(__name__)

_TIMEFRAME_TO_HL = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

_INTERVAL_MS = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

_ASSET_TO_SYMBOL: dict[int, str] = {}
_SYMBOL_TO_ASSET: dict[str, int] = {}


def _refresh_asset_maps() -> None:
    payload = _hl_post("info", {"type": "metaAndAssetCtxs"})
    if not isinstance(payload, list) or not payload:
        raise ValueError("invalid Hyperliquid metaAndAssetCtxs payload")
    meta = payload[0]
    if not isinstance(meta, dict):
        raise ValueError("invalid Hyperliquid meta payload")
    universe = meta.get("universe", [])
    asset_to_symbol: dict[int, str] = {}
    symbol_to_asset: dict[str, int] = {}
    for asset_id, asset in enumerate(universe):
        symbol = str(asset.get("name", "")).strip().upper()
        if not symbol:
            continue
        asset_to_symbol[asset_id] = symbol
        symbol_to_asset[symbol] = asset_id
    if not asset_to_symbol:
        raise ValueError("empty Hyperliquid universe")
    _ASSET_TO_SYMBOL.clear()
    _ASSET_TO_SYMBOL.update(asset_to_symbol)
    _SYMBOL_TO_ASSET.clear()
    _SYMBOL_TO_ASSET.update(symbol_to_asset)


def resolve_asset_id(hl_symbol: str) -> int | None:
    """Resolve a Hyperliquid symbol to its asset id via the public info API."""
    try:
        symbol = str(hl_symbol).strip().upper()
        if symbol in _SYMBOL_TO_ASSET:
            return _SYMBOL_TO_ASSET[symbol]
        _refresh_asset_maps()
        return _SYMBOL_TO_ASSET.get(symbol)
    except Exception as exc:
        logger.warning(f"HL asset id resolution failed for {hl_symbol}: {exc}")
        return None


def _symbol_for_asset(asset_id: int) -> str | None:
    try:
        if asset_id in _ASSET_TO_SYMBOL:
            return _ASSET_TO_SYMBOL[asset_id]
        _refresh_asset_maps()
        return _ASSET_TO_SYMBOL.get(asset_id)
    except Exception as exc:
        logger.warning(f"HL symbol resolution failed for asset_id={asset_id}: {exc}")
        return None


def normalize_timeframe(timeframe: str) -> str | None:
    return _TIMEFRAME_TO_HL.get(str(timeframe).strip().lower())


def bars_for_lookback(timeframe: str, lookback: str | int, warmup_bars: int = 0) -> int:
    """Convert a legacy lookback string like 60d into an HL candle limit."""
    tf = normalize_timeframe(timeframe)
    if tf is None:
        return 0
    interval_ms = _INTERVAL_MS[tf]
    if isinstance(lookback, int):
        return max(lookback + warmup_bars, 1)
    raw = str(lookback).strip().lower()
    if raw.isdigit():
        return max(int(raw) + warmup_bars, 1)
    if len(raw) < 2:
        return 0
    unit = raw[-1]
    value = int(raw[:-1])
    duration_ms = value * {
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }.get(unit, 0)
    if duration_ms <= 0:
        return 0
    return max(int(math.ceil(duration_ms / interval_ms)) + warmup_bars, 1)


def get_hl_candles(asset_id: int, timeframe: str, limit: int) -> pd.DataFrame | None:
    """
    Fetch Hyperliquid candles and return a normalized DataFrame:
    ts, open, high, low, close, volume
    """
    if not isinstance(asset_id, int) or asset_id < 0:
        logger.warning(f"HL candles skipped: invalid asset_id={asset_id}")
        return None
    hl_interval = normalize_timeframe(timeframe)
    if hl_interval is None:
        logger.warning(f"HL candles skipped: unsupported timeframe={timeframe}")
        return None
    if not isinstance(limit, int) or limit <= 0:
        logger.warning(f"HL candles skipped: invalid limit={limit}")
        return None
    symbol = _symbol_for_asset(asset_id)
    if not symbol:
        logger.warning(f"HL candles skipped: no symbol for asset_id={asset_id}")
        return None

    interval_ms = _INTERVAL_MS[hl_interval]
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (limit * interval_ms)
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": symbol,
            "interval": hl_interval,
            "startTime": start_ms,
            "endTime": end_ms,
        },
    }

    try:
        candles = _hl_post("info", payload)
    except Exception as exc:
        logger.warning(f"HL candles failed for {symbol}: {exc}")
        return None
    if not isinstance(candles, list) or not candles:
        logger.warning(f"HL candles empty for {symbol}")
        return None

    rows = candles[-limit:]
    df = pd.DataFrame(
        {
            "ts": [pd.to_datetime(int(c["t"]), unit="ms", utc=True) for c in rows],
            "open": [float(c["o"]) for c in rows],
            "high": [float(c["h"]) for c in rows],
            "low": [float(c["l"]) for c in rows],
            "close": [float(c["c"]) for c in rows],
            "volume": [float(c["v"]) for c in rows],
        }
    )
    df.dropna(inplace=True)
    logger.debug(f"HL candles fetched for {symbol} [{hl_interval}] (n={len(df)})")
    return df
