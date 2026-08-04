"""Tile info popup handler."""
from __future__ import annotations

import logging

import numpy as np

from core.device import Device

from ..geometry import tap_template
from ..state import StepResult
from .network import check_and_handle_network_popup

log = logging.getLogger(__name__)


def handle_tile_info(
    device: Device, screen: np.ndarray,
) -> StepResult:
    """Tile info popup: tap THU THẬP for a resource gather.

    Non-resource popups (barbarian / empty land) have no THU THẬP
    button so the template miss correctly triggers a BACK escape.
    """
    if check_and_handle_network_popup(device, screen):
        return StepResult(
            True, "đã xử lý popup mạng giữa tile_info", sleep_after=1.5,
        )
    pos = tap_template(
        device, screen, "btn_thu_thap.png", 0.78,
        region_pct=(55, 30, 95, 80),
        long_tap=True,
    )
    if pos is not None:
        log.info("Popup ô tile -> chạm THU THẬP @(%d,%d)", *pos)
        return StepResult(True, "đã chạm thu thập", sleep_after=0.8)

    log.warning(
        "Popup tile không có THU THẬP (Man rợ/Đất trống hoặc nhận diện nhầm) "
        "-> chạm vùng trống để đóng popup an toàn",
    )
    try:
        h, w = screen.shape[:2]
        # Chạm vùng trống góc trên-trái (15% w, 25% h) để đóng popup tile mà không kích hoạt phím BACK (gây hiện exit_dialog)
        safe_x = int(w * 0.15)
        safe_y = int(h * 0.25)
        device.tap(safe_x, safe_y)
    except Exception as e:
        log.warning("Lỗi chạm vùng trống thoát tile_info: %s", e)

    return StepResult(
        False, "ô không phải tài nguyên, đã chạm vùng trống để thoát", sleep_after=1.0,
    )

