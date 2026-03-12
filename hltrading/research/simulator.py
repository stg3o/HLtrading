"""Shared backtesting simulation helpers."""
from __future__ import annotations


def run_supertrend_simulation(
    df,
    p: dict,
    *,
    paper_capital: float,
    risk_per_trade: float,
    supertrend_arrays,
    include_timestamps: bool = False,
) -> tuple[list, float, list]:
    """Run the shared Supertrend simulation loop."""
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)

    st_period = int(p.get("st_period", 10))
    st_multiplier = float(p.get("st_multiplier", 3.0))
    stop_loss_pct = float(p.get("stop_loss_pct", 0.010))
    max_bars = int(p.get("max_bars_in_trade", 168))

    direction, _ = supertrend_arrays(high, low, close, st_period, st_multiplier)

    warmup = st_period + 5
    capital = float(paper_capital)
    equity_peak = capital
    position = None
    trades = []
    equity_curve = [capital]

    for i in range(warmup, len(df)):
        bar_high = high[i]
        bar_low = low[i]
        bar_close = close[i]

        if position:
            bars_held = i - position["bar_in"]
            hit = None

            if position["side"] == "long" and direction[i] == -1 and direction[i - 1] == 1:
                hit = ("st_flip", bar_close)
            elif position["side"] == "short" and direction[i] == 1 and direction[i - 1] == -1:
                hit = ("st_flip", bar_close)

            if hit is None:
                if position["side"] == "long" and bar_low <= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif position["side"] == "short" and bar_high >= position["sl"]:
                    hit = ("stop_loss", position["sl"])

            if hit is None and bars_held >= max_bars:
                hit = ("time_stop", bar_close)

            if hit:
                reason, exit_price = hit
                if position["side"] == "long":
                    pnl = (exit_price - position["entry"]) * position["size_units"]
                else:
                    pnl = (position["entry"] - exit_price) * position["size_units"]

                capital += pnl
                equity_peak = max(equity_peak, capital)
                trade = {
                    "side": position["side"],
                    "entry": position["entry"],
                    "exit": round(exit_price, 4),
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
                    "reason": reason,
                    "bars": bars_held,
                }
                if include_timestamps:
                    trade["timestamp"] = df.index[i].isoformat()
                trades.append(trade)
                position = None

            equity_curve.append(capital)
            continue

        if direction[i] == direction[i - 1]:
            equity_curve.append(capital)
            continue

        side = "long" if direction[i] == 1 else "short"
        sl = (
            round(bar_close * (1 - stop_loss_pct), 6)
            if side == "long"
            else round(bar_close * (1 + stop_loss_pct), 6)
        )

        risk_usd = capital * risk_per_trade
        size_usd = risk_usd / stop_loss_pct
        size_units = size_usd / bar_close if bar_close > 0 else 0

        position = {
            "side": side,
            "entry": bar_close,
            "size_usd": size_usd,
            "size_units": size_units,
            "sl": sl,
            "bar_in": i,
        }
        if include_timestamps:
            position["timestamp"] = df.index[i].isoformat()
        equity_curve.append(capital)

    if position:
        last_close = close[-1]
        if position["side"] == "long":
            pnl = (last_close - position["entry"]) * position["size_units"]
        else:
            pnl = (position["entry"] - last_close) * position["size_units"]
        capital += pnl
        trade = {
            "side": position["side"],
            "entry": position["entry"],
            "exit": round(last_close, 4),
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
            "reason": "end_of_data",
            "bars": len(df) - 1 - position["bar_in"],
        }
        if include_timestamps:
            trade["timestamp"] = df.index[-1].isoformat()
        trades.append(trade)

    return trades, capital, equity_curve


def run_mean_reversion_simulation(
    df,
    p: dict,
    *,
    paper_capital: float,
    risk_per_trade: float,
    warmup: int,
    calc_kc_mid,
    signal_for_window,
    include_timestamps: bool = False,
) -> tuple[list, float, list]:
    """Run the shared mean-reversion simulation loop."""
    capital = float(paper_capital)
    equity_peak = capital
    position = None
    trades = []
    equity_curve = [capital]

    stop_loss_pct = p["stop_loss_pct"]
    take_profit_pct = p["take_profit_pct"]
    min_rr = p["min_rr_ratio"]
    max_bars_in_trade = p["max_bars_in_trade"]

    for i in range(warmup, len(df)):
        window = df.iloc[:i + 1]
        row = df.iloc[i]
        bar_high = float(row["High"])
        bar_low = float(row["Low"])
        bar_close = float(row["Close"])

        if position:
            bars_held = i - position["bar_in"]
            current_kc_mid = calc_kc_mid(window)
            hit = None

            if position["side"] == "long":
                if bar_low <= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif current_kc_mid > 0 and bar_high >= current_kc_mid:
                    hit = ("tp_midline", min(bar_high, current_kc_mid))
                elif bar_high >= position["tp_fallback"]:
                    hit = ("tp_fixed", position["tp_fallback"])
                elif bars_held >= max_bars_in_trade:
                    hit = ("time_stop", bar_close)
            else:
                if bar_high >= position["sl"]:
                    hit = ("stop_loss", position["sl"])
                elif current_kc_mid > 0 and bar_low <= current_kc_mid:
                    hit = ("tp_midline", max(bar_low, current_kc_mid))
                elif bar_low <= position["tp_fallback"]:
                    hit = ("tp_fixed", position["tp_fallback"])
                elif bars_held >= max_bars_in_trade:
                    hit = ("time_stop", bar_close)

            if hit:
                reason, exit_price = hit
                if position["side"] == "long":
                    pnl = (exit_price - position["entry"]) * position["size_units"]
                else:
                    pnl = (position["entry"] - exit_price) * position["size_units"]

                capital += pnl
                equity_peak = max(equity_peak, capital)
                trade = {
                    "side": position["side"],
                    "entry": position["entry"],
                    "exit": round(exit_price, 4),
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
                    "reason": reason,
                    "bars": bars_held,
                }
                if include_timestamps:
                    trade["timestamp"] = df.index[i].isoformat()
                trades.append(trade)
                position = None

            equity_curve.append(capital)
            continue

        action, reason, kc_mid, _ = signal_for_window(window, p)

        if action in ("long", "short"):
            sl_dist = bar_close * stop_loss_pct

            if action == "long":
                tp_mid_dist = max(kc_mid - bar_close, 0)
                tp_fallback = round(bar_close * (1 + take_profit_pct), 6)
                tp_target = kc_mid if tp_mid_dist >= bar_close * take_profit_pct else tp_fallback
            else:
                tp_mid_dist = max(bar_close - kc_mid, 0)
                tp_fallback = round(bar_close * (1 - take_profit_pct), 6)
                tp_target = kc_mid if tp_mid_dist >= bar_close * take_profit_pct else tp_fallback

            tp_dist = abs(bar_close - tp_target) if tp_target else bar_close * take_profit_pct

            if sl_dist > 0 and (tp_dist / sl_dist) < min_rr:
                equity_curve.append(capital)
                continue

            risk_usd = capital * risk_per_trade
            size_usd = risk_usd / stop_loss_pct
            size_units = size_usd / bar_close if bar_close > 0 else 0

            sl = round(bar_close * (1 - stop_loss_pct), 6) if action == "long" \
                 else round(bar_close * (1 + stop_loss_pct), 6)

            position = {
                "side": action,
                "entry": bar_close,
                "size_usd": size_usd,
                "size_units": size_units,
                "sl": sl,
                "tp_fallback": tp_fallback,
                "bar_in": i,
                "reason": reason,
            }
            if include_timestamps:
                position["timestamp"] = df.index[i].isoformat()

        equity_curve.append(capital)

    if position:
        last_close = float(df.iloc[-1]["Close"])
        if position["side"] == "long":
            pnl = (last_close - position["entry"]) * position["size_units"]
        else:
            pnl = (position["entry"] - last_close) * position["size_units"]
        capital += pnl
        trade = {
            "side": position["side"],
            "entry": position["entry"],
            "exit": round(last_close, 4),
            "pnl": round(pnl, 4),
            "pnl_pct": round(pnl / position["size_usd"] * 100, 3),
            "reason": "end_of_data",
            "bars": len(df) - 1 - position["bar_in"],
        }
        if include_timestamps:
            trade["timestamp"] = df.index[-1].isoformat()
        trades.append(trade)

    return trades, capital, equity_curve


__all__ = [
    "run_supertrend_simulation",
    "run_mean_reversion_simulation",
]
