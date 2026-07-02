"""
Shared technical-analysis helpers. Kept dependency-light (pandas/numpy only)
so the agent logic is transparent and debuggable instead of a black box.
"""

import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def swing_points(df: pd.DataFrame, lookback: int = 3):
    """Very simple swing high/low detector: a bar is a swing high/low if it's
    the max/min within `lookback` bars on either side."""
    highs, lows = [], []
    for i in range(lookback, len(df) - lookback):
        window = df.iloc[i - lookback: i + lookback + 1]
        if df["high"].iloc[i] == window["high"].max():
            highs.append((df["time"].iloc[i], df["high"].iloc[i]))
        if df["low"].iloc[i] == window["low"].min():
            lows.append((df["time"].iloc[i], df["low"].iloc[i]))
    return highs, lows


def trend_direction(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> str:
    """EMA-cross based trend read. Cheap, transparent, good enough as one
    input signal among several — not meant to be the whole strategy."""
    ema_fast = df["close"].ewm(span=fast).mean()
    ema_slow = df["close"].ewm(span=slow).mean()
    if ema_fast.iloc[-1] > ema_slow.iloc[-1]:
        return "up"
    if ema_fast.iloc[-1] < ema_slow.iloc[-1]:
        return "down"
    return "flat"


def detect_bos(df: pd.DataFrame, lookback: int = 3) -> str:
    """Break of structure: does the latest close break beyond the most
    recent confirmed swing high/low?"""
    highs, lows = swing_points(df, lookback)
    last_close = df["close"].iloc[-1]
    if highs and last_close > highs[-1][1]:
        return "bullish_bos"
    if lows and last_close < lows[-1][1]:
        return "bearish_bos"
    return "none"


def fair_value_gap(df: pd.DataFrame) -> list:
    """3-candle imbalance detector (simplified ICT-style FVG)."""
    gaps = []
    for i in range(2, len(df)):
        c1, c3 = df.iloc[i - 2], df.iloc[i]
        if c3["low"] > c1["high"]:
            gaps.append(("bullish", c1["high"], c3["low"], df["time"].iloc[i]))
        elif c3["high"] < c1["low"]:
            gaps.append(("bearish", c3["high"], c1["low"], df["time"].iloc[i]))
    return gaps[-5:]  # most recent few only


def volatility_regime(df: pd.DataFrame) -> str:
    current_atr = atr(df).iloc[-1]
    avg_atr = atr(df).iloc[-50:].mean()
    if current_atr > avg_atr * 1.3:
        return "high"
    if current_atr < avg_atr * 0.7:
        return "low"
    return "normal"
