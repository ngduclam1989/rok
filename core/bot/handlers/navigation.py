"""WORLD <-> CITY navigation handlers."""
from __future__ import annotations

import logging
import time
import cv2

import numpy as np

from core import ocr
from core.device import Device

from ..geometry import pct_to_px, region_pct_to_px, tap_template, tap_template_debug, ocr_text_in, try_template
from ..state import StepResult
from ..capture import save_debug_image
from .network import check_and_handle_network_popup

log = logging.getLogger(__name__)


def handle_city(
    device: Device, screen: np.ndarray, goal: str,
) -> StepResult:
    """City view: tap MAP TOGGLE to switch to the world map.

    No badge OCR here. Slot tracking is driven by ``dispatched_count``
    in the main loop, which triggers the panel-timer-read flow after
    ``MAX_SLOTS`` successful dispatches.
    """
    if check_and_handle_network_popup(device, screen):
        return StepResult(
            True, "đã xử lý popup mạng giữa city", sleep_after=1.5,
        )
    log.info("Trong thành -> chạm chuyển sang bản đồ (template)")
    pos = tap_template(
        device, screen, "btn_map_toggle.png", 0.75,
        region_pct=(0, 80, 15, 100),
    )
    if pos is None:
        log.warning(
            "Không thấy template chuyển bản đồ -> dùng toạ độ (6.0, 91.2)",
        )
        x, y = pct_to_px(screen, 6.0, 91.2)
        device.tap(x, y)
    return StepResult(True, "đã chuyển ra bản đồ", sleep_after=1.5)


def handle_world(
    device: Device, screen: np.ndarray, goal: str,
) -> StepResult:
    """World map: tap the magnifying glass to open the search panel."""
    if check_and_handle_network_popup(device, screen):
        return StepResult(
            True, "đã xử lý popup mạng giữa world", sleep_after=1.5,
        )
    log.info("Bản đồ thế giới -> quét kính lúp")
    region_pct = (0, 70, 10, 85)
    
    # Chỉ tìm kiếm ảnh xem có tồn tại hay không, không chạm tự động
    found = try_template(
        device, screen, "btn_kinh_luc.png", 0.55,
        region_pct=region_pct,
    )
    if not found:
        log.warning("Không tìm thấy kính lúp trong vùng %s -> không làm gì cả", region_pct)
        return StepResult(False, "thiếu kính lúp", sleep_after=1.5)
        
    # Nếu tìm thấy kính lúp, chạm vào trung tâm của vùng quét
    r_x1, r_y1, r_x2, r_y2 = region_pct
    center_x_pct = (r_x1 + r_x2) / 2.0
    center_y_pct = (r_y1 + r_y2) / 2.0
    x, y = pct_to_px(screen, center_x_pct, center_y_pct)
    log.info(
        "Tìm thấy kính lúp -> Chạm vào trung tâm vùng tìm kiếm: (%.1f%%, %.1f%%) tại tọa độ pixel @(%d,%d)",
        center_x_pct, center_y_pct, x, y
    )
    device.tap(x, y)
    return StepResult(True, f"đã mở bảng tìm kiếm (chạm @({x},{y}))", sleep_after=1.5)


def handle_switch_account(device: Device) -> bool:
    """Thực hiện chuỗi thao tác chuyển tài khoản: Avatar -> Cài đặt -> Nhân vật -> Ngôi sao -> Yes."""
    log.info("Đang đợi 10s cho các đạo quân ổn định trước khi chuyển acc...")
    time.sleep(10.0)

    try:
        screen = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình để tìm Avatar")
        return False

    # 1. Quét tìm và chạm nút Avatar
    log.info("Đang scan khu vực góc trên bên trái màn hình tìm btn_avatar.png...")
    pos = tap_template_debug(
        device, screen, "btn_avatar.png", 0.55,
        region_pct=(0, 0, 10, 10),
    )
    if pos is None:
        log.warning("Không tìm thấy template btn_avatar.png ở góc trên bên trái")
        return False

    log.info("Tìm thấy Avatar -> Đã chạm để mở bảng thông tin người chơi. Chờ ổn định 5s...")
    time.sleep(5.0)

    # 2. Quét tìm và chạm nút Cài đặt
    try:
        screen_profile = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình sau khi chạm Avatar")
        return False

    log.info("Tìm nút Cài đặt theo template hình ảnh trong vùng (65, 75, 100, 100)...")
    pos_settings = tap_template_debug(
        device, screen_profile, "btn_cai_dat.png", 0.5,
        region_pct=(65, 75, 100, 100),
    )
    if pos_settings is None:
        log.warning("Không tìm thấy nút Cài đặt theo hình ảnh trong vùng quét!")
        return False

    log.info("Đã tìm thấy và chạm nút Cài đặt tại: %r. Chờ ổn định giao diện Cài đặt trong 5s...", pos_settings)
    time.sleep(5.0)

    # 3. Quét tìm và chạm nút Nhân vật
    try:
        screen_settings = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình trong giao diện Cài đặt")
        return False

    log.info("Tìm nút Nhân vật theo template hình ảnh trong vùng (20, 20, 60, 60)...")
    pos_char = tap_template_debug(
        device, screen_settings, "btn_nhan_vat.png", 0.5,
        region_pct=(20, 20, 60, 60),
    )
    if pos_char is None:
        log.warning("Không tìm thấy nút Nhân vật theo hình ảnh trong vùng quét!")
        return False

    log.info("Đã tìm thấy và chạm nút Nhân vật tại: %r. Chờ 10s...", pos_char)
    time.sleep(10.0)

    # Chụp ảnh màn hình mới sau khi chạm Nhân vật và chờ 10s
    try:
        screen_post_char = device.snapshot()
    except Exception as e:
        log.warning("Realtime: Không chụp được ảnh màn hình sau chạm Nhân vật: %s", e)
        return False

    # 4. Quét tìm và chạm nút Ngôi sao (chạm lệch phải để chọn dòng nhân vật)
    log.info("Tìm nút Ngôi sao theo template hình ảnh trong vùng (20, 20, 80, 80)...")
    try:
        region_px = region_pct_to_px(screen_post_char, (20, 20, 80, 80))
        pos_star = device.find_template_in(
            "btn_ngoi_sao.png", screen_post_char, threshold=0.5, region=region_px
        )
    except FileNotFoundError:
        log.error("Thiếu template: btn_ngoi_sao.png")
        pos_star = None
    except Exception as e:
        log.warning("Lỗi khi quét tìm Ngôi sao: %s", e)
        pos_star = None

    if pos_star is None:
        log.warning("Không tìm thấy nút Ngôi sao theo hình ảnh trong vùng quét!")
        return False

    # Tính toán tọa độ click lệch phải 200px để chạm vào dòng nhân vật
    x_click = pos_star[0] + 200
    y_click = pos_star[1]
    log.info("Đã tìm thấy Ngôi sao tại: %r. Chạm lệch phải tại (%d, %d) để chọn dòng nhân vật. Chờ ổn định 5s...", pos_star, x_click, y_click)

    try:
        save_debug_image(
            screen_post_char,
            device.serial,
            subdir="switch_account",
            prefix="star_found",
            clicks=[(x_click, y_click)],
            rects=[(pos_star[0] - 20, pos_star[1] - 20, pos_star[0] + 20, pos_star[1] + 20)],
            label="Chon Dong Nhan Vat (Lech Phai 200px)",
        )
    except Exception as err:
        log.warning("Không lưu được ảnh debug ngôi sao: %s", err)

    device.tap(x_click, y_click)
    time.sleep(5.0)

    # 5. Quét tìm và chạm nút Yes
    try:
        screen_post_star = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình sau khi chạm Ngôi sao")
        return False

    log.info("Tìm nút Yes theo template hình ảnh trong vùng (50, 50, 100, 100)...")
    pos_yes = tap_template_debug(
        device, screen_post_star, "btn_yes.png", 0.5,
        region_pct=(50, 50, 100, 100),
    )
    if pos_yes is None:
        log.warning("Không tìm thấy nút Yes theo hình ảnh trong vùng quét!")
        return False

    log.info("Đã tìm thấy và chạm nút Yes tại: %r. Hoàn thành chuỗi chuyển tài khoản!", pos_yes)
    time.sleep(3.0)
    return True
