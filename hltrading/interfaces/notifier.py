"""
notifier.py — Telegram trade notifications
Sends alerts when trades open, close, SL/TP hits, or emergency stop triggers.
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable.
Create a bot via @BotFather on Telegram to get your token.
Get your chat ID by messaging @userinfobot on Telegram.
"""
from datetime import datetime

from colorama import Fore

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TESTNET
from hltrading.shared.telegram_transport import send_telegram_message


def _enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def send(text: str) -> bool:
    """Send a plain text message to Telegram. Returns True on success."""
    if not _enabled():
        return False
    try:
        return send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, text, timeout=5)
    except Exception as e:
        print(Fore.YELLOW + f"  Telegram error: {e}")
        return False


def notify_trade_open(coin: str, side: str, price: float,
                      size_usd: float, stop_loss: float, take_profit: float) -> None:
    net = "TESTNET" if TESTNET else "⚠️ MAINNET"
    emoji = "🟢" if side == "long" else "🔴"
    send(
        f"{emoji} <b>Trade Opened [{net}]</b>\n"
        f"Coin:   <b>{coin}</b>  {side.upper()}\n"
        f"Entry:  <b>${price:,.4f}</b>  (${size_usd:,.2f})\n"
        f"SL:     ${stop_loss:,.4f}\n"
        f"TP:     ${take_profit:,.4f}\n"
        f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
    )


def notify_trade_close(coin: str, side: str, entry: float,
                       exit_price: float, pnl: float, reason: str) -> None:
    emoji = "✅" if pnl >= 0 else "❌"
    pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    send(
        f"{emoji} <b>Trade Closed</b>\n"
        f"Coin:   <b>{coin}</b>  {side.upper()}\n"
        f"Entry:  ${entry:,.4f}  →  Exit: ${exit_price:,.4f}\n"
        f"P&L:    <b>{pnl_str}</b>\n"
        f"Reason: {reason}\n"
        f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
    )


def notify_emergency(reason: str) -> None:
    send(
        f"🚨 <b>EMERGENCY STOP TRIGGERED</b>\n"
        f"Reason: {reason}\n"
        f"All positions closed. Trading halted.\n"
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )


def notify_daily_halt(daily_loss_pct: float) -> None:
    send(
        f"⛔ <b>Daily loss limit reached</b>\n"
        f"Loss: {daily_loss_pct:.1f}%\n"
        f"Trading halted until tomorrow."
    )


def notify_signal(coin: str, action: str, confidence: float, reason: str) -> None:
    """Notify when AI generates a trade signal (before execution)."""
    emoji = "📈" if action == "long" else "📉"
    send(
        f"{emoji} <b>Signal: {action.upper()} {coin}</b>\n"
        f"Confidence: {confidence:.0%}\n"
        f"<i>{reason}</i>"
    )


__all__ = [
    "_enabled",
    "send",
    "notify_trade_open",
    "notify_trade_close",
    "notify_emergency",
    "notify_daily_halt",
    "notify_signal",
]
