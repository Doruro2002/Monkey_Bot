"""
Learning Engine — reviews CLOSED trades in batches (not after every single
loss, to avoid overfitting to normal variance) and produces:

  1. A per-agent scoreboard (accuracy, best/worst conditions)
  2. Updated CEO trust weights based on that scoreboard
  3. A plain-language weekly review to send yourself on Telegram

Run this on a schedule (e.g. weekly, or every 50-100 closed trades) —
NOT inside the live trading loop.
"""

import json
from collections import defaultdict

import journal


def review_closed_trade(trade: dict) -> dict:
    """Attaches a structured review to one closed trade. This is the
    'ask itself questions after every trade' step from the plan, but it
    only informs the scoreboard — it does not retrain anything by itself."""
    votes = json.loads(trade["agent_votes"])
    outcome = trade["outcome"]

    per_agent_correct = {}
    for v in votes:
        agent_dir = v["vote"]
        was_directional = agent_dir in ("BUY", "SELL")
        if not was_directional:
            continue
        agent_matched_trade_direction = agent_dir == trade["direction"]
        # An agent was "right" if it matched the trade's direction AND the
        # trade won, or it steered away from a direction that lost.
        correct = (agent_matched_trade_direction and outcome == "win") or \
                  (not agent_matched_trade_direction and outcome == "loss")
        per_agent_correct[v["name"]] = correct

    review = {
        "followed_rules": trade["rr"] is not None and trade["rr"] > 0,
        "outcome": outcome,
        "profit_r": trade["profit_r"],
        "per_agent_correct": per_agent_correct,
    }
    journal.record_review(trade["trade_id"], review)
    return review


def build_scoreboard(trades: list) -> dict:
    """trades: list of journal rows that already have a `review` filled in."""
    stats = defaultdict(lambda: {"correct": 0, "total": 0})

    for t in trades:
        if not t.get("review"):
            continue
        review = json.loads(t["review"]) if isinstance(t["review"], str) else t["review"]
        for agent, was_correct in review.get("per_agent_correct", {}).items():
            stats[agent]["total"] += 1
            if was_correct:
                stats[agent]["correct"] += 1

    scoreboard = {}
    for agent, s in stats.items():
        accuracy = round((s["correct"] / s["total"]) * 100, 1) if s["total"] else 0
        scoreboard[agent] = {"accuracy": accuracy, "sample_size": s["total"]}
    return scoreboard


def recompute_weights(scoreboard: dict, min_samples: int = 20) -> dict:
    """Converts accuracy into normalized CEO weights. Agents with too few
    samples keep a neutral default weight instead of swinging wildly on
    small numbers."""
    weights = {}
    for agent, s in scoreboard.items():
        if s["sample_size"] < min_samples:
            weights[agent] = 0.15  # neutral, not yet trusted or distrusted
        else:
            # accuracy of 50% -> weight ~0.1, 90% -> weight ~0.3 (soft scaling)
            weights[agent] = round(0.05 + (s["accuracy"] / 100) * 0.3, 3)

    total = sum(weights.values()) or 1
    return {k: round(v / total, 3) for k, v in weights.items()}


def weekly_report_text(scoreboard: dict, weights: dict) -> str:
    lines = ["*Weekly Learning Report*\n"]
    for agent, s in sorted(scoreboard.items(), key=lambda x: -x[1]["accuracy"]):
        w = weights.get(agent, 0)
        lines.append(f"- {agent}: {s['accuracy']}% accuracy (n={s['sample_size']}) -> new weight {w}")
    return "\n".join(lines)


def run_weekly_learning_cycle():
    """Call this from a weekly cron job."""
    unreviewed = journal.get_unreviewed_closed_trades()
    for t in unreviewed:
        review_closed_trade(t)

    all_trades = journal.get_recent_trades(limit=500)
    scoreboard = build_scoreboard(all_trades)
    weights = recompute_weights(scoreboard)
    report = weekly_report_text(scoreboard, weights)
    return {"scoreboard": scoreboard, "weights": weights, "report_text": report}
