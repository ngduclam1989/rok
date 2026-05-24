"""`python main.py status` — xem thiết bị + lượt chạy gần đây từ DB."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.store import Database, DeviceRepository, RunRepository, init_schema


def _init_store(
    db_path: Path,
) -> tuple[Database, DeviceRepository, RunRepository]:
    db = Database(db_path)
    init_schema(db)
    return db, DeviceRepository(db), RunRepository(db)


def cmd_status(args: argparse.Namespace) -> int:
    _, device_repo, run_repo = _init_store(Path(args.db))
    devices = device_repo.list_all()
    if not devices:
        sys.stdout.write(
            "Chưa có thiết bị nào trong DB. "
            "Chạy `python main.py run` trước.\n",
        )
        return 0
    header = (
        f"{'TÊN':<12} {'SERIAL':<20} {'MODEL':<16} "
        f"{'TRẠNG THÁI':<12} LẦN CHẠY GẦN NHẤT\n"
    )
    sys.stdout.write(header)
    for d in devices:
        runs = run_repo.list_recent(d.id, limit=1)
        if runs:
            r = runs[0]
            last = (
                f"{r.scenario} [{r.status}] "
                f"vòng={r.iteration_count} lỗi={r.error_count}"
            )
        else:
            last = "—"
        line = (
            f"{d.name:<12} {d.serial:<20} "
            f"{(d.model or '?'):<16} {d.status:<12} {last}\n"
        )
        sys.stdout.write(line)
    return 0
