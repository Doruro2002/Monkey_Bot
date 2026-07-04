"""
Crypto version of main.py. Run with:  python main_crypto.py

Same strategy engine (strategies.py) and prediction-tracking/learning loop
(prediction_tracker.py) as the forex bot — just pointed at real crypto
exchange data via ccxt instead of MT5.

With 5 symbols x 2 messages (review + predictions) each, that's 10 Telegram
messages per cycle. Consider raising CRYPTO_POLL_INTERVAL_SECONDS in
config.py if that's too chatty, or trimming CRYPTO_SYMBOLS to fewer coins.

No live order execution is wired up here — this is analysis/predictions
only. Placing real crypto orders needs an authenticated exchange API key
with trading permissions, which is a separate, bigger step (and real
exchange funds, since most exchanges don't offer a standardized "demo"
account the way MT5 brokers do — some, like Binance, have a separate
testnet you'd need to set up independently). Get comfortable with the
predictions and their tracked accuracy first.
"""

import logging
import time

import config
import crypto_data_feed
import news_calendar
import prediction_tracker
import strategies
import telegram_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main_crypto")


def run_cycle_for_symbol(symbol: str):
    data = crypto_data_feed.get_multi_timeframe_snapshot(symbol)
    ltf = data[config.PRIMARY_ENTRY_TF] if config.PRIMARY_ENTRY_TF in data else data["M15"]
    last_close = ltf["close"].iloc[-1]

    # --- 1. REVIEW last cycle's predictions first (T-1) ---
    reviews = prediction_tracker.review_and_get_reports(symbol, last_close)
    telegram_bot.send_plain_alert(telegram_bot.format_review_report(symbol, reviews))
    log.info("%s: review sent (%d strategies reviewed)", symbol, len(reviews))

    # --- 2. Fresh PREDICTIONS this cycle (T) ---
    # No forex-style macro calendar filter applied for crypto by default —
    # pass [] unless you want to wire in crypto-specific event tracking.
    predictions = strategies.run_all(data, upcoming_events=[])
    telegram_bot.send_plain_alert(telegram_bot.format_predictions_report(symbol, predictions))
    log.info("%s: predictions sent (%d strategies)", symbol, len(predictions))

    # --- 3. Save for next cycle's review ---
    prediction_tracker.save_predictions(symbol, predictions)


def main():
    if not crypto_data_feed.connect():
        log.error("Could not connect to %s — check ccxt is installed and the exchange id is correct.",
                   config.CRYPTO_EXCHANGE)
        return

    telegram_bot.send_plain_alert(
        f"🟢 Crypto bot started. Watching: {', '.join(config.CRYPTO_SYMBOLS)} on {config.CRYPTO_EXCHANGE}. "
        f"Reporting every {config.CRYPTO_POLL_INTERVAL_SECONDS // 60} min."
    )

    try:
        while True:
            for symbol in config.CRYPTO_SYMBOLS:
                try:
                    run_cycle_for_symbol(symbol)
                except Exception as e:
                    log.exception("Error processing %s: %s", symbol, e)
            time.sleep(config.CRYPTO_POLL_INTERVAL_SECONDS)
    finally:
        crypto_data_feed.shutdown()


if __name__ == "__main__":
    main()
