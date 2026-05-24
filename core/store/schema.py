"""SQL schema. Idempotent — safe to call on every startup.

Timestamps are ISO-8601 UTC strings set from Python so the schema stays
portable to Postgres (no SQLite-only `datetime('now')` calls).
"""
from __future__ import annotations

from .db import Database

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS devices (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        serial          TEXT    NOT NULL UNIQUE,
        name            TEXT    NOT NULL,
        model           TEXT,
        screen_w        INTEGER,
        screen_h        INTEGER,
        first_seen_at   TEXT    NOT NULL,
        last_seen_at    TEXT    NOT NULL,
        status          TEXT    NOT NULL DEFAULT 'offline'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)",
    """
    CREATE TABLE IF NOT EXISTS runs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id       INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        scenario        TEXT    NOT NULL,
        started_at      TEXT    NOT NULL,
        ended_at        TEXT,
        status          TEXT    NOT NULL DEFAULT 'running',
        iteration_count INTEGER NOT NULL DEFAULT 0,
        error_count     INTEGER NOT NULL DEFAULT 0,
        last_error      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_device ON runs(device_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",
    """
    CREATE TABLE IF NOT EXISTS run_events (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        ts      TEXT    NOT NULL,
        level   TEXT    NOT NULL,
        message TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, ts)",
)


def init_schema(db: Database) -> None:
    conn = db.conn()
    for stmt in SCHEMA_STATEMENTS:
        conn.execute(stmt)
