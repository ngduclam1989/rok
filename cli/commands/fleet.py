"""`python main.py fleet` — chạy bot SONG SONG cho mọi máy trong devices.yaml.

Mỗi máy:
  * 1 subprocess riêng (process-isolated, 1 máy crash KHÔNG kéo
    máy khác chết).
  * 1 file log riêng `logs/<serial>.log`.
  * Stdout in console parent với prefix "thiết bị <tên>:".

Dừng:
  * Ctrl+C ở terminal -> dừng tất cả (graceful, đợi tối đa 30s).
  * Tạo file `STOP_<serial>.flag` -> dừng riêng 1 máy.
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.config_io import load_bot_fleet_config
from core.fleet import FleetMember, run_fleet

from ..paths import DEVICES_FILE, ROOT


def cmd_fleet(args: argparse.Namespace) -> int:
    members_cfg = load_bot_fleet_config(DEVICES_FILE)
    if not members_cfg:
        logging.error(
            "Không có máy nào trong devices.yaml. "
            "Thêm 1 thiết bị rồi chạy lại.",
        )
        return 1

    # Nếu chọn chạy TUẦN TỰ từng máy một
    if getattr(args, "sequential", False):
        import time
        from core.device import Device
        from core import bot as bot_engine
        from ..paths import TEMPLATES_DIR

        logging.info("=== CHẾ ĐỘ CHẠY TUẦN TỰ (SEQUENTIAL MODE) ===")
        sys.stdout.write(
            f"=== Khởi động fleet tuần tự ({len(members_cfg)} máy) ===\n",
        )
        for index, c in enumerate(members_cfg):
            sys.stdout.write(
                f"[{index + 1}/{len(members_cfg)}] Đang mở và chạy thiết bị: {c.name} ({c.serial})...\n"
            )
            
            # 1. Khởi động và kết nối thiết bị
            try:
                device = Device(c.serial, TEMPLATES_DIR)
                # Tự khởi động game khi kết nối thành công
                device.start_game()
            except Exception as e:
                logging.error("Không thể kết nối đến thiết bị %s: %s. Chuyển sang thiết bị tiếp theo.", c.name, e)
                continue
                
            # 3. Gán tham số cấu hình bot
            bot_engine.TARGET_LEVEL = c.target_level
            bot_engine.MAX_SLOTS = c.max_slots
            bot_engine.RESOURCE_TAB = c.resource
            bot_engine.SKIP_LEVEL_ADJUST = c.skip_level_adjust
            bot_engine.TURN_WAIT_SEC = c.turn_wait_min * 60
            
            # 4. Chạy kịch bản farm (Vào acc 1 -> Farm acc 1 -> Chuyển acc -> Farm acc 2 -> Ngừng)
            logging.info("Bắt đầu chạy kịch bản farm cho thiết bị %s...", c.name)
            try:
                bot_engine.run(device)
            except Exception as e:
                logging.error("Lỗi xảy ra khi đang chạy bot trên thiết bị %s: %s", c.name, e)
                
            logging.info(">>> Đã hoàn thành bot trên thiết bị %s (giữ nguyên game chạy). Chờ 5s trước khi chuyển sang thiết bị tiếp theo...\n", c.name)
            time.sleep(5.0)
            
        logging.info("=== ĐÃ HOÀN THÀNH CHẠY TUẦN TỰ CHO TOÀN BỘ DANH SÁCH THIẾT BỊ! ===")
        return 0

    # Chế độ chạy SONG SONG mặc định
    sys.stdout.write(
        f"=== Khởi động fleet ({len(members_cfg)} máy) ===\n",
    )
    for c in members_cfg:
        sys.stdout.write(
            f"  - {c.name} ({c.serial}): {c.resource} "
            f"cấp {c.target_level} slot {c.max_slots} "
            f"đợi {c.turn_wait_min}phút\n",
        )
    sys.stdout.write("\n")

    members = [
        FleetMember(
            name=c.name,
            serial=c.serial,
            bot_args=c.to_bot_cli_args(),
        )
        for c in members_cfg
    ]
    return run_fleet(members, project_root=ROOT)
