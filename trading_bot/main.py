"""
Main loop. Run with:  python main.py

Flow per symbol, each cycle (2 messages per symbol = 4 total for 2 symbols):
  1. REVIEW message: check last cycle's predictions from all 9 strategies
     against current price, update rolling accuracy per strategy (the
     "learn from it" loop), send to Telegram.
  2. PREDICTIONS message: run all 9 strategies fresh (Trend Following,
     Price Action, SMC, ICT, Supply & Demand, Breakout & Retest, Range
     Trading, Day Trading, News Trading), send every one of them —
     directional call + entry/SL/TP/confidence/reasoning — to Telegram.
  3. Save this cycle's predictions so next cycle can review them.
  4. Separately (not part of the messages above): if the combined CEO
     read clears the confidence bar, the existing risk-gated execution
     path (confirm/auto modes) can still act — this is about money
     movement, kept deliberately conservative regardless of how chatty
     the informational reports are.

IMPORTANT: leave EXECUTION_MODE="analysis_only" until you've watched the
predictions (and their review accuracy) for a good while.
"""

import logging
import time
import uuid

import ceo
import config
import data_feed
import indicators
import journal
import news_calendar
import prediction_tracker
import risk_manager
import strategies
import telegram_bot
from telegram_listener import PENDING_TRADES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

_state = {"trades_today": 0, "consecutive_losses": 0, "daily_pnl_pct": 0.0}


def run_cycle_for_symbol(symbol: str):
    data = data_feed.get_multi_timeframe_snapshot(symbol)
    ltf = data[config.PRIMARY_ENTRY_TF]
    last_close = ltf["close"].iloc[-1]

    # --- 1. REVIEW last cycle's predictions first (T-1) ---
    reviews = prediction_tracker.review_and_get_reports(symbol, last_close)
    review_text = telegram_bot.format_review_report(symbol, reviews)
    telegram_bot.send_plain_alert(review_text)
    log.info("%s: review sent (%d strategies reviewed)", symbol, len(reviews))

    # --- 2. Fresh PREDICTIONS this cycle (T) ---
    upcoming_events = news_calendar.get_upcoming_events_for_symbol(symbol)
    predictions = strategies.run_all(data, upcoming_events)

    predictions_text = telegram_bot.format_predictions_report(symbol, predictions)
    telegram_bot.send_plain_alert(predictions_text)
    log.info("%s: predictions sent (%d strategies)", symbol, len(predictions))

    # --- 3. Save this cycle's predictions for next cycle's review ---
    prediction_tracker.save_predictions(symbol, predictions)

    # --- 4. Separate, risk-gated execution path (not part of the 2 messages
    # above — this only fires if you're in confirm/auto mode AND confidence
    # clears the bar). Uses the same predictions as directional "votes." ---
    final = ceo.decide(predictions)
    if final["consensus"] == "WAIT" or final["confidence"] < config.MIN_CONFIDENCE_TO_ALERT:
        return
    if config.EXECUTION_MODE == "analysis_only":
        return  # informational reports above already cover this mode fully

    # --- hard news blackout for execution only (informational reports above
    # still show News Trading's read regardless — this only blocks money
    # movement right before a tracked high-impact event) ---
    blackout_event = next(
        (e for e in upcoming_events if 0 <= e["minutes_until"] <= config.NEWS_BLACKOUT_MINUTES), None
    )
    if blackout_event:
        log.warning("%s: execution blocked — %s in %d min", symbol, blackout_event["title"], blackout_event["minutes_until"])
        return

    direction = final["consensus"]
    atr_val = indicators.atr(ltf).iloc[-1]
    entry = last_close
    if direction == "BUY":
        sl, tp1, tp2 = entry - atr_val * 1.5, entry + atr_val * 3, entry + atr_val * 4.5
    else:
        sl, tp1, tp2 = entry + atr_val * 1.5, entry - atr_val * 3, entry - atr_val * 4.5

    rr = risk_manager.calc_rr(entry, sl, tp1)

    open_positions = []
    try:
        open_positions = data_feed.get_open_positions()
    except Exception:
        pass

    allowed, reason = risk_manager.check_hard_limits(_state["daily_pnl_pct"], len(open_positions))
    if not allowed:
        log.warning("Risk manager blocked trading: %s", reason)
        return
    if rr < config.MIN_RR_RATIO:
        log.info("%s: RR %.2f below minimum %.2f — not executing", symbol, rr, config.MIN_RR_RATIO)
        return

    lots = risk_manager.calc_position_size(account_equity=10000, entry=entry, stop_loss=sl, pip_value_per_lot=10.0)
    trade_id = str(uuid.uuid4())[:8]
    approvals = f"{len([p for p in predictions if p['vote'] == direction])}/{len(predictions)}"
    text = telegram_bot.format_trade_alert(symbol, final, entry, sl, tp1, tp2, rr, lots, approvals)

    journal.log_trade(
        trade_id=trade_id, symbol=symbol, direction=direction, entry=entry, sl=sl,
        tp=tp1, lots=lots, rr=rr, confidence=final["confidence"],
        agent_votes=predictions, executed=(config.EXECUTION_MODE == "auto"),
    )

    if config.EXECUTION_MODE == "confirm":
        PENDING_TRADES[trade_id] = {"symbol": symbol, "direction": direction, "lots": lots,
                                     "entry": entry, "sl": sl, "tp": tp1}
        telegram_bot.send_trade_alert_with_confirmation(text, trade_id)

    elif config.EXECUTION_MODE == "auto":
        if final["confidence"] >= config.MIN_CONFIDENCE_TO_AUTO_EXECUTE:
            import executor
            executor.place_order(symbol, direction, lots, entry, sl, tp1)
            telegram_bot.send_plain_alert(text + "\n\n_(auto-executed)_")
        else:
            telegram_bot.send_plain_alert(text + "\n\n_(confidence below auto-execute threshold — not sent to broker)_")

    _state["trades_today"] += 1


def main():
    connected = data_feed.connect()
    if not connected:
        log.warning("Running WITHOUT a live MT5 connection — data calls will fail.")

    telegram_bot.send_plain_alert(
        f"🟢 Bot started/restarted. Watching: {', '.join(config.SYMBOLS)}. "
        f"Reporting every {config.POLL_INTERVAL_SECONDS // 60} min "
        f"(2 messages per symbol: review + predictions)."
    )

    try:
        while True:
            for symbol in config.SYMBOLS:
                try:
                    run_cycle_for_symbol(symbol)
                except Exception as e:
                    log.exception("Error processing %s: %s", symbol, e)
            time.sleep(config.POLL_INTERVAL_SECONDS)
    finally:
        data_feed.shutdown()


if __name__ == "__main__":
    main()
