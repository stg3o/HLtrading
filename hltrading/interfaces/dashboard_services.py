"""Read-only data assembly and HTML helper logic for dashboard rendering."""

from __future__ import annotations

import json

from config import PAPER_CAPITAL
from hltrading.shared.metrics import aggregate_coin_pnl, build_equity_series


def load_dashboard_state() -> dict:
    try:
        from risk_manager import load_state
        return load_state()
    except Exception:
        return {}


def load_dashboard_trades() -> list:
    try:
        from hltrading.execution.trade_log import load_trades
        return load_trades()
    except Exception:
        return []


def get_live_prices(coins: list) -> dict:
    """Try to fetch live HL prices for open positions. Returns {} on failure."""
    try:
        from config import HL_ENABLED
        if not HL_ENABLED:
            return {}
        from hltrading.execution.hyperliquid_client import get_hl_price
        prices = {}
        for coin in coins:
            price = get_hl_price(coin)
            if price:
                prices[coin] = price
        return prices
    except Exception:
        return {}


def get_live_fees() -> dict:
    """Try to fetch live fees from Hyperliquid. Returns {} on failure."""
    try:
        from config import HL_ENABLED
        if not HL_ENABLED:
            return {}
        from hltrading.execution.account_service import get_hl_fees
        return get_hl_fees()
    except Exception:
        return {}


def compute_stats(trades: list) -> dict:
    wins = [trade for trade in trades if float(trade.get("pnl", 0)) > 0]
    losses = [trade for trade in trades if float(trade.get("pnl", 0)) <= 0]

    gross_profit = sum(float(trade.get("pnl", 0)) for trade in wins)
    gross_loss = abs(sum(float(trade.get("pnl", 0)) for trade in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0

    outcomes = {"take_profit": 0, "stop_loss": 0, "max_bars": 0, "manual": 0}
    for trade in trades:
        reason = str(trade.get("reason", "")).lower()
        if "take_profit" in reason or "take profit" in reason or reason == "tp":
            outcomes["take_profit"] += 1
        elif "stop_loss" in reason or "stop loss" in reason or reason == "sl":
            outcomes["stop_loss"] += 1
        elif "max_bar" in reason or "timeout" in reason:
            outcomes["max_bars"] += 1
        else:
            outcomes["manual"] += 1

    n = len(trades) or 1
    by_coin = {}
    for trade in trades:
        coin = trade.get("coin", "?")
        pnl = float(trade.get("pnl", 0))
        duration = float(trade.get("duration_min") or 0)
        if coin not in by_coin:
            by_coin[coin] = {"trades": 0, "wins": 0, "pnl": 0.0,
                             "gross_p": 0.0, "gross_l": 0.0, "durations": []}
        by_coin[coin]["trades"] += 1
        by_coin[coin]["pnl"] += pnl
        if pnl > 0:
            by_coin[coin]["wins"] += 1
            by_coin[coin]["gross_p"] += pnl
        else:
            by_coin[coin]["gross_l"] += abs(pnl)
        if duration > 0:
            by_coin[coin]["durations"].append(duration)

    edges = [0, 5, 15, 30, 60, 120, 240, 480]
    labels = ["<5m", "5-15m", "15-30m", "30-60m", "1-2h", "2-4h", "4-8h", "8h+"]
    counts = [0] * len(labels)
    for trade in trades:
        duration = float(trade.get("duration_min") or 0)
        placed = False
        for i in range(len(edges) - 1):
            if edges[i] <= duration < edges[i + 1]:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1

    return {
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "outcomes": outcomes,
        "tp_pct": outcomes["take_profit"] / n * 100,
        "sl_pct": outcomes["stop_loss"] / n * 100,
        "mb_pct": outcomes["max_bars"] / n * 100,
        "mc_pct": outcomes["manual"] / n * 100,
        "by_coin": by_coin,
        "dur_labels": labels,
        "dur_counts": counts,
    }


def coin_breakdown_html(by_coin: dict) -> str:
    if not by_coin:
        return '<p class="empty">No closed trades yet.</p>'
    rows = []
    for coin, data in sorted(by_coin.items()):
        n = data["trades"]
        win_rate = data["wins"] / n * 100 if n else 0
        profit_factor = data["gross_p"] / data["gross_l"] if data["gross_l"] > 0 else (999 if data["gross_p"] > 0 else 0)
        pnl = data["pnl"]
        avg_duration = sum(data["durations"]) / len(data["durations"]) if data["durations"] else 0
        wr_cls = "green" if win_rate >= 50 else "red"
        pf_cls = "green" if profit_factor >= 1.0 else "red"
        pnl_cls = "green" if pnl >= 0 else "red"
        pf_disp = "∞" if profit_factor >= 999 else f"{profit_factor:.2f}"
        rows.append(
            f"<tr><td><b>{coin}</b></td><td>{n}</td>"
            f'<td class="{wr_cls}">{win_rate:.1f}%</td>'
            f'<td class="{pf_cls}">{pf_disp}</td>'
            f'<td class="{pnl_cls}">${pnl:+,.2f}</td>'
            f"<td>${data['gross_p']:,.2f}</td>"
            f"<td>${data['gross_l']:,.2f}</td>"
            f"<td>{avg_duration:.0f} min</td></tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Coin</th><th>Trades</th><th>Win Rate</th><th>Prof. Factor</th>"
        "<th>Net P&amp;L</th><th>Gross Win</th><th>Gross Loss</th><th>Avg Duration</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def positions_html(positions: dict, live_prices: dict) -> str:
    if not positions:
        return '<p class="empty">No open positions.</p>'
    rows = []
    for coin, pos in positions.items():
        entry = float(pos.get("entry_price", 0))
        sl = float(pos.get("stop_loss", 0))
        tp = float(pos.get("take_profit", 0))
        size_units = float(pos.get("size_units", 0))
        side = pos.get("side", "?")
        opened = str(pos.get("opened_at", ""))[:16]
        entry_usd = entry * size_units
        live_price = live_prices.get(coin)
        if live_price:
            unreal = ((live_price - entry) if side == "long" else (entry - live_price)) * size_units
            unreal_str = f'<span class="{"green" if unreal >= 0 else "red"}">${unreal:+,.2f}</span>'
            live_price_str = f"${live_price:,.4f}"
        else:
            unreal_str = '<span style="color:var(--muted)">—</span>'
            live_price_str = "—"
        rows.append(
            f"<tr><td><b>{coin}</b></td>"
            f'<td><span class="badge b{side[0]}">{side.upper()}</span></td>'
            f"<td>${entry:,.4f}</td>"
            f"<td>${entry_usd:,.2f}</td>"
            f"<td>{live_price_str}</td>"
            f"<td>{unreal_str}</td>"
            f"<td>${sl:,.4f}</td>"
            f"<td>${tp:,.4f}</td>"
            f"<td>{opened}</td></tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Coin</th><th>Side</th><th>Entry</th><th>Value ($)</th>"
        "<th>Live Price</th><th>Unreal. P&amp;L</th>"
        "<th>SL</th><th>TP</th><th>Opened</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def trades_html(trades: list) -> str:
    if not trades:
        return '<p class="empty">No closed trades yet.</p>'

    def _pill(reason: str) -> str:
        reason = reason.lower()
        if "take_profit" in reason or "take profit" in reason or reason == "tp":
            return '<span class="pill pill-tp">TP</span>'
        if "stop_loss" in reason or "stop loss" in reason or reason == "sl":
            return '<span class="pill pill-sl">SL</span>'
        if "max_bar" in reason or "timeout" in reason:
            return '<span class="pill pill-mb">Timeout</span>'
        return '<span class="pill pill-mc">Manual</span>'

    rows = "".join(
        f"<tr>"
        f"<td>{str(trade.get('timestamp',''))[:16]}</td>"
        f"<td><b>{trade.get('coin','?')}</b></td>"
        f'<td><span class="badge b{str(trade.get("side","?"))[0]}">{str(trade.get("side","?")).upper()}</span></td>'
        f"<td>${float(trade.get('entry_price',0)):,.4f}</td>"
        f"<td>${float(trade.get('exit_price',0)):,.4f}</td>"
        f'<td class="{"green" if float(trade.get("pnl",0))>=0 else "red"}">${float(trade.get("pnl",0)):+,.2f}</td>'
        f"<td>{float(trade.get('pnl_pct',0)):+.2f}%</td>"
        f"<td>{trade.get('duration_min','?')} min</td>"
        f"<td>{_pill(str(trade.get('reason','')))}</td>"
        f"</tr>"
        for trade in reversed(trades[-100:])
    )
    return (
        "<table><thead><tr>"
        "<th>Time</th><th>Coin</th><th>Side</th><th>Entry</th><th>Exit</th>"
        "<th>P&amp;L</th><th>%</th><th>Duration</th><th>Outcome</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table>"
    )


def equity_series_json(trades: list) -> str:
    return json.dumps(build_equity_series(trades, starting_capital=PAPER_CAPITAL, timestamp_chars=10))


def coin_series_json(trades: list) -> str:
    return json.dumps(aggregate_coin_pnl(trades))


def max_drawdown(trades: list) -> float:
    capital, peak, max_dd = PAPER_CAPITAL, PAPER_CAPITAL, 0.0
    for trade in trades:
        capital += float(trade.get("pnl", 0))
        peak = max(peak, capital)
        max_dd = max(max_dd, (peak - capital) / peak * 100 if peak else 0)
    return max_dd


__all__ = [
    "coin_breakdown_html",
    "coin_series_json",
    "compute_stats",
    "equity_series_json",
    "get_live_fees",
    "get_live_prices",
    "load_dashboard_state",
    "load_dashboard_trades",
    "max_drawdown",
    "positions_html",
    "trades_html",
]
