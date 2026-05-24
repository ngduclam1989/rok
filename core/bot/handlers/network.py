"""Network-disconnect popup handling.

The "Đã ngắt kết nối mạng / Network unstable" popup can appear at
any time and overlay the current screen. Long-running handlers call
``check_and_handle_network_popup`` after each snapshot so that
subsequent taps don't land on a covered UI.
"""
from __future__ import annotations

import logging
import time

import numpy as np

from core.device import Device

from ..detection import is_network_popup, is_gems_shop
from ..geometry import pct_to_px
from ..state import StepResult

log = logging.getLogger(__name__)


def handle_network_error(
    device: Device, screen: np.ndarray,
) -> StepResult:
    """Main-loop handler for the network-disconnect modal."""
    log.warning(
        "Popup mất kết nối -> chạm XÁC NHẬN + chờ 20s reconnect",
    )
    x, y = pct_to_px(screen, 50.0, 67.0)
    device.tap(x, y)
    return StepResult(
        True, "đã chạm XÁC NHẬN, đang reconnect", sleep_after=20.0,
    )


def check_and_handle_network_popup(
    device: Device, screen: np.ndarray,
) -> bool:
    """Detect + auto-handle critical popups like network error or gems shop/recharge screen.

    Called inside other handlers at points where the popup might
    intrude (after a snapshot, before a critical tap, during a long
    sleep). Returns ``True`` if a popup was found and handled — the
    caller should abort its current flow and return to the main
    loop so the state machine can re-detect.
    """
    # 1. Kiểm tra popup mất kết nối mạng
    if is_network_popup(screen):
        log.warning(
            "Popup ngắt kết nối xuất hiện giữa chừng "
            "-> chạm XÁC NHẬN + chờ 20s",
        )
        x, y = pct_to_px(screen, 50.0, 67.0)
        device.tap(x, y)
        time.sleep(20.0)
        return True

    # 2. Kiểm tra cửa hàng đá quý / nạp tiền xuất hiện bất ngờ
    if is_gems_shop(screen):
        log.warning("Màn hình nạp tiền/đá quý xuất hiện giữa chừng -> nhấn phím BACK để thoát")
        try:
            device.key("BACK")
        except Exception as e:
            log.warning("Không thể gửi phím BACK qua ADB: %s, thử chạm góc trên bên trái", e)
            x, y = pct_to_px(screen, 5.0, 5.0)
            device.tap(x, y)
        time.sleep(2.5)
        return True

    return False
