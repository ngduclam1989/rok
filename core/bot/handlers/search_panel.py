"""Search-panel handler.

Selects the configured resource tab, ensures the slider level matches
``config.TARGET_LEVEL``, then taps TÌM KIẾM. The slider state is kept
in module-level ``LAST_LEVEL_SEEN`` / ``LAST_ADJUST_DIR`` so the
main loop can reset them at each new turn.
"""
from __future__ import annotations

import logging

import numpy as np

from core import ocr
from core.device import Device

from .. import config
from ..geometry import region_pct_to_px, tap_template
from ..readers import read_level_in_panel
from ..signals import pause
from ..state import StepResult
from .network import check_and_handle_network_popup

log = logging.getLogger(__name__)

# Mutable slider-state across iterations. Reset by ``runtime.run``
# at the start of each turn via ``reset_slider_state()``.
LAST_LEVEL_SEEN: int | None = None
LAST_ADJUST_DIR: str | None = None
OCR_FAILED_COUNT: int = 0


def reset_slider_state() -> None:
    global LAST_LEVEL_SEEN, LAST_ADJUST_DIR, OCR_FAILED_COUNT
    LAST_LEVEL_SEEN = None
    LAST_ADJUST_DIR = None
    OCR_FAILED_COUNT = 0


# Substring needles (after strip-diacritics + lowercase). Each needle
# must be UNIQUE to a single resource — e.g. "tram t" would match
# both "tram tich da" and "tram tich vang" and is forbidden.
_TAB_LABEL_NEEDLES = {
    "barb": ("nguoi man", "guoi man", "man ro", "manro"),
    "corn": ("dat trong", "dattrong", "at trong", "datron", "dat trồng", "dat trong"),
    "wood": ("trai xe go", "trai xe g", "ai xe go", "rai xe"),
    "stone": ("tram tich da", "ram tich da", "tich da", "ich da"),
    "gold": (
        "tram tich vang", "ram tich vang", "tich vang",
        "ich vang", "tich van",
    ),
}

# Content needles for confirming the panel is already on a given tab.
# Different from _TAB_LABEL_NEEDLES (which only matches the bottom
# strip labels) — these match descriptive copy in the panel body.
_TAB_PANEL_CONTENT_NEEDLES = {
    "barb": ("nguoi man", "phao dai", "barbaria"),
    "corn": ("dat trong", "bao vay", "thuc pham", "gui quan", "ngo", "ruong lua"),
    "wood": ("trai xe go", "trai xe", "xe go"),
    "stone": ("tram tich da", "tich da", "ich da"),
    "gold": ("tram tich vang", "tich vang", "ich vang"),
}


def _find_resource_tab(
    screen: np.ndarray, resource: str,
) -> tuple[int, int] | None:
    """OCR the bottom-strip tabs and return the tap coords for one.

    Returns the LABEL centre (not the icon centre) — on Android the
    tab cell accepts taps anywhere over icon+label, and label centres
    are more stable than icon centres which can drift with theming.
    """
    region_px = region_pct_to_px(screen, (0, 85, 100, 100))
    needles = _TAB_LABEL_NEEDLES.get(resource, ())
    if not needles:
        return None
    hits = ocr.find_all(screen, region=region_px)
    if hits:
        labels = ", ".join(
            f"{ocr.strip_diacritics(h.text)!r}@({h.cx},{h.cy}) "
            f"conf={h.confidence:.2f}"
            for h in hits if h.confidence >= 0.4
        )
        log.info("OCR dải tab dưới: %s", labels or "(không có)")
    for hit in hits:
        if hit.confidence < 0.5:
            continue
        norm = ocr.strip_diacritics(hit.text).lower().strip()
        for n in needles:
            if n in norm:
                log.info(
                    "Tab %s match needle %r trong text %r -> tap (%d,%d)",
                    resource.upper(), n, hit.text, hit.cx, hit.cy,
                )
                return hit.cx, hit.cy
    return None


def _is_panel_on_tab(screen: np.ndarray, resource: str) -> bool:
    """OCR the panel body for content needles unique to ``resource``.

    Some tabs (e.g. EMPTY) don't display the resource name as a title
    — fall back to descriptive content like "bao vay" / "thuc pham".
    """
    needles = _TAB_PANEL_CONTENT_NEEDLES.get(resource, ())
    if not needles:
        return False
    region_px = region_pct_to_px(screen, (5, 5, 95, 75))
    hits = ocr.find_all(screen, region=region_px)
    for hit in hits:
        if hit.confidence < 0.4:
            continue
        norm = ocr.strip_diacritics(hit.text).lower().strip()
        if any(n in norm for n in needles):
            return True
    return False


def handle_search_panel(
    device: Device, screen: np.ndarray,
) -> StepResult:
    """Pick the resource tab, set the slider level, tap TÌM KIẾM."""
    global LAST_LEVEL_SEEN, LAST_ADJUST_DIR, OCR_FAILED_COUNT

    h, w = screen.shape[:2]
    resource = config.RESOURCE_TAB
    target_level = config.TARGET_LEVEL

    if check_and_handle_network_popup(device, screen):
        return StepResult(
            True, "đã xử lý popup mạng giữa search_panel", sleep_after=1.5,
        )

    # Always tap the target resource tab to ensure we are correctly selected.
    tab_pos = _find_resource_tab(screen, resource)
    if tab_pos is None:
        tab_x_pct = config._RESOURCE_TAB_X_PCT.get(resource, 0.50)
        tab_x, tab_y = int(w * tab_x_pct), int(h * 0.91)
        log.warning(
            "OCR không thấy tab %s -> dùng toạ độ mặc định @(%d,%d)",
            resource.upper(), tab_x, tab_y,
        )
    else:
        tab_x, tab_y = tab_pos
    log.info(
        "Chạm tab %s @(%d,%d)", resource.upper(), tab_x, tab_y,
    )
    device.long_tap(tab_x, tab_y, duration_ms=200)
    pause(1.2)
    try:
        screen = device.snapshot()
    except Exception:
        pass
    if check_and_handle_network_popup(device, screen):
        return StepResult(
            True, "popup mạng sau chạm tab", sleep_after=1.5,
        )

    if not config.SKIP_LEVEL_ADJUST:
        level = read_level_in_panel(screen)
        log.info("Bảng tìm kiếm (%s), cấp=%s", resource, level)

        if level is None:
            OCR_FAILED_COUNT += 1
            log.warning(
                "OCR cấp thất bại (lần %d/3) -> thử lại lần sau",
                OCR_FAILED_COUNT,
            )
            if OCR_FAILED_COUNT >= 3:
                log.warning("OCR cấp thất bại liên tiếp 3 lần -> Bấm BACK quay về WORLD để reset bảng tìm kiếm")
                OCR_FAILED_COUNT = 0
                try:
                    device.key("BACK")
                except Exception:
                    pass
                return StepResult(
                    True, "thất bại cấp quá nhiều, bấm BACK quay lại world", sleep_after=2.0
                )
            return StepResult(
                False, "không đọc được cấp", sleep_after=1.5,
            )

        # Reset bộ đếm nếu OCR thành công
        OCR_FAILED_COUNT = 0

        # Anti-runaway: if the previous adjustment moved the slider
        # the wrong way (e.g., we tapped "minus" but level rose —
        # template matched the plus button or the slider knob), bail
        # out for the rest of this turn and tap TÌM KIẾM with whatever
        # level is set. Saves the user from a stuck loop.
        if (
            LAST_ADJUST_DIR is not None
            and LAST_LEVEL_SEEN is not None
            and level != target_level
        ):
            went_down = level < LAST_LEVEL_SEEN
            went_up = level > LAST_LEVEL_SEEN
            wrong = (
                (LAST_ADJUST_DIR == "minus" and went_up)
                or (LAST_ADJUST_DIR == "plus" and went_down)
            )
            if wrong:
                log.warning(
                    "Slider chạy SAI hướng (%d -> %d sau khi bấm %s) "
                    "-> bỏ qua chỉnh tiếp",
                    LAST_LEVEL_SEEN, level, LAST_ADJUST_DIR,
                )
                LAST_ADJUST_DIR = "skip"
                LAST_LEVEL_SEEN = level
                level = target_level  # bypass adjust branch

        if level != target_level:
            diff = abs(level - target_level)
            tpl = (
                "btn_slider_plus.png" if level < target_level
                else "btn_slider_minus.png"
            )
            action = "plus" if level < target_level else "minus"
            try:
                region_px = region_pct_to_px(screen, (15, 50, 90, 75))
                pos = device.find_template_in(
                    tpl, screen, 0.55, region=region_px,
                )
            except FileNotFoundError:
                log.error("Thiếu template: %s", tpl)
                pos = None
            if pos is None:
                return StepResult(
                    False, f"không thấy nút {action}", sleep_after=1.5,
                )
            taps = min(diff, 30)
            log.info(
                "Cấp %d != %d -> bấm %s x%d @(%d,%d)",
                level, target_level, action, taps, *pos,
            )
            for _ in range(taps):
                device.long_tap(*pos, duration_ms=120)
                pause(0.25)
            LAST_LEVEL_SEEN = level
            LAST_ADJUST_DIR = action
            # sleep_after dài hơn (2.5s thay vì 1.0s) để slider có
            # đủ thời gian render giá trị mới — iter sau OCR cấp
            # sẽ đọc số ổn định, không bị "trôi" trong animation.
            return StepResult(
                True, f"{action} x{taps}", sleep_after=1.5,
            )

    # Delay trước khi chạm TÌM KIẾM: kể cả khi không vừa chỉnh slider
    # ở iter này (level đã = target từ trước), iter trước có thể vừa
    # mới chỉnh xong. Đợi 1.2s cho UI ổn định rồi mới tap, tránh tap
    # vào lúc animation slider/panel còn đang chạy -> game bỏ qua.
    log.info("Chạm TÌM KIẾM (chờ 0.5s cho UI ổn định)")
    pause(0.5)
    pos = tap_template(
        device, screen, "btn_tim_kiem.png", 0.75,
        region_pct=(20, 55, 95, 80),
        long_tap=True,
    )
    if pos is None:
        return StepResult(
            False, "không thấy nút TÌM KIẾM", sleep_after=1.5,
        )
    return StepResult(True, "đã chạm tìm kiếm", sleep_after=2.5)
