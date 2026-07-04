"""
The CEO agent: combines every trader's vote into one decision with a
confidence score. Weights are dynamic — the Learning Engine (learning.py)
adjusts them over time based on each agent's historical accuracy.
"""

from typing import Dict, List

DEFAULT_WEIGHTS = {
    "Structure": 0.25,
    "ICT/SmartMoney": 0.20,
    "Quant": 0.20,
    "News": 0.15,   # mostly acts as a veto via WAIT, not a directional vote
    "Psychology": 0.10,
    "DevilsAdvocate": 0.10,
}


def decide(agent_results: List[dict], weights: Dict[str, float] = None) -> dict:
    """
    agent_results: outputs from structure_agent, ict_agent, quant_agent,
    news_agent, psychology_agent, devils_advocate_agent (NOT risk_agent —
    that one is applied separately as a hard veto in main.py).
    """
    weights = weights or DEFAULT_WEIGHTS

    buy_score = 0.0
    sell_score = 0.0
    total_weight = 0.0
    all_reasons = []
    vetoed = False
    veto_reasons = []

    # Psychology structurally never votes BUY/SELL (APPROVE/WAIT only) — it's
    # oversight, not a market call. Its weight must NOT dilute the
    # denominator, or consensus becomes mathematically capped below 100%
    # even when every directional agent agrees. News is now directional
    # (see agents.py) so it stays IN the tally, except for its hard veto
    # case below (imminent high-impact news), which still overrides everything.
    NON_DIRECTIONAL_AGENTS = {"Psychology"}

    for r in agent_results:
        name = r["name"]
        w = weights.get(name, 0.1)
        all_reasons.append(f"{name}: {r['vote']} ({r['confidence']}%) — {'; '.join(r['reasons'])}")

        if name == "DevilsAdvocate" and r["vote"] == "REJECT":
            vetoed = True
            veto_reasons.append(r["reasons"])
            continue

        if name == "News" and r["vote"] == "WAIT" and r["confidence"] >= 90:
            vetoed = True
            veto_reasons.append(r["reasons"])
            continue

        if name in NON_DIRECTIONAL_AGENTS:
            continue  # informational/veto-only, excluded from the vote tally

        total_weight += w

        if r["vote"] == "BUY":
            buy_score += w * (r["confidence"] / 100)
        elif r["vote"] == "SELL":
            sell_score += w * (r["confidence"] / 100)

    if vetoed:
        return {
            "consensus": "WAIT",
            "confidence": 0,
            "reasons": all_reasons + [f"VETOED: {v}" for v in veto_reasons],
        }

    if total_weight == 0:
        total_weight = 1

    buy_pct = round((buy_score / total_weight) * 100)
    sell_pct = round((sell_score / total_weight) * 100)

    if buy_pct > sell_pct and buy_pct >= 50:
        return {"consensus": "BUY", "confidence": buy_pct, "reasons": all_reasons}
    if sell_pct > buy_pct and sell_pct >= 50:
        return {"consensus": "SELL", "confidence": sell_pct, "reasons": all_reasons}

    return {"consensus": "WAIT", "confidence": max(buy_pct, sell_pct), "reasons": all_reasons}
