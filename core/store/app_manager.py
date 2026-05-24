"""Application management and helper utilities."""
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

GAME_PACKAGE_NAME = "com.rok.gp.vn"

def restart_game_app(device: Any) -> None:
    """Tự động tắt ứng dụng game (nếu đang chạy) và khởi chạy lại sạch sẽ qua ADB."""
    log.info("[%s] Đang tự động khởi động lại ứng dụng game (%s)...", device.serial, GAME_PACKAGE_NAME)
    try:
        # Tắt ứng dụng trước
        device._adb_shell("am", "force-stop", GAME_PACKAGE_NAME)
        time.sleep(1.5)
        # Khởi động lại ứng dụng bằng monkey command
        device._adb_shell("monkey", "-p", GAME_PACKAGE_NAME, "-c", "android.intent.category.LAUNCHER", "1")
    except Exception as e:
        log.error("Không thể khởi động lại game %s: %s", GAME_PACKAGE_NAME, e)
