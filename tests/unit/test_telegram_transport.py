#!/usr/bin/env python3
"""
Regression tests for shared Telegram transport wrappers.
"""
import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch


def _stub_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestSharedTelegramTransport(unittest.TestCase):
    def test_send_telegram_message_returns_ok_flag(self):
        from shared.telegram_transport import send_telegram_message

        with patch("urllib.request.urlopen", return_value=_FakeResponse({"ok": True})) as mock_urlopen:
            result = send_telegram_message("token", "chat", "hello", timeout=9)

        self.assertTrue(result)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 9)
        self.assertEqual(request.full_url, "https://api.telegram.org/bottoken/sendMessage")
        self.assertEqual(request.headers["Content-type"], "application/json")

    def test_send_telegram_message_returns_false_without_credentials(self):
        from shared.telegram_transport import send_telegram_message

        self.assertFalse(send_telegram_message("", "chat", "hello"))
        self.assertFalse(send_telegram_message("token", "", "hello"))


class TestNotifierAndTelegramBotWrappers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module_keys = ("dotenv", "colorama")
        cls._original_modules = {key: sys.modules.get(key) for key in cls._module_keys}

        sys.modules.setdefault("dotenv", _stub_module("dotenv", load_dotenv=lambda: None))
        sys.modules.setdefault(
            "colorama",
            _stub_module(
                "colorama",
                Fore=types.SimpleNamespace(YELLOW="", RED="", CYAN=""),
                Style=types.SimpleNamespace(RESET_ALL=""),
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

    def test_notifier_send_preserves_timeout_and_bool_return(self):
        notifier = importlib.import_module("notifier")

        with patch.object(notifier, "TELEGRAM_BOT_TOKEN", "token"), \
             patch.object(notifier, "TELEGRAM_CHAT_ID", "chat"), \
             patch("notifier.send_telegram_message", return_value=True) as mock_send:
            result = notifier.send("hi")

        self.assertTrue(result)
        mock_send.assert_called_once_with("token", "chat", "hi", timeout=5)

    def test_telegram_bot_wrappers_preserve_api_and_send_behavior(self):
        telegram_bot = importlib.import_module("telegram_bot")

        with patch.object(telegram_bot, "TELEGRAM_BOT_TOKEN", "token"), \
             patch.object(telegram_bot, "TELEGRAM_CHAT_ID", "chat"), \
             patch("telegram_bot.telegram_api_request", return_value={"result": []}) as mock_api, \
             patch("telegram_bot.send_telegram_message", return_value=False) as mock_send:
            api_result = telegram_bot._api("getUpdates", {"offset": 2}, timeout=12)
            send_result = telegram_bot._send("hello")

        self.assertEqual(api_result, {"result": []})
        mock_api.assert_called_once_with("token", "getUpdates", {"offset": 2}, timeout=12)
        mock_send.assert_called_once_with("token", "chat", "hello", timeout=15)
        self.assertTrue(send_result)
