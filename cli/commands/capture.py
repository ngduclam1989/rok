"""`python main.py capture` — chụp ảnh màn hình thiết bị."""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from core.config_io import first_device_serial
from airtest.core.android.adb import ADB

from ..paths import DEVICES_FILE, ROOT


def cmd_capture(args: argparse.Namespace) -> int:
    serial = args.serial or first_device_serial(DEVICES_FILE)
    if not serial:
        logging.error("Chưa có --serial và devices.yaml cũng rỗng")
        return 1
    if not args.serial:
        logging.info("Dùng thiết bị đầu trong devices.yaml: %s", serial)

    out = Path(args.out) if args.out else ROOT / "screenshot_current.png"
    remote = "/sdcard/_mini_game_cap.png"

    adb_path = ADB().adb_path
    if ":" in serial:
        subprocess.run([adb_path, "connect", serial], check=False)
    subprocess.run(  # noqa: S603,S607
        [adb_path, "-s", serial, "shell", "screencap", "-p", remote],
        check=True,
    )
    subprocess.run(  # noqa: S603,S607
        [adb_path, "-s", serial, "pull", remote, str(out)], check=True,
    )
    subprocess.run(  # noqa: S603,S607
        [adb_path, "-s", serial, "shell", "rm", remote], check=False,
    )

    sys.stdout.write(f"Đã lưu ảnh vào {out}\n")
    return 0
