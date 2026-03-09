"""
risk_manager.py — hard risk rules, position sizing, drawdown protection
This module is the last line of defence before any trade executes.
AI recommendations are overridden here if they violate risk rules.
"""
import json
from datetime import datetime, date
from colorama import Fore, Style
from config import (
    RISK_PER_TRADE, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    MAX_OPEN_POSITIONS, MAX_DAILY_LOSS, MAX_DRAWDOWN,
    STATE_FILE, AI_CONFIDENCE_THRESHOLD, KELLY_FRACTION
)


def load_state() -> dict:
    defaults = _default_state()
    try:
        with open(STATE_FILE) as f:
            loaded = json.load(f)
        # Merge: fill in any keys missing from old state files
        defaults.update(loaded)
        return defaults
    except (FileNotFoundError, json.JSONDecodeError):
        return defaults


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _default_state() -> dict:
    from config import PAPER_CAPITAL
    return {
        "capital":        PAPER_CAPITAL,
        "equity_peak":    PAPER_CAPITAL,
        "daily_start":    PAPER_CAPITAL,
        "last_reset_date": str(date.today()),
        "positions":      {},       # coin → {side, size, entry_price, stop_loss, take_profit}
        "total_trades":   0,
        "wins":           0,
        "losses":         0,
        "emergency_stop": False,
        "trading_halted": False,
    }


class RiskManager:
    def __init__(self):
        self.state = load_state()
        self._maybe_reset_daily()

    def _maybe_reset_daily(self):
        """Reset daily tracking at start of new day."""
        today = str(date.today())
        if self.state.get("last_reset_date") != today:
            self.state["daily_start"]     = self.state["capital"]
            self.state["last_reset_date"] = today
            self.state["trading_halted"]  = False
            save_state(self.state)

    # ── CHECKS ────────────────────────────────────────────────────────────────

    def is_halted(self) -> tuple[bool, str]:
        """Returns (halted: bool, reason: str)."""
        if self.state.get("emergency_stop"):
            return True, "EMERGENCY STOP is active"

        if self.state.get("trading_halted"):
            return True, "Daily loss limit reached — trading halted until tomorrow"

        # Check drawdown from equity peak
        drawdown = (self.state["equity_peak"] - self.state["capital"]) / self.state["equity_peak"]
        if drawdown >= MAX_DRAWDOWN:
            self.state["emergency_stop"] = True
            save_state(self.state)
            return True, f"Max drawdown {MAX_DRAWDOWN*100:.0f}% breached ({drawdown*100:.1f}%) — EMERGENCY STOP triggered"

        # Check daily loss
        daily_loss = (self.state["daily_start"] - self.state["capital"]) / self.state["daily_start"]
        if daily_loss >= MAX_DAILY_LOSS:
            self.state["trading_halted"] = True
            save_state(self.state)
            return True, f"Daily loss limit {MAX_DAILY_LOSS*100:.0f}% reached ({daily_loss*100:.1f}%) — halting for today"

        return False, ""

    def can_open_position(self, coin: str) -> tuple[bool, str]:
        """Check whether we're allowed to open a new position."""
        halted, reason = self.is_halted()
        if halted:
            return False, reason

        if coin in self.state["positions"]:
            return False, f"Already have an open position in {coin}"

        if len(self.state["positions"]) >= MAX_OPEN_POSITIONS:
            return False, f"Max open positions ({MAX_OPEN_POSITIONS}) reached"

        return True, ""

    # ── POSITION SIZING ───────────────────────────────────────────────────────

    # Volatility scalars: high vol → smaller size, low vol → slightly larger
    _VOL_SCALAR = {"high": 0.50, "normal": 1.00, "low": 1.20}

    # BTC / ETH / SOL are ~0.8 correlated; holding one reduces size of others.
    # Coins NOT in this set are treated as uncorrelated.
    _CORRELATED_COINS = {"BTC", "ETH", "SOL"}
    _CORRELATION_PENALTY = 0.20   # reduce by 20% per already-held correlated coin

    def calculate_position(self, price: float,
                           vol_regime: str = "normal",
                           coin: str = "",
                           sl_pct: float | None = None,
                           tp_pct: float | None = None,
                           tp_price: float | None = None,
                           ai_confidence: float | None = None) -> dict:
        """
        Calculate position size, stop loss, and take profit levels.

        Uses fixed-risk sizing (RISK_PER_TRADE % of capital), then applies:
        1. Volatility scalar  — shrink size in high-vol, grow slightly in low-vol
        2. Correlation scalar — shrink size if correlated coins already held
        3. Kelly scalar       — scale by confidence relative to the threshold
                                (fractional Kelly, capped 0.5×–1.5×)

        sl_pct / tp_pct: per-coin overrides from COINS config. Falls back to
        global STOP_LOSS_PCT / TAKE_PROFIT_PCT if not provided.

        tp_price: explicit TP price override (e.g. KC midline). When set, this
        takes precedence over the fixed-% TP for both long and short positions.

        ai_confidence: AI model confidence (0–1).  When provided, applies a
        fractional Kelly multiplier to reward higher-conviction entries.
        Uses AI_CONFIDENCE_THRESHOLD as the 1.0× reference point.
        """
        sl_pct = sl_pct if sl_pct is not None else STOP_LOSS_PCT
        tp_pct = tp_pct if tp_pct is not None else TAKE_PROFIT_PCT

        capital     = self.state["capital"]
        risk_amount = capital * RISK_PER_TRADE          # USD at risk
        size_usd    = risk_amount / sl_pct              # base position size

        # ── 1. Volatility adjustment ───────────────────────────────────────────
        vol_scalar = self._VOL_SCALAR.get(vol_regime, 1.0)

        # ── 2. Correlation adjustment ──────────────────────────────────────────
        corr_scalar = 1.0
        if coin.upper() in self._CORRELATED_COINS:
            open_correlated = sum(
                1 for held in self.state.get("positions", {})
                if held.upper() in self._CORRELATED_COINS and held.upper() != coin.upper()
            )
            corr_scalar = max(0.25, 1.0 - open_correlated * self._CORRELATION_PENALTY)

        # ── 3. Kelly scalar (confidence-proportional sizing) ───────────────────
        # f* = (p·b − q) / b  where  b = tp_pct/sl_pct (R:R),  p = confidence
        # Use threshold confidence as the 1.0× reference so every trade that
        # already passed the confidence gate is sized at ≥1.0× baseline.
        # SuperTrend coins have no fixed tp_pct — use 2.5 as conservative R:R.
        kelly_mult = 1.0
        if ai_confidence is not None:
            b = tp_pct / sl_pct if sl_pct > 0 else 2.5
            def _kelly_f(p: float) -> float:
                return (p * b - (1.0 - p)) / b

            f_actual = _kelly_f(ai_confidence) * KELLY_FRACTION
            f_ref    = _kelly_f(AI_CONFIDENCE_THRESHOLD) * KELLY_FRACTION
            if f_ref > 1e-6 and f_actual > 0:
                kelly_mult = max(0.5, min(1.5, f_actual / f_ref))
            elif f_actual <= 0:
                kelly_mult = 0.5   # negative edge — shrink to minimum

        size_usd   = size_usd * vol_scalar * corr_scalar * kelly_mult
        size_units = size_usd / price

        # Use explicit TP price if provided (e.g. KC midline); else fixed %.
        # We store the long-oriented fixed TP for open_position fallback.
        _tp_fixed_long = round(price * (1 + tp_pct), 4)

        return {
            "size_usd":       round(size_usd, 2),
            "size_units":     round(size_units, 6),
            "risk_amount":    round(risk_amount, 2),
            "vol_scalar":     vol_scalar,
            "corr_scalar":    round(corr_scalar, 2),
            "kelly_mult":     round(kelly_mult, 2),
            "ai_confidence":  ai_confidence,
            "stop_loss":      round(price * (1 - sl_pct), 4),
            "take_profit":    _tp_fixed_long,
            # Carry effective pct through so open_position can use them for shorts
            "sl_pct":         sl_pct,
            "tp_pct":         tp_pct,
            # Explicit TP price (KC midline) — used by open_position for both sides
            "tp_price":       tp_price,
        }

    # ── POSITION LIFECYCLE ────────────────────────────────────────────────────

    def open_position(self, coin: str, side: str, price: float, sizing: dict) -> None:
        _sl_pct   = sizing.get("sl_pct",   STOP_LOSS_PCT)
        _tp_pct   = sizing.get("tp_pct",   TAKE_PROFIT_PCT)
        _tp_price = sizing.get("tp_price")  # explicit KC-midline TP if set

        # SL: long = below entry, short = above entry
        sl = sizing["stop_loss"] if side == "long" else round(price * (1 + _sl_pct), 4)

        # TP: if an explicit price was passed (KC midline), use it directly for
        # both sides — the caller already validated it's on the correct side.
        # Otherwise fall back to fixed-pct TP.
        if _tp_price is not None and _tp_price > 0:
            tp = round(_tp_price, 4)
        elif side == "long":
            tp = sizing["take_profit"]
        else:
            tp = round(price * (1 - _tp_pct), 4)

        self.state["positions"][coin] = {
            "side":           side,
            "entry_price":    price,
            "size_units":     sizing["size_units"],
            "size_usd":       sizing["size_usd"],
            "stop_loss":      sl,
            "take_profit":    tp,
            "opened_at":      str(datetime.now()),
            "ai_confidence":  sizing.get("ai_confidence"),   # stored for Brier Score
        }
        save_state(self.state)

    def close_position(self, coin: str, exit_price: float) -> dict:
        """Close position, update capital and stats. Returns trade summary."""
        pos = self.state["positions"].pop(coin, None)
        if not pos:
            return {}

        if pos["side"] == "long":
            pnl = (exit_price - pos["entry_price"]) * pos["size_units"]
        else:
            pnl = (pos["entry_price"] - exit_price) * pos["size_units"]

        self.state["capital"]      += pnl
        self.state["equity_peak"]   = max(self.state["equity_peak"], self.state["capital"])
        self.state["total_trades"] += 1
        if pnl > 0:
            self.state["wins"]    += 1
        else:
            self.state["losses"]  += 1

        save_state(self.state)

        return {
            "coin":        coin,
            "side":        pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price":  exit_price,
            "pnl":         round(pnl, 2),
            "pnl_pct":     round(pnl / pos["size_usd"] * 100, 2),
        }

    def trigger_emergency_stop(self) -> None:
        self.state["emergency_stop"] = True
        save_state(self.state)

    def clear_emergency_stop(self) -> None:
        self.state["emergency_stop"] = False
        self.state["trading_halted"] = False
        save_state(self.state)

    # ── REPORTING ─────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        capital   = self.state["capital"]
        peak      = self.state["equity_peak"]
        drawdown  = (peak - capital) / peak * 100 if peak > 0 else 0
        total     = self.state["total_trades"]
        win_rate  = self.state["wins"] / total * 100 if total > 0 else 0
        from config import PAPER_CAPITAL
        total_pnl = capital - PAPER_CAPITAL

        return {
            "capital":    round(capital, 2),
            "peak":       round(peak, 2),
            "drawdown":   round(drawdown, 2),
            "total_pnl":  round(total_pnl, 2),
            "total_trades": total,
            "win_rate":   round(win_rate, 1),
            "positions":  self.state["positions"],
            "halted":     self.state.get("trading_halted", False),
            "emergency":  self.state.get("emergency_stop", False),
        }

    def print_summary(self) -> None:
        s = self.get_summary()
        pnl_color  = Fore.GREEN if s["total_pnl"] >= 0 else Fore.RED
        halt_color = Fore.RED   if s["halted"] or s["emergency"] else Fore.GREEN
        status     = "EMERGENCY STOP" if s["emergency"] else "HALTED" if s["halted"] else "ACTIVE"

        print(f"\n  {Fore.CYAN}{'─'*44}")
        print(f"  {Fore.CYAN}RISK SUMMARY")
        print(f"  Capital   : ${s['capital']:,.2f}   Peak: ${s['peak']:,.2f}")
        print(f"  Total P&L : {pnl_color}${s['total_pnl']:+,.2f}{Style.RESET_ALL}")
        print(f"  Drawdown  : {s['drawdown']:.1f}%   Win rate: {s['win_rate']:.1f}%  ({s['total_trades']} trades)")
        print(f"  Status    : {halt_color}{status}{Style.RESET_ALL}")
        if s["positions"]:
            print(f"  Positions : {', '.join(s['positions'].keys())}")
        else:
            print(f"  Positions : none")
