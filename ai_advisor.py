"""
ai_advisor.py — AI-powered trade signal interpreter
Uses local Ollama first, falls back to OpenRouter if confidence is too low.
AI recommends; risk_manager and trader execute. AI never touches money directly.
"""
import json
import urllib.request
import urllib.error
from colorama import Fore, Style
from config import (
    OLLAMA_MODEL, OLLAMA_URL,
    OPENROUTER_MODEL, OPENROUTER_URL, OPENROUTER_API_KEY,
    AI_CONFIDENCE_THRESHOLD, AI_LOCAL_FALLBACK_THRESHOLD
)

SYSTEM_PROMPT = """You are a disciplined crypto scalping advisor using a Keltner Channel mean-reversion strategy on the 5-minute timeframe.
Your job is to interpret technical indicators and decide: long, short, or hold.
Be conservative — when in doubt, hold. Capital preservation is more important than catching every move.
Respond ONLY with valid JSON, no extra text."""

SYSTEM_PROMPT_SUPERTREND = """You are a disciplined crypto trend-following advisor using a Supertrend strategy on the 1-hour timeframe.
Your job is to interpret the Supertrend indicator and decide: long, short, or hold.
ONLY act on confirmed Supertrend flips — do not anticipate or front-run a flip.
Hold existing trades while the trend is intact. Be patient: trend trades need room to breathe.
Respond ONLY with valid JSON, no extra text."""

def _build_user_prompt_supertrend(indicators: dict, recent_trades: list,
                                  daily_bias: dict | None = None) -> str:
    """User prompt for Supertrend (trend-following) coins."""
    recent_summary = "No recent trades."
    if recent_trades:
        wins  = sum(1 for t in recent_trades if float(t.get("pnl", 0)) > 0)
        total = len(recent_trades)
        recent_summary = f"Last {total} trades: {wins} wins, {total - wins} losses."

    d       = indicators.get("st_direction", 0)
    d_prev  = indicators.get("st_direction_prev", d)
    flipped = indicators.get("st_flipped", False)
    sig     = indicators.get("st_signal", "hold")
    hurst   = indicators.get("hurst", 0.5)
    adx     = indicators.get("adx", 0.0)
    vol     = indicators.get("vol_regime", "normal")
    mom     = indicators.get("momentum", 0.0)

    dir_str    = "BULLISH (up)" if d == 1 else "BEARISH (down)"
    prev_str   = "bullish" if d_prev == 1 else "bearish"
    flip_str   = (f"YES — just flipped from {prev_str} to {'bullish' if d == 1 else 'bearish'}"
                  if flipped else "NO — trend continuing")
    vol_note   = (" CAUTION: Elevated volatility — reduce size."
                  if vol == "high" else "")

    bias_section = ""
    if daily_bias and daily_bias.get("trend") != "neutral":
        bias_section = (
            f"\nHigher timeframe (1D) context:\n"
            f"- Daily trend: {daily_bias['trend']}\n"
            f"- Daily MA alignment: {daily_bias['ma_alignment']}\n"
        )

    return f"""Analyze {indicators['coin']} on {indicators['interval']} timeframe (Supertrend strategy).

Current indicators:
- Price: ${indicators['price']:,.4f}
- Supertrend line: ${indicators['st_line']:,.4f}  ({indicators.get('price_vs_st', '?')})
- Supertrend direction: {dir_str}
- Trend just flipped: {flip_str}
- ADX: {adx:.1f} ({indicators.get('trend_strength', '?')} trend strength)
- Hurst Exponent: {hurst:.3f} ({indicators.get('market_regime', '?')})
- Momentum score: {mom:+.4f} ({'bullish' if mom > 0 else 'bearish' if mom < 0 else 'flat'})
- Volatility regime: {vol}{vol_note}
- MA trend: {indicators.get('ma_trend', 0):,.4f}  (price is {indicators.get('trend_direction', '?')})
- Recent performance: {recent_summary}
{bias_section}
Strategy rules:
- LONG signal:  Supertrend JUST flipped to bullish (direction changed from -1 to +1)
- SHORT signal: Supertrend JUST flipped to bearish (direction changed from +1 to -1)
- HOLD:         No flip occurred this bar — do not enter mid-trend; wait for the next flip
- Exit is the next opposing flip — this strategy holds for days, not hours
- NEVER enter if "trend just flipped" is NO unless adding to an existing confirmed trend
- In HIGH volatility: reduce confidence by 0.15

Respond ONLY with this JSON:
{{"action": "long" | "short" | "hold", "confidence": 0.0-1.0, "reason": "one sentence"}}"""


def _build_user_prompt(indicators: dict, recent_trades: list,
                       daily_bias: dict | None = None) -> str:
    recent_summary = "No recent trades."
    if recent_trades:
        wins  = sum(1 for t in recent_trades if float(t.get("pnl", 0)) > 0)
        total = len(recent_trades)
        recent_summary = f"Last {total} trades: {wins} wins, {total - wins} losses."

    bias_section = ""
    if daily_bias and daily_bias.get("trend") != "neutral":
        bias_section = (
            f"\nHigher timeframe (1D) context:\n"
            f"- Daily trend: {daily_bias['trend']}\n"
            f"- Daily RSI: {daily_bias['rsi']:.1f}\n"
            f"- Daily MA alignment: {daily_bias['ma_alignment']}\n"
            f"- Daily price vs KC: {daily_bias.get('price_vs_kc', 'unknown')}\n"
        )
        if daily_bias.get("market_regime"):
            bias_section += (
                f"- Daily market regime: {daily_bias['market_regime']}"
                f" (H={daily_bias.get('hurst', 0.5):.3f})\n"
            )
        bias_section += (
            f"Note: Prefer trades aligned with the daily trend. "
            f"Counter-trend scalps require a stronger setup.\n"
        )

    # ── Market regime context ──────────────────────────────────────────────────
    regime     = indicators.get("market_regime", "ranging")
    hurst      = indicators.get("hurst", 0.5)
    adx        = indicators.get("adx", 0.0)
    vol_regime = indicators.get("vol_regime", "normal")
    momentum   = indicators.get("momentum", 0.0)

    regime_note = (
        f"Market is MEAN-REVERTING (Hurst={hurst:.3f}) — "
        f"Keltner band fades have statistical edge."
        if regime == "mean_reverting" else
        f"Market is TRENDING (Hurst={hurst:.3f}, ADX={adx:.1f}) — "
        f"fading the trend is risky; prefer trend-aligned trades."
        if regime == "trending" else
        f"Market is RANGING (Hurst={hurst:.3f}) — "
        f"no strong directional bias; require a clean, high-conviction setup."
    )
    vol_note = (
        " CAUTION: Volatility is ELEVATED — widen stops or reduce size."
        if vol_regime == "high" else
        " Volatility is LOW — tight ranges and smaller moves expected."
        if vol_regime == "low" else
        ""
    )

    # Per-coin RSI thresholds for the prompt (injected by strategy.get_indicators_for_coin)
    from config import RSI_OVERSOLD as _RSI_OS_G, RSI_OVERBOUGHT as _RSI_OB_G
    rsi_os = int(indicators.get("rsi_oversold",  _RSI_OS_G))
    rsi_ob = int(indicators.get("rsi_overbought", _RSI_OB_G))

    # Per-coin MA_TREND direction filter — if disabled, the trend gate is removed
    # from the signal rules so the LLM doesn't reject valid KC+RSI setups.
    ma_trend_filter = indicators.get("ma_trend_filter", True)
    if ma_trend_filter:
        long_trend_rule  = ", AND price is ABOVE MA_TREND (trend_direction=up) — HOLD if below MA_TREND"
        short_trend_rule = ", AND price is BELOW MA_TREND (trend_direction=down) — HOLD if above MA_TREND"
    else:
        long_trend_rule  = " — MA_TREND direction filter is OFF for this coin; take the KC+RSI setup regardless of trend"
        short_trend_rule = " — MA_TREND direction filter is OFF for this coin; take the KC+RSI setup regardless of trend"

    return f"""Analyze {indicators['coin']} on {indicators['interval']} timeframe.

Current indicators:
- Price: ${indicators['price']:,.4f}
- RSI: {indicators['rsi']:.1f} ({indicators['rsi_zone']})
- Keltner Channel: upper={indicators['kc_upper']:,.4f}, mid={indicators['kc_mid']:,.4f}, lower={indicators['kc_lower']:,.4f}
- Price position: {indicators['price_vs_kc']}
- MA fast/slow/trend: {indicators['ma_fast']:,.4f} / {indicators['ma_slow']:,.4f} / {indicators['ma_trend']:,.4f}
- MA alignment: {indicators['ma_alignment']}
- Trend direction: price is {indicators.get('trend_direction', 'unknown')} relative to MA_TREND
- ATR: {indicators['atr']:,.4f}
- ADX: {adx:.1f} ({indicators.get('trend_strength', 'unknown')} trend strength)
- Hurst Exponent: {hurst:.3f} → {regime}
- Momentum score: {momentum:+.4f} ({'bullish' if momentum > 0 else 'bearish' if momentum < 0 else 'flat'})
- Volatility regime: {vol_regime} ({indicators.get('ann_vol', 0) * 100:.1f}% annualised)
- Recent performance: {recent_summary}
{bias_section}
Market regime: {regime_note}{vol_note}

Strategy rules:
- LONG signal: price below KC lower, RSI oversold (≤{rsi_os}){long_trend_rule}
- SHORT signal: price above KC upper, RSI overbought (≥{rsi_ob}){short_trend_rule}
- HOLD: signals are mixed, RSI neutral, or price is inside the channel without a clean setup
- In TRENDING markets (H>0.55): skip fades entirely — trend-following is required, not fading
- In MEAN-REVERTING markets (H<0.45): KC fades have statistical edge; standard setup sufficient
- TP target is the KC midline (not a fixed %); SL is tight at 0.2% — only take trades with clear R:R

Respond ONLY with this JSON:
{{"action": "long" | "short" | "hold", "confidence": 0.0-1.0, "reason": "one sentence"}}"""


def _parse_response(raw: str) -> dict:
    """Extract JSON from model response, even if there's surrounding text."""
    try:
        # Try direct parse first
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        # Try to find JSON block within the text
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    return {"action": "hold", "confidence": 0.0, "reason": "Failed to parse model response"}


def _ask_ollama(prompt: str) -> dict:
    """Query local Ollama instance. Returns parsed decision dict."""
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt}
        ],
        "stream": False
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data    = json.loads(resp.read())
            content = data["message"]["content"]
            result  = _parse_response(content)
            result["source"] = "ollama"
            return result
    except Exception as e:
        return {"action": "hold", "confidence": 0.0, "reason": f"Ollama error: {e}", "source": "ollama_error"}


def _ask_openrouter(prompt: str) -> dict:
    """Query OpenRouter cloud API. Returns parsed decision dict."""
    if not OPENROUTER_API_KEY:
        return {"action": "hold", "confidence": 0.0,
                "reason": "No OPENROUTER_API_KEY set", "source": "openrouter_error"}

    payload = json.dumps({
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt}
        ]
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data    = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            result  = _parse_response(content)
            result["source"] = "openrouter"
            return result
    except Exception as e:
        return {"action": "hold", "confidence": 0.0,
                "reason": f"OpenRouter error: {e}", "source": "openrouter_error"}


def _rule_based_signal(indicators: dict) -> dict:
    """
    Pure rule-based fallback — mirrors the backtester signal logic exactly.
    Used when both Ollama and OpenRouter are unavailable.
    Routes to supertrend or mean-reversion logic based on strategy_type.
    Confidence is 0.75 for a clean signal, 0 for hold.
    """
    strategy_type = indicators.get("strategy_type", "mean_reversion")

    if strategy_type == "supertrend":
        return _rule_based_signal_supertrend(indicators)

    from config import RSI_OVERSOLD as _RSI_OS_GLOBAL, RSI_OVERBOUGHT as _RSI_OB_GLOBAL

    try:
        price    = float(indicators.get("price",    0))
        rsi      = float(indicators.get("rsi",      50))
        kc_lower = float(indicators.get("kc_lower", 0))
        kc_upper = float(indicators.get("kc_upper", 0))
        ma_trend = float(indicators.get("ma_trend", 0))
        hurst    = float(indicators.get("hurst",    0.5))
        rsi_os   = float(indicators.get("rsi_oversold",  _RSI_OS_GLOBAL))
        rsi_ob   = float(indicators.get("rsi_overbought", _RSI_OB_GLOBAL))

        if hurst > 0.62:
            return {"action": "hold", "confidence": 0.0,
                    "reason": f"rules: trending market (H={hurst:.2f}) — skip fade",
                    "source": "rules"}

        above_trend = price > ma_trend
        below_trend = price < ma_trend
        ma_filter   = indicators.get("ma_trend_filter", True)

        long_ok  = (not ma_filter) or above_trend
        short_ok = (not ma_filter) or below_trend

        if price < kc_lower and rsi < rsi_os and long_ok:
            trend_note = "above MA_TREND" if above_trend else "MA_TREND filter OFF"
            return {"action": "long", "confidence": 0.75,
                    "reason": f"rules: below KC lower, RSI {rsi:.1f} < {rsi_os}, {trend_note}",
                    "source": "rules"}

        if price > kc_upper and rsi > rsi_ob and short_ok:
            trend_note = "below MA_TREND" if below_trend else "MA_TREND filter OFF"
            return {"action": "short", "confidence": 0.75,
                    "reason": f"rules: above KC upper, RSI {rsi:.1f} > {rsi_ob}, {trend_note}",
                    "source": "rules"}

        return {"action": "hold", "confidence": 0.0,
                "reason": "rules: no signal — price inside channel or direction filter active",
                "source": "rules"}

    except Exception as e:
        return {"action": "hold", "confidence": 0.0,
                "reason": f"rules: error — {e}", "source": "rules"}


def _rule_based_signal_supertrend(indicators: dict) -> dict:
    """Rule-based fallback for Supertrend coins. Fires only on confirmed flips."""
    try:
        sig     = indicators.get("st_signal", "hold")
        flipped = indicators.get("st_flipped", False)
        vol     = indicators.get("vol_regime", "normal")

        if not flipped or sig == "hold":
            d = indicators.get("st_direction", 0)
            dir_str = "UP (bullish)" if d == 1 else "DOWN (bearish)"
            return {"action": "hold", "confidence": 0.0,
                    "reason": f"rules-ST: no flip — trend {dir_str}, waiting",
                    "source": "rules"}

        conf = 0.75
        if vol == "high":
            conf -= 0.15

        return {"action": sig, "confidence": conf,
                "reason": f"rules-ST: Supertrend flipped to {'bullish' if sig == 'long' else 'bearish'}",
                "source": "rules"}

    except Exception as e:
        return {"action": "hold", "confidence": 0.0,
                "reason": f"rules-ST: error — {e}", "source": "rules"}


def get_decision(indicators: dict, recent_trades: list = None,
                 daily_bias: dict | None = None) -> dict:
    """
    Main entry point. Returns a decision dict:
    {action: 'long'|'short'|'hold', confidence: float, reason: str, source: str}

    Flow:
    1. Try local Ollama (with daily bias context if provided)
    2. If confidence < AI_LOCAL_FALLBACK_THRESHOLD, escalate to OpenRouter
    3. If BOTH fail (source ends in _error), fall back to rule-based signal
    4. If final confidence < AI_CONFIDENCE_THRESHOLD, override to 'hold'
    5. If daily_bias is strongly counter to the signal, reduce confidence by 0.10
    """
    if recent_trades is None:
        recent_trades = []

    strategy_type = indicators.get("strategy_type", "mean_reversion")
    if strategy_type == "supertrend":
        prompt = _build_user_prompt_supertrend(indicators, recent_trades, daily_bias)
        # Swap system prompt in the Ollama payload by monkey-patching the module-level
        # constant temporarily — cleaner than threading it through every helper.
        import ai_advisor as _self
        _orig_sys = _self.SYSTEM_PROMPT
        _self.SYSTEM_PROMPT = SYSTEM_PROMPT_SUPERTREND
    else:
        prompt = _build_user_prompt(indicators, recent_trades, daily_bias)
        _orig_sys = None

    decision = _ask_ollama(prompt)

    if _orig_sys is not None:
        import ai_advisor as _self
        _self.SYSTEM_PROMPT = _orig_sys

    source_label = Fore.GREEN + "local" + Style.RESET_ALL

    # Only escalate to cloud if local model wants to trade but isn't confident.
    local_action = decision.get("action", "hold")
    if local_action != "hold" and decision.get("confidence", 0) < AI_LOCAL_FALLBACK_THRESHOLD:
        print(Fore.YELLOW + f"  Local confidence {decision.get('confidence', 0):.2f} — escalating to OpenRouter…")
        cloud = _ask_openrouter(prompt)
        if cloud.get("confidence", 0) > decision.get("confidence", 0):
            decision     = cloud
            source_label = Fore.MAGENTA + "cloud" + Style.RESET_ALL

    # ── Rule-based fallback: both AI backends unavailable ─────────────────────
    # If Ollama timed out AND OpenRouter has no key / also errored, the bot
    # would silently hold forever.  Fall back to the same rules the backtester
    # uses so trading can continue without AI.
    ollama_failed = decision.get("source", "") == "ollama_error"
    cloud_failed  = decision.get("source", "") in ("openrouter_error", "ollama_error")

    if ollama_failed and cloud_failed:
        rules = _rule_based_signal(indicators)
        decision     = rules
        source_label = Fore.YELLOW + "rules" + Style.RESET_ALL
        print(Fore.YELLOW + "  AI unavailable — using rule-based signal.")

    # Counter-trend penalty: if daily bias contradicts the signal, knock 0.10 off
    if daily_bias:
        action = decision.get("action", "hold")
        daily  = daily_bias.get("trend", "neutral")
        if (action == "long"  and daily == "bearish") or \
           (action == "short" and daily == "bullish"):
            old_conf = decision.get("confidence", 0)
            decision["confidence"] = max(0, old_conf - 0.10)
            decision["reason"] += f" [counter-trend penalty: daily={daily}]"

    # Hard floor: if still not confident enough, hold
    if decision.get("confidence", 0) < AI_CONFIDENCE_THRESHOLD:
        decision["action"] = "hold"
        decision["reason"] += (
            f" [overridden to hold — confidence {decision['confidence']:.2f}"
            f" < {AI_CONFIDENCE_THRESHOLD}]"
        )

    decision["source_label"] = source_label
    return decision


def print_decision(decision: dict) -> None:
    """Pretty-print the AI decision."""
    action = decision.get("action", "hold").upper()
    conf   = decision.get("confidence", 0)
    reason = decision.get("reason", "")
    source = decision.get("source_label", "")

    color = Fore.GREEN if action == "LONG" else Fore.RED if action == "SHORT" else Fore.YELLOW
    print(f"\n  {Fore.CYAN}AI Decision ({source}{Fore.CYAN})")
    print(f"  {color}{action}{Style.RESET_ALL}  confidence={conf:.2f}")
    print(f"  {Fore.WHITE}{reason}{Style.RESET_ALL}")
