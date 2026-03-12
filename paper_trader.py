"""Compatibility facade for paper trading helpers."""

from hltrading.execution import paper_trader as _impl
from hltrading.execution.paper_trader import *  # noqa: F401,F403

_load_json_state = _impl._load_json_state
_save_json_state = _impl._save_json_state


def _sync_impl_state_globals():
    _impl.PAPER_CAPITAL = PAPER_CAPITAL
    _impl.STATE_FILE = STATE_FILE
    _impl.TRADES_FILE = TRADES_FILE


def _default_state():
    _sync_impl_state_globals()
    return _impl._default_state()


def load_state():
    _sync_impl_state_globals()
    return _impl.load_state()


def save_state(state):
    _sync_impl_state_globals()
    return _impl.save_state(state)


def log_trade(action, price, pnl=None, pnl_pct=None, reason=""):
    _sync_impl_state_globals()
    return _impl.log_trade(action, price, pnl=pnl, pnl_pct=pnl_pct, reason=reason)
