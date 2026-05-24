"""Unknown-state recovery sequence."""
from __future__ import annotations

import logging
import time

import numpy as np

from core.device import Device

from ..constants import CAPTURES_DIR
from ..geometry import pct_to_px
from ..state import StepResult

log = logging.getLogger(__name__)


def handle_unknown(
    device: Device, screen: np.ndarray, stuck_count: int,
) -> StepResult:
    """Escalating escape attempts when state detection fails.

    Only the first iteration in a streak saves a screenshot — keeps
    captures/ from filling with near-duplicate frames.
    """
    log.warning("Trạng thái UNKNOWN, đã kẹt %d lần", stuck_count)
    if stuck_count == 1:
        log.info("Hồi phục 1: chạm X góc trên-phải (97, 5)")
        x, y = pct_to_px(screen, 97.0, 5.0)
        device.tap(x, y)
        return StepResult(False, "chạm góc trên-phải", sleep_after=2.0)
    if stuck_count == 2:
        log.info("Hồi phục 2: bấm BACK")
        device.key("BACK")
        return StepResult(False, "back", sleep_after=2.0)
    if stuck_count == 3:
        log.info("Hồi phục 3: chạm giữa-trên (50, 12)")
        x, y = pct_to_px(screen, 50.0, 12.0)
        device.tap(x, y)
        return StepResult(False, "chạm giữa-trên", sleep_after=2.0)
    if stuck_count == 4:
        log.warning("Hồi phục 4: BACK x2 + đợi lâu")
        device.key("BACK")
        time.sleep(1.5)
        device.key("BACK")
        return StepResult(False, "back x2", sleep_after=4.0)

    log.warning("Hồi phục 5: Vẫn kẹt ở UNKNOWN -> Tự động khởi động lại game...")
    device.start_game()
    return StepResult(False, "khởi động lại game com.rok.gp.vn", sleep_after=15.0)
