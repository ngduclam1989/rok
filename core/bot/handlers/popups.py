"""Small popup / dialog / build-menu handlers."""
from __future__ import annotations

import logging

import numpy as np

from core.device import Device

from ..detection import locate_modal_button
from ..geometry import pct_to_px
from ..state import StepResult
from ..constants import ALLIANCE_PANEL_CLOSE_X, PRE_KVK_CLOSE_X



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
    """Đóng panel Liên Minh hoặc sub-panel (Quà Tặng, Công Nghệ, Lãnh Thổ).

    Sub-panel có nút X riêng ở (87%, 6%), khác với X chính (80.4%, 6.25%).
    Ưu tiên đóng sub-panel trước, vòng lặp kế tiếp sẽ thấy panel chính và
    đóng nốt.
    """
    from core import ocr
    from ..geometry import ocr_text_in

    # Kiểm tra xem đang ở sub-panel (Quà Tặng / Công Nghệ / Lãnh Thổ)
    is_sub_panel = ocr_text_in(
        screen, (20.0, 0.0, 80.0, 15.0),
        (
            "QUA TANG", "Qua Tang", "QUA TẶNG",
            "KY NANG LIEN MINH", "Ky Nang Lien Minh",
            "LANH THO LIEN MINH", "Lanh Tho Lien Minh",
            "CONG NGHE", "Cong Nghe",
        ),
        threshold=0.4,
    )
    if not is_sub_panel:
        # Fallback: OCR toàn màn tìm keyword đặc trưng sub-panel Quà
        is_sub_panel = ocr_text_in(
            screen, (0.0, 0.0, 100.0, 50.0),
            ("nhan tat ca", "qua da nhan", "qua thuong", "qua hiem"),
            threshold=0.35,
        )

    if is_sub_panel:
        # Sub-panel: nút X ở góc trên-phải (87%, 6%) — vị trí _CLOSE_QUA_X
        log.info(
            "Phát hiện sub-panel Liên Minh (Quà/CN/LT) -> chạm X đóng sub-panel (87.0%%, 6.0%%)"
        )
        x, y = pct_to_px(screen, 87.0, 6.0)
        device.tap(x, y)
        return StepResult(True, "đã đóng sub-panel Liên Minh", sleep_after=1.5)

    # Panel chính: nút X đóng ở vị trí ALLIANCE_PANEL_CLOSE_X
    log.info(
        "Phát hiện màn hình Bảng Liên Minh -> chạm X đóng panel (%.1f%%, %.1f%%) để thoát về world",
        ALLIANCE_PANEL_CLOSE_X[0], ALLIANCE_PANEL_CLOSE_X[1],
    )
    x, y = pct_to_px(screen, ALLIANCE_PANEL_CLOSE_X[0], ALLIANCE_PANEL_CLOSE_X[1])
    device.tap(x, y)
    return StepResult(True, "đã đóng bảng Liên Minh", sleep_after=1.5)



def handle_pre_kvk(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Phát hiện màn hình sự kiện Pre-KVK (Đêm Giao Thừa Của Cuộc Thập Tự Chinh) -> chạm X đóng panel (%.2f%%, %.2f%%) để thoát về world", PRE_KVK_CLOSE_X[0], PRE_KVK_CLOSE_X[1])
    x, y = pct_to_px(screen, PRE_KVK_CLOSE_X[0], PRE_KVK_CLOSE_X[1])
    device.tap(x, y)
    return StepResult(True, "đã đóng màn hình Pre-KVK", sleep_after=1.5)





def handle_troops_panel(device: Device, screen: np.ndarray) -> StepResult:
    log.info("Phát hiện màn hình Bảng Đạo Quân -> chạm X góc trên-phải để thoát về world")
    x, y = pct_to_px(screen, 90.6, 5.5)
    device.tap(x, y)
    return StepResult(True, "đã đóng bảng Đạo Quân", sleep_after=1.5)



