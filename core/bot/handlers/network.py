"""Network-disconnect popup handling.

The "Đã ngắt kết nối mạng / Network unstable" popup can appear at
any time and overlay the current screen. Long-running handlers call
``check_and_handle_network_popup`` after each snapshot so that
subsequent taps don't land on a covered UI.
"""
from __future__ import annotations

import logging

import numpy as np

from core.device import Device

from ..detection import is_gems_shop, classify_modal_popup, locate_modal_button
from ..geometry import pct_to_px
from ..signals import pause
from ..state import S, StepResult

log = logging.getLogger(__name__)


def handle_network_error(
    device: Device, screen: np.ndarray,
) -> StepResult:
    """Main-loop handler for the network-disconnect modal."""
    modal_state = classify_modal_popup(screen, debug=True)
    if modal_state == S.EXIT_DIALOG:
        log.warning("Handler network nhung thay popup thoat game -> cham HUY")
        pos = locate_modal_button(screen, "cancel")
        if pos is None:
            x, y = pct_to_px(screen, 65.0, 70.0)
        else:
            x, y = pos
        device.tap(x, y)
        return StepResult(True, "da huy popup thoat game", sleep_after=1.5)

    log.warning(
        "Popup mất kết nối -> chạm XÁC NHẬN + chờ 20s reconnect",
    )
    pos = locate_modal_button(screen, "confirm")
    if pos is None:
        x, y = pct_to_px(screen, 50.0, 67.0)
    else:
        x, y = pos
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
    modal_state = classify_modal_popup(screen, debug=True)
    if modal_state == S.EXIT_DIALOG:
        log.warning("Popup thoat game xuat hien giua chung -> cham HUY")
        pos = locate_modal_button(screen, "cancel")
        if pos is None:
            x, y = pct_to_px(screen, 65.0, 70.0)
        else:
            x, y = pos
        device.tap(x, y)
        pause(1.5)
        return True

    if modal_state == S.NETWORK_ERROR:
        log.warning(
            "Popup ngắt kết nối xuất hiện giữa chừng "
            "-> chạm XÁC NHẬN + chờ 20s",
        )
        pos = locate_modal_button(screen, "confirm")
        if pos is None:
            x, y = pct_to_px(screen, 50.0, 67.0)
        else:
            x, y = pos
        device.tap(x, y)
        pause(20.0)
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
        pause(2.5)
        return True

    return False
