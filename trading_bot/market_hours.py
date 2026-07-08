"""
Market hours detection. Two independent checks combined:

1. A calendar rule (forex/metals close roughly Friday ~21:00 UTC through
   Sunday ~21:00 UTC — exact minute varies slightly by broker).
2. A data-freshness check: if the latest candle is much older than it
   should be given your poll interval, treat the market as closed/stale
   regardless of the calendar rule — this catches broker-specific holidays,
   maintenance windows, or feed issues without hardcoding every exception.

Crypto trades 24/7 — this module is intentionally NOT used for
main_crypto.py at all.
"""

from datetime import datetime, timezone

import pandas as pd


def is_forex_metals_calendar_open(now_utc: datetime = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # Monday=0 ... Sunday=6
    hour = now_utc.hour

    if weekday == 5:  # Saturday — closed all day
        return False
    if weekday == 4 and hour >= 21:  # Friday from ~21:00 UTC
        return False
    if weekday == 6 and hour < 21:  # Sunday before ~21:00 UTC
        return False
    return True


def is_data_stale(ltf_df: pd.DataFrame, poll_interval_seconds: int, stale_multiplier: float = 2.5) -> bool:
    """If the newest candle is much older than expected, the feed likely
    isn't updating — safer to treat that as 'market closed' than to keep
    generating predictions on dead data."""
    if ltf_df is None or len(ltf_df) == 0:
        return True

    last_bar_time = pd.to_datetime(ltf_df["time"].iloc[-1])
    if last_bar_time.tzinfo is None:
        last_bar_time = last_bar_time.tz_localize("UTC")

    age_seconds = (datetime.now(timezone.utc) - last_bar_time).total_seconds()
    return age_seconds > (poll_interval_seconds * stale_multiplier)


def is_market_open(ltf_df: pd.DataFrame, poll_interval_seconds: int) -> dict:
    """
    Returns {"open": bool, "reason": str} — combines both checks so the
    caller can log/report WHY it's treating the market as closed.
    """
    calendar_open = is_forex_metals_calendar_open()
    if not calendar_open:
        return {"open": False, "reason": "Outside forex/metals trading hours (weekend)"}

    if is_data_stale(ltf_df, poll_interval_seconds):
        return {"open": False, "reason": "Latest price data is stale — feed likely paused/closed"}

    return {"open": True, "reason": "Market open"}
