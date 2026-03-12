"""
hltrading.shared.telegram_transport — low-level Telegram Bot API helpers.
"""
from __future__ import annotations

import json
import urllib.request


def telegram_api_request(
    token: str,
    method: str,
    payload: dict | None = None,
    *,
    timeout: int = 15,
) -> dict:
    """Call the Telegram Bot API and return the parsed JSON response."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def send_telegram_message(
    token: str,
    default_chat_id: str | None,
    text: str,
    *,
    chat_id: str | None = None,
    timeout: int = 5,
) -> bool:
    """
    Send a Telegram message using HTML parse mode.

    Returns False when credentials are missing, otherwise returns the Bot API
    `ok` flag from the response.
    """
    target_chat_id = chat_id or default_chat_id
    if not (token and target_chat_id):
        return False
    response = telegram_api_request(
        token,
        "sendMessage",
        {"chat_id": target_chat_id, "text": text, "parse_mode": "HTML"},
        timeout=timeout,
    )
    return bool(response.get("ok", False))
