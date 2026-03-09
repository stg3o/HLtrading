#!/usr/bin/env python3
"""
Hyperliquid Testnet Trader
Connects our Keltner strategy signals to Hyperliquid futures
"""

import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
import eth_account
from eth_account.signers.local import LocalAccount

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
TESTNET = True  # ← change to False for mainnet
BASE_URL = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL

WALLET_ADDRESS = os.environ.get("HL_WALLET_ADDRESS")
PRIVATE_KEY    = os.environ.get("HL_PRIVATE_KEY")

# Trading config
SYMBOL   = "ETH"
SIZE_USD = 50       # trade size in USD

# ─────────────────────────────────────────────
#  CONNECTION
# ─────────────────────────────────────────────

def connect():
    account: LocalAccount = eth_account.Account.from_key(PRIVATE_KEY)
    info     = Info(BASE_URL, skip_ws=True)
    exchange = Exchange(account, BASE_URL, account_address=WALLET_ADDRESS)
    return info, exchange, account

# ─────────────────────────────────────────────
#  ACCOUNT INFO
# ─────────────────────────────────────────────

def get_account_info():
    info, exchange, account = connect()
    state = info.user_state(WALLET_ADDRESS.lower())
    print(f"  Wallet: {WALLET_ADDRESS}")
    print(f"  Lower:  {WALLET_ADDRESS.lower()}")
    print(f"  Length: {len(WALLET_ADDRESS)}")

    margin     = float(state["marginSummary"]["accountValue"])
    unrealized = float(state["marginSummary"]["totalUnrealizedPnl"])
    positions  = state.get("assetPositions", [])

    print(f"\n  Account Value : ${margin:,.2f}")
    print(f"  Unrealized PnL: ${unrealized:,.2f}")
    print(f"  Positions     : {len(positions)}")

    for p in positions:
        pos = p["position"]
        print(f"    {pos['coin']} | Size: {pos['szi']} | "
              f"Entry: ${float(pos['entryPx']):,.2f} | "
              f"PnL: ${float(pos['unrealizedPnl']):,.2f}")

    return state

# ─────────────────────────────────────────────
#  PLACE ORDER
# ─────────────────────────────────────────────

def place_order(side="buy", size=None, price=None):
    info, exchange, account = connect()

    # Get current price if not provided
    if price is None:
        mids = info.all_mids()
        price = float(mids[SYMBOL])

    if size is None:
        size = round(SIZE_USD / price, 4)

    is_buy = side.lower() == "buy"

    print(f"\n  Placing {side.upper()} order...")
    print(f"  Symbol : {SYMBOL}")
    print(f"  Size   : {size} ETH")
    print(f"  Price  : ${price:,.2f}")

    result = exchange.market_open(
        SYMBOL,
        is_buy,
        size,
        slippage=0.01
    )

    print(f"  Result : {result}")
    return result

# ─────────────────────────────────────────────
#  CLOSE POSITION
# ─────────────────────────────────────────────

def close_position():
    info, exchange, account = connect()
    state = info.user_state(WALLET_ADDRESS.lower())

    for p in state.get("assetPositions", []):
        pos = p["position"]
        if pos["coin"] == SYMBOL:
            size    = abs(float(pos["szi"]))
            is_buy  = float(pos["szi"]) < 0  # close short = buy

            print(f"\n  Closing {SYMBOL} position (size={size})...")
            result = exchange.market_close(SYMBOL, slippage=0.01)
            print(f"  Result: {result}")
            return result

    print("  No open position to close")

# ─────────────────────────────────────────────
#  MAIN TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "─"*50)
    print("  HYPERLIQUID TESTNET CONNECTION TEST")
    print("─"*50)

    print("\n  Testing connection...")
    get_account_info()

    print("\n  Getting ETH price...")
    info, _, _ = connect()
    mids = info.all_mids()
    eth_price = float(mids["ETH"])
    print(f"  ETH price: ${eth_price:,.2f}")

    print("\n  Connection successful! ✅")
    print("  Ready to trade on testnet\n")
