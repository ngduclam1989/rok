"""WORLD <-> CITY navigation handlers."""
from __future__ import annotations

import difflib
import logging
import random
import time
import cv2
from pathlib import Path

import numpy as np

from core import ocr
from core.device import Device

from ..geometry import pct_to_px, region_pct_to_px, tap_template, tap_template_debug, ocr_text_in, try_template
from ..signals import pause
from ..state import StepResult
from ..capture import save_debug_image
from .network import check_and_handle_network_popup

log = logging.getLogger(__name__)

_REF_SCREEN_SIZE = (2400, 1080)
_ACCOUNT_TEXT_REGION_REF = (1192, 722, 859, 412)
_ACCOUNT_TAP_REGION_REF = (1086, 656, 954, 484)
_ACCOUNT_EMAIL_REGION_REF = (1105, 513, 638, 403)
_SWITCH_ACCOUNT_BUTTON_REGION_REF = (1082, 205, 799, 145)
_CHANGE_ACC_BUTTON_REGION_REF = (942, 561, 741, 383)
_ACCOUNT_DROPDOWN_LIST_REGION_REF = (712, 288, 1624, 979)
_ACCOUNT_LOGIN_CONFIRM_REGION_REF = (712, 281, 1599, 790)
_LOGIN_BUTTON_REGION_REF = (818, 575, 1475, 641)
_ACCOUNT_TEXT_NEEDLES = ("tai khoan", "taikhoan", "tai khon", "tai khe")
_ACCOUNTS_FILE = Path(__file__).resolve().parents[3] / "account.txt"
_USED_ACCOUNTS: set[str] = set()
_FIRST_USED_ACCOUNT: str | None = None


def reset_account_run_tracking(start_account: str | None = None) -> None:
    """Reset account traversal memory, optionally starting from one account."""
    global _FIRST_USED_ACCOUNT
    _USED_ACCOUNTS.clear()
    _FIRST_USED_ACCOUNT = None
    if start_account:
        _FIRST_USED_ACCOUNT = start_account
        _USED_ACCOUNTS.add(start_account)
    log.info(
        "Reset account run tracking: first=%s used=%s",
        _FIRST_USED_ACCOUNT,
        sorted(_USED_ACCOUNTS),
    )


def _scale_ref_region(
    screen: np.ndarray,
    region_ref: tuple[int, int, int, int],
    ref_size: tuple[int, int] = _REF_SCREEN_SIZE,
) -> tuple[int, int, int, int]:
    """Scale absolute coords measured on the reference screen to this device."""
    h, w = screen.shape[:2]
    ref_w, ref_h = ref_size
    x1, y1, x2, y2 = region_ref
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    sx1 = max(0, min(w, int(w * left / ref_w)))
    sy1 = max(0, min(h, int(h * top / ref_h)))
    sx2 = max(0, min(w, int(w * right / ref_w)))
    sy2 = max(0, min(h, int(h * bottom / ref_h)))
    return sx1, sy1, sx2, sy2


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
    
    region_px = region_pct_to_px(screen, region_pct)
    try:
        pos = device.find_template_in(
            "btn_kinh_luc.png", screen, 0.50, region=region_px,
        )
    except FileNotFoundError:
        pos = None
    if pos is None:
        log.warning("Không tìm thấy kính lúp trong vùng %s -> không làm gì cả", region_pct)
        return StepResult(False, "thiếu kính lúp", sleep_after=1.5)

    x, y = pos
    log.info(
        "Tìm thấy kính lúp trong vùng %s -> chạm đúng template tại @(%d,%d)",
        region_pct, x, y,
    )
    device.tap(x, y)
    return StepResult(True, f"đã mở bảng tìm kiếm (chạm @({x},{y}))", sleep_after=1.5)


def _open_settings_screen(device: Device, flow_name: str) -> np.ndarray | None:
    """Open Avatar -> Settings and return the settings screen."""
    log.info("Đang đợi 10s cho các đạo quân ổn định trước khi %s...", flow_name)
    pause(10.0)

    try:
        screen = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình để tìm Avatar")
        return None

    # 1. Quét tìm và chạm nút Avatar
    log.info("Đang scan khu vực góc trên bên trái màn hình tìm btn_avatar.png...")
    pos = tap_template_debug(
        device, screen, "btn_avatar.png", 0.55,
        region_pct=(0, 0, 10, 10),
    )
    if pos is None:
        log.warning("Không tìm thấy template btn_avatar.png ở góc trên bên trái")
        return None

    log.info("Tìm thấy Avatar -> Đã chạm để mở bảng thông tin người chơi. Chờ ổn định 5s...")
    pause(5.0)

    # 2. Quét tìm và chạm nút Cài đặt
    try:
        screen_profile = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình sau khi chạm Avatar")
        return None

    log.info("Tìm nút Cài đặt theo template hình ảnh trong vùng (65, 75, 100, 100)...")
    pos_settings = tap_template_debug(
        device, screen_profile, "btn_cai_dat.png", 0.5,
        region_pct=(65, 75, 100, 100),
    )
    if pos_settings is None:
        log.warning("Không tìm thấy nút Cài đặt theo hình ảnh trong vùng quét!")
        return None

    log.info("Đã tìm thấy và chạm nút Cài đặt tại: %r. Chờ ổn định giao diện Cài đặt trong 5s...", pos_settings)
    pause(5.0)

    try:
        return device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình trong giao diện Cài đặt")
        return None


def _open_character_menu(device: Device, flow_name: str) -> np.ndarray | None:
    """Open Avatar -> Settings -> Character and return the character screen."""
    screen_settings = _open_settings_screen(device, flow_name)
    if screen_settings is None:
        return None

    # 3. Quét tìm và chạm nút Nhân vật
    log.info("Tìm nút Nhân vật theo template hình ảnh trong vùng (20, 20, 60, 60)...")
    pos_char = tap_template_debug(
        device, screen_settings, "btn_nhan_vat.png", 0.5,
        region_pct=(20, 20, 60, 60),
    )
    if pos_char is None:
        log.warning("Không tìm thấy nút Nhân vật theo hình ảnh trong vùng quét!")
        return None

    log.info("Đã tìm thấy và chạm nút Nhân vật tại: %r. Chờ 10s...", pos_char)
    pause(10.0)

    # Chụp ảnh màn hình mới sau khi chạm Nhân vật và chờ 10s
    try:
        return device.snapshot()
    except Exception as e:
        log.warning("Realtime: Không chụp được ảnh màn hình sau chạm Nhân vật: %s", e)
        return None


def _log_next_screen_ocr(screen: np.ndarray, min_confidence: float = 0.45) -> None:
    hits = [hit for hit in ocr.find_all(screen) if hit.confidence >= min_confidence]
    if not hits:
        log.warning("OCR màn tiếp theo không đọc được chữ nào với confidence >= %.2f", min_confidence)
        return
    summary = "; ".join(
        f"{hit.text!r}@({hit.cx},{hit.cy})/{hit.confidence:.2f}"
        for hit in hits
    )
    log.info("OCR màn tiếp theo đọc được: %s", summary)


def _normalize_account_text(text: str) -> str:
    normalized = ocr.strip_diacritics(text).lower().replace(" ", "").strip()
    if normalized.endswith(".con"):
        normalized = normalized[:-4] + ".com"
    return normalized


def _load_known_accounts() -> list[str]:
    try:
        return [
            line.strip()
            for line in _ACCOUNTS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as err:
        log.warning("Không đọc được account.txt để map tài khoản: %s", err)
        return []


def _map_ocr_to_known_account(ocr_text: str, accounts: list[str]) -> tuple[str | None, float]:
    normalized_ocr = _normalize_account_text(ocr_text)
    best_account: str | None = None
    best_ratio = 0.0
    for account in accounts:
        normalized_account = _normalize_account_text(account)
        if normalized_ocr == normalized_account:
            return account, 1.0
        ratio = difflib.SequenceMatcher(None, normalized_ocr, normalized_account).ratio()
        if ratio > best_ratio:
            best_account = account
            best_ratio = ratio
    if best_ratio >= 0.94:
        return best_account, best_ratio
    return None, best_ratio


def _map_ocr_to_known_account_strict(ocr_text: str, accounts: list[str]) -> str | None:
    matched, score = _map_ocr_to_known_account(ocr_text, accounts)
    if matched is not None and score >= 0.94:
        return matched
    return None


def _mark_account_used(account: str, accounts: list[str]) -> list[str]:
    global _FIRST_USED_ACCOUNT
    if _FIRST_USED_ACCOUNT is None:
        _FIRST_USED_ACCOUNT = account
    _USED_ACCOUNTS.add(account)
    remaining = _remaining_accounts(accounts)
    log.info("Danh sách tài khoản đã sử dụng tạm: %s", sorted(_USED_ACCOUNTS))
    log.info("Tài khoản đầu tiên trong used: %s", _FIRST_USED_ACCOUNT)
    log.info("Danh sách tài khoản còn phải mở (%d): %s", len(remaining), remaining)
    return remaining


def _account_run_order(accounts: list[str]) -> list[str]:
    if not accounts:
        return []
    # Nếu account đầu tiên phát hiện là account cuối danh sách thì đi ngược
    # lam1999 -> ... -> lam6. Các trường hợp còn lại, kể cả account giữa,
    # đi xuôi từ lam6 -> ... -> lam1999.
    if _FIRST_USED_ACCOUNT == accounts[-1]:
        return list(reversed(accounts))
    return list(accounts)


def _remaining_accounts(accounts: list[str]) -> list[str]:
    return [item for item in _account_run_order(accounts) if item not in _USED_ACCOUNTS]


def _tap_random_ref_region(
    device: Device,
    screen: np.ndarray,
    region_ref: tuple[int, int, int, int],
    label: str,
) -> tuple[int, int]:
    x1, y1, x2, y2 = _scale_ref_region(screen, region_ref)
    tap_x = random.randint(x1, max(x1, x2 - 1))
    tap_y = random.randint(y1, max(y1, y2 - 1))
    log.info("Chạm random %s trong vùng %r -> (%d,%d)", label, region_ref, tap_x, tap_y)
    device.tap(tap_x, tap_y)
    return tap_x, tap_y


def _tap_center_jitter(
    device: Device,
    x: int,
    y: int,
    label: str,
    jitter: int = 5,
) -> tuple[int, int]:
    tap_x = x + random.randint(-jitter, jitter)
    tap_y = y + random.randint(-jitter, jitter)
    log.info("Chạm %s quanh điểm (%d,%d) +- %dpx -> (%d,%d)", label, x, y, jitter, tap_x, tap_y)
    device.tap(tap_x, tap_y)
    return tap_x, tap_y


def _tap_ocr_hit_center(
    device: Device,
    hit,
    label: str,
    jitter: int = 8,
) -> tuple[int, int]:
    """Tap near an OCR hit center; safer than a wide static region for menu rows."""
    return _tap_center_jitter(device, int(hit.cx), int(hit.cy), label, jitter=jitter)


def _tap_settings_tile_from_label(
    device: Device,
    screen: np.ndarray,
    hit,
    label: str,
) -> tuple[int, int]:
    h, _ = screen.shape[:2]
    icon_offset = max(90, int(h * 0.13))
    target_y = max(0, int(hit.cy) - icon_offset)
    return _tap_center_jitter(device, int(hit.cx), target_y, label, jitter=8)


def _tap_template_with_center_jitter(
    device: Device,
    screen: np.ndarray,
    template_name: str,
    region_ref: tuple[int, int, int, int],
    threshold: float = 0.7,
) -> bool:
    region_px = _scale_ref_region(screen, region_ref)
    try:
        pos = device.find_template_in(template_name, screen, threshold=threshold, region=region_px)
    except FileNotFoundError:
        log.error("Thiếu template: %s", template_name)
        return False
    except Exception as err:
        log.warning("Lỗi khi tìm template %s trong vùng %r: %s", template_name, region_ref, err)
        return False

    if pos is None:
        log.warning("Không tìm thấy template %s trong vùng coords=%r", template_name, region_ref)
        return False

    jitter = 5
    tap_x = pos[0] + random.randint(-jitter, jitter)
    tap_y = pos[1] + random.randint(-jitter, jitter)
    log.info(
        "Tìm thấy template %s tại %r. Chạm random quanh tâm +- %dpx -> (%d,%d)",
        template_name,
        pos,
        jitter,
        tap_x,
        tap_y,
    )
    device.tap(tap_x, tap_y)
    return True


def _select_account_from_dropdown(
    device: Device,
    screen: np.ndarray,
    target_accounts: list[str],
    label: str,
) -> str | None:
    accounts = _load_known_accounts()
    if not target_accounts:
        log.info("Không có tài khoản mục tiêu để chọn trong dropdown.")
        return None

    region_px = _scale_ref_region(screen, _ACCOUNT_DROPDOWN_LIST_REGION_REF)
    hits = [hit for hit in ocr.find_all(screen, region=region_px) if hit.confidence >= 0.45]
    visible_by_account: dict[str, list] = {}
    for hit in hits:
        matched_account = _map_ocr_to_known_account_strict(hit.text, accounts)
        if matched_account is None:
            continue
        visible_by_account.setdefault(matched_account, []).append(hit)

    log.info("%s theo account.txt: %s", label, target_accounts)
    log.info("Account đang thấy trên popup: %s", sorted(visible_by_account))

    for account in target_accounts:
        account_hits = visible_by_account.get(account)
        if not account_hits:
            continue
        # Nếu một account xuất hiện nhiều lần, ưu tiên dòng thấp hơn vì dòng đầu
        # có thể là ô đang chọn ở phần header của dropdown.
        hit = max(account_hits, key=lambda item: item.cy)
        log.info(
            "Chọn account remaining đầu tiên thấy được: %s, OCR=%r, bbox=(%d,%d,%d,%d), center=(%d,%d)",
            account,
            hit.text,
            hit.x1,
            hit.y1,
            hit.x2,
            hit.y2,
            hit.cx,
            hit.cy,
        )
        _tap_center_jitter(device, hit.cx, hit.cy, f"account {account}", jitter=5)
        return account

    log.warning("Không tìm thấy account nào thuộc %s trong vùng dropdown coords=%r", label, _ACCOUNT_DROPDOWN_LIST_REGION_REF)
    return None


def _select_remaining_account_from_dropdown(device: Device, screen: np.ndarray) -> str | None:
    accounts = _load_known_accounts()
    return _select_account_from_dropdown(device, screen, _remaining_accounts(accounts), "remaining")


def _read_selected_login_account(screen: np.ndarray) -> str | None:
    accounts = _load_known_accounts()
    region_px = _scale_ref_region(screen, _ACCOUNT_LOGIN_CONFIRM_REGION_REF)
    hits = [hit for hit in ocr.find_all(screen, region=region_px) if hit.confidence >= 0.45]
    for hit in hits:
        matched_account = _map_ocr_to_known_account_strict(hit.text, accounts)
        if matched_account is not None:
            log.info(
                "Màn xác nhận login đang chọn account: %s (OCR=%r, score>=0.94)",
                matched_account,
                hit.text,
            )
            return matched_account
    log.warning("Không đọc được account đã chọn trong vùng coords=%r", _ACCOUNT_LOGIN_CONFIRM_REGION_REF)
    return None


def _confirm_selected_account_and_login(
    device: Device,
    screen: np.ndarray,
    expected_account: str,
) -> bool:
    selected_account = _read_selected_login_account(screen)
    if selected_account != expected_account:
        log.warning(
            "Account trên màn login không khớp expected. expected=%s selected=%s",
            expected_account,
            selected_account,
        )
        return False
    _tap_random_ref_region(device, screen, _LOGIN_BUTTON_REGION_REF, "nút Đăng nhập")
    return True


def _tap_switch_account_by_ocr(device: Device, screen: np.ndarray) -> bool:
    hits = ocr.find_all(screen)
    for hit in hits:
        if hit.confidence < 0.55:
            continue
        text = ocr.strip_diacritics(hit.text).lower().replace(" ", "")
        if (
            "chuyentaikhoan" in text
            or "chuyentaikhon" in text
            or "chuyntaikhon" in text
            or "chuyntaikhoan" in text
        ):
            log.info(
                "Tìm thấy chữ Chuyển tài khoản '%s' tại (%d,%d). Chạm theo tâm OCR.",
                hit.text,
                hit.cx,
                hit.cy,
            )
            _tap_ocr_hit_center(device, hit, "chữ Chuyển tài khoản", jitter=8)
            return True
    return False


def _looks_like_settings_screen(screen: np.ndarray) -> bool:
    region_px = _scale_ref_region(screen, _ACCOUNT_TEXT_REGION_REF)
    for hit in ocr.find_all(screen, region=region_px):
        if hit.confidence < 0.55:
            continue
        text = ocr.strip_diacritics(hit.text).lower()
        if any(needle in text for needle in _ACCOUNT_TEXT_NEEDLES):
            log.info(
                "Xác nhận đang ở màn Cài đặt qua OCR mục Tài khoản: '%s' tại (%d,%d)",
                hit.text,
                hit.cx,
                hit.cy,
            )
            return True
    return False


def _log_current_account_mapping(screen: np.ndarray) -> str | None:
    region_px = _scale_ref_region(screen, _ACCOUNT_EMAIL_REGION_REF)
    hits = [hit for hit in ocr.find_all(screen, region=region_px) if hit.confidence >= 0.45]
    if not hits:
        log.warning("Không OCR được e-mail tài khoản trong vùng coords=%r", _ACCOUNT_EMAIL_REGION_REF)
        return None

    ocr_text = " ".join(hit.text for hit in hits)
    accounts = _load_known_accounts()
    matched_account, score = _map_ocr_to_known_account(ocr_text, accounts)
    if matched_account:
        log.info(
            "OCR e-mail tài khoản: %r -> map với account.txt: %s (score=%.3f)",
            ocr_text,
            matched_account,
            score,
        )
        _mark_account_used(matched_account, accounts)
        return matched_account
    else:
        log.warning(
            "OCR e-mail tài khoản: %r nhưng chưa map được account.txt (best_score=%.3f)",
            ocr_text,
            score,
        )
    return None


def _switch_from_account_center(
    device: Device,
    screen: np.ndarray,
    matched_account: str,
    *,
    wrap_to_first: bool,
    force_target_accounts: list[str] | None = None,
    forced_result: str = "wrapped",
) -> str:
    accounts = _load_known_accounts()
    if force_target_accounts is not None:
        target_accounts = force_target_accounts
        result_after_login = forced_result
        if target_accounts and matched_account == target_accounts[0]:
            log.info(
                "Da dung san o account muc tieu (%s). Khong can switch lai.",
                matched_account,
            )
            reset_account_run_tracking(matched_account)
            return result_after_login
    else:
        remaining_accounts = _remaining_accounts(accounts)
        if remaining_accounts:
            target_accounts = remaining_accounts
            result_after_login = "switched"
        else:
            if not wrap_to_first:
                log.info(
                    "Account hien tai la account cuoi trong thu tu chay. "
                    "Khong wrap ve account dau; giu nguyen account hien tai: %s",
                    matched_account,
                )
                reset_account_run_tracking(matched_account)
                return "done"
            if accounts and matched_account == accounts[0]:
                log.info(
                    "Da dung san o account dau tien trong account.txt (%s). Khong can switch lai.",
                    matched_account,
                )
                reset_account_run_tracking(matched_account)
                return "wrapped"
            target_accounts = accounts[:1]
            result_after_login = "wrapped"
            log.info(
                "Account hiện tại là account cuối. Sẽ quay về account đầu tiên trong account.txt: %s",
                target_accounts[0] if target_accounts else None,
            )
    if not _tap_switch_account_by_ocr(device, screen):
        _tap_random_ref_region(
            device,
            screen,
            _SWITCH_ACCOUNT_BUTTON_REGION_REF,
            "nút Chuyển tài khoản",
        )
    wait_after_switch_tap = random.uniform(5.0, 10.0)
    log.info("Đã chạm Chuyển tài khoản, chờ %.2fs để chuyển màn...", wait_after_switch_tap)
    time.sleep(wait_after_switch_tap)
    try:
        switch_screen = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình sau khi chạm Chuyển tài khoản")
        return "failed"
    if not _tap_template_with_center_jitter(
        device,
        switch_screen,
        "btn_change_acc.png",
        _CHANGE_ACC_BUTTON_REGION_REF,
        threshold=0.7,
    ):
        return "failed"
    wait_after_dropdown_tap = random.uniform(2.0, 4.0)
    log.info("Đã chạm mở danh sách account, chờ %.2fs để đọc dropdown...", wait_after_dropdown_tap)
    time.sleep(wait_after_dropdown_tap)
    try:
        dropdown_screen = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình dropdown tài khoản")
        return "failed"
    selected_account = _select_account_from_dropdown(
        device,
        dropdown_screen,
        target_accounts,
        "account mục tiêu",
    )
    if selected_account is None:
        return "failed"
    log.info("Đã chọn account còn lại: %s", selected_account)
    wait_after_account_select = random.uniform(3.0, 6.0)
    log.info("Chờ %.2fs để màn login cập nhật account đã chọn...", wait_after_account_select)
    time.sleep(wait_after_account_select)
    try:
        login_screen = device.snapshot()
    except Exception:
        log.exception("Không chụp được màn hình xác nhận login sau khi chọn account")
        return "failed"
    if not _confirm_selected_account_and_login(device, login_screen, selected_account):
        return "failed"
    if result_after_login == "wrapped":
        reset_account_run_tracking(selected_account)
    return result_after_login


def handle_switch_account(device: Device, *, wrap_to_first: bool = True) -> str:
    """Mở luồng chuyển tài khoản đến bước Avatar -> Cài đặt -> Tài khoản."""
    screen_settings = _open_settings_screen(device, "chuyển tài khoản")
    if screen_settings is None:
        try:
            current_screen = device.snapshot()
        except Exception:
            log.exception("Không chụp được màn hình để kiểm tra recovery Cài đặt")
            return "failed"
        if _looks_like_settings_screen(current_screen):
            log.info("Luồng chuyển tài khoản: đang ở sẵn màn Cài đặt, tiếp tục thay vì fail.")
            screen_settings = current_screen
        else:
            matched_account = _log_current_account_mapping(current_screen)
            if matched_account is not None:
                log.info("Luồng chuyển tài khoản: đang ở sẵn Trung Tâm Người Dùng, tiếp tục từ email hiện tại.")
                return _switch_from_account_center(
                    device,
                    current_screen,
                    matched_account,
                    wrap_to_first=wrap_to_first,
                )
            return "failed"

    region_px = _scale_ref_region(screen_settings, _ACCOUNT_TEXT_REGION_REF)
    log.info(
        "Tìm chữ Tài khoản bằng OCR trong vùng coords=%r -> %r...",
        _ACCOUNT_TEXT_REGION_REF,
        region_px,
    )
    hits = ocr.find_all(screen_settings, region=region_px)
    for hit in hits:
        if hit.confidence < 0.55:
            continue
        text = ocr.strip_diacritics(hit.text).lower()
        if any(needle in text for needle in _ACCOUNT_TEXT_NEEDLES):
            log.info(
                "Tìm thấy chữ Tài khoản '%s' tại (%d,%d). Chạm theo tâm OCR.",
                hit.text,
                hit.cx,
                hit.cy,
            )
            _tap_settings_tile_from_label(device, screen_settings, hit, "ô Tài khoản")
            wait_sec = random.uniform(5.0, 10.0)
            log.info("Đã chạm Tài khoản, chờ %.2fs để chuyển màn...", wait_sec)
            time.sleep(wait_sec)
            try:
                next_screen = device.snapshot()
            except Exception:
                log.exception("Không chụp được màn hình tiếp theo sau khi chạm Tài khoản")
                return "failed"
            _log_next_screen_ocr(next_screen)
            matched_account = _log_current_account_mapping(next_screen)
            if matched_account is None:
                for retry_tap in range(1, 3):
                    log.warning(
                        "Chưa đọc được e-mail tài khoản sau khi tap Tài khoản. "
                        "Có thể vẫn đang ở màn Cài đặt; thử tap lại Tài khoản lần %d/2...",
                        retry_tap,
                    )
                    retry_region_px = _scale_ref_region(next_screen, _ACCOUNT_TEXT_REGION_REF)
                    retry_hits = ocr.find_all(next_screen, region=retry_region_px)
                    tapped_retry = False
                    for retry_hit in retry_hits:
                        if retry_hit.confidence < 0.55:
                            continue
                        retry_text = ocr.strip_diacritics(retry_hit.text).lower()
                        if any(needle in retry_text for needle in _ACCOUNT_TEXT_NEEDLES):
                            _tap_settings_tile_from_label(device, next_screen, retry_hit, "ô Tài khoản retry")
                            tapped_retry = True
                            break
                    if not tapped_retry:
                        log.warning("Không còn thấy chữ Tài khoản để tap lại trong vùng coords=%r", _ACCOUNT_TEXT_REGION_REF)
                        break
                    wait_retry_screen = random.uniform(5.0, 10.0)
                    log.info("Đã tap lại Tài khoản, chờ %.2fs để chuyển màn...", wait_retry_screen)
                    time.sleep(wait_retry_screen)
                    try:
                        next_screen = device.snapshot()
                    except Exception:
                        log.exception("Không chụp được màn hình sau khi tap lại Tài khoản")
                        return "failed"
                    _log_next_screen_ocr(next_screen)
                    matched_account = _log_current_account_mapping(next_screen)
                    if matched_account is not None:
                        break
                if matched_account is None:
                    return "failed"
            return _switch_from_account_center(
                device,
                next_screen,
                matched_account,
                wrap_to_first=wrap_to_first,
            )

    log.warning("Không tìm thấy chữ Tài khoản trong vùng coords=%r", _ACCOUNT_TEXT_REGION_REF)
    try:
        save_debug_image(
            screen_settings,
            device.serial,
            subdir="switch_account",
            prefix="account_text_not_found",
            rects=[region_px],
            label="Account text OCR area",
        )
    except Exception as err:
        log.warning("Không lưu được ảnh debug vùng Tài khoản: %s", err)
    return "failed"


def handle_switch_to_first_account(device: Device) -> str:
    """Switch directly to the first account in account.txt, usually lam6."""
    accounts = _load_known_accounts()
    if not accounts:
        log.warning("Khong co account nao trong account.txt de dua ve account dau")
        return "failed"

    first_account = accounts[0]
    log.info("=== Ep dua ve account dau tien trong account.txt: %s ===", first_account)
    screen_settings = _open_settings_screen(device, "dua ve account dau tien")
    if screen_settings is None:
        try:
            current_screen = device.snapshot()
        except Exception:
            log.exception("Khong chup duoc man hinh de ep ve account dau")
            return "failed"
        matched_account = _log_current_account_mapping(current_screen)
        if matched_account is not None:
            return _switch_from_account_center(
                device,
                current_screen,
                matched_account,
                wrap_to_first=True,
                force_target_accounts=[first_account],
                forced_result="wrapped",
            )
        if _looks_like_settings_screen(current_screen):
            screen_settings = current_screen
        else:
            return "failed"

    region_px = _scale_ref_region(screen_settings, _ACCOUNT_TEXT_REGION_REF)
    hits = ocr.find_all(screen_settings, region=region_px)
    for hit in hits:
        if hit.confidence < 0.55:
            continue
        text = ocr.strip_diacritics(hit.text).lower()
        if any(needle in text for needle in _ACCOUNT_TEXT_NEEDLES):
            _tap_settings_tile_from_label(device, screen_settings, hit, "o Tai khoan")
            wait_sec = random.uniform(5.0, 10.0)
            log.info("Da cham Tai khoan de ep ve account dau, cho %.2fs...", wait_sec)
            time.sleep(wait_sec)
            try:
                next_screen = device.snapshot()
            except Exception:
                log.exception("Khong chup duoc man account center")
                return "failed"
            matched_account = _log_current_account_mapping(next_screen)
            if matched_account is None:
                return "failed"
            return _switch_from_account_center(
                device,
                next_screen,
                matched_account,
                wrap_to_first=True,
                force_target_accounts=[first_account],
                forced_result="wrapped",
            )

    log.warning("Khong tim thay muc Tai khoan de ep ve account dau")
    return "failed"


def handle_switch_character(device: Device) -> bool:
    """Thực hiện chuỗi thao tác chuyển nhân vật: Avatar -> Cài đặt -> Nhân vật -> Ngôi sao -> Yes."""
    screen_post_char = _open_character_menu(device, "chuyển nhân vật")
    if screen_post_char is None:
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
    pause(5.0)

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

    log.info("Đã tìm thấy và chạm nút Yes tại: %r. Hoàn thành chuỗi chuyển nhân vật!", pos_yes)
    pause(3.0)
    return True
