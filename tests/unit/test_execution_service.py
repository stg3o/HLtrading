#!/usr/bin/env python3
"""Focused regression tests for execution service behavior."""
import types
import unittest
from unittest.mock import Mock

from execution.execution_service import close_trade, execute_trade


class TestExecutionService(unittest.TestCase):
    def test_execute_trade_constructs_hl_order_parameters_before_order_failure(self):
        risk_manager = Mock()
        risk_manager.state = {"capital": 1000.0, "positions": {}}
        risk_manager.can_open_position.return_value = (True, "")
        risk_manager.calculate_position.return_value = {
            "size_units": 1.0,
            "size_usd": 20.0,
            "risk_amount": 5.0,
            "vol_scalar": 1.0,
            "corr_scalar": 1.0,
            "kelly_mult": 1.5,
            "tp_price": None,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        }
        exchange = Mock()
        exchange.update_leverage.return_value = {"status": "ok"}
        exchange.info.l2_snapshot.return_value = {
            "levels": [
                [{"px": "99.9", "sz": "10"}],
                [{"px": "100.1", "sz": "10"}],
            ]
        }
        exchange.info.asset_to_sz_decimals = {1: 3}
        exchange.order.return_value = {"status": "error"}
        exchange.market_open.return_value = {"status": "error"}

        result = execute_trade(
            coin="SOL",
            side="long",
            size=0.1,
            risk_manager=risk_manager,
            vol_regime="normal",
            kc_mid=0.0,
            ai_confidence=0.8,
            entry_tags={"cascade_assisted": True, "entry_context": "cascade_trend"},
            coins={"SOL": {"hl_symbol": "SOL", "asset_id": 1, "hl_size": 0.1, "hl_leverage": 4, "sz_decimals": 3}},
            stop_loss_pct=0.02,
            take_profit_pct=0.05,
            hl_enabled=True,
            testnet=False,
            hl_leverage=3,
            hl_max_position_usd=25.0,
            get_hl_price=Mock(return_value=100.0),
            get_indicator_price=Mock(),
            hl_exchange_factory=Mock(return_value=exchange),
            notify_trade_open=Mock(),
            printer=Mock(),
            fore=types.SimpleNamespace(RED="", YELLOW="", GREEN="", CYAN=""),
            style=types.SimpleNamespace(RESET_ALL=""),
        )

        self.assertFalse(result)
        risk_manager.calculate_position.assert_called_once_with(
            100.0,
            vol_regime="normal",
            coin="SOL",
            sl_pct=0.02,
            tp_pct=0.05,
            tp_price=None,
            ai_confidence=0.8,
        )
        exchange.update_leverage.assert_called_once_with(4, "SOL", is_cross=True)
        self.assertEqual(exchange.market_open.call_count, 2)
        exchange.market_open.assert_any_call("SOL", True, 0.25, px=100.0, slippage=0.002)
        exchange.market_open.assert_any_call("SOL", True, 0.25, px=100.0, slippage=0.004)
        risk_manager.open_position.assert_not_called()

    def test_close_trade_preserves_cancel_price_close_log_notify_order(self):
        call_order = []
        risk_manager = Mock()
        risk_manager.state = {
            "capital": 1200.0,
            "positions": {
                "ETH": {"side": "long", "entry_price": 100.0, "size_units": 1.0}
            },
        }

        def cancel_open_orders_fn(coin):
            call_order.append(("cancel", coin))
            return 1

        def get_hl_price(coin):
            call_order.append(("price", coin))
            return 110.0

        def close_position(coin, price):
            call_order.append(("close_position", coin, price))
            return {
                "entry_price": 100.0,
                "exit_price": 110.0,
                "pnl": 10.0,
                "gross_pnl": 10.5,
                "fees": 0.5,
                "pnl_pct": 10.0,
            }

        risk_manager.close_position.side_effect = close_position

        def log_trade(*args, **kwargs):
            call_order.append(("log_trade", args, kwargs))

        def notify_trade_close(*args):
            call_order.append(("notify", args))

        result = close_trade(
            coin="ETH",
            risk_manager=risk_manager,
            reason="manual",
            coins={"ETH": {"hl_symbol": "ETH"}},
            hl_enabled=True,
            get_hl_price=get_hl_price,
            get_indicator_price=Mock(),
            cancel_open_orders_fn=cancel_open_orders_fn,
            hl_exchange_factory=Mock(return_value=Mock(market_close=Mock(return_value={"status": "ok"}))),
            notify_trade_close=notify_trade_close,
            log_trade=log_trade,
            printer=Mock(),
            fore=types.SimpleNamespace(RED="", YELLOW="", GREEN="", CYAN=""),
            style=types.SimpleNamespace(RESET_ALL=""),
        )

        self.assertTrue(result)
        self.assertEqual(
            [entry[0] for entry in call_order],
            ["cancel", "price", "close_position", "log_trade", "notify"],
        )


if __name__ == "__main__":
    unittest.main()
