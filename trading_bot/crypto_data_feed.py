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
from typing import Dict

import pandas as pd

import config

log = logging.getLogger("crypto_feed")

try:
    import ccxt
except ImportError:
    ccxt = None

_exchange = None


def connect() -> bool:
    global _exchange
    if ccxt is None:
        log.error("ccxt not installed. Run: pip install ccxt")
        return False

    try:
        exchange_class = getattr(ccxt, config.CRYPTO_EXCHANGE)
        _exchange = exchange_class({"enableRateLimit": True})
        _exchange.load_markets()
        log.info("Connected to %s (public market data — no API key needed for prices).", config.CRYPTO_EXCHANGE)
        return True
    except Exception as e:
        log.error("Could not connect to %s: %s", config.CRYPTO_EXCHANGE, e)
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
