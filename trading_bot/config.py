"""
Central configuration. Copy this to config_local.py and fill in your real
values — never commit real keys/passwords to version control.
"""

import os

# ---------------------------------------------------------------------------
# MT5 / Exness connection
# ---------------------------------------------------------------------------
# Exness MT5 terminal must be installed and logged in on this machine.
# The MetaTrader5 python package talks to the *running terminal*, not the
# cloud, so this only works on Windows (or a Windows VPS/VM).
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "Exness-MT5Trial")  # check your account
MT5_TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")  # optional, auto-detect if blank

# ---------------------------------------------------------------------------
# Symbols & timeframes
# ---------------------------------------------------------------------------
SYMBOLS = ["EURUSD","XAUUSD"]
TIMEFRAMES = ["M15", "H1", "H4", "D1"]  # multi-timeframe context per agent
PRIMARY_ENTRY_TF = "M15"

# ---------------------------------------------------------------------------
# LLM backend (optional — agents work with pure rule-based logic if this is
# left as "none". Free options: local Ollama model, or a free-tier API.)
# ---------------------------------------------------------------------------
LLM_BACKEND = os.getenv("LLM_BACKEND", "none")  # "none" | "ollama" | "openrouter"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Execution mode — START ON "analysis_only". Do not skip the graduation path.
# ---------------------------------------------------------------------------
# "analysis_only"  -> Telegram alerts only, nothing touches the account
# "confirm"        -> Telegram alert with Yes/No buttons, you approve each trade
# "auto"           -> bot places the order automatically after CEO approval
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "analysis_only")

# ---------------------------------------------------------------------------
# Risk management (hard limits — Risk Manager agent enforces these)
# ---------------------------------------------------------------------------
RISK_PER_TRADE_PCT = 0.5        # % of account equity risked per trade
MAX_DAILY_LOSS_PCT = 2.0        # stop trading for the day past this
MAX_OPEN_TRADES = 2
MIN_RR_RATIO = 2.0              # reject trades below this reward:risk
MIN_CONFIDENCE_TO_ALERT = 65    # % - below this, don't even notify
MIN_CONFIDENCE_TO_AUTO_EXECUTE = 80
NEWS_BLACKOUT_MINUTES = 15      # no new trades within N minutes of high-impact news

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "trading_journal.db")

# ---------------------------------------------------------------------------
# Loop timing
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 900 
