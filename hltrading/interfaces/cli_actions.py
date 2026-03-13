"""Read-only CLI action helpers extracted from main.py."""
from __future__ import annotations

from pathlib import Path
import urllib.request


def render_view_positions(*, risk_manager, print_positions, get_hl_account_info, testnet: bool, printer=print, fore=None, style=None) -> None:
    print_positions(risk_manager)
    risk_manager.print_summary()

    printer(f"\n  {fore.CYAN}{'─'*44}")
    net_label = fore.YELLOW + "TESTNET" if testnet else fore.RED + "MAINNET"
    printer(f"  {fore.CYAN}Hyperliquid Wallet [{net_label}{fore.CYAN}]" + style.RESET_ALL)
    acct = get_hl_account_info()
    if acct:
        printer(f"  Total equity   : {fore.GREEN}${acct.get('account_value', 0):,.2f}{style.RESET_ALL}")
        printer(f"    Spot USDC    : ${acct.get('spot_usdc', 0):,.2f}")
        printer(f"    Perps equity : ${acct.get('perps_equity', 0):,.2f}")
        printer(f"  Margin used    : ${acct.get('margin_used', 0):,.2f}")
        printer(f"  Withdrawable   : ${acct.get('withdrawable', 0):,.2f}")
        hl_positions = acct.get("positions", [])
        if hl_positions:
            printer("  Open on-chain  :")
            for position_wrapper in hl_positions:
                pos = position_wrapper.get("position", {})
                coin = pos.get("coin", "?")
                size = pos.get("szi", "0")
                pnl = float(pos.get("unrealizedPnl", 0))
                entry = float(pos.get("entryPx", 0))
                pnl_color = fore.GREEN if pnl >= 0 else fore.RED
                printer(
                    f"    {coin:4}  size={size}  entry=${entry:,.4f}  "
                    f"uPnL={pnl_color}${pnl:+,.2f}{style.RESET_ALL}"
                )
        else:
            printer("  Open on-chain  : none")
    else:
        printer(fore.RED + "  Could not fetch wallet info — check credentials and connection.")


def _url_available(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1.5):
            return True
    except Exception:
        return False


def open_dashboard_action(*, module_file: str, browser_open, printer=print, fore=None) -> None:
    """Open the live web dashboard first, then fall back to static HTML."""
    url = "http://localhost:5000"
    if _url_available(url):
        try:
            browser_open(url)
            printer(fore.GREEN + f"  Live dashboard opened → {url}")
            printer(fore.CYAN + "  (Bot controls, positions, charts, and optimizer all available.)")
            return
        except Exception as exc:
            printer(fore.YELLOW + f"  Could not open live dashboard in browser: {exc}")
    else:
        printer(fore.YELLOW + "  Live web dashboard unavailable — falling back to static dashboard.")

    static_candidates = (
        Path(module_file).parent / "enhanced_dashboard.html",
        Path(module_file).parent / "dashboard.html",
    )
    for dashboard_file in static_candidates:
        if not dashboard_file.exists():
            continue
        try:
            browser_open(f"file://{dashboard_file.resolve()}")
            printer(fore.GREEN + f"  Static dashboard opened → {dashboard_file.name}")
            return
        except Exception as exc:
            printer(fore.YELLOW + f"  Could not open {dashboard_file.name}: {exc}")

    printer(fore.RED + "  No dashboard could be opened.")
    printer(fore.WHITE + f"  Tried live web dashboard: {url}")
    printer(fore.WHITE + "  Tried static files: enhanced_dashboard.html, dashboard.html")


def render_performance_report(*, performance_report_fn, load_trades, printer=print, fore=None, style=None) -> None:
    stats = performance_report_fn()
    printer(f"\n  {fore.CYAN}Performance Report")
    printer(f"  {fore.CYAN}{'─'*44}")

    if not stats:
        printer(fore.YELLOW + "  No closed trades yet.")
        return

    pnl_color = fore.GREEN if stats["total_pnl"] >= 0 else fore.RED
    pf_str = f"{stats['profit_factor']:.2f}" if stats["profit_factor"] != float("inf") else "∞"

    printer(f"  Trades:          {stats['total_trades']}")
    printer(f"  Win rate:        {fore.GREEN if stats['win_rate'] >= 50 else fore.RED}"
            f"{stats['win_rate']:.1f}%{style.RESET_ALL}")
    total_fees = stats.get("total_fees", 0.0)
    printer(f"  Total P&L:       {pnl_color}${stats['total_pnl']:+,.2f}{style.RESET_ALL}"
            f"  {fore.YELLOW}(fees paid: ${total_fees:,.4f}){style.RESET_ALL}")
    printer(f"  Avg win:         {fore.GREEN}${stats['avg_win']:,.2f}{style.RESET_ALL}")
    printer(f"  Avg loss:        {fore.RED}${stats['avg_loss']:,.2f}{style.RESET_ALL}")
    printer(f"  Profit factor:   {pf_str}")
    printer(f"  Max drawdown:    {fore.RED}{stats['max_drawdown']:.1f}%{style.RESET_ALL}")
    printer(f"  Max consec loss: {stats['max_consec_losses']}")
    printer(f"  Best trade:      {fore.GREEN}${stats['best_trade']:+,.2f}{style.RESET_ALL}")
    printer(f"  Worst trade:     {fore.RED}${stats['worst_trade']:+,.2f}{style.RESET_ALL}")

    sharpe = stats.get("sharpe_ratio", 0)
    sortino = stats.get("sortino_ratio", 0)
    s_color = fore.GREEN if sharpe >= 1.0 else fore.YELLOW if sharpe > 0 else fore.RED
    o_color = fore.GREEN if sortino >= 1.5 else fore.YELLOW if sortino > 0 else fore.RED
    sortino_str = f"{sortino:.3f}" if sortino != float("inf") else "∞"
    printer(f"  Sharpe ratio:    {s_color}{sharpe:.3f}{style.RESET_ALL}"
            f"  {'✓ good' if sharpe >= 1.0 else '○ target ≥ 1.0'}")
    printer(f"  Sortino ratio:   {o_color}{sortino_str}{style.RESET_ALL}"
            f"  {'✓ good' if sortino >= 1.5 else '○ target ≥ 1.5'}")

    brier = stats.get("brier_score")
    n_cal = stats.get("calibrated_trades", 0)
    if brier is not None:
        b_color = (
            fore.GREEN if brier < 0.15 else
            fore.YELLOW if brier < 0.20 else fore.RED
        )
        b_grade = (
            "✓ well calibrated" if brier < 0.15 else
            "○ decent" if brier < 0.20 else
            "✗ overconfident / poorly calibrated"
        )
        printer(f"  Brier score:     {b_color}{brier:.4f}{style.RESET_ALL}"
                f"  {b_grade}  (n={n_cal}, 0=perfect, 0.25=random)")
    else:
        printer(f"  Brier score:     {fore.YELLOW}— (need ≥5 trades with confidence logged){style.RESET_ALL}")

    trades = load_trades()[-5:]
    if trades:
        printer(f"\n  {fore.CYAN}Last {len(trades)} trades:")
        for trade in trades:
            pnl = float(trade["pnl"])
            color = fore.GREEN if pnl >= 0 else fore.RED
            printer(f"  {trade['timestamp'][:16]}  {trade['coin']:4} {trade['side'].upper():5} "
                    f"{color}${pnl:+,.2f}{style.RESET_ALL}  ({trade['reason']})")


__all__ = [
    "open_dashboard_action",
    "render_performance_report",
    "render_view_positions",
]
