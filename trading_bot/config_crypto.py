"""Crypto market (BTC + ETH) — own DB, own Telegram bot. Uses ccxt, not MT5."""

import os

CRYPTO_EXCHANGE = os.getenv("CRYPTO_EXCHANGE", "binance")
CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT"]
CRYPTO_TIMEFRAMES = ["15m", "1h", "4h", "1d"]
CRYPTO_PRIMARY_ENTRY_TF = "15m"
CRYPTO_POLL_INTERVAL_SECONDS = 900

DB_PATH = os.getenv("CRYPTO_DB_PATH", "crypto_journal.db")
PREDICTIONS_DB_PATH = os.getenv("CRYPTO_PREDICTIONS_DB_PATH", "crypto_predictions.db")

TELEGRAM_BOT_TOKEN = os.getenv("CRYPTO_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("CRYPTO_TELEGRAM_CHAT_ID", "")

LEARNING_REPORT_EVERY_N_CYCLES = 4
