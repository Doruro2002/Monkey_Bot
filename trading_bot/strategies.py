"""
Strategy-based trader team — replaces the earlier persona-based agents with
your requested "professional toolbox": Trend Following, Price Action, Smart
Money Concepts, ICT, Supply & Demand, Breakout & Retest, Range Trading, Day
Trading, and News Trading (real calendar-driven, not a placeholder).

Every strategy always commits to BUY or SELL (never WAIT) — weak conviction
shows up as a LOW confidence score instead of dodging the call. Entry/SL/TP
are always computed deterministically from real ATR data, never invented by
an LLM. This reuses the same honest-uncertainty design established earlier.

Each strategy function returns:
{
  "name": str, "vote": "BUY"|"SELL", "confidence": 0-100,
  "reasons": [str, ...], "strategy": str,
  "entry": float, "sl": float, "tp1": float, "tp2": float,
}
"""

from typing import Dict

import pandas as pd

import indicators
from agents import _base_result, _trade_levels, _llm_reason_directional


# ---------------------------------------------------------------------------
# 1. Trend Following — trade only in the direction of the main trend
# ---------------------------------------------------------------------------
def trend_following(data: Dict[str, pd.DataFrame]) -> dict:
    h4_trend = indicators.trend_direction(data["H4"])
    d1_trend = indicators.trend_direction(data["D1"])
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    facts = [f"H4 trend: {h4_trend}", f"D1 trend: {d1_trend}"]

    if h4_trend == d1_trend and h4_trend in ("up", "down"):
        vote = "BUY" if h4_trend == "up" else "SELL"
        rule_result = _base_result("TrendFollowing", vote, 70, facts + ["H4 and D1 aligned — clear main trend"])
    else:
        vote = "BUY" if h4_trend != "down" else "SELL"
        rule_result = _base_result("TrendFollowing", vote, 30, facts + ["H4/D1 disagree — weak trend read"])

    return _llm_reason_directional("Trend Following Trader", "trend following",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 2. Price Action — structure, support/resistance, candlestick read
# ---------------------------------------------------------------------------
def price_action(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    levels = indicators.support_resistance_levels(ltf)
    bos = indicators.detect_bos(ltf)

    facts = [
        f"Nearest support: {levels['nearest_support']}",
        f"Nearest resistance: {levels['nearest_resistance']}",
        f"Structure: {bos}",
    ]

    dist_to_support = abs(last_close - levels["nearest_support"]) if levels["nearest_support"] else None
    dist_to_resistance = abs(levels["nearest_resistance"] - last_close) if levels["nearest_resistance"] else None

    if dist_to_support is not None and dist_to_resistance is not None:
        if dist_to_support < dist_to_resistance:
            rule_result = _base_result("PriceAction", "BUY", 55, facts + ["Price closer to support — favor bounce"])
        else:
            rule_result = _base_result("PriceAction", "SELL", 55, facts + ["Price closer to resistance — favor rejection"])
    else:
        vote = "BUY" if bos != "bearish_bos" else "SELL"
        rule_result = _base_result("PriceAction", vote, 25, facts + ["No clear nearby S/R — weak structural lean"])

    return _llm_reason_directional("Price Action Trader", "pure price action, minimal indicators",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 3. Smart Money Concepts — order blocks, FVG, BOS/CHoCH, liquidity sweeps
# ---------------------------------------------------------------------------
def smart_money_concepts(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    gaps = indicators.fair_value_gap(ltf)
    bos = indicators.detect_bos(ltf)

    facts = [f"BOS/CHoCH read: {bos}", f"Unfilled FVGs: {len(gaps)}"]

    if gaps:
        gap_type = gaps[-1][0]
        aligned = (gap_type == "bullish" and bos != "bearish_bos") or (gap_type == "bearish" and bos != "bullish_bos")
        vote = "BUY" if gap_type == "bullish" else "SELL"
        conf = 65 if aligned else 30
        rule_result = _base_result("SMC", vote, conf, facts + [f"{gap_type.title()} imbalance {'confirmed' if aligned else 'conflicting'} by structure"])
    else:
        vote = "SELL" if bos == "bearish_bos" else "BUY"
        rule_result = _base_result("SMC", vote, 25, facts + ["No fresh imbalance — leaning on structure only"])

    return _llm_reason_directional("Smart Money Concepts Trader", "SMC (order blocks, FVG, BOS/CHoCH, liquidity)",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 4. ICT — kill zones, OTE, liquidity, institutional concepts
# ---------------------------------------------------------------------------
def ict_strategy(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    d1_trend = indicators.trend_direction(data["D1"])
    gaps = indicators.fair_value_gap(ltf)

    facts = [f"Daily bias (D1 trend): {d1_trend}", f"Recent imbalances: {len(gaps)}"]

    vote = "BUY" if d1_trend != "down" else "SELL"
    supporting_gap = any(g[0] == ("bullish" if vote == "BUY" else "bearish") for g in gaps)
    conf = 60 if supporting_gap else 30
    rule_result = _base_result("ICT", vote, conf,
                                facts + [f"{'Imbalance supports' if supporting_gap else 'No imbalance confirming'} daily bias"])

    return _llm_reason_directional("ICT Trader", "ICT (kill zones, OTE, liquidity, SMT divergence)",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 5. Supply & Demand — trade from strong zones
# ---------------------------------------------------------------------------
def supply_demand(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    levels = indicators.support_resistance_levels(ltf, lookback=5)
    h4_trend = indicators.trend_direction(data["H4"])

    facts = [
        f"Nearest demand zone (support): {levels['nearest_support']}",
        f"Nearest supply zone (resistance): {levels['nearest_resistance']}",
        f"H4 trend: {h4_trend}",
    ]

    if levels["nearest_support"] and abs(last_close - levels["nearest_support"]) < atr_val * 1.5 and h4_trend != "down":
        rule_result = _base_result("SupplyDemand", "BUY", 60, facts + ["Price at demand zone with trend support"])
    elif levels["nearest_resistance"] and abs(levels["nearest_resistance"] - last_close) < atr_val * 1.5 and h4_trend != "up":
        rule_result = _base_result("SupplyDemand", "SELL", 60, facts + ["Price at supply zone with trend support"])
    else:
        vote = "BUY" if h4_trend != "down" else "SELL"
        rule_result = _base_result("SupplyDemand", vote, 25, facts + ["Not at a clear zone — weak trend-only lean"])

    return _llm_reason_directional("Supply & Demand Trader", "supply & demand zones + trend confirmation",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 6. Breakout & Retest — wait for break, enter on the retest
# ---------------------------------------------------------------------------
def breakout_retest(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    pattern = indicators.detect_breakout_retest(ltf)

    facts = [f"Breakout/retest pattern: {pattern['pattern']}", f"Level: {pattern['level']}"]

    if pattern["pattern"] == "bullish_retest":
        rule_result = _base_result("BreakoutRetest", "BUY", 65, facts + ["Retesting broken resistance as new support"])
    elif pattern["pattern"] == "bearish_retest":
        rule_result = _base_result("BreakoutRetest", "SELL", 65, facts + ["Retesting broken support as new resistance"])
    else:
        trend = indicators.trend_direction(ltf)
        vote = "BUY" if trend != "down" else "SELL"
        rule_result = _base_result("BreakoutRetest", vote, 20, facts + ["No active breakout/retest — no real setup, weak default"])

    return _llm_reason_directional("Breakout & Retest Trader", "breakout confirmation + retest entry",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 7. Range Trading — buy support / sell resistance in sideways markets
# ---------------------------------------------------------------------------
def range_trading(data: Dict[str, pd.DataFrame]) -> dict:
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    ranging = indicators.is_ranging(ltf)
    bounds = indicators.range_bounds(ltf)

    facts = [f"Ranging: {ranging}", f"Range high: {bounds['range_high']:.5f}", f"Range low: {bounds['range_low']:.5f}"]

    if ranging:
        mid = (bounds["range_high"] + bounds["range_low"]) / 2
        if last_close < mid:
            rule_result = _base_result("RangeTrading", "BUY", 60, facts + ["Price in lower half of range — buy toward range high"])
        else:
            rule_result = _base_result("RangeTrading", "SELL", 60, facts + ["Price in upper half of range — sell toward range low"])
    else:
        trend = indicators.trend_direction(ltf)
        vote = "BUY" if trend != "down" else "SELL"
        rule_result = _base_result("RangeTrading", vote, 20, facts + ["Market is trending, not ranging — this strategy has no real edge right now"])

    return _llm_reason_directional("Range Trading Trader", "range trading (buy support, sell resistance)",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 8. Day Trading — intraday M15/H1 read, opened & closed same session
# ---------------------------------------------------------------------------
def day_trading(data: Dict[str, pd.DataFrame]) -> dict:
    m15_trend = indicators.trend_direction(data["M15"], fast=8, slow=21)
    h1_trend = indicators.trend_direction(data["H1"])
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]
    vol_regime = indicators.volatility_regime(ltf)

    facts = [f"M15 trend: {m15_trend}", f"H1 trend: {h1_trend}", f"Volatility: {vol_regime}"]

    if m15_trend == h1_trend and m15_trend in ("up", "down") and vol_regime != "low":
        vote = "BUY" if m15_trend == "up" else "SELL"
        rule_result = _base_result("DayTrading", vote, 60, facts + ["M15/H1 aligned with tradeable volatility"])
    else:
        vote = "BUY" if m15_trend != "down" else "SELL"
        rule_result = _base_result("DayTrading", vote, 25, facts + ["Timeframes disagree or volatility too low for intraday edge"])

    return _llm_reason_directional("Day Trading Trader", "intraday M15/H1 momentum",
                                    facts, rule_result, last_close, atr_val)


# ---------------------------------------------------------------------------
# 9. News Trading — real calendar (NFP, CPI, FOMC, Interest Rate, GDP)
# ---------------------------------------------------------------------------
def news_trading(upcoming_events: list, data: Dict[str, pd.DataFrame]) -> dict:
    """
    Uses the REAL calendar feed (news_calendar.py) — not a placeholder.
    If a tracked high-impact event (NFP/CPI/FOMC/Interest Rate/GDP) is
    imminent, this is honest about it: nobody can predict which way the
    market will jump on an unreleased number, so confidence stays low and
    the reasoning says so explicitly, rather than pretending to know.
    The hard trading-blackout veto for imminent news still lives in
    main.py/ceo.py — this function is about the *informational* prediction.
    """
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    if upcoming_events:
        next_event = upcoming_events[0]
        facts = [f"Next tracked event: {next_event['title']} ({next_event['currency']}) "
                 f"in {next_event['minutes_until']} min, impact: {next_event['impact']}"]
        h4_trend = indicators.trend_direction(data["H4"])
        vote = "BUY" if h4_trend != "down" else "SELL"
        rule_result = _base_result(
            "NewsTrading", vote, 20,
            facts + ["No directional edge from an unreleased number — this is a volatility-risk flag, not a real prediction"],
        )
    else:
        facts = ["No tracked high-impact event (NFP/CPI/FOMC/Interest Rate/GDP) upcoming"]
        h4_trend = indicators.trend_direction(data["H4"])
        vote = "BUY" if h4_trend != "down" else "SELL"
        rule_result = _base_result("NewsTrading", vote, 20, facts + ["Quiet calendar — defaulting to technical bias only"])

    return _llm_reason_directional("News Trading Trader", "macro/news-driven (NFP, CPI, FOMC, rates, GDP)",
                                    facts, rule_result, last_close, atr_val)


ALL_STRATEGIES = [
    trend_following, price_action, smart_money_concepts, ict_strategy,
    supply_demand, breakout_retest, range_trading, day_trading,
]


def run_all(data: Dict[str, pd.DataFrame], upcoming_events: list) -> list:
    """Runs all 9 strategies (the 8-item toolbox + News Trading) and returns
    their results as a list, in a fixed order."""
    results = [s(data) for s in ALL_STRATEGIES]
    results.append(news_trading(upcoming_events, data))
    return results
