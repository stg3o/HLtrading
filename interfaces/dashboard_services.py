"""Compatibility facade for dashboard service helpers."""

from hltrading.interfaces.dashboard_services import (
    coin_breakdown_html,
    coin_series_json,
    compute_stats,
    equity_series_json,
    get_live_fees,
    get_live_prices,
    load_dashboard_state,
    load_dashboard_trades,
    max_drawdown,
    positions_html,
    trades_html,
)

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
