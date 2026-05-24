"""`python main.py devices` — liệt kê thiết bị ADB đang kết nối."""
from __future__ import annotations

import argparse
import subprocess
import sys

from airtest.core.android.adb import ADB


def cmd_devices(_: argparse.Namespace) -> int:
    adb_path = ADB().adb_path
    result = subprocess.run(  # noqa: S603,S607 — local adb invocation
        [adb_path, "devices"],
        capture_output=True,
        text=True,
        check=False,
    )
    sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode

