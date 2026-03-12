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


if __name__ == "__main__":
    unittest.main()
