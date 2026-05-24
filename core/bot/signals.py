"""Graceful-stop signal handling + sleep utilities that respect it.

`install_signal_handler()` wires SIGINT/SIGTERM to a flag-based
shutdown; the second signal within 3s force-exits (when PaddleOCR
or ADB is blocking on a long op).

Per-device stop flag: when running in a fleet, parent can write
``STOP_<serial>.flag`` to stop ONE device while others keep running.
``STOP.flag`` (no suffix) stops every device.
"""
from __future__ import annotations

import logging
import os
import random
import signal
import time
from datetime import datetime, timedelta

from .constants import ROOT, STOP_FLAG

log = logging.getLogger(__name__)

_stop_requested = False
_last_signal_time = 0.0
_per_device_stop_flag: "os.PathLike[str] | None" = None


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
        chunk = min(1.0, target_sec - elapsed)
        time.sleep(chunk)
        elapsed += chunk


def sleep_with_stop_check(min_sec: float, max_sec: float) -> None:
    sleep_with_stop_check_exact(random.uniform(min_sec, max_sec))


def pause(min_s: float, max_s: float | None = None) -> None:
    """Short sleep with stop-flag polling every 0.5s."""
    target = min_s if max_s is None else random.uniform(min_s, max_s)
    elapsed = 0.0
    while elapsed < target:
        if should_stop():
            return
        chunk = min(0.5, target - elapsed)
        time.sleep(chunk)
        elapsed += chunk
