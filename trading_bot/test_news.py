"""
Standalone diagnostic for the news feed. Run this by itself to see exactly
what Finnhub returns — separate from the full bot, so we can pinpoint the
issue without wading through everything else.

    python test_news.py
"""

import config
import news_sentiment

print(f"FINNHUB_API_KEY set: {'YES' if config.FINNHUB_API_KEY else 'NO — set it with $env:FINNHUB_API_KEY=...'}")
print(f"Key (first 6 chars): {config.FINNHUB_API_KEY[:6] if config.FINNHUB_API_KEY else 'N/A'}...")
print()

print("=== Raw general news (category=general) ===")
raw = news_sentiment.get_general_news(category="general", limit=5)
print(f"Got {len(raw)} articles")
for a in raw[:3]:
    print(f"  - {a.get('headline', 'NO HEADLINE FIELD')}")
print()

print("=== Raw forex news (category=forex) ===")
raw_fx = news_sentiment.get_general_news(category="forex", limit=5)
print(f"Got {len(raw_fx)} articles")
for a in raw_fx[:3]:
    print(f"  - {a.get('headline', 'NO HEADLINE FIELD')}")
print()

print("=== Symbol sentiment for EURUSD ===")
result = news_sentiment.get_symbol_sentiment("EURUSD")
print(result)
