"""
Main loop. Run with:  python main.py

Architecture (brain vs. calculator, as requested):
  - strategies.py (+ LLM via agents._llm_reason_directional) = the BRAIN.
    It only ever proposes a direction, a confidence, and a narrative. It
    never touches account state, position sizing, or the final go/no-go.
  - guardrail.py = the CALCULATOR. Deterministic, fixed rules in plain
    Python. No LLM output can override anything it decides. This is the
    layer that actually protects your account.
  - ceo.py = combines strategy votes into one consensus, using weights that
    are increasingly based on each strategy's OWN tracked accuracy per
    symbol (ceo.get_dynamic_weights) — this is the real learning loop.

One combined Telegram message per symbol per cycle (not split into
review/predictions separately anymore) — summary and recommended action
at the top, full detail below, review of last cycle at the bottom.
Telegram's 4096-char hard limit means very rare edge cases may still need
a second message; telegram_bot.send_long_alert() handles that automatically.
"""

import logging
import time
import uuid

import ceo
import config
import data_feed
import executor
import guardrail
import indicators
import journal
import news_calendar
import news_sentiment
import prediction_tracker
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
    atr_val = indicators.atr(ltf).iloc[-1]

    # --- Review last cycle's predictions (the visible learning loop) ---
    reviews = prediction_tracker.review_and_get_reports(symbol, last_close)

    # --- Fresh predictions from all 9 strategies (the "brain") ---
    upcoming_events = news_calendar.get_upcoming_events_for_symbol(symbol)
    predictions = strategies.run_all(data, upcoming_events)
    prediction_tracker.save_predictions(symbol, predictions)

    # --- Real news headlines (never invented by the LLM) ---
    sentiment = news_sentiment.get_symbol_sentiment(symbol)

    # --- CEO consensus, weighted by each strategy's OWN tracked accuracy ---
    strategy_names = [p["name"] for p in predictions]
    dynamic_weights = ceo.get_dynamic_weights(symbol, strategy_names)
    final = ceo.decide(predictions, weights=dynamic_weights)

    # --- Guardrail: the deterministic calculator, always evaluated so the
    # report can show its verdict, even if the CEO consensus is weak/WAIT ---
    direction = final["consensus"] if final["consensus"] != "WAIT" else "BUY"
    entry = last_close
    if direction == "BUY":
        sl, tp1 = entry - atr_val * 1.5, entry + atr_val * 3
    else:
        sl, tp1 = entry + atr_val * 1.5, entry - atr_val * 3

    open_positions = []
    try:
        open_positions = data_feed.get_open_positions()
    except Exception:
        pass

    guardrail_result = guardrail.check(
        symbol=symbol, direction=direction, entry=entry, sl=sl, tp=tp1,
        account_equity=10000, open_positions_count=len(open_positions),
        daily_pnl_pct=_state["daily_pnl_pct"], consecutive_losses=_state["consecutive_losses"],
        trades_today=_state["trades_today"], upcoming_news_events=upcoming_events, ltf_df=ltf,
    )

    # --- ONE combined message per symbol ---
    report_text = telegram_bot.format_full_report(
        symbol, reviews, predictions, final, guardrail_result, sentiment.get("headlines")
    )
    telegram_bot.send_long_alert(report_text)
    log.info("%s: report sent — CEO %s (%s%%), guardrail %s",
              symbol, final["consensus"], final["confidence"], "ALLOWED" if guardrail_result["allowed"] else "BLOCKED")

    # --- Actual execution, only in confirm/auto modes, only if guardrail allows ---
    if config.EXECUTION_MODE == "analysis_only":
        return
    if final["consensus"] == "WAIT" or final["confidence"] < config.MIN_CONFIDENCE_TO_ALERT:
        return
    if not guardrail_result["allowed"]:
        return

    lots_placeholder = 0.01  # replace with risk_manager.calc_position_size using real pip value before going live
    trade_id = str(uuid.uuid4())[:8]
    approvals = f"{sum(1 for p in predictions if p['vote'] == final['consensus'])}/{len(predictions)}"
    alert_text = telegram_bot.format_trade_alert(symbol, final, entry, sl, tp1, tp1, guardrail_result["rr"], lots_placeholder, approvals)

    journal.log_trade(
        trade_id=trade_id, symbol=symbol, direction=final["consensus"], entry=entry, sl=sl,
        tp=tp1, lots=lots_placeholder, rr=guardrail_result["rr"], confidence=final["confidence"],
        agent_votes=predictions, executed=(config.EXECUTION_MODE == "auto"),
    )

    if config.EXECUTION_MODE == "confirm":
        PENDING_TRADES[trade_id] = {"symbol": symbol, "direction": final["consensus"], "lots": lots_placeholder,
                                     "entry": entry, "sl": sl, "tp": tp1}
        telegram_bot.send_trade_alert_with_confirmation(alert_text, trade_id)

    elif config.EXECUTION_MODE == "auto":
        if final["confidence"] >= config.MIN_CONFIDENCE_TO_AUTO_EXECUTE:
            executor.place_order(symbol, final["consensus"], lots_placeholder, entry, sl, tp1)
            telegram_bot.send_plain_alert(alert_text + "\n\n_(auto-executed)_")
        else:
            telegram_bot.send_plain_alert(alert_text + "\n\n_(confidence below auto-execute threshold — not sent to broker)_")

    _state["trades_today"] += 1


def main():
    connected = data_feed.connect()
    if not connected:
        log.warning("Running WITHOUT a live MT5 connection — data calls will fail.")

    telegram_bot.send_plain_alert(
        f"🟢 Bot started/restarted. Watching: {', '.join(config.SYMBOLS)}. "
        f"One combined report per symbol every {config.POLL_INTERVAL_SECONDS // 60} min."
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
