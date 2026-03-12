"""
hltrading.shared.metrics — reusable reporting helpers for trade-derived metrics.
"""
from __future__ import annotations


def build_equity_series(
    trades: list,
    *,
    starting_capital: float,
    timestamp_chars: int,
) -> dict:
    """Build a cumulative equity curve from closed trades."""
    labels, values, capital = [], [], starting_capital
    for trade in trades:
        capital += float(trade.get("pnl", 0))
        labels.append(str(trade.get("timestamp", ""))[:timestamp_chars])
        values.append(round(capital, 2))
    return {"labels": labels, "values": values}


def aggregate_coin_pnl(trades: list) -> dict:
    """Aggregate closed-trade P&L by coin."""
    by_coin: dict = {}
    for trade in trades:
        coin = trade.get("coin", "?")
        by_coin[coin] = round(by_coin.get(coin, 0.0) + float(trade.get("pnl", 0)), 2)
    return {"labels": list(by_coin), "values": list(by_coin.values())}
