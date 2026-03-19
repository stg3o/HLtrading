"""
trade_log.py — persistent CSV trade history
Records every closed trade with full details for performance analysis.
"""
import csv
import math
import json
from datetime import datetime
from pathlib import Path
from config import BASE_DIR, COINS, LAST_STRATEGY_UPDATE, DISABLED_COINS_FILE

LOG_FILE = BASE_DIR / "trade_history.csv"

HEADERS = [
    "timestamp", "coin", "side", "entry_price", "exit_price",
    "size_units", "size_usd", "gross_pnl", "fees", "pnl", "pnl_pct", "reason",
    "duration_min", "capital_after", "ai_confidence", "cascade_assisted", "entry_context"
]


def _ensure_file():
    """Create the CSV if missing, or migrate it to the current schema if stale."""
    if not LOG_FILE.exists():
        with open(LOG_FILE, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=HEADERS).writeheader()
        return

    # ── Schema migration: add missing columns without losing existing data ──────
    with open(LOG_FILE, newline="") as f:
        reader     = csv.DictReader(f)
        old_fields = reader.fieldnames or []
        rows       = list(reader)

    missing = [h for h in HEADERS if h not in old_fields]
    if not missing:
        return   # already up-to-date

    # Back-fill sensible defaults for each missing column
    for row in rows:
        if "gross_pnl" not in row or row.get("gross_pnl") in ("", None):
            row["gross_pnl"] = row.get("pnl", "0")   # best guess: gross = net
        if "fees" not in row or row.get("fees") in ("", None):
            row["fees"] = "0.0"
        if "cascade_assisted" not in row or row.get("cascade_assisted") in ("", None):
            row["cascade_assisted"] = "False"
        if "entry_context" not in row or row.get("entry_context") in ("", None):
            row["entry_context"] = "normal"

    # Rewrite the file with the full HEADERS
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  [trade_log] Migrated {LOG_FILE.name}: added columns {missing} "
          f"({len(rows)} rows backfilled)")


def log_trade(position: dict, exit_price: float, pnl: float,
              reason: str, capital_after: float,
              gross_pnl: float | None = None, fees: float = 0.0) -> None:
    """Append a closed trade to the CSV log.

    pnl       : net P&L after fees (used for capital tracking).
    gross_pnl : raw price-based P&L before fees (defaults to pnl if not passed).
    fees      : round-trip trading fee deducted from gross_pnl.
    """
    _ensure_file()

    if gross_pnl is None:
        gross_pnl = pnl  # backward-compatible: callers that don't pass gross_pnl

    opened_at = position.get("opened_at", "")
    try:
        opened_dt = datetime.fromisoformat(str(opened_at))
        duration  = round((datetime.now() - opened_dt).total_seconds() / 60, 1)
    except Exception:
        duration = 0

    conf = position.get("ai_confidence")
    row = {
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "coin":          position.get("coin", "?"),
        "side":          position.get("side", "?"),
        "entry_price":   position.get("entry_price", 0),
        "exit_price":    round(exit_price, 4),
        "size_units":    position.get("size_units", 0),
        "size_usd":      position.get("size_usd", 0),
        "gross_pnl":     round(gross_pnl, 2),
        "fees":          round(fees, 4),
        "pnl":           round(pnl, 2),
        "pnl_pct":       round(pnl / position.get("size_usd", 1) * 100, 2),
        "reason":        reason,
        "duration_min":  duration,
        "capital_after": round(capital_after, 2),
        "ai_confidence": round(conf, 3) if conf is not None else "",
        "cascade_assisted": str(bool(position.get("cascade_assisted", False))),
        "entry_context": position.get("entry_context", "normal"),
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


def _profit_factor_from_pnls(pnls: list[float]):
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    if losses and sum(losses) != 0:
        return round(abs(sum(wins) / sum(losses)), 2)
    return "∞" if wins else 0.0


def _group_stats(group_key: str, group_value, trades: list[dict]) -> dict:
    pnls = [float(t.get("pnl", 0) or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    total = len(pnls)
    return {
        group_key: group_value,
        "trade_count": total,
        "win_rate": round((len(wins) / total * 100) if total else 0.0, 1),
        "profit_factor": _profit_factor_from_pnls(pnls),
        "avg_pnl": round((sum(pnls) / total) if total else 0.0, 2),
        "total_pnl": round(sum(pnls), 2),
    }


def _strategy_type_for_trade(trade: dict) -> str:
    coin = trade.get("coin", "")
    cfg = COINS.get(coin)
    if cfg:
        return cfg.get("strategy_type", "unknown")
    if coin.endswith("_ST"):
        return "supertrend"
    if coin.endswith("_RANGE"):
        return "mean_reversion"
    return "unknown"


def analyze_pnl_by_coin(trades: list[dict] | None = None) -> list[dict]:
    if trades is None:
        trades = load_trades()
    grouped: dict[str, list[dict]] = {}
    for trade in trades:
        grouped.setdefault(trade.get("coin", "?"), []).append(trade)
    return [
        _group_stats("coin", coin, bucket)
        for coin, bucket in sorted(grouped.items())
    ]


def analyze_pnl_by_strategy_type(trades: list[dict] | None = None) -> list[dict]:
    if trades is None:
        trades = load_trades()
    grouped: dict[str, list[dict]] = {}
    for trade in trades:
        grouped.setdefault(_strategy_type_for_trade(trade), []).append(trade)
    return [
        _group_stats("strategy_type", strategy_type, bucket)
        for strategy_type, bucket in sorted(grouped.items())
    ]


def analyze_pnl_by_hour(trades: list[dict] | None = None) -> list[dict]:
    if trades is None:
        trades = load_trades()
    grouped: dict[int, list[dict]] = {}
    for trade in trades:
        ts = str(trade.get("timestamp", ""))
        try:
            hour = datetime.fromisoformat(ts.replace(" ", "T")).hour
        except Exception:
            continue
        grouped.setdefault(hour, []).append(trade)
    return [
        _group_stats("hour", hour, bucket)
        for hour, bucket in sorted(grouped.items())
    ]


def analyze_pnl_by_weekday(trades: list[dict] | None = None) -> list[dict]:
    if trades is None:
        trades = load_trades()
    grouped: dict[str, list[dict]] = {}
    for trade in trades:
        ts = str(trade.get("timestamp", ""))
        try:
            weekday = datetime.fromisoformat(ts.replace(" ", "T")).strftime("%A")
        except Exception:
            continue
        grouped.setdefault(weekday, []).append(trade)
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [
        _group_stats("weekday", weekday, grouped[weekday])
        for weekday in order
        if weekday in grouped
    ]


def analyze_pnl_by_entry_context(trades: list[dict] | None = None) -> list[dict]:
    if trades is None:
        trades = load_trades()
    grouped: dict[str, list[dict]] = {}
    for trade in trades:
        context = "cascade" if str(trade.get("cascade_assisted", "False")).lower() == "true" else "normal"
        grouped.setdefault(context, []).append(trade)
    return [
        _group_stats("entry_context", context, bucket)
        for context, bucket in sorted(grouped.items())
    ]


def _trades_since_update(trades: list[dict], since_ts: str | None) -> list[dict]:
    if not since_ts:
        return []
    try:
        cutoff = datetime.fromisoformat(str(since_ts).replace(" ", "T"))
    except Exception:
        return []

    filtered: list[dict] = []
    for trade in trades:
        try:
            trade_ts = datetime.fromisoformat(str(trade.get("timestamp", "")).replace(" ", "T"))
        except Exception:
            continue
        if trade_ts >= cutoff:
            filtered.append(trade)
    return filtered


def _performance_summary(trades: list[dict]) -> dict:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_consec_losses": 0,
            "max_drawdown": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "brier_score": None,
            "calibrated_trades": 0,
            "total_fees": 0.0,
        }

    pnls = [float(t["pnl"]) for t in trades]
    total_fees = sum(float(t["fees"]) for t in trades if t.get("fees") not in ("", None))
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = len(pnls)
    win_rate = len(wins) / total * 100 if total else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    total_pnl = sum(pnls)
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    max_consec_loss = cur = 0
    for pnl in pnls:
        cur = cur + 1 if pnl <= 0 else 0
        max_consec_loss = max(max_consec_loss, cur)

    capitals = [float(t["capital_after"]) for t in trades if t["capital_after"]]
    if capitals:
        peak = capitals[0]
        max_dd = 0.0
        for capital in capitals:
            peak = max(peak, capital)
            max_dd = max(max_dd, (peak - capital) / peak * 100)
    else:
        max_dd = 0.0

    pnl_pcts = [float(t["pnl_pct"]) / 100 for t in trades if t.get("pnl_pct")]
    sharpe, sortino = _sharpe_sortino(pnl_pcts)

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
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_consec_losses": max_consec_loss,
        "max_drawdown": round(max_dd, 1),
        "best_trade": round(max(pnls), 2) if pnls else 0,
        "worst_trade": round(min(pnls), 2) if pnls else 0,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "brier_score": brier_score,
        "calibrated_trades": len(calibrated),
        "total_fees": round(total_fees, 4),
    }


def _append_disabled_coins(coins: list[str]) -> None:
    existing: list[str] = []
    try:
        if DISABLED_COINS_FILE.exists():
            existing = json.loads(DISABLED_COINS_FILE.read_text())
    except Exception:
        existing = []
    merged = sorted(set(existing) | set(coins))
    DISABLED_COINS_FILE.write_text(json.dumps(merged, indent=2))


def auto_disable_failing_components(trades: list[dict] | None = None) -> list[str]:
    if trades is None:
        trades = load_trades()
    recent_trades = _trades_since_update(trades, LAST_STRATEGY_UPDATE)
    if not recent_trades:
        return []

    disabled_messages: list[str] = []
    disabled_coins: set[str] = set()

    for row in analyze_pnl_by_coin(recent_trades):
        coin = str(row.get("coin", ""))
        if int(row.get("trade_count", 0) or 0) >= 5 and float(row.get("win_rate", 0) or 0) == 0.0:
            cfg = COINS.get(coin)
            if cfg and cfg.get("enabled", False):
                cfg["enabled"] = False
                disabled_coins.add(coin)
                disabled_messages.append(
                    f"[AUTO-DISABLE] {coin} disabled — since update: {row['trade_count']} trades, 0.0% WR"
                )

    failing_strategy_types: list[str] = []
    for row in analyze_pnl_by_strategy_type(recent_trades):
        strategy_type = str(row.get("strategy_type", ""))
        if int(row.get("trade_count", 0) or 0) >= 5 and float(row.get("win_rate", 0) or 0) == 0.0:
            failing_strategy_types.append(strategy_type)
            for coin, cfg in COINS.items():
                if cfg.get("enabled", False) and cfg.get("strategy_type") == strategy_type:
                    cfg["enabled"] = False
                    disabled_coins.add(coin)
            disabled_messages.append(
                f"[AUTO-DISABLE] strategy {strategy_type} disabled — since update: {row['trade_count']} trades, 0.0% WR"
            )

    if disabled_coins:
        _append_disabled_coins(sorted(disabled_coins))
    return disabled_messages


def performance_report() -> dict:
    """Calculate performance stats from trade history."""
    trades = load_trades()
    if not trades:
        return {}
    all_time = _performance_summary(trades)
    since_update_trades = _trades_since_update(trades, LAST_STRATEGY_UPDATE)
    since_update = _performance_summary(since_update_trades)
    breakdown = performance_breakdown_by_coin_and_context(trades)
    by_coin = analyze_pnl_by_coin(trades)
    by_strategy_type = analyze_pnl_by_strategy_type(trades)
    by_hour = analyze_pnl_by_hour(trades)
    by_weekday = analyze_pnl_by_weekday(trades)
    by_entry_context = analyze_pnl_by_entry_context(trades)
    since_update_by_coin = analyze_pnl_by_coin(since_update_trades)
    since_update_by_strategy_type = analyze_pnl_by_strategy_type(since_update_trades)
    since_update_by_hour = analyze_pnl_by_hour(since_update_trades)

    return {
        **all_time,
        "all_time": all_time,
        "since_last_update": since_update,
        "last_strategy_update": LAST_STRATEGY_UPDATE,
        "since_last_update_pnl_by_coin": since_update_by_coin,
        "since_last_update_pnl_by_strategy_type": since_update_by_strategy_type,
        "since_last_update_pnl_by_hour": since_update_by_hour,
        "pnl_by_coin": by_coin,
        "pnl_by_strategy_type": by_strategy_type,
        "pnl_by_hour": by_hour,
        "pnl_by_weekday": by_weekday,
        "pnl_by_entry_context": by_entry_context,
        "breakdown_by_coin_and_context": breakdown,
    }


def performance_breakdown_by_coin_and_context(trades: list[dict] | None = None) -> list[dict]:
    """Break down performance by coin and cascade-vs-normal entry context."""
    if trades is None:
        trades = load_trades()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for trade in trades:
        coin = trade.get("coin", "?")
        context = "cascade" if str(trade.get("cascade_assisted", "False")).lower() == "true" else "normal"
        grouped.setdefault((coin, context), []).append(trade)

    rows: list[dict] = []
    for (coin, context), bucket in sorted(grouped.items()):
        pnls = [float(t.get("pnl", 0) or 0) for t in bucket]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total = len(pnls)
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")
        rows.append({
            "coin": coin,
            "entry_context": context,
            "trade_count": total,
            "win_rate": round((len(wins) / total * 100) if total else 0.0, 1),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
            "avg_pnl": round((sum(pnls) / total) if total else 0.0, 2),
        })
    return rows
