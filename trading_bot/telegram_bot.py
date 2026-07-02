"""
Telegram notifications, with optional inline Yes/No confirmation for
EXECUTION_MODE == "confirm".

Setup:
  1. Message @BotFather on Telegram, /newbot, get your TELEGRAM_BOT_TOKEN.
  2. Message your new bot once, then visit
     https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat id.
  3. Put both in config.py / environment variables.
"""

import logging

import requests

import config

log = logging.getLogger("telegram_bot")

API_BASE = "https://api.telegram.org/bot{token}"


def _url(method: str) -> str:
    return f"{API_BASE.format(token=config.TELEGRAM_BOT_TOKEN)}/{method}"


def send_message(text: str, reply_markup: dict = None) -> dict:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — printing instead:\n%s", text)
        return {}

    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    resp = requests.post(_url("sendMessage"), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def format_team_report(symbol: str, agent_results: list, ceo_summary: dict = None) -> str:
    """Shows what every trader actually said, unfiltered — sent every cycle
    regardless of whether they agree. Directional traders (Structure, ICT,
    Quant, News) show full entry/SL/TP/strategy. Oversight agents (Risk,
    Psychology, DevilsAdvocate) show vote + reasoning only — they don't
    predict direction, so a fake price target would just be noise."""
    lines = [f"*{symbol}* — Team Report\n"]

    vote_emoji = {"BUY": "🟢", "SELL": "🔴", "WAIT": "⚪", "APPROVE": "✅",
                  "REJECT": "🚫", "PASS": "➡️"}

    for r in agent_results:
        emoji = vote_emoji.get(r["vote"], "⚪")
        header = f"{emoji} *{r['name']}*: {r['vote']}"
        if r.get("confidence") is not None:
            header += f" ({r['confidence']}%)"
        lines.append(header)

        if r.get("strategy"):
            lines.append(f"   Strategy: _{r['strategy']}_")

        if "entry" in r:  # directional trader — show the full trade case
            lines.append(f"   Entry: `{r['entry']}` | SL: `{r['sl']}` | TP1: `{r['tp1']}` | TP2: `{r['tp2']}`")

        if r.get("reasons"):
            reason_text = " ".join(r["reasons"]) if isinstance(r["reasons"], list) else str(r["reasons"])
            lines.append(f"   Why: _{reason_text}_")

    if ceo_summary:
        lines.append(f"\n*CEO read:* {ceo_summary['consensus']} ({ceo_summary['confidence']}%)")

    return "\n".join(lines)


def format_trade_alert(symbol: str, decision: dict, entry: float, sl: float,
                        tp1: float, tp2: float, rr: float, lots: float, approvals: str) -> str:
    return (
        f"*{symbol}*\n"
        f"*{decision['consensus']}*\n\n"
        f"Entry: `{entry}`\n"
        f"SL: `{sl}`\n"
        f"TP1: `{tp1}`\n"
        f"TP2: `{tp2}`\n"
        f"Lot size: `{lots}`\n"
        f"RR: `{rr}`\n"
        f"Confidence: *{decision['confidence']}%*\n"
        f"Approved by: {approvals}\n\n"
        f"*Reasoning:*\n" + "\n".join(f"- {r}" for r in decision["reasons"])
    )


def send_trade_alert_with_confirmation(text: str, trade_id: str):
    """Sends the alert with inline Yes/No buttons. You'll need a small
    webhook or polling handler (see telegram_listener.py) to catch the
    button press and trigger executor.place_order()."""
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Execute", "callback_data": f"exec_yes:{trade_id}"},
            {"text": "❌ Skip", "callback_data": f"exec_no:{trade_id}"},
        ]]
    }
    return send_message(text, reply_markup=keyboard)


def send_plain_alert(text: str):
    return send_message(text)