"""
Generates a real candlestick chart image from actual OHLC data, with
entry/SL/TP marked and a volume panel — styled to look like a real trading
platform (dark theme), not a default matplotlib plot.

Previous version had a real bug: candle body width was a fixed 0.3 date-
units regardless of the actual time interval between bars, which is why
candles were smearing into each other for 15-minute data. Width is now
computed from the ACTUAL median time gap between candles, so spacing is
always correct regardless of timeframe (M15, H1, H4, D1, or crypto's
15m/1h/4h/1d).
"""

import os

import matplotlib
matplotlib.use("Agg")  # no display needed, just save to file
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

# TradingView-ish dark theme
BG_COLOR = "#131722"
GRID_COLOR = "#2a2e39"
TEXT_COLOR = "#d1d4dc"
UP_COLOR = "#26a69a"
DOWN_COLOR = "#ef5350"
ENTRY_COLOR = "#2196f3"
SL_COLOR = "#ef5350"
TP_COLOR = "#26a69a"


def generate_chart(symbol: str, df: pd.DataFrame, entry: float = None, sl: float = None,
                    tp: float = None, direction: str = None, bars: int = 80,
                    output_dir: str = "charts") -> str:
    """
    Renders the last `bars` candles + a volume panel, marks entry/SL/TP as
    horizontal lines if provided, and saves a PNG. Returns the file path.
    """
    os.makedirs(output_dir, exist_ok=True)
    recent = df.iloc[-bars:].copy()
    recent["time"] = pd.to_datetime(recent["time"])
    x = mdates.date2num(recent["time"])

    # Real candle width: scale to the ACTUAL median gap between bars, not a
    # fixed number — this is the fix for the overlapping-candle bug.
    if len(x) > 1:
        median_gap = np.median(np.diff(x))
    else:
        median_gap = 0.01
    body_width = median_gap * 0.65
    wick_width = median_gap * 0.08

    has_volume = "tick_volume" in recent.columns
    if has_volume:
        fig, (ax, vol_ax) = plt.subplots(
            2, 1, figsize=(11, 7), dpi=130, sharex=True,
            gridspec_kw={"height_ratios": [3.2, 1]},
        )
    else:
        fig, ax = plt.subplots(figsize=(11, 6), dpi=130)
        vol_ax = None

    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    for xi, (_, row) in zip(x, recent.iterrows()):
        up = row["close"] >= row["open"]
        color = UP_COLOR if up else DOWN_COLOR

        # wick
        ax.add_patch(plt.Rectangle(
            (xi - wick_width / 2, row["low"]), wick_width, row["high"] - row["low"],
            color=color, linewidth=0,
        ))
        # body
        body_bottom = min(row["open"], row["close"])
        body_height = abs(row["close"] - row["open"])
        if body_height == 0:
            body_height = (row["high"] - row["low"]) * 0.02 or 0.0001
        ax.add_patch(plt.Rectangle(
            (xi - body_width / 2, body_bottom), body_width, body_height,
            color=color, linewidth=0,
        ))

    if entry is not None:
        ax.axhline(entry, color=ENTRY_COLOR, linestyle="--", linewidth=1.1, label=f"Entry {entry}")
    if sl is not None:
        ax.axhline(sl, color=SL_COLOR, linestyle="--", linewidth=1.1, label=f"SL {sl}")
    if tp is not None:
        ax.axhline(tp, color=TP_COLOR, linestyle="--", linewidth=1.1, label=f"TP {tp}")

    ax.set_xlim(x[0] - median_gap, x[-1] + median_gap)
    title = f"{symbol}"
    if direction:
        title += f"  —  {direction} setup"
    ax.set_title(title, fontsize=14, fontweight="bold", color=TEXT_COLOR, loc="left")

    legend = ax.legend(loc="upper left", fontsize=8, facecolor=BG_COLOR, edgecolor=GRID_COLOR, labelcolor=TEXT_COLOR)

    ax.grid(True, color=GRID_COLOR, linewidth=0.6, alpha=0.7)
    ax.tick_params(colors=TEXT_COLOR, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    if vol_ax is not None:
        vol_ax.set_facecolor(BG_COLOR)
        colors = [UP_COLOR if row["close"] >= row["open"] else DOWN_COLOR for _, row in recent.iterrows()]
        vol_ax.bar(x, recent["tick_volume"], width=body_width, color=colors, alpha=0.7)
        vol_ax.grid(True, color=GRID_COLOR, linewidth=0.6, alpha=0.5)
        vol_ax.tick_params(colors=TEXT_COLOR, labelsize=7)
        for spine in vol_ax.spines.values():
            spine.set_color(GRID_COLOR)
        vol_ax.set_ylabel("Volume", color=TEXT_COLOR, fontsize=8)
        bottom_ax = vol_ax
    else:
        bottom_ax = ax

    bottom_ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()
    plt.tight_layout()

    filepath = os.path.join(output_dir, f"{symbol.replace('/', '_')}_chart.png")
    fig.savefig(filepath, facecolor=BG_COLOR)
    plt.close(fig)
    return filepath