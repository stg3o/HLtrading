"""Compatibility facade for Telegram transport helpers."""

from hltrading.shared.telegram_transport import send_telegram_message, telegram_api_request

__all__ = ["send_telegram_message", "telegram_api_request"]
