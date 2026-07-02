"""Unlock the RoK in-game lock screen.

When locked the entire viewport goes black. A tap wakes the screen
and the padlock icon renders briefly with four arrows around it, then
it auto-hides after ~0.5-1s of inactivity.

=> Every direction in the unlock sequence does **tap + tiny pause +
fast swipe** with NO snapshot/check in between — a snapshot costs
1-2s, by which time the padlock has hidden and a swipe on the blank
viewport is a no-op.
"""
from __future__ import annotations

import logging

import numpy as np

from core.device import Device

from ..detection import is_lock_screen
from ..signals import pause
from ..state import StepResult

log = logging.getLogger(__name__)


def handle_lock_screen(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Màn hình khoá game -> tap đánh thức + kéo nhanh")
    h, w = screen.shape[:2]
    # Padlock sits near the centre, slightly below the middle.
    px = w // 2
    py = int(h * 0.53)
    log.info("Tâm ổ khoá @(%d,%d)", px, py)

    # DO NOT swipe far DOWN — the system brightness slider sits below
    # the padlock; swiping into it will crank brightness up. Use three
    # safe cardinals (up/left/right) plus two short downward diagonals.
    dx = int(w * 0.28)
    dy_up = int(h * 0.32)
    dy_down = int(h * 0.10)
    drags = [
        ("lên", px, py - dy_up),
        ("phải", px + dx, py),
        ("trái", px - dx, py),
        ("phải-dưới (chéo ngắn)", px + dx, py + dy_down),
        ("trái-dưới (chéo ngắn)", px - dx, py + dy_down),
    ]

    for direction, tx, ty in drags:
        log.info(
            "Tap @(%d,%d) -> kéo %s NGAY (350ms) tới (%d,%d)",
            px, py, direction, tx, ty,
        )
        device.tap(px, py)
        pause(0.25)                    # let the padlock render
        device.swipe(px, py, tx, ty, 350)
        pause(1.5)                     # let the game process the gesture

        try:
            cur = device.snapshot()
        except Exception:
            cur = screen
        if not is_lock_screen(cur):
            log.info("Đã mở khoá (hướng %s)", direction)
            return StepResult(True, "đã mở khoá", sleep_after=2.0)

    log.warning("Kéo 5 hướng xong nhưng vẫn ở màn hình khoá")
    return StepResult(False, "vẫn còn khoá", sleep_after=2.0)
