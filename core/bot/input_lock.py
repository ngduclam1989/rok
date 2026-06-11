"""Khoá / mở khoá chuột PC khi bot đang chạy.

Sử dụng Windows API ``BlockInput`` kết hợp với giới hạn toạ độ ``ClipCursor``
và một luồng phụ thiết lập vị trí để giữ chuột cố định, tránh bị người dùng
di chuyển làm lệch click.

Chỉ hoạt động trên Windows — trên các hệ điều hành khác sẽ là no-op.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

log = logging.getLogger(__name__)

_LOCKED = False
_LOCK_THREAD: threading.Thread | None = None
_LOCK_COORD: tuple[int, int] | None = None
_IDLE_COORD: tuple[int, int] | None = None

# Thư viện Windows
win32api = None
win32con = None
ctypes = None

if sys.platform == "win32":
    try:
        import win32api
        import win32con
        import ctypes
    except ImportError:
        pass


def _lock_loop() -> None:
    """Luồng phụ giữ chuột tại toạ độ chỉ định và giới hạn ClipCursor."""
    global _LOCKED
    while _LOCKED:
        if win32api and ctypes and _LOCK_COORD:
            try:
                # 1. Liên tục ép chuột về toạ độ mong muốn
                win32api.SetCursorPos(_LOCK_COORD)
                
                # 2. Giới hạn vùng di chuyển chuột (ClipCursor) tại toạ độ 1x1 này
                from ctypes import wintypes
                x, y = _LOCK_COORD
                rect = wintypes.RECT(x, y, x + 1, y + 1)
                ctypes.windll.user32.ClipCursor(ctypes.byref(rect))
            except Exception:
                pass
        time.sleep(0.01)  # 10ms
        
    # Giải phóng ClipCursor khi ngừng lock
    if ctypes:
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass


def lock_input() -> None:
    """Khoá toàn bộ chuột người dùng.

    Sử dụng BlockInput cho phần cứng, và luồng phụ + ClipCursor để giữ chuột.
    """
    global _LOCKED, _LOCK_COORD, _IDLE_COORD, _LOCK_THREAD
    
    from core.bot import config
    if not getattr(config, "ENABLE_INPUT_LOCK", True):
        log.info("[InputLock] Bỏ qua khoá chuột (đã tắt bằng enable_input_lock trong cấu hình).")
        return
        
    if _LOCKED:
        return
    
    _LOCKED = True
    
    # 1. Khoá qua Windows BlockInput (yêu cầu quyền Admin)
    if ctypes:
        try:
            result = ctypes.windll.user32.BlockInput(True)
            if result:
                log.info("[InputLock] Đã khoá chuột qua BlockInput.")
            else:
                log.warning("[InputLock] BlockInput thất bại (cần quyền Admin hoặc Remote Desktop). Sẽ dùng luồng phụ để khoá.")
        except Exception as e:
            log.warning("[InputLock] Lỗi BlockInput: %s", e)
            
    # 2. Lưu toạ độ hiện tại làm toạ độ nghỉ (idle)
    if win32api:
        try:
            _IDLE_COORD = win32api.GetCursorPos()
        except Exception:
            _IDLE_COORD = (0, 0)
    else:
        _IDLE_COORD = (0, 0)
        
    _LOCK_COORD = _IDLE_COORD
    
    # 3. Khởi chạy luồng phụ giữ chuột
    if sys.platform == "win32":
        _LOCK_THREAD = threading.Thread(target=_lock_loop, name="input-lock-mouse-thread", daemon=True)
        _LOCK_THREAD.start()
        log.info("[InputLock] Đã khởi chạy luồng phụ giữ chuột tại %s.", _IDLE_COORD)


def unlock_input() -> None:
    """Mở khoá chuột người dùng."""
    global _LOCKED, _LOCK_COORD, _IDLE_COORD
    
    from core.bot import config
    if not getattr(config, "ENABLE_INPUT_LOCK", True):
        return
        
    _LOCKED = False
    
    # BlockInput
    if ctypes:
        try:
            ctypes.windll.user32.BlockInput(False)
            log.info("[InputLock] Đã mở khoá chuột qua BlockInput.")
        except Exception as e:
            log.warning("[InputLock] Lỗi giải phóng BlockInput: %s", e)
            
    # Giải phóng ClipCursor
    if ctypes:
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass
            
    _LOCK_COORD = None
    _IDLE_COORD = None
    log.info("[InputLock] Đã giải phóng hoàn toàn khoá chuột.")


def set_lock_position(x: int, y: int) -> None:
    """Thay đổi toạ độ giữ chuột (dùng trước khi click/swipe)."""
    global _LOCK_COORD
    if not _LOCKED:
        return
    _LOCK_COORD = (x, y)
    if win32api:
        try:
            win32api.SetCursorPos((x, y))
        except Exception:
            pass


def move_lock_position_smooth(target_x: int, target_y: int, duration: float = 0.15) -> None:
    """Di chuyển toạ độ giữ chuột mượt mà từ vị trí hiện tại đến đích để mô phỏng người dùng di chuột."""
    global _LOCK_COORD
    if not _LOCKED or _LOCK_COORD is None:
        return
        
    start_x, start_y = _LOCK_COORD
    if start_x == target_x and start_y == target_y:
        return
        
    step_time = 0.01  # 10ms mỗi bước
    steps = max(1, int(duration / step_time))
    
    for i in range(1, steps + 1):
        t = i / steps
        # Easing function: quadratic ease-out để di chuyển tự nhiên hơn
        t_eased = 1.0 - (1.0 - t) * (1.0 - t)
        curr_x = int(start_x + (target_x - start_x) * t_eased)
        curr_y = int(start_y + (target_y - start_y) * t_eased)
        
        _LOCK_COORD = (curr_x, curr_y)
        if win32api:
            try:
                win32api.SetCursorPos((curr_x, curr_y))
            except Exception:
                pass
        time.sleep(step_time)
        
    # Đảm bảo chính xác ở tọa độ đích cuối cùng
    _LOCK_COORD = (target_x, target_y)
    if win32api:
        try:
            win32api.SetCursorPos((target_x, target_y))
        except Exception:
            pass


def reset_lock_position(smooth: bool = True) -> None:
    """Đưa toạ độ giữ chuột về lại vị trí nghỉ ban đầu."""
    global _LOCK_COORD
    if not _LOCKED or _IDLE_COORD is None:
        return
    if smooth:
        move_lock_position_smooth(_IDLE_COORD[0], _IDLE_COORD[1], duration=0.15)
    else:
        _LOCK_COORD = _IDLE_COORD
        if win32api:
            try:
                win32api.SetCursorPos(_IDLE_COORD)
            except Exception:
                pass
