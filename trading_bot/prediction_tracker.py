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


def get_top_combinations_all_sizes(db_path: str, symbol: str, sizes: tuple = (2, 3, 4, 5),
                                    min_sample_size: int = 10, top_n: int = 3) -> dict:
    """
    Same idea as before, generalized to combination sizes 2 through 5 —
    computed in a single pass over the reviewed history (not re-querying
    the DB per size). Returns {size: [list of top combos]}, where each
    combo is {"combo": (name1, name2, ...), "direction":..., "win_rate":...,
    "sample_size":...}. A size with nothing clearing min_sample_size
    returns [] for that size — that's expected, not an error, especially
    for larger combo sizes (5 specific strategies agreeing together is
    rarer than 2, so it naturally needs more history to qualify).
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

    # combo_stats[size][(pair, direction)] = {"wins":.., "total":..}
    combo_stats = {size: defaultdict(lambda: {"wins": 0, "total": 0}) for size in sizes}

    for timestamp, entries in cycles.items():
        by_direction = defaultdict(list)
        for strategy, vote, was_correct in entries:
            by_direction[vote].append((strategy, was_correct))

        for direction, participants in by_direction.items():
            names = sorted(p[0] for p in participants)
            outcome = participants[0][1]  # shared outcome for this cycle/direction
            for size in sizes:
                if len(names) < size:
                    continue
                for combo in _combinations(names, size):
                    key = (combo, direction)
                    combo_stats[size][key]["total"] += 1
                    combo_stats[size][key]["wins"] += int(outcome)

    results = {}
    for size in sizes:
        size_results = []
        for (combo, direction), stats in combo_stats[size].items():
            if stats["total"] >= min_sample_size:
                win_rate = round(stats["wins"] / stats["total"] * 100, 1)
                size_results.append({"combo": combo, "direction": direction,
                                      "win_rate": win_rate, "sample_size": stats["total"]})
        size_results.sort(key=lambda r: (-r["win_rate"], -r["sample_size"]))
        results[size] = size_results[:top_n]

    return results


def get_top_combinations(db_path: str, symbol: str, min_sample_size: int = 10, top_n: int = 3) -> list:
    """Backward-compatible pairs-only version — kept for any existing callers."""
    return get_top_combinations_all_sizes(db_path, symbol, sizes=(2,), min_sample_size=min_sample_size, top_n=top_n)[2]


def get_recency_weighted_accuracy(db_path: str, symbol: str, strategy: str,
                                   recent_n: int = 10, full_lookback: int = 50) -> dict:
    """
    Real (not injected) recency signal: compares a strategy's accuracy over
    its most recent N reviewed calls against its longer-run accuracy. If a
    strategy has been cooling off lately, `recent_loss_rate` reflects that
    numerically — computed entirely from actual stored outcomes, nothing
    assumed or hand-set.
    """
    conn = _conn(db_path)
    cur = conn.execute(
        """SELECT was_correct FROM predictions
           WHERE symbol = ? AND strategy = ? AND reviewed = 1
           ORDER BY id DESC LIMIT ?""",
        (symbol, strategy, full_lookback),
    )
    rows = [r[0] for r in cur.fetchall()]
    conn.close()

    if not rows:
        return {"overall_accuracy": None, "recent_accuracy": None, "recent_loss_rate": 0.0, "sample_size": 0}

    overall_accuracy = round(sum(rows) / len(rows) * 100, 1)

    recent_rows = rows[:recent_n]  # already DESC (most recent first)
    if recent_rows:
        recent_accuracy = round(sum(recent_rows) / len(recent_rows) * 100, 1)
        recent_loss_rate = round(1 - (sum(recent_rows) / len(recent_rows)), 3)
    else:
        recent_accuracy, recent_loss_rate = overall_accuracy, round(1 - sum(rows)/len(rows), 3)

    return {
        "overall_accuracy": overall_accuracy,
        "recent_accuracy": recent_accuracy,
        "recent_loss_rate": recent_loss_rate,
        "sample_size": len(rows),
    }


def get_all_strategy_accuracies(db_path: str, symbol: str, strategy_names: list) -> dict:
    return {name: get_accuracy(db_path, symbol, name) for name in strategy_names}
