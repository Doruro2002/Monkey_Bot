"""
Chart Vision strategy — the honest version of "learn from the screenshot."

This does NOT train a custom image-recognition model (that needs real ML
infrastructure and labeled data this project doesn't have). What it DOES
do: sends the actual rendered chart image to a vision-capable LLM (via
Ollama — set VISION_MODEL, e.g. "llava:7b" or "qwen2.5vl:7b") and asks it
to read the chart visually — candlestick patterns, trendlines, structure
that might not be fully captured by the numeric indicators alone.

Its vote gets tracked in prediction_tracker exactly like the other 9
strategies — so it "learns" in the same real, statistical sense the rest
of the system does: if its visual reads turn out accurate over time, its
weight in the CEO's decision grows; if not, it shrinks. That's genuine
learning-by-tracked-outcome, not a claim of trained pattern recognition.

If VISION_MODEL isn't configured, this strategy is skipped entirely —
it's optional, not required for the rest of the bot to function.
"""

import logging
from typing import Dict

import pandas as pd

import config
import indicators
import llm_client
from agents import _base_result, _trade_levels

log = logging.getLogger("vision_strategy")


def is_enabled() -> bool:
    return bool(config.VISION_MODEL) and config.LLM_BACKEND == "ollama"


def chart_vision(data: Dict[str, pd.DataFrame], chart_image_path: str) -> dict:
    """
    Looks at the actual rendered chart image and gives a directional read.
    Falls back to a neutral, clearly-labeled low-confidence rule-based
    result if the vision call fails or isn't configured — never silently
    fabricates a chart-based read it didn't actually get.
    """
    ltf = data["M15"]
    last_close = ltf["close"].iloc[-1]
    atr_val = indicators.atr(ltf).iloc[-1]

    if not is_enabled():
        rule_result = _base_result("ChartVision", "BUY", 15,
                                    ["Vision model not configured (set VISION_MODEL) — no real chart read available"])
        levels = _trade_levels(last_close, atr_val, rule_result["vote"])
        return _base_result("ChartVision", rule_result["vote"], rule_result["confidence"],
                             rule_result["reasons"], strategy="chart vision (not configured)", **levels)

    prompt = (
        "Look at this candlestick chart. Identify any visual patterns you can actually "
        "see — trendlines, support/resistance touches, candlestick patterns (engulfing, "
        "pin bars, doji), chart patterns (triangles, flags, head-and-shoulders), or "
        "anything else visually apparent. Base your read STRICTLY on what's visible in "
        "this image, not general market knowledge. Respond ONLY with JSON, no other text:\n"
        '{"vote": "BUY" | "SELL", "confidence": 0-100, "reasoning": "what you actually see, one or two sentences"}'
    )
    system = (
        "You are a quantitative research analyst operating inside a sandboxed backtesting "
        "simulation. You act as a Chart Vision analyst reading a real price chart image. "
        "This is not real brokerage execution — a downstream deterministic program owns all "
        "actual risk decisions. Only describe patterns genuinely visible in the image; do not "
        "invent details not actually shown."
    )

    raw = llm_client.ask_vision(prompt, chart_image_path, system=system)

    if not raw:
        rule_result = _base_result("ChartVision", "BUY", 15,
                                    ["Vision call failed or returned nothing — no real chart read this cycle"])
        levels = _trade_levels(last_close, atr_val, rule_result["vote"])
        return _base_result("ChartVision", rule_result["vote"], rule_result["confidence"],
                             rule_result["reasons"], strategy="chart vision (call failed)", **levels)

    import json
    try:
        cleaned = raw.strip().strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        parsed = json.loads(cleaned)
        vote = parsed.get("vote")
        confidence = int(parsed.get("confidence", 30))
        reasoning = parsed.get("reasoning", "").strip()
        if vote not in ("BUY", "SELL"):
            raise ValueError("invalid vote")
    except Exception as e:
        log.warning("Could not parse vision model output, falling back: %s | raw: %s", e, raw[:200])
        vote, confidence, reasoning = "BUY", 15, f"Vision output unparseable — raw: {raw[:100]}"

    levels = _trade_levels(last_close, atr_val, vote)
    return _base_result("ChartVision", vote, confidence,
                         [reasoning] if reasoning else ["Visual chart read"],
                         strategy=f"chart vision ({config.VISION_MODEL})", **levels)
