"""
Position sizing and hard-limit enforcement. This module has final veto
power in main.py — no trade bypasses it, regardless of CEO confidence.
"""

import config


def calc_position_size(account_equity: float, entry: float, stop_loss: float,
                        pip_value_per_lot: float, risk_pct: float = None) -> float:
    """
    Simplified lot-size calculation.
    pip_value_per_lot: monetary value of a 1-pip move for 1.0 lot in your
    account currency — pull this from mt5.symbol_info() in production
    (it varies by symbol and by broker's contract size).
    """
    risk_pct = risk_pct if risk_pct is not None else config.RISK_PER_TRADE_PCT
    risk_amount = account_equity * (risk_pct / 100)
    stop_distance_pips = abs(entry - stop_loss)

    if stop_distance_pips <= 0 or pip_value_per_lot <= 0:
        return 0.0

    lots = risk_amount / (stop_distance_pips * pip_value_per_lot)
    return round(max(lots, 0.01), 2)


def calc_rr(entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk == 0:
        return 0.0
    return round(reward / risk, 2)


def check_hard_limits(daily_pnl_pct: float, open_positions_count: int) -> tuple:
    """Returns (allowed: bool, reason: str)."""
    if daily_pnl_pct <= -abs(config.MAX_DAILY_LOSS_PCT):
        return False, f"Daily loss limit reached ({daily_pnl_pct:.2f}%). Trading halted for today."
    if open_positions_count >= config.MAX_OPEN_TRADES:
        return False, f"Max concurrent trades reached ({open_positions_count}/{config.MAX_OPEN_TRADES})."
    return True, "OK"
