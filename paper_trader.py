#!/usr/bin/env python3
"""
ETH_4H Keltner Strategy — Paper Trader + Hyperliquid Testnet
"""
import json, os, csv
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
import pandas as pd
import pandas_ta as ta
from colorama import init, Fore, Style
init(autoreset=True)

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
TICKER        = "ETH-USD"
INTERVAL      = "4h"
PERIOD        = "30d"
PAPER_CAPITAL = 50.0

KC_PERIOD  = 20
KC_SCALAR  = 2
MA_FAST    = 9
MA_SLOW    = 21
RSI_PERIOD = 14

# Hyperliquid config
TESTNET        = True
HL_SYMBOL      = "ETH"
HL_SIZE_ETH    = 0.01      # small test size
HL_ENABLED     = True      # set False to disable live trading

WALLET_ADDRESS = os.environ.get("HL_WALLET_ADDRESS", "").lower()
PRIVATE_KEY    = os.environ.get("HL_PRIVATE_KEY", "")
BASE_URL       = constants.TESTNET_API_URL if TESTNET else constants.MAINNET_API_URL

SCRIPT_DIR  = Path(__file__).parent
TRADES_FILE = SCRIPT_DIR / "paper_trades.csv"
STATE_FILE  = SCRIPT_DIR / "paper_state.json"

# ─────────────────────────────────────────────
#  HYPERLIQUID
# ─────────────────────────────────────────────
def hl_connect():
    account  = eth_account.Account.from_key(PRIVATE_KEY)
    exchange = Exchange(account, BASE_URL, account_address=WALLET_ADDRESS)
    return exchange

def hl_buy():
    try:
        exchange = hl_connect()
        result   = exchange.market_open(HL_SYMBOL, True, HL_SIZE_ETH, slippage=0.01)
        if result["status"] == "ok":
            filled = result["response"]["data"]["statuses"][0]["filled"]
            print(Fore.GREEN + f"  🔗 HL BUY filled: {filled['totalSz']} ETH @ ${float(filled['avgPx']):,.2f}")
            return True
        else:
            print(Fore.RED + f"  HL BUY failed: {result}")
            return False
    except Exception as e:
        print(Fore.RED + f"  HL BUY error: {e}")
        return False

def hl_sell():
    try:
        exchange = hl_connect()
        result   = exchange.market_open(HL_SYMBOL, False, HL_SIZE_ETH, slippage=0.01)
        if result["status"] == "ok":
            filled = result["response"]["data"]["statuses"][0]["filled"]
            print(Fore.GREEN + f"  🔗 HL SELL filled: {filled['totalSz']} ETH @ ${float(filled['avgPx']):,.2f}")
            return True
        else:
            print(Fore.RED + f"  HL SELL failed: {result}")
            return False
    except Exception as e:
        print(Fore.RED + f"  HL SELL error: {e}")
        return False

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "in_position":  False,
        "entry_price":  0.0,
        "entry_time":   "",
        "stop_price":   0.0,
        "shares":       0.0,
        "capital":      PAPER_CAPITAL,
        "total_trades": 0,
        "wins":         0,
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────
def log_trade(action, price, pnl=None, pnl_pct=None, reason=""):
    file_exists = TRADES_FILE.exists()
    with open(TRADES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp","action","price","pnl","pnl_pct","reason","capital_after"])
        state = load_state()
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            action, f"{price:.2f}",
            f"{pnl:.2f}" if pnl is not None else "",
            f"{pnl_pct:.2f}" if pnl_pct is not None else "",
            reason,
            f"{state['capital']:.2f}"
        ])

# ─────────────────────────────────────────────
#  DATA
# ─────────────────────────────────────────────
def get_data():
    df = yf.download(TICKER, interval=INTERVAL, period=PERIOD,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.dropna(inplace=True)
    close          = df["Close"]
    ema_mid        = ta.ema(close, length=KC_PERIOD)
    atr            = ta.atr(df["High"], df["Low"], close, length=KC_PERIOD)
    df["KC_upper"] = ema_mid + KC_SCALAR * atr
    df["KC_lower"] = ema_mid - KC_SCALAR * atr
    df["MA_fast"]  = ta.ema(close, length=MA_FAST)
    df["MA_slow"]  = ta.ema(close, length=MA_SLOW)
    df["RSI"]      = ta.rsi(close, length=RSI_PERIOD)
    df.dropna(inplace=True)
    return df

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
def run_check():
    print(f"\n{Fore.CYAN}{'─'*50}")
    print(f"  ETH_4H TRADER {'(TESTNET)' if TESTNET else '(MAINNET)'}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'─'*50}{Style.RESET_ALL}\n")

    df    = get_data()
    row   = df.iloc[-1]
    price = float(row["Close"])
    rsi   = float(row["RSI"])
    kc_l  = float(row["KC_lower"])

    state = load_state()
    save_state(state)

    print(f"  Price    : ${price:,.2f}")
    print(f"  RSI      : {rsi:.1f}")
    print(f"  KC Lower : ${kc_l:,.2f}")
    print(f"  Capital  : ${state['capital']:,.2f}")
    print(f"  Position : {'OPEN @ $' + str(round(state['entry_price'],2)) if state['in_position'] else 'None'}\n")

    # ── EXIT ──
    if state["in_position"]:
        exit_reason = None
        if price <= state["stop_price"]:
            exit_reason = "Stop loss hit"
        elif rsi > 70:
            exit_reason = "RSI overbought exit"

        if exit_reason:
            pnl     = (price - state["entry_price"]) * state["shares"]
            pnl_pct = (price - state["entry_price"]) / state["entry_price"] * 100
            state["capital"] += state["shares"] * price
            state["total_trades"] += 1
            if pnl > 0:
                state["wins"] += 1
            state["in_position"] = False
            state["shares"]      = 0.0
            log_trade("SELL", price, pnl, pnl_pct, exit_reason)
            save_state(state)

            color = Fore.GREEN if pnl > 0 else Fore.RED
            print(color + f"  🔴 SELL @ ${price:,.2f}  P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
            print(color + f"  Reason: {exit_reason}")

            if HL_ENABLED:
                hl_sell()
            return

    # ── ENTRY ──
    if not state["in_position"]:
        entry = price < kc_l and 30 < rsi < 50
        if entry and state["capital"] > 0:
            shares               = (state["capital"] * 0.95) / price
            state["shares"]      = shares
            state["capital"]    -= shares * price
            state["entry_price"] = price
            state["stop_price"]  = price * 0.98
            state["in_position"] = True
            state["entry_time"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
            log_trade("BUY", price, reason="KC lower + RSI 30-50")
            save_state(state)

            print(Fore.GREEN + f"  🟢 BUY  @ ${price:,.2f}")
            print(Fore.GREEN + f"  Stop   : ${state['stop_price']:,.2f}")
            print(Fore.GREEN + f"  Shares : {shares:.6f} ETH")

            if HL_ENABLED:
                hl_buy()
        else:
            print(Fore.YELLOW + "  No signal — watching…")
            if price < kc_l:
                print(Fore.YELLOW + f"  (Below KC but RSI={rsi:.1f} not in 30-50 range)")

    # ── SUMMARY ──
    win_rate    = (state["wins"] / state["total_trades"] * 100) if state["total_trades"] > 0 else 0
    total_value = state["capital"] + (state["shares"] * price if state["in_position"] else 0)
    pnl_total   = total_value - PAPER_CAPITAL
    print(f"\n  {'─'*40}")
    print(f"  Total trades : {state['total_trades']}")
    print(f"  Win rate     : {win_rate:.1f}%")
    c = Fore.GREEN if pnl_total >= 0 else Fore.RED
    print(c + f"  Total P&L    : ${pnl_total:+,.2f} ({pnl_total/PAPER_CAPITAL*100:+.1f}%)")

if __name__ == "__main__":
    run_check()
