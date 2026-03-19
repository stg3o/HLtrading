"""Core SL/TP monitor-loop orchestration."""
from __future__ import annotations

from datetime import datetime


def _interval_to_seconds(interval: str) -> int:
    """Convert an interval string (e.g. '5m', '1h', '4h', '1d') to seconds."""
    _MAP = {"m": 60, "h": 3600, "d": 86400}
    try:
        unit = interval[-1].lower()
        return int(interval[:-1]) * _MAP.get(unit, 60)
    except Exception:
        return 300   # safe default: 5 minutes


def run_monitor_loop(
    *,
    bot_running,
    stop_event,
    risk_manager,
    hl_enabled,
    get_hl_price,
    get_indicator_price,
    close_trade,
    monitor_interval_sec,
    max_hold_minutes,
    sleep,
    coins=None,
    print_fn=print,
    fore=None,
):
    """Run the SL/TP monitor loop with caller-supplied dependencies.

    coins: optional dict of coin configs (from config.COINS).  When provided,
    the monitor enforces the per-coin max_bars_in_trade time-stop so that live
    behaviour matches the backtester.  Without it, only price-based SL/TP fire.
    """
    coins = coins or {}

    while bot_running.is_set() and not stop_event.is_set():
        positions = dict(risk_manager.state.get("positions", {}))
        for coin, pos in positions.items():
            if stop_event.is_set():
                return

            # ── Time-stop: explicit max hold, only for losing positions ─────
            coin_cfg = coins.get(coin, {})
            interval = coin_cfg.get("interval", "5m")
            opened_at_str = pos.get("opened_at")
            coin_max_hold_minutes = max_hold_minutes
            if coin_max_hold_minutes is None:
                max_bars = coin_cfg.get("max_bars_in_trade")
                if max_bars:
                    coin_max_hold_minutes = int((max_bars * _interval_to_seconds(interval)) / 60)

            if coin_max_hold_minutes and opened_at_str:
                try:
                    opened_at = datetime.fromisoformat(opened_at_str)
                    elapsed_minutes = (datetime.now() - opened_at).total_seconds() / 60
                except Exception:
                    elapsed_minutes = None

            # ── Price-based SL/TP ─────────────────────────────────────────────
            price = None
            try:
                price = get_hl_price(coin) if hl_enabled else None
                if not price:
                    price = get_indicator_price(coin)
            except Exception:
                pass

            if not price:
                continue

            if coin_max_hold_minutes and elapsed_minutes is not None and elapsed_minutes >= coin_max_hold_minutes:
                entry_price = float(pos.get("entry_price", 0) or 0)
                size_units = float(pos.get("size_units", 0) or 0)
                side = pos.get("side", "long")
                pnl = ((price - entry_price) if side == "long" else (entry_price - price)) * size_units
                if pnl < 0:
                    print_fn(
                        f"\n  {fore.YELLOW}TIME STOP triggered after {elapsed_minutes:.1f} minutes | pnl={pnl:+.2f}"
                    )
                    close_trade(coin, risk_manager, reason="time_stop")
                    continue

            sl   = pos.get("stop_loss")
            tp   = pos.get("take_profit")
            side = pos.get("side", "long")

            hit = None
            if side == "long":
                if sl and price <= sl:
                    hit = "stop loss"
                elif tp and price >= tp:
                    hit = "take profit"
            else:
                if sl and price >= sl:
                    hit = "stop loss"
                elif tp and price <= tp:
                    hit = "take profit"

            if hit:
                print_fn(
                    f"\n  {fore.YELLOW}[Monitor] {coin} hit {hit}"
                    f" at ${price:,.4f} — closing…"
                )
                close_trade(coin, risk_manager, reason=hit)

        for _ in range(monitor_interval_sec):
            if not bot_running.is_set() or stop_event.is_set():
                return
            sleep(1)
