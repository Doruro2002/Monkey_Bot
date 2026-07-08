"""
Places and manages orders on the Exness account via the MT5 terminal.
Only ever called after: CEO approval -> Risk Manager approval -> (if
EXECUTION_MODE == "confirm") explicit user Yes on Telegram.
"""

import logging

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

log = logging.getLogger("executor")


def place_limit_order(symbol: str, direction: str, lots: float, limit_price: float,
                       sl: float, tp: float, comment: str = "AI-team-FVG-limit") -> dict:
    """
    Places a pending limit order at a specific price (e.g. an FVG boundary)
    instead of chasing the current market price — this is the "wait for
    the retest, don't chase" behavior: the order only fills if price
    actually comes back to the level, which typically means a better
    entry and a tighter, more meaningful stop.
    """
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not available — cannot execute live orders.")

    order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
        "price": limit_price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 20260701,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("Limit order failed: %s", result)
    else:
        log.info("Limit order placed: %s %s %s lots @ %s", direction, symbol, lots, limit_price)

    return result._asdict() if result else {}


def place_order(symbol: str, direction: str, lots: float, entry: float,
                 sl: float, tp: float, comment: str = "AI-team-trade") -> dict:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not available — cannot execute live orders.")

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = mt5.symbol_info_tick(symbol).ask if direction == "BUY" else mt5.symbol_info_tick(symbol).bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 10,
        "magic": 20260701,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error("Order failed: %s", result)
    else:
        log.info("Order placed: %s %s %s lots @ %s", direction, symbol, lots, price)

    return result._asdict() if result else {}


def close_position(ticket: int) -> dict:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not available.")

    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"error": "position not found"}

    pos = positions[0]
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = mt5.symbol_info_tick(pos.symbol).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(pos.symbol).ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": close_type,
        "price": price,
        "deviation": 10,
        "magic": 20260701,
        "comment": "AI-team-close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    return mt5.order_send(request)._asdict()
