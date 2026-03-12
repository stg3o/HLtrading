"""Compatibility facade for notifier helpers."""

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TESTNET
from hltrading.shared.telegram_transport import send_telegram_message
from hltrading.interfaces.notifier import (
    notify_daily_halt,
    notify_emergency,
    notify_signal,
    notify_trade_close,
    notify_trade_open,
)


def _enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send(text: str) -> bool:
    """Send a plain text message to Telegram. Returns True on success."""
    if not _enabled():
        return False
    try:
        return send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, text, timeout=5)
    except Exception as e:
        from colorama import Fore

        print(Fore.YELLOW + f"  Telegram error: {e}")
        return False

__all__ = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TESTNET",
    "send_telegram_message",
    "_enabled",
    "send",
    "notify_trade_open",
    "notify_trade_close",
    "notify_emergency",
    "notify_daily_halt",
    "notify_signal",
]
