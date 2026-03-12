"""
trader.py — trade execution layer
Handles both paper trading and live Hyperliquid trading.
Never makes decisions — only executes what risk_manager approves.
"""
import json
import math
import traceback
from colorama import Fore, Style
from config import (TESTNET, HL_ENABLED, HL_WALLET_ADDRESS, HL_PRIVATE_KEY,
                    COINS, STOP_LOSS_PCT, TAKE_PROFIT_PCT, HL_MAX_POSITION_USD,
                    HL_LEVERAGE)
from execution.account_service import (
    get_hl_account_info as _account_service_get_hl_account_info,
    get_hl_fees as _account_service_get_hl_fees,
    get_hl_positions as _account_service_get_hl_positions,
)
from execution.execution_service import (
    cancel_open_orders as _service_cancel_open_orders,
    close_trade as _service_close_trade,
    execute_trade as _service_execute_trade,
)
from execution.hyperliquid_client import (
    _hl_post as _hl_post_client,
    get_hl_obi as _get_hl_obi,
    get_hl_price as _get_hl_price,
)
from risk_manager import RiskManager


# ── HYPERLIQUID DIRECT API ─────────────────────────────────────────────────────

def _hl_post(endpoint: str, payload: dict):
    """Compatibility wrapper for the shared Hyperliquid REST client."""
    return _hl_post_client(endpoint, payload)


def _hl_exchange():
    """Return an authenticated Exchange object for order placement."""
    import eth_account
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    base_url = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL
    account  = eth_account.Account.from_key(HL_PRIVATE_KEY)
    # Pass empty spot_meta to skip testnet spot-token fetch: the SDK tries to index
    # spot_meta["tokens"][base] but testnet's token list has mismatched indices.
    # We only trade perp futures, so spot metadata is never needed.
    return Exchange(account, base_url, account_address=HL_WALLET_ADDRESS,
                    spot_meta={"universe": [], "tokens": []})


def get_hl_price(coin: str) -> float | None:
    """Compatibility wrapper for the shared Hyperliquid price helper."""
    return _get_hl_price(coin)


def get_hl_obi(coin: str, levels: int = 10) -> float | None:
    """Compatibility wrapper for the shared Hyperliquid OBI helper."""
    return _get_hl_obi(coin, levels=levels)


def cancel_open_orders(coin: str) -> int:
    """Compatibility wrapper for execution-service order cancellation."""
    return _service_cancel_open_orders(
        coin=coin,
        hl_enabled=HL_ENABLED,
        hl_wallet_address=HL_WALLET_ADDRESS,
        coins=COINS,
        hl_post=_hl_post,
        hl_exchange_factory=_hl_exchange,
        printer=print,
        fore=Fore,
    )


def get_hl_positions() -> list:
    """Compatibility wrapper for the shared account service positions helper."""
    return _account_service_get_hl_positions()


def get_hl_account_info() -> dict:
    """Compatibility wrapper for the shared account service helper."""
    return _account_service_get_hl_account_info()


def get_hl_fees() -> dict:
    """Compatibility wrapper for the shared account service fee helper."""
    return _account_service_get_hl_fees()


# ── TRADE EXECUTION ────────────────────────────────────────────────────────────

def execute_trade(coin: str, side: str, size: float, risk_manager: RiskManager,
                  vol_regime: str = "normal",
                  kc_mid: float = 0.0,
                  ai_confidence: float | None = None) -> bool:
    from notifier import notify_trade_open
    from strategy import get_indicators_for_coin

    return _service_execute_trade(
        coin=coin,
        side=side,
        size=size,
        risk_manager=risk_manager,
        vol_regime=vol_regime,
        kc_mid=kc_mid,
        ai_confidence=ai_confidence,
        coins=COINS,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        hl_enabled=HL_ENABLED,
        testnet=TESTNET,
        hl_leverage=HL_LEVERAGE,
        hl_max_position_usd=HL_MAX_POSITION_USD,
        get_hl_price=get_hl_price,
        get_indicator_price=get_indicators_for_coin,
        hl_exchange_factory=_hl_exchange,
        notify_trade_open=notify_trade_open,
        printer=print,
        fore=Fore,
        style=Style,
    )


def close_trade(coin: str, risk_manager: RiskManager, reason: str = "manual") -> bool:
    from notifier  import notify_trade_close
    from trade_log import log_trade
    from strategy import get_indicators_for_coin

    return _service_close_trade(
        coin=coin,
        risk_manager=risk_manager,
        reason=reason,
        coins=COINS,
        hl_enabled=HL_ENABLED,
        get_hl_price=get_hl_price,
        get_indicator_price=get_indicators_for_coin,
        cancel_open_orders_fn=cancel_open_orders,
        hl_exchange_factory=_hl_exchange,
        notify_trade_close=notify_trade_close,
        log_trade=log_trade,
        printer=print,
        fore=Fore,
        style=Style,
    )


def emergency_close_all(risk_manager: RiskManager) -> None:
    """Close all open positions immediately."""
    from notifier import notify_emergency
    positions = list(risk_manager.state.get("positions", {}).keys())
    if not positions:
        print(Fore.YELLOW + "  No open positions to close.")
        risk_manager.trigger_emergency_stop()
        return
    print(Fore.RED + f"\n  ⚠  EMERGENCY CLOSE — {len(positions)} position(s)")
    for coin in positions:
        close_trade(coin, risk_manager, reason="emergency stop")
    risk_manager.trigger_emergency_stop()
    notify_emergency("Manual emergency stop triggered")
    print(Fore.RED + "  Emergency stop active. Trading halted.")


def print_positions(risk_manager: RiskManager) -> None:
    """Print all open positions with live P&L."""
    positions = risk_manager.state.get("positions", {})
    if not positions:
        print(Fore.YELLOW + "  No open positions.")
        return

    print(f"\n  {Fore.CYAN}{'─'*44}")
    print(f"  {Fore.CYAN}OPEN POSITIONS")
    for coin, pos in positions.items():
        price = get_hl_price(coin) if HL_ENABLED else None
        if price:
            live_pnl  = ((price - pos["entry_price"]) if pos["side"] == "long"
                         else (pos["entry_price"] - price)) * pos["size_units"]
            pnl_color = Fore.GREEN if live_pnl >= 0 else Fore.RED
            pnl_str   = f"{pnl_color}${live_pnl:+,.2f}{Style.RESET_ALL}"
        else:
            pnl_str = Fore.YELLOW + "N/A"

        print(f"  {coin:4}  {pos['side'].upper():5}  entry=${pos['entry_price']:,.4f}"
              f"  SL=${pos['stop_loss']:,.4f}  TP=${pos['take_profit']:,.4f}  P&L={pnl_str}")
