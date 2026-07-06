"""
Metals bot (Gold + Silver) — own Telegram bot, own database.
Run with: python main_metals.py

Identical architecture to main_forex.py — same MT5 connection can serve
both (most brokers offering forex also offer XAUUSD/XAGUSD), but tracked,
reported, and rate-limited completely separately with its own DB and bot.
"""

import logging
import time

import ceo
import config
import config_metals as market
import data_feed
import guardrail
import indicators
import llm_client
import news_calendar
import news_sentiment
import prediction_tracker
import strategies
import telegram_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main_metals")

config.SYMBOLS = market.SYMBOLS
config.TIMEFRAMES = market.TIMEFRAMES
config.PRIMARY_ENTRY_TF = market.PRIMARY_ENTRY_TF
config.POLL_INTERVAL_SECONDS = market.POLL_INTERVAL_SECONDS

DB_PATH = market.DB_PATH
PREDICTIONS_DB_PATH = market.PREDICTIONS_DB_PATH
TG_TOKEN = market.TELEGRAM_BOT_TOKEN
TG_CHAT = market.TELEGRAM_CHAT_ID

_state = {"trades_today": 0, "consecutive_losses": 0, "daily_pnl_pct": 0.0}
_shutdown = {"triggered": False}


def build_market_lean_summary(predictions: list) -> str:
    buy = sum(1 for p in predictions if p["vote"] == "BUY")
    sell = len(predictions) - buy
    return f"{buy} of {len(predictions)} strategies currently lean BUY" if buy >= sell else \
           f"{sell} of {len(predictions)} strategies currently lean SELL"


def maybe_send_learning_report(symbol: str, predictions: list):
    cycle_count = prediction_tracker.increment_and_check_cycle(PREDICTIONS_DB_PATH, symbol, every_n=market.LEARNING_REPORT_EVERY_N_CYCLES)
    if cycle_count % market.LEARNING_REPORT_EVERY_N_CYCLES != 0:
        return

    strategy_names = [p["name"] for p in predictions]
    accuracies = prediction_tracker.get_all_strategy_accuracies(PREDICTIONS_DB_PATH, symbol, strategy_names)
    market_lean = build_market_lean_summary(predictions)

    llm_summary = None
    if config.LLM_BACKEND != "none":
        prompt = (
            f"Over the last {market.LEARNING_REPORT_EVERY_N_CYCLES} review cycles for {symbol}, "
            f"here is each strategy's tracked accuracy: {accuracies}. Current lean: {market_lean}. "
            f"In 2 sentences, summarize what a research desk would take away from this and what "
            f"they think about the market today. Be concrete, no disclaimers."
        )
        llm_summary = llm_client.ask(prompt, system="You are a quantitative research analyst in a sandboxed "
                                                       "backtesting simulation, summarizing tracked performance data.")

    report = telegram_bot.format_learning_report(symbol, accuracies, market_lean, llm_summary)
    telegram_bot.send_long_alert(report, token=TG_TOKEN, chat_id=TG_CHAT)
    log.info("%s: learning report sent (cycle %d)", symbol, cycle_count)


def run_cycle_for_symbol(symbol: str):
    data = data_feed.get_multi_timeframe_snapshot(symbol)
    ltf = data[config.PRIMARY_ENTRY_TF]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    reviews = prediction_tracker.review_and_get_reports(PREDICTIONS_DB_PATH, symbol, last_close)

    upcoming_events = news_calendar.get_upcoming_events_for_symbol(symbol) if len(symbol) == 6 else []
    predictions = strategies.run_all(data, upcoming_events)
    prediction_tracker.save_predictions(PREDICTIONS_DB_PATH, symbol, predictions)

    sentiment = news_sentiment.get_symbol_sentiment(symbol)

    strategy_names = [p["name"] for p in predictions]
    dynamic_weights = ceo.get_dynamic_weights(PREDICTIONS_DB_PATH, symbol, strategy_names)
    final = ceo.decide(predictions, weights=dynamic_weights)

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

    report_text = telegram_bot.format_full_report(symbol, reviews, predictions, final, guardrail_result, sentiment.get("headlines"))
    telegram_bot.send_long_alert(report_text, token=TG_TOKEN, chat_id=TG_CHAT)
    log.info("%s: report sent — CEO %s (%s%%), guardrail %s",
              symbol, final["consensus"], final["confidence"], "ALLOWED" if guardrail_result["allowed"] else "BLOCKED")

    maybe_send_learning_report(symbol, predictions)

    if any("Daily loss limit" in r for r in guardrail_result["reasons"]):
        _shutdown["triggered"] = True
        telegram_bot.send_plain_alert(
            f"🛑 *{symbol}* — Daily drawdown limit hit. Bot is SHUTTING DOWN, not just skipping this trade. "
            f"Review before restarting manually.",
            token=TG_TOKEN, chat_id=TG_CHAT,
        )


def main():
    connected = data_feed.connect()
    if not connected:
        log.warning("Running WITHOUT a live MT5 connection — data calls will fail.")

    telegram_bot.send_plain_alert(
        f"🟢 Metals bot started. Watching: {', '.join(config.SYMBOLS)}. "
        f"Report every {config.POLL_INTERVAL_SECONDS // 60} min. Assisted mode — you make the final call.",
        token=TG_TOKEN, chat_id=TG_CHAT,
    )

    try:
        while not _shutdown["triggered"]:
            for symbol in config.SYMBOLS:
                try:
                    run_cycle_for_symbol(symbol)
                except Exception as e:
                    log.exception("Error processing %s: %s", symbol, e)
                if _shutdown["triggered"]:
                    break
            if not _shutdown["triggered"]:
                time.sleep(config.POLL_INTERVAL_SECONDS)
    finally:
        data_feed.shutdown()


if __name__ == "__main__":
    main()
