"""Forex market — own DB, own Telegram bot. Plain constants only; main_forex.py
applies these onto the shared config module at startup (safe: separate process)."""

import os

SYMBOLS = ["EURUSD", "GBPUSD"]
TIMEFRAMES = ["M15", "H1", "H4", "D1"]
PRIMARY_ENTRY_TF = "M15"
POLL_INTERVAL_SECONDS = 900

DB_PATH = os.getenv("FOREX_DB_PATH", "forex_journal.db")
PREDICTIONS_DB_PATH = os.getenv("FOREX_PREDICTIONS_DB_PATH", "forex_predictions.db")

TELEGRAM_BOT_TOKEN = os.getenv("FOREX_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("FOREX_TELEGRAM_CHAT_ID", "")

LEARNING_REPORT_EVERY_N_CYCLES = 4
