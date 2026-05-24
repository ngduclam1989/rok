"""Frozen row dataclasses — keep SQL rows out of the rest of the app."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceRow:
    id: int
    serial: str
    name: str
    model: str | None
    screen_w: int | None
    screen_h: int | None
    first_seen_at: str
    last_seen_at: str
    status: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DeviceRow":
        return cls(
            id=row["id"],
            serial=row["serial"],
            name=row["name"],
            model=row["model"],
            screen_w=row["screen_w"],
            screen_h=row["screen_h"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            status=row["status"],
        )


@dataclass(frozen=True)
class RunRow:
    id: int
    device_id: int
    scenario: str
    started_at: str
    ended_at: str | None
    status: str
    iteration_count: int
    error_count: int
    last_error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RunRow":
        return cls(
            id=row["id"],
            device_id=row["device_id"],
            scenario=row["scenario"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            iteration_count=row["iteration_count"],
            error_count=row["error_count"],
            last_error=row["last_error"],
        )


@dataclass(frozen=True)
class RunEventRow:
    id: int
    run_id: int
    ts: str
    level: str
    message: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "RunEventRow":
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            ts=row["ts"],
            level=row["level"],
            message=row["message"],
        )
