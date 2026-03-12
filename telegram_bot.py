"""
telegram_bot.py — Two-way Telegram control for the trading bot.

Commands:
  /help      — list all commands
  /status    — capital, open positions, today's P&L
  /positions — detailed open positions
  /pause     — stop opening new trades (monitoring continues)
  /resume    — resume trading after pause
  /close COIN — force-close a specific position (e.g. /close SOL)
  /closeall  — emergency close all open positions

Usage:
  Start the listener in a background thread from main.py:
      from telegram_bot import TelegramController
      tg = TelegramController(risk_manager=_risk, close_fn=close_trade,
                              closeall_fn=emergency_close_all)
      tg.start()

  Check pause state in the bot loop:
      if tg.is_paused():
          continue
"""
import json
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from colorama import Fore, Style

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TESTNET
from hltrading.shared.telegram_transport import send_telegram_message, telegram_api_request


# ─── LOW-LEVEL API ─────────────────────────────────────────────────────────────

def _api(method: str, payload: dict | None = None, timeout: int = 15) -> dict:
    """Call the Telegram Bot API. Returns the parsed JSON response.

    The `timeout` param controls the *socket* read timeout — must be greater
    than any Telegram long-poll timeout in the payload, or urllib will fire
    first and raise a spurious 'read operation timed out' error.
    """
    return telegram_api_request(TELEGRAM_BOT_TOKEN, method, payload, timeout=timeout)


def _send(text: str, chat_id: str | None = None) -> bool:
    """Send a message. Silently swallows errors so the bot never crashes."""
    cid = chat_id or TELEGRAM_CHAT_ID
    if not (TELEGRAM_BOT_TOKEN and cid):
        return False
    try:
        send_telegram_message(TELEGRAM_BOT_TOKEN, cid, text, timeout=15)
        return True
    except Exception as e:
        print(Fore.YELLOW + f"  [Telegram] send error: {e}")
        return False


# ─── CONTROLLER ────────────────────────────────────────────────────────────────

class TelegramController:
    """
    Polls Telegram for commands and routes them to bot actions.
    Runs in its own daemon thread — does not block the main bot loop.
    """

    POLL_TIMEOUT = 30     # long-poll timeout (seconds) — reduces API calls
    RETRY_DELAY  = 5      # seconds to wait after a network error before retrying

    def __init__(self, risk_manager, close_fn, closeall_fn):
        """
        risk_manager : RiskManager instance (reads positions + capital)
        close_fn     : close_trade(coin, risk_manager, reason=...) callable
        closeall_fn  : emergency_close_all(risk_manager) callable
        """
        self._risk      = risk_manager
        self._close     = close_fn
        self._closeall  = closeall_fn
        self._paused    = threading.Event()   # set = paused, clear = running
        self._offset    = 0                   # Telegram update offset
        self._thread: threading.Thread | None = None
        self._stop      = threading.Event()

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background polling thread."""
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            print(Fore.YELLOW + "  [Telegram] BOT_TOKEN or CHAT_ID not set — command listener disabled.")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name="telegram-controller")
        self._thread.start()
        print(Fore.CYAN + "  [Telegram] Command listener started.")
        _send("🤖 <b>Bot started.</b> Send /help for commands.")

    def stop(self) -> None:
        """Signal the polling thread to exit."""
        self._stop.set()

    def is_paused(self) -> bool:
        """Return True if trading is paused via /pause command."""
        return self._paused.is_set()

    # ── Polling loop ────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                # Socket timeout MUST exceed Telegram's poll timeout, otherwise
                # urllib fires first and raises "read operation timed out".
                resp = _api("getUpdates", {
                    "offset":  self._offset,
                    "timeout": self.POLL_TIMEOUT,
                    "allowed_updates": ["message"],
                }, timeout=self.POLL_TIMEOUT + 5)
                for update in resp.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle(update)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    print(Fore.RED + "  [Telegram] ✗ HTTP 401 — bot token invalid or missing.")
                    print(Fore.RED + "  Check TELEGRAM_BOT_TOKEN in .env (get it from @BotFather).")
                    print(Fore.YELLOW + "  Pausing Telegram polling for 60 s before retrying...")
                    time.sleep(60)
                else:
                    print(Fore.YELLOW + f"  [Telegram] poll HTTP error {e.code}: {e}")
                    time.sleep(self.RETRY_DELAY)
            except Exception as e:
                print(Fore.YELLOW + f"  [Telegram] poll error: {e}")
                time.sleep(self.RETRY_DELAY)

    # ── Message handler ─────────────────────────────────────────────────────

    def _handle(self, update: dict) -> None:
        msg  = update.get("message", {})
        text = (msg.get("text") or "").strip()
        cid  = str(msg.get("chat", {}).get("id", ""))

        # Only respond to the configured chat ID (security)
        if cid != str(TELEGRAM_CHAT_ID):
            return
        if not text.startswith("/"):
            return

        parts   = text.split()
        command = parts[0].lower().split("@")[0]   # strip @botname suffix

        print(Fore.CYAN + f"  [Telegram] Command received: {text}")

        if command == "/help":
            self._cmd_help()
        elif command == "/status":
            self._cmd_status()
        elif command == "/positions":
            self._cmd_positions()
        elif command == "/pause":
            self._cmd_pause()
        elif command == "/resume":
            self._cmd_resume()
        elif command == "/close":
            coin = parts[1].upper() if len(parts) > 1 else ""
            self._cmd_close(coin)
        elif command == "/closeall":
            self._cmd_closeall()
        else:
            _send(f"❓ Unknown command: <code>{command}</code>\nSend /help for the list.")

    # ── Command implementations ─────────────────────────────────────────────

    def _cmd_help(self) -> None:
        net = "TESTNET" if TESTNET else "⚠️ MAINNET"
        _send(
            f"🤖 <b>Bot Commands [{net}]</b>\n\n"
            "/status — capital, positions, P&amp;L\n"
            "/positions — detailed open positions\n"
            "/pause — stop opening new trades\n"
            "/resume — resume trading\n"
            "/close COIN — force-close a position\n"
            "  e.g. <code>/close SOL</code>\n"
            "/closeall — emergency close everything\n"
            "/help — show this message"
        )

    def _cmd_status(self) -> None:
        from trade_log import load_trades
        from config import PAPER_CAPITAL
        from datetime import date as _date

        # Use get_summary() — it correctly computes total_pnl as capital − PAPER_CAPITAL
        s       = self._risk.get_summary()
        capital = s["capital"]
        pnl     = s["total_pnl"]
        pnl_pct = (pnl / PAPER_CAPITAL * 100) if PAPER_CAPITAL else 0
        pnl_str = (f"+${pnl:,.2f} (+{pnl_pct:.1f}%)"
                   if pnl >= 0 else
                   f"-${abs(pnl):,.2f} ({pnl_pct:.1f}%)")

        # Today's P&L from trade log (CSV), filtered by today's date
        today_prefix = str(_date.today())
        try:
            trades     = load_trades()
            today_pnl  = sum(float(t["pnl"]) for t in trades
                             if t.get("timestamp", "").startswith(today_prefix))
            today_str  = (f"+${today_pnl:,.2f}" if today_pnl >= 0
                          else f"-${abs(today_pnl):,.2f}")
            today_n    = sum(1 for t in trades
                             if t.get("timestamp", "").startswith(today_prefix))
        except Exception:
            today_str = "n/a"
            today_n   = 0

        positions  = s["positions"]
        pos_count  = len(positions)
        paused_str = "⏸ PAUSED" if self._paused.is_set() else "▶️ RUNNING"

        lines = [
            f"📊 <b>Bot Status</b>  [{paused_str}]",
            f"",
            f"Capital:    <b>${capital:,.2f}</b>",
            f"Total P&amp;L: <b>{pnl_str}</b>",
            f"Today P&amp;L: <b>{today_str}</b>  ({today_n} trades today,  {s['win_rate']:.0f}% WR all-time)",
            f"Positions:  <b>{pos_count}</b> open",
        ]

        for coin, pos in positions.items():
            side  = pos.get("side", "?").upper()
            entry = pos.get("entry_price", 0)
            sz    = pos.get("size_usd", 0)
            lines.append(f"  • {coin} {side}  entry=${entry:,.4f}  sz=${sz:,.2f}")

        _send("\n".join(lines))

    def _cmd_positions(self) -> None:
        positions = self._risk.state.get("positions", {})
        if not positions:
            _send("📭 No open positions.")
            return

        lines = ["📋 <b>Open Positions</b>\n"]
        for coin, pos in positions.items():
            side  = pos.get("side", "?").upper()
            entry = pos.get("entry_price", 0)
            sl    = pos.get("stop_loss", 0)
            tp    = pos.get("take_profit", 0)
            sz    = pos.get("size_usd", 0)
            units = pos.get("size_units", 0)
            lines.append(
                f"<b>{coin}</b>  {side}\n"
                f"  Entry: ${entry:,.4f}  ({units} units, ${sz:,.2f})\n"
                f"  SL:    ${sl:,.4f}  |  TP: ${tp:,.4f}"
            )
        _send("\n".join(lines))

    def _cmd_pause(self) -> None:
        if self._paused.is_set():
            _send("⏸ Already paused. Send /resume to restart trading.")
            return
        self._paused.set()
        _send("⏸ <b>Trading paused.</b>\nOpen positions are still monitored. Send /resume to restart.")

    def _cmd_resume(self) -> None:
        if not self._paused.is_set():
            _send("▶️ Already running. No action needed.")
            return
        self._paused.clear()
        _send("▶️ <b>Trading resumed.</b>")

    def _cmd_close(self, coin: str) -> None:
        if not coin:
            _send("❌ Usage: <code>/close COIN</code>  e.g. /close SOL")
            return
        positions = self._risk.state.get("positions", {})
        if coin not in positions:
            open_list = ", ".join(positions.keys()) or "none"
            _send(f"❌ No open position for <b>{coin}</b>.\nOpen positions: {open_list}")
            return
        _send(f"⚡ Closing <b>{coin}</b> position…")
        try:
            self._close(coin, self._risk, reason="telegram_command")
            _send(f"✅ <b>{coin}</b> position closed.")
        except Exception as e:
            _send(f"❌ Error closing {coin}: {e}")

    def _cmd_closeall(self) -> None:
        positions = self._risk.state.get("positions", {})
        if not positions:
            _send("📭 No open positions to close.")
            return
        coins = ", ".join(positions.keys())
        _send(f"🚨 Closing all positions: <b>{coins}</b>…")
        try:
            self._closeall(self._risk)
            _send("✅ All positions closed.")
        except Exception as e:
            _send(f"❌ Error during closeall: {e}")
