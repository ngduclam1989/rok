"""Windows input lock and smooth physical mouse movement."""
from __future__ import annotations

import logging
import sys
import threading
import time

from core.mouse import mouse_bez

log = logging.getLogger(__name__)

_LOCKED = False
_LOCK_THREAD: threading.Thread | None = None
_LOCK_COORD: tuple[int, int] | None = None
_IDLE_COORD: tuple[int, int] | None = None

win32api = None
ctypes = None

if sys.platform == "win32":
    try:
        import ctypes
        import win32api
    except ImportError:
        pass


def _lock_loop() -> None:
    """Keep the cursor pinned to the current lock coordinate."""
    global _LOCKED
    while _LOCKED:
        if win32api and ctypes and _LOCK_COORD:
            try:
                win32api.SetCursorPos(_LOCK_COORD)
                from ctypes import wintypes

                x, y = _LOCK_COORD
                rect = wintypes.RECT(x, y, x + 1, y + 1)
                ctypes.windll.user32.ClipCursor(ctypes.byref(rect))
            except Exception:
                pass
        time.sleep(0.01)

    if ctypes:
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass


def lock_input() -> None:
    """Lock user mouse input while the bot is running."""
    global _LOCKED, _LOCK_COORD, _IDLE_COORD, _LOCK_THREAD

    from core.bot import config

    if not getattr(config, "ENABLE_INPUT_LOCK", True):
        log.info("[InputLock] Skipping input lock because enable_input_lock=false.")
        return
    if _LOCKED:
        return

    _LOCKED = True

    if ctypes:
        try:
            result = ctypes.windll.user32.BlockInput(True)
            if result:
                log.info("[InputLock] Locked input via BlockInput.")
            else:
                log.warning(
                    "[InputLock] BlockInput failed. Falling back to cursor pinning.",
                )
        except Exception as exc:
            log.warning("[InputLock] BlockInput error: %s", exc)

    if win32api:
        try:
            _IDLE_COORD = win32api.GetCursorPos()
        except Exception:
            _IDLE_COORD = (0, 0)
    else:
        _IDLE_COORD = (0, 0)
    _LOCK_COORD = _IDLE_COORD

    if sys.platform == "win32":
        _LOCK_THREAD = threading.Thread(
            target=_lock_loop,
            name="input-lock-mouse-thread",
            daemon=True,
        )
        _LOCK_THREAD.start()
        log.info("[InputLock] Cursor pinning started at %s.", _IDLE_COORD)


def unlock_input() -> None:
    """Release user mouse input."""
    global _LOCKED, _LOCK_COORD, _IDLE_COORD

    from core.bot import config

    if not getattr(config, "ENABLE_INPUT_LOCK", True):
        return

    _LOCKED = False

    if ctypes:
        try:
            ctypes.windll.user32.BlockInput(False)
            log.info("[InputLock] Released BlockInput.")
        except Exception as exc:
            log.warning("[InputLock] BlockInput release error: %s", exc)
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass

    _LOCK_COORD = None
    _IDLE_COORD = None
    log.info("[InputLock] Input lock fully released.")


def set_lock_position(x: int, y: int) -> None:
    """Move the cursor and, when locked, update the held coordinate."""
    global _LOCK_COORD
    if _LOCKED:
        _LOCK_COORD = (x, y)
    if win32api:
        try:
            win32api.SetCursorPos((x, y))
        except Exception:
            pass


def move_lock_position_smooth(
    target_x: int,
    target_y: int,
    duration: float = 0.15,
    deviation: int = 8,
) -> None:
    """Move the cursor smoothly along a Bezier path.

    This works even when input locking is disabled, which keeps
    ``control_mode: physical_mouse`` usable with ``enable_input_lock: false``.
    """
    global _LOCK_COORD
    if not win32api:
        return

    if _LOCKED and _LOCK_COORD is not None:
        start_x, start_y = _LOCK_COORD
    else:
        try:
            start_x, start_y = win32api.GetCursorPos()
        except Exception:
            start_x, start_y = target_x, target_y

    if start_x == target_x and start_y == target_y:
        return

    step_time = 0.01
    steps = max(1, int(max(0.01, duration) / step_time))
    speed = max(1, round(steps / 100))
    path = mouse_bez((start_x, start_y), (target_x, target_y), deviation, speed)

    if len(path) > steps:
        stride = max(1, len(path) // steps)
        path = path[::stride][:steps]
    if not path or path[-1] != (target_x, target_y):
        path.append((target_x, target_y))

    for curr_x_float, curr_y_float in path:
        curr_x = int(round(curr_x_float))
        curr_y = int(round(curr_y_float))
        if _LOCKED:
            _LOCK_COORD = (curr_x, curr_y)
        try:
            win32api.SetCursorPos((curr_x, curr_y))
        except Exception:
            pass
        time.sleep(step_time)

    if _LOCKED:
        _LOCK_COORD = (target_x, target_y)
    try:
        win32api.SetCursorPos((target_x, target_y))
    except Exception:
        pass


def reset_lock_position(smooth: bool = True) -> None:
    """Move the cursor back to the idle coordinate captured at lock time."""
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
