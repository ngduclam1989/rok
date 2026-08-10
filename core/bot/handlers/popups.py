"""Small popup / dialog / build-menu handlers."""
from __future__ import annotations

import logging

import numpy as np

from core.device import Device

from ..detection import locate_modal_button
from ..geometry import pct_to_px
from ..state import StepResult

log = logging.getLogger(__name__)


def handle_exit_dialog(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Hộp thoại thoát -> chạm HUỶ")
    pos = locate_modal_button(screen, "cancel")
    if pos is None:
        x, y = pct_to_px(screen, 65.0, 70.0)
    else:
        x, y = pos
    device.tap(x, y)
    return StepResult(True, "đã huỷ thoát", sleep_after=1.5)


def handle_popup(device: Device, screen: np.ndarray) -> StepResult:
    """Close a generic event / shop popup via the top-right X."""
    log.info("Phát hiện popup -> chạm X đóng (96.5%%, 5.5%%)")
    x, y = pct_to_px(screen, 96.5, 5.5)
    device.tap(x, y)
    return StepResult(True, "đã đóng popup", sleep_after=1.5)


def handle_build_menu(
    device: Device, screen: np.ndarray,
) -> StepResult:
    log.info("Menu xây dựng -> chạm vùng thành phố phía trên")
    x, y = pct_to_px(screen, 50.0, 12.0)
    device.tap(x, y)
    return StepResult(True, "đóng menu xây dựng", sleep_after=1.5)


def handle_gems_shop(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Phát hiện màn hình đá quý/nạp tiền -> nhấn phím BACK để thoát về world")
    try:
        device.key("BACK")
    except Exception as e:
        log.warning("Không thể gửi phím BACK qua ADB: %s, thử chạm góc trên bên trái", e)
        x, y = pct_to_px(screen, 5.0, 5.0)
        device.tap(x, y)
    return StepResult(True, "đã xử lý thoát màn hình nạp đá quý", sleep_after=1.5)


def handle_alliance_panel(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Phát hiện màn hình Bảng Liên Minh -> chạm X góc trên-phải (96.5%%, 5.5%%) để thoát về world")
    x, y = pct_to_px(screen, 96.5, 5.5)
    device.tap(x, y)
    return StepResult(True, "đã đóng bảng Liên Minh", sleep_after=1.5)



def handle_pre_kvk(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Phát hiện màn hình sự kiện Pre-KVK (Đêm Giao Thừa Của Cuộc Thập Tự Chinh) -> chạm X góc trên-phải để thoát về world")
    x, y = pct_to_px(screen, 90.6, 12.0)
    device.tap(x, y)
    return StepResult(True, "đã đóng màn hình Pre-KVK", sleep_after=1.5)


def handle_troops_panel(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Phát hiện màn hình Bảng Đạo Quân -> chạm X góc trên-phải để thoát về world")
    x, y = pct_to_px(screen, 90.6, 5.5)
    device.tap(x, y)
    return StepResult(True, "đã đóng bảng Đạo Quân", sleep_after=1.5)



