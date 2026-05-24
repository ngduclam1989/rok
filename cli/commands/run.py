"""`python main.py run` — chạy scenario YAML legacy (đa thiết bị).

Đây là engine cũ — bot mới dùng `python main.py bot` hoặc
`python main.py fleet`.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from core.config_io import load_legacy_devices_config
from core.runner import DeviceConfig, FleetRunner
from core.store import Database, DeviceRepository, RunRepository, init_schema

from ..paths import DEVICES_FILE, SCENARIOS_DIR, TEMPLATES_DIR


def _init_store(
    db_path: Path,
) -> tuple[Database, DeviceRepository, RunRepository]:
    db = Database(db_path)
    init_schema(db)
    return db, DeviceRepository(db), RunRepository(db)


def cmd_run(args: argparse.Namespace) -> int:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)

    _, device_repo, run_repo = _init_store(Path(args.db))

    if args.serial and args.scenario:
        devices = [
            DeviceConfig(
                name=args.serial,
                serial=args.serial,
                scenario=args.scenario,
            )
        ]
    else:
        devices = load_legacy_devices_config(DEVICES_FILE)

    if not devices:
        logging.error("Chưa cấu hình thiết bị nào")
        return 1

    runner = FleetRunner(
        devices, SCENARIOS_DIR, TEMPLATES_DIR, device_repo, run_repo,
    )
    runner.start()
    runner.wait()
    return 0
