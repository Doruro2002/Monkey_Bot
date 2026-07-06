"""Metals market (Gold + Silver) — own DB, own Telegram bot."""

import os

SYMBOLS = ["XAUUSD", "XAGUSD"]   # Gold, Silver — check both exist in your MT5 Market Watch
TIMEFRAMES = ["M15", "H1", "H4", "D1"]
PRIMARY_ENTRY_TF = "M15"
POLL_INTERVAL_SECONDS = 900

DB_PATH = os.getenv("METALS_DB_PATH", "metals_journal.db")
PREDICTIONS_DB_PATH = os.getenv("METALS_PREDICTIONS_DB_PATH", "metals_predictions.db")

TELEGRAM_BOT_TOKEN = os.getenv("METALS_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("METALS_TELEGRAM_CHAT_ID", "")

LEARNING_REPORT_EVERY_N_CYCLES = 4
