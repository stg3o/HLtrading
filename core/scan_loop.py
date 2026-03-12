"""Core bot scan-loop orchestration."""
from __future__ import annotations

from datetime import datetime


def run_bot_scan_loop(
    *,
    apply_best_configs,
    active_coins,
    bot_running,
    risk_manager,
    tg_controller,
    web_is_paused,
    ai_enabled,
    load_trades,
    get_indicators_for_coin,
    print_indicators,
    get_trend_bias,
    get_decision,
    rule_based_signal,
    print_decision,
    min_edge,
    entry_quality_gate,
    min_entry_quality,
    stop_loss_pct,
    hl_enabled,
    get_hl_obi,
    obi_gate,
    vol_min_ratio,
    close_trade,
    execute_trade,
    add_log,
    print_scan_summary,
    sleep,
    bot_interval_sec,
    print_fn=print,
    fore=None,
    style=None,
):
    """Run the bot scan loop with caller-supplied dependencies."""
    apply_best_configs()
    active = active_coins()
    coin_list = ", ".join(active) or "none"
    print_fn(
        fore.GREEN + f"\n  Bot started — active coins: {coin_list}  "
        f"(scanning every {bot_interval_sec//60}m)"
    )
    while bot_running.is_set():
        n_active = len(active)
        print_fn(f"\n  {fore.CYAN}{'─'*48}")
        print_fn(f"  [{datetime.now().strftime('%H:%M:%S')}] Scanning {n_active} coins…{style.RESET_ALL}")

        halted, reason = risk_manager.is_halted()
        if halted:
            print_fn(fore.RED + f"  Trading halted: {reason}")
            bot_running.wait(bot_interval_sec)
            continue

        if tg_controller and tg_controller.is_paused():
            print_fn(fore.YELLOW + "  ⏸ Trading paused via Telegram — skipping new entries.")
            bot_running.wait(bot_interval_sec)
            continue

        if web_is_paused():
            print_fn(fore.YELLOW + "  ⏸ Trading paused via web dashboard — skipping new entries.")
            bot_running.wait(bot_interval_sec)
            continue

        scan_results = []

        for coin, cfg in active.items():
            if not bot_running.is_set():
                break

            indicators = get_indicators_for_coin(coin, cfg)
            if not indicators:
                continue

            print_indicators(indicators)
            daily_bias = get_trend_bias(coin, cfg) if ai_enabled else None

            if ai_enabled:
                recent = load_trades()[-20:]
                decision = get_decision(indicators, recent, daily_bias=daily_bias)
            else:
                decision = rule_based_signal(indicators)
            print_decision(decision, daily_bias=daily_bias)

            action = decision.get("action", "hold")
            confidence = float(decision.get("confidence", 0.5))
            strategy_type = cfg.get("strategy_type", "mean_reversion")

            if ai_enabled and action in ("long", "short"):
                recent_trades = load_trades()
                if len(recent_trades) >= 10:
                    wins_hist = sum(1 for t in recent_trades if float(t["pnl"]) > 0)
                    base_wr = wins_hist / len(recent_trades)
                else:
                    base_wr = 0.50
                edge = confidence - base_wr
                if edge < min_edge:
                    print_fn(
                        fore.YELLOW + f"  ⊘ Edge gate  conf={confidence:.2f} − base_wr={base_wr:.2f}"
                        f" = {edge:+.2f} < {min_edge:.2f}"
                    )
                    action = "hold"

            if entry_quality_gate and action in ("long", "short") and strategy_type == "mean_reversion":
                price_now = indicators.get("price", 0)
                kc_upper = indicators.get("kc_upper", 0)
                kc_lower = indicators.get("kc_lower", 0)
                atr_val = indicators.get("atr", 0)
                if atr_val and atr_val > 0 and price_now > 0:
                    if action == "short" and kc_upper:
                        z_score = (price_now - kc_upper) / atr_val
                    elif action == "long" and kc_lower:
                        z_score = (kc_lower - price_now) / atr_val
                    else:
                        z_score = min_entry_quality
                    if z_score < min_entry_quality:
                        print_fn(
                            fore.YELLOW + f"  ⊘ Entry quality gate  z={z_score:.3f} ATR"
                            f" outside band (need ≥{min_entry_quality:.2f})"
                        )
                        action = "hold"

            if action in ("long", "short"):
                if strategy_type == "mean_reversion":
                    price_now = indicators.get("price", 0)
                    kc_mid = indicators.get("kc_mid", 0)
                    sl_pct = cfg.get("stop_loss_pct", stop_loss_pct)
                    sl_dist = price_now * sl_pct
                    tp_dist = abs(kc_mid - price_now) if kc_mid else 0
                    if kc_mid and tp_dist < 1.2 * sl_dist:
                        print_fn(
                            fore.YELLOW + f"  ⊘ R:R gate  midline={tp_dist/price_now*100:.2f}%"
                            f" away, need ≥{1.2*sl_pct*100:.2f}%"
                        )
                        action = "hold"
                else:
                    open_pos = risk_manager.state.get("positions", {}).get(coin)
                    open_side = open_pos.get("side") if open_pos else None
                    if open_side and open_side != action:
                        print_fn(fore.YELLOW + f"  ↺ ST flip — closing {open_side} → opening {action}")
                        close_trade(coin, risk_manager, reason="st_flip")

            if action in ("long", "short") and hl_enabled:
                hl_sym = cfg.get("hl_symbol", coin)
                obi = get_hl_obi(hl_sym)
                if obi is not None:
                    obi_blocks = (
                        (action == "short" and obi > obi_gate) or
                        (action == "long" and obi < -obi_gate)
                    )
                    obi_color = fore.RED if obi_blocks else fore.GREEN
                    if obi_blocks:
                        print_fn(
                            fore.YELLOW + f"  ⊘ OBI gate  book={obi_color}{obi:+.3f}{style.RESET_ALL}"
                            f"  opposes {action} (gate=±{obi_gate})"
                        )
                        action = "hold"

            if action in ("long", "short") and strategy_type == "mean_reversion":
                vol_ratio = indicators.get("vol_ratio", 1.0)
                if vol_ratio < vol_min_ratio:
                    print_fn(
                        fore.YELLOW + f"  ⊘ Volume gate  bar={vol_ratio:.2f}× avg"
                        f" (need ≥{vol_min_ratio}×)"
                    )
                    action = "hold"

            if action in ("long", "short"):
                allowed, reason = risk_manager.can_open_position(coin, side=action)
                if allowed:
                    execute_trade(
                        coin,
                        action,
                        cfg["hl_size"],
                        risk_manager,
                        vol_regime=indicators.get("vol_regime", "normal"),
                        kc_mid=indicators.get("kc_mid", 0.0),
                        ai_confidence=confidence,
                    )
                else:
                    print_fn(fore.YELLOW + f"  ⊘ Skipping {coin}: {reason}")

            scan_results.append((coin, indicators, action))
            add_log(coin, action, decision.get("reason", ""))
            sleep(2)

        print_scan_summary(scan_results)

        for _ in range(bot_interval_sec):
            if not bot_running.is_set():
                break
            sleep(1)

    print_fn(fore.YELLOW + "\n  Bot stopped.")
