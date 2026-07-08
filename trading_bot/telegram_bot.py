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


def _url(method: str, token: str) -> str:
    return f"{API_BASE.format(token=token)}/{method}"


def send_message(text: str, reply_markup: dict = None, token: str = None, chat_id: str = None) -> dict:
    """
    token/chat_id are optional — if omitted, falls back to config.py's
    single global bot (backward compatible with the original single-market
    setup). Each market's main script should pass its OWN token/chat_id
    explicitly so forex/metals/crypto each message a different bot.
    """
    token = token or config.TELEGRAM_BOT_TOKEN
    chat_id = chat_id or config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        log.warning("Telegram not configured — printing instead:\n%s", text)
        return {}

    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    resp = requests.post(_url("sendMessage", token), json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


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
                        top_combinations_by_size: dict = None) -> str:
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

    # --- Top combinations, built from REAL tracked history, not a one-off report ---
    lines.append("*── Top Combinations (tracked) ──*")
    size_labels = {2: "Pairs", 3: "Triplets", 4: "Quads", 5: "Quintuplets"}
    if top_combinations_by_size:
        any_shown = False
        for size in sorted(top_combinations_by_size.keys()):
            combos = top_combinations_by_size[size]
            label = size_labels.get(size, f"{size}-combos")
            if combos:
                any_shown = True
                lines.append(f"   _{label}:_")
                for c in combos:
                    names_joined = " + ".join(c["combo"])
                    lines.append(f"     {names_joined} → {c['direction']}: *{c['win_rate']}%* ({c['sample_size']} agreed-cycles)")
            else:
                lines.append(f"   _{label}:_ still building history")
        if not any_shown:
            lines.append("   Still building history — need more reviewed cycles before any combination clears the minimum sample size.")
    else:
        lines.append("   Still building history — need more reviewed cycles before any combination clears the minimum sample size.")

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
