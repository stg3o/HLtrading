import ccxt
import time
import csv
import os
from datetime import datetime
from colorama import Fore, Style, init

init(autoreset=True)

exchanges = {
    'kucoin': ccxt.kucoin(),
    'gate': ccxt.gate(),
    'mexc': ccxt.mexc(),
    'bybit': ccxt.bybit(),
}

PAIRS      = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
TAKER_FEE  = 0.001   # 0.1% per leg — typical taker fee
MIN_NET_SPREAD = 0.3  # minimum net spread after fees (%)
LOG_FILE   = 'opportunities.csv'

# Create CSV file with headers if it doesn't exist
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'pair', 'buy_exchange', 'buy_price', 'sell_exchange', 'sell_price', 'gross_spread_pct', 'net_spread_pct'])

def log_opportunity(pair, buy_ex, buy_price, sell_ex, sell_price, gross_spread, net_spread):
    with open(LOG_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            pair, buy_ex, buy_price, sell_ex, sell_price,
            round(gross_spread, 4), round(net_spread, 4)
        ])

def get_prices():
    prices = {}
    for name, exchange in exchanges.items():
        prices[name] = {}
        for pair in PAIRS:
            try:
                ticker = exchange.fetch_ticker(pair)
                ask = ticker.get('ask')
                bid = ticker.get('bid')
                # fall back to last if bid/ask unavailable
                if ask is None: ask = ticker['last']
                if bid is None: bid = ticker['last']
                prices[name][pair] = {'ask': ask, 'bid': bid}
            except Exception as e:
                prices[name][pair] = None
    return prices

def find_arbitrage(prices):
    opportunities = []
    fee_cost_pct = TAKER_FEE * 2 * 100  # buy leg + sell leg
    for pair in PAIRS:
        pair_prices = {ex: prices[ex][pair] for ex in prices if prices[ex][pair]}
        if len(pair_prices) < 2:
            continue
        # buy at ask on cheapest, sell at bid on most expensive
        min_ex = min(pair_prices, key=lambda ex: pair_prices[ex]['ask'])
        max_ex = max(pair_prices, key=lambda ex: pair_prices[ex]['bid'])
        if min_ex == max_ex:
            continue
        buy_price  = pair_prices[min_ex]['ask']
        sell_price = pair_prices[max_ex]['bid']
        gross_spread = ((sell_price - buy_price) / buy_price) * 100
        net_spread   = gross_spread - fee_cost_pct
        if net_spread >= MIN_NET_SPREAD:
            opportunities.append((pair, min_ex, buy_price, max_ex, sell_price, gross_spread, net_spread))
    return opportunities

print(Fore.CYAN + "🚀 Crypto Arbitrage Monitor Started")
print(Fore.YELLOW + f"Logging opportunities to: {LOG_FILE}\n")

while True:
    try:
        print(Fore.WHITE + f"Scanning... {time.strftime('%H:%M:%S')}")
        prices = get_prices()
        opportunities = find_arbitrage(prices)

        if opportunities:
            for pair, buy_ex, buy_price, sell_ex, sell_price, gross_spread, net_spread in opportunities:
                print(Fore.GREEN + f"💰 {pair} | Buy {buy_ex} ask: ${buy_price:,.2f} | Sell {sell_ex} bid: ${sell_price:,.2f} | Gross: {gross_spread:.2f}% | Net: {net_spread:.2f}%")
                log_opportunity(pair, buy_ex, buy_price, sell_ex, sell_price, gross_spread, net_spread)
        else:
            print(Fore.RED + "No opportunities found\n")

        time.sleep(10)

    except KeyboardInterrupt:
        print(Fore.CYAN + f"\nStopped. Data saved to {LOG_FILE}")
        break
    except Exception as e:
        print(Fore.RED + f"Error: {e}")
        time.sleep(10)