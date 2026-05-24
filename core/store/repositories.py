"""Repository pattern: each repo encapsulates SQL for one aggregate.

Callers work with frozen model dataclasses only. Swap SQLite for Postgres
later by reimplementing the body of these methods — the public API stays.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .db import Database
from .models import DeviceRow, RunEventRow, RunRow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeviceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(
        self,
        serial: str,
        name: str,
        model: str | None = None,
        screen_w: int | None = None,
        screen_h: int | None = None,
    ) -> DeviceRow:
        now = _now()
        existing = self.db.fetchone(
            "SELECT 1 FROM devices WHERE serial = ?", (serial,)
        )
        if existing is None:
            self.db.execute(
                "INSERT INTO devices "
                "(serial, name, model, screen_w, screen_h, "
                " first_seen_at, last_seen_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'idle')",
                (serial, name, model, screen_w, screen_h, now, now),
            )
        else:
            self.db.execute(
                "UPDATE devices SET "
                "  name = ?, "
                "  model = COALESCE(?, model), "
                "  screen_w = COALESCE(?, screen_w), "
                "  screen_h = COALESCE(?, screen_h), "
                "  last_seen_at = ? "
                "WHERE serial = ?",
                (name, model, screen_w, screen_h, now, serial),
            )
        row = self.db.fetchone(
            "SELECT * FROM devices WHERE serial = ?", (serial,)
        )
        assert row is not None, "device row missing immediately after upsert"
        return DeviceRow.from_row(row)

    def set_status(self, serial: str, status: str) -> None:
        self.db.execute(
            "UPDATE devices SET status = ?, last_seen_at = ? WHERE serial = ?",
            (status, _now(), serial),
        )

    def heartbeat(self, serial: str) -> None:
        self.db.execute(
            "UPDATE devices SET last_seen_at = ? WHERE serial = ?",
            (_now(), serial),
        )

    def get(self, serial: str) -> DeviceRow | None:
        row = self.db.fetchone(
            "SELECT * FROM devices WHERE serial = ?", (serial,)
        )
        return DeviceRow.from_row(row) if row else None

    def list_all(self) -> list[DeviceRow]:
        rows = self.db.fetchall("SELECT * FROM devices ORDER BY name")
        return [DeviceRow.from_row(r) for r in rows]


class RunRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(self, device_id: int, scenario: str) -> int:
        cur = self.db.execute(
            "INSERT INTO runs (device_id, scenario, started_at, status) "
            "VALUES (?, ?, ?, 'running')",
            (device_id, scenario, _now()),
        )
        return int(cur.lastrowid)

    def end(
        self,
        run_id: int,
        status: str,
        last_error: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE runs SET status = ?, ended_at = ?, last_error = ? "
            "WHERE id = ?",
            (status, _now(), last_error, run_id),
        )

    def increment_iteration(self, run_id: int) -> None:
        self.db.execute(
            "UPDATE runs SET iteration_count = iteration_count + 1 "
            "WHERE id = ?",
            (run_id,),
        )

    def increment_error(self, run_id: int, message: str) -> None:
        self.db.execute(
            "UPDATE runs SET error_count = error_count + 1, last_error = ? "
            "WHERE id = ?",
            (message, run_id),
        )

    def log_event(self, run_id: int, level: str, message: str) -> None:
        self.db.execute(
            "INSERT INTO run_events (run_id, ts, level, message) "
            "VALUES (?, ?, ?, ?)",
            (run_id, _now(), level, message),
        )

    def get(self, run_id: int) -> RunRow | None:
        row = self.db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
        return RunRow.from_row(row) if row else None

    def list_recent(self, device_id: int, limit: int = 10) -> list[RunRow]:
        rows = self.db.fetchall(
            "SELECT * FROM runs WHERE device_id = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (device_id, limit),
        )
        return [RunRow.from_row(r) for r in rows]

    def list_events(self, run_id: int, limit: int = 100) -> list[RunEventRow]:
        rows = self.db.fetchall(
            "SELECT * FROM run_events WHERE run_id = ? "
            "ORDER BY ts DESC LIMIT ?",
            (run_id, limit),
        )
        return [RunEventRow.from_row(r) for r in rows]
