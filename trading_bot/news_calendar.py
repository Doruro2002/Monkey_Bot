"""
Real economic calendar feed — replaces the old placeholder that always said
"no dedicated macro feed connected." Uses a public, free, no-key-required
JSON calendar feed. If it's ever unreachable, this fails safe (empty list,
logged warning) rather than crashing the bot.

Covers exactly the events you asked for: NFP, CPI, FOMC, Interest Rate
Decisions, GDP (see config.NEWS_KEYWORDS).
"""

import logging
from datetime import datetime, timezone

import requests

import config

log = logging.getLogger("news_calendar")

_cache = {"events": [], "fetched_at": None}
_CACHE_TTL_SECONDS = 900  # refetch at most every 15 min — this is a shared public feed, don't hammer it


def _fetch_raw() -> list:
    try:
        resp = requests.get(config.NEWS_CALENDAR_URL, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning("Could not fetch economic calendar (using empty list this cycle): %s", e)
        return []


def _matches_keywords(title: str) -> bool:
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in config.NEWS_KEYWORDS)


def get_upcoming_events(currency_filter: list = None) -> list:
    """
    Returns a list of dicts: {"title": str, "impact": "high"|"medium"|"low",
    "minutes_until": int, "currency": str}, filtered to the keywords in
    config.NEWS_KEYWORDS and (optionally) to specific currencies (e.g.
    ["USD", "EUR"] for EURUSD).

    Cached for config-defined TTL so every symbol/cycle doesn't hit the
    public feed separately.
    """
    now = datetime.now(timezone.utc)

    if _cache["fetched_at"] is None or (now - _cache["fetched_at"]).total_seconds() > _CACHE_TTL_SECONDS:
        raw = _fetch_raw()
        _cache["events"] = raw
        _cache["fetched_at"] = now

    results = []
    for ev in _cache["events"]:
        try:
            title = ev.get("title", "")
            impact = ev.get("impact", "").lower()
            currency = ev.get("currency", "")
            date_str = ev.get("date")  # ISO format in this feed

            if config.NEWS_HIGH_IMPACT_ONLY and impact != "high":
                continue
            if not _matches_keywords(title):
                continue
            if currency_filter and currency not in currency_filter:
                continue

            event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            minutes_until = int((event_time - now).total_seconds() / 60)

            if minutes_until < -60:  # skip events that already passed a while ago
                continue

            results.append({
                "title": title,
                "impact": impact,
                "currency": currency,
                "minutes_until": minutes_until,
            })
        except Exception as e:
            log.debug("Skipping malformed calendar entry: %s (%s)", ev, e)
            continue

    return sorted(results, key=lambda e: e["minutes_until"])


def get_upcoming_events_for_symbol(symbol: str) -> list:
    """Maps a forex pair like EURUSD to its two relevant currencies (EUR, USD)
    and returns only news affecting either side of the pair."""
    currencies = [symbol[0:3], symbol[3:6]] if len(symbol) >= 6 else None
    return get_upcoming_events(currency_filter=currencies)
