## Purpose
Short, actionable guidance for AI coding agents working on this repo: small crypto tooling containing a realtime arbitrage monitor and a strategy backtester.

## Big picture
- Two main entry points: [arbitrage.py](arbitrage.py#L1-L200) (real-time price monitor using `ccxt`) and [strategy.py](strategy.py#L1-L400) (offline/backtest using `yfinance`, `pandas_ta`, `backtrader`).
- Data flow: `arbitrage.py` fetches `ticker['last']` across exchanges and appends detected spreads to `opportunities.csv` (created at runtime). `strategy.py` downloads OHLCV data, computes indicators, and runs `backtrader` `Cerebro` backtests.

## Key files to inspect
- [arbitrage.py](arbitrage.py#L1-L200): constants at top (`PAIRS`, `MIN_SPREAD`, `LOG_FILE`), `get_prices()` and `find_arbitrage()` implement core logic. See CSV header creation and `log_opportunity()` for persistence.
- [strategy.py](strategy.py#L1-L400): interactive prompt, indicator construction (`EMA`, `KC`, `RSI`) and `KeltnerRSIStrategy` implemented with `backtrader`.
- `opportunities.csv`: runtime log target.

## Run / debug steps (reproducible locally)
- Create venv and install runtime deps (example):
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install ccxt colorama yfinance pandas pandas_ta backtrader matplotlib`
- Run the monitor: `python arbitrage.py` — it prints scans and appends CSV rows to `opportunities.csv`.
- Run the backtester: `python strategy.py` — interactive prompts ask for pair/timeframe and then plot results.

## Project-specific conventions & patterns
- Constants at module top control behavior: change `PAIRS` or `MIN_SPREAD` in [arbitrage.py](arbitrage.py#L1-L40) rather than sprinkling values.
- Null-safe fetching: `get_prices()` sets `None` on exception — agents should preserve that contract when refactoring (logic in `find_arbitrage()` expects missing values).
- Logging/persistence: CSV is created if missing with a fixed header (see file creation block in [arbitrage.py](arbitrage.py#L14-L22)). Keep CSV schema stable when adding fields.
- Interactive UX: `strategy.py` uses blocking `input()` prompts and immediate plotting; non-interactive automation should construct `tf` and `ticker` programmatically instead of altering prompts.

## Integration points & external dependencies
- Exchange data: `ccxt` exchange instances are created without explicit API keys in this repo; by default public endpoints are used. If adding authenticated calls, use env vars or a separate secrets file and do not commit keys.
- Market data: `strategy.py` uses `yfinance` (public), `pandas_ta` for indicators, and `backtrader` for simulation.

## Editing guidance for AI agents (do this first)
- Preserve exported constants and CSV header format unless migrating data with a scripted migration.
- When changing price-fetch logic, keep the return shape of `get_prices()` as a nested mapping: {exchange: {pair: price_or_None}}.
- For unit-testability: extract network calls behind small adapters (e.g., `fetch_ticker_for(exchange, pair)`) so tests can inject deterministic data.

## Minimal examples to reference
- Arbitrage spread calc (from `find_arbitrage()`): compute spread as `((high - low) / low) * 100` and compare to `MIN_SPREAD` ([arbitrage.py](arbitrage.py#L40-L80)).
- Backtester entry: convert `pandas.DataFrame` into `backtrader` feed with `bt.feeds.PandasData(dataname=df)` and run `cerebro.run()` ([strategy.py](strategy.py#L200-L300)).

## Useful checks an agent should run after edits
- Run `python arbitrage.py` for a quick smoke test; confirm console output and that a new row is appended to `opportunities.csv`.
- Run `python strategy.py` interactively for the selected pair/timeframe to validate no runtime exceptions in indicator calculation.

## Notes and constraints
- There are no tests or CI in the repo — prefer small, verifiable edits and add targeted unit tests if you expand functionality.
- Do not add long-running background services or secret keys to the repo.

---
If any part is unclear or you want me to expand examples (for tests, adapters, or a requirements file), tell me which section to iterate on.
