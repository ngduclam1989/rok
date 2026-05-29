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
        log.info("[%s] Đã kích hoạt lệnh mở game, chờ 10s...", device.serial)
        time.sleep(10.0)

        # Thực hiện longtap tâm màn hình để bỏ qua intro/cinematic
        log.info("[%s] Hết 10s -> Thực hiện longtap vào tâm màn hình...", device.serial)
        try:
            screen = device.snapshot()
            h, w = screen.shape[:2]
            cx, cy = int(w * 0.5), int(h * 0.5)
            device.long_tap(cx, cy, duration_ms=500)
        except Exception as e:
            log.warning("[%s] Không chụp được màn hình, dùng tọa độ mặc định (1200, 540): %s", device.serial, e)
            try:
                device.long_tap(1200, 540, duration_ms=500)
            except Exception:
                pass
        
        log.info("[%s] Chờ thêm 15s cho game load vào world...", device.serial)
        time.sleep(15.0)
    except Exception as e:
        log.error("Không thể khởi động lại game %s: %s", GAME_PACKAGE_NAME, e)
