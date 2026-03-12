"""Core SL/TP monitor-loop orchestration."""
from __future__ import annotations


def run_monitor_loop(
    *,
    bot_running,
    risk_manager,
    hl_enabled,
    get_hl_price,
    get_indicator_price,
    close_trade,
    monitor_interval_sec,
    sleep,
    print_fn=print,
    fore=None,
):
    """Run the SL/TP monitor loop with caller-supplied dependencies."""
    while bot_running.is_set():
        positions = dict(risk_manager.state.get("positions", {}))
        for coin, pos in positions.items():
            price = None
            try:
                price = get_hl_price(coin) if hl_enabled else None
                if not price:
                    price = get_indicator_price(coin)
            except Exception:
                pass

            if not price:
                continue

            sl = pos.get("stop_loss")
            tp = pos.get("take_profit")
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
                print_fn(f"\n  {fore.YELLOW}[Monitor] {coin} hit {hit} at ${price:,.4f} — closing…")
                close_trade(coin, risk_manager, reason=hit)

        for _ in range(monitor_interval_sec):
            if not bot_running.is_set():
                return
            sleep(1)
