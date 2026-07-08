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
SYMBOLS = ["EURUSD", "GBPUSD"]   # forex-only focus, two most liquid pairs
TIMEFRAMES = ["M15", "H1", "H4", "D1"]  # multi-timeframe context per strategy
PRIMARY_ENTRY_TF = "M15"

# ---------------------------------------------------------------------------
# Crypto (separate pipeline — uses ccxt + a real exchange's public API,
# NOT MetaTrader5. Most MT5 servers don't offer USDT pairs at all.)
# ---------------------------------------------------------------------------
CRYPTO_EXCHANGE = os.getenv("CRYPTO_EXCHANGE", "binance")   # any ccxt-supported exchange id
CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"]
CRYPTO_TIMEFRAMES = ["15m", "1h", "4h", "1d"]   # ccxt timeframe strings
CRYPTO_PRIMARY_ENTRY_TF = "15m"
CRYPTO_POLL_INTERVAL_SECONDS = 900   # 15 min, matches entry timeframe

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
MAX_CONSECUTIVE_LOSSES = 3      # cooldown trigger for the guardrail
MAX_TRADES_PER_DAY = 5          # hard overtrading cap, enforced in guardrail.py
BLOCK_TRADES_IN_HIGH_VOLATILITY = False  # now handled by regime-switching (regime_engine.py) instead of a blanket block
DEVILS_ADVOCATE_VETO_MIN_CONFIDENCE = 65   # only a CONFIDENT rejection hard-blocks a trade
STRUCTURAL_LOCK_SIZE_REDUCTION = 0.25      # when H4 trend conflicts with M15 structure, trade at 25% of normal size (not fully blocked)
SPREAD_MAX_PIPS = 3.0                       # halt execution if broker spread widens beyond this (protects against slippage)
PRE_NEWS_RISK_REDUCTION_MINUTES = 30        # start reducing risk this many minutes before high-impact news
PRE_NEWS_RISK_MULTIPLIER = 0.5              # risk-per-trade multiplier during the pre-news window

# ---------------------------------------------------------------------------
# News sentiment (Finnhub — free tier, needs a free API key)
# ---------------------------------------------------------------------------
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "trading_journal.db")
PREDICTIONS_DB_PATH = os.getenv("PREDICTIONS_DB_PATH", "predictions.db")

# ---------------------------------------------------------------------------
# News calendar (real feed — public, free, no API key required)
# ---------------------------------------------------------------------------
NEWS_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEWS_KEYWORDS = ["Non-Farm", "NFP", "CPI", "FOMC", "Interest Rate", "GDP"]
NEWS_HIGH_IMPACT_ONLY = True

# ---------------------------------------------------------------------------
# Loop timing
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 900   # 15 min — matches PRIMARY_ENTRY_TF
