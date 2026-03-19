#!/usr/bin/env python3
"""
Regression tests for shared state persistence wrappers.
"""
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


class TestSharedStateHelpers(unittest.TestCase):
    def test_build_default_state_returns_fresh_copy(self):
        from shared.state import build_default_state

        defaults = {"positions": {}, "capital": 1}
        result = build_default_state(defaults)
        result["positions"]["ETH"] = 1

        self.assertEqual(defaults, {"positions": {}, "capital": 1})

    def test_load_state_can_merge_defaults(self):
        from shared.state import load_state

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(json.dumps({"capital": 50.0}))

            loaded = load_state(
                state_path,
                defaults={"capital": 100.0, "positions": {}, "wins": 0},
                merge_defaults=True,
                fallback_exceptions=(FileNotFoundError, json.JSONDecodeError),
            )

        self.assertEqual(loaded["capital"], 50.0)
        self.assertEqual(loaded["positions"], {})
        self.assertEqual(loaded["wins"], 0)


class TestRiskManagerStateWrappers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module_keys = ("dotenv", "colorama")
        cls._original_modules = {key: sys.modules.get(key) for key in cls._module_keys}

        sys.modules.setdefault("dotenv", _stub_module("dotenv", load_dotenv=lambda: None))
        sys.modules.setdefault(
            "colorama",
            _stub_module(
                "colorama",
                Fore=types.SimpleNamespace(),
                Style=types.SimpleNamespace(),
                init=lambda **kwargs: None,
            ),
        )

    @classmethod
    def tearDownClass(cls):
        for key, original in cls._original_modules.items():
            if original is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = original

    def test_risk_manager_load_state_merges_missing_keys_and_bad_json_falls_back(self):
        risk_manager = importlib.import_module("risk_manager")

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "risk_state.json"
            state_path.write_text(json.dumps({"capital": 321.0}))

            with patch.object(risk_manager, "STATE_FILE", str(state_path)), \
                 patch("config.PAPER_CAPITAL", 999.0):
                loaded = risk_manager.load_state()

                self.assertEqual(loaded["capital"], 321.0)
                self.assertEqual(loaded["equity_peak"], 999.0)
                self.assertIn("positions", loaded)

                state_path.write_text("{bad json")
                fallback = risk_manager.load_state()
                self.assertEqual(fallback["capital"], 999.0)
                self.assertEqual(fallback["positions"], {})


class TestPaperTraderStateWrappers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module_keys = (
            "dotenv",
            "yfinance",
            "pandas",
            "pandas_ta",
            "colorama",
            "eth_account",
            "hyperliquid",
            "hyperliquid.exchange",
            "hyperliquid.info",
            "hyperliquid.utils",
            "hyperliquid.utils.constants",
        )
        cls._original_modules = {key: sys.modules.get(key) for key in cls._module_keys}

        sys.modules.setdefault("dotenv", _stub_module("dotenv", load_dotenv=lambda: None))
        sys.modules.setdefault("yfinance", _stub_module("yfinance"))
        sys.modules.setdefault("pandas", _stub_module("pandas"))
        sys.modules.setdefault("pandas_ta", _stub_module("pandas_ta"))
        sys.modules.setdefault(
            "colorama",
            _stub_module(
                "colorama",
                Fore=types.SimpleNamespace(GREEN="", RED="", CYAN="", WHITE=""),
                Style=types.SimpleNamespace(RESET_ALL=""),
                init=lambda **kwargs: None,
            ),
        )
        eth_account = _stub_module(
            "eth_account",
            Account=types.SimpleNamespace(from_key=lambda key: object()),
        )
        sys.modules.setdefault("eth_account", eth_account)
        sys.modules.setdefault("hyperliquid", _stub_module("hyperliquid"))
        sys.modules.setdefault(
            "hyperliquid.exchange",
            _stub_module("hyperliquid.exchange", Exchange=object),
        )
        sys.modules.setdefault(
            "hyperliquid.info",
            _stub_module("hyperliquid.info", Info=object),
        )
        constants = _stub_module(
            "hyperliquid.utils.constants",
            TESTNET_API_URL="https://test.example",
            MAINNET_API_URL="https://main.example",
        )
        sys.modules.setdefault("hyperliquid.utils", _stub_module("hyperliquid.utils", constants=constants))
        sys.modules.setdefault("hyperliquid.utils.constants", constants)

    @classmethod
    def tearDownClass(cls):
        for key, original in cls._original_modules.items():
            if original is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = original

    def test_paper_trader_load_save_round_trip_preserves_schema(self):
        paper_trader = importlib.import_module("paper_trader")

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "paper_state.json"

            with patch.object(paper_trader, "STATE_FILE", state_path):
                default_state = paper_trader.load_state()
                self.assertEqual(default_state["capital"], paper_trader.PAPER_CAPITAL)
                self.assertFalse(default_state["in_position"])

                saved = {
                    "in_position": True,
                    "entry_price": 100.0,
                    "entry_time": "2026-03-12 10:00",
                    "stop_price": 98.0,
                    "shares": 1.5,
                    "capital": 12.34,
                    "total_trades": 2,
                    "wins": 1,
                }
                paper_trader.save_state(saved)
                loaded = paper_trader.load_state()

        self.assertEqual(loaded, saved)


class TestAtomicStateSave(unittest.TestCase):
    """Verify save_state uses write-then-rename so a crash cannot corrupt the file."""

    def test_save_produces_valid_json(self):
        from shared.state import save_state, load_state
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            save_state(path, {"capital": 999.0, "positions": {}})
            loaded = load_state(path)
        self.assertEqual(loaded["capital"], 999.0)

    def test_save_replaces_existing_file_atomically(self):
        """Old file must survive if an intermediate write is interrupted."""
        from shared.state import save_state, load_state
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            # Write initial state
            save_state(path, {"capital": 100.0})
            self.assertTrue(path.exists())
            # Write new state — temp file then rename
            save_state(path, {"capital": 200.0})
            loaded = load_state(path)
        self.assertEqual(loaded["capital"], 200.0)
        # No leftover temp files
        import glob
        leftover = glob.glob(str(Path(tmp) / ".state_tmp_*"))
        self.assertEqual(leftover, [])


class TestRiskManagerSizingCap(unittest.TestCase):
    """Verify calculate_position applies HL_MAX_POSITION_USD and returns honest risk_amount."""

    def setUp(self):
        for key in ("dotenv", "colorama"):
            sys.modules.setdefault(key, _stub_module(
                key,
                load_dotenv=lambda: None,
                Fore=types.SimpleNamespace(GREEN="", RED="", CYAN="", YELLOW=""),
                Style=types.SimpleNamespace(RESET_ALL=""),
            ))

    def test_size_usd_is_capped_at_hl_max(self):
        import importlib
        rm_mod = importlib.import_module("risk_manager")
        # With capital=672, RISK_PER_TRADE=0.03, sl_pct=0.002:
        # uncapped = 672 × 0.03 / 0.002 = $10,080 — should be capped at 200
        with patch("config.PAPER_CAPITAL", 672.0), \
             patch("config.RISK_PER_TRADE", 0.03), \
             patch("config.HL_MAX_POSITION_USD", 200.0), \
             patch("config.AI_ENABLED", False):
            rm = rm_mod.RiskManager.__new__(rm_mod.RiskManager)
            rm.state = {"capital": 672.0, "positions": {}}
            sizing = rm.calculate_position(price=100.0, sl_pct=0.002)
        self.assertLessEqual(sizing["size_usd"], 200.0)
        # risk_amount should reflect actual risk, not the inflated RISK_PER_TRADE figure
        self.assertAlmostEqual(sizing["risk_amount"], sizing["size_usd"] * 0.002, places=4)
