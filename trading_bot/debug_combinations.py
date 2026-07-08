"""
Diagnostic: shows the RAW combination counts from your actual forex
database, with no minimum-sample filter, so we can see what's really in
there and confirm whether get_top_combinations is working correctly.

    python debug_combinations.py
"""

import sqlite3
from collections import defaultdict
from itertools import combinations

import config_forex as market

db_path = market.PREDICTIONS_DB_PATH
symbol = "EURUSD"

print(f"Inspecting: {db_path}, symbol={symbol}\n")

conn = sqlite3.connect(db_path)

# Basic sanity counts first
total = conn.execute("SELECT COUNT(*) FROM predictions WHERE symbol = ?", (symbol,)).fetchone()[0]
reviewed = conn.execute("SELECT COUNT(*) FROM predictions WHERE symbol = ? AND reviewed = 1", (symbol,)).fetchone()[0]
distinct_timestamps = conn.execute(
    "SELECT COUNT(DISTINCT timestamp) FROM predictions WHERE symbol = ? AND reviewed = 1", (symbol,)
).fetchone()[0]

print(f"Total rows for {symbol}: {total}")
print(f"Reviewed rows: {reviewed}")
print(f"Distinct reviewed cycle timestamps: {distinct_timestamps}\n")

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
        outcome = participants[0][1]
        for pair in combinations(names, 2):
            key = (pair, direction)
            combo_stats[key]["total"] += 1
            combo_stats[key]["wins"] += int(outcome)

print(f"Total distinct (pair, direction) combinations found: {len(combo_stats)}\n")
print("ALL combinations (no minimum filter), sorted by sample size:")
sorted_combos = sorted(combo_stats.items(), key=lambda kv: -kv[1]["total"])
for (pair, direction), stats in sorted_combos[:15]:
    win_rate = round(stats["wins"] / stats["total"] * 100, 1) if stats["total"] else 0
    print(f"  {pair[0]} + {pair[1]} -> {direction}: {win_rate}% ({stats['total']} agreed-cycles)")
