"""State detection - classify the current screen into one of ``S``.

Hot path is template-only (no OCR). On the test phone a template
match is ~100-500ms vs ~25-30s for a full-image OCR pass, so every
common state is detected by templates alone. The OCR phases only
run when no template matched - meaning we're likely in a popup /
dialog / lock screen / army composition view.
"""
from __future__ import annotations

import logging

import numpy as np

from core import ocr
from core.device import Device

from .capture import save_debug_image
from .geometry import ocr_text_in, region_pct_to_px, try_template
from .readers import read_slot_badge
from .state import S

log = logging.getLogger(__name__)


def _ocr_hits_in_region(
    screen: np.ndarray,
    region_pct: tuple[float, float, float, float],
    min_confidence: float = 0.35,
) -> list[tuple[str, float, int, int]]:
    region_px = region_pct_to_px(screen, region_pct)
    hits = ocr.find_all(screen, region=region_px)
    out = []
    for hit in hits:
        if hit.confidence < min_confidence:
            continue
        norm = ocr.strip_diacritics(hit.text).lower().strip()
        out.append((norm, hit.confidence, hit.cx, hit.cy))
    return out


def _texts_contain(texts: list[str], needles: tuple[str, ...]) -> bool:
    return any(any(needle in text for needle in needles) for text in texts)


def is_exit_dialog(screen: np.ndarray, *, debug: bool = False) -> bool:
    """Compatibility wrapper around the single modal classifier."""
    return classify_modal_popup(screen, debug=debug) == S.EXIT_DIALOG


def classify_modal_popup(screen: np.ndarray, *, debug: bool = True) -> S | None:
    """OCR modal text once and classify exit vs network at the same level."""
    region_pct = (15, 15, 85, 80)
    hits = _ocr_hits_in_region(screen, region_pct, min_confidence=0.35)
    texts = [text for text, _conf, _x, _y in hits]
    joined = " | ".join(texts)

    has_exit_text = _texts_contain(
        texts,
        ("thoat tro", "thoat ung", "thoat game", "roi khoi", "exit"),
    )
    has_cancel = _texts_contain(texts, ("huy", "cancel", "hy"))
    has_confirm = _texts_contain(texts, ("xac nh", "confirm"))
    has_network_text = _texts_contain(
        texts,
        (
            "ngat ket noi", "ngt kt ni", "da ngat", "mat ket noi",
            "mt kt ni", "mang khong on", "khong on dinh", "ket noi lai",
            "network unstable", "network un", "connection lost", "error 2",
        ),
    )

    is_exit = has_exit_text or (has_cancel and has_confirm)
    is_network = has_network_text and not has_cancel
    state = S.EXIT_DIALOG if is_exit else S.NETWORK_ERROR if is_network else None

    if debug and (state is not None or has_cancel or has_confirm or has_network_text):
        log.info(
            "[detect-popup] modal=%s exit_text=%s network_text=%s cancel=%s confirm=%s hits=%s",
            state.value if state is not None else "none",
            has_exit_text,
            has_network_text,
            has_cancel,
            has_confirm,
            joined or "(none)",
        )
        if state is not None:
            region_px = region_pct_to_px(screen, region_pct)
            save_debug_image(
                screen,
                "detect",
                subdir="popup_debug",
                prefix=state.value,
                rects=[region_px],
                label=f"{state.value} hits={joined[:80]}",
            )
    return state


def locate_modal_button(screen: np.ndarray, button: str) -> tuple[int, int] | None:
    """Find a modal button by OCR text and return its screen coordinates."""
    button = button.strip().lower()
    if button == "cancel":
        needles = ("huy", "hy", "cancel")
    elif button == "confirm":
        needles = ("xac nh", "xac nhn", "confirm")
    else:
        needles = (button,)

    hits = _ocr_hits_in_region(screen, (15, 15, 85, 80), min_confidence=0.30)
    matches = [
        (text, conf, x, y)
        for text, conf, x, y in hits
        if any(needle in text for needle in needles)
    ]
    if not matches:
        return None

    text, conf, x, y = max(matches, key=lambda hit: hit[1])
    log.info(
        "[detect-popup] button=%s hit=%r conf=%.2f at=(%d,%d)",
        button,
        text,
        conf,
        x,
        y,
    )
    return x, y


def is_lock_screen(screen: np.ndarray) -> bool:
    """Detect the RoK in-game lock screen.

    Two signals must coincide to avoid false positives on dim panels
    (e.g. the "Quan moi" army composition view):

      A. Centre is very dark (avg RGB-sum < 200) - the lock overlay
         dims the entire viewport.
      B. At least 2 of the sampled centre pixels carry the distinctive
         BLUE colour of the padlock icon (high B, very low R, mid G).

    Fallback: pitch-black centre (avg < 80) also counts as locked -
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

    Resource tiles (with THU THAP) are detected by the btn_thu_thap
    template; barbarian / empty-land tiles use the same popup frame
    WITHOUT THU THAP and would otherwise be misclassified as WORLD
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
    return light_count >= 8



def is_network_popup(screen: np.ndarray) -> bool:
    """Compatibility wrapper around the single modal classifier."""
    return classify_modal_popup(screen, debug=True) == S.NETWORK_ERROR


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


def is_alliance_panel(screen: np.ndarray) -> bool:
    """Xác định màn hình Bảng Liên Minh (S.ALLIANCE_PANEL).

    Nhận diện kết hợp 3 tín hiệu:
      1. Pixel xanh đặc trưng của icon Công Nghệ (beaker).
      2. Tiêu đề "LIÊN MINH" ở vùng giữa trên cùng.
      3. Hoặc chứa các nhãn cố định động: "thủ lĩnh", "lãnh thổ", "quà liên minh", "sức mạnh", "thành viên".
    """
    h, w = screen.shape[:2]
    cx = int(w * 0.522)
    cy = int(h * 0.868)
    blue = 0
    for dx in (-22, -8, 8, 22):
        for dy in (-12, 0, 12):
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                b, g, r = screen[y, x]
                if int(b) > 140 and int(r) < 140:
                    blue += 1
    if blue >= 5:
        return True

    has_title = ocr_text_in(
        screen, (30.0, 0.0, 70.0, 15.0),
        ("LIEN MINH", "Lien Minh", "LIÊN MINH"),
        threshold=0.4,
    )
    if has_title:
        return True

    hits = ocr.find_all(screen)
    matched_labels = 0
    keywords = ("thu linh", "lanh tho", "qua lien minh", "suc manh", "thanh vien")
    for hit in hits:
        if hit.confidence < 0.3:
            continue
        norm = ocr.strip_diacritics(hit.text).lower()
        if any(k in norm for k in keywords):
            matched_labels += 1
            if matched_labels >= 2:
                return True
    return False



def is_pre_kvk(screen: np.ndarray) -> bool:
    """Xác định màn hình sự kiện Pre-KVK (Đêm Giao Thừa Của Cuộc Thập Tự Chinh).

    Nhận diện kết hợp tiêu đề & đa nhãn đặc trưng tự động chịu lỗi OCR rớt nguyên âm:
      - "dem giao", "giao tha", "thp t chinh", "thap tu chinh"
      - "dong quan", "cup boc", "tri thuy", "tri ha", "tri tho"
    """
    hits = ocr.find_all(screen)
    matched_labels = 0
    keywords = (
        "dem giao", "thp t chinh", "thap tu chinh", "giao tha", "giao thua",
        "dong quan", "cup boc", "tri thuy", "tri ha", "tri tho", "tri hoa",
    )
    for hit in hits:
        if hit.confidence < 0.3:
            continue
        norm = ocr.strip_diacritics(hit.text).lower()
        if any(k in norm for k in keywords):
            matched_labels += 1
            if matched_labels >= 2:
                return True
    return False


def is_troops_panel(screen: np.ndarray) -> bool:
    """Xác định màn hình Bảng Danh Sách Đạo Quân (Màn hình Đội Quân / Đạo Quân).

    Tín hiệu nhận diện:
      - Tiêu đề "Đại Quân", "Đội Quân", "Đi Quân" ở header.
      - Các từ khóa nội dung: "chuyen dong quan", "cam tri va dang cho lanh", "don vi".
    """
    hits = ocr.find_all(screen)
    keywords = (
        "di quan", "doi quan", "dai quan", "chuyen dong quan", "chuyn dng qun",
        "cam tri va dang cho lanh", "cm tri va dang", "qun ca bn da duc cm tri",
    )
    for hit in hits:
        if hit.confidence < 0.3:
            continue
        norm = ocr.strip_diacritics(hit.text).lower()
        if any(k in norm for k in keywords):
            return True
    return False









def detect_state(device: Device, screen: np.ndarray) -> S:
    """Detect current game state. First-match-wins ordering."""
    # ---- Phase 0: lock screen (cheap brightness check) --------------
    if is_lock_screen(screen):
        return S.LOCK_SCREEN

    # ---- Phase 1: template-only fast path ---------------------------

    # 1a. MARCH_PLAN (composition view): HANH QUAN at bottom-right.
    if try_template(device, screen, "btn_hanh_quan.png", 0.78,
                    region_pct=(55, 75, 100, 100)):
        return S.MARCH_PLAN

    # 1b. MARCH_PLAN (initial form): Quan moi at top-right.
    if try_template(device, screen, "btn_quan_moi.png", 0.80,
                    region_pct=(60, 0, 100, 30)):
        return S.MARCH_PLAN

    # 2. TILE_INFO: THU THAP button.
    # CHECKED BEFORE SEARCH_PANEL because btn_slider_minus spuriously
    # matches on tile_info's slider-like UI (conf ~0.72). thu_thap
    # matches at ~1.00 on tile_info vs ~0.5 on search_panel, so
    # threshold 0.80 cleanly discriminates.
    if try_template(device, screen, "btn_thu_thap.png", 0.80,
                    region_pct=(55, 30, 95, 80)):
        return S.TILE_INFO

    # 3. SEARCH_PANEL via TIM KIEM + slider. Threshold for tim_kiem
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
    # MUST come before kinh_luc check - kinh_luc threshold is low
    # and sometimes false-matches build-menu icons.
    if try_template(device, screen, "btn_map_toggle.png", 0.88,
                    region_pct=(0, 80, 15, 100)):
        return S.CITY

    # 5. WORLD: kinh_luc (magnifying glass). Popup safety net afterward.
    if try_template(device, screen, "btn_kinh_luc.png", 0.50,
                    region_pct=(0, 70, 10, 85)):
        if _has_tile_info_popup(screen):
            log.info("Phat hien kinh lup + popup -> TILE_INFO")
            return S.TILE_INFO
        return S.WORLD

    # ---- Phase 2a: REGION-ONLY OCR for SEARCH_PANEL -----------------
    # Cheap pre-check before the expensive full-image OCR. If we see
    # >=2 of the 5 tab labels in the bottom strip, it's the search panel.
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
        log.info("OCR thay %d nhan tab duoi -> SEARCH_PANEL", matched)
        return S.SEARCH_PANEL

    # ---- Phase 2b: full-image OCR fallback --------------------------
    ocr.find_all(screen)

    # Cua hang da quy / Nap tien (Gems Shop)
    if is_gems_shop(screen):
        return S.GEMS_SHOP

    # Bang Lien Minh (Alliance Panel)
    if is_alliance_panel(screen):
        return S.ALLIANCE_PANEL

    # Man hinh su kien Pre-KVK
    if is_pre_kvk(screen):
        return S.PRE_KVK

    # Bang Danh sach Dao Quan (Troops Panel)
    if is_troops_panel(screen):
        return S.TROOPS_PANEL

    modal_state = classify_modal_popup(screen, debug=True)


    if modal_state in (S.EXIT_DIALOG, S.NETWORK_ERROR):
        return modal_state




    # Army composition (no Quan moi template - distinctive bottom labels).
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

    # City fallback: "Thoi ky phong kien" banner.
    if ocr_text_in(screen, (10, 0, 80, 12),
                   ("phong", "Thi k", "Thoi k", "ky phong"),
                   threshold=0.5):
        return S.CITY

    # World fallback: on WORLD the march queue badge n/N is visible at
    # top-right even when the kinh_luc template misses because of camera/UI
    # animation. Put this late, after modal/panel checks, to avoid masking
    # actionable overlays.
    n, mx = read_slot_badge(screen)
    if n is not None and mx is not None:
        log.info("WORLD fallback bang huy hieu hang doi: %d/%d", n, mx)
        return S.WORLD

    return S.UNKNOWN
