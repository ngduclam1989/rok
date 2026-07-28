"""`python main.py bot` — chạy state-machine bot cho 1 thiết bị."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from core import bot as bot_engine
from core.config_io import first_device_serial
from core.device import Device

from ..paths import DEVICES_FILE, TEMPLATES_DIR
from ..prompts import run_bot_wizard


def _attach_file_log_handler(log_file: str) -> None:
    """Ghi log của bot vào ``log_file`` SONG SONG với stdout.

    Dùng cho fleet: parent pass ``--log-file logs/<serial>.log`` để
    mỗi máy có 1 file log riêng. Stdout vẫn cần để parent đọc + in
    console kèm prefix tên máy.
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logging.getLogger().addHandler(fh)
    logging.info("Ghi log ra %s", log_path)


def cmd_bot(args: argparse.Namespace) -> int:
    # Nếu không truyền --serial trên CLI -> bật chế độ hỏi tương tác.
    if args.serial is None or args.interactive:
        default_serial = first_device_serial(DEVICES_FILE) or ""
        run_bot_wizard(args, default_serial=default_serial)

    serial = args.serial
    if not serial:
        logging.error("Chưa có --serial và devices.yaml cũng rỗng")
        return 1

    log_file = getattr(args, "log_file", None)
    if log_file:
        _attach_file_log_handler(log_file)

    import sys
    import random
    import time
    from core.config_io import load_bot_fleet_config, split_resource_and_farm_scenario
    from core.bot.bluestack import start_bluestack, stop_bluestack, get_instance_name_by_port, is_port_open
    from core.bot.signals import install_signal_handler, install_pause_hotkey, should_stop, sleep_with_stop_check_exact, pause

    install_signal_handler()
    install_pause_hotkey()

    only_claim_vip = getattr(args, "only_claim_vip", False)

    while not should_stop():
        try:
            fleet_cfg = load_bot_fleet_config(DEVICES_FILE)
            dev_cfg = next((c for c in fleet_cfg if c.serial == serial), None)
        except Exception:
            dev_cfg = None

        # Áp cấu hình từ CLI > devices.yaml > Mặc định hệ thống
        resource = args.resource
        if resource is None:
            resource = dev_cfg.resource if dev_cfg else "wood"

        farm_scenario = getattr(args, "farm_scenario", None)
        if farm_scenario is None:
            farm_scenario = dev_cfg.farm_scenario if dev_cfg else "random"
        
        target_level = args.target_level
        if target_level is None:
            target_level = dev_cfg.target_level if dev_cfg else 5

        max_slots = args.max_slots
        if max_slots is None:
            max_slots = dev_cfg.max_slots if dev_cfg else 4

        # skip_level_adjust: kiểm tra xem có cờ trong sys.argv hay không, nếu không lấy từ devices.yaml
        if "--skip-level-adjust" in sys.argv:
            skip_level_adjust = True
        else:
            skip_level_adjust = dev_cfg.skip_level_adjust if dev_cfg else False

        turn_wait_min = args.turn_wait_min
        if turn_wait_min is None:
            turn_wait_min = dev_cfg.turn_wait_min if dev_cfg else 60

        # Lưu cấu hình xuống engine
        bot_engine.TARGET_LEVEL = target_level
        bot_engine.MAX_SLOTS = max_slots
        res_map = {"ngo": "corn", "food": "corn", "crop": "corn"}
        resource = res_map.get(resource, resource)
        resource, farm_scenario = split_resource_and_farm_scenario(
            resource,
            farm_scenario,
        )
        bot_engine.RESOURCE_TAB = resource
        bot_engine.FARM_SCENARIO = str(farm_scenario).strip().lower()
        bot_engine.SKIP_LEVEL_ADJUST = skip_level_adjust
        bot_engine.TURN_WAIT_SEC = turn_wait_min * 60
        bot_engine.ONLY_CLAIM_VIP = only_claim_vip

        enable_vip_claim = getattr(args, "enable_vip_claim", False)
        if not enable_vip_claim and dev_cfg:
            enable_vip_claim = bot_engine.config.ENABLE_VIP_CLAIM
        bot_engine.config.ENABLE_VIP_CLAIM = enable_vip_claim

        logging.info(
            "Cấu hình bot: tài nguyên=%s cấp=%d slot=%d bỏ-chỉnh-cấp=%s đợi(phút)=%d nhận-vip=%s",
            bot_engine.RESOURCE_TAB,
            bot_engine.TARGET_LEVEL,
            bot_engine.MAX_SLOTS,
            bot_engine.SKIP_LEVEL_ADJUST,
            turn_wait_min,
            bot_engine.config.ENABLE_VIP_CLAIM,
        )

        s = str(serial).strip()
        port_str = s.split(":")[-1] if ":" in s else s
        is_bluestacks = False
        try:
            port = int(port_str)
            if get_instance_name_by_port(port) is not None:
                is_bluestacks = True
        except ValueError:
            pass

        if is_bluestacks:
            logging.info("B1: Phát hiện cấu hình Bluestacks. Kiểm tra trạng thái và bật...")
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
                logging.info("Bluestacks chưa bật. Tiến hành bật lên...")
                if not start_bluestack(serial):
                    logging.error("Không thể khởi động hoặc kết nối Bluestacks cho %s", serial)
                    return 1
                logging.info("Đã bật Bluestacks thành công. Chờ thêm 10s cho giả lập ổn định...")
                pause(10.0)
            else:
                logging.info("Bluestacks đã bật sẵn. Bỏ qua chờ 10s và chuyển sang B2.")
        else:
            logging.info("B1: Thiết bị không thuộc cấu hình Bluestacks hoặc không tìm thấy instance. Bỏ qua tự động bật/tắt.")

        control_mode = args.control_mode
        if control_mode is None:
            control_mode = dev_cfg.control_mode if dev_cfg else "adb"
        scrcpy_window_path = (
            dev_cfg.scrcpy_path
            if dev_cfg and dev_cfg.open_scrcpy_window
            else None
        )

        bot_engine.config.ENABLE_INPUT_LOCK = False
        device = Device(
            serial,
            TEMPLATES_DIR,
            control_mode=control_mode,
            scrcpy_window_path=scrcpy_window_path,
        )
        try:
            bot_engine.run(device, max_iterations=args.max_iter)
        finally:
            if getattr(bot_engine.config, "CYCLE_WAIT_MIN", 120) == 0:
                logging.info("B5: CYCLE_WAIT_MIN = 0 -> force-stop game before exiting bot.")
                device.shutdown()
            else:
                device.close()
            if is_bluestacks:
                if getattr(bot_engine.config, "AUTO_CLOSE_BLUESTACK", False):
                    logging.info("B5: Kết thúc bot. Tiến hành tắt Bluestacks...")
                    from core.bot.bluestack import stop_bluestack
                    stop_bluestack(serial)
                else:
                    logging.info("B5: Kết thúc bot. Giữ nguyên trạng thái Bluestacks (không tắt).")
                pause(5.0)

        if only_claim_vip or should_stop():
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
            "🔹 B6: Chờ và chạy lại bot. Ngủ %d giây (~%.1f phút) trước khi bắt đầu lượt mới...",
            wait_sec, wait_sec / 60.0
        )
        sleep_with_stop_check_exact(wait_sec)

    return 0
