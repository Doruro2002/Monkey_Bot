# AI Trader Team — Multi-Agent Trading System for Exness/MT5

A multi-agent system that analyzes markets from several perspectives,
reaches a consensus with a confidence score, alerts you on Telegram, and
(only once you enable it) can place trades on your Exness account through
MT5.

**Read the whole README before running anything against a live account.**

## What this actually is

- 7 "agents": Market Structure, ICT/Smart Money, Quant, News, Risk Manager,
  Psychology, and a Devil's Advocate that tries to kill every trade idea.
- A CEO module that combines their votes into one decision + confidence %.
- A Telegram bot for alerts, with an optional Yes/No confirm step.
- A SQLite trade journal that records every decision and its reasoning.
- A Learning Engine that reviews *batches* of closed trades (not single
  losses) and adjusts how much the CEO trusts each agent over time.

## What it is NOT

- Not a system that is "always correct." No such system exists.
- Not financial advice, and I'm not a financial advisor.
- Not something that should touch real money on day one.

## Honest constraints of "totally free"

| Component | Free path | The catch |
|---|---|---|
| Reasoning | Rule-based logic (included, works today) or a local LLM via Ollama | Local LLMs need decent hardware (16GB+ RAM for a usable 7-8B model) |
| Reasoning (cloud) | OpenRouter free-tier models | Rate-limited, weaker than paid frontier models |
| Broker connection | `MetaTrader5` Python package | **Windows-only**, requires the Exness MT5 terminal installed and logged in and running at all times |
| 24/7 uptime | A cheap/free-tier VPS, or your own PC left on | A PC that sleeps or loses power kills the bot mid-trade |
| Market data | Comes free through MT5 itself | Good enough for this use case |
| News calendar | You need to wire one in — `agents.news_agent()` expects a list you supply | Free economic calendar APIs exist but you'll need to add the fetching code |

There is no combination of "free" + "fully automatic" + "guaranteed
correct." Pick two, realistically: free and automatic is achievable; free
and correct is not something anyone can promise.

## Setup

```bash
pip install -r requirements.txt
```

1. **MT5 / Exness**: install the Exness MT5 terminal on a Windows machine
   (or Windows VPS), log into your account, leave it running.
2. **Telegram**: message @BotFather → `/newbot` → copy the token. Message
   your new bot once, then hit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat id.
3. Set these as environment variables (or edit `config.py` directly):
   ```
   MT5_LOGIN=12345678
   MT5_PASSWORD=yourpassword
   MT5_SERVER=Exness-MT5Trial
   TELEGRAM_BOT_TOKEN=xxxx
   TELEGRAM_CHAT_ID=xxxx
   EXECUTION_MODE=analysis_only
   ```
4. Run it:
   ```bash
   python main.py
   ```
   If you're using `EXECUTION_MODE=confirm`, also run
   `python telegram_listener.py` alongside it (separate process/terminal).

## The graduation path — please actually follow this order

1. **`analysis_only`** for at least a few weeks. Watch every alert. Would
   you have taken that trade? Was the reasoning sound? Keep a manual log
   of whether you agree with the bot, separate from its own journal.
2. **`confirm`** — same alerts, but now you tap Yes/No and it executes
   through MT5. This is where you find out if the execution plumbing
   (lot sizing, SL/TP placement) actually works correctly, with you as
   the safety check.
3. **`auto`**, and only on a **demo/Exness Trial account first.** Only
   move to a real account after you've watched it operate correctly on
   demo for a meaningful stretch, and only with size you can afford to
   lose.

Skipping straight to `auto` on a funded account is how "free" becomes
very expensive very fast.

## Learning loop

Run this weekly (cron job, Task Scheduler, etc.), not inside the live loop:

```python
from learning import run_weekly_learning_cycle
result = run_weekly_learning_cycle()
print(result["report_text"])
```

This reviews closed trades, builds a per-agent accuracy scoreboard, and
recomputes the CEO's trust weights — feed `result["weights"]` back into
`ceo.decide(..., weights=result["weights"])` in `main.py` once you have
enough sample size (the code defaults to requiring 20+ reviewed trades
per agent before it trusts the new weight).

## Filling in the gaps (things I stubbed intentionally)

- **`agents.news_agent`** needs a real economic calendar feed — currently
  returns an empty list (no news veto) until you wire one in.
- **`risk_manager.calc_position_size`** needs the real pip value per lot
  for your symbol/account currency — pull it from
  `mt5.symbol_info(symbol)` rather than the placeholder `10.0` in `main.py`.
- **`data_feed.get_account_info()`** should replace the hardcoded
  `account_equity=10000` placeholders in `main.py` once you're connected
  to a real account.
- Entry/SL/TP logic in `main.py` is a simple ATR-multiple placeholder —
  each agent's own logic (order blocks, structure levels, etc.) should
  ultimately drive the actual levels, not one generic formula.

## Files

```
config.py            all settings
data_feed.py          MT5 multi-timeframe data
indicators.py          shared technical analysis helpers
llm_client.py           optional LLM wrapper (Ollama / OpenRouter free tier)
agents.py                the 7-agent trader team
ceo.py                     consensus + confidence + dynamic weights
risk_manager.py             position sizing + hard limits
telegram_bot.py               alerts + confirm buttons
telegram_listener.py            catches button presses -> executes
executor.py                       places/closes MT5 orders
journal.py                          SQLite trade history
learning.py                           batch review + scoreboard + reweighting
main.py                                  orchestrator loop
```

## Final honesty check

This is a legitimate, well-structured piece of trading software
engineering — the kind of layered, self-critiquing pipeline serious
quant teams actually build. It is not magic. Markets are probabilistic;
this system can help you make more disciplined, better-reasoned, better
risk-managed decisions — it cannot guarantee winning trades. Trade with
size you can afford to lose, and treat the first month of `analysis_only`
as the real test of whether this is worth trusting with money at all.
