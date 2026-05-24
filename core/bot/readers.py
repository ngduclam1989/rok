"""OCR-based readers for in-game text.

* ``read_slot_badge`` — n/N march-queue indicator at top-right.
* ``read_level_in_panel`` — slider level inside the search panel.
* ``read_march_panel_times`` — every "Đang thu gom HH:MM:SS" timer
  in the army-detail panel, returning the dynamic sleep duration.
"""
from __future__ import annotations

import logging
import re
import time

import numpy as np

from core import ocr
from core.device import Device

from . import config
from .geometry import pct_to_px, region_pct_to_px
from .signals import should_stop, sleep_with_stop_check_exact

log = logging.getLogger(__name__)

_SLOT_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")

_DANG_THU_GOM_MARGIN_SEC = 10 * 60  # +10 min after shortest timer


def read_slot_badge(
    screen: np.ndarray,
) -> tuple[int | None, int | None]:
    """OCR the n/N badge at top-right of city/world view.

    Returns ``(n, max)`` or ``(None, None)`` when unreadable.
    """
    region = region_pct_to_px(screen, (88, 16, 100, 32))
    hits = ocr.find_all(screen, region=region)
    for h in hits:
        m = _SLOT_RE.search(h.text)
        if not m:
            continue
        try:
            n, mx = int(m.group(1)), int(m.group(2))
        except ValueError:
            continue
        if 0 <= n <= mx <= 20:
            return n, mx
    return None, None


def read_level_in_panel(screen: np.ndarray) -> int | None:
    """OCR "Cấp: N" in the search panel.

    The panel can sit on the LEFT half (e.g. EMPTY tab) or RIGHT half
    (e.g. WOOD, BARB) depending on resource. The OCR region spans
    5-95% x to cover both.

    Two text shapes are accepted:
      * "Cấp: N"           — current slider value (the target).
      * "Cấp tối đa M ..." — kingdom's max description (fallback).
    """
    region = region_pct_to_px(screen, (5, 30, 95, 75))
    hits = ocr.find_all(screen, region=region)

    label_re = re.compile(r"c[ap]+\s*[:\.]\s*(\d+)", re.IGNORECASE)
    desc_re = re.compile(
        r"c[ap]+\s+t[a-z]*\s+[a-z]*\s*(\d+)", re.IGNORECASE,
    )

    def _parse(rx: re.Pattern[str], text: str) -> int | None:
        text_norm = ocr.strip_diacritics(text)
        m = rx.search(text_norm)
        if not m:
            return None
        try:
            val = int(m.group(1))
        except ValueError:
            return None
        return val if 1 <= val <= 50 else None

    for hit in hits:
        if hit.confidence < 0.6:
            continue
        val = _parse(label_re, hit.text)
        if val is not None:
            return val

    for hit in hits:
        if hit.confidence < 0.6:
            continue
        val = _parse(desc_re, hit.text)
        if val is not None:
            log.info(
                "Dùng mô tả cấp=%d (OCR nhãn slider không đọc được)", val,
            )
            return val
    return None


def _ocr_panel_times(screen: np.ndarray) -> set[int]:
    """Return the set of HH:MM:SS values (in seconds) on this screen
    that look like real gather/march timers (between 1s and 24h)."""
    ocr.clear_cache()
    found: set[int] = set()
    for hit in ocr.find_all(screen):
        if hit.confidence < 0.5:
            continue
        m = _TIME_RE.search(hit.text)
        if not m:
            continue
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        total = h * 3600 + mn * 60 + s
        if 0 < total < 24 * 3600:
            if total not in found:
                log.info(
                    "Thời gian bảng quân: %02d:%02d:%02d = %ds (text=%r)",
                    h, mn, s, total, hit.text,
                )
            found.add(total)
    return found


def read_march_panel_times(
    device: Device, current_screen: np.ndarray,
) -> float | None:
    """Open the march-detail panel, OCR every "Đang thu gom HH:MM:SS"
    timer, and return ``shortest + 10 minutes`` (in seconds).

    Steps:
      1. Wait 30s so freshly-dispatched troops enter "Đang thu gom".
      2. Tap the n/N badge arrow at top-right to open the detail panel.
      3. OCR the panel.
      4. Scroll up to 3 times to expose slots cut off below the fold.
      5. Drop timers shorter than GATHER_MIN_SEC (those are travel
         time, not gather).
      6. Return min + 10 min margin. Close the panel via BACK.

    Returns ``None`` if no gather-grade timer was found — caller
    falls back to ``config.TURN_WAIT_SEC``.
    """
    # log.info("Đợi 30s cho các đội quân vào pha thu thập...")
    # sleep_with_stop_check_exact(30.0)
    if should_stop():
        return None

    # Tap the n/N badge arrow at (92%, 20%) on the test device.
    bx, by = pct_to_px(current_screen, 92.0, 20.0)
    log.info(
        "Chạm mũi tên huy hiệu @(%d,%d) để mở bảng chi tiết quân",
        bx, by,
    )
    device.tap(bx, by)
    time.sleep(2.5)

    all_seconds: set[int] = set()
    try:
        panel = device.snapshot()
        all_seconds |= _ocr_panel_times(panel)
    except Exception:
        log.exception("Snapshot bảng quân lần đầu thất bại")

    h_screen, w_screen = current_screen.shape[:2]
    scroll_from_x = w_screen // 2
    scroll_from_y = int(h_screen * 0.80)
    scroll_to_y = int(h_screen * 0.30)
    for pass_idx in range(3):
        device.swipe(
            scroll_from_x, scroll_from_y,
            scroll_from_x, scroll_to_y, 500,
        )
        time.sleep(1.2)
        try:
            panel = device.snapshot()
        except Exception:
            log.exception("Snapshot sau khi cuộn thất bại")
            break
        new_found = _ocr_panel_times(panel)
        before = len(all_seconds)
        all_seconds |= new_found
        if len(all_seconds) == before:
            log.info(
                "Lần cuộn %d: không có thời gian mới -> dừng cuộn",
                pass_idx + 1,
            )
            break

    try:
        device.key("BACK")
    except Exception:
        pass
    time.sleep(1.5)

    if not all_seconds:
        log.warning("Không đọc được thời gian thu thập từ bảng quân")
        return None
    gather_times = [s for s in all_seconds if s >= config.GATHER_MIN_SEC]
    if not gather_times:
        log.warning(
            "Không có thời gian nào vượt ngưỡng %ds — tất cả trông giống "
            "thời gian di chuyển (%s). Trả None để caller fallback.",
            config.GATHER_MIN_SEC, sorted(all_seconds),
        )
        return None
    shortest = min(gather_times)
    wait_with_margin = shortest + _DANG_THU_GOM_MARGIN_SEC
    log.info(
        "Thời gian thu gom (s): %s | Ngắn nhất: %ds (~%.1f phút); "
        "đợi lượt sau = ngắn nhất + 10 phút = %ds (~%.1f phút)",
        sorted(gather_times), shortest, shortest / 60.0,
        wait_with_margin, wait_with_margin / 60.0,
    )
    return float(wait_with_margin)
