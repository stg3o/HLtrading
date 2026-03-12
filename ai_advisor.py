"""Compatibility facade for AI advisor helpers."""

from hltrading.strategy import ai_advisor as _impl
from hltrading.strategy.ai_advisor import *  # noqa: F401,F403

SYSTEM_PROMPT = _impl.SYSTEM_PROMPT
SYSTEM_PROMPT_SUPERTREND = _impl.SYSTEM_PROMPT_SUPERTREND
_ORIG_ASK_OLLAMA = _impl._ask_ollama
_ORIG_ASK_OPENROUTER = _impl._ask_openrouter
_build_user_prompt_supertrend = _impl._build_user_prompt_supertrend
_build_user_prompt = _impl._build_user_prompt
_parse_response = _impl._parse_response
_rule_based_signal = _impl._rule_based_signal
_rule_based_signal_supertrend = _impl._rule_based_signal_supertrend


def _sync_impl():
    _impl.SYSTEM_PROMPT = SYSTEM_PROMPT
    _impl.SYSTEM_PROMPT_SUPERTREND = SYSTEM_PROMPT_SUPERTREND
    _impl._build_user_prompt_supertrend = _build_user_prompt_supertrend
    _impl._build_user_prompt = _build_user_prompt
    _impl._parse_response = _parse_response
    _impl._rule_based_signal = _rule_based_signal
    _impl._rule_based_signal_supertrend = _rule_based_signal_supertrend


def _ask_ollama(prompt: str) -> dict:
    _sync_impl()
    return _ORIG_ASK_OLLAMA(prompt)


def _ask_openrouter(prompt: str) -> dict:
    _sync_impl()
    return _ORIG_ASK_OPENROUTER(prompt)


def get_decision(indicators: dict, recent_trades: list = None,
                 daily_bias: dict | None = None) -> dict:
    _sync_impl()
    _impl._ask_ollama = _ask_ollama
    _impl._ask_openrouter = _ask_openrouter
    return _impl.get_decision(indicators, recent_trades=recent_trades, daily_bias=daily_bias)
