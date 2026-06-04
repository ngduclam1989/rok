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

    # Áp config xuống bot engine ngay trước khi chạy.
    bot_engine.TARGET_LEVEL = args.target_level
    bot_engine.MAX_SLOTS = args.max_slots
    res_map = {"ngo": "corn", "food": "corn", "crop": "corn"}
    args.resource = res_map.get(args.resource, args.resource)
    bot_engine.RESOURCE_TAB = args.resource
    bot_engine.SKIP_LEVEL_ADJUST = args.skip_level_adjust
    bot_engine.TURN_WAIT_SEC = args.turn_wait_min * 60
    logging.info(
        "Cấu hình bot: tài nguyên=%s cấp=%d slot=%d " "bỏ-chỉnh-cấp=%s đợi(phút)=%d",
        bot_engine.RESOURCE_TAB,
        bot_engine.TARGET_LEVEL,
        bot_engine.MAX_SLOTS,
        bot_engine.SKIP_LEVEL_ADJUST,
        args.turn_wait_min,
    )

    from core.bot.bluestack import start_bluestack, stop_bluestack, get_instance_name_by_port
    import time

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
        from core.bot.bluestack import is_port_open
        already_on = is_port_open(port)
        if not already_on:
            logging.info("Bluestacks chưa bật. Tiến hành bật lên...")
            if not start_bluestack(serial):
                logging.error("Không thể khởi động hoặc kết nối Bluestacks cho %s", serial)
                return 1
            logging.info("Đã bật Bluestacks thành công. Chờ thêm 10s cho giả lập ổn định...")
            time.sleep(10.0)
        else:
            logging.info("Bluestacks đã bật sẵn. Bỏ qua chờ 10s và chuyển sang B2.")
    else:
        logging.info("B1: Thiết bị không thuộc cấu hình Bluestacks hoặc không tìm thấy instance. Bỏ qua tự động bật/tắt.")

    device = Device(serial, TEMPLATES_DIR)
    try:
        bot_engine.run(device, max_iterations=args.max_iter)
    finally:
        if is_bluestacks:
            logging.info("B5: Kết thúc bot. Chờ 5s trước khi tắt Bluestack...")
            time.sleep(5.0)
            stop_bluestack(serial)

    return 0
