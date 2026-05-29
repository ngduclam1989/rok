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
        return StepResult(True, "đã chạm thu thập", sleep_after=1.5)

    log.warning(
        "Popup tile không có THU THẬP (chắc là Man rỡ/Đất trống) "
        "-> bấm BACK để thoát",
    )
    try:
        device.key("BACK")
    except Exception:
        pass
    return StepResult(
        False, "ô không phải tài nguyên, đã thoát", sleep_after=1.5,
    )
