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
        import random
        from core.device import Device
        from core import bot as bot_engine
        from core.bot.bluestack import start_bluestack, stop_bluestack, get_instance_name_by_port, is_port_open
        from core.bot.signals import (
            install_signal_handler,
            install_pause_hotkey,
            should_stop,
            wait_if_paused,
            pause,
            sleep_with_stop_check_exact,
        )
        from ..paths import TEMPLATES_DIR

        logging.info("=== CHẾ ĐỘ CHẠY TUẦN TỰ (SEQUENTIAL MODE) ===")
        install_signal_handler()
        install_pause_hotkey()   # Ctrl+Space pause/resume

        while not should_stop():
            members_cfg = load_bot_fleet_config(DEVICES_FILE)
            if not members_cfg:
                logging.error(
                    "Không có máy nào trong devices.yaml. "
                    "Thêm 1 thiết bị rồi chạy lại.",
                )
                return 1

            ordered_members = list(members_cfg)
            sys.stdout.write(
                f"\n=== BẮT ĐẦU CHẠY TUẦN TỰ MỘT LƯỢT "
                f"(Thứ tự: {[m.name for m in ordered_members]}) ===\n",
            )

            for index, c in enumerate(ordered_members):
                wait_if_paused()
                if should_stop():
                    break
                device = None

                sys.stdout.write(
                    f"[{index + 1}/{len(ordered_members)}] Đang kiểm tra thiết bị: {c.name} ({c.serial})...\n"
                )

                # Kiểm tra xem có phải Bluestacks không
                s = str(c.serial).strip()
                port_str = s.split(":")[-1] if ":" in s else s
                is_bluestacks = False
                try:
                    port = int(port_str)
                    if get_instance_name_by_port(port) is not None:
                        is_bluestacks = True
                except ValueError:
                    pass

                try:
                    # B1: kiểm tra xem bluestack có địa chỉ đã bật chưa, chưa thì bật lên và chờ 10s còn đã bật rồi thì chạy B2
                    if is_bluestacks:
                        logging.info("[%s] B1: Kiểm tra trạng thái Bluestacks...", c.name)
                        instance_name = get_instance_name_by_port(port)
                        is_running = False
                        if instance_name:
                            import psutil
                            for proc in psutil.process_iter(['name', 'cmdline']):
                                try:
                                    if proc.info['name'] == 'HD-Player.exe' and proc.info['cmdline']:
                                        cmdline = proc.info['cmdline']
                                        if '--instance' in cmdline:
                                            idx = cmdline.index('--instance')
                                            if idx + 1 < len(cmdline) and cmdline[idx+1] == instance_name:
                                                is_running = True
                                                break
                                except Exception:
                                    continue
                        
                        if not is_running:
                            logging.info("[%s] Bluestacks chưa bật. Tiến hành bật lên...", c.name)
                            if not start_bluestack(c.serial):
                                logging.error("[%s] Không thể khởi động hoặc kết nối Bluestacks. Chuyển sang máy tiếp theo.", c.name)
                                continue
                            logging.info("[%s] Đã bật Bluestacks thành công. Chờ thêm 10s cho giả lập ổn định...", c.name)
                            pause(10.0)
                        else:
                            logging.info("[%s] Bluestacks đã bật sẵn.", c.name)

                    # Khởi tạo thiết bị
                    try:
                        control_mode = getattr(c, "control_mode", "adb")
                        bot_engine.config.ENABLE_INPUT_LOCK = False
                        device = Device(c.serial, TEMPLATES_DIR, control_mode=control_mode)
                    except Exception as e:
                        logging.error("Không thể kết nối đến thiết bị %s: %s. Chuyển sang thiết bị tiếp theo.", c.name, e)
                        continue

                    # Gán tham số cấu hình bot
                    bot_engine.TARGET_LEVEL = c.target_level
                    bot_engine.MAX_SLOTS = c.max_slots
                    bot_engine.RESOURCE_TAB = c.resource
                    bot_engine.FARM_SCENARIO = c.farm_scenario
                    bot_engine.SKIP_LEVEL_ADJUST = c.skip_level_adjust
                    bot_engine.TURN_WAIT_SEC = c.turn_wait_min * 60

                    # Chạy kịch bản farm
                    logging.info("Bắt đầu chạy kịch bản farm cho thiết bị %s...", c.name)
                    try:
                        bot_engine.run(device)
                    except Exception as e:
                        logging.error("Lỗi xảy ra khi đang chạy bot trên thiết bị %s: %s", c.name, e)
                finally:
                    if device is not None:
                        device.close()
                    # B5: sau khi chạy xong hoặc gặp bất kỳ lỗi gì, dọn dẹp và đóng Bluestacks nếu cấu hình yêu cầu
                    if is_bluestacks:
                        if getattr(bot_engine.config, "AUTO_CLOSE_BLUESTACK", False):
                            logging.info(">>> Dọn dẹp thiết bị %s. Tiến hành tắt Bluestacks...", c.name)
                            from core.bot.bluestack import stop_bluestack
                            stop_bluestack(c.serial)
                        else:
                            logging.info(">>> Dọn dẹp thiết bị %s. Giữ nguyên trạng thái Bluestacks...", c.name)
                        pause(5.0)
                    else:
                        logging.info(">>> Hoàn thành dọn dẹp thiết bị %s. Chờ 5s...\n", c.name)
                        pause(5.0)

            if should_stop():
                break

            # B6: Chờ và chạy lại bot (Đọc cấu hình động từ devices.yaml)
            cycle_wait = getattr(bot_engine.config, "CYCLE_WAIT_MIN", 120)
            if cycle_wait == 0:
                logging.info("CYCLE_WAIT_MIN = 0 -> Thoát bot sau khi chạy hết vòng.")
                break
            variance = getattr(bot_engine.config, "CYCLE_WAIT_VARIANCE_MIN", 10)
            min_wait = max(0, cycle_wait - variance)
            max_wait = cycle_wait + variance
            wait_sec = random.randint(min_wait * 60, max_wait * 60)
            logging.info(
                "🔹 B6: Đã hoàn thành một lượt chạy tuần tự cho tất cả thiết bị. "
                "Ngủ %d giây (~%.1f phút) trước khi bắt đầu lượt mới...",
                wait_sec, wait_sec / 60.0
            )
            sleep_with_stop_check_exact(wait_sec)

        logging.info("=== Đã hoàn thành chạy tuần tự cho tất cả thiết bị. Tắt bot ===")
        return 0

    # Chế độ chạy SONG SONG mặc định
    has_physical_mouse = any(getattr(c, "control_mode", "adb") == "physical_mouse" for c in members_cfg)
    if has_physical_mouse:
        logging.error(
            "CẢNH BÁO NGHIÊM TRỌNG: Bạn không thể chạy SONG SONG nhiều thiết bị khi sử dụng chế độ 'physical_mouse' (chiếm chuột). "
            "Chuột máy tính sẽ bị nhảy loạn xạ giữa các cửa sổ. "
            "Vui lòng chuyển sang chạy TUẦN TỰ (dùng tham số --sequential) hoặc dùng chế độ 'adb'."
        )
        return 1

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
