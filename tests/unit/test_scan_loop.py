#!/usr/bin/env python3
"""Focused regression tests for scan-loop orchestration."""
import types
import unittest
from unittest.mock import Mock

from core.scan_loop import run_bot_scan_loop


class _OneShotEvent:
    def __init__(self):
        self._set = True
        self.wait_calls = []

    def is_set(self):
        return self._set

    def wait(self, timeout):
        self.wait_calls.append(timeout)
        self._set = False


class TestScanLoop(unittest.TestCase):
    def _base_kwargs(self):
        event = _OneShotEvent()
        risk = Mock()
        risk.state = {"positions": {}}
        risk.is_halted.return_value = (False, "")
        risk.can_open_position.return_value = (False, "blocked")
        return {
            "apply_best_configs": Mock(),
            "active_coins": Mock(return_value={}),
            "bot_running": event,
            "risk_manager": risk,
            "tg_controller": None,
            "web_is_paused": Mock(return_value=False),
            "ai_enabled": False,
            "load_trades": Mock(return_value=[]),
            "get_indicators_for_coin": Mock(),
            "print_indicators": Mock(),
            "get_trend_bias": Mock(),
            "get_decision": Mock(),
            "rule_based_signal": Mock(),
            "print_decision": Mock(),
            "min_edge": 0.0,
            "entry_quality_gate": False,
            "min_entry_quality": 0.0,
            "stop_loss_pct": 0.01,
            "hl_enabled": False,
            "get_hl_obi": Mock(),
            "get_hl_funding_rate": Mock(return_value=None),
            "get_hl_open_interest": Mock(return_value=None),
            "attach_derivatives_context": Mock(side_effect=lambda coin, indicators, funding_rate=None, open_interest=None: indicators),
            "get_btc_market_filter": Mock(return_value={"risk_off": False, "adx": 0.0, "atr_pct": 0.0}),
            "select_strategy_candidates": Mock(side_effect=lambda candidates: candidates),
            "allocate_best_strategy_per_symbol": True,
            "use_funding_rate_signal": True,
            "use_open_interest_signal": True,
            "require_oi_confirmation_for_trend": True,
            "suppress_trend_on_oi_divergence": True,
            "use_btc_market_filter": True,
            "btc_filter_suppress_altcoins": True,
            "btc_alt_signal_confidence_penalty": 0.2,
            "use_cascade_filter": True,
            "cascade_trend_confidence_bonus": 0.08,
            "cascade_mr_entry_quality_bonus": 0.2,
            "cascade_risk_confidence_penalty": 0.2,
            "cascade_risk_block_extreme": True,
            "funding_conflict_penalty": 0.15,
            "funding_contrarian_bonus": 0.05,
            "obi_gate": 0.0,
            "vol_min_ratio": 0.0,
            "close_trade": Mock(),
            "execute_trade": Mock(),
            "add_log": Mock(),
            "print_scan_summary": Mock(side_effect=lambda results: event.wait(0)),
            "sleep": Mock(),
            "bot_interval_sec": 1,
            "print_fn": Mock(),
            "fore": types.SimpleNamespace(CYAN="", GREEN="", YELLOW="", RED=""),
            "style": types.SimpleNamespace(RESET_ALL=""),
        }

    def test_halt_gate_short_circuits_pause_checks_and_waits(self):
        kwargs = self._base_kwargs()
        kwargs["risk_manager"].is_halted.return_value = (True, "halted")
        kwargs["tg_controller"] = Mock()

        run_bot_scan_loop(**kwargs)

        kwargs["risk_manager"].is_halted.assert_called_once_with()
        kwargs["tg_controller"].is_paused.assert_not_called()
        kwargs["web_is_paused"].assert_not_called()
        self.assertEqual(kwargs["bot_running"].wait_calls, [1])

    def test_telegram_pause_short_circuits_web_pause_and_coin_scan(self):
        kwargs = self._base_kwargs()
        kwargs["tg_controller"] = Mock()
        kwargs["tg_controller"].is_paused.return_value = True

        run_bot_scan_loop(**kwargs)

        kwargs["tg_controller"].is_paused.assert_called_once_with()
        kwargs["web_is_paused"].assert_not_called()
        kwargs["get_indicators_for_coin"].assert_not_called()
        self.assertEqual(kwargs["bot_running"].wait_calls, [1])

    def test_web_pause_skips_coin_scan_and_waits(self):
        kwargs = self._base_kwargs()
        kwargs["tg_controller"] = Mock()
        kwargs["tg_controller"].is_paused.return_value = False
        kwargs["web_is_paused"].return_value = True

        run_bot_scan_loop(**kwargs)

        kwargs["tg_controller"].is_paused.assert_called_once_with()
        kwargs["web_is_paused"].assert_called_once_with()
        kwargs["get_indicators_for_coin"].assert_not_called()
        self.assertEqual(kwargs["bot_running"].wait_calls, [1])

    def test_strategy_allocator_filters_candidates_before_decisioning(self):
        kwargs = self._base_kwargs()
        kwargs["active_coins"].return_value = {
            "BTC": {"hl_symbol": "BTC", "strategy_type": "supertrend", "hl_size": 1},
            "BTC_RANGE": {"hl_symbol": "BTC", "strategy_type": "mean_reversion", "hl_size": 1},
        }
        kwargs["get_indicators_for_coin"].side_effect = [
            {"coin": "BTC", "price": 100.0, "strategy_regime_match": False, "strategy_type": "supertrend"},
            {"coin": "BTC_RANGE", "price": 100.0, "strategy_regime_match": True, "strategy_type": "mean_reversion"},
        ]
        kwargs["select_strategy_candidates"].side_effect = None
        kwargs["select_strategy_candidates"].return_value = [
            ("BTC_RANGE", kwargs["active_coins"].return_value["BTC_RANGE"], {"coin": "BTC_RANGE", "price": 100.0, "strategy_regime_match": True, "strategy_type": "mean_reversion"})
        ]
        kwargs["rule_based_signal"].return_value = {"action": "hold", "confidence": 0.0, "reason": "x"}

        run_bot_scan_loop(**kwargs)

        kwargs["rule_based_signal"].assert_called_once()

    def test_btc_risk_off_suppresses_altcoin_signal(self):
        kwargs = self._base_kwargs()
        kwargs["active_coins"].return_value = {
            "SOL_ST": {"hl_symbol": "SOL", "strategy_type": "supertrend", "hl_size": 1},
        }
        kwargs["get_indicators_for_coin"].return_value = {
            "coin": "SOL_ST",
            "price": 100.0,
            "strategy_regime_match": True,
            "strategy_type": "supertrend",
            "regime": "trend",
            "oi_signal": "trend_up_confirmed",
            "funding_bias": "neutral",
            "funding_extreme": False,
            "funding_hard_block": False,
            "extreme_volatility": False,
        }
        kwargs["get_btc_market_filter"].return_value = {"risk_off": True, "adx": 35.0, "atr_pct": 0.04}
        kwargs["select_strategy_candidates"].side_effect = None
        kwargs["select_strategy_candidates"].return_value = [
            ("SOL_ST", kwargs["active_coins"].return_value["SOL_ST"], kwargs["get_indicators_for_coin"].return_value)
        ]
        kwargs["rule_based_signal"].return_value = {"action": "long", "confidence": 0.8, "reason": "trend"}

        run_bot_scan_loop(**kwargs)

        kwargs["execute_trade"].assert_not_called()

    def test_extreme_cascade_blocks_unstable_entry(self):
        kwargs = self._base_kwargs()
        kwargs["active_coins"].return_value = {
            "BTC": {"hl_symbol": "BTC", "strategy_type": "supertrend", "hl_size": 1},
        }
        kwargs["get_indicators_for_coin"].return_value = {
            "coin": "BTC",
            "price": 100.0,
            "strategy_regime_match": True,
            "strategy_type": "supertrend",
            "regime": "trend",
            "oi_signal": "trend_up_confirmed",
            "funding_bias": "neutral",
            "funding_extreme": False,
            "funding_hard_block": False,
            "extreme_volatility": False,
            "cascade_event": True,
            "cascade_direction": "up",
            "cascade_exhaustion": False,
            "extreme_cascade": True,
            "cascade_volume_spike": 5.0,
            "cascade_range_atr": 3.0,
        }
        kwargs["select_strategy_candidates"].side_effect = None
        kwargs["select_strategy_candidates"].return_value = [
            ("BTC", kwargs["active_coins"].return_value["BTC"], kwargs["get_indicators_for_coin"].return_value)
        ]
        kwargs["rule_based_signal"].return_value = {"action": "long", "confidence": 0.8, "reason": "trend"}

        run_bot_scan_loop(**kwargs)

        kwargs["execute_trade"].assert_not_called()
