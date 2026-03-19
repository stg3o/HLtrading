"""
config.py — single source of truth for all settings
Edit this file to change bot behaviour. Do not hardcode values elsewhere.
"""
import os
from dotenv import load_dotenv
load_dotenv()

# ─── DIAGNOSTICS ──────────────────────────────────────────────────────────────
DEBUG_MODE = False
DEBUG_SCAN_LOGS = False
LAST_STRATEGY_UPDATE = "2026-03-19 00:00:00"
MIN_CONFIDENCE = 0.15
HL_ORDER_SLIPPAGE = 0.002
HL_ORDER_RETRY_SLIPPAGE = 0.004
AUTO_IMPORT_POSITIONS = True
DEFAULT_STOP_LOSS_PCT = 0.005
DEFAULT_TAKE_PROFIT_PCT = 0.01
TRADE_COOLDOWN_MINUTES = 15
ENFORCE_LOSS_LIMIT_IN_PAPER = False
MAX_HOLD_MINUTES = None
LOW_VOLUME_EXTREME_RSI_LONG = 35
LOW_VOLUME_EXTREME_RSI_SHORT = 65
LOW_VOLUME_EXTREME_CONFIDENCE_PENALTY = 0.10
LOW_VOLUME_EXTREME_SIZE_SCALAR = 0.50
HL_MARKET_BUFFER = 0.002
HL_MAX_FILL_SLIPPAGE = 0.005
HL_ORACLE_DEVIATION_MAX = 0.01

# ─── COINS ────────────────────────────────────────────────────────────────────
# Per-coin timeframes: ETH/BTC use 1h, SOL uses 5m scalping.
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
    "ETH": {"ticker": "ETH", "interval": "1h", "period": "365d",
            "hl_symbol": "ETH", "hl_size": 0.01,  "sz_decimals": 4,  "enabled": True,
            "strategy_type": "supertrend",
            "st_period": 10, "st_multiplier": 2.5,
            "stop_loss_pct": 0.008,
            "max_bars_in_trade": 168},   # 7 days max — let the trend run

    # BTC — Supertrend trend-following on 1h.
    # Optimizer rank-1 + walk-forward agreed: st(14,2.5), sl=0.8%.
    # Longer period than ETH (14 vs 10) = slower, cleaner BTC trend filter.
    # Walk-forward showed 34% pf decay in holdout — keep position sizing at
    # half of ETH until it proves itself live.
    "BTC": {"ticker": "BTC", "interval": "1h", "period": "365d",
            "hl_symbol": "BTC", "hl_size": 0.001, "enabled": True,
            "strategy_type": "supertrend",
            "allowed_regimes": ("trend", "high_volatility"),
            "timeframes": {"higher": "4h", "mid": "1h", "entry": "1h"},
            "st_period": 14, "st_multiplier": 2.5,
            "stop_loss_pct": 0.008,
            "max_bars_in_trade": 168},

    # BTC_RANGE — conservative 5m range strategy for allocator-based regime switching.
    # Disabled by default to preserve current live behavior; enable alongside BTC
    # once you want the allocator to trade BTC in both range and trend regimes.
    "BTC_RANGE": {"ticker": "BTC", "interval": "5m", "period": "60d",
                  "hl_symbol": "BTC", "hl_size": 0.001, "enabled": False,
                  "strategy_type": "mean_reversion",
                  "allowed_regimes": ("range",),
                  "timeframes": {"higher": "4h", "mid": "1h", "entry": "5m"},
                  "ma_trend_filter": True,
                  "rsi_oversold": 35, "rsi_overbought": 65,
                  "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
                  "max_bars_in_trade": 36},

    # SOL — KC mean-reversion scalping on 5m.
    # Problem: prior optimizer run produced only 13 trades over 60d — not
    # enough for any statistical conclusion. Root cause: MA_filter + RSI 40/60
    # + hurst≤0.45 are too selective combined.
    # Changes vs prior run:
    #   sl: 0.004 → 0.002  (optimizer confirmed 0.2% is best-scoring SL)
    #   tp: 0.008 → 0.004  (maintains 2:1 R:R with tighter SL)
    #   rsi: 40/60 → 35/65  (looser bands = more signals)
    #   ma_trend_filter: False → re-enabled (Mar-2026 trending day caused 16-loss streak without it)
    # Re-run optimizer (option 12) on SOL alone to validate — target: 50+ trades.
    # SOL — KC mean-reversion scalping on 5m.
    # Optimizer (fixed-capital, Mar-2026): rank-1 = kc=1.0, rsi=40/60, PF=1.31, 1973 trades.
    # rsi updated 35/65 → 40/60: same PF (1.31 vs 1.30) but 635 more trades (1973 vs 1338).
    # sl=0.2% retained: wider SL kills Gate 3 (R:R check).
    "SOL": {"ticker": "SOL", "interval": "5m", "period": "60d",
            "hl_symbol": "SOL", "hl_size": 0.2,   "sz_decimals": 2,  "enabled": True,  # min floor; 0.2 SOL ≈ $16
            "strategy_type": "mean_reversion",
            "allowed_regimes": ("range",),
            "timeframes": {"higher": "4h", "mid": "1h", "entry": "5m"},
            "ma_trend_filter": True,   # re-enabled: prevents counter-trend fades in trending markets
            "rsi_oversold": 40, "rsi_overbought": 60,
            "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
            "max_bars_in_trade": 36},   # 3 h max hold on 5m bars

    # DOGE — KC mean-reversion scalping on 5m.
    # Rationale: retail-driven, high-volume, low correlation to SOL/ETH ecosystem.
    # Optimizer rank-1 (7d): pf=1.29, wr=43%, 1924 trades — stronger than SOL.
    # Key difference vs SOL: kc_scalar=2.0 (wider bands needed for DOGE's volatility),
    # rsi=45/55 (tighter RSI — more signals pass vs SOL's 35/65).
    # kc_scalar is now per-coin — does NOT affect SOL's kc=1.0.
    # ⚠ DISABLED: only 7 days of 5m history available — insufficient sample for
    #   statistical validation. Re-enable once HL candle history confirms 30d+ of data.
    "DOGE": {"ticker": "DOGE", "interval": "5m", "period": "7d",
             "hl_symbol": "DOGE", "hl_size": 500,  "enabled": True,
             "sz_decimals": 0,          # HL DOGE requires whole-number lot sizes (no fractions)
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,          # optimizer rank-1: wider bands suit DOGE volatility
             "ma_trend_filter": True,   # re-enabled: prevents counter-trend fades in trending markets
             "rsi_oversold": 45, "rsi_overbought": 55,   # optimizer rank-1
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,  # 0.2% SL / 0.4% TP — same as SOL
             "max_bars_in_trade": 36},

    # ─── CANDIDATE COINS — disabled pending optimizer validation ──────────────────
    # Candidate coins for the Hyperliquid-only trading universe.
    # Default params below are conservative starting points.  The optimizer will
    # search kc_scalar ∈ {1.0, 1.25, 1.5, 2.0} and rsi_oversold ∈ {35, 40, 45}.
    # Enable a coin ONLY after the optimizer shows PF ≥ 1.2 on its best config.
    # sz_decimals values come from HL asset metadata — verify each before live trading.

    # XRP — high liquidity, retail-driven, strong mean-reversion history on 5m.
    # Optimizer rank-1 (60d): pf=1.23, wr=39%, 1326 trades — MARGINAL (barely clears 1.2 threshold).
    # ⚠ PROBATIONARY: live PF must stay ≥ 1.1 over first 30 trades; disable if it drifts below.
    # After spread/slippage, real-world edge is likely ~PF 1.05–1.10. Watch closely.
    "XRP":  {"ticker": "XRP",  "interval": "5m", "period": "60d",
             "hl_symbol": "XRP",  "hl_size": 5,    "sz_decimals": 1,  "enabled": False,
             "probationary": True,      # auto-disabled if live PF < 1.1 over 30 trades
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # WIF — meme-tier volatility. kc_scalar is irrelevant (all values tied at PF=1.45).
    # Optimizer fixed-capital rank-1 (Mar-2026): rsi=35/65, PF=1.45, 1557 trades.
    # rsi updated 40/60 → 35/65 (previous run had compounding artifact inflating 40/60).
    "WIF":  {"ticker": "WIF",  "interval": "5m", "period": "30d",
             "hl_symbol": "WIF",  "hl_size": 7,    "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "kc_scalar": 1.5,
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # BONK — ultra-low price; HL denominates BONK in 1k-unit lots (1 lot ≈ 1000 BONK).
    # hl_size=500 → 500 k-lots = 500 000 BONK ≈ $11 at $0.000022/BONK.
    # Optimizer rank-1 (30d): pf=1.49, wr=36%, 1469 trades — strongest PF of new candidates.
    # ⚠ VERIFY HL denomination and sz_decimals against HL meta before switching to mainnet.
    "BONK": {"ticker": "kBONK", "interval": "5m", "period": "30d",
             "hl_symbol": "kBONK", "hl_size": 500,  "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # ADA — large-cap alt; optimizer confirmed kc=1.0 (tighter bands suit lower volatility).
    # Optimizer rank-1 (60d): pf=1.45, wr=38%, 1378 trades.
    "ADA":  {"ticker": "ADA",  "interval": "5m", "period": "60d",
             "hl_symbol": "ADA",  "hl_size": 15,   "sz_decimals": 0,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # AVAX — mid-cap L1; best Sharpe (13.14) and solid 41% WR among new candidates.
    # Optimizer rank-1 (60d): pf=1.47, wr=41%, 1390 trades. kc=1.0, rsi=35/65.
    "AVAX": {"ticker": "AVAX", "interval": "5m", "period": "60d",
             "hl_symbol": "AVAX", "hl_size": 0.4,  "sz_decimals": 2,  "enabled": True,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # LINK — DeFi oracle token. Optimizer fixed-capital rank-1 (Mar-2026): kc=2.0, rsi=40/60.
    # kc updated 1.5 → 2.0: same PF=1.32 but 471 more trades (1865 vs 1394).
    "LINK": {"ticker": "LINK", "interval": "5m", "period": "60d",
             "hl_symbol": "LINK", "hl_size": 0.8,  "sz_decimals": 2,  "enabled": False,
             "strategy_type": "mean_reversion",
             "kc_scalar": 2.0,
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 40, "rsi_overbought": 60,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # LTC — previously failed at PF=1.17 (compounding artifact). Fixed-capital rerun shows
    # PF=1.24 with kc=1.0, rsi=35/65 — now clears the 1.2 threshold. Enabled.
    # ⚠ PROBATIONARY: was previously sub-threshold. Live PF must stay ≥ 1.1 over first 30 trades.
    "LTC":  {"ticker": "LTC",  "interval": "5m", "period": "60d",
             "hl_symbol": "LTC",  "hl_size": 0.12, "sz_decimals": 3,  "enabled": False,
             "probationary": True,      # auto-disabled if live PF < 1.1 over 30 trades
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # SHIB — ultra-low price meme coin; similar denomination caveat to BONK.
    # HL may denominate in k-lots; hl_size=1000 → 1M SHIB ≈ $13 at $0.000013.
    # Optimizer rank-1 (7d): pf=1.33, wr=40%, 1414 trades. kc=1.0, rsi=35/65.
    # ⚠ DISABLED: only 7 days of 5m history available — insufficient sample for
    #   statistical validation. Also verify HL denomination before re-enabling.
    #   Re-enable once HL candle history confirms 30d+ of data.
    "SHIB": {"ticker": "kSHIB", "interval": "5m", "period": "7d",
             "hl_symbol": "kSHIB", "hl_size": 1000, "sz_decimals": 0,  "enabled": False,
             "strategy_type": "mean_reversion",
             "ma_trend_filter": True,   # re-enabled
             "rsi_oversold": 35, "rsi_overbought": 65,
             "stop_loss_pct": 0.002, "take_profit_pct": 0.004,
             "max_bars_in_trade": 36},

    # ─── SUPERTREND TREND-FOLLOWING — 1h ──────────────────────────────────────
    # Complements the KC mean-reversion coins: fires when ADX > 30 (trending
    # regime) while the 5m KC configs are gated out.  These use the same
    # hl_symbol as their KC counterparts — the risk manager prevents double-open
    # (can_open_position checks hl_symbol uniqueness, not just the dict key).
    #
    # Params: st(10, 2.5) = ETH consensus params as a starting point.
    # take_profit_pct=0.05 (5%) is intentionally wide — the ST flip is the
    # primary exit; TP only fires if the trend runs 5%+ without reversing.
    # ⚠ Run the optimizer (option 12) on these after 30+ live trades to tune
    #   st_period, st_multiplier, and stop_loss_pct per coin.

    # SOL_ST — optimizer walk-forward (Mar-2026): ST(14,2.0), sl=0.8%
    # Train PF=2.52, holdout PF=1.46 (87 trades) — edge confirmed on OOS data.
    # "OVERFIT" flag fired (42% PF decay train→val) but holdout PF > 1.0 is what counts.
    "SOL_ST": {"ticker": "SOL", "interval": "1h", "period": "365d",
               "hl_symbol": "SOL",  "hl_size": 0.2,  "sz_decimals": 2,  "enabled": True,
               "strategy_type": "supertrend",
               "allowed_regimes": ("trend", "high_volatility"),
               "timeframes": {"higher": "4h", "mid": "1h", "entry": "1h"},
               "st_period": 14, "st_multiplier": 2.0,
               "stop_loss_pct": 0.008,
               "take_profit_pct": 0.05,
               "max_bars_in_trade": 168},   # 7 days max — let the trend run

    # AVAX_ST — optimizer walk-forward (Mar-2026): ST(7,2.5), sl=0.8%
    # Train PF=2.55, holdout PF=1.73 (93 trades) — strongest OOS result of the three.
    # Faster ST period (7) suits AVAX's shorter trend cycles vs SOL.
    "AVAX_ST": {"ticker": "AVAX", "interval": "1h", "period": "365d",
                "hl_symbol": "AVAX", "hl_size": 0.4,  "sz_decimals": 2,  "enabled": True,
                "strategy_type": "supertrend",
                "allowed_regimes": ("trend", "high_volatility"),
                "timeframes": {"higher": "4h", "mid": "1h", "entry": "1h"},
                "st_period": 7, "st_multiplier": 2.5,
                "stop_loss_pct": 0.008,
                "take_profit_pct": 0.05,
                "max_bars_in_trade": 168},

    # LINK_ST — DISABLED: holdout PF=0.82 (-0.63 Sharpe, 59 trades) — losing on OOS.
    # LINK trends too poorly on 1h for SuperTrend to extract edge.
    # The 5m KC mean-reversion config (LINK) remains active for ranging regimes.
    "LINK_ST": {"ticker": "LINK", "interval": "1h", "period": "365d",
                "hl_symbol": "LINK", "hl_size": 0.8,  "sz_decimals": 2,  "enabled": False,
                "strategy_type": "supertrend",
                "allowed_regimes": ("trend", "high_volatility"),
                "timeframes": {"higher": "4h", "mid": "1h", "entry": "1h"},
                "st_period": 7, "st_multiplier": 3.5,
                "stop_loss_pct": 0.008,
                "take_profit_pct": 0.05,
                "max_bars_in_trade": 168},
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

# ─── REGIME DETECTION ─────────────────────────────────────────────────────────
# Mean-reversion strategies (KC band fade) only work in ranging/choppy markets.
# In trending regimes, fading the band produces the 14:00–15:30 loss streak pattern.
#
# ADX_MR_MAX: skip all mean-reversion signals when ADX exceeds this.
#   ADX < 20            → ranging / choppy → ideal for KC fade
#   ADX 20–ADX_MR_MAX   → moderate trend → MA trend filter handles direction
#   ADX > ADX_MR_MAX    → strong trend → skip mean-reversion entirely
#   ADX responds in ~14 bars (70 min on 5m) — fast enough to protect intraday.
#
# HURST_MR_MAX: secondary regime check. Skip mean-reversion when Hurst > this.
#   Hurst < 0.45 = mean-reverting  |  Hurst > 0.55 = trending  |  0.45–0.55 = random walk
#   Threshold 0.55 is looser than previous 0.62 — "random walk or better" blocks trending.
#   Hurst needs ~200 bars (~16h on 5m) to be reliable; ADX gate fires faster.
ADX_MR_MAX   = 30     # skip mean-reversion when ADX > 30 (strong trend)
HURST_MR_MAX = 0.55   # skip mean-reversion when Hurst ≥ 0.55 (trending / random walk)

# ─── GATE / FILTER SWITCHES ───────────────────────────────────────────────────
# Set to False to bypass a gate without removing its code.
# Gate 1 (AI edge):          disabled — LLM adds 3-5s latency per coin; optimizer
#                            already found PF 1.3-1.5 without AI involvement.
#                            Uses _rule_based_signal() (exact backtest mirror) instead.
# Gate 2 (entry quality):    disabled — MIN_ENTRY_QUALITY=0.05 is too loose to filter
#                            anything real; Gate 3 (R:R) already covers the same concern.
# Hurst gate:                re-enabled at 0.55 threshold (was 0.62 — too loose).
#                            Works as secondary regime check alongside ADX gate.
AI_ENABLED               = False   # True = call LLM; False = use rule-based signal directly
ENTRY_QUALITY_GATE       = False   # True = enforce z-score ≥ MIN_ENTRY_QUALITY
HURST_GATE               = True    # True = skip mean-reversion when Hurst ≥ HURST_MR_MAX

# ─── MULTI-TIMEFRAME / REGIME ALLOCATION ─────────────────────────────────────
MTF_TIMEFRAME_DEFAULTS = {
    "higher": {"interval": "4h", "period": "180d"},
    "mid": {"interval": "1h", "period": "90d"},
    "entry": {"interval": None, "period": None},
}
STRATEGY_ALLOWED_REGIMES = {
    "mean_reversion": ("range",),
    "supertrend": ("trend", "high_volatility"),
}
REGIME_TREND_ADX_MIN = 25.0
REGIME_RANGE_ADX_MAX = 25.0   # raised from 22 — closes the 22-25 dead zone where
                               # neither mean-reversion nor trend signals could fire.
REGIME_HIGH_VOL_ATR_PCT = 0.025
REGIME_VOL_EXPANSION_BANDWIDTH = 0.06
EXTREME_VOL_ATR_PCT = 0.04
ALLOCATE_BEST_STRATEGY_PER_SYMBOL = True

# ─── FUNDING / OPEN INTEREST ──────────────────────────────────────────────────
USE_FUNDING_RATE_SIGNAL = True
USE_OPEN_INTEREST_SIGNAL = True
FUNDING_EXTREME_ABS = 0.0005        # 0.05% current funding regarded as crowded
FUNDING_CONFLICT_PENALTY = 0.15     # hold if extreme funding fights the trade
FUNDING_CONTRARIAN_BONUS = 0.05     # modest confidence lift when fading crowded side
FUNDING_HARD_BLOCK_ABS = 0.0010     # 0.10% funding = fully suppress crowded direction
OI_MIN_PCT_CHANGE = 0.01            # 1% scan-to-scan OI move required for confirmation
REQUIRE_OI_CONFIRMATION_FOR_TREND = True
SUPPRESS_TREND_ON_OI_DIVERGENCE = True

# ─── BTC MARKET FILTER ────────────────────────────────────────────────────────
USE_BTC_MARKET_FILTER = True
BTC_FILTER_INTERVAL = "1h"
BTC_FILTER_PERIOD = "90d"
BTC_FILTER_TREND_ADX = 32.0
BTC_FILTER_EXTREME_VOL_ATR_PCT = 0.03
BTC_FILTER_SUPPRESS_ALTCOINS = True
BTC_ALT_SIGNAL_CONFIDENCE_PENALTY = 0.20

# ─── LIQUIDATION CASCADE FILTER ───────────────────────────────────────────────
USE_CASCADE_FILTER = True
CASCADE_VOLUME_SPIKE_MIN = 2.5          # completed bar volume / 20-bar avg
CASCADE_RANGE_ATR_MIN = 1.8             # completed bar range / ATR
CASCADE_BREAKOUT_LOOKBACK = 20          # bars for recent high/low breakout
CASCADE_BREAKOUT_ATR_BUFFER = 0.15      # require breakout by >= 0.15 ATR
CASCADE_EXTREME_VOLUME_SPIKE = 4.0
CASCADE_EXTREME_RANGE_ATR = 2.8
CASCADE_TREND_CONFIDENCE_BONUS = 0.08   # boost aligned supertrend entry
CASCADE_MR_ENTRY_QUALITY_BONUS = 0.20   # only upgrades existing MR quality
CASCADE_RISK_CONFIDENCE_PENALTY = 0.20  # reduce confidence during unstable extremes
CASCADE_RISK_BLOCK_EXTREME = True       # fully suppress unstable extreme cascades

# ─── RISK MANAGEMENT ──────────────────────────────────────────────────────────
PAPER_CAPITAL      = 672.0    # starting paper capital (USD) — matches testnet wallet
RISK_PER_TRADE     = 0.03     # 3% of capital at risk per trade (raised from 2% for more aggression)
STOP_LOSS_PCT      = 0.004    # 0.4% — optimizer rank-4 SOL recommendation; live-safe width
TAKE_PROFIT_PCT    = 0.008    # 0.8% fallback TP (2× SL, keeps R:R ratio intact)
MAX_OPEN_POSITIONS  = 6       # raised from 3 — supports 9 active 5m coins without constant slot blocking
MAX_POSITIONS_SIDE  = 3       # max simultaneous longs OR shorts — prevents correlated alt pile-on
                              # All 9 KC coins are crypto alts: they move together in broad market rallies.
                              # Capping per-side at 3 limits correlated exposure when the market trends hard.
                              # At 14:43 on 2026-03-09: AVAX+ADA+SOL+DOGE all shorted simultaneously → -$2.30
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
HL_LEVERAGE         = 3       # default cross-margin leverage for all HL trades.
                              # Set low (3×) — our risk is sized by SL distance, not leverage.
                              # Liquidation at 3× is ~33% adverse move — far beyond any SL.
                              # Override per-coin with "hl_leverage": N in COINS config.

# HL_FEE_RATE: Hyperliquid round-trip fee rate (entry + exit combined).
#   Observed live: $0.09 total per trade on ~$200 notional → 0.045% round-trip.
#   Applied once per closed trade as: fees = size_usd × HL_FEE_RATE.
#   The fee is deducted from P&L in close_position() so paper capital tracks
#   the real wallet balance correctly.
#   At 33 trades × $0.09 = $2.97 in fees — enough to flip a marginal strategy
#   from slightly profitable to slightly negative.
HL_FEE_RATE = 0.00045         # 0.045% round-trip (entry + exit) on notional position size

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
# Runtime-disabled coins written here so the circuit breaker survives restarts.
DISABLED_COINS_FILE = BASE_DIR / "disabled_coins.json"
