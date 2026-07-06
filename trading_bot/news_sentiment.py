"""
Real market news + sentiment via Finnhub's free tier.

Setup (free, ~2 minutes):
  1. Go to https://finnhub.io/register — free signup, no credit card.
  2. Copy your API key from the dashboard.
  3. Set it as an environment variable: FINNHUB_API_KEY=your_key_here

Free tier: 60 API calls/minute — more than enough for a couple of symbols
checked every 15 minutes. This module fails safe (empty list, logged
warning) if the key is missing or the call fails — it never crashes the bot
and never fabricates sentiment data.

This is intentionally a pure DATA-FETCHING module. The LLM never generates
or guesses sentiment scores — it only ever receives what's actually
returned here and interprets/summarizes it. That separation (real data in,
LLM only allowed to reason over it) is the "brain vs. calculator" principle
applied to news too, not just price levels.
"""

import logging
from datetime import datetime, timedelta

import requests

import config

log = logging.getLogger("news_sentiment")

BASE_URL = "https://finnhub.io/api/v1"


def get_general_news(category: str = "forex", limit: int = 10) -> list:
    """Latest general market news. category: 'general' | 'forex' | 'crypto' | 'merger'"""
    if not config.FINNHUB_API_KEY:
        log.warning("FINNHUB_API_KEY not set — skipping news sentiment this cycle. "
                     "Free signup: https://finnhub.io/register")
        return []

    def _try(cat):
        try:
            resp = requests.get(
                f"{BASE_URL}/news",
                params={"category": cat, "token": config.FINNHUB_API_KEY},
                timeout=15,
            )
            log.info("Finnhub /news category=%s -> HTTP %s", cat, resp.status_code)
            if resp.status_code != 200:
                log.warning("Finnhub returned non-200: %s | body: %s", resp.status_code, resp.text[:300])
                return []
            resp.raise_for_status()
            articles = resp.json()
            log.info("Finnhub category=%s returned %d articles", cat, len(articles) if isinstance(articles, list) else 0)
            return articles if isinstance(articles, list) else []
        except Exception as e:
            log.warning("Finnhub news fetch failed for category=%s: %s", cat, e)
            return []

    articles = _try(category)
    if not articles and category != "general":
        log.info("No articles for category=%s, falling back to category=general", category)
        articles = _try("general")

    return articles[:limit]


_CURRENCY_NAMES = {
    "EUR": ["eur", "euro"], "USD": ["usd", "dollar", "fed", "federal reserve"],
    "GBP": ["gbp", "pound", "sterling", "boe", "bank of england"],
    "JPY": ["jpy", "yen", "boj", "bank of japan"],
    "BTC": ["btc", "bitcoin"], "ETH": ["eth", "ethereum"],
    "SOL": ["sol", "solana"], "XRP": ["xrp", "ripple"], "DOGE": ["doge", "dogecoin"],
    "USDT": ["usdt", "tether", "stablecoin"],
}


def get_symbol_sentiment(symbol: str) -> dict:
    """
    Finnhub's news-sentiment endpoint is stock-ticker-based, not
    forex/crypto-pair-based, so for FX/crypto pairs we fall back to general
    market news filtered by keyword relevance instead of a numeric score —
    still real data, just a different shape. Returns:
    {"headlines": [str, ...], "source": "finnhub", "count": int}
    """
    base_currency = symbol[:3] if "/" not in symbol else symbol.split("/")[0]
    category = "crypto" if "/" in symbol or "USDT" in symbol else "forex"

    articles = get_general_news(category=category, limit=15)
    keywords = _CURRENCY_NAMES.get(base_currency, [base_currency.lower()])

    def _matches(article):
        text = (article.get("headline", "") + " " + article.get("summary", "")).lower()
        return any(kw in text for kw in keywords)

    relevant = [a for a in articles if _matches(a)]
    log.info("%s: %d/%d articles matched keywords %s", symbol, len(relevant), len(articles), keywords)

    # If nothing matches the specific currency, fall back to the general feed
    # rather than returning nothing — still real headlines, just less targeted.
    chosen = relevant if relevant else articles[:5]

    return {
        "headlines": [a.get("headline", "") for a in chosen if a.get("headline")],
        "source": "finnhub",
        "count": len(chosen),
    }
