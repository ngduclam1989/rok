"""March-plan handler — army composition + dispatch."""
from __future__ import annotations

import logging

import numpy as np

from core.device import Device

from ..constants import CAPTURES_DIR
from ..geometry import ocr_text_in, pct_to_px, tap_template
from ..signals import pause
from ..state import StepResult
from .network import check_and_handle_network_popup

log = logging.getLogger(__name__)


def handle_march_plan(
    device: Device, screen: np.ndarray,
) -> StepResult:
    """Two sub-states:

    1. INITIAL: only "Quân mới" is shown — tap it to open composition.
    2. COMPOSITION: troops selected, HÀNH QUÂN visible at bottom-right
       — tap to dispatch.

    Discriminated by template + OCR: HÀNH QUÂN takes priority; if not
    present, fall through to Quân mới.
    """
    if check_and_handle_network_popup(device, screen):
        return StepResult(
            True, "đã xử lý popup mạng giữa march_plan", sleep_after=1.5,
        )

    pos = tap_template(
        device, screen, "btn_hanh_quan.png", 0.78,
        region_pct=(55, 75, 100, 100),
        long_tap=True,
    )
    if pos is not None:
        log.info("Chạm HÀNH QUÂN cuối cùng @(%d,%d)", *pos)
        return StepResult(
            True, "đã gửi quân", sleep_after=0.8, goal_reached=True,
        )

    log.info("Bảng quân (bước đầu) -> chạm Quân mới")
    pos = tap_template(
        device, screen, "btn_quan_moi.png", 0.78,
        region_pct=(60, 0, 100, 30),
        long_tap=True,
    )
    if pos is not None:
        return StepResult(True, "đã mở bảng chọn quân", sleep_after=0.8)

    # Slow fallback: only OCR the disabled/no-troops state after the expected
    # action buttons are not visible. Normal farm runs avoid this OCR pass.
    if ocr_text_in(screen, (55, 75, 100, 100),
                   ("Khong co Doi", "khong co doi", "khong co d",
                    "khong co quan", "0/76", "0/100", "0 / 76",
                    "0 / 100"),
                   threshold=0.4):
        log.info("Bảng quân -> tướng chưa có quân, đóng bảng")
        x, y = pct_to_px(screen, 96.0, 8.0)
        device.tap(x, y)
        return StepResult(
            True, "tướng trống, đã đóng bảng", sleep_after=1.0,
        )

    # Neither button found — likely the general has no troops or we
    # caught an animation frame. Force-close the panel via top-right X.
    log.warning(
        "Không thấy HÀNH QUÂN lẫn Quân mới -> ép chạm X góc trên-phải",
    )
    for cx_pct, cy_pct in ((96.0, 8.0), (97.0, 5.0)):
        x, y = pct_to_px(screen, cx_pct, cy_pct)
        device.tap(x, y)
        pause(0.4)
    return StepResult(False, "ép đóng panel", sleep_after=1.5)
