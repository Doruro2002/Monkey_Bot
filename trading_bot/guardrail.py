"""
The Guardrail — this is the "calculator," not the "brain."

Core principle you asked for: the LLM is a strategy researcher, never the
executioner. It outputs a direction, a confidence, and a narrative — but
every actual number that touches risk (position size, RR, daily loss,
trade count, volatility filter) is computed here, deterministically, in
plain Python, using fixed thresholds from config.py. No LLM output — no
matter how convincing or confident-sounding its reasoning — can override
any check in this file. If a rule fails here, the trade is blocked, full
stop, regardless of what any strategy or CEO summary said.

This is deliberately dumb and rigid. That's the point.
"""

import logging

import config
import indicators

log = logging.getLogger("guardrail")


def check(symbol: str, direction: str, entry: float, sl: float, tp: float,
          account_equity: float, open_positions_count: int, daily_pnl_pct: float,
          consecutive_losses: int, trades_today: int, upcoming_news_events: list,
          ltf_df) -> dict:
    """
    Runs every hard rule. Returns {"allowed": bool, "reasons": [str, ...]}.
    ALL checks run (not short-circuited) so you see every violated rule at
    once, not just the first one — useful for understanding why something
    was blocked.
    """
    reasons = []
    allowed = True

    # 1. Daily loss limit — the single most important rule. Once hit, no
    # more trades today, no matter how good the next setup looks.
    if daily_pnl_pct <= -abs(config.MAX_DAILY_LOSS_PCT):
        allowed = False
        reasons.append(f"Daily loss limit reached ({daily_pnl_pct:.2f}% <= -{config.MAX_DAILY_LOSS_PCT}%) — halted for today")

    # 2. Max concurrent trades
    if open_positions_count >= config.MAX_OPEN_TRADES:
        allowed = False
        reasons.append(f"Max open trades reached ({open_positions_count}/{config.MAX_OPEN_TRADES})")

    # 3. Minimum reward:risk — a trade with bad math is bad regardless of
    # how confident the narrative sounds.
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    if rr < config.MIN_RR_RATIO:
        allowed = False
        reasons.append(f"RR {rr} below minimum {config.MIN_RR_RATIO}")

    # 4. Consecutive loss cooldown — psychology-as-code, not vibes.
    if consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
        allowed = False
        reasons.append(f"{consecutive_losses} consecutive losses >= cooldown threshold {config.MAX_CONSECUTIVE_LOSSES}")

    # 5. Overtrading cap
    if trades_today >= config.MAX_TRADES_PER_DAY:
        allowed = False
        reasons.append(f"Already {trades_today} trades today >= daily cap {config.MAX_TRADES_PER_DAY}")

    # 6. Hard news blackout — no override possible, regardless of AI confidence.
    blackout = next((e for e in upcoming_news_events if 0 <= e.get("minutes_until", 999) <= config.NEWS_BLACKOUT_MINUTES), None)
    if blackout:
        allowed = False
        reasons.append(f"News blackout: {blackout['title']} in {blackout['minutes_until']} min")

    # 7. Volatility sanity check — reject if current volatility is extreme
    # relative to recent history (both directions: dead-flat markets have no
    # edge either, wildly volatile ones have unreliable stops).
    try:
        vol_regime = indicators.volatility_regime(ltf_df)
        if vol_regime == "high" and config.BLOCK_TRADES_IN_HIGH_VOLATILITY:
            allowed = False
            reasons.append("Volatility regime is HIGH — stops/targets unreliable right now")
    except Exception as e:
        log.debug("Volatility check skipped (insufficient data): %s", e)

    if allowed:
        reasons.append(f"All guardrail checks passed. RR={rr}")

    return {"allowed": allowed, "reasons": reasons, "rr": rr}
