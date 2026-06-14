"""Việc vặt "người chơi" chạy XEN trong pha ngủ khi hàng chờ đầy.

Sau khi gửi hết đạo quân đi gather, bot chỉ ngủ chờ slot trống. Người
thật lấp khoảng nghỉ đó bằng việc vặt: nhận quà liên minh, đóng góp công
nghệ... Rải các việc này ở thời điểm NGẪU NHIÊN trong giấc ngủ làm dòng
thời gian thao tác giống người, thay vì "gửi quân -> im lặng -> gửi quân"
đều như máy.

Toạ độ là PHẦN TRĂM màn hình, calibrate trên Samsung A71 2400x1080
landscape (2026-05-26) bằng cách điều hướng thật + OCR vị trí nhãn:
  Liên Minh (nav dưới-phải)      (75.6, 91.7)
  -> Quà Tặng (icon trong panel) (76.25, 56.5)
     -> NHẬN TẤT CẢ              (79.4, 31.5)
  -> Công Nghệ (icon)            (53.75, 78.7)
     -> kỹ năng có flag đỏ       (1 trong 6 ô _TECH_SLOTS)
        -> TẶNG xanh (góp RSS)   (71.0, 79.0) — verified ADB calibration

Mọi bước best-effort: lỗi chỉ log, luôn cố đưa game về WORLD để chu kỳ
gather không bị vỡ. Việc vặt CHỈ chạy khi humanize đang bật.
"""
from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime, timedelta

import numpy as np

from core import ocr
from core.device import Device

from . import humanize
from .capture import save_debug_image
from .detection import is_lock_screen
from .geometry import ocr_text_in, pct_to_px, region_pct_to_px
from .handlers import handle_exit_dialog, handle_lock_screen

log = logging.getLogger(__name__)

# --- toạ độ đã verify (A71 2400x1080 landscape, % màn hình) ---
_LIEN_MINH = (75.6, 94.0)        # nút Liên Minh ở nav dưới-phải (world/city)
_QUA_TANG = (76.25, 56.5)        # icon Quà Tặng trong panel Liên Minh
_NHAN_TAT_CA = (79.4, 31.5)      # nút NHẬN TẤT CẢ trong panel Quà
_TAB_THUONG = (49.0, 28.0)       # tab "Thưởng" trong panel Quà
_TAB_HIEM = (71.0, 28.0)         # tab "Hiếm" trong panel Quà
_DOT_THUONG = (58.5, 24.5)       # vùng red-dot trên tab Thưởng
_DOT_HIEM = (75.0, 24.5)         # vùng red-dot trên tab Hiếm
_XAC_NHAN = (46.0, 76.0)         # nút "Xác nhận" trong popup QUÀ NHẬN ĐƯỢC
_CLOSE_QUA_X = (87.0, 6.0)       # dấu X đóng panel Quà ở góc trên-phải
_CONG_NGHE = (53.75, 78.7)       # icon Công Nghệ trong panel Liên Minh
# 6 ô kỹ năng trong panel "Kỹ năng liên minh" (3 cột x 2 hàng).
_TECH_SLOTS: tuple[tuple[float, float], ...] = (
    (27.0, 39.0),    # row1 col1 — Nạp đầy đủ
    (50.5, 39.0),    # row1 col2 — Quà tặng của thiên nhiên
    (75.0, 39.0),    # row1 col3 — Tiến độ không kiểm soát
    (27.0, 66.0),    # row2 col1 — Nghệ nhân khéo léo
    (50.5, 66.0),    # row2 col2 — Sách & Trận chiến
    (75.0, 66.0),    # row2 col3 — Phản công
)
# Banner "Thiếu của sĩ quan" (ribbon đỏ tươi + ngôi sao vàng) nằm chéo
# ở góc TOP-LEFT của tile kỹ năng — KHÔNG nằm đối xứng trên đỉnh icon.
# Trước đây sample (dx=0, dy=-8%) hay miss vì banner lệch sang trái và
# lên cao hơn. Sample vùng rộng quanh điểm TOP-LEFT cho chắc.
_TECH_HINT_DX_PCT = -6.0
_TECH_HINT_DY_PCT = -11.0
_TECH_HINT_HALF_W = 50  # px (vùng sample rộng theo trục x)
_TECH_HINT_HALF_H = 28  # px (vùng sample cao theo trục y)
_TECH_HINT_MIN_RED = 40  # ngưỡng pixel đỏ tươi để công nhận có banner
_TANG_DONATE = (71.0, 79.0)      # nút TẶNG xanh phải — góp RSS liên minh
_CLOSE_TECH_X = (87.0, 6.0)      # X đóng panel chi tiết kỹ năng

# --- Lãnh Thổ (Alliance Territory) ---
# Icon Lãnh Thổ ở row1-col3 của panel Liên Minh (Quà Tặng là col5 x=76.25,
# Công Nghệ col2 hàng dưới x=53.75 -> Δ≈7.5%/cột -> col3 ≈ 61.25%).
# NHẬN button = nút xanh cyan ở header panel "Lãnh Thổ Liên Minh", góc
# trên-phải bên cạnh các con số RSS (1.6K bắp, 1.6K gỗ, 1.2K đá, 852 vàng).
_LANH_THO = (61.25, 56.5)        # icon Lãnh Thổ trong panel Liên Minh
# NHẬN button: nút cyan ngay BÊN PHẢI 4 con số RSS (bắp/gỗ/đá/vàng),
# KHÔNG sát mép phải panel (mép phải là dấu X close). Verify bằng OCR
# trên A71 2400x1080 landscape (2026-05-27): label "NHÂN" ở (73.5%, 18.9%).
_NHAN_LANH_THO = (73.5, 18.9)    # nút NHẬN xanh cyan ở header

# Icon "bắt tay" floating phía TRÊN nút Liên Minh — chỉ hiện khi có thành
# viên đang xây/nghiên cứu cần assist. 1 tap = trợ giúp tất cả (RoK tự
# batch). Toạ độ ước lượng từ ảnh user gửi: ngay trên Liên Minh
# (cùng x), y khoảng 84% (Liên Minh ở y=94%). Badge "N" đỏ nằm góc
# trên-phải icon -> dịch sang phải ~3% và lên trên ~2.5%.
_HELP_ICON = (75.6, 84.0)        # tâm icon bắt tay (tap target)
_HELP_BADGE = (78.5, 81.5)       # vị trí badge "N" đỏ để phát hiện

# Số lần góp tối đa mỗi lần chạy (cơ hội tối đa của RoK là 20/20).
# Set qua biến module: ``chores.TECH_MAX_DONATE = N``.
TECH_MAX_DONATE: int = 20

# Xác suất một giấc ngủ-chờ-slot có kèm việc vặt.
CHORE_CHANCE = 0.6
# Bỏ qua với giấc ngủ ngắn — cần chỗ để điều hướng + ngủ quanh việc vặt.
MIN_SLEEP_FOR_CHORE_SEC = 360.0


def _has_alliance_button(screen) -> bool:
    """Kiểm tra xem nút Liên Minh có trên màn hình chính hay không."""
    return ocr_text_in(
        screen, (60.0, 85.0, 100.0, 100.0),
        ("Lien Minh", "lien minh", "LIEN MINH"),
        threshold=0.5,
    )


def _ensure_alliance_button_visible(device: Device, screen) -> np.ndarray:
    """Đảm bảo nút Liên Minh xuất hiện trên màn hình chính.
    
    Nếu không thấy nút Liên Minh (do menu bị thu gọn), bot sẽ:
      1. Vẽ ô vuông tại coords="2281,963,2366,1057" trên bản debug.
      2. Chạm vào điểm trung tâm lệch -10px (tương đương 2313, 1000 trên màn 2400x1080).
      3. Chờ 1.0s.
      4. Chụp lại màn hình để xác nhận lại.
    """
    if _has_alliance_button(screen):
        return screen

    log.info("[việc vặt] Không tìm thấy nút Liên Minh -> Tiến hành mở rộng menu")
    
    h, w = screen.shape[:2]
    # Toạ độ góc tuyệt đối trên màn tham chiếu 2400x1080
    ref_w, ref_h = 2400, 1080
    x1 = int(w * 2281 / ref_w)
    y1 = int(h * 963 / ref_h)
    x2 = int(w * 2366 / ref_w)
    y2 = int(h * 1057 / ref_h)
    
    # Tính điểm chạm trung tâm lệch -10px
    center_x = (x1 + x2) // 2 - int(10 * w / ref_w)
    center_y = (y1 + y2) // 2 - int(10 * h / ref_h)

    # Vẽ debug và ấn vào
    save_debug_image(
        screen, getattr(device, 'serial', 'dev'),
        subdir="menu_expand", prefix="menu_expand",
        clicks=[(center_x, center_y)],
        rects=[(x1, y1, x2, y2)],
        label="Expand Menu",
    )
    device.tap(center_x, center_y)
    time.sleep(1.0)
    
    # Chụp lại màn hình để xác nhận lại
    try:
        new_screen = device.snapshot()
        return new_screen
    except Exception:
        log.exception("[việc vặt] Không thể snapshot sau khi mở menu")
        return screen


def _tap(device: Device, screen, xy: tuple[float, float]) -> None:
    """Tap theo % màn (shape của screen là cố định cho thiết bị)."""
    humanize.human_thinking_pause()
    x, y = pct_to_px(screen, xy[0], xy[1])
    device.tap(x, y)


def _tap_quick(device: Device, screen, xy: tuple[float, float]) -> None:
    """Tap NHANH — pause ngắn 0.05-0.30s thay vì 0.4-1.1s.

    Dùng cho luồng việc vặt user yêu cầu "đừng chậm chạp" (vd. Lãnh Thổ
    chỉ 3 tap: vào panel, vào tab, nhận quà — chờ lâu giữa các tap không
    cần thiết, chỉ làm chậm tổng giấc ngủ).
    """
    humanize.human_inter_action_pause()
    x, y = pct_to_px(screen, xy[0], xy[1])
    device.tap(x, y)


def _wake_and_unlock(device: Device):
    """Snapshot; nếu đang khoá game -> mở khoá (1 lần).

    Trả screen mới hoặc None.

    Chỉ thử ĐÚNG 1 lần ở tầng này vì `handle_lock_screen` bên trong đã
    tự thử 4 hướng kéo (~20s). Retry 3 lần ở đây = 60s lãng phí khi
    `is_lock_screen` false-positive (vd. portrait buffer, RoK chưa
    foreground, Android home dim...). Vẫn khoá sau 1 lần -> dump
    screenshot ra captures/ rồi trả screen cuối để runner tiếp tục thử
    bằng logic riêng (hầu hết chores tap toạ độ % nên vẫn có cơ may).
    """
    try:
        device.keep_awake()
    except Exception:
        pass
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot thất bại")
        return None
    if not is_lock_screen(screen):
        return screen

    log.info("[việc vặt] màn khoá game -> mở khoá (1 lần)")
    try:
        handle_lock_screen(device, screen)
    except Exception:
        log.exception("[việc vặt] handler mở khoá crash")
    time.sleep(2.5)

    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot verify thất bại")
        return None
    if not is_lock_screen(screen):
        log.info("[việc vặt] đã mở khoá game")
        return screen

    save_debug_image(
        screen, getattr(device, 'serial', 'dev'),
        subdir="", prefix="chore_unlock_failed",
        label="Unlock FAILED",
    )
    log.warning("[việc vặt] vẫn khoá -> dump ảnh, runner sẽ tự tap thử")
    return screen


def _close_to_world(device: Device, max_back: int = 5) -> bool:
    """Đóng panel về world bằng BACK + nhận diện popup 'Thoát' (OCR vùng
    NHỎ, nhanh) rồi huỷ.

    KHÔNG dùng detect_state: full-image OCR trên máy này quá chậm
    (13-76s/lần). Logic: BACK từng nấc; khi BACK lố qua world thì game
    bung popup 'Thoát trò chơi?' -> bắt được popup -> chạm HUỶ -> đang ở
    world -> xong. Chỉ OCR 1 vùng nhỏ quanh nút popup mỗi nấc.
    """
    for _ in range(max_back):
        try:
            device.key("BACK")
        except Exception:
            pass
        time.sleep(1.4)
        try:
            screen = device.snapshot()
        except Exception:
            continue
        ocr.clear_cache()
        # Popup "Thoát trò chơi?": tiêu đề ở ~y46%, nút XÁC NHẬN/HỦY ở
        # ~y66%. OCR hay rớt nguyên âm ("HỦY"->"HY") nên KHÔNG bắt theo
        # "HUY"; bắt theo "thoat tro" (tiêu đề) + "xac nh" (XÁC NHẬN).
        if ocr_text_in(
            screen, (18, 38, 84, 74),
            ("thoat tro", "thoat ung", "xac nh"),
            threshold=0.5,
        ):
            log.info("[việc vặt] gặp popup Thoát -> chạm HUỶ về world")
            handle_exit_dialog(device, screen)
            time.sleep(1.5)
            return True
    log.info("[việc vặt] đóng panel xong (không gặp popup Thoát)")
    return False


def _has_red_dot(
    screen, center_pct: tuple[float, float], radius_px: int = 22,
) -> bool:
    """Có dấu chấm đỏ thông báo trong vùng quanh center không?

    Red dot RoK là chấm bão hoà đỏ (R>200, G/B<90) trên nền xanh/tối.
    Đếm pixel match — >=8 px được tính là có dot (chấm to ~12-16px).
    """
    h, w = screen.shape[:2]
    cx = int(w * center_pct[0] / 100.0)
    cy = int(h * center_pct[1] / 100.0)
    x1 = max(0, cx - radius_px)
    y1 = max(0, cy - radius_px)
    x2 = min(w, cx + radius_px)
    y2 = min(h, cy + radius_px)
    crop = screen[y1:y2, x1:x2]
    if crop.size == 0:
        return False
    b = crop[..., 0].astype(np.int16)
    g = crop[..., 1].astype(np.int16)
    r = crop[..., 2].astype(np.int16)
    mask = (r > 200) & (g < 90) & (b < 90)
    return int(mask.sum()) >= 8


def _has_xac_nhan_popup(screen) -> bool:
    """Popup "QUÀ NHẬN ĐƯỢC" đang mở -> có nút Xác nhận màu cyan ở giữa.

    Nút Xác nhận màu cyan sáng (B>180, G>140, R<170). Sample lưới 5x3
    quanh _XAC_NHAN; >=5 px cyan = popup đang hiện.
    """
    h, w = screen.shape[:2]
    cx = int(w * _XAC_NHAN[0] / 100.0)
    cy = int(h * _XAC_NHAN[1] / 100.0)
    cyan_count = 0
    for dx in (-22, -10, 0, 10, 22):
        for dy in (-12, 0, 12):
            x = cx + dx
            y = cy + dy
            if 0 <= x < w and 0 <= y < h:
                b, g, r = screen[y, x]
                if int(b) > 180 and int(g) > 140 and int(r) < 170:
                    cyan_count += 1
    return cyan_count >= 5


def _drain_xac_nhan_popups(device: Device, max_iters: int = 6) -> None:
    """Tap nút Xác nhận đến khi popup QUÀ NHẬN ĐƯỢC tắt hẳn.

    RoK gộp nhiều rương vào 1 popup nhưng nếu quá nhiều có thể bung
    nhiều popup liên tiếp. Loop snapshot + tap đến khi không còn thấy
    nút Xác nhận (theo pixel cyan). Tối đa ``max_iters`` lần để khỏi
    treo nếu detect sai.
    """
    for i in range(max_iters):
        try:
            scr = device.snapshot()
        except Exception:
            log.exception("[việc vặt] snapshot popup thất bại")
            return
        if not _has_xac_nhan_popup(scr):
            if i == 0:
                log.info("[việc vặt] không có popup Xác nhận -> bỏ qua")
            else:
                log.info(
                    "[việc vặt] popup Xác nhận đã tắt sau %d lần tap", i,
                )
            return
        log.info("[việc vặt] tap Xác nhận (%d)", i + 1)
        _tap(device, scr, _XAC_NHAN)
        time.sleep(random.uniform(1.3, 1.9))
    log.warning(
        "[việc vặt] vẫn còn popup Xác nhận sau %d lần tap -> bỏ qua",
        max_iters,
    )


def _claim_gift_tab(
    device: Device, tab_pct: tuple[float, float], tab_name: str,
) -> None:
    """Tap vào tab (Thưởng/Hiếm) -> NHẬN TẤT CẢ -> drain popup Xác nhận."""
    log.info("[việc vặt] tab %s có dấu chấm đỏ -> nhận", tab_name)
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot trước khi tap tab thất bại")
        return
    _tap(device, screen, tab_pct)
    time.sleep(random.uniform(1.2, 1.8))
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot trước NHẬN TẤT CẢ thất bại")
        return
    _tap(device, screen, _NHAN_TAT_CA)
    time.sleep(random.uniform(1.6, 2.2))
    _drain_xac_nhan_popups(device)


def do_alliance_gifts(device: Device) -> bool:
    """Mở Liên Minh -> Quà -> check red-dot từng tab -> NHẬN TẤT CẢ.

    Luồng:
      1. Mở khoá (nếu khoá), tap Liên Minh -> Quà Tặng.
      2. Snapshot panel Quà. Check 2 tab Thưởng / Hiếm theo red-dot:
         tab nào có dot -> tap tab -> NHẬN TẤT CẢ -> drain popup Xác nhận.
      3. Tap X đóng panel Quà rồi BACK về world (an toàn cho mọi state).
    """
    log.info("[việc vặt] Nhận quà liên minh")
    screen = _wake_and_unlock(device)
    if screen is None:
        return False
    screen = _ensure_alliance_button_visible(device, screen)
    _tap(device, screen, _LIEN_MINH)
    time.sleep(random.uniform(2.2, 3.0))
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot trước Quà Tặng thất bại")
        return False
    _tap(device, screen, _QUA_TANG)
    time.sleep(random.uniform(2.2, 3.0))

    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot panel Quà thất bại")
        return False

    has_thuong = _has_red_dot(screen, _DOT_THUONG)
    has_hiem = _has_red_dot(screen, _DOT_HIEM)
    log.info(
        "[việc vặt] red-dot Thưởng=%s Hiếm=%s",
        has_thuong, has_hiem,
    )
    if has_thuong:
        _claim_gift_tab(device, _TAB_THUONG, "Thưởng")
    if has_hiem:
        _claim_gift_tab(device, _TAB_HIEM, "Hiếm")
    if not (has_thuong or has_hiem):
        log.info("[việc vặt] không tab nào có quà mới -> skip nhận")

    # Đóng panel Quà bằng X góc trên-phải rồi BACK về world cho chắc.
    try:
        screen = device.snapshot()
        _tap(device, screen, _CLOSE_QUA_X)
        time.sleep(random.uniform(1.0, 1.5))
    except Exception:
        log.exception("[việc vặt] tap X đóng panel Quà thất bại")
    return _close_to_world(device)


def _is_alliance_panel(screen) -> bool:
    """Panel "LIÊN MINH" đang mở? -> icon Công Nghệ (beaker xanh dương).

    Sample lưới quanh ``_CONG_NGHE`` tìm pixel xanh đặc trưng của
    bình thí nghiệm (B>140, R<140). Khi đang ở World/City (không có
    panel), khu này hiển thị bản đồ -> pixel không khớp.
    """
    h, w = screen.shape[:2]
    cx = int(w * _CONG_NGHE[0] / 100.0)
    cy = int(h * _CONG_NGHE[1] / 100.0)
    blue = 0
    for dx in (-22, -8, 8, 22):
        for dy in (-12, 0, 12):
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                b, g, r = screen[y, x]
                if int(b) > 140 and int(r) < 140:
                    blue += 1
    return blue >= 5


def _wait_for_panel(
    device: Device, check_fn, name: str, max_wait_s: float = 6.0,
) -> bool:
    """Poll snapshot mỗi 0.6s tới khi ``check_fn(screen)`` True.

    Trả True nếu panel xuất hiện trước deadline. Trả False + log warning
    nếu hết ``max_wait_s`` mà panel chưa thấy — caller nên BACK về world
    để recover thay vì tap tiếp.
    """
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        try:
            screen = device.snapshot()
        except Exception:
            log.exception("[việc vặt] snapshot chờ %s thất bại", name)
            return False
        if check_fn(screen):
            log.info("[việc vặt] đã thấy %s", name)
            return True
        time.sleep(0.6)
    log.warning(
        "[việc vặt] không thấy %s sau %.1fs -> abort", name, max_wait_s,
    )
    return False


_OPPORTUNITY_RE = re.compile(r"(\d{1,2})\s*[/\\]\s*20")
# Vùng OCR "Cơ hội: N/20" trên panel chi tiết kỹ năng — ô nhỏ ngay trên
# cụm 2 nút TẶNG. Cố ý KHÔNG bao gồm dòng "Cơ hội tiếp theo sau HH:MM"
# (nằm dưới các nút, ~y>90%).
_OPP_REGION_PCT: tuple[float, float, float, float] = (60.0, 65.0, 95.0, 80.0)


def _read_tech_opportunities(screen) -> int | None:
    """Đọc 'Cơ hội: N/20' qua OCR — trả N hoặc None nếu fail.

    Để tránh việc PaddleOCR không nhận diện được chữ khi cắt ảnh quá nhỏ (region crop),
    chúng ta chạy OCR trên toàn bộ màn hình và lọc các kết quả nằm trong vùng _OPP_REGION_PCT.
    """
    try:
        ocr.clear_cache()
        hits = ocr.find_all(screen)
    except Exception:
        log.exception("[việc vặt] OCR Cơ hội thất bại")
        return None

    # Tính tọa độ pixel của vùng Cơ hội để lọc
    h_scr, w_scr = screen.shape[:2]
    x1 = int(w_scr * _OPP_REGION_PCT[0] / 100.0)
    y1 = int(h_scr * _OPP_REGION_PCT[1] / 100.0)
    x2 = int(w_scr * _OPP_REGION_PCT[2] / 100.0)
    y2 = int(h_scr * _OPP_REGION_PCT[3] / 100.0)

    matched_hits = []
    for h in hits:
        if x1 <= h.cx < x2 and y1 <= h.cy < y2:
            matched_hits.append(h)
            match = _OPPORTUNITY_RE.search(h.text)
            if match:
                n = int(match.group(1))
                log.info(
                    "[việc vặt] đọc Cơ hội: %d/20 (text=%r conf=%.2f)",
                    n, h.text, h.confidence,
                )
                return n

    log.info(
        "[việc vặt] không khớp pattern N/20 trong %d text lọc được",
        len(matched_hits),
    )
    return None


def _count_tech_red_px(
    screen, icon_pct: tuple[float, float],
) -> int:
    """Đếm pixel đỏ tươi trong vùng banner top-LEFT của icon kỹ năng.

    Banner ribbon đỏ tươi (R>170, G<110, B<110). Sample vùng rộng quanh
    điểm (icon_x + DX, icon_y + DY) với half-size (W, H). Trả số pixel
    đỏ — caller dùng cho cả threshold check (``>= MIN_RED``) lẫn so sánh
    giữa 6 ô để chọn ô có badge "Thiếu của sĩ quan" rõ nhất.
    """
    h, w = screen.shape[:2]
    cx = int(w * (icon_pct[0] + _TECH_HINT_DX_PCT) / 100.0)
    cy = int(h * (icon_pct[1] + _TECH_HINT_DY_PCT) / 100.0)
    x1 = max(0, cx - _TECH_HINT_HALF_W)
    y1 = max(0, cy - _TECH_HINT_HALF_H)
    x2 = min(w, cx + _TECH_HINT_HALF_W)
    y2 = min(h, cy + _TECH_HINT_HALF_H)
    crop = screen[y1:y2, x1:x2]
    if crop.size == 0:
        return 0
    b = crop[..., 0].astype(np.int16)
    g = crop[..., 1].astype(np.int16)
    r = crop[..., 2].astype(np.int16)
    mask = (r > 170) & (g < 110) & (b < 110)
    return int(mask.sum())


def _has_tech_hint(
    screen, icon_pct: tuple[float, float],
) -> bool:
    """Tile này có badge "Thiếu của sĩ quan" không (>= ngưỡng pixel đỏ)?"""
    return _count_tech_red_px(screen, icon_pct) >= _TECH_HINT_MIN_RED


def _find_tech_slot(screen) -> tuple[float, float] | None:
    """Quét cờ đỏ 'Thiếu của sĩ quan' để chọn ô kỹ năng được đề xuất.
    
    Sử dụng Template Matching trên vùng coords="454,160,1945,1026" của màn hình 2400x1080.
    Nếu không tìm thấy bằng MatchTemplate, sẽ tự động fallback sang cơ chế đếm pixel đỏ.
    """
    import cv2
    from .constants import TEMPLATES_DIR
    
    # 1. Thử nhận diện bằng Template Matching
    tpl_path = TEMPLATES_DIR / "btn_officer_recommend.png"
    tpl = cv2.imread(str(tpl_path))
    if tpl is not None:
        h_scr, w_scr = screen.shape[:2]
        # Đưa màn hình về độ phân giải chuẩn 2400x1080 để khớp hệ tọa độ tuyệt đối
        if w_scr != 2400 or h_scr != 1080:
            screen_ref = cv2.resize(screen, (2400, 1080))
        else:
            screen_ref = screen
            
        # Vùng cắt coords="454,160,1945,1026"
        crop_x1, crop_y1, crop_x2, crop_y2 = 454, 160, 1945, 1026
        crop = screen_ref[crop_y1:crop_y2, crop_x1:crop_x2]
        
        res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        
        # Ngưỡng tin cậy >= 0.75
        if max_val >= 0.75:
            match_x = crop_x1 + max_loc[0]
            match_y = crop_y1 + max_loc[1]
            
            # Khôi phục tọa độ tâm ô kỹ năng (băng rôn lệch dx=-144, dy=-118 so với tâm ô)
            detected_cx = match_x + 144
            detected_cy = match_y + 118
            
            # Map về ô gần nhất trong 6 ô tiêu chuẩn
            slots_px = [
                (int(2400 * slot[0] / 100.0), int(1080 * slot[1] / 100.0))
                for slot in _TECH_SLOTS
            ]
            
            closest_idx = -1
            min_dist = float('inf')
            for idx, (sx, sy) in enumerate(slots_px):
                dist = np.sqrt((detected_cx - sx)**2 + (detected_cy - sy)**2)
                if dist < min_dist:
                    min_dist = dist
                    closest_idx = idx
                    
            if closest_idx != -1 and min_dist < 150:
                if closest_idx == 4:  # Slot 5 ("Phòng thủ kỵ binh II")
                    # Tọa độ vùng chọn coords="1137,621,1260,740" -> tâm (1198.5, 680.5) +- 20px
                    target_x = 1198.5 + random.uniform(-20, 20)
                    target_y = 680.5 + random.uniform(-20, 20)
                    best_slot = (target_x / 2400.0 * 100.0, target_y / 1080.0 * 100.0)
                    
                    save_debug_image(
                        screen_ref, 'tech',
                        subdir="", prefix="tech_slot5_found",
                        clicks=[(int(target_x), int(target_y))],
                        rects=[(1137, 621, 1260, 740)],
                        label="Tech Slot5 TemplateMatch",
                    )

                    log.info(
                        "[việc vặt] Đã tìm thấy cờ đề xuất bằng MatchTemplate tại (%d, %d), conf: %.2f. "
                        "Khớp với ô số 5 (Phòng thủ kỵ binh II). Chạm vùng chọn coords=(1137,621) to (1260,740) "
                        "tại tâm ngẫu nhiên: (%.1f, %.1f) px (%.2f%%, %.2f%%)",
                        match_x, match_y, max_val, target_x, target_y, best_slot[0], best_slot[1]
                    )
                else:
                    best_slot = _TECH_SLOTS[closest_idx]
                    log.info(
                        "[việc vặt] Đã tìm thấy cờ đề xuất bằng MatchTemplate tại (%d, %d), conf: %.2f. "
                        "Khớp với ô số %d (%.1f, %.1f)",
                        match_x, match_y, max_val, closest_idx + 1, best_slot[0], best_slot[1]
                    )
                return best_slot
                
        log.info("[việc vặt] Không tìm thấy cờ đề xuất bằng MatchTemplate (max_val=%.2f) -> Chuyển sang quét pixel đỏ", max_val)
    else:
        log.warning("[việc vặt] Không thể tải ảnh mẫu %s -> Chuyển sang quét pixel đỏ", tpl_path)

    # 2. Fallback sang quét pixel đỏ truyền thống
    scores: list[tuple[tuple[float, float], int]] = [
        (slot, _count_tech_red_px(screen, slot)) for slot in _TECH_SLOTS
    ]
    log.info(
        "[việc vặt] điểm đỏ 6 ô Công Nghệ: %s",
        ", ".join(
            f"({s[0]:.0f},{s[1]:.0f})={n}" for s, n in scores
        ),
    )
    best_slot, best_n = max(scores, key=lambda x: x[1])
    if best_n >= _TECH_HINT_MIN_RED:
        if best_slot == _TECH_SLOTS[4]:  # Slot 5
            target_x = 1198.5 + random.uniform(-20, 20)
            target_y = 680.5 + random.uniform(-20, 20)
            best_slot = (target_x / 2400.0 * 100.0, target_y / 1080.0 * 100.0)
            
            save_debug_image(
                screen_ref, 'tech',
                subdir="", prefix="tech_slot5_found",
                clicks=[(int(target_x), int(target_y))],
                rects=[(1137, 621, 1260, 740)],
                label="Tech Slot5 Fallback",
            )

            log.info(
                "[việc vặt] hint Công Nghệ tại ô số 5 — %d px đỏ. "
                "Chạm vùng chọn coords=(1137,621) to (1260,740) tại tâm ngẫu nhiên: (%.1f, %.1f) px (%.2f%%, %.2f%%)",
                best_n, target_x, target_y, best_slot[0], best_slot[1]
            )
        else:
            log.info(
                "[việc vặt] hint Công Nghệ tại (%.1f, %.1f) — %d px đỏ",
                best_slot[0], best_slot[1], best_n,
            )
        return best_slot
    return None


def do_alliance_tech(
    device: Device, max_donate: int | None = None,
) -> bool:
    """Mở Liên Minh -> Công Nghệ -> ô có flag -> đọc Cơ hội N/20 -> tap N.

    Luồng:
      1. Mở khoá; tap Liên Minh.
         -> ``_is_alliance_panel`` (thấy icon Công Nghệ?) hoặc abort.
      2. Tap Công Nghệ -> sleep 2.5-3.5s.
      3. Quét 6 ô tìm flag đỏ "thiếu của sĩ quan"; fallback ô đầu.
         Tap ô đó -> sleep 2-3s.
      4. OCR vùng nhỏ trên panel chi tiết để đọc "Cơ hội: N/20".
         - N is None (OCR fail) -> bỏ qua góp, an toàn về world.
         - N == 0 -> hết cơ hội, đóng panel.
         - N > 0  -> tap TẶNG ``min(N, cap)`` lần (1.5-2.0s/lần).
      5. X đóng -> BACK về world.

    Tin OCR + động vào N thực tế, KHÔNG hardcode cap=20 spam mù. Cap
    chỉ là trần (vd user set cap=5 thì chỉ tap 5 dù còn 20 cơ hội).
    """
    if max_donate is None:
        cap = int(TECH_MAX_DONATE)
    else:
        cap = max(0, int(max_donate))
    log.info(
        "[việc vặt] Đóng góp công nghệ liên minh (cap %d/20)",
        cap,
    )
    screen = _wake_and_unlock(device)
    if screen is None:
        return False
    screen = _ensure_alliance_button_visible(device, screen)

    # Bước 1: vào panel Liên Minh (retry tối đa 2 lần để xử lý nếu có popup chắn).
    opened = False
    for attempt in range(2):
        _tap(device, screen, _LIEN_MINH)
        if _wait_for_panel(device, _is_alliance_panel, "panel Liên Minh", max_wait_s=3.0):
            opened = True
            break
        log.info("[việc vặt] Chưa thấy panel Liên Minh -> Thử tap lại nút Liên Minh (lần %d)", attempt + 2)
        try:
            screen = device.snapshot()
        except Exception:
            pass
            
    if not opened:
        return _close_to_world(device)

    # Bước 2: tap Công Nghệ -> sleep cho panel Kỹ năng mở (không gate,
    # màu khung vàng-cam khó phân biệt với nhiều state khác -> hay false
    # negative khiến abort oan; tin vào sleep).
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot trước Công Nghệ thất bại")
        return _close_to_world(device)
    _tap(device, screen, _CONG_NGHE)
    time.sleep(random.uniform(2.5, 3.5))

    # Bước 3: chọn ô có flag (fallback ô đầu) -> sleep cho panel chi tiết.
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot panel Kỹ năng thất bại")
        return _close_to_world(device)
    slot = _find_tech_slot(screen)
    if slot is None:
        slot = _TECH_SLOTS[0]
        log.info(
            "[việc vặt] không thấy flag -> tap ô đầu (%.1f, %.1f)",
            slot[0], slot[1],
        )
    _tap(device, screen, slot)
    time.sleep(random.uniform(2.0, 3.0))

    # Bước 4: OCR "Cơ hội: N/20" -> tap TẶNG đúng N lần (capped).
    # Snapshot 1 lần: (a) OCR đọc Cơ hội, (b) có screen.shape cho
    # pct_to_px trong loop tap. Reuse cùng screen — shape không đổi.
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot panel chi tiết thất bại")
        return _close_to_world(device)

    available = _read_tech_opportunities(screen)
    if available is None:
        log.warning(
            "[việc vặt] không đọc được Cơ hội -> bỏ qua góp (an toàn)",
        )
    elif available <= 0:
        log.info(
            "[việc vặt] Cơ hội 0/20 -> không còn gì để góp, đóng panel",
        )
    else:
        n_tap = min(available, cap)
        log.info(
            "[việc vặt] Cơ hội %d/20, cap=%d -> tap TẶNG %d lần"
            " (gap random 0.35-0.9s, chống phát hiện)",
            available, cap, n_tap,
        )
        # Gap RANDOM dưới 1s mỗi lần tap. Game flag bot khi tap quá đều
        # (vd. cố định 1.5s) -> dùng uniform(0.35, 0.9) cho mỗi tap riêng
        # biệt. Khoảng cận dưới 0.35s đủ để animation TẶNG kịp xử lý.
        for i in range(n_tap):
            _tap(device, screen, _TANG_DONATE)
            log.info("[việc vặt] TẶNG %d/%d", i + 1, n_tap)
            time.sleep(random.uniform(0.35, 0.9))
        log.info("[việc vặt] góp Công Nghệ xong: %d lần", n_tap)

    # Bước 5: X đóng panel chi tiết rồi BACK về world.
    try:
        screen = device.snapshot()
        _tap(device, screen, _CLOSE_TECH_X)
        time.sleep(random.uniform(1.0, 1.5))
    except Exception:
        log.exception("[việc vặt] tap X đóng panel Công Nghệ thất bại")
    return _close_to_world(device)


def do_alliance_territory(device: Device) -> bool:
    """Mở Liên Minh -> Lãnh Thổ -> tap NHẬN (thu tài nguyên lãnh thổ).

    Luồng NHANH (user yêu cầu tap không chần chừ):
      1. Mở khoá; tap Liên Minh -> chờ panel xuất hiện.
      2. Tap icon Lãnh Thổ -> sleep ngắn cho panel detail mở.
      3. Tap NHẬN ở header panel -> drain popup Xác nhận nếu RoK bung quà.
      4. X đóng -> BACK về world.

    So với gifts/tech (sleep 2.2-3.0s mỗi tap), territory chore dùng
    ``_tap_quick`` (pre-pause 50-300ms) và post-tap 0.8-1.4s — tổng
    luồng ~3-5s thay vì ~10s.
    """
    log.info("[việc vặt] Thu tài nguyên Lãnh Thổ liên minh")
    screen = _wake_and_unlock(device)
    if screen is None:
        return False
    screen = _ensure_alliance_button_visible(device, screen)

    # Bước 1: mở panel Liên Minh (cần gate vì wait_for_panel reuse được
    # _is_alliance_panel — detect icon Công Nghệ xanh ở row 2).
    _tap_quick(device, screen, _LIEN_MINH)
    if not _wait_for_panel(device, _is_alliance_panel, "panel Liên Minh"):
        return _close_to_world(device)

    # Bước 2: tap Lãnh Thổ -> sleep cho panel "LÃNH THỔ LIÊN MINH" mở.
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot trước Lãnh Thổ thất bại")
        return _close_to_world(device)
    _tap_quick(device, screen, _LANH_THO)
    time.sleep(random.uniform(1.2, 1.6))

    # Bước 3: tap NHẬN ở header. RoK có thể bung popup "QUÀ NHẬN ĐƯỢC"
    # khi thu RSS -> drain popup Xác nhận luôn (best-effort, không có
    # popup thì _drain_xac_nhan_popups tự return).
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("[việc vặt] snapshot trước NHẬN Lãnh Thổ thất bại")
        return _close_to_world(device)
    _tap_quick(device, screen, _NHAN_LANH_THO)
    # NHẬN territory KHÔNG bung popup "Xác nhận" — RSS bay thẳng vào kho.
    # KHÔNG gọi _drain_xac_nhan_popups: pixel-detect tại (46%, 76%) trùng
    # vị trí nút "XÂY DỰNG" trên fortress card -> false-positive sẽ tap
    # nhầm vào nó. Chỉ chờ animation xong rồi đóng panel.
    time.sleep(random.uniform(0.8, 1.2))

    # Bước 4: KHÔNG tap X (toạ độ X trong panel territory khác với
    # gift/tech panel, dễ miss). Dùng BACK key qua _close_to_world để
    # đóng panel territory -> panel alliance -> world. _close_to_world
    # tự detect popup "Thoát?" + chạm HUỶ nếu BACK lố qua world.
    return _close_to_world(device)


def _has_help_icon(screen) -> bool:
    """Có icon "bắt tay" với badge đỏ phía trên nút Liên Minh không?

    Icon chỉ float lên khi có thành viên cần assist. Phát hiện qua
    badge "N" đỏ ở góc trên-phải icon (cùng kiểu chấm đỏ thông báo,
    R>200, G/B<90). Không có badge -> không có icon -> skip im lặng.
    """
    return _has_red_dot(screen, _HELP_BADGE, radius_px=26)


def do_alliance_help(device: Device) -> bool:
    """Tap icon bắt tay phía trên Liên Minh nếu hiện (assist 1-tap).

    Icon "bắt tay" floating phía trên nút Liên Minh xuất hiện khi có
    thành viên đang xây/nghiên cứu cần giúp. Tap 1 phát = RoK auto
    batch trợ giúp tất cả (không cần mở panel). Không có icon thì
    skip — KHÔNG mở panel Liên Minh vô ích.

    Luồng:
      1. Mở khoá nếu khoá, snapshot màn World/City.
      2. Check badge đỏ tại ``_HELP_BADGE``. Không có -> log + return.
      3. Có -> tap ``_HELP_ICON`` -> ngủ 1-1.5s cho icon biến mất.
    """
    log.info("[việc vặt] Trợ giúp liên minh")
    screen = _wake_and_unlock(device)
    if screen is None:
        return False
    screen = _ensure_alliance_button_visible(device, screen)

    if not _has_help_icon(screen):
        log.info("[việc vặt] không có icon Trợ giúp -> skip")
        return True

    log.info("[việc vặt] có icon Trợ giúp -> tap (%.1f, %.1f)",
             _HELP_ICON[0], _HELP_ICON[1])
    _tap(device, screen, _HELP_ICON)
    time.sleep(random.uniform(1.0, 1.5))
    return True


_CHORES = (
    do_alliance_gifts,
    do_alliance_tech,
    do_alliance_help,
    do_alliance_territory,
)


def run_random_chore(device: Device) -> bool:
    """Chọn ngẫu nhiên 1 việc vặt, chạy, đảm bảo về world."""
    chore = random.choice(_CHORES)
    try:
        return chore(device)
    except Exception:
        log.exception("[việc vặt] crash -> cố đưa về world")
        try:
            _close_to_world(device)
        except Exception:
            pass
        return False


def chore_aware_sleep(device: Device, total_sec: float) -> None:
    """Ngủ ``total_sec`` giây, có xác suất xen 1 việc vặt ở thời điểm random.

    Thay cho 1 cú ``sleep_with_stop_check_exact`` đơn. Dùng cho pha ngủ
    chờ slot trống: ngủ một phần ngẫu nhiên -> làm việc vặt -> ngủ nốt.
    Tôn trọng cờ dừng. Import signals tại chỗ để tránh vòng phụ thuộc.
    """
    from .signals import should_stop, sleep_with_stop_check_exact

    enabled = humanize.is_enabled()
    too_short = total_sec < MIN_SLEEP_FOR_CHORE_SEC
    rolled_out = random.random() > CHORE_CHANCE
    if not enabled or too_short or rolled_out:
        # Log RÕ lý do không kèm việc vặt để theo dõi trên WebUI/log.
        if not enabled:
            reason = "humanize tắt"
        elif too_short:
            reason = f"giấc ngắn (<{MIN_SLEEP_FOR_CHORE_SEC / 60:.0f} phút)"
        else:
            reason = f"bốc thăm trượt (cơ hội {CHORE_CHANCE * 100:.0f}%)"
        log.info(
            "[việc vặt] giấc ngủ %.1f phút này KHÔNG kèm việc vặt (%s)",
            total_sec / 60.0, reason,
        )
        sleep_with_stop_check_exact(total_sec)
        return

    # Việc vặt ở 25-70% giấc ngủ, chừa đuôi tối thiểu để bot kịp ổn định.
    pre = total_sec * random.uniform(0.25, 0.70)
    chore_at = datetime.now() + timedelta(seconds=pre)
    log.info(
        "[việc vặt] sẽ làm việc vặt lúc %s"
        " (sau %.1f phút ngủ, tổng giấc %.1f phút)",
        chore_at.strftime("%H:%M:%S"), pre / 60.0, total_sec / 60.0,
    )
    sleep_with_stop_check_exact(pre)
    if should_stop():
        return

    t0 = time.monotonic()
    run_random_chore(device)
    spent = time.monotonic() - t0

    rest = max(60.0, total_sec - pre - spent)
    log.info(
        "[việc vặt] xong (mất %.0fs) -> ngủ tiếp %.1f phút",
        spent, rest / 60.0,
    )
    sleep_with_stop_check_exact(rest)


__all__ = [
    "chore_aware_sleep",
    "do_alliance_gifts",
    "do_alliance_help",
    "do_alliance_tech",
    "do_alliance_territory",
    "run_random_chore",
]
