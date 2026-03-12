#!/usr/bin/env python3
"""
config_secure.py — Secure configuration with encrypted credential storage
Enhanced version of config.py with security-first credential management
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from hltrading.config.secure_config import load_secure_credentials, SecureConfig
from input_validation import InputValidator, ValidationError

# Load environment variables first (for CONFIG_PASSWORD)
load_dotenv()

# Set up logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load secure credentials
try:
    credentials = load_secure_credentials()
    logger.info("✅ Loaded credentials from secure configuration")
except Exception as e:
    logger.warning(f"⚠️  Failed to load secure credentials: {e}")
    credentials = {}


def get_credential(key: str, fallback_env: str = None) -> str:
    """Get credential from secure config or environment variable"""
    if key in credentials:
        return credentials[key]

    env_key = fallback_env or key
    value = os.environ.get(env_key)
    if value:
        logger.info(f"Using {env_key} from environment variable")
        return value

    logger.error(f"❌ Required credential {key} not found in secure config or environment")
    return ""


# ─── HYPERLIQUID CREDENTIALS (SECURE) ─────────────────────────────────────────
HL_WALLET_ADDRESS = get_credential("HL_WALLET_ADDRESS")
HL_PRIVATE_KEY = get_credential("HL_PRIVATE_KEY")

# Validate credentials
if not HL_WALLET_ADDRESS or not HL_PRIVATE_KEY:
    logger.error("❌ Hyperliquid credentials are required for trading")
    if not os.environ.get("CONFIG_PASSWORD"):
        logger.error("💡 Set CONFIG_PASSWORD environment variable to access encrypted credentials")
        logger.error("💡 Run: python3 setup_secure_config.py to set up secure configuration")
    sys.exit(1)

# ─── AI CREDENTIALS (SECURE) ──────────────────────────────────────────────────
OPENROUTER_API_KEY = get_credential("OPENROUTER_API_KEY")

# ─── TELEGRAM CREDENTIALS (SECURE) ────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = get_credential("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_credential("TELEGRAM_CHAT_ID")

# ─── COINS ────────────────────────────────────────────────────────────────────
# Per-coin timeframes: ETH/BTC use 1h (yfinance supports up to 730d),
# SOL uses 5m scalping (yfinance caps 5m data at 60d).
#
# strategy_type controls which entry/exit logic each coin uses:
#   "mean_reversion" — KC band touch + RSI threshold + MA trend filter
#   "supertrend"     — ATR-based Supertrend flip; trend-following, not fading
#
# ETH/BTC → "supertrend": walk-forward validation showed ETH has been in a
# trending regime (pf=0.48 in holdout) — fading the trend is wrong. Supertrend
# matches the current regime and lets us enable BTC at the same time.
#
# SOL → "mean_reversion": walk-forward holdout pf=1.85, still profitable.
# Mean-reversion edge on 5m SOL is confirmed. Keep unchanged.
#
# Supertrend SL/TP are wider than mean-reversion: trend trades need room to
# breathe. Main exit is the ST flip (trend reversal), SL is safety-net only.
COINS = {
    # ETH — Supertrend trend-following on 1h.
    # Optimizer rank-1 + walk-forward ROBUST: st(10,2.5), sl=0.8%.
    # All top-5 converged on st_mult=2.5 and sl=0.8% — strong consensus.
    # Main exit is the ST flip (trend reversal); SL is safety-net only.
    "ETH": {"ticker": "ETH-USD", "interval": "1h", "period": "365d",
            "hl_symbol": "ETH", "hl_size": 0.01,  "sz_decimals": 4,  "enabled": True,
            "strategy_type": "supertrend",
            "st_period": 10, "st_multiplier": 2.5,
            "stop_loss_pct": 0.008,
            "max_bars_in_trade": 168},

    # BTC — Supertrend trend-following on 1h.
    # Optimizer rank-1 + walk-forward agreed: st(14,2.5), sl=0.8%.
    # Longer period than ETH (14 vs 10) = slower, cleaner BTC trend filter.
    # Walk-forward showed 34% pf decay in holdout — keep position sizing at
    # half of ETH until it proves itself live.
    "BTC": {"ticker": "BTC-USD", "interval": "1h", "period": "365d",
            "hl_symbol": "BTC", "hl_size": 0.001, "enabled": False,
            "strategy_type": "supertrend",
            "st_period": 14, "st_multiplier": 2.5,
            "stop_loss_pct": 0.008,
            "max_bars_in_trade": 168},

    # SOL — KC mean-reversion scalping on 5m.
    "SOL": {"ticker": "SOL-USD", "interval": "5m", "period": "60d",
            "hl_symbol": "SOL", "hl_size": 0.2,   "sz_decimals": 2,  "enabled": True,
            "strategy_type": "mean_reversion",
            "ma_trend_filter": True,
            "rsi_oversold": 40, "rsi_overbought": 60,
            "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
            "max_bars_in_trade": 36},

    # DOGE — KC mean-reversion scalping on 5m.
    "DOGE": {"ticker": "DOGE-USD", "interval": "5m", "period": "7d",
             "hl_symbol": "DOGE", "hl_size": 500,  "enabled": True,
             "sz_decimals": 0,
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,
             "ma_trend_filter": True,
             "rsi_oversold": 45, "rsi_overbought": 55,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # ─── CANDIDATE COINS — disabled pending optimizer validation ──────────────────
    "XRP": {"ticker": "XRP-USD",  "interval": "5m", "period": "60d",
             "hl_symbol": "XRP",  "hl_size": 5,    "sz_decimals": 1,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "WIF": {"ticker": "WIF-USD",  "interval": "5m", "period": "30d",
             "hl_symbol": "WIF",  "hl_size": 7,    "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "kc_scalar": 1.5,
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "BONK": {"ticker": "BONK-USD", "interval": "5m", "period": "30d",
             "hl_symbol": "BONK", "hl_size": 500,  "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "ADA": {"ticker": "ADA-USD",  "interval": "5m", "period": "60d",
             "hl_symbol": "ADA",  "hl_size": 15,   "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "AVAX": {"ticker": "AVAX-USD", "interval": "5m", "period": "60d",
             "hl_symbol": "AVAX", "hl_size": 0.4,  "sz_decimals": 2,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "LINK": {"ticker": "LINK-USD", "interval": "5m", "period": "60d",
             "hl_symbol": "LINK", "hl_size": 0.8,  "sz_decimals": 2,  "enabled": True,
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,
             "ma_trend_filter": True,
             "rsi_oversold": 40, "rsi_overbought": 60,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "LTC": {"ticker": "LTC-USD",  "interval": "5m", "period": "60d",
             "hl_symbol": "LTC",  "hl_size": 0.12, "sz_decimals": 3,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    "SHIB": {"ticker": "SHIB-USD", "interval": "5m", "period": "7d",
             "hl_symbol": "SHIB", "hl_size": 1000, "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # ─── SUPERTREND TREND-FOLLOWING — 1h ──────────────────────────────────────
    "SOL_ST": {"ticker": "SOL-USD", "interval": "1h", "period": "365d",
               "hl_symbol": "SOL",  "hl_size": 0.2,  "sz_decimals": 2,  "enabled": True,
               "strategy_type": "supertrend",
               "st_period": 14, "st_multiplier": 2.0,
               "stop_loss_pct": 0.008,
               "take_profit_pct": 0.05,
               "max_bars_in_trade": 168},

    "AVAX_ST": {"ticker": "AVAX-USD", "interval": "1h", "period": "365d",
                "hl_symbol": "AVAX", "hl_size": 0.4,  "sz_decimals": 2,  "enabled": True,
                "strategy_type": "supertrend",
                "st_period": 7, "st_multiplier": 2.5,
                "stop_loss_pct": 0.008,
                "take_profit_pct": 0.05,
                "max_bars_in_trade": 168},

    "LINK_ST": {"ticker": "LINK-USD", "interval": "1h", "period": "365d",
                "hl_symbol": "LINK", "hl_size": 0.8,  "sz_decimals": 2,  "enabled": False,
                "strategy_type": "supertrend",
                "st_period": 7, "st_multiplier": 3.5,
                "stop_loss_pct": 0.008,
                "take_profit_pct": 0.05,
                "max_bars_in_trade": 168},
}

# ─── STRATEGY PARAMETERS ──────────────────────────────────────────────────────
KC_PERIOD = 20
KC_SCALAR = 1.0
MA_FAST = 9
MA_SLOW = 21
MA_TREND = 50
RSI_PERIOD = 14

RSI_OVERSOLD = 45
RSI_OVERBOUGHT = 55

# ─── AI ADVISOR ───────────────────────────────────────────────────────────────
OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_URL = "http://localhost:11434/api/chat"
OPENROUTER_MODEL = "openai/gpt-4o-mini"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_CONFIDENCE_THRESHOLD = 0.60
AI_LOCAL_FALLBACK_THRESHOLD = 0.50

# ─── REGIME DETECTION ─────────────────────────────────────────────────────────
ADX_MR_MAX = 30
HURST_MR_MAX = 0.55

# ─── GATE / FILTER SWITCHES ───────────────────────────────────────────────────
AI_ENABLED = False
ENTRY_QUALITY_GATE = False
HURST_GATE = True

# ─── RISK MANAGEMENT ──────────────────────────────────────────────────────────
PAPER_CAPITAL = 672.0
RISK_PER_TRADE = 0.03
STOP_LOSS_PCT = 0.004
TAKE_PROFIT_PCT = 0.008
MAX_OPEN_POSITIONS = 6
MAX_POSITIONS_SIDE = 3
MAX_DAILY_LOSS = 0.06
MAX_DRAWDOWN = 0.15
HL_MAX_POSITION_USD = 200.0
HL_LEVERAGE = 3
HL_FEE_RATE = 0.00045

# ─── EDGE / KELLY FILTERS ─────────────────────────────────────────────────────
MIN_EDGE = 0.02
KELLY_FRACTION = 0.50
MIN_ENTRY_QUALITY = 0.05
OBI_GATE = 0.40
VOL_MIN_RATIO = 0.5

# ─── TRADING MODE ─────────────────────────────────────────────────────────────
TESTNET = True
HL_ENABLED = True

# ─── FILES ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "paper_state.json"
TRADES_FILE = BASE_DIR / "paper_trades.csv"
SIGNALS_LOG = BASE_DIR / "signals.log"
BEST_CONFIGS_FILE = BASE_DIR / "best_configs.json"


def validate_security():
    """Validate that secure configuration is properly set up"""
    issues = []

    if not os.environ.get("CONFIG_PASSWORD"):
        issues.append("CONFIG_PASSWORD environment variable not set")

    secure_files = [".config_salt", ".config_key", "secure_config.json"]
    for file in secure_files:
        if not (BASE_DIR / file).exists():
            issues.append(f"Secure config file missing: {file}")

    for file in secure_files:
        file_path = BASE_DIR / file
        if file_path.exists():
            import stat
            mode = file_path.stat().st_mode
            if mode & stat.S_IRWXG or mode & stat.S_IRWXO:
                issues.append(f"File permissions too open: {file} (should be 600)")

    if issues:
        logger.error("❌ Security validation failed:")
        for issue in issues:
            logger.error(f"  - {issue}")
        logger.error("💡 Run: python3 setup_secure_config.py to fix security issues")
        return False

    logger.info("✅ Security validation passed")
    return True


if __name__ != "__main__":
    validate_security()
