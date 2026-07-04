"""
Stores each cycle's predictions and reviews them one cycle later — this is
the "check if T-1 was right and learn from it" loop you asked for.

Review heuristic (documented honestly, not hidden): a prediction counts as
"correct so far" if price has moved in the predicted direction since entry
by the time it's reviewed (one cycle later, i.e. ~POLL_INTERVAL_SECONDS).
This is NOT the same as "hit take-profit" — it's a lightweight, fast-feedback
signal ("was this a step in the right direction one cycle later"), which is
what makes a rolling accuracy score possible without waiting days for every
trade to fully play out. Treat the resulting accuracy % as a directional
tendency indicator, not a win-rate.
"""

import json
import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    strategy TEXT,
    timestamp TEXT,
    vote TEXT,
    confidence REAL,
    entry_price REAL,
    reasons TEXT,
    reviewed INTEGER DEFAULT 0,
    was_correct INTEGER,       -- NULL until reviewed; 0/1 after
    price_at_review REAL
);
"""


def _conn():
    conn = sqlite3.connect(config.PREDICTIONS_DB_PATH)
    conn.execute(SCHEMA)
    return conn


def save_predictions(symbol: str, predictions: list) -> None:
    conn = _conn()
    now = datetime.utcnow().isoformat()
    for p in predictions:
        conn.execute(
            """INSERT INTO predictions
               (symbol, strategy, timestamp, vote, confidence, entry_price, reasons)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, p["name"], now, p["vote"], p["confidence"], p.get("entry"),
             json.dumps(p.get("reasons", []))),
        )
    conn.commit()
    conn.close()


def get_unreviewed_predictions(symbol: str) -> list:
    """Returns the most recent unreviewed prediction per strategy for this
    symbol (i.e. last cycle's calls, waiting to be checked against now)."""
    conn = _conn()
    cur = conn.execute(
        """SELECT * FROM predictions
           WHERE symbol = ? AND reviewed = 0
           ORDER BY id DESC""",
        (symbol,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()

    # keep only the most recent unreviewed row per strategy
    seen = set()
    latest = []
    for r in rows:
        if r["strategy"] not in seen:
            latest.append(r)
            seen.add(r["strategy"])
    return latest


def mark_reviewed(prediction_id: int, was_correct: bool, price_at_review: float) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE predictions SET reviewed = 1, was_correct = ?, price_at_review = ? WHERE id = ?",
        (int(was_correct), price_at_review, prediction_id),
    )
    conn.commit()
    conn.close()


def get_accuracy(symbol: str, strategy: str, lookback: int = 50) -> dict:
    conn = _conn()
    cur = conn.execute(
        """SELECT was_correct FROM predictions
           WHERE symbol = ? AND strategy = ? AND reviewed = 1
           ORDER BY id DESC LIMIT ?""",
        (symbol, strategy, lookback),
    )
    rows = [r[0] for r in cur.fetchall()]
    conn.close()

    if not rows:
        return {"accuracy": None, "sample_size": 0}
    accuracy = round(sum(rows) / len(rows) * 100, 1)
    return {"accuracy": accuracy, "sample_size": len(rows)}


def review_and_get_reports(symbol: str, current_price: float) -> list:
    """
    Reviews every unreviewed prediction for this symbol against the current
    price, updates the DB, and returns a list of review dicts ready for
    Telegram formatting:
    {"strategy": str, "vote": str, "confidence": float, "entry": float,
     "current_price": float, "correct": bool, "accuracy": float|None,
     "sample_size": int}
    """
    pending = get_unreviewed_predictions(symbol)
    reports = []

    for p in pending:
        entry = p["entry_price"]
        vote = p["vote"]
        if entry is None:
            continue

        correct = (vote == "BUY" and current_price > entry) or (vote == "SELL" and current_price < entry)
        mark_reviewed(p["id"], correct, current_price)

        acc = get_accuracy(symbol, p["strategy"])
        reports.append({
            "strategy": p["strategy"],
            "vote": vote,
            "confidence": p["confidence"],
            "entry": entry,
            "current_price": current_price,
            "correct": correct,
            "accuracy": acc["accuracy"],
            "sample_size": acc["sample_size"],
        })

    return reports