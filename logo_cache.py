"""
Persistent SQLite cache for user-accepted logos.
Stored at ~/.logolift/cache.db — survives app restarts.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DB_PATH = Path.home() / ".logolift" / "cache.db"

_DDL = """
CREATE TABLE IF NOT EXISTS logos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query_key    TEXT    NOT NULL,
    name         TEXT,
    source_orig  TEXT,
    format       TEXT,
    url          TEXT    UNIQUE,
    content      BLOB    NOT NULL,
    accept_count INTEGER NOT NULL DEFAULT 1,
    last_accepted TEXT   NOT NULL DEFAULT (datetime('now'))
)
"""


def _normalize(query: str) -> str:
    return re.sub(r"[^a-z0-9]", "", query.lower())


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(_DDL)
    conn.commit()
    return conn


def save_logo(query: str, logo: dict) -> None:
    key = _normalize(query)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO logos (query_key, name, source_orig, format, url, content)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                accept_count  = accept_count + 1,
                last_accepted = datetime('now')
            """,
            (key, logo["name"], logo.get("source_orig", logo["source"]),
             logo["format"], logo["url"], logo["content"]),
        )


def get_logos(query: str, limit: int = 5) -> list[dict]:
    key = _normalize(query)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT name, source_orig, format, url, content, accept_count
            FROM logos
            WHERE query_key = ?
               OR instr(query_key, ?) > 0
               OR instr(?, query_key) > 0
            ORDER BY accept_count DESC
            LIMIT ?
            """,
            (key, key, key, limit),
        ).fetchall()

    results = []
    for name, source_orig, fmt, url, content, count in rows:
        results.append({
            "name": name,
            "source": "Your Archive",
            "source_orig": source_orig,
            "format": fmt,
            "url": url,
            "content": bytes(content),
            "accept_count": count,
            "cached": True,
        })
    return results
