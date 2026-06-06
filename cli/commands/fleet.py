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
        from core.bot.bluestack import start_bluestack, stop_bluestack, get_instance_name_by_port, is_port_open
        from core.bot.signals import install_signal_handler, should_stop, sleep_with_stop_check_exact
        from ..paths import TEMPLATES_DIR

        logging.info("=== CHẾ ĐỘ CHẠY TUẦN TỰ (SEQUENTIAL MODE) ===")
        install_signal_handler()

        import random

        is_first_cycle = True   # Chu kỳ đầu: 1→2→3→4 theo thứ tự

        while True:
            # Load lại devices.yaml mỗi chu kỳ để cập nhật thay đổi (ví dụ: comment/uncomment máy)
            members_cfg = load_bot_fleet_config(DEVICES_FILE)
            if not members_cfg:
                logging.warning("Không có máy nào hoạt động trong devices.yaml. Đợi 60s rồi kiểm tra lại...")
                sleep_with_stop_check_exact(60.0)
                if should_stop():
                    break
                continue

            # B6: Sắp xếp thứ tự kiểm tra thiết bị
            #   - Chu kỳ ĐẦU TIÊN (lúc khởi động): 1 → 2 → 3 → 4 (đúng thứ tự trong devices.yaml)
            #   - Từ chu kỳ THỨ 2 trở đi    : máy 1 cố định đứng đầu, random các máy còn lại
            if is_first_cycle:
                ordered_members = list(members_cfg)
                is_first_cycle = False
                cycle_label = "Khởi động — thứ tự mặc định"
            else:
                primary = members_cfg[:1]       # máy 1 — luôn kiểm tra trước
                rest    = list(members_cfg[1:]) # máy 2, 3, 4, ... — xáo trộn
                random.shuffle(rest)
                ordered_members = primary + rest
                cycle_label = "Random"

            sys.stdout.write(
                f"\n=== BẮT ĐẦU CHU KỲ KIỂM TRA TUẦN TỰ [{cycle_label}] "
                f"(Thứ tự: {[m.name for m in ordered_members]}) ===\n",
            )


            for index, c in enumerate(ordered_members):
                if should_stop():
                    break

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
                        already_on = is_port_open(port)
                        if not already_on:
                            logging.info("[%s] Bluestacks chưa bật. Tiến hành bật lên...", c.name)
                            if not start_bluestack(c.serial):
                                logging.error("[%s] Không thể khởi động hoặc kết nối Bluestacks. Chuyển sang máy tiếp theo.", c.name)
                                continue
                            logging.info("[%s] Đã bật Bluestacks thành công. Chờ thêm 10s cho giả lập ổn định...", c.name)
                            time.sleep(10.0)
                        else:
                            logging.info("[%s] Bluestacks đã bật sẵn.", c.name)

                    # Khởi tạo thiết bị
                    try:
                        control_mode = getattr(c, "control_mode", "adb")
                        device = Device(c.serial, TEMPLATES_DIR, control_mode=control_mode)
                    except Exception as e:
                        logging.error("Không thể kết nối đến thiết bị %s: %s. Chuyển sang thiết bị tiếp theo.", c.name, e)
                        continue

                    # Gán tham số cấu hình bot
                    bot_engine.TARGET_LEVEL = c.target_level
                    bot_engine.MAX_SLOTS = c.max_slots
                    bot_engine.RESOURCE_TAB = c.resource
                    bot_engine.SKIP_LEVEL_ADJUST = c.skip_level_adjust
                    bot_engine.TURN_WAIT_SEC = c.turn_wait_min * 60

                    # Chạy kịch bản farm
                    logging.info("Bắt đầu chạy kịch bản farm cho thiết bị %s...", c.name)
                    try:
                        bot_engine.run(device)
                    except Exception as e:
                        logging.error("Lỗi xảy ra khi đang chạy bot trên thiết bị %s: %s", c.name, e)
                finally:
                    # B5: sau khi chạy xong hoặc gặp bất kỳ lỗi gì, dọn dẹp và giữ nguyên Bluestacks (không tắt)
                    if is_bluestacks:
                        logging.info(">>> Dọn dẹp thiết bị %s. Giữ nguyên trạng thái Bluestacks...", c.name)
                        time.sleep(5.0)
                        # Đã tắt stop_bluestack để giữ Bluestacks luôn mở
                    else:
                        logging.info(">>> Hoàn thành dọn dẹp thiết bị %s. Chờ 5s...\n", c.name)
                        time.sleep(5.0)

            if should_stop():
                logging.info("Phát hiện tín hiệu dừng. Kết thúc chạy tuần tự.")
                break

            # B6: Sau khi quét xong TOÀN BỘ chu kỳ (tất cả thiết bị),
            # chờ ngẫu nhiên 2h–2h10' (7200–7800 giây) rồi mới bắt đầu chu kỳ tiếp theo.
            wait_sec = random.randint(7200, 7800)
            wait_h = wait_sec // 3600
            wait_m = (wait_sec % 3600) // 60
            sys.stdout.write(
                f"\n[B6] Đã quét xong {len(ordered_members)} thiết bị. "
                f"Chờ {wait_h}h{wait_m:02d}' trước chu kỳ tiếp theo...\n\n"
            )
            sleep_with_stop_check_exact(float(wait_sec))



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
