# Crypto Futures Scalping Bot

A sophisticated futures trading bot designed for crypto markets with advanced technical analysis, AI-powered decision making, and comprehensive risk management.

## Features

- **Multi-Strategy Support**: Mean-reversion (Keltner Channel) and trend-following (Supertrend) strategies
- **AI-Powered Analysis**: Local LLM integration with cloud fallback for market analysis
- **Advanced Risk Management**: Position sizing, stop-loss, take-profit, and drawdown protection
- **Real-time Technical Analysis**: ADX, Hurst Exponent, momentum scoring, and volatility regime detection
- **Hyperliquid Integration**: Live trading on Hyperliquid exchange (testnet/mainnet)
- **Paper Trading**: Full paper trading mode for strategy validation
- **Backtesting**: Historical performance analysis with walk-forward validation
- **Comprehensive Logging**: Structured logging with multiple output formats
- **Telegram Notifications**: Real-time trade alerts and performance updates

## Quick Start

### Prerequisites

- Python 3.8+
- pip package manager
- Hyperliquid account (for live trading)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd HLTRADING-main
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   Create a `.env` file in the project root:
   ```bash
   # Hyperliquid credentials
   HL_WALLET_ADDRESS=your_wallet_address
   HL_PRIVATE_KEY=your_private_key

   # AI configuration (optional)
   OPENROUTER_API_KEY=your_openrouter_api_key

   # Telegram notifications (optional)
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   ```

4. **Run the bot:**
   ```bash
   # Start the trading bot CLI
   python3 main.py

   # Or explicitly use the project virtualenv
   ./.venv/bin/python main.py

   # Run paper trading
   python3 paper_trader.py

   # Backtest strategies
   python3 backtester.py
   ```

## Configuration

The bot is configured through `config.py`. Key settings include:

### Strategy Configuration
```python
COINS = {
    "ETH": {
        "ticker": "ETH-USD",
        "interval": "1h",
        "period": "365d",
        "strategy_type": "supertrend",  # or "mean_reversion"
        "st_period": 10,
        "st_multiplier": 2.5,
        "stop_loss_pct": 0.008,
        "take_profit_pct": 0.05
    }
}
```

### Risk Management
```python
RISK_PER_TRADE = 0.03        # 3% of capital per trade
MAX_OPEN_POSITIONS = 6       # Maximum concurrent positions
MAX_DAILY_LOSS = 0.06        # 6% daily loss limit
MAX_DRAWDOWN = 0.15          # 15% maximum drawdown
```

### AI Configuration
```python
OLLAMA_MODEL = "qwen2.5:14b"                    # Local model
OPENROUTER_MODEL = "openai/gpt-4o-mini"         # Cloud fallback
AI_CONFIDENCE_THRESHOLD = 0.60                  # Minimum confidence to trade
```

## Strategies

### Mean-Reversion (Keltner Channel)
- **Best for**: Ranging/choppy markets
- **Entry**: Price touches Keltner Channel bands
- **Filters**: RSI zones, ADX trend strength, Hurst exponent
- **Exit**: RSI reversal, stop-loss, take-profit

### Trend-Following (Supertrend)
- **Best for**: Strong trending markets
- **Entry**: Supertrend direction flip
- **Filters**: ADX strength, volume confirmation
- **Exit**: Supertrend reversal, stop-loss, take-profit

## File Structure

```
├── config.py              # Configuration and constants
├── strategy.py            # Technical indicator calculations
├── ai_advisor.py          # AI-powered market analysis
├── risk_manager.py        # Risk management and position sizing
├── trader.py              # Live trading execution
├── paper_trader.py        # Paper trading simulation
├── backtester.py          # Historical backtesting
├── dashboard.py           # Web dashboard
├── main.py                # Main trading bot CLI / runtime entrypoint
├── validate_csv_headers.py # CSV header validation
├── tests/                 # Unit, regression, integration, and manual tests
└── requirements.txt       # Python dependencies
```

## Usage Examples

### Basic Trading
```bash
# Start the bot CLI
python3 main.py

# Start paper trading
python3 paper_trader.py

# Run backtest
python3 backtester.py --pair ETH --interval 1h --days 30
```

### Strategy Testing
```bash
# Test mean-reversion strategy
python3 backtester.py --strategy mean_reversion --pair SOL --interval 5m

# Test Supertrend strategy
python3 backtester.py --strategy supertrend --pair ETH --interval 1h
```

### Configuration Override
```bash
# Start non-interactive bot mode
python3 main.py --autostart
```

## Monitoring and Logging

### Log Files
- `arbitrage.log` - Bot/runtime logs
- `paper_trades.csv` - Paper trading history
- `opportunities.csv` - Arbitrage opportunities
- `signals.log` - Trade signals

### Telegram Notifications
Enable real-time notifications by setting up Telegram credentials in `.env`:
- Trade executions
- P&L updates
- Risk alerts
- Strategy performance

## Risk Management

The bot implements multiple layers of risk protection:

1. **Position Sizing**: Kelly fraction-based sizing with confidence scaling
2. **Stop-Loss**: Dynamic stop-loss based on ATR and strategy type
3. **Take-Profit**: Strategy-specific profit targets
4. **Daily Limits**: Maximum daily loss limits
5. **Correlation Control**: Limits on same-direction positions
6. **Market Regime Filters**: ADX and Hurst-based strategy selection

## Development

### Running Tests
```bash
# Run automated tests (tests/manual is excluded)
python3 -m unittest discover -s tests -t .

# Run specific test file
python3 -m unittest tests.regression.test_strategy

# Run with coverage
coverage run -m unittest discover -s tests -t .
coverage report

# Run manual/exploratory backtester harness
python3 tests/manual/test_enhanced_backtester.py
```

`tests/manual/` contains exploratory/manual harnesses. These are excluded from normal automated discovery and may write output files to the current working directory.

### Adding New Strategies
1. Add strategy logic to `strategy.py`
2. Update `config.py` with strategy parameters
3. Add risk management rules to `risk_manager.py`
4. Create automated tests under `tests/regression/` or `tests/unit/`

### Adding New Exchanges
1. Install exchange SDK
2. Add exchange configuration to `config.py`
3. Implement API wrapper in `trader.py`
4. Add tests for exchange integration

## Security

### Credential Management
- Never commit `.env` files to version control
- Use environment variables for sensitive data
- Regularly rotate API keys
- Enable 2FA on exchange accounts

### Code Security
- Input validation for all external data
- Rate limiting for API calls
- Error handling for network failures
- Secure credential storage

## Troubleshooting

### Common Issues

**"No arbitrage opportunities found"**
- Check strategy/risk filters and market regime gates
- Verify exchange connectivity and data downloads
- Confirm enabled coins/configuration are correct

**"ImportError: No module named 'ccxt'"**
- Run `pip install -r requirements.txt`
- Check Python environment

**"Connection timeout"**
- Check internet connection
- Verify exchange API endpoints
- Check rate limits

**"Insufficient balance"**
- Check account funding
- Verify position sizing calculations
- Check leverage settings

### Debug Mode
Enable debug logging by setting environment variable:
```bash
export DEBUG=1
python3 main.py
```

## Performance Optimization

### Hardware Requirements
- **Minimum**: 2 CPU cores, 4GB RAM
- **Recommended**: 4+ CPU cores, 8GB+ RAM
- **Storage**: SSD for faster data access

### Network Optimization
- Use low-latency connections
- Consider colocation for high-frequency strategies
- Monitor API rate limits

### Strategy Optimization
- Regular backtesting and parameter tuning
- Walk-forward validation for parameter stability
- Monitor strategy performance metrics

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This software is for educational and research purposes only. Trading involves substantial risk and is not suitable for all investors. Users are responsible for their own trading decisions and should consult with financial advisors before engaging in live trading.

The authors are not responsible for any losses incurred through the use of this software.
