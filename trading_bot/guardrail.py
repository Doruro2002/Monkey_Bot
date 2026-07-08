"""
The Guardrail — this is the "calculator," not the "brain."

Core principle: the LLM/strategies are researchers, never the executioner.
They output a direction, a confidence, and a narrative — but every actual
number that touches risk (position size, RR, daily loss, trade count) is
computed here, deterministically, in plain Python, using fixed thresholds
from config.py. No LLM output can override any hard check in this file.

Volatility handling changed: instead of a blanket block on high volatility
(which data suggested was leaving money on the table for genuine momentum
setups), high volatility now feeds into regime_engine.py's weighting
instead — strategies that historically do better in volatile conditions
get more say, ones that don't get less. This file still enforces a hard
size reduction (not a full block) when H4 trend conflicts with M15
structure ("structural lock"), since trading against timeframe alignment
is a real, mechanical risk regardless of any single strategy's confidence.
"""

import logging

import config
import indicators

log = logging.getLogger("guardrail")


def check(symbol: str, direction: str, entry: float, sl: float, tp: float,
          account_equity: float, open_positions_count: int, daily_pnl_pct: float,
          consecutive_losses: int, trades_today: int, upcoming_news_events: list,
          ltf_df, htf_df=None, current_spread_pips: float = None,
          is_anticipation_entry: bool = False, has_confirmation: bool = False) -> dict:
    """
    ...
    is_anticipation_entry: True when this is a limit order placed at a
    level (e.g. FVG boundary) BEFORE price has reacted there — "anticipation"
    per the confirmation-vs-anticipation tradeoff. has_confirmation: True
    if a micro-rejection was already observed at that level (see
    indicators.detect_micro_rejection). Per community-tested wisdom (not
    just this bot's own thin backtest sample): pure anticipation without
    any reaction gets a reduced 'probe' size; anticipation WITH a rejection
    signal, or a plain confirmed entry, gets full size.
    """
    reasons = []
    allowed = True
    size_multiplier = 1.0
    risk_multiplier = 1.0

    # 1. Daily loss limit — the single most important rule. Once hit, no
    # more trades today, no matter how good the next setup looks.
    if daily_pnl_pct <= -abs(config.MAX_DAILY_LOSS_PCT):
        allowed = False
        reasons.append(f"Daily loss limit reached ({daily_pnl_pct:.2f}% <= -{config.MAX_DAILY_LOSS_PCT}%) — halted for today")

    # 2. Max concurrent trades
    if open_positions_count >= config.MAX_OPEN_TRADES:
        allowed = False
        reasons.append(f"Max open trades reached ({open_positions_count}/{config.MAX_OPEN_TRADES})")

    # 3. Minimum reward:risk
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    if rr < config.MIN_RR_RATIO:
        allowed = False
        reasons.append(f"RR {rr} below minimum {config.MIN_RR_RATIO}")

    # 4. Consecutive loss cooldown
    if consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
        allowed = False
        reasons.append(f"{consecutive_losses} consecutive losses >= cooldown threshold {config.MAX_CONSECUTIVE_LOSSES}")

    # 5. Overtrading cap
    if trades_today >= config.MAX_TRADES_PER_DAY:
        allowed = False
        reasons.append(f"Already {trades_today} trades today >= daily cap {config.MAX_TRADES_PER_DAY}")

    # 6. Hard news blackout — always a full block, no size-scaling option.
    blackout = next((e for e in upcoming_news_events if 0 <= e.get("minutes_until", 999) <= config.NEWS_BLACKOUT_MINUTES), None)
    if blackout:
        allowed = False
        reasons.append(f"News blackout: {blackout['title']} in {blackout['minutes_until']} min")

    # 6b. Pre-news risk reduction (softer than the blackout above — active
    # for a wider window before the hard blackout kicks in).
    pre_news = next((e for e in upcoming_news_events
                      if 0 <= e.get("minutes_until", 999) <= config.PRE_NEWS_RISK_REDUCTION_MINUTES), None)
    if pre_news and allowed:
        risk_multiplier *= config.PRE_NEWS_RISK_MULTIPLIER
        reasons.append(f"Pre-news window ({pre_news['title']} in {pre_news['minutes_until']} min) — risk reduced to {int(config.PRE_NEWS_RISK_MULTIPLIER*100)}%")

    # 7. Structural lock (Rule 8): if H4 trend conflicts with M15 structure,
    # don't fully block — reduce size, since a real (if lower-probability)
    # setup may still exist, but trading against timeframe alignment
    # deserves smaller risk, not zero.
    if htf_df is not None:
        try:
            htf_trend = indicators.trend_direction(htf_df)
            ltf_structure = indicators.detect_bos(ltf_df)
            conflict = (htf_trend == "up" and ltf_structure == "bearish_bos") or \
                       (htf_trend == "down" and ltf_structure == "bullish_bos")
            if conflict:
                size_multiplier *= config.STRUCTURAL_LOCK_SIZE_REDUCTION
                reasons.append(f"Structural lock: H4 trend ({htf_trend}) conflicts with M15 structure ({ltf_structure}) "
                                f"— size reduced to {int(config.STRUCTURAL_LOCK_SIZE_REDUCTION*100)}%")
        except Exception as e:
            log.debug("Structural lock check skipped: %s", e)

    # 8. Spread invalidation — halt if the broker's spread has widened
    # beyond a safe threshold (protects against slippage during illiquid
    # or chaotic moments that technical models can't see).
    if current_spread_pips is not None and current_spread_pips > config.SPREAD_MAX_PIPS:
        allowed = False
        reasons.append(f"Spread too wide ({current_spread_pips} pips > {config.SPREAD_MAX_PIPS} max) — slippage risk")

    # 9. Anticipation vs confirmation sizing (community-tested principle,
    # not this bot's own thin sample): a limit entry at a level nobody has
    # reacted to yet is a "probe" — reduce size. If a rejection was
    # observed at that level, or this isn't an anticipation entry at all
    # (plain market entry on confirmed structure), use full size.
    if is_anticipation_entry and not has_confirmation:
        size_multiplier *= 0.5
        reasons.append("Anticipation entry with no rejection confirmation yet — probe size (50%)")
    elif is_anticipation_entry and has_confirmation:
        reasons.append("Anticipation entry WITH rejection confirmation — full size")

    if allowed:
        reasons.append(f"All hard guardrail checks passed. RR={rr}, size_multiplier={size_multiplier}, risk_multiplier={risk_multiplier}")

    return {"allowed": allowed, "reasons": reasons, "rr": rr,
            "size_multiplier": size_multiplier, "risk_multiplier": risk_multiplier}
