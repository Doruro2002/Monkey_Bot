"""
Stores each cycle's predictions and reviews them one cycle later — this is
the "check if T-1 was right and learn from it" loop.

Review heuristic (documented honestly, not hidden): a prediction counts as
"correct so far" if price has moved in the predicted direction since entry
by the time it's reviewed (one cycle later). This is NOT the same as "hit
take-profit" — it's a fast-feedback signal, not a win-rate.

Every function takes an explicit db_path now, so each market (forex/metals/
crypto) can use its own separate database file, as requested — nothing is
shared or mixed between markets.
"""

import json
import sqlite3
from datetime import datetime

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
    was_correct INTEGER,
    price_at_review REAL
);
CREATE TABLE IF NOT EXISTS review_cycles (
    symbol TEXT PRIMARY KEY,
    cycle_count INTEGER DEFAULT 0
);
"""


def _conn(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def save_predictions(db_path: str, symbol: str, predictions: list) -> None:
    conn = _conn(db_path)
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


def get_unreviewed_predictions(db_path: str, symbol: str) -> list:
    conn = _conn(db_path)
    cur = conn.execute(
        "SELECT * FROM predictions WHERE symbol = ? AND reviewed = 0 ORDER BY id DESC",
        (symbol,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()

    seen = set()
    latest = []
    for r in rows:
        if r["strategy"] not in seen:
            latest.append(r)
            seen.add(r["strategy"])
    return latest


def mark_reviewed(db_path: str, prediction_id: int, was_correct: bool, price_at_review: float) -> None:
    conn = _conn(db_path)
    conn.execute(
        "UPDATE predictions SET reviewed = 1, was_correct = ?, price_at_review = ? WHERE id = ?",
        (int(was_correct), price_at_review, prediction_id),
    )
    conn.commit()
    conn.close()


def get_accuracy(db_path: str, symbol: str, strategy: str, lookback: int = 50) -> dict:
    conn = _conn(db_path)
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


def review_and_get_reports(db_path: str, symbol: str, current_price: float) -> list:
    pending = get_unreviewed_predictions(db_path, symbol)
    reports = []

    for p in pending:
        entry = p["entry_price"]
        vote = p["vote"]
        if entry is None:
            continue

        correct = (vote == "BUY" and current_price > entry) or (vote == "SELL" and current_price < entry)
        mark_reviewed(db_path, p["id"], correct, current_price)

        acc = get_accuracy(db_path, symbol, p["strategy"])
        reports.append({
            "strategy": p["strategy"], "vote": vote, "confidence": p["confidence"],
            "entry": entry, "current_price": current_price, "correct": correct,
            "accuracy": acc["accuracy"], "sample_size": acc["sample_size"],
        })

    return reports


def increment_and_check_cycle(db_path: str, symbol: str, every_n: int = 4) -> int:
    """
    Increments this symbol's review-cycle counter and returns the new count.
    Call `count % every_n == 0` at the call site to know whether it's time
    for a learning report. Persisted in the DB so it survives restarts.
    """
    conn = _conn(db_path)
    cur = conn.execute("SELECT cycle_count FROM review_cycles WHERE symbol = ?", (symbol,))
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO review_cycles (symbol, cycle_count) VALUES (?, 1)", (symbol,))
        count = 1
    else:
        count = row[0] + 1
        conn.execute("UPDATE review_cycles SET cycle_count = ? WHERE symbol = ?", (count, symbol))
    conn.commit()
    conn.close()
    return count


def get_top_combinations(db_path: str, symbol: str, min_sample_size: int = 10, top_n: int = 3) -> list:
    """
    Finds which PAIRS of strategies, when they agreed on the same direction
    in the same cycle, had the best REAL tracked win rate — built entirely
    from this bot's own reviewed history, not a one-off backtest report.

    min_sample_size is a real filter, not decoration: pairs with fewer than
    this many agreed-cycles are excluded entirely, specifically to avoid
    the "100% over 2 trades" trap. Returns [] if nothing qualifies yet —
    that's an honest, expected result early on, not a bug.
    """
    from collections import defaultdict
    from itertools import combinations as _combinations

    conn = _conn(db_path)
    cur = conn.execute(
        "SELECT timestamp, strategy, vote, was_correct FROM predictions WHERE symbol = ? AND reviewed = 1",
        (symbol,),
    )
    rows = cur.fetchall()
    conn.close()

    cycles = defaultdict(list)
    for timestamp, strategy, vote, was_correct in rows:
        cycles[timestamp].append((strategy, vote, was_correct))

    combo_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for timestamp, entries in cycles.items():
        by_direction = defaultdict(list)
        for strategy, vote, was_correct in entries:
            by_direction[vote].append((strategy, was_correct))

        for direction, participants in by_direction.items():
            if len(participants) < 2:
                continue
            names = sorted(p[0] for p in participants)
            outcome = participants[0][1]  # all participants share the same cycle/direction/entry -> same outcome
            for pair in _combinations(names, 2):
                key = (pair, direction)
                combo_stats[key]["total"] += 1
                combo_stats[key]["wins"] += int(outcome)

    results = []
    for (pair, direction), stats in combo_stats.items():
        if stats["total"] >= min_sample_size:
            win_rate = round(stats["wins"] / stats["total"] * 100, 1)
            results.append({"combo": pair, "direction": direction, "win_rate": win_rate, "sample_size": stats["total"]})

    results.sort(key=lambda r: (-r["win_rate"], -r["sample_size"]))
    return results[:top_n]


def get_all_strategy_accuracies(db_path: str, symbol: str, strategy_names: list) -> dict:
    return {name: get_accuracy(db_path, symbol, name) for name in strategy_names}