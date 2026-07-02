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
                timeout=60,
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
