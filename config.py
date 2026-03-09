"""
config.py — single source of truth for all settings
Edit this file to change bot behaviour. Do not hardcode values elsewhere.
"""
import os
from dotenv import load_dotenv
load_dotenv()

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
            "hl_symbol": "ETH", "hl_size": 0.01,  "enabled": True,
            "strategy_type": "supertrend",
            "st_period": 10, "st_multiplier": 2.5,
            "stop_loss_pct": 0.008,
            "max_bars_in_trade": 168},   # 7 days max — let the trend run

    # BTC — Supertrend trend-following on 1h.
    # Optimizer rank-1 + walk-forward agreed: st(14,2.5), sl=0.8%.
    # Longer period than ETH (14 vs 10) = slower, cleaner BTC trend filter.
    # Walk-forward showed 34% pf decay in holdout — keep position sizing at
    # half of ETH until it proves itself live.
    "BTC": {"ticker": "BTC-USD", "interval": "1h", "period": "365d",
            "hl_symbol": "BTC", "hl_size": 0.001, "enabled": False,  # DISABLED: WR=17%, PF=0.90, drawdown=33.7% — losing strategy
            "strategy_type": "supertrend",
            "st_period": 14, "st_multiplier": 2.5,
            "stop_loss_pct": 0.008,
            "max_bars_in_trade": 168},

    # SOL — KC mean-reversion scalping on 5m.
    # Problem: prior optimizer run produced only 13 trades over 60d — not
    # enough for any statistical conclusion. Root cause: MA_filter + RSI 40/60
    # + hurst≤0.45 are too selective combined.
    # Changes vs prior run:
    #   sl: 0.004 → 0.002  (optimizer confirmed 0.2% is best-scoring SL)
    #   tp: 0.008 → 0.004  (maintains 2:1 R:R with tighter SL)
    #   rsi: 40/60 → 35/65  (looser bands = more signals)
    #   ma_trend_filter: True → False  (removing the biggest signal killer)
    # Re-run optimizer (option 12) on SOL alone to validate — target: 50+ trades.
    # SOL — walk-forward ROBUST: val pf=1.30 > train pf=1.26 (424 trades, Feb-Mar 2026).
    # Strategy is performing BETTER in the current market regime than the training period.
    # Optimizer and walk-forward both confirm sl=0.2% / rsi=35/65 / MA_filter=OFF.
    # sl reverted 0.3% → 0.2%: the 0.3% made the live R:R gate STRICTER (needed 0.36%
    # midline distance), not looser. 0.2% requires only 0.24% — more signals pass.
    "SOL": {"ticker": "SOL-USD", "interval": "5m", "period": "60d",
            "hl_symbol": "SOL", "hl_size": 0.2,   "enabled": True,  # min floor; 0.2 SOL ≈ $16
            "strategy_type": "mean_reversion",
            "ma_trend_filter": False,
            "rsi_oversold": 35, "rsi_overbought": 65,
            "stop_loss_pct": 0.002, "take_profit_pct": 0.004,  # 0.2% SL / 0.4% TP — optimizer best; wider SL kills Gate 3
            "max_bars_in_trade": 36},   # 3 h max hold on 5m bars

    # DOGE — KC mean-reversion scalping on 5m.
    # Rationale: retail-driven, high-volume, low correlation to SOL/ETH ecosystem.
    # Optimizer rank-1 (60d): pf=1.29, wr=43%, 1924 trades — stronger than SOL.
    # Key difference vs SOL: kc_scalar=2.0 (wider bands needed for DOGE's volatility),
    # rsi=45/55 (tighter RSI — more signals pass vs SOL's 35/65).
    # kc_scalar is now per-coin — does NOT affect SOL's kc=1.0.
    "DOGE": {"ticker": "DOGE-USD", "interval": "5m", "period": "60d",
             "hl_symbol": "DOGE", "hl_size": 500,  "enabled": True,  # 500 DOGE ≈ $85 at $0.17
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,          # optimizer rank-1: wider bands suit DOGE volatility
             "ma_trend_filter": False,
             "rsi_oversold": 45, "rsi_overbought": 55,   # optimizer rank-1
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,  # 0.2% SL / 0.4% TP — same as SOL
             "max_bars_in_trade": 36},
}

# ─── STRATEGY PARAMETERS ──────────────────────────────────────────────────────
KC_PERIOD  = 20      # Keltner Channel period
KC_SCALAR  = 1.0     # optimizer winner across ETH/BTC/SOL (was 1.5)
MA_FAST    = 9       # fast EMA period
MA_SLOW    = 21      # slow EMA period
MA_TREND   = 50      # trend EMA period — direction filter: longs only above, shorts only below
RSI_PERIOD = 14      # RSI period

RSI_OVERSOLD    = 45   # SOL optimizer rank-4 winner — better live Sharpe (2.10 vs 1.71)
RSI_OVERBOUGHT  = 55   # symmetric

# ─── AI ADVISOR ───────────────────────────────────────────────────────────────
OLLAMA_MODEL       = "qwen2.5:14b"        # local model via Ollama
OLLAMA_URL         = "http://localhost:11434/api/chat"
OPENROUTER_MODEL   = "openai/gpt-4o-mini" # fallback cloud model
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
AI_CONFIDENCE_THRESHOLD = 0.60            # minimum confidence to act on AI signal (lowered from 0.65 for more trades)
AI_LOCAL_FALLBACK_THRESHOLD = 0.50        # if local confidence < this, try cloud

# ─── RISK MANAGEMENT ──────────────────────────────────────────────────────────
PAPER_CAPITAL      = 672.0    # starting paper capital (USD) — matches testnet wallet
RISK_PER_TRADE     = 0.03     # 3% of capital at risk per trade (raised from 2% for more aggression)
STOP_LOSS_PCT      = 0.004    # 0.4% — optimizer rank-4 SOL recommendation; live-safe width
TAKE_PROFIT_PCT    = 0.008    # 0.8% fallback TP (2× SL, keeps R:R ratio intact)
MAX_OPEN_POSITIONS = 3        # maximum concurrent open positions (ETH + SOL + DOGE)
MAX_DAILY_LOSS     = 0.06     # halt trading if down 6% in a day
MAX_DRAWDOWN       = 0.15     # emergency stop if down 15% from equity peak

# HL_MAX_POSITION_USD: cap on notional position size sent to Hyperliquid.
#   HL position sizes are now derived from risk_manager sizing (RISK_PER_TRADE)
#   rather than hardcoded hl_size minimums. hl_size per coin is now the FLOOR
#   (to satisfy HL's $10 minimum order), and this cap is the CEILING.
#
#   Math: with $671 capital, 3% risk, SOL SL=0.5% → target size = $671×0.03/0.005
#         = $4,026 (way too large). This cap brings it to $200 (~30% of account)
#         which risks $200 × 0.5% = $1.00 per SOL trade — a meaningful amount.
#
#   Raise to $400-500 if you want even more risk (requires HL leverage headroom).
HL_MAX_POSITION_USD = 200.0   # max USD notional per HL trade (~30% of account)

# ─── EDGE / KELLY FILTERS (from prediction-market sizing theory) ───────────────
# MIN_EDGE: minimum (ai_confidence − historical_win_rate) required to enter.
#   Directly maps to the prediction-market "trade only when edge > 0.04" rule.
#   Prevents entering when the AI is barely beating the base rate.
#   Computed from the last 30 closed trades; defaults to 50% base rate if
#   fewer than 10 trades are available.
MIN_EDGE = 0.02   # softened from 0.05 — only blocks true zero-edge signals

# KELLY_FRACTION: fractional Kelly multiplier applied to position sizing.
#   Full Kelly (1.0) is too aggressive for live crypto trading.
#   0.25 (quarter-Kelly) gives a conservative confidence-proportional scalar.
#   At threshold confidence (0.65): size = 1.0× base
#   At high confidence   (0.80+):  size ≈ 1.5× base (capped)
#   Scaling is relative to AI_CONFIDENCE_THRESHOLD so the multiplier is
#   always ≥1.0× for any trade that already passed the confidence gate.
KELLY_FRACTION = 0.50   # half-Kelly (raised from quarter-Kelly for more aggression)

# MIN_ENTRY_QUALITY: minimum ATRs price must be outside the KC band for
#   mean-reversion entries (z-score gate).  Filters weak band-touch entries
#   where price barely crossed the band and the mean-reversion odds are low.
#   0.10 = price must be at least 10% of one ATR beyond the KC band edge.
MIN_ENTRY_QUALITY = 0.05   # halved from 0.10 — allows shallower KC band breaks

# OBI_GATE: Order Book Imbalance threshold for Gate 4.
#   OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume), range -1 to +1.
#   For a SHORT: positive OBI means buyers dominate → fights the signal → skip.
#   For a LONG:  negative OBI means sellers dominate → fights the signal → skip.
#   0.2 = skip if 60%+ of top-10-level book volume is against signal direction.
#   Set to 1.0 to effectively disable the gate.
OBI_GATE = 0.40   # raised from 0.20 — only blocks strong book pressure (>70% one-sided)

# VOL_MIN_RATIO: minimum volume ratio (current bar / 20-bar average) for
#   mean-reversion entries (Gate 5).  Filters entries during thin/quiet bars
#   where a KC band touch is more likely noise than real participation.
#   0.5 = skip if current bar volume is less than half the 20-bar average.
#   Set to 0.0 to effectively disable the gate.
VOL_MIN_RATIO = 0.5

# ─── TRADING MODE ─────────────────────────────────────────────────────────────
TESTNET   = True    # True = Hyperliquid testnet, False = mainnet (real money)
HL_ENABLED = True   # False = generate signals only, no execution

# ─── HYPERLIQUID CREDENTIALS ──────────────────────────────────────────────────
HL_WALLET_ADDRESS  = os.environ.get("HL_WALLET_ADDRESS", "").lower()
HL_PRIVATE_KEY     = os.environ.get("HL_PRIVATE_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ─── TELEGRAM ──────────────────────────────────────────────────────────────────
# Get bot token from @BotFather, chat ID from @userinfobot on Telegram.
# Leave blank to disable notifications.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── FILES ────────────────────────────────────────────────────────────────────
from pathlib import Path
BASE_DIR          = Path(__file__).parent
STATE_FILE        = BASE_DIR / "paper_state.json"
TRADES_FILE       = BASE_DIR / "paper_trades.csv"
SIGNALS_LOG       = BASE_DIR / "signals.log"
BEST_CONFIGS_FILE = BASE_DIR / "best_configs.json"
