"""
trade_log.py — persistent CSV trade history
Records every closed trade with full details for performance analysis.
"""
import csv
import math
from datetime import datetime
from pathlib import Path
from config import BASE_DIR

LOG_FILE = BASE_DIR / "trade_history.csv"

HEADERS = [
    "timestamp", "coin", "side", "entry_price", "exit_price",
    "size_units", "size_usd", "pnl", "pnl_pct", "reason",
    "duration_min", "capital_after", "ai_confidence"
]


def _ensure_file():
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=HEADERS).writeheader()


def log_trade(position: dict, exit_price: float, pnl: float,
              reason: str, capital_after: float) -> None:
    """Append a closed trade to the CSV log."""
    _ensure_file()

    opened_at = position.get("opened_at", "")
    try:
        opened_dt = datetime.fromisoformat(str(opened_at))
        duration  = round((datetime.now() - opened_dt).total_seconds() / 60, 1)
    except Exception:
        duration = 0

    # ai_confidence stored at entry time (for Brier Score calibration tracking)
    conf = position.get("ai_confidence")
    row = {
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "coin":          position.get("coin", "?"),
        "side":          position.get("side", "?"),
        "entry_price":   position.get("entry_price", 0),
        "exit_price":    round(exit_price, 4),
        "size_units":    position.get("size_units", 0),
        "size_usd":      position.get("size_usd", 0),
        "pnl":           round(pnl, 2),
        "pnl_pct":       round(pnl / position.get("size_usd", 1) * 100, 2),
        "reason":        reason,
        "duration_min":  duration,
        "capital_after": round(capital_after, 2),
        "ai_confidence": round(conf, 3) if conf is not None else "",
    }

    with open(LOG_FILE, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=HEADERS).writerow(row)


def load_trades() -> list[dict]:
    """Load all trades from CSV as list of dicts."""
    _ensure_file()
    with open(LOG_FILE, newline="") as f:
        return list(csv.DictReader(f))


def _sharpe_sortino(pnl_pcts: list[float]) -> tuple[float, float]:
    """
    Compute annualised Sharpe and Sortino ratios from per-trade returns.

    Assumes ~2 trades/day on a 4h crypto strategy → 730 trades/year.
    Risk-free rate: 4.34% annual (US T-bill proxy).
    Returns (sharpe, sortino).  Both are 0.0 if fewer than 2 trades.
    """
    n = len(pnl_pcts)
    if n < 2:
        return 0.0, 0.0

    TRADES_PER_YEAR = 730
    rf_per_trade    = 0.0434 / TRADES_PER_YEAR

    excess      = [r - rf_per_trade for r in pnl_pcts]
    mean_e      = sum(excess) / n
    variance    = sum((x - mean_e) ** 2 for x in excess) / (n - 1)
    std_e       = math.sqrt(variance) if variance > 0 else 0.0

    sharpe = math.sqrt(TRADES_PER_YEAR) * (mean_e / std_e) if std_e > 1e-8 else 0.0

    neg = [x for x in excess if x < 0]
    if neg:
        downside_var = sum(x ** 2 for x in neg) / len(neg)
        downside_std = math.sqrt(downside_var)
        sortino = (math.sqrt(TRADES_PER_YEAR) * (mean_e / downside_std)
                   if downside_std > 1e-8
                   else (float("inf") if mean_e > 0 else 0.0))
    else:
        sortino = float("inf") if mean_e > 0 else 0.0

    return round(sharpe, 3), round(sortino, 3)


def performance_report() -> dict:
    """Calculate performance stats from trade history."""
    trades = load_trades()
    if not trades:
        return {}

    pnls        = [float(t["pnl"]) for t in trades]
    wins        = [p for p in pnls if p > 0]
    losses      = [p for p in pnls if p <= 0]
    total       = len(pnls)
    win_rate    = len(wins) / total * 100 if total else 0
    avg_win     = sum(wins) / len(wins) if wins else 0
    avg_loss    = sum(losses) / len(losses) if losses else 0
    total_pnl   = sum(pnls)
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    # Max consecutive losses
    max_consec_loss = cur = 0
    for p in pnls:
        cur = cur + 1 if p <= 0 else 0
        max_consec_loss = max(max_consec_loss, cur)

    # Running capital for drawdown
    capitals = [float(t["capital_after"]) for t in trades if t["capital_after"]]
    if capitals:
        peak   = capitals[0]
        max_dd = 0.0
        for c in capitals:
            peak  = max(peak, c)
            max_dd = max(max_dd, (peak - c) / peak * 100)
    else:
        max_dd = 0.0

    # Sharpe / Sortino from per-trade pnl_pct returns
    pnl_pcts = [float(t["pnl_pct"]) / 100 for t in trades if t.get("pnl_pct")]
    sharpe, sortino = _sharpe_sortino(pnl_pcts)

    # Brier Score — measures AI confidence calibration.
    # BS = mean((confidence − outcome)²)  where outcome = 1 for win, 0 for loss.
    # Lower is better.  0.25 = random 50/50, 0.0 = perfect calibration.
    # Only computed when ≥5 trades have confidence recorded.
    calibrated = [
        (float(t["ai_confidence"]), 1.0 if float(t["pnl"]) > 0 else 0.0)
        for t in trades
        if t.get("ai_confidence") not in ("", None)
    ]
    brier_score: float | None = None
    if len(calibrated) >= 5:
        brier_score = round(
            sum((conf - outcome) ** 2 for conf, outcome in calibrated) / len(calibrated),
            4,
        )

    return {
        "total_trades":      total,
        "win_rate":          round(win_rate, 1),
        "total_pnl":         round(total_pnl, 2),
        "avg_win":           round(avg_win, 2),
        "avg_loss":          round(avg_loss, 2),
        "profit_factor":     round(profit_factor, 2),
        "max_consec_losses": max_consec_loss,
        "max_drawdown":      round(max_dd, 1),
        "best_trade":        round(max(pnls), 2) if pnls else 0,
        "worst_trade":       round(min(pnls), 2) if pnls else 0,
        "sharpe_ratio":      sharpe,
        "sortino_ratio":     sortino,
        "brier_score":       brier_score,    # None until ≥5 calibrated trades
        "calibrated_trades": len(calibrated),
    }
