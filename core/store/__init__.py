"""Persistence layer — SQLite now, easy port to Postgres later.

Public API:
    Database               — thread-safe connection manager
    init_schema(db)        — idempotent CREATE TABLE
    DeviceRepository       — device CRUD + status
    RunRepository          — scenario runs + events
    DeviceRow, RunRow, RunEventRow
    DbObserver             — bridges ScenarioRunner events to DB
"""
from .db import Database
from .models import DeviceRow, RunEventRow, RunRow
from .observers import DbObserver
from .repositories import DeviceRepository, RunRepository
from .schema import init_schema
from .app_manager import restart_game_app

__all__ = [
    "Database",
    "DbObserver",
    "DeviceRepository",
    "DeviceRow",
    "RunEventRow",
    "RunRepository",
    "RunRow",
    "init_schema",
    "restart_game_app",
]
