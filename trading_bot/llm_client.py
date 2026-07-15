"""
Thin wrapper so agents can optionally ask an LLM to reason in natural
language on top of the hard technical numbers. If LLM_BACKEND == "none",
agents fall back to pure rule-based logic (still fully functional).

Free-ish options:
  - "ollama":     run a local open-weight model (e.g. qwen2.5, llama3.1,
                   gemma2) via https://ollama.com — free, but needs decent
                   hardware (16GB+ RAM recommended for 7-8B models).
  - "openrouter": some models on https://openrouter.ai are offered free
                   with rate limits — good if your machine is modest.
"""

import json
import logging

import requests

import config

log = logging.getLogger("llm_client")


def ask(prompt: str, system: str = "") -> str:
    if config.LLM_BACKEND == "none":
        return ""

    try:
        if config.LLM_BACKEND == "ollama":
            resp = requests.post(
                config.OLLAMA_URL,
                json={"model": config.OLLAMA_MODEL, "prompt": prompt, "system": system, "stream": False},
                timeout=180,  # local inference on modest hardware can be slow, especially on first load
            )
            resp.raise_for_status()
            return resp.json().get("response", "")

        if config.LLM_BACKEND == "openrouter":
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={
                    "model": config.OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    except Exception as e:
        log.warning("LLM call failed, falling back to rule-based only: %s", e)
        return ""

    return ""


def ask_vision(prompt: str, image_path: str, system: str = "") -> str:
    """
    Sends a prompt PLUS an actual chart image to a vision-capable Ollama
    model (e.g. llava, qwen2.5vl). Requires VISION_MODEL to be set in
    config — this is a separate, optional model from your regular
    LLM_BACKEND text model, since most small local models can't read
    images at all. Fails safe (empty string) if not configured or the
    call fails — callers should have a non-vision fallback.
    """
    if not config.VISION_MODEL:
        return ""
    if config.LLM_BACKEND != "ollama":
        log.warning("Vision analysis currently only supports the Ollama backend.")
        return ""

    import base64
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        log.warning("Could not read chart image for vision analysis: %s", e)
        return ""

    try:
        resp = requests.post(
            config.OLLAMA_URL,
            json={
                "model": config.VISION_MODEL,
                "prompt": prompt,
                "system": system,
                "images": [image_b64],
                "stream": False,
            },
            timeout=120,  # vision models are typically slower than text-only
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        log.warning("Vision analysis call failed: %s", e)
        return ""


def ask_json(prompt: str, system: str = "") -> dict:
    """Asks the LLM to respond in JSON only, and safely parses it."""
    raw = ask(prompt, system)
    if not raw:
        return {}
    cleaned = raw.strip().strip("`")
    if cleaned.startswith("json"):
        cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("Could not parse LLM JSON output: %s", raw[:200])
        return {}
