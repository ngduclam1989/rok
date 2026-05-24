"""`python main.py detect` — nhận diện trạng thái màn hình (không chạm)."""
from __future__ import annotations

import argparse
import logging
import sys

from core import bot as bot_engine
from core.config_io import first_device_serial
from core.device import Device

from ..paths import DEVICES_FILE, TEMPLATES_DIR


def cmd_detect(args: argparse.Namespace) -> int:
    serial = args.serial or first_device_serial(DEVICES_FILE)
    if not serial:
        logging.error("Chưa có --serial và devices.yaml cũng rỗng")
        return 1

    device = Device(serial, TEMPLATES_DIR)
    screen = device.snapshot()
    state = bot_engine.detect_state(device, screen)
    n, mx = bot_engine.read_slot_badge(screen)
    sys.stdout.write(f"state={state.value} slot={n}/{mx}\n")
    return 0
