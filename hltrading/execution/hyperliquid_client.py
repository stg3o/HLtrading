"""Read-only Hyperliquid REST client helpers."""
import json
import urllib.request

from colorama import Fore

from config import TESTNET, HL_WALLET_ADDRESS


def _hl_post(endpoint: str, payload: dict):
    """Direct HTTP call to Hyperliquid REST API — bypasses broken SDK Info class."""
    from hyperliquid.utils import constants

    base = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL
    url = base.rstrip("/") + "/" + endpoint.lstrip("/")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_hl_price(coin: str) -> float | None:
    """Fetch current mid price via direct API — no SDK Info needed."""
    try:
        mids = _hl_post("info", {"type": "allMids"})
        val = mids.get(coin)
        return float(val) if val else None
    except Exception as exc:
        print(Fore.RED + f"  Price fetch error ({coin}): {exc}")
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
        state = _hl_post("info", {"type": "clearinghouseState", "user": HL_WALLET_ADDRESS})
        return state.get("assetPositions", [])
    except Exception as exc:
        print(Fore.RED + f"  Position fetch error: {exc}")
        return []


def get_hl_account_info() -> dict:
    """Fetch unified account info (perps equity + spot USDC)."""
    try:
        perps = _hl_post("info", {"type": "clearinghouseState", "user": HL_WALLET_ADDRESS})
        margin = perps.get("crossMarginSummary") or perps.get("marginSummary") or {}

        spot = _hl_post("info", {"type": "spotClearinghouseState", "user": HL_WALLET_ADDRESS})
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
    except Exception as exc:
        print(Fore.RED + f"  Account info error: {exc}")
        return {}


def get_hl_fees() -> dict:
    """Fetch total fees paid on Hyperliquid from account history."""
    try:
        history = _hl_post("info", {"type": "userFills", "user": HL_WALLET_ADDRESS})
        total_fees = 0.0
        for fill in history:
            total_fees += float(fill.get("fee", 0))
        return {"total_fees": round(total_fees, 4), "currency": "USDC"}
    except Exception as exc:
        print(Fore.RED + f"  Fee fetch error: {exc}")
        return {"total_fees": 0.0, "currency": "USDC"}
