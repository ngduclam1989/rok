"""Tiện ích chụp và vẽ debug chung dùng cho toàn bộ bot.

Hàm duy nhất public: ``save_debug_image``.

Cách dùng:
    from .capture import save_debug_image

    save_debug_image(
        screen,
        device.serial,
        subdir="vip_claims",
        prefix="vip",
        clicks=[(x, y)],             # điểm click -> chấm đỏ
        rects=[(x1, y1, x2, y2)],    # vùng highlight -> hình chữ nhật xanh lá
        label="Mo Giao Dien VIP",     # text hiển thị góc trên-trái
    )
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Sequence

import numpy as np

from .constants import CAPTURES_DIR

log = logging.getLogger(__name__)


def save_debug_image(
    screen: np.ndarray,
    serial: str | object,
    *,
    subdir: str = "",
    prefix: str = "debug",
    clicks: Sequence[tuple[int, int]] | None = None,
    rects: Sequence[tuple[int, int, int, int]] | None = None,
    label: str = "",
) -> Path | None:
    """Lưu ảnh debug với vòng tròn đỏ tại điểm click và hình chữ nhật xanh cho vùng highlight.

    Args:
        screen:  ảnh numpy BGR từ device.snapshot().
        serial:  serial thiết bị (dùng để đặt tên file).
        subdir:  thư mục con trong captures/ (ví dụ 'vip_claims', 'logo_18_clicks').
        prefix:  tiền tố tên file (ví dụ 'vip', 'unknown', 'first_world').
        clicks:  danh sách tọa độ (x, y) điểm click -> vẽ chấm đỏ + circle đỏ.
        rects:   danh sách vùng (x1, y1, x2, y2) -> vẽ hình chữ nhật xanh lá.
        label:   text chú thích hiện góc trên-trái ảnh.

    Returns:
        Path tới file ảnh đã lưu, hoặc None nếu lỗi.
    """
    try:
        import cv2
    except ImportError:
        log.warning("save_debug_image: cv2 không khả dụng, bỏ qua.")
        return None

    try:
        out_dir = CAPTURES_DIR / subdir if subdir else CAPTURES_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        drawn = screen.copy()

        # Vẽ hình chữ nhật vùng highlight (xanh lá)
        for rect in (rects or []):
            x1, y1, x2, y2 = rect
            cv2.rectangle(drawn, (x1, y1), (x2, y2), (0, 255, 0), 2, lineType=cv2.LINE_AA)

        # Vẽ điểm click (đỏ)
        for i, (cx, cy) in enumerate((clicks or [])):
            cv2.circle(drawn, (int(cx), int(cy)), 18, (0, 0, 255), 3, lineType=cv2.LINE_AA)
            cv2.circle(drawn, (int(cx), int(cy)), 5, (0, 0, 255), -1, lineType=cv2.LINE_AA)
            if label:
                text = f"{label} @({cx},{cy})" if i == 0 else f"click{i+1} @({cx},{cy})"
            else:
                text = f"@({cx},{cy})"
            cv2.putText(
                drawn, text,
                (30, 50 + i * 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, lineType=cv2.LINE_AA,
            )

        # Nếu chỉ có label mà không có click
        if label and not clicks:
            cv2.putText(
                drawn, label,
                (30, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, lineType=cv2.LINE_AA,
            )

        # Đặt tên file
        safe_serial = str(serial).replace(":", "_").replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{prefix}_{safe_serial}_{timestamp}.png"
        out_path = out_dir / filename

        cv2.imwrite(str(out_path), drawn)
        log.info("[capture] Đã lưu ảnh debug: %s", out_path.name)
        return out_path

    except Exception as e:
        log.warning("save_debug_image lỗi: %s", e)
        return None
