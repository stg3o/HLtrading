#!/usr/bin/env python3
"""
Focused route/render contract tests for web_server.
"""
import importlib
import unittest
from unittest.mock import patch


class TestWebServerRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_server = importlib.import_module("web_server")
        cls.client = cls.web_server.app.test_client()

    def test_index_route_serves_dashboard_html(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        body = response.get_data(as_text=True)
        self.assertIn("HLTrading Dashboard", body)
        self.assertIn("Equity Curve", body)
        self.assertIn("/api/status", body)

    def test_performance_route_preserves_payload_shape(self):
        with patch.object(self.web_server, "_perf_stats", return_value={"win_rate": 50.0}), \
             patch.object(self.web_server, "_equity_series", return_value={"labels": ["t1"], "values": [101.0]}), \
             patch.object(self.web_server, "_coin_pnl_series", return_value={"labels": ["ETH"], "values": [1.5]}):
            response = self.client.get("/api/performance")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "stats": {"win_rate": 50.0},
            "equity": {"labels": ["t1"], "values": [101.0]},
            "coins": {"labels": ["ETH"], "values": [1.5]},
        })

    def test_status_route_preserves_payload_shape(self):
        self.web_server._risk = object()
        self.web_server._bot_running = object()

        expected = {
            "bot_running": True,
            "paused": False,
            "capital": 123.45,
            "hl_perps_equity": 100.0,
            "hl_spot_usdc": 23.45,
            "positions": {"ETH": {"side": "long"}},
            "mode": "paper",
            "network": "testnet",
            "last_updated": "12:34:56",
        }

        with patch.object(self.web_server, "_hl_account_cached", return_value={"account_value": 123.45}), \
             patch.object(self.web_server, "is_paused", return_value=False), \
             patch.object(self.web_server, "build_status_payload", return_value=expected):
            response = self.client.get("/api/status")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, expected)
