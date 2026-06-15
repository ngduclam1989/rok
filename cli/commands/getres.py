"""`python main.py getres SERIAL` - collect floating resources in City."""
from __future__ import annotations

import argparse
import logging

from core.bot.chores import collect_city_resources
from core.device import Device

from ..paths import TEMPLATES_DIR


def cmd_getres(args: argparse.Namespace) -> int:
    serial = str(args.serial).strip()
    if not serial:
        logging.error("Thieu serial thiet bi")
        return 1

    device = Device(serial, TEMPLATES_DIR, control_mode=args.control_mode)
    ok = collect_city_resources(device, max_resources=args.max_resources)
    return 0 if ok else 1
