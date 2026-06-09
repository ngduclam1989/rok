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
        import threading
        from core.device import Device
        from core import bot as bot_engine
        from core.bot.bluestack import start_bluestack, stop_bluestack, get_instance_name_by_port, is_port_open
        from core.bot.signals import install_signal_handler, install_pause_hotkey, should_stop, sleep_with_stop_check_exact
        from ..paths import TEMPLATES_DIR

        logging.info("=== CHẾ ĐỘ CHẠY TUẦN TỰ (SEQUENTIAL MODE) ===")
        install_signal_handler()
        install_pause_hotkey()   # Ctrl+Space pause/resume

        # Biến dùng chung để chia sẻ trạng thái thiết bị đang hoạt động cho tiến trình chạy ngầm
        active_serial_container = [None]
        # Container chia sẻ thời điểm bắt đầu chu kỳ farm tiếp theo (monotonic)
        next_cycle_time_container = [time.monotonic()]
        # Flag: True khi đang trong giai đoạn chờ 3h (giữa các chu kỳ farm)
        # Thread nền CHỈ được thực hiện hành động khi flag này = True
        is_waiting_container = [False]

        def sleep_with_stop_check(duration_seconds: float) -> bool:
            # Sleep ngắt quãng 1s để phản hồi nhanh với tín hiệu dừng (Ctrl+C)
            start_t = time.monotonic()
            while time.monotonic() - start_t < duration_seconds:
                if should_stop():
                    return True
                time.sleep(1.0)
            return False

        def background_periodic_kill():
            last_killed = None
            logging.info("[Background] Khởi chạy tiến trình chạy ngầm định kỳ tái khởi động game...")
            while not should_stop():
                # Chờ ngẫu nhiên theo cấu hình (đổi từ phút sang giây)
                from core.bot import config
                wait_sec = random.randint(config.BG_ACTION_INTERVAL_MIN * 60, config.BG_ACTION_INTERVAL_MAX * 60)
                if sleep_with_stop_check(float(wait_sec)):
                    break

                # Load cấu hình mới nhất
                latest_cfg = load_bot_fleet_config(DEVICES_FILE)
                if not latest_cfg:
                    continue

                active_s = active_serial_container[0]

                # Chỉ hoạt động trong giai đoạn chờ 3h giữa các chu kỳ farm
                # (không làm gì khi đang chạy farm 4 máy tuần tự)
                if not is_waiting_container[0]:
                    logging.info(
                        "[Background] Chưa vào giai đoạn chờ 3h (đang farm tuần tự) "
                        "→ bỏ qua lần này."
                    )
                    continue

                # Nếu có máy đang chạy bot farm thì không cần làm gì cả
                if active_s is not None:
                    remaining = next_cycle_time_container[0] - time.monotonic()
                    if remaining > 0:
                        rm_h = int(remaining) // 3600
                        rm_m = (int(remaining) % 3600) // 60
                        rm_s = int(remaining) % 60
                        logging.info(
                            "[Background] Máy %s đang farm → bỏ qua. Chu kỳ tiếp theo còn: %dh%02dm%02ds.",
                            active_s, rm_h, rm_m, rm_s
                        )
                    else:
                        logging.info("[Background] Máy %s đang farm → bỏ qua.", active_s)
                    continue

                # Lọc ra thiết bị không phải active (đang chạy bot) và không phải thiết bị vừa bị kill
                candidates = [
                    c for c in latest_cfg 
                    if c.serial != active_s and c.serial != last_killed
                ]
                if not candidates:
                    # Nếu không có ứng viên, thử bỏ điều kiện last_killed để tránh block khi có ít máy
                    candidates = [c for c in latest_cfg if c.serial != active_s]

                if not candidates:
                    continue

                target = random.choice(candidates)
                last_killed = target.serial

                logging.info(
                    "[Background] Định kỳ 10-20': Thực hiện tối ưu trạng thái game trên %s (%s)...",
                    target.name, target.serial
                )
                try:
                    # --- Kiểm tra lại lần cuối: nếu máy vừa được kích hoạt để farm thì bỏ qua ---
                    if active_serial_container[0] == target.serial:
                        logging.info(
                            "[Background] %s vừa được kích hoạt để farm → bỏ qua lần này.",
                            target.name
                        )
                        continue

                    # --- Kiểm tra Bluestacks có đang bật không (port mở) ---
                    s_bg = str(target.serial).strip()
                    port_str_bg = s_bg.split(":")[-1] if ":" in s_bg else s_bg
                    bg_port = None
                    try:
                        bg_port = int(port_str_bg)
                    except ValueError:
                        pass

                    if bg_port is not None:
                        if not is_port_open(bg_port):
                            logging.warning(
                                "[Background] %s (%s): Bluestacks chưa bật (port %d đóng) → bỏ qua hành động.",
                                target.name, target.serial, bg_port
                            )
                            continue

                    # Luôn dùng control_mode='adb' ở background để không chiếm chuột thật PC
                    dev = Device(target.serial, TEMPLATES_DIR, control_mode="adb")

                    # Chọn ngẫu nhiên hành động: kill app và vào lại, hoặc về thành rồi quay ra world
                    action = random.choice(["kill_relaunch", "toggle_city_world"])

                    if action == "kill_relaunch":
                        logging.info("[Background] Hành động: force-stop và khởi động lại game com.rok.gp.vn trên %s...", target.name)
                        dev._adb_shell("am", "force-stop", "com.rok.gp.vn")
                        time.sleep(5.0)

                        logging.info("[Background] Khởi chạy lại game trên %s...", target.name)
                        dev.start_game()

                        # Chờ game tải (25s), bấm pop-up và điều hướng về WORLD
                        time.sleep(25.0)
                        dev.tap(1200, 540)
                        time.sleep(float(random.randint(5, 15)))

                        from core.bot.runtime import _initial_navigate_to_world
                        _initial_navigate_to_world(dev)
                    else:
                        logging.info("[Background] Hành động: về thành rồi quay ra world trên %s...", target.name)
                        from core.bot.detection import detect_state
                        from core.bot.constants import State as S
                        from core.bot.geometry import pct_to_px, tap_template

                        screen = dev.snapshot()
                        h, w = screen.shape[:2]
                        state = detect_state(dev, screen)

                        # Định nghĩa hàm chạm nút chuyển bản đồ (Map Toggle)
                        def tap_map_toggle(scr):
                            pos = tap_template(
                                dev, scr, "btn_map_toggle.png", 0.75,
                                region_pct=(0, 80, 15, 100),
                            )
                            if pos is None:
                                dev.tap(int(w * 0.06), int(h * 0.912))

                        if state == S.WORLD:
                            # 1. Chuyển sang CITY (Về thành)
                            logging.info("[Background] Đang ở WORLD -> chuyển sang CITY")
                            tap_map_toggle(screen)
                            time.sleep(5.0)
                            # 2. Chuyển ngược lại WORLD (Quay ra world)
                            logging.info("[Background] Đang ở CITY -> chuyển ngược lại WORLD")
                            try:
                                screen2 = dev.snapshot()
                                tap_map_toggle(screen2)
                            except Exception:
                                dev.tap(int(w * 0.06), int(h * 0.912))
                            time.sleep(5.0)
                        elif state == S.CITY:
                            # Chuyển sang WORLD
                            logging.info("[Background] Đang ở CITY -> chuyển sang WORLD")
                            tap_map_toggle(screen)
                            time.sleep(5.0)
                        else:
                            # Ở các trạng thái khác, dùng initial navigate to world để dọn dẹp
                            logging.info("[Background] Trạng thái hiện tại: %s -> dùng initial_navigate_to_world", state.value)
                            from core.bot.runtime import _initial_navigate_to_world
                            _initial_navigate_to_world(dev)

                    logging.info("[Background] Đã hoàn thành xử lý thiết bị %s.", target.name)

                    # --- Thông báo còn bao nhiêu thời gian trước chu kỳ farm tiếp theo ---
                    remaining = next_cycle_time_container[0] - time.monotonic()
                    if remaining > 0:
                        rm_h = int(remaining) // 3600
                        rm_m = (int(remaining) % 3600) // 60
                        rm_s = int(remaining) % 60
                        logging.info(
                            "[Background] Chu kỳ farm tiếp theo còn: %dh%02dm%02ds.",
                            rm_h, rm_m, rm_s
                        )
                    else:
                        logging.info("[Background] Chu kỳ farm tiếp theo sắp bắt đầu (hoặc đang chạy).")

                except Exception as ex:
                    logging.error("[Background] Lỗi tự động tái khởi động game trên %s: %s", target.name, ex)

        # Chạy tiến trình ngầm
        bg_thread = threading.Thread(target=background_periodic_kill, daemon=True)
        bg_thread.start()

        is_first_cycle = True
        while True:
            # Load lại devices.yaml mỗi chu kỳ để cập nhật thay đổi (ví dụ: comment/uncomment máy)
            members_cfg = load_bot_fleet_config(DEVICES_FILE)
            if not members_cfg:
                logging.warning("Không có máy nào hoạt động trong devices.yaml. Đợi 60s rồi kiểm tra lại...")
                sleep_with_stop_check_exact(60.0)
                if should_stop():
                    break
                continue

            # Đầu mỗi chu kỳ farm: tắt cờ chờ để thread nền biết đang farm
            is_waiting_container[0] = False

            # B6: Sắp xếp thứ tự kiểm tra thiết bị: Chu kỳ đầu chạy mặc định 1->2->3->4, sau đó random thay đổi thứ tự
            ordered_members = list(members_cfg)
            if is_first_cycle:
                is_first_cycle = False
                cycle_label = "Mặc định (Chu kỳ đầu)"
            else:
                random.shuffle(ordered_members)
                cycle_label = "Ngẫu nhiên (Đổi thứ tự)"

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

                active_serial_container[0] = c.serial
                try:
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
                        else:
                            logging.info(">>> Hoàn thành dọn dẹp thiết bị %s. Chờ 5s...\n", c.name)
                            time.sleep(5.0)
                finally:
                    active_serial_container[0] = None

            if should_stop():
                logging.info("Phát hiện tín hiệu dừng. Kết thúc chạy tuần tự.")
                break

            # B6: Sau khi quét xong TOÀN BỘ chu kỳ (tất cả thiết bị),
            # chờ ngẫu nhiên theo cấu hình (CYCLE_WAIT_MIN +- CYCLE_WAIT_VARIANCE_MIN) đổi sang giây
            from core.bot import config
            wait_min = random.randint(
                max(1, config.CYCLE_WAIT_MIN - config.CYCLE_WAIT_VARIANCE_MIN),
                config.CYCLE_WAIT_MIN + config.CYCLE_WAIT_VARIANCE_MIN
            )
            wait_sec = wait_min * 60
            wait_h = wait_sec // 3600
            wait_m = (wait_sec % 3600) // 60
            wait_s = wait_sec % 60
            sys.stdout.write(
                f"\n[B6] Đã quét xong {len(ordered_members)} thiết bị. "
                f"Chờ {wait_h}h{wait_m:02d}m{wait_s:02d}s trước chu kỳ tiếp theo...\n\n"
            )
            # Cập nhật thời điểm chu kỳ tiếp theo để thread nền có thể báo thời gian còn lại
            next_cycle_time_container[0] = time.monotonic() + float(wait_sec)
            # Bật cờ: đang trong giai đoạn chờ 3h → thread nền được phép hoạt động
            is_waiting_container[0] = True
            sleep_with_stop_check_exact(float(wait_sec))
            # Tắt cờ ngay khi thức dậy (sẽ bật lại đầu vòng lặp kế tiếp nếu còn chờ)
            is_waiting_container[0] = False


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
