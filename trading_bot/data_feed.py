"""
Pulls multi-timeframe market data from the MetaTrader5 terminal (Exness).

Requires: pip install MetaTrader5 pandas
Windows only (MT5 terminal must be installed, logged in, and running).
"""

import logging
from datetime import datetime
from typing import Dict

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # allows the rest of the codebase to be read/tested
    mt5 = None         # off-Windows, without triggering an import crash

import config

log = logging.getLogger("data_feed")

_TF_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def connect() -> bool:
    if mt5 is None:
        log.error("MetaTrader5 package not available (Windows-only). "
                   "Install with: pip install MetaTrader5")
        return False

    kwargs = {}
    if config.MT5_TERMINAL_PATH:
        kwargs["path"] = config.MT5_TERMINAL_PATH

    if not mt5.initialize(**kwargs):
        log.error("MT5 initialize() failed: %s", mt5.last_error())
        return False

    if config.MT5_LOGIN:
        authorized = mt5.login(
            config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        if not authorized:
            log.error("MT5 login failed: %s", mt5.last_error())
            return False

    log.info("Connected to MT5 terminal.")
    return True


def shutdown():
    if mt5:
        mt5.shutdown()


def get_ohlc(symbol: str, timeframe: str, bars: int = 300) -> pd.DataFrame:
    """Returns a DataFrame with columns: time, open, high, low, close, tick_volume."""
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not available.")

    tf_const = getattr(mt5, _TF_MAP[timeframe])
    rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data returned for {symbol} {timeframe}: {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_multi_timeframe_snapshot(symbol: str) -> Dict[str, pd.DataFrame]:
    """Fetches every configured timeframe for one symbol — this is the
    'context like a professional trader would use' data package that gets
    handed to every agent."""
    return {tf: get_ohlc(symbol, tf) for tf in config.TIMEFRAMES}


def get_account_info() -> dict:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not available.")
    info = mt5.account_info()
    if info is None:
        raise RuntimeError(f"account_info() failed: {mt5.last_error()}")
    return info._asdict()


def get_open_positions() -> list:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not available.")
    positions = mt5.positions_get()
    return [p._asdict() for p in positions] if positions else []
