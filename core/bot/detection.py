"""State detection — classify the current screen into one of ``S``.

Hot path is template-only (no OCR). On the test phone a template
match is ~100-500ms vs ~25-30s for a full-image OCR pass, so every
common state is detected by templates alone. The OCR phases only
run when no template matched — meaning we're likely in a popup /
dialog / lock screen / army composition view.
"""
from __future__ import annotations

import logging

import numpy as np

from core import ocr
from core.device import Device

from .geometry import ocr_text_in, region_pct_to_px, try_template
from .state import S

log = logging.getLogger(__name__)


def is_lock_screen(screen: np.ndarray) -> bool:
    """Detect the RoK in-game lock screen.

    Two signals must coincide to avoid false positives on dim panels
    (e.g. the "Quân mới" army composition view):

      A. Centre is very dark (avg RGB-sum < 200) — the lock overlay
         dims the entire viewport.
      B. At least 2 of the sampled centre pixels carry the distinctive
         BLUE colour of the padlock icon (high B, very low R, mid G).

    Fallback: pitch-black centre (avg < 80) also counts as locked —
    handles the screen-off state where the padlock hasn't rendered yet.
    """
    h, w = screen.shape[:2]
    total = 0
    n = 0
    blue_count = 0
    for xp in (42, 46, 50, 54, 58):
        for yp in (44, 48, 52, 56, 60):
            x = int(w * xp / 100)
            y = int(h * yp / 100)
            b, g, r = screen[y, x]
            bi, gi, ri = int(b), int(g), int(r)
            total += bi + gi + ri
            n += 1
            if bi > 130 and ri < 100 and 80 < gi < 180:
                blue_count += 1
    avg = total / n
    if avg < 200 and blue_count >= 2:
        return True
    return False


def _has_tile_info_popup(screen: np.ndarray) -> bool:
    """Cheap pixel-color check for ANY tile_info popup over world view.

    Resource tiles (with THU THẬP) are detected by the btn_thu_thap
    template; barbarian / empty-land tiles use the same popup frame
    WITHOUT THU THẬP and would otherwise be misclassified as WORLD
    (because the kinh_luc icon stays visible behind the popup).

    The cream-coloured popup frame produces many "light" pixels in
    the centre region; pure world view averages green/brown. >=4
    light pixels => popup likely present.
    """
    h, w = screen.shape[:2]
    light_count = 0
    for xp in range(25, 80, 10):
        for yp in range(25, 65, 10):
            x = int(w * xp / 100)
            y = int(h * yp / 100)
            b, g, r = screen[y, x]
            if int(r) + int(g) + int(b) > 600:
                light_count += 1
    return light_count >= 4


def is_network_popup(screen: np.ndarray) -> bool:
    """Fast OCR check for the "Đã ngắt kết nối mạng" popup banner.

    The region is small (centre-top, 30-70% x by 10-28% y) so OCR
    takes ~0.2-0.4s. Call this after every snapshot inside long
    handlers — the popup can appear at any time and overlay the UI,
    making subsequent taps land on the wrong elements.
    """
    return ocr_text_in(
        screen, (30, 10, 70, 28),
        (
            "NGAT KET NOI", "Ngat ket noi", "ngat ket noi",
            "DA NGAT", "Da ngat",
            "Network unstable", "Network un",
            "connection lost", "Connection lost",
        ),
        threshold=0.4,
    )


def is_gems_shop(screen: np.ndarray) -> bool:
    """Fast OCR check for the Gem Shop / Recharge menu screen.

    Since this can overlay the UI or pop up at any time, we check
    for distinctive in-game store / Google Play keywords.
    """
    return ocr_text_in(
        screen, (0, 0, 100, 100),
        (
            "da quy", "mt gio da quy", "mt xe da quy",
            "d499,000", "d1,300,000", "d2,500,000",
            "huy thanh toan", "thanh toan",
        ),
        threshold=0.4,
    )


def detect_state(device: Device, screen: np.ndarray) -> S:
    """Detect current game state. First-match-wins ordering."""
    # ---- Phase 0: lock screen (cheap brightness check) --------------
    if is_lock_screen(screen):
        return S.LOCK_SCREEN

    # ---- Phase 1: template-only fast path ---------------------------

    # 1a. MARCH_PLAN (composition view): HÀNH QUÂN at bottom-right.
    if try_template(device, screen, "btn_hanh_quan.png", 0.78,
                    region_pct=(55, 75, 100, 100)):
        return S.MARCH_PLAN

    # 1b. MARCH_PLAN (initial form): Quân mới at top-right.
    if try_template(device, screen, "btn_quan_moi.png", 0.80,
                    region_pct=(60, 0, 100, 30)):
        return S.MARCH_PLAN

    # 2. TILE_INFO: THU THẬP button.
    # CHECKED BEFORE SEARCH_PANEL because btn_slider_minus spuriously
    # matches on tile_info's slider-like UI (conf ~0.72). thu_thap
    # matches at ~1.00 on tile_info vs ~0.5 on search_panel, so
    # threshold 0.80 cleanly discriminates.
    if try_template(device, screen, "btn_thu_thap.png", 0.80,
                    region_pct=(55, 30, 95, 80)):
        return S.TILE_INFO

    # 3. SEARCH_PANEL via TÌM KIẾM + slider. Threshold for tim_kiem
    # is raised to 0.75 to prevent false matches with background.
    if try_template(device, screen, "btn_tim_kiem.png", 0.75,
                    region_pct=(5, 50, 85, 90)):
        if (
            try_template(device, screen, "btn_slider_plus.png", 0.72,
                         region_pct=(5, 35, 75, 80))
            or try_template(device, screen, "btn_slider_minus.png", 0.68,
                            region_pct=(5, 35, 75, 80))
        ):
            return S.SEARCH_PANEL

    # 3b. SEARCH_PANEL via both +/- buttons (tim_kiem may miss).
    if (
        try_template(device, screen, "btn_slider_plus.png", 0.70,
                     region_pct=(5, 35, 75, 80))
        and try_template(device, screen, "btn_slider_minus.png", 0.65,
                         region_pct=(5, 35, 75, 80))
    ):
        return S.SEARCH_PANEL

    # 4. CITY: map_toggle (globe icon) at bottom-left.
    # MUST come before kinh_luc check — kinh_luc threshold is low
    # and sometimes false-matches build-menu icons.
    if try_template(device, screen, "btn_map_toggle.png", 0.88,
                    region_pct=(0, 80, 15, 100)):
        return S.CITY

    # 5. WORLD: kinh_luc (magnifying glass). Popup safety net afterward.
    if try_template(device, screen, "btn_kinh_luc.png", 0.55,
                    region_pct=(0, 70, 10, 85)):
        if _has_tile_info_popup(screen):
            log.info("Phát hiện kính lúp + popup -> TILE_INFO")
            return S.TILE_INFO
        return S.WORLD

    # ---- Phase 2a: REGION-ONLY OCR for SEARCH_PANEL -----------------
    # Cheap pre-check before the expensive full-image OCR. If we see
    # ≥2 of the 5 tab labels in the bottom strip, it's the search panel.
    bottom_strip = region_pct_to_px(screen, (0, 85, 100, 100))
    bottom_hits = ocr.find_all(screen, region=bottom_strip)
    tab_keywords = (
        "nguoi man", "dat trong", "trai xe", "tram tich", "tich da",
        "tich vang",
    )
    matched = 0
    for hit in bottom_hits:
        if hit.confidence < 0.4:
            continue
        norm = ocr.strip_diacritics(hit.text).lower()
        if any(k in norm for k in tab_keywords):
            matched += 1
    if matched >= 2:
        log.info("OCR thấy %d nhãn tab dưới -> SEARCH_PANEL", matched)
        return S.SEARCH_PANEL

    # ---- Phase 2b: full-image OCR fallback --------------------------
    ocr.find_all(screen)

    # Cửa hàng đá quý / Nạp tiền (Gems Shop)
    if is_gems_shop(screen):
        return S.GEMS_SHOP

    # Network-disconnect popup. Checked EARLY in phase 2 because it's
    # a fullscreen modal — other phase-2 checks might match its body.
    if ocr_text_in(screen, (15, 15, 85, 80),
                   ("Network unstable", "Network un",
                    "connection lost", "Connection lost",
                    "Please click CONFIRM", "click CONFIRM",
                    "Error 2",
                    "Mang khong on", "Khong on dinh",
                    "Mat ket noi", "ket noi lai",
                    "XAC NHAN", "Xac nhan"),
                   threshold=0.4):
        return S.NETWORK_ERROR



    # Army composition (no Quân mới template — distinctive bottom labels).
    if ocr_text_in(screen, (20, 0, 80, 15),
                   ("Quan moi", "QUAN MOI", "Quan m"),
                   threshold=0.3):
        return S.MARCH_PLAN
    if ocr_text_in(screen, (25, 65, 100, 100),
                   ("Hanh quan", "HANH QUAN", "Toi da", "TOI DA",
                    "Chon Nhieu", "Trong tai", "Tong suc",
                    "Khong co", "Bo quan", "XOA", "Xoa",
                    "+148", "+88", "+81", "+11"),
                   threshold=0.3):
        return S.MARCH_PLAN

    # Resource / shop / event popup.
    if ocr_text_in(screen, (0, 0, 90, 15),
                   ("TAI NGUYEN", "TANG TOC", "THIET BI", "VU TRANG",
                    "Goi Tai", "Su dung", "SU DUNG"),
                   threshold=0.5):
        return S.POPUP

    # Tile info via OCR (template missed but popup still visible).
    if ocr_text_in(screen, (25, 25, 75, 70),
                   ("Chua bi chiem", "Nguoi so huu", "Dich Chuyen",
                    "Tram tich", "Du tru", "Linh thu gom", "THU THAP",
                    "Thu thap"),
                   threshold=0.55):
        return S.TILE_INFO

    if ocr_text_in(screen, (0, 18, 18, 90),
                   ("KINH T", "QUAN DO", "TRANG TR", "Nha may go"),
                   threshold=0.4):
        return S.BUILD_MENU

    if ocr_text_in(screen, (30, 30, 70, 70),
                   ("Thoat tro choi", "thoat ung dung", "HUY"),
                   threshold=0.5):
        return S.EXIT_DIALOG

    if ocr_text_in(screen, (15, 25, 85, 75),
                   ("Khoa", "Keo bieu", "mo khoa"),
                   threshold=0.5):
        return S.LOCK_SCREEN

    # City fallback: "Thời kỳ phong kiến" banner.
    if ocr_text_in(screen, (10, 0, 80, 12),
                   ("phong", "Thi k", "Thoi k", "ky phong"),
                   threshold=0.5):
        return S.CITY

    return S.UNKNOWN
