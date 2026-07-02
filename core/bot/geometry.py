"""Coordinate + OCR-region helpers and a template-tap convenience wrapper.

These have no game knowledge — they convert percent-of-screen coords
to pixel coords, OCR a region for keywords, and find/tap templates.
"""
from __future__ import annotations

import logging
import cv2

import numpy as np

from core import ocr
from core.device import Device
from .constants import CAPTURES_DIR
from .signals import pause

log = logging.getLogger(__name__)


def pct_to_px(
    screen: np.ndarray, x_pct: float, y_pct: float,
) -> tuple[int, int]:
    h, w = screen.shape[:2]
    return int(w * x_pct / 100.0), int(h * y_pct / 100.0)


def region_pct_to_px(
    screen: np.ndarray, region: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    h, w = screen.shape[:2]
    x1 = int(w * region[0] / 100.0)
    y1 = int(h * region[1] / 100.0)
    x2 = int(w * region[2] / 100.0)
    y2 = int(h * region[3] / 100.0)
    return x1, y1, x2, y2


def ocr_text_in(
    screen: np.ndarray,
    region_pct: tuple[float, float, float, float],
    needles: tuple[str, ...],
    threshold: float = 0.55,
) -> bool:
    """OCR a region and return True if any needle substring is found.

    Both hit text and needles are normalised (strip-diacritics + lower)
    so callers can pass ASCII-folded keywords like ``"Mang khong on"``.
    """
    region_px = region_pct_to_px(screen, region_pct)
    hits = ocr.find_all(screen, region=region_px)
    needles_lc = tuple(ocr.strip_diacritics(n).lower() for n in needles)
    for h in hits:
        if h.confidence < threshold:
            continue
        t = ocr.strip_diacritics(h.text).lower()
        if any(n in t for n in needles_lc):
            return True
    return False


def try_template(
    device: Device,
    screen: np.ndarray,
    name: str,
    threshold: float,
    region_pct: tuple[float, float, float, float] | None = None,
) -> bool:
    """Return True if a template matches above ``threshold`` in region."""
    try:
        region_px = (
            region_pct_to_px(screen, region_pct) if region_pct else None
        )
        return device.find_template_in(
            name, screen, threshold, region=region_px,
        ) is not None
    except FileNotFoundError:
        return False


def tap_template(
    device: Device,
    screen: np.ndarray,
    name: str,
    threshold: float = 0.78,
    region_pct: tuple[float, float, float, float] | None = None,
    long_tap: bool = False,
) -> tuple[int, int] | None:
    """Find a template on ``screen`` and tap its centre."""
    try:
        region_px = (
            region_pct_to_px(screen, region_pct) if region_pct else None
        )
        pos = device.find_template_in(
            name, screen, threshold, region=region_px,
        )
    except FileNotFoundError:
        log.error("Thiếu template: %s", name)
        return None

    if pos is None:
        log.warning(
            "Không thấy template %s (ngưỡng=%.2f, vùng=%s)",
            name, threshold, region_pct,
        )
        return None

    # Chạm vào
    if long_tap:
        device.long_tap(*pos, duration_ms=100)
    else:
        device.tap(*pos)

    # Đợi 0.8s cho giao diện chuyển đổi/mở ra
    pause(0.8)

    return pos


def tap_template_debug(
    device: Device,
    screen: np.ndarray,
    name: str,
    threshold: float = 0.78,
    region_pct: tuple[float, float, float, float] | None = None,
    long_tap: bool = False,
) -> tuple[int, int] | None:
    """Gọi trực tiếp hàm tap_template đã tích hợp debug realtime."""
    return tap_template(device, screen, name, threshold, region_pct, long_tap)
