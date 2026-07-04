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


def support_resistance_levels(df: pd.DataFrame, lookback: int = 3, n_levels: int = 3) -> dict:
    """Returns the strongest nearby support and resistance levels, derived
    from recent confirmed swing points."""
    highs, lows = swing_points(df, lookback)
    last_close = df["close"].iloc[-1]

    resistances = sorted([h[1] for h in highs if h[1] > last_close])[:n_levels]
    supports = sorted([l[1] for l in lows if l[1] < last_close], reverse=True)[:n_levels]

    return {
        "nearest_resistance": resistances[0] if resistances else None,
        "nearest_support": supports[0] if supports else None,
    }


def is_ranging(df: pd.DataFrame, lookback: int = 30, threshold_atr_multiples: float = 3.0) -> bool:
    """Rough range detector: if price has stayed within a band narrower than
    N average-ATR-widths over the lookback window, treat it as ranging
    rather than trending."""
    recent = df.iloc[-lookback:]
    band_width = recent["high"].max() - recent["low"].min()
    avg_atr = atr(df).iloc[-lookback:].mean()
    if avg_atr == 0 or pd.isna(avg_atr):
        return False
    return band_width < (avg_atr * threshold_atr_multiples)


def range_bounds(df: pd.DataFrame, lookback: int = 30) -> dict:
    recent = df.iloc[-lookback:]
    return {"range_high": recent["high"].max(), "range_low": recent["low"].min()}


def detect_breakout_retest(df: pd.DataFrame, lookback: int = 30, retest_tolerance_atr: float = 0.5) -> dict:
    """
    Looks for: price broke out of the recent range, and has since pulled
    back close to the broken level (a retest) — the classic
    breakout-and-retest entry pattern.
    Returns {"pattern": "bullish_retest" | "bearish_retest" | "none",
             "level": float | None}.
    """
    recent = df.iloc[-lookback:-1]  # exclude the very last (still-forming) bar
    range_high = recent["high"].max()
    range_low = recent["low"].min()
    last_close = df["close"].iloc[-1]
    atr_val = atr(df).iloc[-1]

    if pd.isna(atr_val) or atr_val == 0:
        return {"pattern": "none", "level": None}

    broke_up = df["high"].iloc[-lookback:].max() > range_high
    broke_down = df["low"].iloc[-lookback:].min() < range_low

    if broke_up and abs(last_close - range_high) <= atr_val * retest_tolerance_atr and last_close >= range_high * 0.999:
        return {"pattern": "bullish_retest", "level": range_high}
    if broke_down and abs(last_close - range_low) <= atr_val * retest_tolerance_atr and last_close <= range_low * 1.001:
        return {"pattern": "bearish_retest", "level": range_low}

    return {"pattern": "none", "level": None}
