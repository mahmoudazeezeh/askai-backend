"""SQLite storage: clients, enrollment codes, usage, settings."""
from __future__ import annotations

import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    created_at    INTEGER NOT NULL,
    last_seen     INTEGER,
    disabled      INTEGER NOT NULL DEFAULT 0,
    can_select_model INTEGER NOT NULL DEFAULT 0,
    per_minute    INTEGER,
    per_day       INTEGER,
    per_month     INTEGER,
    enrolled_with TEXT,
    machine       TEXT
);
CREATE TABLE IF NOT EXISTS enroll_codes (
    code_hash  TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    max_uses   INTEGER NOT NULL,
    uses       INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER,
    disabled   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  TEXT NOT NULL,
    ts         INTEGER NOT NULL,
    day        TEXT NOT NULL,
    month      TEXT NOT NULL,
    mode       TEXT,
    provider   TEXT,
    model      TEXT,
    status     TEXT NOT NULL,
    in_tokens  INTEGER DEFAULT 0,
    out_tokens INTEGER DEFAULT 0,
    ms         INTEGER DEFAULT 0,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS usage_client_day ON usage(client_id, day);
CREATE INDEX IF NOT EXISTS usage_client_month ON usage(client_id, month);
CREATE INDEX IF NOT EXISTS usage_day ON usage(day);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """Tiny thread-safe wrapper (one connection, one lock)."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def one(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
