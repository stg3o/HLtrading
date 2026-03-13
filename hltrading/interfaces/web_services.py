"""Read-only data services for the Flask web interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import time

from hltrading.shared.metrics import aggregate_coin_pnl, build_equity_series


@dataclass
class HLAccountCache:
    """Small TTL cache for read-only Hyperliquid account data."""

    ttl: float = 30.0
    data: dict = field(default_factory=dict)
    ts: float = 0.0

    def get(self) -> dict:
        if time.time() - self.ts < self.ttl and self.data:
            return self.data
        try:
            from hltrading.execution.account_service import get_hl_account_info

            fresh = get_hl_account_info()
            if fresh:
                self.data = fresh
                self.ts = time.time()
            return self.data
        except Exception:
            return self.data


def hl_account_cached(cache: HLAccountCache) -> dict:
    """Compatibility helper for callers that want a function wrapper."""
    return cache.get()


def get_live_price(coin: str):
    try:
        from config import HL_ENABLED

        if HL_ENABLED:
            from hltrading.execution.hyperliquid_client import get_hl_price

            price = get_hl_price(coin)
            if price:
                return price
            return None
    except Exception:
        pass
    try:
        from strategy import get_indicators_for_coin
        from config import COINS

        if coin in COINS:
            indicators = get_indicators_for_coin(coin, COINS[coin])
            return indicators["price"] if indicators else None
    except Exception:
        return None


def _build_hl_positions_data(hl_account: dict, *, live_price_fn=get_live_price) -> dict:
    from config import COINS

    result = {}
    for position_wrapper in hl_account.get("positions", []):
        pos = position_wrapper.get("position", {})
        coin = pos.get("coin")
        if not coin:
            continue
        size = float(pos.get("szi", 0) or 0)
        if size == 0:
            continue
        entry = float(pos.get("entryPx", 0) or 0)
        live_price = live_price_fn(coin)
        unrealized = pos.get("unrealizedPnl")
        unreal = float(unrealized) if unrealized is not None else (
            ((live_price - entry) if size > 0 else (entry - live_price)) * abs(size)
            if live_price and entry else None
        )
        result[coin] = {
            "side": "long" if size > 0 else "short",
            "entry_price": entry,
            "size_units": abs(size),
            "size_usd": round(entry * abs(size), 2),
            "live_price": live_price,
            "live_pnl": round(unreal, 4) if unreal is not None else None,
            "stop_loss": None,
            "take_profit": None,
            "opened_at": "",
            "strategy": COINS.get(coin, {}).get("strategy_type", ""),
        }
    return result


def build_positions_data(risk, *, live_price_fn=get_live_price, hl_account: dict | None = None) -> dict:
    if not risk:
        risk_positions = {}
    else:
        risk_positions = risk.state.get("positions", {})
    try:
        from config import HL_ENABLED
        if HL_ENABLED and hl_account and hl_account.get("positions"):
            return _build_hl_positions_data(hl_account, live_price_fn=live_price_fn)
    except Exception:
        pass
    from config import COINS

    result = {}
    for coin, pos in risk_positions.items():
        entry = float(pos.get("entry_price", 0))
        size_units = float(pos.get("size_units", 0))
        side = pos.get("side", "?")
        live_price = live_price_fn(coin)
        unreal = (((live_price - entry) if side == "long" else (entry - live_price)) * size_units
                  if live_price and entry and size_units else None)
        result[coin] = {
            "side": side,
            "entry_price": entry,
            "size_units": size_units,
            "size_usd": round(float(pos.get("size_usd", entry * size_units)), 2),
            "live_price": live_price,
            "live_pnl": round(unreal, 4) if unreal is not None else None,
            "stop_loss": float(pos.get("stop_loss", 0)),
            "take_profit": float(pos.get("take_profit", 0)),
            "opened_at": str(pos.get("opened_at", ""))[:16],
            "strategy": COINS.get(coin, {}).get("strategy_type", ""),
        }
    return result


def build_positions_payload(risk, *, live_price_fn=get_live_price, hl_account: dict | None = None) -> dict:
    """Compatibility alias for positions payload assembly."""
    return build_positions_data(risk, live_price_fn=live_price_fn, hl_account=hl_account)


def build_perf_stats() -> dict:
    try:
        from hltrading.execution.trade_log import performance_report, load_trades

        stats = performance_report() or {}
        trades = load_trades()
        today = str(date.today())
        stats["today_pnl"] = round(sum(float(t["pnl"]) for t in trades
                                       if t.get("timestamp", "").startswith(today)), 4)
        stats["today_trades"] = sum(1 for t in trades
                                    if t.get("timestamp", "").startswith(today))
        return stats
    except Exception:
        return {}


def build_performance_stats() -> dict:
    """Compatibility alias for performance stats assembly."""
    return build_perf_stats()


def build_equity_payload() -> dict:
    try:
        from hltrading.execution.trade_log import load_trades
        from config import PAPER_CAPITAL

        return build_equity_series(
            load_trades(),
            starting_capital=PAPER_CAPITAL,
            timestamp_chars=16,
        )
    except Exception:
        return {"labels": [], "values": []}


def build_coin_pnl_payload() -> dict:
    try:
        from hltrading.execution.trade_log import load_trades

        return aggregate_coin_pnl(load_trades())
    except Exception:
        return {"labels": [], "values": []}


def build_recent_trades_payload(n: int = 50) -> list:
    try:
        from hltrading.execution.trade_log import load_trades

        return list(reversed(load_trades()[-n:]))
    except Exception:
        return []


def build_status_payload(*, risk, bot_running, paused: bool, hl_account: dict, last_updated: str) -> dict:
    from config import PAPER_CAPITAL, TESTNET, HL_ENABLED

    hl_balance = hl_account.get("account_value")
    hl_perps = hl_account.get("perps_equity")
    hl_spot = hl_account.get("spot_usdc")
    hl_withdrawable = hl_account.get("withdrawable")

    capital = float(hl_balance) if hl_balance is not None else (
        float(risk.state["capital"]) if risk else PAPER_CAPITAL
    )
    pnl = capital - PAPER_CAPITAL

    return {
        "bot_running": bool(bot_running and bot_running.is_set()),
        "paused": paused,
        "halted": bool(risk and risk.state.get("trading_halted")),
        "emergency": bool(risk and risk.state.get("emergency_stop")),
        "hl_balance": round(hl_balance, 2) if hl_balance is not None else None,
        "hl_perps_equity": round(hl_perps, 2) if hl_perps is not None else None,
        "hl_spot_usdc": round(hl_spot, 2) if hl_spot is not None else None,
        "hl_withdrawable": round(hl_withdrawable, 2) if hl_withdrawable is not None else None,
        "capital": round(capital, 2),
        "total_pnl": round(pnl, 2),
        "total_pnl_pct": round(pnl / PAPER_CAPITAL * 100, 2) if PAPER_CAPITAL else 0,
        "mode": "live" if HL_ENABLED else "paper",
        "network": "testnet" if TESTNET else "mainnet",
        "positions": build_positions_data(risk, hl_account=hl_account),
        "last_updated": last_updated,
    }


def build_performance_payload(*, stats: dict, equity: dict, coins: dict) -> dict:
    return {
        "stats": stats,
        "equity": equity,
        "coins": coins,
    }


def build_coins_payload(risk, hl_account: dict | None = None) -> dict:
    from config import COINS

    positions = risk.state.get("positions", {}) if risk else {}
    hl_symbols_with_positions = set()
    if hl_account:
        for position_wrapper in hl_account.get("positions", []):
            pos = position_wrapper.get("position", {})
            coin = pos.get("coin")
            size = float(pos.get("szi", 0) or 0)
            if coin and size != 0:
                hl_symbols_with_positions.add(coin)
    result = {}
    for key, cfg in COINS.items():
        hl_sym = cfg.get("hl_symbol", key)
        has_pos = (
            hl_sym in hl_symbols_with_positions
            if hl_symbols_with_positions
            else any(COINS.get(c, {}).get("hl_symbol", c) == hl_sym for c in positions)
        )
        result[key] = {
            "enabled": cfg.get("enabled", True),
            "strategy": cfg.get("strategy_type", "mean_reversion"),
            "interval": cfg.get("interval", "5m"),
            "hl_symbol": hl_sym,
            "has_position": has_pos,
        }
    return result


__all__ = [
    "HLAccountCache",
    "build_coin_pnl_payload",
    "build_coins_payload",
    "build_equity_payload",
    "build_perf_stats",
    "build_performance_payload",
    "build_performance_stats",
    "build_positions_data",
    "build_positions_payload",
    "build_recent_trades_payload",
    "build_status_payload",
    "get_live_price",
    "hl_account_cached",
]
