# AI Trading Assistant — Technical & Functional Documentation

**Status as of this document:** three independent, running systems (Forex, Metals, Crypto), each analysis-first, human-in-the-loop, with a real (not simulated) learning loop.

---

## 1. Core Philosophy

This is not an autonomous trading bot. It is an **assisted research system**. The design follows one non-negotiable split:

| Layer | Role | Can it be overridden? |
|---|---|---|
| **The Brain** (strategies + LLM reasoning) | Proposes a direction, a confidence, a narrative | Yes — freely, every cycle |
| **The Calculator** (`guardrail.py`, `risk_manager.py`) | Enforces hard, deterministic risk rules in plain Python | **No.** No LLM output, no matter how confident, can bypass it |

Nothing places a real trade until `EXECUTION_MODE` is explicitly changed from `analysis_only`, and even then, the guardrail can block execution regardless of what the strategies say.

---

## 2. The Three Markets

The system is split into **three fully independent processes**, each with its own:
- Telegram bot (own token + chat ID)
- SQLite database (journal + predictions)
- Symbol list

| Market | Script | Symbols | Data source |
|---|---|---|---|
| Forex | `main_forex.py` | EURUSD, GBPUSD | MetaTrader5 (MT5) |
| Metals | `main_metals.py` | XAUUSD, XAGUSD | MetaTrader5 (MT5) |
| Crypto | `main_crypto.py` | BTC/USDT, ETH/USDT | ccxt / Binance public API |

They can run simultaneously in three separate terminal windows, or independently at different times. Nothing is shared between them except the underlying Python modules (code, not data).

---

## 3. The Strategy Engine — 9 "Traders"

Every cycle, all 9 strategies analyze the same multi-timeframe price data (M15/H1/H4/D1) and each **always commits to BUY or SELL** — never a bare "wait." Weak conviction is expressed as a **low confidence score** (e.g. 20-30%), not an evasive non-answer.

1. **Trend Following** — H4/D1 EMA trend alignment
2. **Price Action** — nearest support/resistance, market structure (BOS)
3. **Smart Money Concepts (SMC)** — Fair Value Gaps, BOS/CHoCH, order flow
4. **ICT** — daily bias + imbalance confirmation, kill-zone style reasoning
5. **Supply & Demand** — proximity to demand/supply zones + trend confirmation
6. **Breakout & Retest** — detects a broken level being retested
7. **Range Trading** — buy support / sell resistance when the market isn't trending
8. **Day Trading** — M15/H1 intraday momentum alignment
9. **News Trading** — real economic calendar (NFP/CPI/FOMC/Interest Rate/GDP), honest about the fact that pre-release direction is a volatility flag, not a real edge

Each strategy returns: `vote`, `confidence`, `reasons` (technical facts), `strategy` (label), and deterministic `entry`/`sl`/`tp1`/`tp2` (computed from real ATR data — **never** invented by the LLM).

### LLM reasoning layer (`agents._llm_reason_directional`)
If `LLM_BACKEND` is set (Ollama local or OpenRouter cloud), each strategy's rule-based read is handed to an LLM with a system prompt framing it as a sandboxed quantitative research analyst — reducing refusals/hallucinations and keeping price data strictly grounded in what was actually computed, never recalled from memory. If no LLM backend is configured, the system runs entirely on the rule-based fallback logic (still fully functional).

---

## 4. The CEO — Consensus & Dynamic Weighting (`ceo.py`)

Combines all 9 strategy votes into one consensus + confidence score.

**Weighting is not fixed.** Two layers:
1. **Tier priors** (`regime_engine.TIER_PRIORS`) — an informed cold-start default (SMC/ICT trusted slightly more early on, as order-flow models), used only until a strategy has enough tracked history of its own.
2. **Real tracked accuracy** (`prediction_tracker.get_accuracy`) — once a strategy has 10+ reviewed predictions for a symbol, its actual win/loss record entirely overrides the tier prior. A strategy that's been wrong more often genuinely loses influence over time.

### Regime & session adjustment (`regime_engine.py`)
Weights are further adjusted (not silenced) based on:
- **Volatility regime** (high/normal/low) — e.g. SMC/ICT get more say in high volatility, Range Trading gets discounted
- **Trading session** (Asian/London/New York/overlap) — e.g. Range Trading favored in the low-volume Asian session, Breakout strategies favored in London/NY overlap

### Devil's Advocate veto (`agents.devils_advocate_agent`)
A dedicated contrarian check argues against the proposed direction. It only produces a **hard veto** (forces WAIT regardless of everything else) if its rejection confidence is ≥ `DEVILS_ADVOCATE_VETO_MIN_CONFIDENCE` (default 65%) — a weak objection doesn't override real confluence, only a confident one does.

---

## 5. The Guardrail — Deterministic Risk Rules (`guardrail.py`)

Runs every cycle, independent of any AI confidence. Checks (all evaluated, not short-circuited):

1. **Daily loss limit** — if breached, blocks all trading for the day (and triggers a full bot shutdown, not just a skip — see §9)
2. **Max concurrent trades**
3. **Minimum reward:risk ratio**
4. **Consecutive-loss cooldown**
5. **Daily trade cap** (overtrading protection)
6. **Hard news blackout** — no trades within `NEWS_BLACKOUT_MINUTES` of a tracked high-impact event
7. **Pre-news risk reduction** — a wider window before the blackout where risk is automatically halved, not fully blocked
8. **Structural lock** — if H4 trend conflicts with M15 structure, position size is reduced (not fully blocked) to 25%
9. **Spread invalidation** — blocks execution if the broker's spread has widened beyond a safe threshold
10. **Anticipation vs. confirmation sizing** — a limit entry placed at an FVG boundary with no price reaction yet gets 50% "probe" size; one with an observed rejection gets full size

---

## 6. Entry Logic — Limit vs. Market Orders

If the winning direction's SMC or ICT strategy references an **unfilled Fair Value Gap**, the system prefers a **limit order at that FVG boundary** over chasing the current market price (the "anticipation" entry — waiting for the retest). Otherwise, it uses a plain market-style entry at the current price. This directly reflects real trader practice (confirmation vs. anticipation tradeoffs), not blind order-chasing.

---

## 7. The Learning Loop (`prediction_tracker.py`)

This is the actual "learn from mistakes" system, and it is genuinely persistent (SQLite file, survives restarts):

1. **Every prediction is saved** with its entry price and reasoning.
2. **One cycle later, it's reviewed**: did price move in the predicted direction since entry? (This is a directional fast-feedback signal, not "did it hit take-profit" — documented honestly in the code.)
3. **Rolling accuracy per strategy per symbol** is computed from this review history and feeds directly into the CEO's dynamic weighting (§4).
4. **Every 4 review cycles**, a separate **Learning Report** is sent — a step back from the noise, ranking which strategies are earning/losing trust and giving a plain-language market lean.
5. **Top Combinations tracking** — the system tracks, from real history, which *groups* of strategies (pairs, triplets, quads, quintuplets) tend to agree together and how that agreement has actually performed. A combination only appears once it has 10+ real agreed-cycles — deliberately avoiding the false-precision trap of tiny-sample "100% win rate" claims (this was directly informed by catching exactly that mistake in an external AI-generated analysis earlier in this project's development).

---

## 8. What You Actually Receive on Telegram

**One combined message per symbol, every cycle** (default: every 15 minutes), containing, in order:
1. Quick Summary (BUY/SELL vote counts, core-strategy confluence alignment, CEO consensus)
2. 🎯 Recommended Action — the guardrail-gated real recommendation (can legitimately say NO TRADE)
3. 🧭 Trading Advisor — a separate line that **always** gives a directional lean, worded by conviction strength, never a bare "wait"
4. Strategy Table — all 9 strategies at a glance (monospace, aligned columns)
5. Top Combinations — pairs/triplets/quads/quintuplets with real tracked win rates
6. Live News Headlines (Finnhub, real data)
7. "Why" detail — each strategy's reasoning
8. Review of last cycle's predictions — did they move the right way, current rolling accuracy

Plus, separately:
- **Startup message** once per launch
- **Learning Report** every 4 cycles
- **Market closed/reopened** notifications (forex/metals only, transition-only, not spammed)
- **Kill-switch alert** if the daily drawdown limit is ever breached

---

## 9. Safety Architecture

- **`EXECUTION_MODE` defaults to `analysis_only`** — nothing touches your account regardless of anything else in the system.
- **`confirm` mode** — Telegram sends Yes/No buttons; only your explicit tap executes anything.
- **`auto` mode** — only fires if confidence clears a separate, higher bar (`MIN_CONFIDENCE_TO_AUTO_EXECUTE`), and only if the guardrail allows it.
- **Kill-switch**: if the daily drawdown limit is breached, the entire bot process **shuts down** (not just skips a trade) and alerts you. It does not restart itself — you review what happened and restart manually.
- **Market-hours detection** (`market_hours.py`, forex/metals only): skips analysis entirely on weekends, using both a calendar rule and a data-staleness check, so no predictions are generated on dead data.

---

## 10. Honest Limitations (please actually read this section)

- **The review heuristic is directional, not outcome-based.** "Correct" means price moved the right way one cycle later — not that a trade would have hit its actual take-profit. Treat tracked accuracy as a tendency indicator, not a win-rate.
- **Position sizing uses a placeholder pip value** (`pip_value_per_lot=10.0`) — needs replacing with a real value from `mt5.symbol_info()` before this should ever touch real money.
- **No live position tracking for crypto** — the crypto bot doesn't hold an authenticated exchange connection, so `open_positions_count` is always 0 there. Real crypto execution isn't wired up at all yet.
- **The LLM never invents price levels** — but it does generate the reasoning narrative, and local/free models can occasionally be less sharp than paid frontier models. Rule-based fallback logic still runs underneath regardless.
- **Small-sample combinations remain small-sample** even at the 10-cycle minimum — this reduces but doesn't eliminate the overfitting risk that motivated building the combination tracker this way in the first place.
- **This has not been extensively paper-traded over months yet** — per your own research, that's the real gate before any of this should touch a funded account.

---

## 11. File Map

```
config.py                 shared defaults (LLM, risk, Finnhub key, news calendar)
config_forex.py / config_metals.py / config_crypto.py   per-market overrides (symbols, DB paths, Telegram creds)

data_feed.py               MT5 market data (forex/metals)
crypto_data_feed.py        ccxt market data (crypto)
indicators.py               shared technical analysis (ATR, trend, S/R, FVG, breakout/retest, rejection detection)
market_hours.py              weekend/closed-market detection

agents.py                    shared LLM reasoning helper + Devil's Advocate
strategies.py                  the 9 strategy-traders
regime_engine.py                 tier priors, volatility/session weight adjustment
ceo.py                             consensus + dynamic weighting + veto logic
guardrail.py                        deterministic hard risk rules
risk_manager.py                      position sizing, RR calculation

news_calendar.py                      real economic calendar (forex/metals blackout)
news_sentiment.py                      real news headlines (Finnhub)

prediction_tracker.py                   the learning loop + combination tracking
journal.py                                trade execution history

telegram_bot.py                           all report formatting + sending
telegram_listener.py                        catches confirm-mode button presses
executor.py                                  places market/limit orders (MT5)

main_forex.py / main_metals.py / main_crypto.py   the three orchestrator loops
run_forever.bat                                     auto-restart wrapper
```

---

## 12. What Would Need to Happen Before This Touches Real Money

1. Weeks-to-months of `analysis_only` observation across all three markets
2. Real pip-value integration for position sizing (currently a placeholder)
3. A genuine authenticated crypto exchange connection if crypto execution is ever wanted
4. Manual review of every Learning Report and Top Combinations section — do the numbers actually hold up as more data accumulates, or do they regress toward 50% like the earlier external "AI report" did?
5. Only then, `confirm` mode on a demo account, then eventually (if ever) real funds — small, and only what you can afford to lose.
