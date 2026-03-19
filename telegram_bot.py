"""Telegram command controller for the trading bot."""

from __future__ import annotations

import threading
import time
import urllib.error

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from hltrading.shared.telegram_transport import send_telegram_message, telegram_api_request


def _api(method: str, payload: dict | None = None, timeout: int = 15) -> dict:
    return telegram_api_request(TELEGRAM_BOT_TOKEN, method, payload, timeout=timeout)


def _send(text: str, chat_id: str | None = None) -> bool:
    cid = chat_id or TELEGRAM_CHAT_ID
    if not (TELEGRAM_BOT_TOKEN and cid):
        return False
    try:
        send_telegram_message(TELEGRAM_BOT_TOKEN, cid, text, timeout=15)
        return True
    except Exception:
        return False


class TelegramController:
    """Background Telegram poller with concise slash-command routing."""

    POLL_TIMEOUT = 30
    RETRY_DELAY = 5

    def __init__(self, *, risk_manager, callbacks: dict[str, callable] | None = None):
        self._risk = risk_manager
        self._callbacks = callbacks or {}
        self._paused = threading.Event()
        self._offset = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._conflict_reported = False
        self._pending_live_confirmation = False

    def start(self) -> None:
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="telegram-controller")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def _call(self, name: str, *args, **kwargs) -> str:
        fn = self._callbacks.get(name)
        if not fn:
            return "Unavailable."
        try:
            result = fn(*args, **kwargs)
            return str(result or "OK")
        except Exception as exc:
            return f"Failed: {exc}"

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                resp = _api(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self.POLL_TIMEOUT,
                        "allowed_updates": ["message"],
                    },
                    timeout=self.POLL_TIMEOUT + 5,
                )
                for update in resp.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle(update)
            except urllib.error.HTTPError as exc:
                if exc.code == 409:
                    self._conflict_reported = True
                    self._stop.set()
                    return
                time.sleep(self.RETRY_DELAY)
            except Exception:
                time.sleep(self.RETRY_DELAY)

    def _handle(self, update: dict) -> None:
        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        cid = str(msg.get("chat", {}).get("id", ""))
        if cid != str(TELEGRAM_CHAT_ID) or not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        command = parts[0].lower().split("@")[0]
        arg_text = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            "/help": self._cmd_help,
            "/start": self._cmd_start,
            "/stop": self._cmd_stop,
            "/status": self._cmd_status,
            "/emergency": self._cmd_emergency,
            "/mode": self._cmd_mode,
            "/setcapital": self._cmd_setcapital,
            "/coins": self._cmd_coins,
            "/analyze": self._cmd_analyze,
            "/backtest": self._cmd_backtest,
            "/optimize": self._cmd_optimize,
            "/report": self._cmd_report,
            "/stress": self._cmd_stress,
            "/dashboard": self._cmd_dashboard,
            "/symbols": self._cmd_symbols,
            "/fetch": self._cmd_fetch,
            "/ask": self._cmd_ask,
        }
        handler = handlers.get(command)
        if not handler:
            _send("Unknown command.\nUse /help.")
            return
        _send(handler(arg_text), chat_id=cid)

    def _cmd_help(self, _arg: str = "") -> str:
        return (
            "Core: /start /stop /status /emergency\n"
            "Trading: /mode /setcapital /coins\n"
            "Analysis: /analyze /backtest /optimize /report /stress\n"
            "Utility: /dashboard /symbols /fetch /ask"
        )

    def _cmd_start(self, _arg: str = "") -> str:
        return self._call("start")

    def _cmd_stop(self, _arg: str = "") -> str:
        return self._call("stop")

    def _cmd_status(self, _arg: str = "") -> str:
        return self._call("status")

    def _cmd_emergency(self, _arg: str = "") -> str:
        return self._call("emergency")

    def _cmd_mode(self, arg: str) -> str:
        mode_parts = arg.lower().split()
        if not mode_parts or mode_parts[0] not in ("paper", "live"):
            return "Usage: /mode [paper|live]"
        target = mode_parts[0]
        if target == "live":
            if len(mode_parts) > 1 and mode_parts[1] == "confirm":
                self._pending_live_confirmation = False
                return self._call("mode", "live", True)
            self._pending_live_confirmation = True
            return "Live mode requires confirmation.\nSend /mode live confirm"
        self._pending_live_confirmation = False
        return self._call("mode", "paper", True)

    def _cmd_setcapital(self, arg: str) -> str:
        try:
            amount = float(arg.strip())
        except Exception:
            return "Usage: /setcapital [amount]"
        return self._call("setcapital", amount)

    def _cmd_coins(self, arg: str) -> str:
        parts = arg.split()
        if not parts or parts[0].lower() == "list":
            return self._call("coins", "list", None)
        if len(parts) != 2 or parts[0].lower() not in ("enable", "disable"):
            return "Usage: /coins [list|enable COIN|disable COIN]"
        return self._call("coins", parts[0].lower(), parts[1].upper())

    def _cmd_analyze(self, arg: str) -> str:
        coin = arg.strip().upper()
        if not coin:
            return "Usage: /analyze [coin]"
        return self._call("analyze", coin)

    def _cmd_backtest(self, arg: str) -> str:
        coin = arg.strip().upper()
        if not coin:
            return "Usage: /backtest [coin]"
        return self._call("backtest", coin)

    def _cmd_optimize(self, _arg: str = "") -> str:
        return self._call("optimize")

    def _cmd_report(self, _arg: str = "") -> str:
        return self._call("report")

    def _cmd_stress(self, arg: str) -> str:
        coin = arg.strip().upper()
        if not coin:
            return "Usage: /stress [coin]"
        return self._call("stress", coin)

    def _cmd_dashboard(self, _arg: str = "") -> str:
        return self._call("dashboard")

    def _cmd_symbols(self, _arg: str = "") -> str:
        return self._call("symbols")

    def _cmd_fetch(self, _arg: str = "") -> str:
        return self._call("fetch")

    def _cmd_ask(self, arg: str) -> str:
        text = arg.strip()
        if not text:
            return "Usage: /ask [text]"
        return self._call("ask", text)
