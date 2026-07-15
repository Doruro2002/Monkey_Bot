"""
Crypto market data via ccxt — completely separate from data_feed.py (MT5).

Why separate: MT5 (even on real broker demos) rarely offers USDT pairs, and
often no crypto at all beyond BTC/ETH as CFDs against USD. ccxt talks
directly to real exchanges (Binance by default) and reading OHLCV price
data from their public endpoints needs NO API key, NO login, and NO money
— it's just public market data, same as anyone can see on the exchange's
own website.

Install: pip install ccxt

Placing real orders (later, optional) DOES require an authenticated API
key with trading permissions on the exchange — that's a separate, bigger
step than reading prices, and is NOT needed just to get predictions.
"""

import logging
import time
from typing import Dict

import pandas as pd

import config

log = logging.getLogger("crypto_feed")

try:
    import ccxt
except ImportError:
    ccxt = None

_exchange = None


def connect(max_retries: int = 3) -> bool:
    global _exchange
    if ccxt is None:
        log.error("ccxt not installed. Run: pip install ccxt")
        return False

    exchange_class = getattr(ccxt, config.CRYPTO_EXCHANGE)
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            _exchange = exchange_class({"enableRateLimit": True})
            _exchange.load_markets()
            log.info("Connected to %s (public market data — no API key needed for prices).", config.CRYPTO_EXCHANGE)
            return True
        except Exception as e:
            last_error = e
            error_text = str(e)

            # Geo-block detection: Binance returns HTTP 451/403 for restricted
            # regions — this is NOT a transient network blip, retrying won't help.
            if "451" in error_text or "restricted location" in error_text.lower() or "eligibility" in error_text.lower():
                log.error(
                    "%s appears to be BLOCKING your region (geo-restriction, not a network issue). "
                    "Retrying won't help. Try a different exchange instead — set CRYPTO_EXCHANGE to "
                    "'kraken', 'bybit', or 'kucoin' in your environment and restart. Full error: %s",
                    config.CRYPTO_EXCHANGE, error_text,
                )
                return False

            log.warning("Connection attempt %d/%d to %s failed: %s", attempt, max_retries, config.CRYPTO_EXCHANGE, error_text)
            if attempt < max_retries:
                time.sleep(3 * attempt)

    log.error("Could not connect to %s after %d attempts. Full error: %s", config.CRYPTO_EXCHANGE, max_retries, last_error)
    return False


_TF_KEY_MAP = {"15m": "M15", "1h": "H1", "4h": "H4", "1d": "D1"}


def get_ohlc(symbol: str, timeframe: str, bars: int = 300) -> pd.DataFrame:
    """Returns a DataFrame with columns: time, open, high, low, close,
    tick_volume — same shape as data_feed.get_ohlc(), so indicators.py and
    strategies.py work unchanged on crypto data."""
    if _exchange is None:
        raise RuntimeError("Not connected — call connect() first.")

    raw = _exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=bars)
    if not raw:
        raise RuntimeError(f"No data returned for {symbol} {timeframe}")

    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "tick_volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df


def get_multi_timeframe_snapshot(symbol: str) -> Dict[str, pd.DataFrame]:
    """Keys come back as M15/H1/H4/D1 — same abstract names strategies.py
    already expects from the forex side — so the entire strategy engine
    works on crypto data with zero changes."""
    return {_TF_KEY_MAP[tf]: get_ohlc(symbol, tf) for tf in config.CRYPTO_TIMEFRAMES}


def shutdown():
    pass  # ccxt REST connections don't need explicit teardown
