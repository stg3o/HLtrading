"""Core bot scan-loop orchestration."""
from __future__ import annotations

from datetime import datetime


def run_bot_scan_loop(
    *,
    apply_best_configs,
    active_coins,
    bot_running,
    stop_event,
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
    min_confidence,
    entry_quality_gate,
    min_entry_quality,
    stop_loss_pct,
    hl_enabled,
    get_hl_obi,
    get_hl_funding_rate,
    get_hl_open_interest,
    sync_local_positions_with_hl=None,
    attach_derivatives_context,
    get_btc_market_filter,
    prefetch_scan_market_data,
    select_strategy_candidates,
    allocate_best_strategy_per_symbol,
    use_funding_rate_signal,
    use_open_interest_signal,
    require_oi_confirmation_for_trend,
    suppress_trend_on_oi_divergence,
    use_btc_market_filter,
    btc_filter_suppress_altcoins,
    btc_alt_signal_confidence_penalty,
    use_cascade_filter,
    cascade_trend_confidence_bonus,
    cascade_mr_entry_quality_bonus,
    cascade_risk_confidence_penalty,
    cascade_risk_block_extreme,
    funding_conflict_penalty,
    funding_contrarian_bonus,
    obi_gate,
    vol_min_ratio,
    low_volume_extreme_rsi_long,
    low_volume_extreme_rsi_short,
    low_volume_extreme_confidence_penalty,
    low_volume_extreme_size_scalar,
    close_trade,
    execute_trade,
    add_log,
    print_scan_summary,
    sleep,
    bot_interval_sec,
    debug_scan_logs=False,
    print_fn=print,
    fore=None,
    style=None,
):
    """Run the bot scan loop with caller-supplied dependencies."""
    def _compact_reason(reason: str) -> str:
        text = (reason or "").strip()
        lower = text.lower()
        if "already have position" in lower or "already have an open position" in lower or "position already open" in lower:
            return "position open"
        if "cannot get price" in lower or "missing hl bid/ask" in lower:
            return "no price"
        if "signal price diverges" in lower or "price mismatch" in lower:
            if "price mismatch" in lower:
                return text
            return "price mismatch"
        if "volume gate" in lower or "low-volume" in lower:
            return "low volume"
        if "obi gate" in lower or "opposes" in lower:
            return "OBI conflict"
        if "confidence" in lower and "below minimum" in lower:
            return "low confidence"
        if "oi confirms downside participation" in lower or "oi confirms upside participation" in lower:
            return "OI conflict"
        if "funding crowds" in lower:
            return "funding crowding"
        if "order failed" in lower:
            return "order failed"
        if "cooldown active" in lower:
            return "cooldown"
        return text[:48] if len(text) > 48 else text

    def _emit_coin_line(coin: str, action: str, confidence: float | None, result: str) -> None:
        coin_col = f"{coin:<6}"
        side = action.upper() if action in ("long", "short") else "HOLD"
        side_col = f"{side:<5}"
        if side == "HOLD":
            print_fn(f"  {coin_col} {side_col}")
            return
        print_fn(f"  {coin_col} {side_col} conf={confidence:.2f} -> {result}")

    apply_best_configs()
    active = active_coins()
    while bot_running.is_set() and not stop_event.is_set():
        scan_started_at = datetime.now()
        active = active_coins()
        n_active = len(active)
        print_fn(f"\n  {fore.CYAN}{'─'*48}")
        print_fn(f"  [{scan_started_at.strftime('%H:%M:%S')}] Scan{style.RESET_ALL}")

        halted, reason = risk_manager.is_halted()
        if halted:
            print_fn(fore.RED + f"  Trading halted: {reason}")
            bot_running.wait(bot_interval_sec)
            continue

        if hl_enabled and sync_local_positions_with_hl:
            sync_local_positions_with_hl(
                risk_manager,
                print_fn=print_fn,
                fore=fore,
            )

        if tg_controller and tg_controller.is_paused():
            print_fn(fore.YELLOW + "  ⏸ Trading paused via Telegram — skipping new entries.")
            bot_running.wait(bot_interval_sec)
            continue

        if web_is_paused():
            print_fn(fore.YELLOW + "  ⏸ Trading paused via web dashboard — skipping new entries.")
            bot_running.wait(bot_interval_sec)
            continue

        scan_results = []
        raw_candidates = []
        market_ctx_cache = {}
        candle_cache = prefetch_scan_market_data(
            active,
            ai_enabled=ai_enabled,
            include_btc_filter=use_btc_market_filter,
        )
        btc_market_filter = (
            get_btc_market_filter(market_data_cache=candle_cache)
            if use_btc_market_filter else {"risk_off": False}
        )
        scanned_count = 0
        succeeded_count = 0
        skipped_count = 0
        errored_count = 0

        for coin, cfg in active.items():
            if not bot_running.is_set() or stop_event.is_set():
                break

            scanned_count += 1
            if debug_scan_logs:
                print_fn(f"  [scan] {coin}: fetching indicators")
            try:
                indicators = get_indicators_for_coin(coin, cfg, market_data_cache=candle_cache)
            except Exception as exc:
                errored_count += 1
                print_fn(fore.RED + f"  [scan] {coin} skipped: indicator error: {exc}")
                continue
            if not indicators:
                skipped_count += 1
                print_fn(fore.YELLOW + f"  [scan] {coin} skipped: no indicators returned")
                continue
            succeeded_count += 1
            if debug_scan_logs:
                print_fn(fore.GREEN + f"  [scan] {coin}: indicators ready")

            hl_sym = cfg.get("hl_symbol", coin)
            if hl_sym not in market_ctx_cache:
                market_ctx_cache[hl_sym] = {
                    "funding_rate": get_hl_funding_rate(hl_sym) if use_funding_rate_signal else None,
                    "open_interest": get_hl_open_interest(hl_sym) if use_open_interest_signal else None,
                }
            market_ctx = market_ctx_cache[hl_sym]
            indicators = attach_derivatives_context(
                coin,
                indicators,
                funding_rate=market_ctx.get("funding_rate"),
                open_interest=market_ctx.get("open_interest"),
            )
            raw_candidates.append((coin, cfg, indicators))

        selected_candidates = (
            select_strategy_candidates(raw_candidates)
            if allocate_best_strategy_per_symbol else raw_candidates
        )
        chosen_candidates = list(selected_candidates)
        if allocate_best_strategy_per_symbol:
            if not chosen_candidates:
                if debug_scan_logs:
                    print_fn(fore.YELLOW + "  [scan] allocator selected no strategies — falling back to assigned strategies")
                chosen_candidates = list(raw_candidates)
            else:
                chosen_coins = {coin for coin, _, _ in chosen_candidates}
                fallback_candidates = [item for item in raw_candidates if item[0] not in chosen_coins]
                if debug_scan_logs:
                    for coin, _, _ in fallback_candidates:
                        print_fn(fore.YELLOW + f"  [scan] {coin} allocator fallback: running assigned strategy")
                chosen_candidates.extend(fallback_candidates)

        for coin, cfg, indicators in chosen_candidates:
            if not bot_running.is_set() or stop_event.is_set():
                break

            if debug_scan_logs:
                print_indicators(indicators)
            daily_bias = get_trend_bias(coin, cfg, market_data_cache=candle_cache) if ai_enabled else None
            execution_status = "none"

            if ai_enabled:
                recent = load_trades()[-20:]
                decision = get_decision(indicators, recent, daily_bias=daily_bias)
            else:
                decision = rule_based_signal(indicators)

            action = decision.get("action", "hold")
            confidence = float(decision.get("confidence", 0.5))
            skip_reason = ""
            strategy_type = cfg.get("strategy_type", "mean_reversion")
            if strategy_type == "supertrend":
                st_signal = indicators.get("st_signal", "hold")
                st_flipped = indicators.get("st_flipped", False)
                if st_flipped and st_signal in ("long", "short"):
                    action = st_signal
                    confidence = max(confidence, 0.60 if indicators.get("vol_regime") == "high" else 0.75)
                    decision["reason"] = f"Confirmed Supertrend flip to {st_signal}"
                elif action == "hold":
                    st_direction = int(indicators.get("st_direction", 0) or 0)
                    if st_direction == 1:
                        action = "long"
                        confidence = max(confidence, 0.55)
                        decision["reason"] = "Supertrend continuation long"
                    elif st_direction == -1:
                        action = "short"
                        confidence = max(confidence, 0.55)
                        decision["reason"] = "Supertrend continuation short"
            elif action == "hold":
                price_now = float(indicators.get("price", 0) or 0)
                kc_upper = float(indicators.get("kc_upper", 0) or 0)
                kc_lower = float(indicators.get("kc_lower", 0) or 0)
                rsi = float(indicators.get("rsi", 50) or 50)
                if price_now and kc_lower and rsi <= 30 and price_now < kc_lower:
                    action = "long"
                    confidence = max(confidence, 0.65)
                    decision["reason"] = "Extreme oversold KC stretch long"
                elif price_now and kc_upper and rsi >= 70 and price_now > kc_upper:
                    action = "short"
                    confidence = max(confidence, 0.65)
                    decision["reason"] = "Extreme overbought KC stretch short"
                elif price_now and kc_lower and rsi <= 40 and price_now < kc_lower:
                    action = "long"
                    confidence = max(confidence, 0.50)
                    decision["reason"] = "Light KC stretch long"
                elif price_now and kc_upper and rsi >= 60 and price_now > kc_upper:
                    action = "short"
                    confidence = max(confidence, 0.50)
                    decision["reason"] = "Light KC stretch short"

            display_action = action

            base_confidence = confidence
            total_penalty = 0.0

            def _confidence_floor() -> float:
                floor = max(0.0, base_confidence - 0.15)
                if base_confidence >= 0.25:
                    floor = max(floor, 0.12)
                return floor

            def _apply_penalty_scale(factor: float, reason: str | None = None) -> None:
                nonlocal confidence, total_penalty
                old_conf = confidence
                confidence = max(_confidence_floor(), min(0.99, confidence * factor))
                total_penalty += confidence - old_conf
                if reason:
                    decision["reason"] = reason

            def _apply_bonus(amount: float, reason: str | None = None) -> None:
                nonlocal confidence
                confidence = min(0.99, confidence + amount)
                if reason:
                    decision["reason"] = reason

            if not indicators.get("strategy_regime_match", False):
                decision = {
                    **decision,
                    "reason": (
                        f"{decision.get('reason', '')} [regime {indicators.get('regime')} mismatch: -0.10 conf]"
                    ).strip(),
                }
                _apply_penalty_scale(0.80)

            funding_bias = indicators.get("funding_bias", "neutral")
            funding_extreme = indicators.get("funding_extreme", False)
            funding_hard_block = indicators.get("funding_hard_block", False)
            oi_signal = indicators.get("oi_signal", "neutral")
            regime = indicators.get("regime", "range")
            extreme_volatility = indicators.get("extreme_volatility", False)
            is_trend_strategy = strategy_type == "supertrend" or regime == "trend"
            hl_sym = cfg.get("hl_symbol", coin)
            is_altcoin = hl_sym != "BTC"
            cascade_event = indicators.get("cascade_event", False)
            cascade_direction = indicators.get("cascade_direction", "neutral")
            cascade_exhaustion = indicators.get("cascade_exhaustion", False)
            extreme_cascade = indicators.get("extreme_cascade", False)
            if action in ("long", "short") and funding_extreme:
                if funding_bias == action:
                    _apply_penalty_scale(max(0.0, 1.0 - (funding_conflict_penalty * 2.0)))
                elif funding_bias != "neutral":
                    _apply_bonus(funding_contrarian_bonus)
            if action == "long" and oi_signal == "trend_down_confirmed":
                action = "hold"
                decision["reason"] = "OI confirms downside participation - blocking long"
            elif action == "short" and oi_signal == "trend_up_confirmed":
                action = "hold"
                decision["reason"] = "OI confirms upside participation - blocking short"
            elif action in ("long", "short") and oi_signal in ("trend_up_confirmed", "trend_down_confirmed"):
                # OI aligns with direction — small bonus
                _apply_bonus(funding_contrarian_bonus)

            if action in ("long", "short") and funding_hard_block and funding_bias == action:
                action = "hold"
                decision["reason"] = (
                    f"Extreme funding crowds {action} side "
                    f"({indicators.get('funding_rate', 0.0):+.5f})"
                )

            if action in ("long", "short") and is_trend_strategy and require_oi_confirmation_for_trend:
                # Soft: missing OI confirmation → confidence penalty, not a veto
                if action == "long" and oi_signal != "trend_up_confirmed":
                    _apply_penalty_scale(0.70, "Trend long without rising-OI confirmation [scaled conf]")
                elif action == "short" and oi_signal != "trend_down_confirmed":
                    _apply_penalty_scale(0.70, "Trend short without rising-OI confirmation [scaled conf]")

            if action in ("long", "short") and is_trend_strategy and suppress_trend_on_oi_divergence:
                # Soft: OI divergence → confidence penalty, not a veto
                if action == "long" and oi_signal == "short_covering":
                    _apply_penalty_scale(0.70, "Price up on falling OI - likely short covering [scaled conf]")
                elif action == "short" and oi_signal == "long_liquidation":
                    _apply_penalty_scale(0.70, "Price down on falling OI - likely liquidation [scaled conf]")

            if action in ("long", "short") and regime == "volatility_expansion" and extreme_volatility:
                _apply_penalty_scale(0.50)
                decision["reason"] = (
                    f"Extreme volatility spike (atr={indicators.get('atr_pct', 0.0):.2%}, "
                    f"bw={indicators.get('band_width_pct', 0.0):.2%}) [scaled conf]"
                )

            if action in ("long", "short") and is_altcoin and btc_market_filter.get("risk_off", False):
                _apply_penalty_scale(max(0.0, 1.0 - (btc_alt_signal_confidence_penalty * 2.0)))
                decision["reason"] = (
                    f"BTC market filter risk-off "
                    f"(ADX={btc_market_filter.get('adx', 0.0):.1f}, "
                    f"ATR={btc_market_filter.get('atr_pct', 0.0):.2%}) "
                    f"[scaled conf]"
                )

            cascade_aligns = False   # must be initialised before the conditional below
            if action in ("long", "short") and use_cascade_filter:
                cascade_aligns = (
                    (action == "long" and cascade_direction == "up") or
                    (action == "short" and cascade_direction == "down")
                )
                if strategy_type == "supertrend" and cascade_event and cascade_aligns:
                    _apply_bonus(cascade_trend_confidence_bonus)
                if strategy_type == "mean_reversion" and cascade_exhaustion:
                    indicators["entry_quality"] = float(indicators.get("entry_quality", 0.0)) + cascade_mr_entry_quality_bonus
                    indicators["cascade_snapback_quality"] = True
                if extreme_cascade and not cascade_exhaustion:
                    _apply_penalty_scale(max(0.0, 1.0 - (cascade_risk_confidence_penalty * 2.0)))
                    decision["reason"] = (
                        f"Extreme cascade instability "
                        f"(vol={indicators.get('cascade_volume_spike', 0.0):.2f}x, "
                        f"range={indicators.get('cascade_range_atr', 0.0):.2f} ATR) "
                        f"[scaled conf]"
                    )

            decision["action"] = action
            decision["confidence"] = confidence
            if debug_scan_logs:
                print_decision(decision, daily_bias=daily_bias)

            if ai_enabled and action in ("long", "short"):
                recent_trades = load_trades()
                if len(recent_trades) >= 10:
                    wins_hist = sum(1 for t in recent_trades if float(t["pnl"]) > 0)
                    base_wr = wins_hist / len(recent_trades)
                else:
                    base_wr = 0.50
                edge = confidence - base_wr
                if edge < min_edge:
                    gap = max(min_edge - edge, 0.10)
                    _apply_penalty_scale(max(0.0, 1.0 - (gap * 2.0)))

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
                        _apply_penalty_scale(0.70)

            if action in ("long", "short"):
                if strategy_type == "mean_reversion":
                    price_now = indicators.get("price", 0)
                    kc_mid = indicators.get("kc_mid", 0)
                    sl_pct = cfg.get("stop_loss_pct", stop_loss_pct)
                    sl_dist = price_now * sl_pct
                    tp_dist = abs(kc_mid - price_now) if kc_mid else 0
                    if kc_mid and tp_dist < 1.2 * sl_dist:
                        _apply_penalty_scale(0.70)
                else:
                    open_pos = risk_manager.state.get("positions", {}).get(coin)
                    open_side = open_pos.get("side") if open_pos else None
                    if open_side and open_side != action:
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
                        skip_reason = "OBI conflict"
                        action = "hold"

            if action in ("long", "short") and strategy_type == "mean_reversion":
                vol_ratio = indicators.get("vol_ratio", 1.0)
                entry_size = cfg["hl_size"]
                if vol_ratio < vol_min_ratio:
                    rsi = float(indicators.get("rsi", 50.0) or 50.0)
                    extreme_low_volume_ok = (
                        (action == "long" and rsi <= low_volume_extreme_rsi_long) or
                        (action == "short" and rsi >= low_volume_extreme_rsi_short)
                    )
                    if extreme_low_volume_ok:
                        _apply_penalty_scale(max(0.0, 1.0 - (low_volume_extreme_confidence_penalty * 2.0)))
                        entry_size = cfg["hl_size"] * low_volume_extreme_size_scalar
                    else:
                        skip_reason = "low volume"
                        action = "hold"
                decision["confidence"] = confidence
            else:
                entry_size = cfg["hl_size"]

            if action in ("long", "short") and confidence < min_confidence:
                skip_reason = "low confidence"
                action = "hold"
                decision["reason"] = f"Confidence {confidence:.2f} below minimum {min_confidence:.2f}"

            if action in ("long", "short"):
                # ── Cross-strategy arbitration ───────────────────────────────
                # If a different coin key holds the same hl_symbol (e.g. SOL
                # KC is open and SOL_ST now has a flip signal), close the
                # conflicting position so the allocator-preferred strategy can
                # enter.  Same-coin ST direction flips are handled separately
                # above via the existing st_flip close logic.
                hl_sym_target = cfg.get("hl_symbol", coin)
                for _existing_coin, _existing_pos in list(
                    risk_manager.state.get("positions", {}).items()
                ):
                    if _existing_coin == coin:
                        continue
                    # Resolve hl_symbol for the existing position's coin using
                    # the active dict (already computed at top of while loop).
                    _existing_hl = active.get(_existing_coin, {}).get(
                        "hl_symbol", _existing_coin
                    )
                    if _existing_hl == hl_sym_target:
                        close_trade(_existing_coin, risk_manager, reason="strategy_arbitration")
                        break

                entry_tags = {
                    "cascade_assisted": bool(
                        (strategy_type == "supertrend" and cascade_event and cascade_aligns)
                        or (strategy_type == "mean_reversion" and indicators.get("cascade_snapback_quality", False))
                    ),
                    "entry_context": (
                        "cascade_trend"
                        if strategy_type == "supertrend" and cascade_event and cascade_aligns else
                        "cascade_snapback"
                        if strategy_type == "mean_reversion" and indicators.get("cascade_snapback_quality", False) else
                        "normal"
                    ),
                }
                allowed, reason = risk_manager.can_open_position(coin, side=action)
                if allowed:
                    exec_result = execute_trade(
                        coin,
                        action,
                        entry_size,
                        risk_manager,
                        vol_regime=indicators.get("vol_regime", "normal"),
                        kc_mid=indicators.get("kc_mid", 0.0),
                        signal_price=indicators.get("price"),
                        ai_confidence=confidence,
                        entry_tags=entry_tags,
                        quiet=True,
                        return_result=True,
                    )
                    if exec_result.get("success"):
                        execution_status = "filled"
                        _emit_coin_line(
                            coin,
                            display_action,
                            confidence,
                            f"FILLED @ {exec_result.get('fill_price', indicators.get('price', 0)):.4f}",
                        )
                    else:
                        execution_status = "skipped"
                        _emit_coin_line(coin, display_action, confidence, f"skip ({_compact_reason(exec_result.get('reason', ''))})")
                else:
                    execution_status = "skipped"
                    _emit_coin_line(coin, display_action, confidence, f"skip ({_compact_reason(reason)})")
            else:
                if skip_reason:
                    execution_status = "skipped"
                    _emit_coin_line(coin, display_action, confidence, f"skip ({_compact_reason(skip_reason or decision.get('reason', ''))})")
                else:
                    _emit_coin_line(coin, "hold", None, "HOLD")

            scan_results.append((coin, indicators, action, execution_status))
            add_log(coin, action, decision.get("reason", ""))
            sleep(2)

        print_scan_summary(scan_results, scan_started_at=scan_started_at)
        if debug_scan_logs:
            print_fn(
                f"  [scan] Summary: scanned={scanned_count}  "
                f"succeeded={succeeded_count}  skipped={skipped_count}  errored={errored_count}"
            )

        for _ in range(bot_interval_sec):
            if not bot_running.is_set() or stop_event.is_set():
                break
            sleep(1)

    print_fn(fore.YELLOW + "\n  Bot stopped.")
