"""
dashboard.py — HTML dashboard generator

Reads live data from:
  - trade_history.csv  (via trade_log.load_trades)
  - paper_state.json   (via risk_manager.load_state)
  - Hyperliquid API    (live prices for unrealized P&L, if HL_ENABLED)

Generates a self-contained HTML file with Chart.js charts,
then opens it in the default browser via run().
"""
import json
from pathlib import Path
from datetime import datetime

from config import BASE_DIR, PAPER_CAPITAL
from hltrading.interfaces.dashboard_assets import DASHBOARD_HTML_TEMPLATE
from interfaces.dashboard_services import (
    coin_breakdown_html as _coin_breakdown_html_impl,
    coin_series_json as _coin_series_impl,
    compute_stats as _compute_stats_impl,
    equity_series_json as _equity_series_impl,
    get_live_fees as _get_live_fees_impl,
    get_live_prices as _get_live_prices_impl,
    load_dashboard_state as _load_state_impl,
    load_dashboard_trades as _load_trades_impl,
    max_drawdown as _max_drawdown_impl,
    positions_html as _positions_html_impl,
    trades_html as _trades_html_impl,
)


# ─── DATA HELPERS ─────────────────────────────────────────────────────────────

def _load_state() -> dict:
    return _load_state_impl()


def _load_trades() -> list:
    return _load_trades_impl()


def _get_live_prices(coins: list) -> dict:
    return _get_live_prices_impl(coins)


def _get_live_fees() -> dict:
    return _get_live_fees_impl()


# ─── STATS COMPUTATION ────────────────────────────────────────────────────────

def _compute_stats(trades: list) -> dict:
    return _compute_stats_impl(trades)


# ─── HTML BUILDERS ────────────────────────────────────────────────────────────

def _coin_breakdown_html(by_coin: dict) -> str:
    return _coin_breakdown_html_impl(by_coin)


def _positions_html(positions: dict, live_prices: dict) -> str:
    return _positions_html_impl(positions, live_prices)


def _trades_html(trades: list) -> str:
    return _trades_html_impl(trades)


def _equity_series(trades: list) -> str:
    return _equity_series_impl(trades)


def _coin_series(trades: list) -> str:
    return _coin_series_impl(trades)


def _max_drawdown(trades: list) -> float:
    return _max_drawdown_impl(trades)


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

def run():
    state     = _load_state()
    trades    = _load_trades()

    capital   = float(state.get("capital",     PAPER_CAPITAL))
    peak      = float(state.get("equity_peak", PAPER_CAPITAL))
    positions = state.get("positions", {})
    total_tr  = len(trades)
    emergency = bool(state.get("emergency_stop", False))
    halted    = bool(state.get("trading_halted",  False))

    wins_cnt   = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
    total_pnl  = capital - PAPER_CAPITAL
    return_pct = total_pnl / PAPER_CAPITAL * 100
    win_rate   = wins_cnt / total_tr * 100 if total_tr > 0 else 0.0
    max_dd     = _max_drawdown(trades) if trades else ((peak - capital) / peak * 100 if peak > 0 else 0.0)

    stats      = _compute_stats(trades)
    pf         = stats["profit_factor"]
    avg_win    = stats["avg_win"]
    avg_loss   = stats["avg_loss"]

    live_prices = _get_live_prices(list(positions.keys()))
    live_fees   = _get_live_fees()

    # Calculate fees from trade history (paper trading) vs live fees from HL
    total_fees_from_trades = sum(float(t.get("fees", 0)) for t in trades if t.get("fees"))
    if live_fees and live_fees.get("total_fees", 0) > 0:
        # Use live fees from Hyperliquid
        fees_str     = f"${live_fees['total_fees']:,.4f}"
        fees_class   = "yellow"  # Highlight live fees
        fees_source  = f"Live ({live_fees.get('currency', 'USDC')})"
    else:
        # Fall back to fees from trade history
        fees_str     = f"${total_fees_from_trades:,.4f}"
        fees_class   = "yellow" if total_fees_from_trades > 0 else "muted"
        fees_source  = "From trades" if total_fees_from_trades > 0 else "No fees yet"

    if emergency:
        status, status_class = "EMERGENCY STOP", "red"
    elif halted:
        status, status_class = "HALTED", "yellow"
    else:
        status, status_class = "ACTIVE", "green"

    try:
        from config import TESTNET, HL_ENABLED
        mode_label = "Live Trading" if HL_ENABLED else "Paper Trading"
        net_label  = "Testnet" if TESTNET else "Mainnet"
    except Exception:
        mode_label, net_label = "Paper Trading", ""

    pf_str       = ("∞" if pf >= 999 else f"{pf:.2f}") if total_tr > 0 else "—"
    pf_cls       = "green" if pf >= 1.2 else ("yellow" if pf >= 1.0 else "red")
    avg_win_str  = f"${avg_win:,.2f}"  if avg_win  else "—"
    avg_loss_str = f"${avg_loss:,.2f}" if avg_loss else "—"

    shown = min(100, len(trades))
    html  = DASHBOARD_HTML_TEMPLATE.format(
        generated_at        = datetime.now().strftime("%Y-%m-%d %H:%M"),
        mode_label          = mode_label,
        net_label           = net_label,
        capital             = capital,
        pnl_str             = f"${total_pnl:+,.2f}",
        pnl_class           = "green" if total_pnl >= 0 else "red",
        return_pct          = return_pct,
        win_rate            = win_rate,
        wr_class            = "green" if win_rate >= 50 else "red",
        wins                = wins_cnt,
        total_trades        = total_tr,
        pf_str              = pf_str,
        pf_class            = pf_cls,
        avg_win_str         = avg_win_str,
        avg_loss_str        = avg_loss_str,
        max_dd              = max_dd,
        dd_class            = "red" if max_dd > 10 else "yellow" if max_dd > 5 else "green",
        status              = status,
        status_class        = status_class,
        tp_pct              = stats["tp_pct"],
        sl_pct              = stats["sl_pct"],
        mb_pct              = stats["mb_pct"],
        mc_pct              = stats["mc_pct"],
        fees_str            = fees_str,
        fees_class          = fees_class,
        fees_source         = fees_source,
        coin_breakdown_html = _coin_breakdown_html(stats["by_coin"]),
        positions_html      = _positions_html(positions, live_prices),
        trades_html         = _trades_html(trades),
        equity_json         = _equity_series(trades),
        coin_json           = _coin_series(trades),
        outcome_json        = json.dumps({
            "labels": ["Take Profit", "Stop Loss", "Timeout", "Manual"],
            "values": [
                stats["outcomes"]["take_profit"],
                stats["outcomes"]["stop_loss"],
                stats["outcomes"]["max_bars"],
                stats["outcomes"]["manual"],
            ],
        }),
        duration_json       = json.dumps({
            "labels": stats["dur_labels"],
            "values": stats["dur_counts"],
        }),
        shown               = shown,
    )

    out = BASE_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    p = run()
    if p:
        import webbrowser
        webbrowser.open(f"file://{p}")
        print(f"Dashboard written to {p}")
