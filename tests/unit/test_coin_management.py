import json
import tempfile
import types
import unittest
from pathlib import Path

from interfaces.coin_management import (
    ALLOWED_PERIODS_BY_INTERVAL,
    apply_coin_overrides,
    load_coin_overrides,
    manage_coin_overrides,
    save_coin_overrides,
)


class TestCoinManagement(unittest.TestCase):
    def setUp(self):
        self.coins = {
            "ETH": {"enabled": True, "ticker": "ETH-USD", "strategy_type": "supertrend", "interval": "1h", "period": "365d"},
            "BTC": {"enabled": False, "ticker": "BTC-USD", "strategy_type": "supertrend", "interval": "1h", "period": "365d"},
            "SOL": {"ticker": "SOL-USD", "strategy_type": "mean_reversion", "interval": "5m", "period": "60d"},
        }
        self.fore = types.SimpleNamespace(CYAN="", GREEN="", RED="", YELLOW="", WHITE="")
        self.style = types.SimpleNamespace(RESET_ALL="")

    def test_apply_coin_overrides_updates_effective_coin_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            path.write_text(
                json.dumps(
                    {
                        "BTC": {"enabled": True},
                        "SOL": {"enabled": False, "strategy_type": "supertrend", "interval": "1h", "period": "180d"},
                    }
                ),
                encoding="utf-8",
            )

            settings = apply_coin_overrides(self.coins, path=path)

            self.assertEqual(settings["ETH"]["enabled"], True)
            self.assertEqual(settings["BTC"]["enabled"], True)
            self.assertEqual(settings["SOL"]["enabled"], False)
            self.assertTrue(self.coins["BTC"]["enabled"])
            self.assertFalse(self.coins["SOL"]["enabled"])
            self.assertEqual(self.coins["SOL"]["strategy_type"], "supertrend")
            self.assertEqual(self.coins["SOL"]["interval"], "1h")
            self.assertEqual(self.coins["SOL"]["period"], "180d")

    def test_save_coin_overrides_writes_minimal_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"

            overrides = save_coin_overrides(
                self.coins,
                {
                    "ETH": {"enabled": True, "strategy_type": "supertrend", "interval": "1h", "period": "365d"},
                    "BTC": {"enabled": True, "strategy_type": "supertrend", "interval": "1h", "period": "365d"},
                    "SOL": {"enabled": False, "strategy_type": "supertrend", "interval": "1h", "period": "180d"},
                },
                path=path,
            )

            self.assertEqual(
                overrides,
                {
                    "BTC": {"enabled": True},
                    "SOL": {"enabled": False, "strategy_type": "supertrend", "interval": "1h", "period": "180d"},
                },
            )
            self.assertEqual(load_coin_overrides(path), overrides)

    def test_manage_coin_overrides_toggle_enable_all_and_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            answers = iter(["1", "1", "B", "A", "S"])
            output = []

            changed = manage_coin_overrides(
                self.coins,
                input_fn=lambda _: next(answers),
                printer=output.append,
                fore=self.fore,
                style=self.style,
                path=path,
            )

            self.assertTrue(changed)
            self.assertTrue(self.coins["ETH"]["enabled"])
            self.assertTrue(self.coins["BTC"]["enabled"])
            self.assertTrue(self.coins["SOL"]["enabled"])
            self.assertEqual(load_coin_overrides(path), {"BTC": {"enabled": True}})

    def test_manage_coin_overrides_cancel_does_not_save(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            answers = iter(["2", "1", "B", "C"])

            changed = manage_coin_overrides(
                self.coins,
                input_fn=lambda _: next(answers),
                printer=lambda *_: None,
                fore=self.fore,
                style=self.style,
                path=path,
            )

            self.assertFalse(changed)
            self.assertFalse(path.exists())
            self.assertFalse(self.coins["BTC"]["enabled"])

    def test_manage_coin_overrides_edits_strategy_interval_and_period(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            answers = iter([
                "3",  # SOL
                "2", "2", "N",  # strategy_type -> supertrend, skip preset
                "3", "4",  # interval -> 1h
                "4", "2",  # period -> 180d
                "B",
                "S",
            ])

            changed = manage_coin_overrides(
                self.coins,
                input_fn=lambda _: next(answers),
                printer=lambda *_: None,
                fore=self.fore,
                style=self.style,
                path=path,
            )

            self.assertTrue(changed)
            self.assertEqual(self.coins["SOL"]["strategy_type"], "supertrend")
            self.assertEqual(self.coins["SOL"]["interval"], "1h")
            self.assertEqual(self.coins["SOL"]["period"], "180d")
            self.assertEqual(
                load_coin_overrides(path),
                {"SOL": {"interval": "1h", "period": "180d", "strategy_type": "supertrend"}},
            )

    def test_interval_change_adjusts_invalid_period_to_valid_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            answers = iter([
                "1",      # ETH
                "3", "1", # interval -> 5m
                "B",
                "S",
            ])

            changed = manage_coin_overrides(
                self.coins,
                input_fn=lambda _: next(answers),
                printer=lambda *_: None,
                fore=self.fore,
                style=self.style,
                path=path,
            )

            self.assertTrue(changed)
            self.assertEqual(self.coins["ETH"]["interval"], "5m")
            self.assertEqual(self.coins["ETH"]["period"], ALLOWED_PERIODS_BY_INTERVAL["5m"][0])

    def test_strategy_change_can_apply_preset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            answers = iter([
                "3",          # SOL
                "2", "2", "Y",  # strategy_type -> supertrend, apply preset
                "B",
                "S",
            ])

            changed = manage_coin_overrides(
                self.coins,
                input_fn=lambda _: next(answers),
                printer=lambda *_: None,
                fore=self.fore,
                style=self.style,
                path=path,
            )

            self.assertTrue(changed)
            self.assertEqual(self.coins["SOL"]["strategy_type"], "supertrend")
            self.assertEqual(self.coins["SOL"]["interval"], "1h")
            self.assertEqual(self.coins["SOL"]["period"], "365d")

    def test_strategy_change_can_skip_preset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "coin_overrides.json"
            answers = iter([
                "1",          # ETH
                "2", "1", "N",  # strategy_type -> mean_reversion, skip preset
                "B",
                "S",
            ])

            changed = manage_coin_overrides(
                self.coins,
                input_fn=lambda _: next(answers),
                printer=lambda *_: None,
                fore=self.fore,
                style=self.style,
                path=path,
            )

            self.assertTrue(changed)
            self.assertEqual(self.coins["ETH"]["strategy_type"], "mean_reversion")
            self.assertEqual(self.coins["ETH"]["interval"], "1h")
            self.assertEqual(self.coins["ETH"]["period"], "365d")


if __name__ == "__main__":
    unittest.main()
