"""
Market regime + session detection. Used to ADJUST strategy weighting, not
to hard-silence strategies — down-weighting preserves diversity while still
favoring what tends to work better in the current conditions. This is an
engineering pattern, not a claim that any specific multiplier is "proven" —
real validation comes from prediction_tracker's ongoing accuracy tracking,
not a backtest of a handful of trades.
"""

from datetime import datetime, timezone

import pandas as pd

import indicators

# Tier priors: informed starting weights (SMC/ICT = order-flow models,
# generally considered higher-fidelity than lagging trend indicators) —
# used ONLY before a strategy has enough tracked history of its own. Once
# prediction_tracker has real accuracy data, that takes over completely
# (see ceo.get_dynamic_weights). This is a cold-start default, not a
# permanent hard rule.
TIER_PRIORS = {
    "SMC": 0.20, "ICT": 0.20,                              # Tier 1
    "PriceAction": 0.14, "SupplyDemand": 0.14,               # Tier 2
    "DayTrading": 0.08, "RangeTrading": 0.08,                 # Tier 3
    "BreakoutRetest": 0.08, "TrendFollowing": 0.08, "NewsTrading": 0.08,
}

# Regime-based weight MULTIPLIERS (applied on top of base weights, not a
# hard on/off switch) — in high volatility, momentum/order-flow models get
# a boost and mean-reversion/breakout-retest models get discounted, since
# ranges and retests are less reliable when price is moving fast.
REGIME_MULTIPLIERS = {
    "high": {
        "SMC": 1.3, "ICT": 1.3, "PriceAction": 1.1,
        "RangeTrading": 0.4, "BreakoutRetest": 0.5, "TrendFollowing": 0.6,
    },
    "low": {
        "RangeTrading": 1.3, "SupplyDemand": 1.2, "PriceAction": 1.1,
        "SMC": 0.8, "ICT": 0.8,
    },
    "normal": {},  # no adjustment
}

# Session-based multipliers — London/NY (high volume) favor breakout/trend
# capture; Asian session (typically lower volume, more range-bound) favors
# range/price-action models over trend-chasing.
SESSION_MULTIPLIERS = {
    "asian": {
        "TrendFollowing": 0.6, "BreakoutRetest": 0.6,
        "RangeTrading": 1.3, "PriceAction": 1.2,
    },
    "london": {"BreakoutRetest": 1.2, "SMC": 1.1, "ICT": 1.1},
    "new_york": {"BreakoutRetest": 1.2, "SMC": 1.1, "ICT": 1.1},
    "overlap": {"BreakoutRetest": 1.3, "SMC": 1.2, "ICT": 1.2},  # London/NY overlap, highest volume
}


def get_volatility_regime(ltf_df: pd.DataFrame) -> str:
    return indicators.volatility_regime(ltf_df)


def get_current_session(now_utc: datetime = None) -> str:
    """Rough session buckets in UTC. Real session times shift slightly with
    daylight saving; this is intentionally approximate."""
    now_utc = now_utc or datetime.now(timezone.utc)
    hour = now_utc.hour

    if 12 <= hour < 16:
        return "overlap"     # London/NY overlap — highest liquidity
    if 7 <= hour < 16:
        return "london"
    if 12 <= hour < 21:
        return "new_york"
    if 0 <= hour < 9:
        return "asian"
    return "asian"  # late US / early Asian wraparound


def apply_regime_and_session_adjustment(base_weights: dict, ltf_df: pd.DataFrame) -> dict:
    """Takes the accuracy-based dynamic weights (or tier priors) and applies
    regime + session multipliers on top — down-weighting, never fully
    zeroing out, so a strategy always still gets a voice, just less of one
    when conditions historically favor other approaches."""
    regime = get_volatility_regime(ltf_df)
    session = get_current_session()

    regime_mult = REGIME_MULTIPLIERS.get(regime, {})
    session_mult = SESSION_MULTIPLIERS.get(session, {})

    adjusted = {}
    for name, w in base_weights.items():
        m = regime_mult.get(name, 1.0) * session_mult.get(name, 1.0)
        adjusted[name] = round(w * m, 4)

    total = sum(adjusted.values()) or 1
    return {k: round(v / total, 4) for k, v in adjusted.items()}, regime, session
