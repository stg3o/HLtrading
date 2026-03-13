"""CLI helpers for coin configuration overrides."""
from __future__ import annotations

import json
from pathlib import Path


OVERRIDES_FILE = Path(__file__).resolve().parent.parent / "coin_overrides.json"
EDITABLE_KEYS = ("enabled", "strategy_type", "interval", "period")
ALLOWED_STRATEGY_TYPES = ("mean_reversion", "supertrend")
ALLOWED_INTERVALS = ("5m", "15m", "30m", "1h", "4h", "1d")
ALLOWED_PERIODS_BY_INTERVAL = {
    "5m": ("7d", "30d", "60d"),
    "15m": ("30d", "60d"),
    "30m": ("30d", "60d", "180d"),
    "1h": ("60d", "180d", "365d", "730d"),
    "4h": ("180d", "365d", "730d"),
    "1d": ("365d", "730d"),
}
STRATEGY_PRESETS = {
    "mean_reversion": {"interval": "5m", "period": "60d"},
    "supertrend": {"interval": "1h", "period": "365d"},
}


def _base_coin_settings(coins: dict) -> dict[str, dict]:
    settings = {}
    for coin, cfg in coins.items():
        settings[coin] = {
            "enabled": bool(cfg.get("enabled", True)),
            "strategy_type": cfg.get("strategy_type", "mean_reversion"),
            "interval": cfg.get("interval", "1h"),
            "period": cfg.get("period", "60d"),
        }
    return settings


def _normalize_override_value(value) -> dict:
    if isinstance(value, dict):
        normalized = {}
        for key in EDITABLE_KEYS:
            if key in value:
                normalized[key] = value[key]
        return normalized
    return {"enabled": bool(value)}


def _effective_coin_settings(coins: dict, overrides: dict[str, dict] | None = None) -> dict[str, dict]:
    settings = _base_coin_settings(coins)
    for coin, value in (overrides or {}).items():
        if coin not in settings:
            continue
        settings[coin].update(_normalize_override_value(value))
        settings[coin]["enabled"] = bool(settings[coin].get("enabled", True))
    return settings


def _validate_period(interval: str, period: str) -> bool:
    return period in ALLOWED_PERIODS_BY_INTERVAL.get(interval, ())


def _coerce_settings(settings: dict) -> dict:
    strategy_type = settings.get("strategy_type", "mean_reversion")
    if strategy_type not in ALLOWED_STRATEGY_TYPES:
        strategy_type = "mean_reversion"

    interval = settings.get("interval", "1h")
    if interval not in ALLOWED_INTERVALS:
        interval = "1h"

    period = settings.get("period", "60d")
    if not _validate_period(interval, period):
        period = ALLOWED_PERIODS_BY_INTERVAL[interval][0]

    return {
        "enabled": bool(settings.get("enabled", True)),
        "strategy_type": strategy_type,
        "interval": interval,
        "period": period,
    }


def load_coin_overrides(path: str | Path = OVERRIDES_FILE) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(coin): _normalize_override_value(value) for coin, value in raw.items()}


def save_coin_overrides(
    coins: dict,
    settings_map: dict[str, dict],
    path: str | Path = OVERRIDES_FILE,
) -> dict[str, dict]:
    path = Path(path)
    base = _base_coin_settings(coins)
    overrides = {}
    for coin, current in settings_map.items():
        if coin not in base:
            continue
        current = _coerce_settings(current)
        diff = {
            key: current[key]
            for key in EDITABLE_KEYS
            if current[key] != base[coin][key]
        }
        if diff:
            overrides[coin] = diff
    path.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return overrides


def apply_coin_overrides(coins: dict, path: str | Path = OVERRIDES_FILE) -> dict[str, dict]:
    overrides = load_coin_overrides(path)
    settings = _effective_coin_settings(coins, overrides)
    for coin, coin_settings in settings.items():
        coins[coin]["enabled"] = coin_settings["enabled"]
        coins[coin]["strategy_type"] = coin_settings["strategy_type"]
        coins[coin]["interval"] = coin_settings["interval"]
        coins[coin]["period"] = coin_settings["period"]
    return settings


def _render_coin_list(working: dict[str, dict], *, printer, fore, style) -> None:
    printer(f"\n  {fore.CYAN}Manage Coins{style.RESET_ALL}")
    printer(f"  {fore.CYAN}{'-'*58}{style.RESET_ALL}")
    for idx, (coin, settings) in enumerate(working.items(), start=1):
        status = "ON" if settings["enabled"] else "OFF"
        color = fore.GREEN if status == "ON" else fore.RED
        printer(
            f"  [{idx}] {coin:<8} {color}{status}{style.RESET_ALL}"
            f"  {settings['strategy_type']:<14}  {settings['interval']:<3}  {settings['period']}"
        )
    printer(f"\n  [A] Enable All   [D] Disable All")
    printer(f"  [S] Save & Return")
    printer(f"  [C] Cancel")


def _choose_from_list(title: str, options: tuple[str, ...], *, input_fn, printer, fore, style) -> str | None:
    printer(f"\n  {fore.CYAN}{title}{style.RESET_ALL}")
    for idx, option in enumerate(options, start=1):
        printer(f"  [{idx}] {option}")
    printer("  [C] Cancel")
    raw = input_fn("  Your choice: ").strip().upper()
    if raw == "C":
        return None
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(options):
            return options[idx - 1]
    printer(fore.RED + "  Invalid choice.")
    return None


def _ask_yes_no(prompt: str, *, input_fn, printer, fore) -> bool | None:
    raw = input_fn(prompt).strip().upper()
    if raw in ("Y", "YES"):
        return True
    if raw in ("N", "NO"):
        return False
    if raw in ("C", ""):
        return None
    printer(fore.RED + "  Invalid choice.")
    return None


def _edit_coin(
    coin: str,
    settings: dict,
    *,
    input_fn,
    printer,
    fore,
    style,
) -> None:
    while True:
        printer(f"\n  {fore.CYAN}Edit {coin}{style.RESET_ALL}")
        printer(f"  [1] Enabled       : {'ON' if settings['enabled'] else 'OFF'}")
        printer(f"  [2] Strategy Type : {settings['strategy_type']}")
        printer(f"  [3] Interval      : {settings['interval']}")
        printer(f"  [4] Period        : {settings['period']}")
        printer("  [B] Back")

        raw = input_fn("  Your choice: ").strip().upper()
        if raw == "1":
            settings["enabled"] = not settings["enabled"]
            continue
        if raw == "2":
            value = _choose_from_list(
                "Select Strategy Type",
                ALLOWED_STRATEGY_TYPES,
                input_fn=input_fn,
                printer=printer,
                fore=fore,
                style=style,
            )
            if value is not None:
                settings["strategy_type"] = value
                preset = STRATEGY_PRESETS[value]
                apply_preset = _ask_yes_no(
                    f"  Apply {value} preset ({preset['interval']} / {preset['period']})? [y/N/C]: ",
                    input_fn=input_fn,
                    printer=printer,
                    fore=fore,
                )
                if apply_preset:
                    settings["interval"] = preset["interval"]
                    settings["period"] = preset["period"]
            continue
        if raw == "3":
            value = _choose_from_list(
                "Select Interval",
                ALLOWED_INTERVALS,
                input_fn=input_fn,
                printer=printer,
                fore=fore,
                style=style,
            )
            if value is not None:
                settings["interval"] = value
                if not _validate_period(settings["interval"], settings["period"]):
                    settings["period"] = ALLOWED_PERIODS_BY_INTERVAL[settings["interval"]][0]
                    printer(fore.YELLOW + f"  Period adjusted to {settings['period']} for {settings['interval']}.")
            continue
        if raw == "4":
            value = _choose_from_list(
                "Select Period",
                ALLOWED_PERIODS_BY_INTERVAL[settings["interval"]],
                input_fn=input_fn,
                printer=printer,
                fore=fore,
                style=style,
            )
            if value is not None:
                settings["period"] = value
            continue
        if raw == "B":
            return
        printer(fore.RED + "  Invalid choice.")


def manage_coin_overrides(
    coins: dict,
    *,
    input_fn=input,
    printer=print,
    fore=None,
    style=None,
    path: str | Path = OVERRIDES_FILE,
) -> bool:
    fore = fore or type("Fore", (), {"CYAN": "", "GREEN": "", "RED": "", "YELLOW": "", "WHITE": ""})()
    style = style or type("Style", (), {"RESET_ALL": ""})()
    working = _effective_coin_settings(coins)

    while True:
        _render_coin_list(working, printer=printer, fore=fore, style=style)
        raw = input_fn("  Select coin by number: ").strip().upper()
        if raw == "A":
            for coin_settings in working.values():
                coin_settings["enabled"] = True
            continue
        if raw == "D":
            for coin_settings in working.values():
                coin_settings["enabled"] = False
            continue
        if raw == "C":
            printer(fore.YELLOW + "  Cancelled. No changes saved.")
            return False
        if raw == "S":
            save_coin_overrides(coins, working, path=path)
            for coin, coin_settings in working.items():
                coins[coin]["enabled"] = coin_settings["enabled"]
                coins[coin]["strategy_type"] = coin_settings["strategy_type"]
                coins[coin]["interval"] = coin_settings["interval"]
                coins[coin]["period"] = coin_settings["period"]
            printer(fore.GREEN + "  Coin overrides saved.")
            return True
        if raw.isdigit():
            idx = int(raw)
            coin_keys = list(coins.keys())
            if 1 <= idx <= len(coin_keys):
                coin = coin_keys[idx - 1]
                _edit_coin(
                    coin,
                    working[coin],
                    input_fn=input_fn,
                    printer=printer,
                    fore=fore,
                    style=style,
                )
                continue

        printer(fore.RED + "  Invalid choice.")


__all__ = [
    "OVERRIDES_FILE",
    "apply_coin_overrides",
    "load_coin_overrides",
    "manage_coin_overrides",
    "save_coin_overrides",
]
