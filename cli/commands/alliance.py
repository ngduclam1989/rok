"""`python main.py alliance SERIAL` - Chạy các hành động liên minh trên 1 thiết bị."""
from __future__ import annotations

import argparse
import logging

from core.bot.chores import (
    do_alliance_help,
    do_alliance_gifts,
    do_alliance_territory,
    do_alliance_tech,
)
from core.device import Device

from ..paths import TEMPLATES_DIR

log = logging.getLogger(__name__)


def cmd_alliance(args: argparse.Namespace) -> int:
    serial = str(args.serial).strip()
    if not serial:
        logging.error("Thiếu serial thiết bị")
        return 1

    device = Device(serial, TEMPLATES_DIR, control_mode=args.control_mode)
    
    log.info(">>> BẮT ĐẦU CHẠY CÁC HOẠT ĐỘNG LIÊN MINH CHO %s <<<", serial)
    
    try:
        do_alliance_help(device)
    except Exception as e:
        log.exception("Lỗi trợ giúp liên minh: %s", e)
        
    try:
        do_alliance_gifts(device)
    except Exception as e:
        log.exception("Lỗi nhận quà liên minh: %s", e)
        
    try:
        do_alliance_territory(device)
    except Exception as e:
        log.exception("Lỗi thu tài nguyên lãnh thổ: %s", e)
        
    try:
        do_alliance_tech(device)
    except Exception as e:
        log.exception("Lỗi đóng góp công nghệ liên minh: %s", e)
        
    log.info(">>> HOÀN THÀNH CÁC HOẠT ĐỘNG LIÊN MINH CHO %s <<<", serial)
    return 0
