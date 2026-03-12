"""Shared backtest metrics helpers."""
from __future__ import annotations

import math


def build_exit_breakdown(trades: list) -> dict:
    exit_counts = {}
    for trade in trades:
        reason = trade.get("reason", "unknown")
        exit_counts[reason] = exit_counts.get(reason, 0) + 1
    return exit_counts


def max_consecutive_losses(pnls: list[float]) -> int:
    max_cl = cur = 0
    for pnl in pnls:
        cur = cur + 1 if pnl <= 0 else 0
        max_cl = max(max_cl, cur)
    return max_cl


def max_drawdown(equity_curve: list, starting_capital: float) -> float:
    peak = equity_curve[0] if equity_curve else float(starting_capital)
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        dd = (peak - value) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
    return max_dd


def risk_adjusted_metrics(pnl_pcts: list[float], total_trades: int, date_range_days: int) -> tuple[float, float | str]:
    trades_per_year = max(1, int(total_trades / max(date_range_days, 1) * 365))
    rf = 0.0434 / trades_per_year
    excess = [ret - rf for ret in pnl_pcts]
    n = len(excess)
    mean_e = sum(excess) / n
    var = sum((x - mean_e) ** 2 for x in excess) / max(n - 1, 1)
    std_e = math.sqrt(var) if var > 0 else 0.0
    sharpe = math.sqrt(trades_per_year) * (mean_e / std_e) if std_e > 1e-8 else 0.0

    neg = [x for x in excess if x < 0]
    if neg:
        ds = math.sqrt(sum(x ** 2 for x in neg) / len(neg))
        sortino = math.sqrt(trades_per_year) * (mean_e / ds) if ds > 1e-8 else (
            float("inf") if mean_e > 0 else 0.0
        )
    else:
        sortino = float("inf") if mean_e > 0 else 0.0

    return sharpe, round(sortino, 3) if sortino != float("inf") else "∞"


def compute_core_backtest_stats(
    *,
    coin: str,
    trades: list,
    final_capital: float,
    equity_curve: list,
    period: str,
    date_range_days: int,
    starting_capital: float,
) -> dict:
    if not trades:
        return {
            "coin": coin,
            "total_trades": 0,
            "period": period,
            "error": "no trades — setup too conservative or not enough data",
        }

    pnls = [trade["pnl"] for trade in trades]
    pnl_pcts = [trade["pnl_pct"] / 100 for trade in trades]

    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    total = len(pnls)

    win_rate = len(wins) / total * 100 if total else 0
    total_pnl = sum(pnls)
    pct_return = total_pnl / starting_capital * 100
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    sharpe, sortino = risk_adjusted_metrics(pnl_pcts, total, date_range_days)

    return {
        "coin": coin,
        "period": period,
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "pct_return": round(pct_return, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_consec_losses": max_consecutive_losses(pnls),
        "max_drawdown": round(max_drawdown(equity_curve, starting_capital), 1),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": sortino,
        "final_capital": round(final_capital, 2),
        "exit_breakdown": build_exit_breakdown(trades),
        "trades": trades,
    }


__all__ = [
    "build_exit_breakdown",
    "max_consecutive_losses",
    "max_drawdown",
    "risk_adjusted_metrics",
    "compute_core_backtest_stats",
]
