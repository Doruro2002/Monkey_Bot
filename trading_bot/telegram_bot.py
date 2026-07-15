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
import os
import time

import requests

import config

log = logging.getLogger("telegram_bot")

API_BASE = "https://api.telegram.org/bot{token}"


def _url(method: str, token: str) -> str:
    return f"{API_BASE.format(token=token)}/{method}"


def send_message(text: str, reply_markup: dict = None, token: str = None, chat_id: str = None,
                  max_retries: int = 3, _is_fallback: bool = False) -> dict:
    """
    token/chat_id are optional — if omitted, falls back to config.py's
    single global bot. Retries transient network failures a few times with
    short backoff. If Telegram rejects the message specifically because
    the Markdown couldn't be parsed (very common with dynamic content like
    news headlines that contain stray *, _, [ characters), automatically
    retries ONE more time as plain text instead of giving up — a
    formatting hiccup should never cost you the whole report.
    """
    token = token or config.TELEGRAM_BOT_TOKEN
    chat_id = chat_id or config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log.warning("Telegram not configured — printing instead:\n%s", text)
        return {}

    payload = {"chat_id": chat_id, "text": text}
    if not _is_fallback:
        payload["parse_mode"] = "Markdown"
    if reply_markup:
        payload["reply_markup"] = reply_markup

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(_url("sendMessage", token), json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            body = e.response.text if e.response is not None else ""
            last_error = e
            log.warning("Telegram send failed (attempt %d/%d): %s | response: %s", attempt, max_retries, e, body[:300])

            # 400 + "can't parse entities" = Markdown formatting broke on
            # dynamic content. Retrying the SAME payload won't help — fall
            # back to plain text immediately instead of burning retries.
            if e.response is not None and e.response.status_code == 400 and not _is_fallback:
                log.warning("Retrying as plain text (Markdown parsing failed) instead of giving up.")
                return send_message(text, reply_markup=reply_markup, token=token, chat_id=chat_id,
                                     max_retries=1, _is_fallback=True)
            if attempt < max_retries:
                time.sleep(2 * attempt)
        except requests.exceptions.RequestException as e:
            last_error = e
            log.warning("Telegram send failed (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt < max_retries:
                time.sleep(2 * attempt)

    log.error("Telegram send failed after %d attempts, giving up this cycle: %s", max_retries, last_error)
    return {}


def format_predictions_report(symbol: str, predictions: list) -> str:
    """The 'T' message — this cycle's fresh prediction from every strategy."""
    lines = [f"📊 *{symbol}* — Predictions (now)\n"]

    vote_emoji = {"BUY": "🟢", "SELL": "🔴"}

    for r in predictions:
        emoji = vote_emoji.get(r["vote"], "⚪")
        lines.append(f"{emoji} *{r['name']}* ({r.get('strategy', '')})")
        lines.append(f"   {r['vote']} — Confidence: *{r['confidence']}%*")
        lines.append(f"   Entry: `{r['entry']}` | SL: `{r['sl']}` | TP1: `{r['tp1']}` | TP2: `{r['tp2']}`")
        if r.get("reasons"):
            reason_text = " ".join(r["reasons"]) if isinstance(r["reasons"], list) else str(r["reasons"])
            lines.append(f"   Why: _{reason_text}_")
        lines.append("")

    return "\n".join(lines)


def format_review_report(symbol: str, reviews: list) -> str:
    """The 'T-1' message — did last cycle's prediction move the right way,
    and how's each strategy's rolling accuracy trending. This is the
    learning loop made visible."""
    if not reviews:
        return f"🔁 *{symbol}* — Review (previous cycle)\n\nNothing to review yet (first cycle, or nothing pending)."

    lines = [f"🔁 *{symbol}* — Review (previous cycle)\n"]

    for r in reviews:
        result_emoji = "✅" if r["correct"] else "❌"
        acc_text = f"{r['accuracy']}% over {r['sample_size']} reviewed calls" if r["accuracy"] is not None else "not enough data yet"
        lines.append(f"{result_emoji} *{r['strategy']}*: predicted {r['vote']} @ `{r['entry']}`")
        lines.append(f"   Price now: `{r['current_price']}` — {'moved as predicted' if r['correct'] else 'moved against the call'}")
        lines.append(f"   Rolling accuracy: {acc_text}")
        lines.append("")

    return "\n".join(lines)


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


def send_trade_alert_with_confirmation(text: str, trade_id: str, token: str = None, chat_id: str = None):
    """Sends the alert with inline Yes/No buttons. You'll need a small
    webhook or polling handler (see telegram_listener.py) to catch the
    button press and trigger executor.place_order()."""
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Execute", "callback_data": f"exec_yes:{trade_id}"},
            {"text": "❌ Skip", "callback_data": f"exec_no:{trade_id}"},
        ]]
    }
    return send_message(text, reply_markup=keyboard, token=token, chat_id=chat_id)


def send_photo(image_path: str, caption: str = "", token: str = None, chat_id: str = None,
                max_retries: int = 2) -> dict:
    """
    Sends a chart image as its own Telegram message. Note: Telegram treats
    photos as a separate message type from text (platform limitation, not
    a choice here) — a photo's caption is capped at 1024 characters, so
    this is meant to accompany the full text report, not replace it.
    """
    token = token or config.TELEGRAM_BOT_TOKEN
    chat_id = chat_id or config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log.warning("Telegram not configured — skipping chart send for %s", image_path)
        return {}

    if not os.path.exists(image_path):
        log.warning("Chart file not found, skipping send: %s", image_path)
        return {}

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            with open(image_path, "rb") as f:
                resp = requests.post(
                    _url("sendPhoto", token),
                    data={"chat_id": chat_id, "caption": caption[:1024]},
                    files={"photo": f},
                    timeout=30,
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_error = e
            log.warning("Telegram photo send failed (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt < max_retries:
                time.sleep(2 * attempt)

    log.error("Telegram photo send failed after %d attempts: %s", max_retries, last_error)
    return {}


def send_plain_alert(text: str, token: str = None, chat_id: str = None):
    return send_message(text, token=token, chat_id=chat_id)


TELEGRAM_MAX_LEN = 4096  # Telegram's hard per-message character limit — not configurable


def send_long_alert(text: str, token: str = None, chat_id: str = None):
    """
    Sends as ONE message whenever possible. Telegram enforces a hard 4096
    character limit per message — there's no way around that on their end,
    so this only splits into multiple messages if the text genuinely
    exceeds it, and splits on clean line boundaries so nothing gets cut
    mid-word.
    """
    if len(text) <= TELEGRAM_MAX_LEN:
        return [send_message(text, token=token, chat_id=chat_id)]

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > TELEGRAM_MAX_LEN:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)

    results = []
    for i, chunk in enumerate(chunks):
        prefix = f"(part {i+1}/{len(chunks)})\n" if len(chunks) > 1 else ""
        results.append(send_message(prefix + chunk, token=token, chat_id=chat_id))
    return results


def _pad(text: str, width: int) -> str:
    text = str(text)
    return text[:width] if len(text) > width else text + " " * (width - len(text))


def format_trading_advisor_line(predictions: list, ceo_summary: dict) -> str:
    """
    A dedicated advisor line that ALWAYS gives a lean — never just 'wait'
    with nothing else. This is deliberately separate from the guardrail-
    gated 'Recommended Action' above, which CAN and will block a trade for
    real safety reasons (that block stays, on purpose — see main.py). This
    line is pure informational color: what does the majority of the room
    actually think right now, worded honestly by how convinced they are.

    You still make the final call — per the "assisted, not autonomous AI"
    principle, no line in this report is an instruction to place a trade.
    """
    buy_conf = sum(p["confidence"] for p in predictions if p["vote"] == "BUY")
    sell_conf = sum(p["confidence"] for p in predictions if p["vote"] == "SELL")
    lean = "BUY" if buy_conf >= sell_conf else "SELL"
    lean_strength = max(buy_conf, sell_conf) / (buy_conf + sell_conf) * 100 if (buy_conf + sell_conf) else 50

    if lean_strength >= 70:
        wording = f"Room leans *{lean}* fairly clearly right now."
    elif lean_strength >= 55:
        wording = f"Slight lean toward *{lean}*, but it's not a strong consensus — size down if you act on it."
    else:
        wording = f"Genuinely split — barely favors *{lean}*. Treat this as noise, not a signal."

    return f"🧭 *Trading Advisor:* {wording}"


def format_learning_report(symbol: str, accuracies: dict, market_lean: str, llm_summary: str = None) -> str:
    """
    Sent every N review cycles (main.py calls this every 4th cycle) — a
    step back from the noise of every-cycle predictions to summarize what's
    actually been learned: which strategies are earning more trust, which
    are losing it, and a short plain-language read on where the market
    seems to be leaning lately.
    """
    lines = [f"🎓 *{symbol}* — Learning Report (every 4 cycles)\n"]

    sorted_strats = sorted(accuracies.items(), key=lambda kv: -(kv[1]["accuracy"] or 0))
    lines.append("*Strategy trust ranking:*")
    for name, acc in sorted_strats:
        if acc["accuracy"] is None:
            lines.append(f"   {name}: still building history ({acc['sample_size']} reviewed)")
        else:
            trend_note = "📈 trusted more" if acc["accuracy"] >= 60 else "📉 trusted less" if acc["accuracy"] < 45 else "➖ neutral"
            lines.append(f"   {name}: {acc['accuracy']}% accurate ({acc['sample_size']} calls) — {trend_note}")

    lines.append(f"\n*Overall market lean lately:* {market_lean}")

    if llm_summary:
        lines.append(f"\n_{llm_summary}_")

    return "\n".join(lines)


def format_full_report(symbol: str, reviews: list, predictions: list, ceo_summary: dict,
                        guardrail_result: dict = None, sentiment_headlines: list = None,
                        strategy_weights: dict = None) -> str:
    """
    ONE message, built for fast scanning:
      1. Quick summary + recommended action (read this, done if you're busy)
      2. A monospace TABLE of every strategy (vote/conf/entry/SL/TP at a glance)
      3. Real news headlines
      4. Reasoning detail (only if you want the "why")
      5. Review of last cycle's calls (the learning loop)

    Telegram can't embed an actual image inside a text message (photos are
    a separate message type with a short caption limit), so a monospace
    table inside a code block is the most readable option that still
    fits in a single message.
    """
    buy_count = sum(1 for p in predictions if p["vote"] == "BUY")
    sell_count = sum(1 for p in predictions if p["vote"] == "SELL")
    top_call = max(predictions, key=lambda p: p["confidence"]) if predictions else None

    # Confluence visibility (informational only — NOT a hardcoded "80% win
    # rate" rule; just shows how many of the core order-flow-style
    # strategies agree with the CEO's direction, for your own judgment)
    core_names = {"SMC", "ICT", "PriceAction", "SupplyDemand", "DayTrading"}
    core_predictions = [p for p in predictions if p["name"] in core_names]
    core_aligned = sum(1 for p in core_predictions if p["vote"] == ceo_summary["consensus"])

    lines = [f"📈 *{symbol}* — Full Report\n"]

    # --- Quick summary ---
    lines.append("*── Quick Summary ──*")
    lines.append(f"🟢{buy_count} BUY  /  🔴{sell_count} SELL   |   CEO: *{ceo_summary['consensus']}* ({ceo_summary['confidence']}%)")
    if ceo_summary["consensus"] != "WAIT":
        lines.append(f"Core confluence (SMC/ICT/PriceAction/SupplyDemand/DayTrading): {core_aligned}/{len(core_predictions)} aligned")
    if top_call:
        lines.append(f"Most confident: *{top_call['name']}* → {top_call['vote']} ({top_call['confidence']}%)")

    # --- Recommended action ---
    lines.append("\n*── 🎯 Recommended Action ──*")
    if guardrail_result and not guardrail_result["allowed"]:
        lines.append("⛔ *NO TRADE* — guardrail blocked it:")
        for r in guardrail_result["reasons"]:
            if "passed" not in r.lower():
                lines.append(f"   • {r}")
    elif ceo_summary["consensus"] == "WAIT" or ceo_summary["confidence"] < config.MIN_CONFIDENCE_TO_ALERT:
        lines.append(f"⚪ *WAIT* — no strategy edge clears the {config.MIN_CONFIDENCE_TO_ALERT}% confidence bar right now.")
    else:
        rr_text = f", RR {guardrail_result['rr']}" if guardrail_result else ""
        lines.append(f"✅ *Consider {ceo_summary['consensus']}* — confidence {ceo_summary['confidence']}%{rr_text}. "
                     f"Research signal, not an instruction — you make the final call.")

    lines.append(format_trading_advisor_line(predictions, ceo_summary))

    # --- Strategy Spotlight: WHICH strategy is actually most USEFUL right
    # now — combining learned trust (weight) with actual current conviction
    # (its own confidence this cycle). Weight alone isn't enough: a regime
    # boost can raise a strategy's weight even in a cycle where it has no
    # real signal (e.g. RangeTrading gets boosted in low volatility even
    # when the market isn't actually ranging). Multiplying by its own
    # reported confidence prevents a "trusted but currently blank"
    # strategy from getting spotlighted over one that's both trusted AND
    # actually has something to say right now. ---
    if strategy_weights:
        scored = []
        for p in predictions:
            w = strategy_weights.get(p["name"], 0)
            combined_score = w * (p["confidence"] / 100)
            scored.append((combined_score, p))
        scored.sort(key=lambda x: -x[0])
        top_score, top_pred = scored[0] if scored else (0, None)

        if top_pred:
            lines.append("\n*── 🔦 Strategy Spotlight ──*")
            lines.append(f"Most useful right now: *{top_pred['name']}* "
                         f"(trust weight {round(strategy_weights.get(top_pred['name'],0)*100)}%, "
                         f"its own confidence {top_pred['confidence']}% this cycle)")
            lines.append(f"Its call: {top_pred['vote']} ({top_pred['confidence']}%) — {top_pred.get('strategy', '')}")
            if top_pred.get("reasons"):
                reason_text = " ".join(top_pred["reasons"]) if isinstance(top_pred["reasons"], list) else str(top_pred["reasons"])
                lines.append(f"Why: _{reason_text}_")

    # --- TABLE: every strategy at a glance ---
    lines.append("\n*── Strategy Table ──*")
    table_rows = ["Strategy      Vote Conf  Entry     SL        TP1"]
    table_rows.append("-" * len(table_rows[0]))
    for r in sorted(predictions, key=lambda p: -p["confidence"]):
        name = _pad(r["name"], 13)
        vote = _pad(r["vote"], 4)
        conf = _pad(f"{r['confidence']}%", 5)
        entry = _pad(r["entry"], 9)
        sl = _pad(r["sl"], 9)
        tp1 = _pad(r["tp1"], 9)
        table_rows.append(f"{name} {vote} {conf} {entry} {sl} {tp1}")
    lines.append("```\n" + "\n".join(table_rows) + "\n```")

    # --- Real news headlines ---
    if sentiment_headlines:
        lines.append("*── Live News Headlines ──*")
        for h in sentiment_headlines[:5]:
            lines.append(f"   📰 {h}")
        lines.append("")

    # --- Reasoning detail, for anyone who wants the "why" ---
    lines.append("*── Why (tap-worthy detail) ──*")
    for r in sorted(predictions, key=lambda p: -p["confidence"]):
        if r.get("reasons"):
            reason_text = " ".join(r["reasons"]) if isinstance(r["reasons"], list) else str(r["reasons"])
            lines.append(f"_{r['name']}_: {reason_text}")

    # --- Review of last cycle ---
    lines.append("\n*── Review: Last Cycle ──*")
    if not reviews:
        lines.append("Nothing to review yet (first cycle).")
    else:
        review_rows = ["Strategy      Vote Result  Accuracy"]
        review_rows.append("-" * len(review_rows[0]))
        for r in reviews:
            result_txt = "✅ right" if r["correct"] else "❌ wrong"
            acc_text = f"{r['accuracy']}%/{r['sample_size']}" if r["accuracy"] is not None else "building"
            review_rows.append(f"{_pad(r['strategy'], 13)} {_pad(r['vote'], 4)} {_pad(result_txt, 7)} {acc_text}")
        lines.append("```\n" + "\n".join(review_rows) + "\n```")

    return "\n".join(lines)
