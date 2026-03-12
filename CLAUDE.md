# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the main trading bot
python main.py

# Run the backtester
python backtester.py

# Run the optimizer
python optimizer.py
```

### Running a single script interactively
The project has multiple entry points:
- **main.py** – main trading bot interface with 12+ menu options for various operations
- **backtester.py** – strategy backtesting capabilities
- **optimizer.py** – strategy optimization using grid search

If you need to run a quick smoke test for any script, just execute the command above. There are no automated tests in the repo, so the best way to verify changes is to run the script and inspect console output or generated files.

## High‑level architecture

The repo implements a comprehensive cryptocurrency trading system with Hyperliquid integration, AI-powered decision making, and advanced risk management.

1. **Main Trading Bot (`main.py`)**
   * Core interface with 12+ menu options for various trading operations
   * Multi-threaded operation (bot loop + SL/TP monitor)
   * Real-time position monitoring and SL/TP tracking every 15 seconds
   * Telegram integration for remote control and notifications

2. **Trading Components**
   * **Strategy Engine** (`strategy.py`) – Implements multiple trading strategies including mean-reversion, supertrend, and AI-powered decision making
   * **Risk Manager** (`risk_manager.py`) – Manages position sizing, stop-losses, take-profits, and capital allocation
   * **Trader Interface** (`trader.py`) – Handles actual trading operations with Hyperliquid API
   * **Paper Trader** (`paper_trader.py`) – Simulates trades for testing without real funds

3. **AI Integration**
   * AI-powered decision making using Ollama/OpenRouter APIs
   * Trend bias analysis and confidence scoring
   * Brier score for AI calibration

4. **Backtesting & Optimization**
   * Backtester (`backtester.py`) – Comprehensive backtesting with multiple coin support
   * Optimizer (`optimizer.py`) – Grid search optimization of strategy parameters
   * Performance reporting with statistical metrics

5. **Monitoring & Dashboard**
   * Web dashboard via Flask for real-time monitoring
   * Trade logging and performance tracking
   * Emergency stop functionality

## Important files to inspect

- `main.py` – main trading bot interface with menu-driven operations
- `strategy.py` – strategy implementation including AI decision making
- `trader.py` – Hyperliquid API integration for live trading
- `paper_trader.py` – paper trading simulation
- `risk_manager.py` – risk management and position sizing controls
- `backtester.py` – backtesting framework with performance metrics
- `optimizer.py` – strategy optimization using grid search
- `dashboard.py` – web dashboard implementation
- `config.py` – configuration settings for trading parameters

## Editing guidelines for AI agents

- **Preserve core constants**: Do not change critical trading parameters unless you intentionally want to modify the behavior.
- **API security**: Never modify or expose API keys in the codebase.
- **Risk controls**: Maintain all safety mechanisms including SL/TP, drawdown limits, and capital allocation.
- **AI integration**: Keep AI decision making logic intact, ensuring proper API calls and error handling.
- **Thread safety**: Be careful when modifying multi-threaded components like the SL/TP monitor.

## Useful checks after edits

1. Run `python main.py` – verify the menu interface works correctly
2. Test backtesting with `python backtester.py` – confirm strategy execution without errors
3. Verify optimizer functionality with `python optimizer.py` – ensure parameter optimization works
4. Check dashboard functionality by running the web server and accessing the interface

## Notes

- This is a sophisticated trading system that interfaces with Hyperliquid exchange
- All trading operations are subject to strict risk management controls
- AI decision making requires proper API configuration for Ollama/OpenRouter
- The system supports both paper trading and live trading modes
- Avoid adding long-running services or committing any secret keys.
- If you need additional tooling (e.g., linting), you can add it manually.

---
If you need more detailed examples (e.g., how to modify specific strategies, or how to set up AI APIs), let me know which section you'd like to expand.