"""
SQLite trade journal. Every proposed trade (taken or skipped) gets logged
with the full agent reasoning — this is the raw material the Learning
Engine (learning.py) uses later.
"""

import json
import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    timestamp TEXT,
    symbol TEXT,
    direction TEXT,
    entry REAL,
    sl REAL,
    tp REAL,
    lots REAL,
    rr REAL,
    confidence REAL,
    agent_votes TEXT,       -- JSON blob of every agent's vote+reasons
    executed INTEGER,       -- 0 = alert only, 1 = order sent
    outcome TEXT,           -- NULL until closed: 'win' | 'loss' | 'breakeven'
    profit_r REAL,          -- realized result in R multiples
    review TEXT             -- JSON blob filled in by learning.py post-trade
);
"""


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(SCHEMA)
    return conn


def log_trade(trade_id: str, symbol: str, direction: str, entry: float, sl: float,
              tp: float, lots: float, rr: float, confidence: float,
              agent_votes: list, executed: bool) -> None:
    conn = _conn()
    conn.execute(
        """INSERT OR REPLACE INTO trades
           (trade_id, timestamp, symbol, direction, entry, sl, tp, lots, rr,
            confidence, agent_votes, executed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, datetime.utcnow().isoformat(), symbol, direction, entry, sl,
         tp, lots, rr, confidence, json.dumps(agent_votes), int(executed)),
    )
    conn.commit()
    conn.close()


def record_outcome(trade_id: str, outcome: str, profit_r: float) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE trades SET outcome = ?, profit_r = ? WHERE trade_id = ?",
        (outcome, profit_r, trade_id),
    )
    conn.commit()
    conn.close()


def record_review(trade_id: str, review: dict) -> None:
    conn = _conn()
    conn.execute(
        "UPDATE trades SET review = ? WHERE trade_id = ?",
        (json.dumps(review), trade_id),
    )
    conn.commit()
    conn.close()


def get_recent_trades(limit: int = 100) -> list:
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return rows


def get_unreviewed_closed_trades() -> list:
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM trades WHERE outcome IS NOT NULL AND review IS NULL"
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return rows
