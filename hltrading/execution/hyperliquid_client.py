"""Read-only Hyperliquid REST client helpers."""
import json
import logging
import threading
import time as _time
import urllib.error
import urllib.request

from config import TESTNET, HL_WALLET_ADDRESS

logger = logging.getLogger(__name__)

# Session-level cache of coins/intervals that the HL API cannot serve (HTTP 500
# or empty response on first attempt). Prevents repeated API hits every scan
# cycle for unsupported symbols/intervals.
_HL_UNSUPPORTED: set[tuple[str, str]] = set()   # (coin, interval)


class HLDataStore:
    """Small locked cache for frequently-read Hyperliquid account state."""

    def __init__(self, ttl: float = 2.0):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._ts = 0.0
        self._data = {
            "clearinghouseState": None,
            "spotClearinghouseState": None,
            "openOrders": None,
            "allMids": None,
            "metaAndAssetCtxs": None,
        }

    def snapshot(self) -> dict:
        now = _time.time()
        if now - self._ts < self.ttl and any(v is not None for v in self._data.values()):
            return self._data
        with self._lock:
            now = _time.time()
            if now - self._ts < self.ttl and any(v is not None for v in self._data.values()):
                return self._data
            self._data = {
                "clearinghouseState": _hl_post("info", {"type": "clearinghouseState", "user": HL_WALLET_ADDRESS}),
                "spotClearinghouseState": _hl_post("info", {"type": "spotClearinghouseState", "user": HL_WALLET_ADDRESS}),
                "openOrders": _hl_post("info", {"type": "openOrders", "user": HL_WALLET_ADDRESS}),
                "allMids": _hl_post("info", {"type": "allMids"}),
                "metaAndAssetCtxs": _hl_post("info", {"type": "metaAndAssetCtxs"}),
            }
            self._ts = now
            logger.debug("HL fetch cycle refreshed")
            return self._data


_HL_DATA_STORE = HLDataStore(ttl=2.0)


def _interval_ms(interval: str) -> int:
    """Convert an interval string (e.g. '5m', '1h', '4h') to milliseconds."""
    unit = interval[-1].lower()
    value = int(interval[:-1])
    return value * {"m": 60_000, "h": 3_600_000, "d": 86_400_000}.get(unit, 300_000)


def _hl_base_url() -> str | None:
    """Return a validated Hyperliquid API URL, never the app URL."""
    from hyperliquid.utils import constants

    base = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL
    if not isinstance(base, str):
        logger.error("Invalid HL API URL type: %r", base)
        return None
    normalized = base.strip().rstrip("/")
    if not normalized.startswith("http"):
        logger.error("Invalid HL API URL: %s", normalized)
        return None
    if "app.hyperliquid" in normalized:
        logger.error("Invalid HL API URL (app URL, not API): %s", normalized)
        return None
    if "api.hyperliquid" not in normalized and "hyperliquid-testnet" not in normalized:
        logger.error("Unexpected HL API URL: %s", normalized)
        return None
    return normalized


def _hl_post(endpoint: str, payload: dict):
    """Direct HTTP call to Hyperliquid REST API. Returns None on failure."""
    base = _hl_base_url()
    if not base:
        return None

    url = base.rstrip("/") + "/" + endpoint.lstrip("/")
    logger.debug("HL request URL: %s", url)
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logger.warning("HL request failed (%s): %s", url, exc)
        return None


def get_hl_price(coin: str) -> float | None:
    """Fetch current mid price via direct API — no SDK Info needed."""
    try:
        mids = _HL_DATA_STORE.snapshot().get("allMids")
        if not isinstance(mids, dict):
            return None
        val = mids.get(coin)
        return float(val) if val else None
    except Exception:
        return None


def _get_asset_ctx(coin: str) -> dict | None:
    """Fetch current asset context for a perp symbol from metaAndAssetCtxs."""
    try:
        payload = _HL_DATA_STORE.snapshot().get("metaAndAssetCtxs")
        if not isinstance(payload, list) or len(payload) < 2:
            return None
        meta, asset_ctxs = payload[0], payload[1]
        universe = meta.get("universe", []) if isinstance(meta, dict) else []
        for idx, asset in enumerate(universe):
            if asset.get("name") == coin and idx < len(asset_ctxs):
                ctx = asset_ctxs[idx]
                return ctx if isinstance(ctx, dict) else None
    except Exception:
        return None
    return None


def get_hl_funding_rate(coin: str) -> float | None:
    """Fetch current funding rate for a perp symbol."""
    try:
        ctx = _get_asset_ctx(coin)
        if not ctx:
            return None
        value = ctx.get("funding") or ctx.get("fundingRate")
        return float(value) if value is not None else None
    except Exception:
        return None


def get_hl_open_interest(coin: str) -> float | None:
    """Fetch current open interest for a perp symbol."""
    try:
        ctx = _get_asset_ctx(coin)
        if not ctx:
            return None
        value = (
            ctx.get("openInterest")
            or ctx.get("open_interest")
            or ctx.get("oi")
        )
        return float(value) if value is not None else None
    except Exception:
        return None


def get_hl_mark_oracle(coin: str) -> dict | None:
    """Fetch mark/oracle prices and current deviation for a perp symbol."""
    try:
        ctx = _get_asset_ctx(coin)
        if not ctx:
            return None
        mark = ctx.get("markPx") or ctx.get("mark") or ctx.get("midPx") or ctx.get("mid")
        oracle = ctx.get("oraclePx") or ctx.get("oracle")
        if mark is None or oracle is None:
            return None
        mark_px = float(mark)
        oracle_px = float(oracle)
        if oracle_px <= 0:
            return None
        return {
            "mark": mark_px,
            "oracle": oracle_px,
            "deviation": abs(mark_px - oracle_px) / oracle_px,
        }
    except Exception:
        return None


def get_hl_obi(coin: str, levels: int = 10) -> float | None:
    """
    Order Book Imbalance for top `levels` of the HL L2 book.
    OBI = (bid_vol - ask_vol) / (bid_vol + ask_vol), range [-1, +1].
      +1 = pure bid pressure (buyers dominating)
      -1 = pure ask pressure (sellers dominating)
    Returns None on any fetch/parse error — caller should treat as neutral.
    """
    try:
        book = _hl_post("info", {"type": "l2Book", "coin": coin})
        bids = book.get("levels", [[], []])[0][:levels]
        asks = book.get("levels", [[], []])[1][:levels]
        bid_vol = sum(float(b["sz"]) for b in bids)
        ask_vol = sum(float(a["sz"]) for a in asks)
        total = bid_vol + ask_vol
        if total == 0:
            return None
        return (bid_vol - ask_vol) / total
    except Exception:
        return None


def get_hl_positions() -> list:
    """Fetch open perps positions via direct API."""
    try:
        state = _HL_DATA_STORE.snapshot().get("clearinghouseState")
        if not isinstance(state, dict):
            return []
        return state.get("assetPositions", [])
    except Exception:
        return []


def get_hl_open_orders() -> list:
    """Fetch open orders from the shared HL data store."""
    try:
        orders = _HL_DATA_STORE.snapshot().get("openOrders")
        return orders if isinstance(orders, list) else []
    except Exception:
        return []


def get_hl_account_info() -> dict | None:
    """Fetch unified account info (perps equity + spot USDC)."""
    try:
        snapshot = _HL_DATA_STORE.snapshot()
        perps = snapshot.get("clearinghouseState")
        if not isinstance(perps, dict):
            return None
        margin = perps.get("crossMarginSummary") or perps.get("marginSummary") or {}

        spot = snapshot.get("spotClearinghouseState")
        if not isinstance(spot, dict):
            return None
        spot_usdc = sum(
            float(balance["total"]) for balance in spot.get("balances", [])
            if balance.get("coin") == "USDC"
        )
        perps_equity = float(margin.get("accountValue", 0))
        withdrawable = float(perps.get("withdrawable", 0))

        return {
            "account_value": perps_equity + spot_usdc,
            "perps_equity": perps_equity,
            "spot_usdc": spot_usdc,
            "margin_used": float(margin.get("totalMarginUsed", 0)),
            "withdrawable": withdrawable + spot_usdc,
            "positions": perps.get("assetPositions", []),
            "spot_balances": spot.get("balances", []),
        }
    except Exception:
        return None


def get_hl_fees() -> dict:
    """Fetch total fees paid on Hyperliquid from account history."""
    try:
        history = _hl_post("info", {"type": "userFills", "user": HL_WALLET_ADDRESS})
        if not isinstance(history, list):
            return {"total_fees": 0.0, "currency": "USDC"}
        total_fees = 0.0
        for fill in history:
            total_fees += float(fill.get("fee", 0))
        return {"total_fees": round(total_fees, 4), "currency": "USDC"}
    except Exception:
        return {"total_fees": 0.0, "currency": "USDC"}


def get_hl_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict] | None:
    """
    Fetch OHLCV candle data from Hyperliquid candleSnapshot API with automatic pagination.

    HL caps each response at ~5000 candles. For long periods (e.g. 365d of 1h = 8760 bars)
    this function splits the request into chunks and concatenates the results.

    Returns a list of candle dicts with keys: t (open time ms), o, h, l, c, v.
    Returns None on complete failure; a partial list if some chunks fail.

    Coins not listed on HL perps return HTTP 500. These are recorded in
    _HL_UNSUPPORTED so subsequent scans skip the API call entirely.
    """
    key = (coin, interval)
    if key in _HL_UNSUPPORTED:
        return None

    _MAX_CANDLES = 5000
    interval_ms = _interval_ms(interval)
    all_candles: list[dict] = []
    chunk_start = start_ms

    try:
        while chunk_start < end_ms:
            chunk_end = min(chunk_start + _MAX_CANDLES * interval_ms, end_ms)
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": chunk_start,
                    "endTime": chunk_end,
                },
            }
            candles = _hl_post("info", payload)
            if candles is None:
                break
            if not isinstance(candles, list) or not candles:
                break
            all_candles.extend(candles)
            # Advance past the last returned candle to avoid duplicates
            chunk_start = int(candles[-1]["t"]) + interval_ms

        if not all_candles:
            _HL_UNSUPPORTED.add(key)
            logger.debug(f"HL candleSnapshot returned empty for {coin} {interval} — marking unsupported")
            return None
        return all_candles

    except urllib.error.HTTPError as exc:
        if exc.code == 500:
            # HTTP 500 = coin not listed on HL perps. Mark as unsupported.
            _HL_UNSUPPORTED.add(key)
            logger.debug(f"HL candleSnapshot HTTP 500 for {coin} {interval} — marking unsupported")
        else:
            logger.warning(f"HL candleSnapshot HTTP {exc.code} for {coin} {interval}: {exc}")
        return all_candles if all_candles else None

    except Exception as exc:
        logger.debug(f"HL candleSnapshot error ({coin} {interval}): {exc}")
        return all_candles if all_candles else None
