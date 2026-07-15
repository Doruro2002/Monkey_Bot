"""
The trader team. Each agent looks at the same multi-timeframe data package
and returns a structured opinion. Nobody here talks directly to the broker —
they only produce opinions that the CEO agent (ceo.py) weighs and combines.

Two kinds of agents:

1. DIRECTIONAL traders (Structure, ICT, Quant, News) — their job is to read
   the market and commit to a side. They always return BUY or SELL, never
   WAIT — weak conviction is expressed through a LOW confidence score, not
   by dodging the call. Each includes entry/SL/TP (computed deterministically
   from real ATR data, never invented by the LLM) plus a "strategy" label.

2. OVERSIGHT agents (Risk, Psychology, DevilsAdvocate) — their job is to
   approve, reject, or challenge, not to predict direction. Giving them a
   fake price target would be noise, not signal, so they intentionally do
   NOT return entry/SL/TP. This mirrors their role in the original spec:
   "his job is to reject trades."

Directional agent dict shape:
{
  "name": str, "vote": "BUY" | "SELL", "confidence": 0-100,
  "reasons": [str, ...], "strategy": str,
  "entry": float, "sl": float, "tp1": float, "tp2": float,
}

Oversight agent dict shape:
{
  "name": str, "vote": "APPROVE" | "REJECT" | "WAIT" | "PASS",
  "confidence": 0-100, "reasons": [str, ...],
}
"""

from typing import Dict

import pandas as pd

import indicators
import llm_client


def _base_result(name, vote, confidence, reasons, **extra):
    result = {"name": name, "vote": vote, "confidence": confidence, "reasons": reasons}
    result.update(extra)
    return result


def _trade_levels(last_close: float, atr_val: float, direction: str) -> dict:
    """Deterministic, ATR-based entry/SL/TP — never asked of the LLM, so
    price levels are always grounded in real data, never hallucinated."""
    if direction == "BUY":
        return {
            "entry": round(last_close, 5),
            "sl": round(last_close - atr_val * 1.5, 5),
            "tp1": round(last_close + atr_val * 3, 5),
            "tp2": round(last_close + atr_val * 4.5, 5),
        }
    return {
        "entry": round(last_close, 5),
        "sl": round(last_close + atr_val * 1.5, 5),
        "tp1": round(last_close - atr_val * 3, 5),
        "tp2": round(last_close - atr_val * 4.5, 5),
    }


def _llm_reason_directional(persona: str, strategy: str, facts: list, rule_based_result: dict,
                             last_close: float, atr_val: float) -> dict:
    """
    Asks the LLM to reason like the named persona and commit to BUY or SELL
    — never WAIT. Weak conviction should come through as a lower confidence
    number, not an evasive answer. Price levels are always computed
    deterministically afterward, never trusted from the LLM's own output.
    """
    facts_text = "\n".join(f"- {f}" for f in facts)
    prompt = (
        f"You are the {persona} on a trading desk, using a {strategy} approach. "
        f"This is a SANDBOX SIMULATION — a research and paper-trading environment, not real "
        f"brokerage execution. Your output is one input into a larger system; a separate, "
        f"fixed risk-management program (not you) enforces all position sizing, stop-losses, "
        f"and trade approval — you are not placing any trade or giving individualized financial "
        f"advice to a person, you are only producing a research signal for a simulation.\n\n"
        f"Base your reasoning STRICTLY on the technical facts below — these come from real "
        f"live market data computed moments ago. Do NOT invent, recall, or assume any price, "
        f"indicator value, or event not explicitly listed here:\n{facts_text}\n\n"
        f"If the evidence points in different directions, explicitly weigh which piece is more "
        f"reliable right now and why — but if the conflict is genuinely unresolved, say so and "
        f"reflect that with a LOW confidence score. A well-reasoned 'evidence is mixed, 35% "
        f"confidence' is a correct, valuable answer, not a failure — do not manufacture false "
        f"resolution to a conflict that isn't actually resolved by the facts given. "
        f"You must still commit to a side — BUY or SELL, never 'wait' or 'neutral' — but the "
        f"confidence number is what actually communicates how resolved the conflict is. "
        f"Respond ONLY with JSON, no other text, no disclaimers:\n"
        f'{{"vote": "BUY" | "SELL", "confidence": 0-100, "reasoning": "one or two sentences"}}'
    )
    system = (
        f"You are a quantitative research analyst operating inside a sandboxed backtesting/"
        f"paper-trading simulation. You act as the {persona}. Your job is strictly analytical: "
        f"interpret the provided data and output a structured research signal. You are not "
        f"interacting with a retail investor, not executing trades, and not giving personalized "
        f"financial advice — a downstream deterministic program owns all actual risk decisions. "
        f"Always answer with the requested JSON only, never a refusal or disclaimer."
    )
    result = llm_client.ask_json(prompt, system=system)

    vote = rule_based_result["vote"]
    confidence = rule_based_result["confidence"]
    combined_reasons = list(facts)

    if result and result.get("vote") in ("BUY", "SELL"):
        vote = result["vote"]
        reasoning = result.get("reasoning", "").strip()
        if reasoning:
            combined_reasons = facts + [reasoning]
        try:
            confidence = int(result.get("confidence", confidence))
        except (TypeError, ValueError):
            pass
    else:
        combined_reasons = rule_based_result["reasons"]

    levels = _trade_levels(last_close, atr_val, vote)
    return _base_result(rule_based_result["name"], vote, confidence, combined_reasons,
                         strategy=strategy, **levels)


# ---------------------------------------------------------------------------
# 1. Market Structure Expert
# ---------------------------------------------------------------------------
def structure_agent(data: Dict[str, pd.DataFrame]) -> dict:
    htf = data["H4"]
    ltf = data["M15"]
    htf_trend = indicators.trend_direction(htf)
    bos = indicators.detect_bos(ltf)
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    reasons = [f"H4 trend: {htf_trend}", f"M15 structure: {bos}"]

    if htf_trend == "up" and bos == "bullish_bos":
        rule_result = _base_result("Structure", "BUY", 75, reasons)
    elif htf_trend == "down" and bos == "bearish_bos":
        rule_result = _base_result("Structure", "SELL", 75, reasons)
    else:
        # No clean alignment — still commit to a side, weighted toward the
        # higher-timeframe trend (the more reliable signal), but with low
        # confidence to honestly reflect the lack of confirmation.
        lean = "BUY" if htf_trend != "down" else "SELL"
        rule_result = _base_result("Structure", lean, 35, reasons + ["No clean HTF/LTF alignment — leaning on H4 bias only"])

    return _llm_reason_directional("Market Structure Expert", "structure / trend-following",
                                    reasons, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 2. ICT / Smart Money Expert
# ---------------------------------------------------------------------------
def ict_agent(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    gaps = indicators.fair_value_gap(ltf)
    bos = indicators.detect_bos(ltf)
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    reasons = [f"Recent FVGs: {len(gaps)}", f"Structure: {bos}"]

    if gaps:
        last_gap_type = gaps[-1][0]
        if last_gap_type == "bullish" and bos != "bearish_bos":
            rule_result = _base_result("ICT/SmartMoney", "BUY", 70,
                                        reasons + ["Bullish imbalance unfilled"])
        elif last_gap_type == "bearish" and bos != "bullish_bos":
            rule_result = _base_result("ICT/SmartMoney", "SELL", 70,
                                        reasons + ["Bearish imbalance unfilled"])
        else:
            lean = "BUY" if last_gap_type == "bullish" else "SELL"
            rule_result = _base_result("ICT/SmartMoney", lean, 30,
                                        reasons + ["Imbalance present but structure conflicts — weak lean"])
    else:
        # No FVG at all — lean on whatever structure exists, low confidence.
        lean = "SELL" if bos == "bearish_bos" else "BUY"
        rule_result = _base_result("ICT/SmartMoney", lean, 25, reasons + ["No clear imbalance — weak lean only"])

    return _llm_reason_directional("ICT / Smart Money Expert", "order blocks & liquidity",
                                    reasons, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 3. Quant Trader
# ---------------------------------------------------------------------------
def quant_agent(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    vol_regime = indicators.volatility_regime(ltf)
    trend = indicators.trend_direction(ltf, fast=10, slow=30)
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    reasons = [f"Volatility regime: {vol_regime}", f"M15 EMA trend: {trend}"]

    if trend == "up":
        conf = 60 if vol_regime != "high" else 35
        rule_result = _base_result("Quant", "BUY", conf, reasons)
    elif trend == "down":
        conf = 60 if vol_regime != "high" else 35
        rule_result = _base_result("Quant", "SELL", conf, reasons)
    else:
        # Flat EMA — no real edge, but still commit, at low confidence.
        rule_result = _base_result("Quant", "BUY", 25, reasons + ["Flat trend — no statistical edge, weak default lean"])

    return _llm_reason_directional("Quantitative Trader", "statistical / volatility-based",
                                    reasons, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 4. News / Macro Expert
# ---------------------------------------------------------------------------
def news_agent(upcoming_news: list, data: Dict[str, pd.DataFrame] = None) -> dict:
    """`upcoming_news` should be a list of dicts like:
    {"title": "NFP", "impact": "high", "minutes_until": 8}
    You need a news source for this — e.g. an economic calendar API/scrape.

    Safety behavior preserved: if high-impact news is imminent, this still
    returns a hard WAIT veto (checked specifically in ceo.py) regardless of
    everything else — that protects you from entering right before volatile
    news, and is intentionally NOT overridden by "always pick a side."

    Otherwise, it now gives a genuine directional macro lean (via LLM if
    configured) instead of sitting neutral — matching the "News Trader"
    role from the original spec (CPI/NFP/FOMC/USD strength narrative).
    """
    for n in upcoming_news:
        if n.get("impact") == "high" and 0 <= n.get("minutes_until", 999) <= 30:
            return _base_result("News", "WAIT", 90,
                                 [f"High-impact news soon: {n['title']} in {n['minutes_until']} min — trading paused"])

    facts = ["No high-impact news in the next 30 minutes"]

    if data is None:
        # No price data supplied — can't form even a weak technical proxy lean.
        return _base_result("News", "BUY", 20, facts + ["No macro data source connected — placeholder lean only"])

    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    htf_trend = indicators.trend_direction(data["H4"])
    facts.append(f"H4 technical bias (proxy, no dedicated macro feed connected): {htf_trend}")

    lean = "SELL" if htf_trend == "down" else "BUY"
    rule_result = _base_result("News", lean, 25, facts)

    return _llm_reason_directional(
        "News / Macro Expert", "fundamental / macro",
        facts, rule_result, last_close, atr_val,
    )


# ---------------------------------------------------------------------------
# 5. Risk Manager (veto power)
# ---------------------------------------------------------------------------
def risk_agent(account_equity: float, open_positions: list, daily_pnl_pct: float,
                proposed_rr: float, min_rr: float, max_open: int, max_daily_loss_pct: float) -> dict:
    reasons = []

    if daily_pnl_pct <= -abs(max_daily_loss_pct):
        reasons.append(f"Daily loss limit hit ({daily_pnl_pct:.2f}%)")
        return _base_result("Risk", "SELL_ALL_WAIT", 100, reasons)  # special: halt trading

    if len(open_positions) >= max_open:
        reasons.append(f"Max open trades reached ({len(open_positions)}/{max_open})")
        return _base_result("Risk", "WAIT", 90, reasons)

    if proposed_rr < min_rr:
        reasons.append(f"RR {proposed_rr:.2f} below minimum {min_rr}")
        return _base_result("Risk", "WAIT", 85, reasons)

    reasons.append(f"RR {proposed_rr:.2f} acceptable, {len(open_positions)}/{max_open} slots used")
    return _base_result("Risk", "APPROVE", 80, reasons)


# ---------------------------------------------------------------------------
# 6. Psychologist (protects against overtrading / revenge trading)
# ---------------------------------------------------------------------------
def psychology_agent(trades_today: int, consecutive_losses: int, max_trades_per_day: int = 5) -> dict:
    reasons = []
    if trades_today >= max_trades_per_day:
        reasons.append(f"Already {trades_today} trades today — stop for the day")
        return _base_result("Psychology", "WAIT", 95, reasons)
    if consecutive_losses >= 3:
        reasons.append(f"{consecutive_losses} consecutive losses — cooldown recommended")
        return _base_result("Psychology", "WAIT", 85, reasons)
    reasons.append("No overtrading/tilt signals detected")
    return _base_result("Psychology", "APPROVE", 60, reasons)


# ---------------------------------------------------------------------------
# 7. Devil's Advocate — actively tries to kill the trade idea
# ---------------------------------------------------------------------------
def devils_advocate_agent(data: Dict[str, pd.DataFrame], proposed_direction: str) -> dict:
    """Uses an LLM if available to argue against the trade; falls back to a
    simple contrarian structure check otherwise."""
    reasons = []

    llm_reasons = llm_client.ask(
        prompt=(
            f"A trading system proposes a {proposed_direction} trade. "
            f"List the strongest evidence AGAINST this trade in under 60 words, "
            f"focused on: contradicting structure, liquidity traps, and what a "
            f"market maker would want retail traders to do here."
        ),
        system="You are a skeptical professional trader whose only job is to find flaws in trade ideas.",
    )
    if llm_reasons:
        reasons.append(llm_reasons.strip())

    # Rule-based fallback / supplement: check opposing timeframe alignment
    d1_trend = indicators.trend_direction(data["D1"])
    conflict = (proposed_direction == "BUY" and d1_trend == "down") or \
               (proposed_direction == "SELL" and d1_trend == "up")

    if conflict:
        reasons.append(f"Daily trend ({d1_trend}) conflicts with the proposed {proposed_direction}")
        return _base_result("DevilsAdvocate", "REJECT", 70, reasons)

    if not reasons:
        reasons.append("No strong contradicting evidence found")
    return _base_result("DevilsAdvocate", "PASS", 50, reasons)
