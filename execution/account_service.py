"""Compatibility facade for read-only account and position query helpers."""

from hltrading.execution import account_service as _impl
from hltrading.execution.account_service import *  # noqa: F401,F403

_get_hl_account_info = _impl._get_hl_account_info
_get_hl_fees = _impl._get_hl_fees
_get_hl_positions = _impl._get_hl_positions


def get_hl_positions() -> list:
    """Return open Hyperliquid perp positions."""
    return _get_hl_positions()


def get_hl_account_info() -> dict | None:
    """Return unified Hyperliquid account information."""
    return _get_hl_account_info()


def get_hl_fees() -> dict:
    """Return aggregated Hyperliquid fee information."""
    return _get_hl_fees()
