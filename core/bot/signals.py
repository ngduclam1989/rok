"""Graceful-stop signal handling + sleep utilities that respect it.

`install_signal_handler()` wires SIGINT/SIGTERM to a flag-based
shutdown; the second signal within 3s force-exits (when PaddleOCR
or ADB is blocking on a long op).

Per-device stop flag: when running in a fleet, parent can write
``STOP_<serial>.flag`` to stop ONE device while others keep running.
``STOP.flag`` (no suffix) stops every device.

Pause/resume hotkey: Ctrl+Space toggles the bot between running and
paused. While paused the main loop blocks in ``wait_if_paused()`` and
BlockInput is temporarily released so the user can control the mouse.
"""
from __future__ import annotations

import logging
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timedelta

from .constants import ROOT, STOP_FLAG

log = logging.getLogger(__name__)

_stop_requested = False
_last_signal_time = 0.0
_per_device_stop_flag: "os.PathLike[str] | None" = None

# ---------------------------------------------------------------------------
# Pause / resume state (Ctrl+Space hotkey)
# ---------------------------------------------------------------------------
_paused = False
_pause_event = threading.Event()   # set = bot is RUNNING, clear = bot is PAUSED
_pause_event.set()                 # start in running state
_pause_hotkey_thread: threading.Thread | None = None
_pause_hotkey_id = 1               # arbitrary Windows hotkey id


def is_paused() -> bool:
    """Return True khi bot đang tạm dừng."""
    return _paused


def wait_if_paused() -> None:
    """Block vô hạn khi bot đang paused; return ngay khi bot resume.

    Gọi ở đầu mỗi vòng lặp chính trong run(). Khi bị block, cũng giải
    phóng khóa chuột để người dùng có thể dùng chuột tự do.
    """
    if _pause_event.is_set():
        return   # fast path: không cần lock

    # Giải phóng chuột tạm thời trong khi paused
    try:
        from core.bot.input_lock import unlock_input
        unlock_input()
    except Exception:
        pass

    log.warning("[PAUSE] Bot đang TẠM DỪNG. Nhấn Ctrl+Space để tiếp tục...")
    _pause_event.wait()   # block cho đến khi resume

    # Khoá lại chuột khi resume
    try:
        from core.bot.input_lock import lock_input
        lock_input()
    except Exception:
        pass

    log.warning("[PAUSE] Bot đã TIẾP TỤC chạy.")


def _toggle_pause() -> None:
    """Đổi trạng thái pause/resume, gọi từ hotkey thread."""
    global _paused
    _paused = not _paused
    if _paused:
        _pause_event.clear()
        # Banner rõ ràng trong console
        banner = (
            "\n" + "=" * 60 + "\n"
            "  ⏸  BOT ĐÃ TẠM DỪNG  (Ctrl+Space để tiếp tục)  ⏸\n"
            + "=" * 60
        )
        print(banner, flush=True)
        log.warning("[PAUSE] Người dùng nhấn Ctrl+Space → TẠM DỪNG.")
        # Mở khoá chuột ngay lập tức khi tạm dừng để dùng bình thường
        try:
            from core.bot.input_lock import unlock_input
            unlock_input()
        except Exception:
            pass
    else:
        # Khoá lại chuột ngay lập tức khi resume trước khi luồng chính tiếp tục
        try:
            from core.bot.input_lock import lock_input
            lock_input()
        except Exception:
            pass
        _pause_event.set()
        banner = (
            "\n" + "=" * 60 + "\n"
            "  ▶  BOT ĐÃ TIẾP TỤC  (Ctrl+Space để tạm dừng)  ▶\n"
            + "=" * 60
        )
        print(banner, flush=True)
        log.warning("[PAUSE] Người dùng nhấn Ctrl+Space → TIẾP TỤC.")


def _hotkey_listener_thread() -> None:
    """Thread ngầm dùng Windows RegisterHotKey + GetMessage để nghe Ctrl+Space.

    Không dùng thư viện ngoài — chỉ cần ctypes (có sẵn trên mọi Python/Windows).
    """
    try:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        MOD_CONTROL = 0x0002
        VK_SPACE    = 0x20
        WM_HOTKEY   = 0x0312
        WM_QUIT     = 0x0012

        ok = user32.RegisterHotKey(None, _pause_hotkey_id, MOD_CONTROL, VK_SPACE)
        if not ok:
            log.warning(
                "[PAUSE] RegisterHotKey Ctrl+Space thất bại. "
                "Có thể hotkey này đã được đăng ký bởi app khác."
            )
            return

        log.info("[PAUSE] Đã đăng ký phím tắt Ctrl+Space (pause/resume bot).")
        print(
            "\n[BOT] Phím tắt: Ctrl+Space = TẠM DỪNG / TIẾP TỤC bot\n",
            flush=True,
        )

        msg = ctypes.wintypes.MSG()
        while True:
            # GetMessageW block cho đến khi có message
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:   # WM_QUIT hoặc lỗi
                break
            if msg.message == WM_HOTKEY and msg.wParam == _pause_hotkey_id:
                _toggle_pause()
            elif msg.message == WM_QUIT:
                break
    except Exception as e:
        log.warning("[PAUSE] Hotkey listener lỗi: %s", e)
    finally:
        try:
            ctypes.windll.user32.UnregisterHotKey(None, _pause_hotkey_id)
            log.info("[PAUSE] Đã huỷ đăng ký hotkey Ctrl+Space.")
        except Exception:
            pass


def install_pause_hotkey() -> None:
    """Khởi động thread lắng nghe Ctrl+Space (gọi 1 lần khi bot bắt đầu).

    Chỉ hoạt động trên Windows; trên OS khác là no-op.
    """
    global _pause_hotkey_thread
    if sys.platform != "win32":
        return
    if _pause_hotkey_thread is not None and _pause_hotkey_thread.is_alive():
        return   # đã chạy rồi
    _pause_hotkey_thread = threading.Thread(
        target=_hotkey_listener_thread,
        name="pause-hotkey-listener",
        daemon=True,
    )
    _pause_hotkey_thread.start()


def register_serial(serial: str) -> None:
    """Tell ``should_stop()`` which per-device flag to watch.

    Called by ``run()`` at startup. ``STOP_<serial>.flag`` next to
    the project root will stop this device specifically.
    """
    global _per_device_stop_flag
    _per_device_stop_flag = ROOT / f"STOP_{serial}.flag"


def install_signal_handler() -> None:
    def _on_signal(signum: int, _frame: object) -> None:
        global _stop_requested, _last_signal_time
        now = time.time()
        if _stop_requested and (now - _last_signal_time) < 3.0:
            log.warning("Nhận tín hiệu lần 2 -> thoát ngay (os._exit 130)")
            os._exit(130)
        _last_signal_time = now
        log.warning(
            "Nhận tín hiệu %d -> đang dừng nhẹ nhàng "
            "(Ctrl+C lần 2 trong 3s để thoát ngay)", signum,
        )
        _stop_requested = True

    try:
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
    except Exception:
        pass


def should_stop() -> bool:
    if _stop_requested:
        return True
    if STOP_FLAG.exists():
        log.warning("Phát hiện STOP.flag -> dừng bot")
        return True
    if _per_device_stop_flag is not None and os.path.exists(
        _per_device_stop_flag,
    ):
        log.warning(
            "Phát hiện %s -> dừng máy này", _per_device_stop_flag,
        )
        return True
    return False


def sleep_with_stop_check_exact(target_sec: float) -> None:
    wake_at = datetime.now() + timedelta(seconds=target_sec)
    log.info(
        "Ngủ %.0fs (~%.1f phút, kiểm tra dừng mỗi 1s) "
        "-> dậy lúc %s",
        target_sec, target_sec / 60.0,
        wake_at.strftime("%H:%M:%S %d/%m"),
    )
    elapsed = 0.0
    while elapsed < target_sec:
        if should_stop():
            log.info("Nhận lệnh dừng trong lúc ngủ")
            return
        # Khi paused: block ở đây (không cộng thêm elapsed → đồng hồ đóng băng)
        if not _pause_event.is_set():
            wait_if_paused()
            continue
        chunk = min(1.0, target_sec - elapsed)
        time.sleep(chunk)
        elapsed += chunk


def sleep_with_stop_check(min_sec: float, max_sec: float) -> None:
    sleep_with_stop_check_exact(random.uniform(min_sec, max_sec))


def pause(min_s: float, max_s: float | None = None) -> None:
    """Short sleep with stop-flag + pause-flag polling every 0.5s."""
    if max_s is None:
        if min_s >= 10.0:
            jitter = 2.0
        elif min_s >= 3.0:
            jitter = 1.0
        elif min_s >= 1.0:
            jitter = 0.3
        else:
            jitter = 0.1
        target = random.uniform(max(0.0, min_s - jitter), min_s + jitter)
    else:
        target = random.uniform(min_s, max_s)
    elapsed = 0.0
    while elapsed < target:
        if should_stop():
            return
        # Khi paused: block, không cộng elapsed → đồng hồ đóng băng
        if not _pause_event.is_set():
            wait_if_paused()
            continue
        chunk = min(0.5, target - elapsed)
        time.sleep(chunk)
        elapsed += chunk
