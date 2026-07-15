# AI Trading Assistant — Forex / Metals / Crypto

**Notification-only by default. It never opens a trade automatically unless
you explicitly change `EXECUTION_MODE`.**

Three independent bots, each with its own Telegram bot and database:

| Market | Script | Symbols | Data source |
|---|---|---|---|
| Forex | `main_forex.py` | EURUSD, GBPUSD | MetaTrader5 |
| Metals | `main_metals.py` | XAUUSD, XAGUSD | MetaTrader5 |
| Crypto | `main_crypto.py` | BTC/USDT, ETH/USDT | ccxt/Binance |

> `main.py` is the old single-market version, kept only for reference —
> use the three scripts above instead.

## What it does

Every 15 minutes, per symbol, you get ONE Telegram message containing:
9 strategies' predictions (each with entry/SL/TP/confidence/reasoning),
a guardrail-checked recommendation, an always-directional "Trading
Advisor" line, real news headlines, tracked strategy-combination win
rates, and a review of the last cycle's predictions. Every 4 cycles, a
separate Learning Report shows which strategies are earning/losing trust.

## Install

```powershell
pip install -r requirements.txt
```

MetaTrader5 package is Windows-only. ccxt (crypto) works anywhere.

## Model

Recommended: **`qwen2.5:7b`** via **Ollama** (free, local, no API cost).

```powershell
# 1. Install Ollama from ollama.com
# 2. Pull the model
ollama pull qwen2.5:7b
# 3. Test it
ollama run qwen2.5:7b
```

## Required accounts (all free)

- **Telegram**: `@BotFather` → `/newbot` — do this **three times**, one bot per market
- **MT5**: a broker demo account (Exness, XM, IC Markets, etc.) for forex/metals
- **Finnhub**: free API key at finnhub.io/register — real news headlines
- **Binance**: no account needed — crypto data is public

## Run (one terminal window per market)

```powershell
# Forex
$env:MT5_LOGIN="..."; $env:MT5_PASSWORD="..."; $env:MT5_SERVER="..."
$env:FOREX_TELEGRAM_BOT_TOKEN="..."; $env:FOREX_TELEGRAM_CHAT_ID="..."
$env:FINNHUB_API_KEY="..."
$env:LLM_BACKEND="ollama"; $env:OLLAMA_MODEL="qwen2.5:7b"
python main_forex.py
```

Repeat for `main_metals.py` (swap `FOREX_` → `METALS_`) and `main_crypto.py`
(swap `FOREX_` → `CRYPTO_`, no MT5 vars needed).

Use `run_forever.bat` instead of `python main_forex.py` directly if you
want auto-restart on crash/interruption.

## Safety

`EXECUTION_MODE` defaults to `analysis_only` in `config.py` — no code path
can place a trade in this mode. Do not change this until you've watched
the predictions and their tracked accuracy for a meaningful stretch of
time (weeks, not hours).

See `PROJECT_DOCUMENTATION.md` for full technical/functional details.
