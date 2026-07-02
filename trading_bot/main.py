"""
Main loop. Run with:  python main.py

Flow per symbol, each cycle:
  1. Pull multi-timeframe data (data_feed)
  2. Run all trader agents (agents)
  3. CEO combines votes into a consensus + confidence (ceo)
  4. Risk Manager applies hard vetoes (risk_manager)
  5. Psychology agent checks for overtrading
  6. If approved: send Telegram alert, and execute per EXECUTION_MODE
  7. Log everything to the journal (journal)

IMPORTANT: leave EXECUTION_MODE="analysis_only" until you've watched the
alerts for at least a few weeks and are confident in the logic.
"""

import logging
import time
import uuid

import agents
import ceo
import config
import data_feed
import indicators
import journal
import risk_manager
import telegram_bot
from telegram_listener import PENDING_TRADES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

# session-state counters (reset daily in a real deployment — kept simple here)
_state = {
    "trades_today": 0,
    "consecutive_losses": 0,
    "daily_pnl_pct": 0.0,
}


def get_upcoming_news() -> list:
    """Plug in a real economic calendar source here (e.g. an API/scrape of
    a forex factory-style calendar). Returning [] disables the news veto."""
    return []


def run_cycle_for_symbol(symbol: str):
    data = data_feed.get_multi_timeframe_snapshot(symbol)
    ltf = data[config.PRIMARY_ENTRY_TF]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    # --- run all 6 traders (Structure, ICT, Quant, News, Psychology, and
    # Devil's Advocate as the 6th — a genuine contrarian perspective, not a
    # veto-only role in how it's reported here) ---
    core_votes = [
        agents.structure_agent(data),
        agents.ict_agent(data),
        agents.quant_agent(data),
        agents.news_agent(get_upcoming_news(), data),
        agents.psychology_agent(_state["trades_today"], _state["consecutive_losses"]),
    ]

    # CEO's directional read, used to give Devil's Advocate something to
    # argue against — but this does NOT gate whether you get notified.
    prelim = ceo.decide(core_votes)
    lean_direction = prelim["consensus"] if prelim["consensus"] != "WAIT" else "BUY"
    devils = agents.devils_advocate_agent(data, lean_direction)

    all_votes = core_votes + [devils]
    final_with_devils = ceo.decide(all_votes)

    # --- ALWAYS send the team report, every cycle, regardless of agreement ---
    report_text = telegram_bot.format_team_report(symbol, all_votes, final_with_devils)
    telegram_bot.send_plain_alert(report_text)
    log.info("%s: report sent — CEO read %s (%s%%)", symbol, final_with_devils["consensus"], final_with_devils["confidence"])

    # --- everything below this line is about whether to actually TRADE,
    # not about whether to notify you. This gating stays in place because
    # it controls money movement, not information. ---
    if final_with_devils["consensus"] == "WAIT" or final_with_devils["confidence"] < config.MIN_CONFIDENCE_TO_ALERT:
        return

    direction = final_with_devils["consensus"]
    entry = last_close
    if direction == "BUY":
        sl = entry - atr_val * 1.5
        tp1 = entry + atr_val * 3
        tp2 = entry + atr_val * 4.5
    else:
        sl = entry + atr_val * 1.5
        tp1 = entry - atr_val * 3
        tp2 = entry - atr_val * 4.5

    rr = risk_manager.calc_rr(entry, sl, tp1)

    # --- risk manager veto (hard) ---
    open_positions = []
    try:
        open_positions = data_feed.get_open_positions()
    except Exception:
        pass  # analysis-only mode without MT5 connected

    allowed, reason = risk_manager.check_hard_limits(_state["daily_pnl_pct"], len(open_positions))
    if not allowed:
        log.warning("Risk manager blocked trading: %s", reason)
        return

    risk_check = agents.risk_agent(
        account_equity=10000,  # replace with data_feed.get_account_info()["equity"] when live
        open_positions=open_positions,
        daily_pnl_pct=_state["daily_pnl_pct"],
        proposed_rr=rr,
        min_rr=config.MIN_RR_RATIO,
        max_open=config.MAX_OPEN_TRADES,
        max_daily_loss_pct=config.MAX_DAILY_LOSS_PCT,
    )
    if risk_check["vote"] not in ("APPROVE",):
        log.info("%s: risk manager said %s — %s", symbol, risk_check["vote"], risk_check["reasons"])
        return

    lots = risk_manager.calc_position_size(
        account_equity=10000, entry=entry, stop_loss=sl, pip_value_per_lot=10.0
    )

    trade_id = str(uuid.uuid4())[:8]
    approvals = f"{len([v for v in all_votes if v['vote'] in ('BUY', 'SELL', 'APPROVE', 'PASS')])}/{len(all_votes)}"
    text = telegram_bot.format_trade_alert(symbol, final_with_devils, entry, sl, tp1, tp2, rr, lots, approvals)

    journal.log_trade(
        trade_id=trade_id, symbol=symbol, direction=direction, entry=entry, sl=sl,
        tp=tp1, lots=lots, rr=rr, confidence=final_with_devils["confidence"],
        agent_votes=all_votes, executed=(config.EXECUTION_MODE == "auto"),
    )

    if config.EXECUTION_MODE == "analysis_only":
        telegram_bot.send_plain_alert(text + "\n\n_(analysis_only — nothing executed)_")

    elif config.EXECUTION_MODE == "confirm":
        PENDING_TRADES[trade_id] = {
            "symbol": symbol, "direction": direction, "lots": lots,
            "entry": entry, "sl": sl, "tp": tp1,
        }
        telegram_bot.send_trade_alert_with_confirmation(text, trade_id)

    elif config.EXECUTION_MODE == "auto":
        if final_with_devils["confidence"] >= config.MIN_CONFIDENCE_TO_AUTO_EXECUTE:
            import executor
            executor.place_order(symbol, direction, lots, entry, sl, tp1)
            telegram_bot.send_plain_alert(text + "\n\n_(auto-executed)_")
        else:
            telegram_bot.send_plain_alert(text + "\n\n_(confidence below auto-execute threshold — not sent to broker)_")

    _state["trades_today"] += 1


def main():
    connected = data_feed.connect()
    if not connected:
        log.warning("Running WITHOUT a live MT5 connection — data calls will fail. "
                     "This is expected on non-Windows dev machines; wire up MT5 on your live host.")

    try:
        while True:
            for symbol in config.SYMBOLS:
                try:
                    run_cycle_for_symbol(symbol)
                except Exception as e:
                    log.exception("Error processing %s: %s", symbol, e)
            time.sleep(config.POLL_INTERVAL_SECONDS)
    finally:
        data_feed.shutdown()


if __name__ == "__main__":
    main()