#!/usr/bin/env python3
"""Focused regression tests for read-only Hyperliquid client helpers."""
import unittest
from unittest.mock import patch

from execution import hyperliquid_client


class TestHyperliquidClient(unittest.TestCase):
    def test_get_hl_price_reads_mid_price(self):
        with patch.object(hyperliquid_client, "_hl_post", return_value={"BTC": "123.45"}):
            self.assertEqual(hyperliquid_client.get_hl_price("BTC"), 123.45)

    def test_get_hl_obi_computes_bid_ask_imbalance(self):
        book = {
            "levels": [
                [{"sz": "3"}, {"sz": "1"}],
                [{"sz": "1"}, {"sz": "1"}],
            ]
        }
        with patch.object(hyperliquid_client, "_hl_post", return_value=book):
            self.assertAlmostEqual(hyperliquid_client.get_hl_obi("ETH"), 0.3333333333333333)

    def test_get_hl_positions_returns_asset_positions(self):
        with patch.object(hyperliquid_client, "_hl_post", return_value={"assetPositions": [{"coin": "SOL"}]}):
            self.assertEqual(hyperliquid_client.get_hl_positions(), [{"coin": "SOL"}])

    def test_get_hl_funding_rate_reads_asset_context(self):
        payload = [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
            [{"funding": "0.0006", "openInterest": "1000"}, {"funding": "0.0001", "openInterest": "500"}],
        ]
        with patch.object(hyperliquid_client, "_hl_post", return_value=payload):
            self.assertEqual(hyperliquid_client.get_hl_funding_rate("BTC"), 0.0006)

    def test_get_hl_open_interest_reads_asset_context(self):
        payload = [
            {"universe": [{"name": "BTC"}]},
            [{"funding": "0.0006", "openInterest": "12345"}],
        ]
        with patch.object(hyperliquid_client, "_hl_post", return_value=payload):
            self.assertEqual(hyperliquid_client.get_hl_open_interest("BTC"), 12345.0)

    def test_get_hl_account_info_combines_perps_and_spot(self):
        responses = [
            {
                "crossMarginSummary": {"accountValue": "100", "totalMarginUsed": "25"},
                "withdrawable": "40",
                "assetPositions": [{"coin": "BTC"}],
            },
            {
                "balances": [
                    {"coin": "USDC", "total": "50"},
                    {"coin": "ETH", "total": "2"},
                ]
            },
        ]
        with patch.object(hyperliquid_client, "_hl_post", side_effect=responses):
            result = hyperliquid_client.get_hl_account_info()

        self.assertEqual(
            result,
            {
                "account_value": 150.0,
                "perps_equity": 100.0,
                "spot_usdc": 50.0,
                "margin_used": 25.0,
                "withdrawable": 90.0,
                "positions": [{"coin": "BTC"}],
                "spot_balances": [
                    {"coin": "USDC", "total": "50"},
                    {"coin": "ETH", "total": "2"},
                ],
            },
        )

    def test_get_hl_fees_sums_fill_fees(self):
        fills = [{"fee": "1.25"}, {"fee": "0.75"}, {"fee": "0"}]
        with patch.object(hyperliquid_client, "_hl_post", return_value=fills):
            self.assertEqual(
                hyperliquid_client.get_hl_fees(),
                {"total_fees": 2.0, "currency": "USDC"},
            )


class TestGetHlCandles(unittest.TestCase):
    """Tests for the new get_hl_candles pagination helper."""

    def _make_candle(self, t_ms: int) -> dict:
        return {"t": t_ms, "o": "100", "h": "101", "l": "99", "c": "100.5", "v": "5000"}

    def test_single_chunk_returned_as_is(self):
        """When all candles fit in one request, a single API call is made."""
        candles = [self._make_candle(1_000_000 + i * 300_000) for i in range(3)]
        with patch.object(hyperliquid_client, "_hl_post", return_value=candles) as mock_post:
            from hltrading.execution.hyperliquid_client import get_hl_candles
            result = get_hl_candles("ETH", "5m", 1_000_000, 2_000_000)
        self.assertEqual(len(result), 3)
        mock_post.assert_called_once()

    def test_pagination_makes_multiple_calls_for_large_range(self):
        """Requests spanning >5000 candles trigger multiple API calls."""
        # 1h interval = 3_600_000 ms; 5001 bars span > 5000 × 3_600_000 ms
        interval_ms = 3_600_000
        start_ms = 0
        end_ms = 6000 * interval_ms   # 6000 bars worth
        # First call returns 5000 candles, second returns remainder
        chunk1 = [self._make_candle(i * interval_ms) for i in range(5000)]
        chunk2 = [self._make_candle((5000 + i) * interval_ms) for i in range(1000)]
        call_count = {"n": 0}
        def side_effect(endpoint, payload):
            call_count["n"] += 1
            return chunk1 if call_count["n"] == 1 else chunk2
        with patch.object(hyperliquid_client, "_hl_post", side_effect=side_effect):
            from hltrading.execution.hyperliquid_client import get_hl_candles
            result = get_hl_candles("ETH", "1h", start_ms, end_ms)
        self.assertEqual(call_count["n"], 2)
        self.assertEqual(len(result), 6000)

    def test_returns_none_on_empty_response(self):
        """Returns None when HL returns no candles."""
        with patch.object(hyperliquid_client, "_hl_post", return_value=[]):
            from hltrading.execution.hyperliquid_client import get_hl_candles
            result = get_hl_candles("ETH", "5m", 0, 1_000_000)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
