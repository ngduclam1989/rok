"""DbObserver — bridges ScenarioRunner events into SQLite via RunRepository.

The Scenario engine itself does NOT import the store package — it only
depends on a small Protocol defined in scenario.py. This keeps the
automation engine swappable and testable without a database.
"""
from __future__ import annotations

from .repositories import RunRepository


class DbObserver:
    def __init__(self, repo: RunRepository, run_id: int) -> None:
        self.repo = repo
        self.run_id = run_id

    def on_iteration(self) -> None:
        self.repo.increment_iteration(self.run_id)

    def on_error(self, message: str) -> None:
        self.repo.increment_error(self.run_id, message)

    def on_log(self, level: str, message: str) -> None:
        self.repo.log_event(self.run_id, level, message)
