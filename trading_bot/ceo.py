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


def get_dynamic_weights(db_path: str, symbol: str, strategy_names: list, min_samples: int = 10) -> Dict[str, float]:
    """
    THIS is the "learn from bad trades" loop made concrete: each strategy's
    influence on the final decision is scaled by its own tracked accuracy
    for THIS symbol in THIS market's own database (db_path) — a strategy
    that's been wrong more often on this symbol genuinely gets less say
    over time. Strategies without enough history yet fall back to
    regime_engine.TIER_PRIORS (an informed cold-start default — SMC/ICT
    trusted slightly more early on, since order-flow models are generally
    considered higher-fidelity than lagging trend indicators) — NOT a
    claim that this is proven, just a reasonable starting point until real
    tracked data takes over completely.
    """
    import prediction_tracker  # local import avoids a circular import at module load time
    import regime_engine

    weights = {}
    for name in strategy_names:
        acc = prediction_tracker.get_accuracy(db_path, symbol, name)
        if acc["sample_size"] < min_samples or acc["accuracy"] is None:
            weights[name] = regime_engine.TIER_PRIORS.get(name, 0.10)
        else:
            weights[name] = round(0.05 + (acc["accuracy"] / 100) * 0.3, 3)

    total = sum(weights.values()) or 1
    return {k: round(v / total, 3) for k, v in weights.items()}


def decide(agent_results: List[dict], weights: Dict[str, float] = None,
           devils_advocate_result: dict = None, devils_advocate_veto_min_confidence: int = 65) -> dict:
    """
    agent_results: the 9 strategy predictions from strategies.run_all().
    devils_advocate_result (optional, separate from agent_results): if
    provided and its vote is REJECT with confidence >= the threshold, this
    is a hard veto regardless of everything else — a REJECT below the
    threshold is logged but does NOT block the trade (a weak contrarian
    objection shouldn't override real confluence; only a confident one should).
    """
    weights = weights or DEFAULT_WEIGHTS

    buy_score = 0.0
    sell_score = 0.0
    total_weight = 0.0
    all_reasons = []
    vetoed = False
    veto_reasons = []

    if devils_advocate_result:
        da = devils_advocate_result
        all_reasons.append(f"DevilsAdvocate: {da['vote']} ({da['confidence']}%) — {'; '.join(da['reasons'])}")
        if da["vote"] == "REJECT" and da["confidence"] >= devils_advocate_veto_min_confidence:
            vetoed = True
            veto_reasons.append(da["reasons"])

    # Psychology structurally never votes BUY/SELL (APPROVE/WAIT only) — it's
    # oversight, not a market call. Its weight must NOT dilute the
    # denominator, or consensus becomes mathematically capped below 100%
    # even when every directional agent agrees. News is directional (see
    # agents.py) so it stays IN the tally, except for its hard veto case
    # below (imminent high-impact news), which still overrides everything.
    NON_DIRECTIONAL_AGENTS = {"Psychology"}

    for r in agent_results:
        name = r["name"]
        w = weights.get(name, 0.1)
        all_reasons.append(f"{name}: {r['vote']} ({r['confidence']}%) — {'; '.join(r['reasons'])}")

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
