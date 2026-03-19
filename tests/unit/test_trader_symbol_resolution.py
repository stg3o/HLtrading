#!/usr/bin/env python3
"""Focused tests for Hyperliquid symbol resolution."""
import unittest

from trader import _dedupe_active_assets, _resolve_hl_symbol


class TestTraderSymbolResolution(unittest.TestCase):
    def test_prefers_exact_match(self):
        valid = {"ETH", "BTC-PERP"}
        resolved = _resolve_hl_symbol("ETH", {"hl_symbol": "ETH"}, valid)
        self.assertEqual(resolved, "ETH")

    def test_maps_to_perp_variant(self):
        valid = {"SOL-PERP", "ETH"}
        resolved = _resolve_hl_symbol("SOL", {"hl_symbol": "SOL"}, valid)
        self.assertEqual(resolved, "SOL-PERP")

    def test_maps_from_configured_perp_to_base_when_needed(self):
        valid = {"LINK"}
        resolved = _resolve_hl_symbol("LINK", {"hl_symbol": "LINK-PERP"}, valid)
        self.assertEqual(resolved, "LINK")

    def test_returns_none_when_no_match(self):
        valid = {"BTC", "ETH"}
        resolved = _resolve_hl_symbol("XRP", {"hl_symbol": "XRP"}, valid)
        self.assertIsNone(resolved)

    def test_dedupes_shared_asset_ids_to_primary_coin(self):
        deduped, merged = _dedupe_active_assets([
            ("AVAX_ST", "AVAX", 7),
            ("AVAX", "AVAX", 7),
            ("ETH", "ETH", 1),
        ])
        self.assertEqual(deduped, [("AVAX", "AVAX", 7), ("ETH", "ETH", 1)])
        self.assertEqual(merged, [("AVAX_ST", "AVAX", 7, "AVAX")])


if __name__ == "__main__":
    unittest.main()
