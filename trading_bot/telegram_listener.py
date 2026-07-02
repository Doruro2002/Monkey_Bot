"""
Minimal long-polling listener for the Yes/No confirmation buttons used in
EXECUTION_MODE == "confirm". Run this as a background thread/process
alongside main.py.

Pending trades are looked up by trade_id (set by main.py before sending
the alert) and executed only on an explicit "exec_yes" callback.
"""

import logging
import time

import requests

import config
import executor

log = logging.getLogger("telegram_listener")

_last_update_id = 0

# main.py registers pending trades here before sending the confirm alert:
#   PENDING_TRADES[trade_id] = {"symbol": ..., "direction": ..., "lots": ...,
#                                "entry": ..., "sl": ..., "tp": ...}
PENDING_TRADES = {}


def _get_updates():
    global _last_update_id
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    resp = requests.get(url, params={"offset": _last_update_id + 1, "timeout": 20}, timeout=25)
    resp.raise_for_status()
    return resp.json().get("result", [])


def poll_forever():
    global _last_update_id
    log.info("Telegram listener started.")
    while True:
        try:
            updates = _get_updates()
            for u in updates:
                _last_update_id = max(_last_update_id, u["update_id"])
                cb = u.get("callback_query")
                if not cb:
                    continue
                data = cb.get("data", "")
                if ":" not in data:
                    continue
                action, trade_id = data.split(":", 1)
                trade = PENDING_TRADES.pop(trade_id, None)
                if not trade:
                    continue

                if action == "exec_yes":
                    log.info("User approved trade %s", trade_id)
                    executor.place_order(**trade)
                else:
                    log.info("User skipped trade %s", trade_id)

        except Exception as e:
            log.warning("Telegram listener error: %s", e)

        time.sleep(2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    poll_forever()
