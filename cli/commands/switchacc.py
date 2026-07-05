"""`python main.py switchacc` - stress-test only account switching."""
from __future__ import annotations

import argparse
import logging

from core.config_io import first_device_serial
from core.bot.switch_account_loop import run_switch_account_loop

from ..paths import DEVICES_FILE, ROOT, TEMPLATES_DIR


def cmd_switchacc(args: argparse.Namespace) -> int:
    serial = args.serial or first_device_serial(DEVICES_FILE)
    if not serial:
        logging.error("Chua co --serial va devices.yaml cung rong")
        return 1

    return run_switch_account_loop(
        serial=serial,
        templates_dir=TEMPLATES_DIR,
        devices_file=DEVICES_FILE,
        account_file=ROOT / "account.txt",
        control_mode=args.control_mode,
        loops=args.loops,
        wait_after_switch_sec=args.wait_after_switch_sec,
        fail_sleep_min_sec=args.fail_sleep_min_sec,
        fail_sleep_max_sec=args.fail_sleep_max_sec,
        kill_after_fails=args.kill_after_fails,
        save_fail_screens=not args.no_fail_screens,
        open_game=not args.no_open_game,
    )
