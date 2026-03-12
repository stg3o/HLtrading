"""Read-only account and position query helpers."""
from hltrading.execution.hyperliquid_client import (
    get_hl_account_info as _get_hl_account_info,
    get_hl_fees as _get_hl_fees,
    get_hl_positions as _get_hl_positions,
)


def get_hl_positions() -> list:
    """Return open Hyperliquid perp positions."""
    return _get_hl_positions()


def get_hl_account_info() -> dict:
    """Return unified Hyperliquid account information."""
    return _get_hl_account_info()


def get_hl_fees() -> dict:
    """Return aggregated Hyperliquid fee information."""
    return _get_hl_fees()
