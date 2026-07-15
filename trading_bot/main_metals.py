"""
Metals bot — own Telegram bot, own database. Run with: python main_metals.py

What's in each report (ONE combined Telegram message per symbol):
  - Quick summary + guardrail-gated recommendation + always-directional
    "Trading Advisor" line (never just bare "wait" with nothing else)
  - Strategy table (all 9 strategies, sorted by confidence)
  - Real news headlines (Finnhub)
  - Review of last cycle's predictions (the visible learning loop)

Every 4 review cycles, a separate, smaller "Learning Report" is sent
instead — a step back from the noise to summarize which strategies are
earning/losing trust and what the overall market lean has been.

Safety: this system is ASSISTED, not AUTONOMOUS. EXECUTION_MODE defaults
to analysis_only. The guardrail (guardrail.py) enforces hard, deterministic
risk rules that no LLM output can override. If the daily drawdown limit is
breached, this bot SHUTS DOWN entirely (not just skips a trade) and alerts
you — matching the "set hard bounds, shut down on max daily drawdown"
principle. You restart it manually after reviewing what happened.
"""

import logging
import time

import ceo
import chart_generator
import config
import config_metals as market
import data_feed
import guardrail
import indicators
import llm_client
import market_hours
import news_calendar
import news_sentiment
import prediction_tracker
import regime_engine
import risk_manager
import strategies
import telegram_bot
import vision_strategy
from agents import devils_advocate_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main_metals")

# Apply this market's overrides onto the shared config module. Safe because
# this runs as its own separate OS process — metals/crypto have their own.
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
_market_status = {}  # symbol -> bool (last known open/closed state), for transition-only alerts


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

    status = market_hours.is_market_open(ltf, config.POLL_INTERVAL_SECONDS)
    was_open = _market_status.get(symbol, True)

    if not status["open"]:
        if was_open:  # just transitioned from open -> closed — notify once
            telegram_bot.send_plain_alert(
                f"🌙 *{symbol}* — Market closed. {status['reason']}. Pausing predictions until it reopens.",
                token=TG_TOKEN, chat_id=TG_CHAT,
            )
        _market_status[symbol] = False
        log.info("%s: market closed (%s) — skipping cycle entirely", symbol, status["reason"])
        return

    if not was_open:  # just transitioned from closed -> open — notify once
        telegram_bot.send_plain_alert(f"🔔 *{symbol}* — Market reopened. Resuming predictions.",
                                       token=TG_TOKEN, chat_id=TG_CHAT)
    _market_status[symbol] = True

    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    reviews = prediction_tracker.review_and_get_reports(PREDICTIONS_DB_PATH, symbol, last_close)

    upcoming_events = news_calendar.get_upcoming_events_for_symbol(symbol)
    predictions = strategies.run_all(data, upcoming_events)

    # --- Optional 10th strategy: Chart Vision. Only runs if VISION_MODEL is
    # configured. Uses an UNMARKED chart (no entry/SL/TP overlay) so its
    # read isn't anchored to our own system's proposed levels — it reads
    # the raw price action independently, like the other 9 strategies do
    # from numbers. Tracked in prediction_tracker exactly like the rest. ---
    if vision_strategy.is_enabled():
        try:
            raw_chart_path = chart_generator.generate_chart(symbol, ltf, bars=60)
            vision_result = vision_strategy.chart_vision(data, raw_chart_path)
            predictions.append(vision_result)
        except Exception as e:
            log.warning("Chart Vision strategy failed this cycle, skipping: %s", e)

    prediction_tracker.save_predictions(PREDICTIONS_DB_PATH, symbol, predictions)

    sentiment = news_sentiment.get_symbol_sentiment(symbol)

    strategy_names = [p["name"] for p in predictions]
    base_weights = ceo.get_dynamic_weights(PREDICTIONS_DB_PATH, symbol, strategy_names)
    dynamic_weights, regime, session = regime_engine.apply_regime_and_session_adjustment(base_weights, ltf)

    # Preliminary direction (no Devil's Advocate yet) so it knows which side to attack
    prelim = ceo.decide(predictions, weights=dynamic_weights)
    lean_direction = prelim["consensus"] if prelim["consensus"] != "WAIT" else "BUY"
    devils_result = devils_advocate_agent(data, lean_direction)

    final = ceo.decide(predictions, weights=dynamic_weights, devils_advocate_result=devils_result,
                        devils_advocate_veto_min_confidence=config.DEVILS_ADVOCATE_VETO_MIN_CONFIDENCE)

    direction = final["consensus"] if final["consensus"] != "WAIT" else "BUY"

    # --- Entry: prefer an FVG-boundary LIMIT entry from the winning
    # direction's SMC/ICT call over chasing the market price, when available ---
    fvg_candidates = [p for p in predictions if p["name"] in ("SMC", "ICT")
                       and p["vote"] == direction and p.get("fvg_boundary") is not None]
    use_limit_entry = bool(fvg_candidates)
    entry = fvg_candidates[0]["fvg_boundary"] if use_limit_entry else last_close
    has_confirmation = indicators.detect_micro_rejection(ltf, entry, direction) if use_limit_entry else False

    if direction == "BUY":
        sl, tp1 = entry - atr_val * 1.5, entry + atr_val * 3
    else:
        sl, tp1 = entry + atr_val * 1.5, entry - atr_val * 3

    open_positions = []
    try:
        open_positions = data_feed.get_open_positions()
    except Exception:
        pass

    current_spread = None
    try:
        current_spread = data_feed.get_spread_pips(symbol)
    except Exception:
        pass

    guardrail_result = guardrail.check(
        symbol=symbol, direction=direction, entry=entry, sl=sl, tp=tp1,
        account_equity=10000, open_positions_count=len(open_positions),
        daily_pnl_pct=_state["daily_pnl_pct"], consecutive_losses=_state["consecutive_losses"],
        trades_today=_state["trades_today"], upcoming_news_events=upcoming_events, ltf_df=ltf,
        htf_df=data["H4"], current_spread_pips=current_spread,
        is_anticipation_entry=use_limit_entry, has_confirmation=has_confirmation,
    )
    guardrail_result["reasons"].append(f"Regime: {regime}, Session: {session}")
    if use_limit_entry:
        guardrail_result["reasons"].append(f"Entry style: LIMIT @ FVG boundary {entry} (not chasing market price)")

    report_text = telegram_bot.format_full_report(
        symbol, reviews, predictions, final, guardrail_result, sentiment.get("headlines"),
        strategy_weights=dynamic_weights,
    )
    telegram_bot.send_long_alert(report_text, token=TG_TOKEN, chat_id=TG_CHAT)

    # --- Screenshot: the same chart, now marked with the actual
    # recommended entry/SL/TP for this cycle, sent as its own photo message
    # (Telegram platform limit: photos can't be embedded in a text message). ---
    try:
        marked_chart_path = chart_generator.generate_chart(
            symbol, ltf, entry=entry, sl=sl, tp=tp1, direction=final["consensus"], bars=60,
        )
        caption = f"{symbol} — CEO: {final['consensus']} ({final['confidence']}%)"
        telegram_bot.send_photo(marked_chart_path, caption=caption, token=TG_TOKEN, chat_id=TG_CHAT)
    except Exception as e:
        log.warning("Chart screenshot generation/send failed this cycle: %s", e)

    log.info("%s: report sent — CEO %s (%s%%), guardrail %s",
              symbol, final["consensus"], final["confidence"], "ALLOWED" if guardrail_result["allowed"] else "BLOCKED")

    maybe_send_learning_report(symbol, predictions)

    # --- Actual execution — only in confirm/auto modes, only if guardrail allows.
    # Position size now uses the REAL risk %, scaled by the guardrail's
    # size_multiplier (structural lock) and risk_multiplier (pre-news window)
    # — not a hardcoded placeholder. ---
    if config.EXECUTION_MODE != "analysis_only" and guardrail_result["allowed"] and \
       final["consensus"] != "WAIT" and final["confidence"] >= config.MIN_CONFIDENCE_TO_ALERT:

        effective_risk_pct = config.RISK_PER_TRADE_PCT * guardrail_result["size_multiplier"] * guardrail_result["risk_multiplier"]
        lots = risk_manager.calc_position_size(
            account_equity=10000, entry=entry, stop_loss=sl,
            pip_value_per_lot=10.0,  # TODO: replace with real mt5.symbol_info(symbol) pip value before going live
            risk_pct=effective_risk_pct,
        )

        import uuid
        trade_id = str(uuid.uuid4())[:8]
        approvals = f"{sum(1 for p in predictions if p['vote'] == final['consensus'])}/{len(predictions)}"
        alert_text = telegram_bot.format_trade_alert(symbol, final, entry, sl, tp1, tp1, guardrail_result["rr"], lots, approvals)

        if config.EXECUTION_MODE == "confirm":
            from telegram_listener import PENDING_TRADES
            PENDING_TRADES[trade_id] = {"symbol": symbol, "direction": final["consensus"], "lots": lots,
                                         "entry": entry, "sl": sl, "tp": tp1}
            telegram_bot.send_trade_alert_with_confirmation(alert_text, trade_id, token=TG_TOKEN, chat_id=TG_CHAT)

        elif config.EXECUTION_MODE == "auto" and final["confidence"] >= config.MIN_CONFIDENCE_TO_AUTO_EXECUTE:
            import executor
            if use_limit_entry:
                executor.place_limit_order(symbol, final["consensus"], lots, entry, sl, tp1)
            else:
                executor.place_order(symbol, final["consensus"], lots, entry, sl, tp1)
            telegram_bot.send_plain_alert(alert_text + "\n\n_(auto-executed)_", token=TG_TOKEN, chat_id=TG_CHAT)

        _state["trades_today"] += 1

    # --- Kill-switch: hard shutdown on daily drawdown breach, not just a skip ---
    if any("Daily loss limit" in r for r in guardrail_result["reasons"]):
        _shutdown["triggered"] = True
        telegram_bot.send_plain_alert(
            f"🛑 *{symbol}* — Daily drawdown limit hit. Bot is SHUTTING DOWN, not just skipping this trade. "
            f"Review what happened before restarting manually.",
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
