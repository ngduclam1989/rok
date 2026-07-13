"""Main loop + navigation helpers + CLI entry point.

``run(device, max_iterations)`` is the public entrypoint — it sets up
signal handling, walks the state machine, and orchestrates the
dispatch / poll-for-slot / sleep cycle.
"""
from __future__ import annotations

import argparse
import logging
import random
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from core import ocr
from core.device import Device

from . import config
from .constants import CAPTURES_DIR, ROOT, STOP_FLAG, TEMPLATES_DIR
from .detection import detect_state, is_lock_screen
from .geometry import pct_to_px, region_pct_to_px, tap_template, ocr_text_in
from .handlers import (
    check_and_handle_network_popup,
    handle_build_menu,
    handle_city,
    handle_exit_dialog,
    handle_lock_screen,
    handle_march_plan,
    handle_network_error,
    handle_popup,
    handle_gems_shop,
    handle_search_panel,
    handle_tile_info,
    handle_unknown,
    handle_world,
    handle_switch_account,
    handle_switch_character,
    handle_switch_to_first_account,
    reset_slider_state,
)
from .readers import read_slot_badge
from .signals import (
    install_signal_handler,
    install_pause_hotkey,
    pause,
    register_serial,
    should_stop,
    sleep_with_stop_check,
    sleep_with_stop_check_exact,
    wait_if_paused,
)
from .state import S
from .input_lock import lock_input, unlock_input
from .capture import save_debug_image

log = logging.getLogger(__name__)


def _cleanup_captures() -> None:
    """Xóa ảnh PNG thành công trong captures/, giữ lại FAILED/UNKNOWN/FIRST_WORLD."""
    try:
        if not CAPTURES_DIR.exists():
            return
        for p in CAPTURES_DIR.glob("*.png"):
            if "FAILED" not in p.name and "UNKNOWN" not in p.name and "FIRST_WORLD" not in p.name:
                p.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Lỗi dọn dẹp ảnh captures: %s", e)


def _start_app_watchdog(device: Device, stop_event: threading.Event, interval: float = 60.0) -> threading.Thread:
    """Khởi động background thread kiểm tra app crash mỗi `interval` giây.

    Độc lập hoàn toàn với vòng lặp chính — không chờ theo vòng lặp,
    cứ đúng `interval` giây thì check một lần dù main loop đang
    làm gì. Nếu phát hiện game không chạy thì tự bật lại.
    """
    def _watchdog() -> None:
        log.info("[watchdog] Bắt đầu theo dõi app crash mỗi %.0fs.", interval)
        while not stop_event.wait(timeout=interval):
            # stop_event.wait() trả True nếu được set -> thoát
            if should_stop():
                break
            try:
                running = device.is_game_running()
            except Exception as e:
                log.warning("[watchdog] Không kiểm tra được trạng thái app: %s", e)
                continue
            if not running:
                log.warning(
                    "[watchdog] Phát hiện game KHÔNG chạy -> tự động bật lại!"
                )
                try:
                    device.start_game()
                    device._back_locked_until = 0.0
                except Exception as e:
                    log.error("[watchdog] Bật lại game thất bại: %s", e)
            else:
                log.debug("[watchdog] App đang chạy bình thường.")
        log.info("[watchdog] Dừng theo dõi app crash.")

    t = threading.Thread(target=_watchdog, name="app-watchdog", daemon=True)
    t.start()
    return t


def _read_initial_slot_badge_with_retries(device: Device, max_attempts: int = 4) -> tuple[int | None, int | None]:
    """Thử đọc huy hiệu n/N nhiều lần để đảm bảo có kết quả chính xác ngay khi vào acc/khởi động."""
    for attempt in range(max_attempts):
        try:
            screen = device.snapshot()
            ocr.clear_cache()
            n, mx = read_slot_badge(screen)
            if n is not None and mx is not None:
                log.info("Đọc thành công huy hiệu hàng đợi (lần %d): %d/%d", attempt + 1, n, mx)
                return n, mx
            log.warning("Thử đọc huy hiệu hàng đợi lần %d thất bại -> chờ 2s thử lại...", attempt + 1)
        except Exception as e:
            log.warning("Lỗi khi chụp/đọc huy hiệu lần %d: %s", attempt + 1, e)
        pause(2.0)
    return None, None


@dataclass(frozen=True)
class _BoostImageProps:
    path: str
    threshold: float = 0.70


@dataclass(frozen=True)
class _BoostAssets:
    active_buff_blue: _BoostImageProps = _BoostImageProps(
        "buffs/enhanced_gathering_blue.png",
    )
    active_buff_purple: _BoostImageProps = _BoostImageProps(
        "buffs/enhanced_gathering_purple.png",
    )
    item_blue: _BoostImageProps = _BoostImageProps(
        "items/enhanced_gathering_blue.png",
    )
    item_purple: _BoostImageProps = _BoostImageProps(
        "items/enhanced_gathering_purple.png",
    )


class _GatheringBoostAction:
    menu_pos = (2188, 983)
    dao_cu_region = (1527, 950, 1653, 1080)
    boost_tab_region = (948, 149, 1113, 159)
    use_region = (1579, 903, 1782, 959)
    close_region = (1858, 104, 1903, 143)

    def __init__(self, bot, assets: _BoostAssets | None = None) -> None:
        self.bot = bot
        self.assets = assets or _BoostAssets()

    def ensure_gathering_boost(self) -> bool:
        self.bot.back_to_map()
        self.bot.snapshot_debug("B1_before_boost_check")
        if self.has_any_active_buff():
            log.info("[boost] B1: gathering boost buff is already active.")
            return False

        log.info("[boost] B1: gathering boost is not active; opening item flow.")
        if not self.open_dao_cu_menu():
            log.info("[boost] B4: cannot find Dao Cu menu entry.")
            return False

        self.tap_random(self.dao_cu_region, jitter=10, label="B5 Dao Cu")
        self.bot.snapshot_debug("B6_after_dao_cu")
        self.tap_random(self.boost_tab_region, label="B7 boost tab")
        self.bot.snapshot_debug("B8_before_item_search")

        selected = self.find_first_available_item(
            [self.assets.item_blue, self.assets.item_purple],
        )
        if selected is None:
            log.info("[boost] B8: no item found, retry B7 once and scan again.")
            self.tap_random(self.boost_tab_region, label="B7 retry boost tab")
            self.bot.snapshot_debug("B8_retry_before_item_search")
            selected = self.find_first_available_item(
                [self.assets.item_blue, self.assets.item_purple],
            )
        if selected is None:
            log.info("[boost] B8 retry: still no enhanced gathering item found.")
            self.tap_random(self.close_region, label="B8 no item -> close")
            self.bot.snapshot_debug("B8_no_item_after_close")
            return False

        _item_image, item_pos = selected
        x = item_pos[0] + random.randint(-20, 20)
        y = item_pos[1] + random.randint(-20, 20)
        log.info("[boost] B9: tap item at (%d,%d) from center %s.", x, y, item_pos)
        self.bot.tap(x, y, sleep_time=1.0)
        self.bot.snapshot_debug("B9_after_item_tap")

        self.tap_random(self.use_region, label="B10 use")
        self.bot.snapshot_debug("B10_after_use")
        self.tap_random(self.close_region, label="B11 close")
        self.bot.snapshot_debug("B11_after_close")

        active_after = self.has_any_active_buff()
        log.info("[boost] B11: active buff after use=%s.", active_after)
        return active_after

    def has_any_active_buff(self) -> bool:
        return self.has_buff(self.assets.active_buff_blue) or self.has_buff(
            self.assets.active_buff_purple,
        )

    def has_buff(self, buff_image: _BoostImageProps) -> bool:
        found, pos = self.bot.check_any(buff_image)
        log.info("[boost] B1: check %s found=%s pos=%s.", buff_image.path, found, pos)
        return found

    def open_dao_cu_menu(self) -> bool:
        if self.is_dao_cu_visible():
            log.info("[boost] B2: Dao Cu already visible.")
            return True
        log.info("[boost] B3: Dao Cu not visible; tap menu at %s.", self.menu_pos)
        self.bot.tap(*self.menu_pos, sleep_time=1.0)
        self.bot.snapshot_debug("B3_after_menu_tap")
        matched = self.is_dao_cu_visible()
        log.info("[boost] B4: Dao Cu visible after menu=%s.", matched)
        return matched

    def is_dao_cu_visible(self) -> bool:
        for hit in self.bot.read_ocr(self.dao_cu_region):
            text = ocr.strip_diacritics(hit.text).lower().strip()
            compact = text.replace(" ", "")
            matched = ("daocu" in compact or "doc" in compact) and hit.confidence >= 0.5
            log.info(
                "[boost] B2/B4 OCR text=%r norm=%r conf=%.3f center=(%d,%d) matched=%s.",
                hit.text,
                text,
                hit.confidence,
                hit.cx,
                hit.cy,
                matched,
            )
            if matched:
                return True
        return False

    def find_first_available_item(
        self,
        item_images: list[_BoostImageProps],
    ) -> tuple[_BoostImageProps, tuple[int, int]] | None:
        for item_image in item_images:
            found, item_pos = self.bot.check_any(item_image)
            log.info("[boost] B8: check %s found=%s pos=%s.", item_image.path, found, item_pos)
            if found and item_pos is not None:
                return item_image, item_pos
        return None

    def tap_random(
        self,
        region: tuple[int, int, int, int],
        *,
        jitter: int | None = None,
        label: str,
    ) -> None:
        x1, y1, x2, y2 = self.normalize_rect(region)
        if jitter is None:
            x = random.randint(x1, x2)
            y = random.randint(y1, y2)
        else:
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            x = cx + random.randint(-jitter, jitter)
            y = cy + random.randint(-jitter, jitter)
        log.info("[boost] %s: tap (%d,%d) in region %s.", label, x, y, (x1, y1, x2, y2))
        self.bot.tap(x, y, sleep_time=1.0)

    @staticmethod
    def normalize_rect(region: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = region
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


class _GatheringBoostDeviceAdapter:
    def __init__(self, device: Device) -> None:
        self.device = device
        self.assets_root = TEMPLATES_DIR / "gathering_boost"

    def back_to_map(self) -> None:
        _prepare_world_only(self.device)

    def tap(self, x: float, y: float, sleep_time: float = 0.1) -> None:
        self.device.tap(int(round(x)), int(round(y)))
        pause(float(sleep_time))

    def check_any(self, image_props) -> tuple[bool, tuple[int, int] | None]:
        screen = self.device.snapshot()
        match = self._find_export_template(screen, image_props.path)
        if match is None:
            log.info("[boost] Template %s khong doc duoc/khong match", image_props.path)
            return False, None

        confidence, scale, center, size = match
        found = confidence >= float(getattr(image_props, "threshold", 0.70))
        log.info(
            "[boost] Match %s found=%s conf=%.3f scale=%.3f center=%s size=%s",
            image_props.path,
            found,
            confidence,
            scale,
            center,
            size,
        )
        save_debug_image(
            screen,
            self.device.serial,
            subdir="gathering_boost",
            prefix="boost_match",
            clicks=[center],
            label=f"{image_props.path} conf={confidence:.3f}",
        )
        return found, center if found else None

    def read_ocr(self, region) -> list:
        screen = self.device.snapshot()
        hits = ocr.find_all(screen, region=tuple(region))
        save_debug_image(
            screen,
            self.device.serial,
            subdir="gathering_boost",
            prefix="boost_ocr",
            rects=[tuple(region)],
            label="Boost OCR Dao Cu",
        )
        return hits

    def snapshot_debug(self, label: str) -> None:
        try:
            screen = self.device.snapshot()
        except Exception:
            log.exception("[boost] Snapshot debug failed: %s", label)
            return
        save_debug_image(
            screen,
            self.device.serial,
            subdir="gathering_boost",
            prefix="boost",
            label=label,
        )

    def _find_export_template(
        self,
        screen: np.ndarray,
        rel_path: str,
    ) -> tuple[float, float, tuple[int, int], tuple[int, int]] | None:
        path = self.assets_root / rel_path
        tpl = cv2.imread(str(path))
        if tpl is None:
            log.warning("[boost] Khong doc duoc template: %s", path)
            return None

        th, tw = tpl.shape[:2]
        sh, sw = screen.shape[:2]
        scales = []
        for base in (
            1.0,
            sw / 1280.0,
            sh / 720.0,
            min(sw / 1280.0, sh / 720.0),
            max(sw / 1280.0, sh / 720.0),
        ):
            for mul in (0.65, 0.75, 0.85, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5):
                scales.append(base * mul)

        best = None
        seen = set()
        for scale in scales:
            key = round(scale, 3)
            if key in seen:
                continue
            seen.add(key)
            if abs(scale - 1.0) > 0.01:
                scaled = cv2.resize(
                    tpl,
                    (max(1, int(tw * scale)), max(1, int(th * scale))),
                )
            else:
                scaled = tpl
            h, w = scaled.shape[:2]
            if h > sh or w > sw:
                continue
            result = cv2.matchTemplate(screen, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            center = (int(max_loc[0] + w // 2), int(max_loc[1] + h // 2))
            current = (float(max_val), float(scale), center, (w, h))
            if best is None or current[0] > best[0]:
                best = current
        return best


def _ensure_gathering_boost(device: Device) -> bool:
    action = _GatheringBoostAction(
        _GatheringBoostDeviceAdapter(device),
    )
    return action.ensure_gathering_boost()


def _has_gathering_boost(device: Device) -> bool:
    adapter = _GatheringBoostDeviceAdapter(device)
    assets = _BoostAssets()
    return adapter.check_any(assets.active_buff_blue)[0] or adapter.check_any(
        assets.active_buff_purple
    )[0]


def _claim_vip(device: Device) -> None:
    log.info("=== Bắt đầu hành trình VIP/Boost ===")
    _prepare_world_only(device)

    if _has_gathering_boost(device):
        log.info(
            "Đã có gathering boost active -> bỏ qua nhận VIP và bỏ qua mở boost. Kết thúc hành trình VIP/Boost.",
        )
        return

    actions = [
        ("vip", lambda: _claim_vip_only(device)),
        ("boost", lambda: _ensure_gathering_boost(device)),
    ]
    random.shuffle(actions)
    log.info("Chưa có gathering boost -> thứ tự chạy VIP/Boost: %s", [name for name, _ in actions])
    for name, action in actions:
        log.info("Bắt đầu action VIP/Boost: %s", name)
        try:
            action()
        except Exception:
            log.exception("Action VIP/Boost %s lỗi", name)
        _prepare_world_only(device)
    log.info("=== Hoàn thành hành trình VIP/Boost ===")


def _claim_vip_only(device: Device) -> None:
    log.info("=== Bắt đầu nhận điểm và rương VIP hàng ngày ===")
    try:
        # 1. Đảm bảo ở màn hình CITY
        screen = device.snapshot()
        state = detect_state(device, screen)
        if state == S.WORLD:
            log.info("Đang ở WORLD -> bấm nút chuyển sang CITY")
            region_px = region_pct_to_px(screen, (0, 80, 15, 100))
            pos = device.find_template_in("btn_map_toggle.png", screen, 0.75, region=region_px)
            if pos is not None:
                device.tap(*pos)
            else:
                h, w = screen.shape[:2]
                device.tap(int(w * 0.06), int(h * 0.912))
            pause(2.5)
            screen = device.snapshot()
            state = detect_state(device, screen)

        if state != S.CITY:
            log.warning("Không ở màn hình CITY (trạng thái: %s) -> đưa về world rồi sang city", state.value)
            _return_to_world(device, max_attempts=4)
            screen = device.snapshot()
            region_px = region_pct_to_px(screen, (0, 80, 15, 100))
            pos = device.find_template_in("btn_map_toggle.png", screen, 0.75, region=region_px)
            if pos is not None:
                device.tap(*pos)
            else:
                h, w = screen.shape[:2]
                device.tap(int(w * 0.06), int(h * 0.912))
            pause(2.5)

        # 2. Click VIP với tọa độ ngẫu nhiên dựa trên vùng (151, 81) -> (236, 110)
        # On real 2340x1080 phones the old area (151, 81)-(236, 110)
        # opens the governor profile; the VIP badge is lower/right.
        vip_area = (205, 100, 305, 145)
        center_x = (vip_area[0] + vip_area[2]) // 2
        center_y = (vip_area[1] + vip_area[3]) // 2
        vip_pos = (center_x + random.randint(-10, 10), center_y + random.randint(-10, 10))
        
        vip_point_chest = (1767 + random.randint(-10, 10), 268 + random.randint(-10, 10))
        vip_free_chest = (1650 + random.randint(-10, 10), 540 + random.randint(-10, 10))

        log.info("Mở giao diện VIP tại %s (vùng %s)", vip_pos, vip_area)
        screen = device.snapshot()
        if screen is not None:
            save_debug_image(screen, device.serial, subdir="vip_claims", prefix="vip",
                             clicks=[vip_pos], rects=[vip_area], label="Mo Giao Dien VIP")
        device.tap(*vip_pos)
        pause(2.0)

        # Định nghĩa vùng OCR dạng % để tương thích mọi độ phân giải màn hình
        vip_point_region = (70.0, 20.0, 82.0, 32.0)
        vip_free_region = (64.0, 45.0, 76.0, 60.0)

        log.info("Kiểm tra nút nhận điểm VIP và rương VIP miễn phí hàng ngày...")
        screen = device.snapshot()
        if screen is not None:
            vip_point_region_px = region_pct_to_px(screen, vip_point_region)
            vip_free_region_px = region_pct_to_px(screen, vip_free_region)
            log.info(
                "Vung OCR chu NHAN VIP: diem=%s, ruong=%s",
                vip_point_region_px,
                vip_free_region_px,
            )
            save_debug_image(
                screen,
                device.serial,
                subdir="vip_claims",
                prefix="vip",
                rects=[vip_point_region_px, vip_free_region_px],
                label="OCR NHAN VIP",
            )
            nhan_needles = ("nhan", "nhn")
            has_point_nhan = ocr_text_in(screen, vip_point_region, nhan_needles)
            has_free_nhan = ocr_text_in(screen, vip_free_region, nhan_needles)
            
            if has_point_nhan or has_free_nhan:
                log.info("Phát hiện chữ NHẬN (điểm VIP: %s, rương VIP: %s) -> tiến hành nhận cả hai chỗ", has_point_nhan, has_free_nhan)
                
                # Nhận điểm VIP
                save_debug_image(screen, device.serial, subdir="vip_claims", prefix="vip",
                                 clicks=[vip_point_chest], label="Nhan Diem VIP")
                device.tap(*vip_point_chest)
                pause(5.0)
                device.tap(*vip_point_chest)
                pause(1.0)
                
                # Nhận rương VIP miễn phí
                log.info("Tiến hành nhận rương VIP miễn phí tại %s", vip_free_chest)
                save_debug_image(screen, device.serial, subdir="vip_claims", prefix="vip",
                                 clicks=[vip_free_chest], label="Nhan Ruong VIP Mien Phi")
                device.tap(*vip_free_chest)
                pause(1.0)
            else:
                log.info("Không phát hiện chữ NHẬN ở cả hai vùng điểm VIP và rương VIP -> bỏ qua nhận VIP")

        log.info("Thoát giao diện VIP về lại màn hình chính")
        closed_with_x = False
        screen = device.snapshot()
        if screen is not None:
            h, w = screen.shape[:2]
            vip_close_pos = (int(w * 0.79), int(h * 0.115))
            log.info("Dong giao dien VIP bang nut X tai %s", vip_close_pos)
            device.tap(*vip_close_pos)
            pause(0.8)
            closed_with_x = True
        if not closed_with_x:
            device.key("BACK")
        pause(1.5)
        log.info("=== Hoàn thành nhận VIP ===")
    except Exception as e:
        log.exception("Lỗi khi thực hiện nhận VIP: %s", e)


def _build_randomized_workflows() -> list[str]:
    """Create the per-character workflow list.

    Farm is shuffled together with every individual chore action so each
    account/character runs the same required actions in a different order.
    """
    workflows = [
        "farm",
        "getres",
        "alliance_help",
        "alliance_gifts",
        "alliance_territory",
        "alliance_tech",
    ]
    if getattr(config, "ENABLE_VIP_CLAIM", False):
        workflows.append("vip_boost")
    random.shuffle(workflows)
    return workflows


_WORKFLOW_LABELS = {
    "farm": "farm",
    "getres": "lay tai nguyen noi thanh",
    "alliance_help": "tro giup lien minh",
    "alliance_gifts": "nhan qua lien minh",
    "alliance_territory": "thu tai nguyen lanh tho",
    "alliance_tech": "dong gop cong nghe lien minh",
    "vip_boost": "vip/boost",
}


def _finish_current_workflow(
    remaining_workflows: list[str],
    expected: str,
    reason: str,
) -> None:
    """Mark the first pending workflow as complete without skipping later work."""
    log.info(
        "Hoan tat workflow=%s (%s). Danh sach truoc khi cap nhat: %s",
        expected,
        reason,
        remaining_workflows,
    )
    if remaining_workflows and remaining_workflows[0] == expected:
        remaining_workflows.pop(0)
        log.info("Danh sach workflow con lai: %s", remaining_workflows)
        return

    log.warning(
        "Khong xoa workflow=%s vi dau danh sach hien la %s. Giu nguyen danh sach: %s",
        expected,
        remaining_workflows[0] if remaining_workflows else None,
        remaining_workflows,
    )


def _run_misc_workflow(device: Device, workflow: str) -> None:
    """Run one non-farm workflow action."""
    device._back_locked_until = 0.0
    from .chores import (
        collect_city_resources,
        do_alliance_gifts,
        do_alliance_help,
        do_alliance_tech,
        do_alliance_territory,
    )

    label = _WORKFLOW_LABELS.get(workflow, workflow)

    def run_getres() -> None:
        _prepare_world_only(device)
        collect_city_resources(device, max_resources=4)

    actions = {
        "getres": run_getres,
        "alliance_help": lambda: do_alliance_help(device),
        "alliance_gifts": lambda: do_alliance_gifts(device),
        "alliance_territory": lambda: do_alliance_territory(device),
        "alliance_tech": lambda: do_alliance_tech(device),
        "vip_boost": lambda: _claim_vip(device),
    }
    action = actions.get(workflow)
    if action is None:
        log.warning("[viec vat] workflow khong hop le: %s", workflow)
        return

    log.info(">>> Thuc hien viec vat rieng le: %s <<<", label)
    try:
        _prepare_world_only(device)
        action()
    except Exception:
        log.exception("[viec vat] loi khi chay %s", label)
    try:
        _prepare_world_only(device)
    except Exception:
        log.exception("[viec vat] khong dua ve WORLD/CITY sau %s", label)
    pause(1.5, 3.0)


def _handle_logo_18_check(device: Device) -> None:
    # Vùng click ngẫu nhiên khi phát hiện logo 18+
    click_rect_ref = (950, 810, 1440, 1070)

    log.info("Bắt đầu quy trình quét và click logo 18+ (tối đa 10 lần)...")
    stable_world_count = 0  # Đếm số lần liên tiếp detect WORLD/CITY để tránh false-positive
    for attempt in range(10):
        if should_stop():
            break

        try:
            screen = device.snapshot()
            state = detect_state(device, screen)
        except Exception as snap_err:
            log.warning("Chụp màn hình/Nhận diện trạng thái khi quét logo 18+ thất bại: %s", snap_err)
            stable_world_count = 0
            pause(5.0)
            continue

        if state == S.EXIT_DIALOG:
            stable_world_count = 0
            log.info("Quet logo 18+ gap popup thoat game -> cham HUY roi quet tiep")
            result = handle_exit_dialog(device, screen)
            pause(getattr(result, "sleep_after", 1.5) or 1.5)
            continue

        if state == S.NETWORK_ERROR:
            stable_world_count = 0
            log.info("Quet logo 18+ gap popup mat mang -> xu ly reconnect roi quet tiep")
            result = handle_network_error(device, screen)
            pause(getattr(result, "sleep_after", 20.0) or 20.0)
            continue

        if state == S.GEMS_SHOP:
            stable_world_count = 0
            log.info("Quet logo 18+ gap man nap tien -> thoat roi quet tiep")
            result = handle_gems_shop(device, screen)
            pause(getattr(result, "sleep_after", 2.5) or 2.5)
            continue

        if state in (S.WORLD, S.CITY):
            h, w = screen.shape[:2]
            start_logo_region = (
                int(w * 0.88),
                int(h * 0.80),
                int(w * 0.99),
                int(h * 0.99),
            )
            try:
                start_logo_pos = device.find_template_in(
                    "logo_18.png", screen, threshold=0.70, region=start_logo_region,
                )
            except Exception:
                start_logo_pos = None
            if start_logo_pos is not None:
                stable_world_count = 0
                tx = int(w * 0.50) + random.randint(-30, 30)
                ty = int(h * 0.78) + random.randint(-20, 20)
                log.info(
                    "Phát hiện màn Nhấn để bắt đầu dù state=%s (logo18=%s) -> tap (%d,%d) rồi chờ load",
                    state.value,
                    start_logo_pos,
                    tx,
                    ty,
                )
                device.tap(tx, ty)
                pause(8.0)
                continue
            stable_world_count += 1
            log.info(
                "Phát hiện trạng thái %s (lần %d/2 liên tiếp) -> "
                "%s",
                state.value,
                stable_world_count,
                "Dừng quét logo 18+" if stable_world_count >= 2 else "Chờ xác nhận thêm lần nữa...",
            )
            if stable_world_count >= 2:
                break
            # Chờ 3s rồi check lại lần nữa để xác nhận game đã load thật sự
            pause(3.0)
            continue
        else:
            stable_world_count = 0

        h, w = screen.shape[:2]
        click_rect = (
            max(0, int(w * click_rect_ref[0] / 2400)),
            max(0, int(h * click_rect_ref[1] / 1080)),
            min(w - 1, int(w * click_rect_ref[2] / 2400)),
            min(h - 1, int(h * click_rect_ref[3] / 1080)),
        )
        logo_region = (
            int(w * 0.88),
            int(h * 0.80),
            int(w * 0.99),
            int(h * 0.99),
        )
        try:
            match_pos = device.find_template_in("logo_18.png", screen, threshold=0.70, region=logo_region)
        except Exception as err:
            log.warning("Không thấy template logo_18.png hoặc lỗi: %s", err)
            match_pos = None

        if match_pos is not None:
            tx = random.randint(click_rect[0], click_rect[2])
            ty = random.randint(click_rect[1], click_rect[3])
            log.info(
                "Phát hiện logo 18+ (lần %d) tại %s -> click ngẫu nhiên tại (%d, %d) "
                "trong vùng [(%d,%d)-(%d,%d)]",
                attempt + 1, match_pos, tx, ty,
                click_rect[0], click_rect[1], click_rect[2], click_rect[3],
            )
            save_debug_image(
                screen, device.serial,
                subdir="logo_18_clicks", prefix="logo_18",
                clicks=[(tx, ty)],
                rects=[logo_region, click_rect],
                label=f"Logo18+ L{attempt+1}",
            )
            device.tap(tx, ty)
        else:
            log.info(
                "Không phát hiện logo 18+ trong vùng coords='%d,%d,%d,%d' (lần %d)",
                logo_region[0],
                logo_region[1],
                logo_region[2],
                logo_region[3],
                attempt + 1,
            )

        pause(5.0)


def _prepare_world_only(device: Device) -> None:
    """Đảm bảo màn hình đang ở WORLD hoặc CITY trước khi chạy workflow.

    Gọi _initial_navigate_to_world trước, sau đó kiểm tra trạng thái thực tế.
    Nếu vẫn còn popup/panel thì xử lý tiếp cho đến khi vào được WORLD/CITY
    hoặc hết tối đa 30s.
    """
    _initial_navigate_to_world(device)

    # Kiểm tra lại: nếu vẫn chưa ở WORLD/CITY thì xử lý tiếp
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            screen = device.snapshot()
        except Exception:
            break
        ocr.clear_cache()
        try:
            state = detect_state(device, screen)
        except Exception:
            state = S.UNKNOWN

        if state in (S.WORLD, S.CITY):
            log.info("_prepare_world_only: xác nhận đang ở %s, sẵn sàng chạy workflow.", state.value)
            return

        log.info(
            "_prepare_world_only: màn hình đang ở %s (chưa phải WORLD/CITY), "
            "tiếp tục xử lý...",
            state.value,
        )

        # Xử lý theo state
        if state == S.CITY:
            # Đã ở city -> ok
            return
        elif state == S.POPUP:
            handle_popup(device, screen)
        elif state == S.BUILD_MENU:
            handle_build_menu(device, screen)
        elif state == S.EXIT_DIALOG:
            handle_exit_dialog(device, screen)
        elif state == S.GEMS_SHOP:
            handle_gems_shop(device, screen)
        elif state == S.SEARCH_PANEL:
            handle_search_panel(device, screen)
        elif state == S.TILE_INFO:
            handle_tile_info(device, screen)
        elif state == S.MARCH_PLAN:
            handle_march_plan(device, screen)
        elif state == S.NETWORK_ERROR:
            handle_network_error(device, screen)
            pause(20.0)
        elif state == S.LOCK_SCREEN:
            handle_lock_screen(device, screen)
            pause(2.5)
        else:
            # UNKNOWN hoặc state khác -> gửi phím BACK nhẹ
            device.key("BACK")
            pause(2.0)
        pause(1.5)

    log.warning("_prepare_world_only: hết 30s vẫn chưa vào WORLD/CITY -> main loop sẽ xử lý tiếp.")


def _initial_navigate_to_world(device: Device) -> None:
    """First-time startup: walk the game to the WORLD screen.

    Snapshot + detect. Branches:
      * WORLD          -> ready, return.
      * NETWORK_ERROR  -> tap XÁC NHẬN + wait 20s.
      * LOCK_SCREEN    -> unlock + re-check.
      * CITY           -> tap map_toggle to enter the world.
      * Popup/panel    -> tap top-right X + BACK as fallback.

    Up to 5 attempts. If still not at WORLD, the main loop's recovery
    paths take over.
    """
    log.info("Kiểm tra trạng thái ban đầu...")
    for attempt in range(5):
        try:
            screen = device.snapshot()
        except Exception:
            log.exception("Snapshot ban đầu thất bại")
            return
        ocr.clear_cache()
        try:
            state = detect_state(device, screen)
        except Exception:
            log.exception("Nhận diện trạng thái ban đầu crash")
            state = S.UNKNOWN

        log.info(
            "Trạng thái ban đầu (lần %d): %s", attempt + 1, state.value,
        )
        if state == S.WORLD:
            log.info("OK: đã ở WORLD, vào vòng lặp chính")
            return

        if state == S.NETWORK_ERROR:
            log.warning("Popup mạng ngay từ đầu -> xử lý + chờ 20s")
            handle_network_error(device, screen)
            pause(20.0)
            continue

        if state == S.LOCK_SCREEN:
            log.info("Game đang khoá -> mở khoá")
            handle_lock_screen(device, screen)
            pause(2.5)
            continue

        if state == S.CITY:
            log.info("Đang ở THÀNH -> chạm bản đồ để ra WORLD")
            pos = tap_template(
                device, screen, "btn_map_toggle.png", 0.75,
                region_pct=(0, 80, 15, 100),
            )
            if pos is None:
                x, y = pct_to_px(screen, 6.0, 91.2)
                device.tap(x, y)
            pause(2.5)
            continue

        # Mọi state khác mà MAIN LOOP đã biết cách xử lý
        # (search_panel, tile_info, march_plan, popup, build_menu,
        # exit_dialog, gems_shop) -> không cố ép về WORLD ở đây, vào loop để
        # handler riêng của state đó tiếp quản.
        if state in (
            S.SEARCH_PANEL, S.TILE_INFO, S.MARCH_PLAN,
            S.POPUP, S.BUILD_MENU, S.EXIT_DIALOG, S.GEMS_SHOP,
        ):
            log.info(
                "Đang ở %s -> main loop sẽ tự xử lý, "
                "bỏ qua initial nav",
                state.value,
            )
            return

        # State UNKNOWN: Kiểm tra game có thực sự không chạy hay không trước khi khởi động
        if not device.is_game_running():
            log.warning("Đang ở %s và phát hiện game không chạy/crash -> Khởi chạy lại game com.rok.gp.vn...", state.value)
            device.start_game()
            device._back_locked_until = 0.0
            log.info("Chờ 10s sau khi mở gói com.rok.gp.vn...")
            pause(10.0)
            _handle_logo_18_check(device)
        else:
            log.info("Đang ở %s nhưng game vẫn đang chạy. Mang game lên trước (bring to front) và chờ 5s...", state.value)
            try:
                device._adb_shell("monkey", "-p", "com.rok.gp.vn", "-c", "android.intent.category.LAUNCHER", "1")
            except Exception:
                pass
            device._back_locked_until = 0.0
            pause(5.0)

    log.warning(
        "Sau 5 lần thử vẫn chưa ở WORLD -> vào loop, "
        "để main loop tự xử lý",
    )


def _go_home_then_world(device: Device) -> None:
    """Normalise camera: city <-> world toggle to fix camera-chasing.

    After a successful dispatch the camera follows the marching army.
    Tapping map_toggle twice (world -> city -> world) re-centres on
    the user's main city.

    Swallows every exception — this is a best-effort tidy-up step;
    the bot must still be able to sleep / poll if it fails.
    """
    log.info("Chuẩn hoá camera: về thành rồi quay ra world")
    try:
        screen = device.snapshot()
    except Exception:
        log.exception("Snapshot trong cleanup thất bại -> bỏ qua")
        return
    ocr.clear_cache()

    h, w = screen.shape[:2]

    def _tap_map_toggle(scr: np.ndarray) -> None:
        try:
            region_px = region_pct_to_px(scr, (0, 80, 15, 100))
            pos = device.find_template_in(
                "btn_map_toggle.png", scr, 0.75, region=region_px,
            )
        except FileNotFoundError:
            pos = None
        if pos is not None:
            device.tap(*pos)
        else:
            device.tap(int(w * 0.06), int(h * 0.912))

    _tap_map_toggle(screen)
    pause(2.5)

    try:
        screen = device.snapshot()
    except Exception:
        log.exception("Snapshot lần 2 trong cleanup thất bại")
        return
    ocr.clear_cache()
    _tap_map_toggle(screen)
    pause(2.5)

    try:
        screen = device.snapshot()
        ocr.clear_cache()
        state = detect_state(device, screen)
    except Exception:
        log.exception("Verify trạng thái cuối cleanup thất bại")
        return

    if state == S.WORLD:
        log.info("Cleanup OK: đã ở WORLD")
        return
    log.warning(
        "Sau cleanup vẫn ở %s -> gọi _return_to_world()", state.value,
    )
    _return_to_world(device, max_attempts=4)


def _return_to_world(device: Device, max_attempts: int = 6) -> None:
    """Close any open popup/panel until the game is back on WORLD."""
    log.info("Đang đưa game về màn hình thế giới trước khi thoát...")
    for attempt in range(max_attempts):
        try:
            screen = device.snapshot()
        except Exception:
            log.exception("Không chụp được màn hình khi cleanup")
            return
        ocr.clear_cache()
        try:
            state = detect_state(device, screen)
        except Exception:
            log.exception("Nhận diện trạng thái crash trong cleanup")
            state = S.UNKNOWN

        log.info(
            "Cleanup vòng %d: trạng thái=%s",
            attempt + 1, state.value,
        )
        if state == S.WORLD:
            log.info("Đã về màn hình thế giới")
            return
        if state == S.CITY:
            pos = tap_template(
                device, screen, "btn_map_toggle.png", 0.75,
                region_pct=(0, 80, 15, 100),
            )
            if pos is None:
                x, y = pct_to_px(screen, 6.0, 91.2)
                device.tap(x, y)
        elif state in (S.EXIT_DIALOG, S.POPUP, S.GEMS_SHOP, S.BUILD_MENU, S.SEARCH_PANEL, S.TILE_INFO, S.MARCH_PLAN):
            _dispatch_to_handler(device, screen, state, stuck_count=1)
        else:
            x, y = pct_to_px(screen, 97.0, 5.0)
            device.tap(x, y)
            pause(0.5)
            try:
                device.key("BACK")
            except Exception:
                pass
        pause(1.5)
    log.warning(
        "Không đưa về được world sau %d lần thử -> bỏ qua",
        max_attempts,
    )


def _handle_queue_full(device: Device, current_character: int) -> str:
    """Xử lý khi nhân vật hoàn thành mọi chu trình.

    Returns:
        "character" nếu đã chuyển sang char 2,
        "account" nếu đã chuyển sang account kế tiếp,
        "wrapped" nếu đã quay về account đầu danh sách,
        "retry" nếu chuyển nhân vật/account lỗi — caller tiếp tục vòng lặp (không dừng bot),
        "stop" nếu chuyển account thất bại hoàn toàn (hiếm, chỉ từ path account).
    """
    log.info("=== Đã hoàn thành mọi chu trình của nhân vật hiện tại! ===")
    _return_to_world(device, max_attempts=4)
    _cleanup_captures()

    if current_character == 1:
        log.info("=== Tiến hành chuyển sang nhân vật thứ 2... ===")
        success = False
        for attempt in range(1, 6):
            log.info("Thử chuyển nhân vật lần %d/5...", attempt)
            success = handle_switch_character(device)
            if success:
                break
            log.warning(
                "Chuyển nhân vật lần %d/5 thất bại. Đưa về WORLD rồi thử lại nếu còn lượt...",
                attempt,
            )
            _return_to_world(device, max_attempts=4)
            if attempt < 5:
                pause(5.0)
        if not success:
            log.warning(
                "Chuyển nhân vật thất bại sau 5 lần thử! "
                "Kill app -> bật lại game -> thử lại (không dừng bot)."
            )
            try:
                device.shutdown()
            except Exception:
                log.exception("Kill app sau khi chuyển nhân vật thất bại")
            pause(3.0)
            try:
                device.start_game()
                device._back_locked_until = 0.0
                pause(10.0)
                _handle_logo_18_check(device)
                _prepare_world_only(device)
            except Exception:
                log.exception("Bật lại game sau khi chuyển nhân vật thất bại")
            return "retry"
        log.info("Chuyển nhân vật thành công! Bắt đầu quét logo 18+ ngay sau 5s (logo xuất hiện trong lúc load)...")
        pause(5.0)
        _handle_logo_18_check(device)
        # Sau khi 18+ check xong, nếu vẫn chưa đủ 15s thì chờ thêm cho game ổn định
        log.info("Chờ thêm 10s cho game load nhân vật mới hoàn tất...")
        pause(10.0)
        config.CYCLE_RESOURCES = None
        config.CYCLE_SCENARIO_ID = None
        config.CYCLE_FALLBACK_RESOURCES = None
        return "character"

    log.info("=== Nhân vật thứ 2 đã xong. Thử chuyển sang account kế tiếp... ===")
    account_result = "failed"
    for attempt in range(1, 4):
        log.info("Thử chuyển account lần %d/3...", attempt)
        account_result = handle_switch_account(device, wrap_to_first=True)
        if account_result in ("switched", "wrapped"):
            break
        log.warning(
            "Chuyển account lần %d/3 thất bại. Đưa về WORLD rồi thử lại nếu còn lượt...",
            attempt,
        )
        _return_to_world(device, max_attempts=4)
        if attempt < 3:
            pause(random.uniform(8.0, 15.0))

    if account_result == "wrapped":
        log.info(
            "Da chay xong toan bo account va quay ve account dau danh sach. Dong app; B6 se cho theo cycle_wait_min +/- cycle_wait_variance_min."
        )
        ensure_first = "failed"
        try:
            pause(5.0)
            _handle_logo_18_check(device)
            _prepare_world_only(device)
            for ensure_attempt in range(1, 4):
                log.info("Kiem tra/ep ve account dau tien truoc khi dong app lan %d/3...", ensure_attempt)
                ensure_first = handle_switch_to_first_account(device)
                log.info("Kiem tra/ep ve account dau tien truoc khi dong app: %s", ensure_first)
                if ensure_first != "failed":
                    break
                _return_to_world(device, max_attempts=4)
                if ensure_attempt < 3:
                    pause(random.uniform(8.0, 15.0))
            pause(10.0)
        except Exception:
            log.exception("Loi khi cho game load account dau truoc khi dong app")
        if ensure_first == "failed":
            wait_retry = random.uniform(20.0, 35.0)
            log.warning(
                "Chua xac nhan duoc account dau lam6 sau khi chay xong. Cho %.2fs roi retry chuyen acc.",
                wait_retry,
            )
            pause(wait_retry)
            return "retry"
        try:
            device.shutdown()
        except Exception:
            log.exception("Dong app sau khi wrap ve account dau that bai")
        return "stop"
    if account_result != "switched":
        wait_retry = random.uniform(20.0, 35.0)
        log.warning(
            "Chuyển account vẫn thất bại sau 3 lần. Chờ %.2fs rồi retry mềm; quá 5 retry liên tiếp sẽ kill app.",
            wait_retry,
        )
        pause(wait_retry)
        return "retry"
    log.info("Chuyển account thành công! Bắt đầu quét logo 18+ ngay sau 5s (logo xuất hiện trong lúc load)...")
    pause(5.0)
    _handle_logo_18_check(device)
    log.info("Chờ thêm 10s cho game load account mới hoàn tất...")
    pause(10.0)
    config.CYCLE_RESOURCES = None
    config.CYCLE_SCENARIO_ID = None
    config.CYCLE_FALLBACK_RESOURCES = None
    return "account"


def _dispatch_to_handler(
    device: Device, screen: np.ndarray, state: S, stuck_count: int,
):
    if state == S.LOCK_SCREEN:
        return handle_lock_screen(device, screen)
    if state == S.NETWORK_ERROR:
        return handle_network_error(device, screen)
    if state == S.EXIT_DIALOG:
        return handle_exit_dialog(device, screen)
    if state == S.POPUP:
        return handle_popup(device, screen)
    if state == S.GEMS_SHOP:
        return handle_gems_shop(device, screen)
    if state == S.BUILD_MENU:
        return handle_build_menu(device, screen)
    if state == S.SEARCH_PANEL:
        return handle_search_panel(device, screen)
    if state == S.TILE_INFO:
        return handle_tile_info(device, screen)
    if state == S.MARCH_PLAN:
        return handle_march_plan(device, screen)
    if state == S.WORLD:
        return handle_world(device, screen, goal="dispatch")
    if state == S.CITY:
        return handle_city(device, screen, goal="dispatch")
    return handle_unknown(device, screen, stuck_count)


_CYCLE_FARM_RESOURCES = ["corn", "stone", "gold", "wood"]
_CYCLE_FARM_NO_GOLD = ["corn", "stone", "wood"]
_CYCLE_FARM_SCENARIOS = {
    "1": "4 luot dau random du 4 loai; luot 5 random 1 trong 4 loai",
    "2": "2 luot dau gold; 3 luot sau gom du corn/stone/wood theo thu tu random",
    "3": "luot dau gold; 4 luot sau gom du 4 loai theo thu tu random",
    "4": "chay theo thu tu gold, stone, wood, corn, corn",
    "5": "luot dau corn; 4 luot sau gom du 4 loai theo thu tu random",
}


def _build_cycle_farm_plan(scenario_id: str) -> tuple[list[str], list[str]]:
    if scenario_id == "1":
        plan = list(_CYCLE_FARM_RESOURCES)
        random.shuffle(plan)
        plan.append(random.choice(_CYCLE_FARM_RESOURCES))
        return plan, list(_CYCLE_FARM_RESOURCES)
    if scenario_id == "2":
        plan = ["gold", "gold"]
        no_gold = list(_CYCLE_FARM_NO_GOLD)
        random.shuffle(no_gold)
        plan.extend(no_gold)
        return plan, list(_CYCLE_FARM_NO_GOLD)
    if scenario_id == "3":
        plan = ["gold"]
        tail = list(_CYCLE_FARM_RESOURCES)
        random.shuffle(tail)
        plan.extend(tail)
        return plan, list(_CYCLE_FARM_RESOURCES)
    if scenario_id == "4":
        return ["gold", "stone", "wood", "corn", "corn"], list(_CYCLE_FARM_RESOURCES)
    if scenario_id == "5":
        plan = ["corn"]
        tail = list(_CYCLE_FARM_RESOURCES)
        random.shuffle(tail)
        plan.extend(tail)
        return plan, list(_CYCLE_FARM_RESOURCES)
    raise ValueError(f"Unknown cycle farm scenario: {scenario_id}")


def _cycle_farm_resource_for_dispatch(dispatched_count: int) -> str:
    scenario = str(getattr(config, "FARM_SCENARIO", "random")).strip().lower()
    if scenario not in {"random", "1", "2", "3", "4", "5"}:
        log.warning("farm_scenario=%r khong hop le -> dung random", scenario)
        scenario = "random"

    if not getattr(config, "CYCLE_SCENARIO_ID", None):
        scenario_id = random.choice(["1", "2", "3", "4", "5"]) if scenario == "random" else scenario
        plan, fallback_pool = _build_cycle_farm_plan(scenario_id)
        config.CYCLE_SCENARIO_ID = scenario_id
        config.CYCLE_RESOURCES = plan
        config.CYCLE_FALLBACK_RESOURCES = fallback_pool
        log.info(
            "Chon kich ban farm cycle %s: %s. Ke hoach: %s",
            scenario_id,
            _CYCLE_FARM_SCENARIOS[scenario_id],
            plan,
        )

    plan = list(getattr(config, "CYCLE_RESOURCES", None) or [])
    if dispatched_count < len(plan):
        return plan[dispatched_count]

    fallback_pool = list(
        getattr(config, "CYCLE_FALLBACK_RESOURCES", None) or _CYCLE_FARM_RESOURCES
    )
    return random.choice(fallback_pool)


def _reload_config_from_file(device_serial: str) -> None:
    """Tải lại cấu hình từ file devices.yaml động mà không ảnh hưởng tới trạng thái chạy hiện tại của bot."""
    try:
        from core.config_io import load_bot_fleet_config, load_global_settings
        from .constants import ROOT
        from . import config

        devices_file = ROOT / "devices.yaml"
        if not devices_file.exists():
            return

        # 1. Load global settings đầu tiên
        load_global_settings(devices_file)

        # 2. Load cấu hình cụ thể của thiết bị này nếu có
        fleet_cfg = load_bot_fleet_config(devices_file)
        dev_cfg = next((c for c in fleet_cfg if c.serial == device_serial), None)
        if dev_cfg:
            config.TARGET_LEVEL = dev_cfg.target_level
            
            res_map = {"ngo": "corn", "food": "corn", "crop": "corn"}
            res = res_map.get(dev_cfg.resource, dev_cfg.resource)
            config.RESOURCE_TAB = res
            
            config.SKIP_LEVEL_ADJUST = dev_cfg.skip_level_adjust
            config.TURN_WAIT_SEC = dev_cfg.turn_wait_min * 60
            config.MAX_SLOTS = dev_cfg.max_slots
            config.FARM_SCENARIO = dev_cfg.farm_scenario
            
            log.info(
                "[ReloadConfig] Đã tải lại devices.yaml thành công cho %s: "
                "resource=%s, target_level=%d, max_slots=%d, turn_wait_min=%d",
                device_serial, config.RESOURCE_TAB, config.TARGET_LEVEL, config.MAX_SLOTS, dev_cfg.turn_wait_min
            )
    except Exception as e:
        log.warning("[ReloadConfig] Lỗi khi tự động tải lại devices.yaml: %s", e)


def run(device: Device, max_iterations: int | None = None) -> None:
    # B0: Khoá toàn bộ input chuột và bàn phím PC trong suốt thời gian bot chạy.
    # Người dùng không thể di chuột hay bấm phím làm nhiễu; chỉ bot điều khiển.
    # unlock_input() tự động gọi khi bot kết thúc (kể cả khi crash).
    lock_input()
    try:
        _run_body(device, max_iterations)
    finally:
        # B5: Dọn dẹp sau khi kết thúc bot (thành công hoặc lỗi)
        log.info("B5: Bắt đầu dọn dẹp sau khi kết thúc bot (thành công hoặc lỗi)...")
        try:
            _cleanup_captures()
        except Exception:
            pass
        unlock_input()


def _run_body(device: Device, max_iterations: int | None = None) -> None:
    install_signal_handler()
    install_pause_hotkey()   # Đăng kí phím tắt Ctrl+Space pause/resume
    register_serial(device.serial)
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Khởi động watchdog thread kiểm tra app crash mỗi 60s (độc lập với vòng lặp)
    _watchdog_stop = threading.Event()
    _watchdog_thread = _start_app_watchdog(device, _watchdog_stop, interval=60.0)
    try:
        _run_body_inner(device, max_iterations)
    finally:
        _watchdog_stop.set()
        _watchdog_thread.join(timeout=5.0)
        log.info("[watchdog] Thread theo dõi app đã dừng.")


def _run_body_inner(device: Device, max_iterations: int | None = None) -> None:
    # Dọn STOP flag cũ ở startup:
    #   * STOP.flag (global): có thể là rác từ lần fleet crash, hoặc
    #     từ lần chạy trước user tạo tay rồi quên. Xoá để không bị
    #     dừng ngay.
    #   * STOP_<serial>.flag (riêng máy): tương tự.
    # Fleet KHÔNG dùng STOP.flag global (chỉ dùng per-device) nên
    # xoá ở đây không ảnh hưởng đến fleet đang chạy.

    if STOP_FLAG.exists():
        log.info("Xoá STOP.flag cũ")
        STOP_FLAG.unlink()
    per_dev_flag = STOP_FLAG.parent / f"STOP_{device.serial}.flag"
    if per_dev_flag.exists():
        log.info("Xoá %s cũ", per_dev_flag.name)
        per_dev_flag.unlink()

    device.keep_awake()
    device._back_locked_until = 0.0
    config.CYCLE_RESOURCES = None
    config.CYCLE_SCENARIO_ID = None
    config.CYCLE_FALLBACK_RESOURCES = None

    # B0: đứng im 10s để check thông tin device, app, màn hình
    log.info("B0: Đứng im 10s để check thông tin thiết bị, ứng dụng và màn hình...")
    pause(10.0)

    # 1. Kiểm tra trạng thái Bluestacks (nếu thuộc cấu hình Bluestacks)
    from core.bot.bluestack import start_bluestack, is_port_open, get_instance_name_by_port
    s = str(device.serial).strip()
    port_str = s.split(":")[-1] if ":" in s else s
    is_bluestacks = False
    try:
        port = int(port_str)
        if get_instance_name_by_port(port) is not None:
            is_bluestacks = True
    except ValueError:
        pass

    if is_bluestacks:
        log.info("B0: Phát hiện thiết bị Bluestacks. Kiểm tra xem giả lập có đang bật không...")
        try:
            if not is_port_open(port):
                log.warning("Bluestacks chưa bật hoặc đã bị đóng. Tiến hành bật Bluestacks...")
                if start_bluestack(device.serial):
                    log.info("Đã bật Bluestacks thành công. Chờ thêm 10s cho giả lập ổn định...")
                    pause(10.0)
                else:
                    log.error("Không thể khởi động hoặc kết nối Bluestacks cho %s", device.serial)
            else:
                log.info("Bluestacks đã bật sẵn.")
        except Exception as e:
            log.error("Lỗi khi kiểm tra/khởi động Bluestacks: %s", e)

    # 2. Kiểm tra xem game có bật không
    try:
        if not device.is_game_running():
            log.warning("Game chưa chạy hoặc đã bị đóng. Tiến hành khởi động lại game com.rok.gp.vn...")
            device.start_game()
            device._back_locked_until = 0.0
            
            log.info("Đang chờ 10s sau khi kích hoạt mở gói com.rok.gp.vn...")
            pause(10.0)

            # Quy trình quét logo 18+ coords="2159,916,2316,1041"
            _handle_logo_18_check(device)
        else:
            log.info("Game đang chạy sẵn. Đưa ứng dụng lên tiền cảnh...")
            device._adb_shell("monkey", "-p", "com.rok.gp.vn", "-c", "android.intent.category.LAUNCHER", "1")
            device._back_locked_until = 0.0
            log.info("Đang chờ 5s cho giao diện game hiển thị ổn định...")
            pause(5.0)
            # Kiểm tra logo 18+ dù game đang chạy (có thể vẫn cần ấn xác nhận)
            _handle_logo_18_check(device)
    except Exception as e:
        log.error("Lỗi khi kiểm tra/khởi chạy game: %s. Thử khởi chạy trực tiếp...", e)
        try:
            device._adb_shell("monkey", "-p", "com.rok.gp.vn", "-c", "android.intent.category.LAUNCHER", "1")
            device._back_locked_until = 0.0
            pause(10.0)
        except Exception:
            pass

    # Nếu bật chỉ chạy nhận VIP (ONLY_CLAIM_VIP) -> chỉ chạy VIP rồi thoát
    if getattr(config, "ONLY_CLAIM_VIP", False):
        log.info("=== Chế độ CHỈ NHẬN VIP (ONLY_CLAIM_VIP) được kích hoạt ===")
        _initial_navigate_to_world(device)
        device._back_locked_until = 0.0
        _claim_vip(device)
        _initial_navigate_to_world(device)
        log.info("=== Hoàn thành nhận VIP. Kết thúc chương trình. ===")
        return

    # Xác định màn hình và chuẩn hoá về WORLD trước khi chạy
    _prepare_world_only(device)

    # B1: sau khi vào được city hoặc world, chờ 3>8s
    wait_b1 = random.uniform(3.0, 8.0)
    log.info("B1: Đã vào WORLD/CITY, chờ %.2fs trước khi thực hiện chu trình bot...", wait_b1)
    pause(wait_b1)

    remaining_workflows = _build_randomized_workflows()
    log.info("=== Workflow random cho nhan vat hien tai: %s ===", remaining_workflows)

    last_state: S | None = None
    stuck_count = 0
    iteration = 0
    dispatched_count = 0
    state_history: list[S] = []
    reset_slider_state()
    current_character = 1
    is_first_world_snapshot = True
    switch_account_fail_streak = 0

    # Read the n/N badge once on startup so we know the current queue
    # state (user may already have marches out) and the account's
    # real MAX_SLOTS (varies with VIP / talents).
    n0, mx0 = _read_initial_slot_badge_with_retries(device)
    if mx0 is not None and mx0 > 0:
        if mx0 != config.MAX_SLOTS:
            log.info(
                "Sức chứa hàng chờ ban đầu: %d (CLI cài %d)",
                mx0, config.MAX_SLOTS,
            )
        config.MAX_SLOTS = mx0
    if n0 is not None:
        dispatched_count = n0
        log.info(
            "Hàng chờ ban đầu: %d/%d -> bot bắt đầu từ đây",
            n0, config.MAX_SLOTS,
        )
    else:
        log.warning(
            "Không đọc được huy hiệu ban đầu sau các lần thử -> coi như 0/%d",
            config.MAX_SLOTS,
        )
        dispatched_count = 0

    last_reload_time = time.monotonic()

    while not should_stop():
        # Kiểm tra và chờ nếu bot đang paused (Ctrl+Space)
        wait_if_paused()
        if should_stop():
            break

        # Nếu đã hoàn thành mọi chu trình cho nhân vật hiện tại:
        if not remaining_workflows:
            log.info(
                "Danh sach workflow da rong -> moi duoc chuyen nhan vat/account. Kiem tra lan cuoi: %s",
                remaining_workflows,
            )
            transition = _handle_queue_full(device, current_character)
            if transition == "stop":
                break
            if transition == "retry":
                switch_account_fail_streak += 1
                log.warning(
                    "Chuyen nhan vat/account retry lien tiep %d. Tiep tuc vong lap (khong dung bot)...",
                    switch_account_fail_streak,
                )
                # Neu _handle_queue_full da tu kill+restart (nhan vat fail 5 lan),
                # streak co the tang cao -> reset sau nguong 5 de tranh main loop
                # trigger them 1 lan kill+restart nua (da xu ly ben trong roi).
                if switch_account_fail_streak > 5:
                    log.warning(
                        "Streak chuyen acc/nhan vat > 5 lan -> kill app, mo lai game de phuc hoi.",
                    )
                    try:
                        device.shutdown()
                    except Exception:
                        log.exception("Kill app sau switch fail qua 5 lan")
                    pause(3.0)
                    try:
                        device.start_game()
                        device._back_locked_until = 0.0
                        pause(10.0)
                        _handle_logo_18_check(device)
                        _prepare_world_only(device)
                    except Exception:
                        log.exception("Mo lai game sau switch fail qua 5 lan")
                    switch_account_fail_streak = 0
                continue
            switch_account_fail_streak = 0
            if transition == "character":
                current_character = 2
                log.info("Bắt đầu lại quy trình với nhân vật thứ 2...")
            else:
                current_character = 1
                log.info("Bắt đầu lại workflow random với account mới, nhân vật thứ 1...")

            _prepare_world_only(device)

            # B1: sau khi vào được city hoặc world, chờ 3>8s
            wait_b1 = random.uniform(3.0, 8.0)
            log.info(
                "B1: Account/nhân vật mới đã vào WORLD/CITY, chờ %.2fs trước khi thực hiện chu trình bot...",
                wait_b1,
            )
            pause(wait_b1)

            # Khởi tạo lại chu trình cho nhân vật/account mới
            remaining_workflows = _build_randomized_workflows()
            log.info(
                "=== Workflow random account hien tai / nhan vat %d: %s ===",
                current_character,
                remaining_workflows,
            )

            # Reset các trạng thái của nhân vật/account mới
            last_state = None
            stuck_count = 0
            dispatched_count = 0
            is_first_world_snapshot = True
            reset_slider_state()
            device._back_locked_until = 0.0
            log.info("Bỏ khoá nút BACK đối với account/nhân vật mới.")

            # Đọc lại huy hiệu ban đầu cho nhân vật/account mới
            n0, mx0 = _read_initial_slot_badge_with_retries(device)
            if mx0 is not None and mx0 > 0:
                config.MAX_SLOTS = mx0
            if n0 is not None:
                dispatched_count = n0
                log.info("Hàng chờ account/nhân vật mới ban đầu: %d/%d", n0, config.MAX_SLOTS)
            else:
                log.warning("Không đọc được huy hiệu account/nhân vật mới sau các lần thử -> coi như 0/%d", config.MAX_SLOTS)
                dispatched_count = 0
            continue

        # Lấy chu trình đang chờ chạy đầu tiên
        current_wf = remaining_workflows[0]
        if current_wf != "farm":
            _run_misc_workflow(device, current_wf)
            _finish_current_workflow(
                remaining_workflows,
                current_wf,
                f"{_WORKFLOW_LABELS.get(current_wf, current_wf)} done",
            )
            continue

        # Nếu hàng chờ đã đầy từ trước:
        if dispatched_count >= config.MAX_SLOTS:
            log.info("Hàng chờ đã đầy (%d/%d). Hoàn thành chu trình FARM.", dispatched_count, config.MAX_SLOTS)
            _finish_current_workflow(remaining_workflows, "farm", "queue already full")
            continue

        # Tự động nạp lại devices.yaml mỗi 3 phút (180 giây)
        if time.monotonic() - last_reload_time >= 180.0:
            _reload_config_from_file(device.serial)
            last_reload_time = time.monotonic()

        iteration += 1
        if max_iterations and iteration > max_iterations:
            log.info(
                "Đã đạt giới hạn %d vòng lặp -> dừng. Workflow con lai: %s",
                max_iterations,
                remaining_workflows,
            )
            break

        log.info(
            "=== vòng %d (đã gửi=%d) ===",
            iteration, dispatched_count,
        )



        t0 = time.monotonic()
        try:
            screen = device.snapshot()
        except Exception:
            log.exception("Chụp màn hình thất bại! Thiết bị có thể đã offline. Tiến hành tự động khôi phục kết nối...")
            
            # Kiểm tra và bật lại Bluestacks nếu bị crash/tắt
            from core.bot.bluestack import start_bluestack, is_port_open, get_instance_name_by_port
            s = str(device.serial).strip()
            port_str = s.split(":")[-1] if ":" in s else s
            is_bluestacks = False
            try:
                port = int(port_str)
                if get_instance_name_by_port(port) is not None:
                    is_bluestacks = True
            except ValueError:
                pass

            if is_bluestacks:
                try:
                    if not is_port_open(port):
                        log.warning("Giả lập Bluestacks của %s đã bị tắt/crash. Tiến hành khởi động lại giả lập...", device.serial)
                        start_bluestack(device.serial)
                        pause(10.0)
                except Exception as bs_err:
                    log.error("Lỗi khi tự động khởi động lại Bluestacks: %s", bs_err)

            try:
                # Khởi tạo lại kết nối Airtest Android
                from airtest.core.android.android import Android
                device._dev = Android(
                    serialno=device.serial,
                    cap_method="MINICAP",
                    touch_method="MINITOUCH",
                )
                device._adb_path = device._dev.adb.adb_path
                log.info("Khôi phục kết nối thành công với thiết bị: %s", device.serial)
                
                # Kiểm tra xem game có thực sự bị tắt hay không khi khôi phục kết nối
                if not device.is_game_running():
                    log.warning("Game không chạy sau khi khôi phục kết nối -> Đang khởi chạy lại...")
                    device.start_game()
                    device._back_locked_until = 0.0
                    log.info("Chờ 10s sau khi mở gói com.rok.gp.vn...")
                    pause(10.0)
                    _handle_logo_18_check(device)
                else:
                    log.info("Game vẫn đang chạy sau khi khôi phục kết nối. Đưa game lên trước...")
                    try:
                        device._adb_shell("monkey", "-p", "com.rok.gp.vn", "-c", "android.intent.category.LAUNCHER", "1")
                    except Exception:
                        pass
                    device._back_locked_until = 0.0
                    pause(5.0)
            except Exception as re_err:
                log.error("Tự động khôi phục kết nối thất bại: %s. Thử lại sau 5s...", re_err)
                pause(5.0)
            continue
        t_snap = time.monotonic() - t0
        ocr.clear_cache()

        t1 = time.monotonic()
        try:
            state = detect_state(device, screen)
        except Exception:
            log.exception(
                "Nhận diện trạng thái crash -> coi như UNKNOWN",
            )
            state = S.UNKNOWN
        t_detect = time.monotonic() - t1

        log.info(
            "Trạng thái: %s (chụp=%.2fs nhận diện=%.2fs)",
            state.value, t_snap, t_detect,
        )

        if state == last_state:
            stuck_count += 1
        else:
            stuck_count = 1
            last_state = state

        if state == S.UNKNOWN and stuck_count == 1:
            save_debug_image(screen, device.serial, prefix="UNKNOWN", label="UNKNOWN state")

        if state == S.WORLD and is_first_world_snapshot:
            save_debug_image(screen, device.serial, prefix="FIRST_WORLD", label="First WORLD")
            is_first_world_snapshot = False

        if state == S.WORLD:
            try:
                n_world, mx_world = read_slot_badge(screen)
                if mx_world is not None and mx_world > 0:
                    config.MAX_SLOTS = mx_world
                if n_world is not None:
                    if n_world != dispatched_count:
                        log.info(
                            "Đồng bộ hàng đợi ở WORLD: bot tưởng %d/%d, thực tế %d/%d",
                            dispatched_count, config.MAX_SLOTS,
                            n_world, config.MAX_SLOTS,
                        )
                        dispatched_count = n_world
            except Exception:
                pass

            if dispatched_count >= config.MAX_SLOTS:
                log.info("Đồng bộ hàng đợi: hàng chờ đã đầy (%d/%d). Hoàn thành chu trình FARM.", dispatched_count, config.MAX_SLOTS)
                _finish_current_workflow(remaining_workflows, "farm", "world badge full")
                continue



        state_history.append(state)
        if len(state_history) > 6:
            state_history.pop(0)

        # Pattern "dispatch thất bại": TILE_INFO -> UNKNOWN.
        # Sau khi tap THU THẬP, game thường mở MARCH_PLAN. Nếu thay
        # vào đó là UNKNOWN thì có 2 nguyên nhân thường gặp:
        #   * Hàng chờ thực ra đã đầy (badge ban đầu OCR sai),
        #   * Tile vừa chọn đã có quân của mình đang gather rồi.
        # Cả hai đều khiến game hiện popup lỗi mà bot chưa bắt được
        # → bot khôi phục về WORLD, mở panel, chọn lại CÙNG tile,
        # và lặp vô hạn. Đồng bộ lại huy hiệu n/N: nếu đầy thì vào
        # ngủ chờ ngay; nếu chưa đầy thì cập nhật dispatched_count
        # để lần sau tính đúng.
        prev_state = (
            state_history[-2] if len(state_history) >= 2 else None
        )
        if state == S.UNKNOWN and prev_state == S.TILE_INFO:
            log.warning(
                "Pattern THU THẬP -> UNKNOWN: dispatch có thể đã thất bại "
                "-> đọc lại huy hiệu để đồng bộ",
            )
            try:
                n_sync, mx_sync = read_slot_badge(screen)
                if mx_sync is not None and mx_sync != config.MAX_SLOTS:
                    log.info(
                        "Dò lại sức chứa: %d (trước %d)",
                        mx_sync, config.MAX_SLOTS,
                    )
                    config.MAX_SLOTS = mx_sync
                if n_sync is not None:
                    if n_sync != dispatched_count:
                        log.info(
                            "Đồng bộ: bot tưởng %d/%d, thực tế %d/%d",
                            dispatched_count, config.MAX_SLOTS,
                            n_sync, config.MAX_SLOTS,
                        )
                        dispatched_count = n_sync
                    if n_sync >= config.MAX_SLOTS:
                        log.info("Đồng bộ hàng đợi: hàng chờ đã đầy (%d/%d) sau khi gửi lỗi. Hoàn thành chu trình FARM.", n_sync, config.MAX_SLOTS)
                        _finish_current_workflow(remaining_workflows, "farm", "sync after dispatch failure full")
                        continue
                else:
                    log.info(
                        "Không đọc được huy hiệu khi đồng bộ -> "
                        "tiếp tục recovery bình thường",
                    )
            except Exception:
                log.exception("Đồng bộ huy hiệu thất bại")

        # Hard ceiling: stuck in a non-UNKNOWN state too long.
        if state != S.UNKNOWN and stuck_count >= 6:
            log.warning(
                "Kẹt ở %s %d vòng -> ép vào chế độ hồi phục UNKNOWN",
                state.value, stuck_count,
            )
            state = S.UNKNOWN
            stuck_count = 1
            last_state = S.UNKNOWN

        # A-B-A-B-A-B ping-pong (no progress).
        if (
            state != S.UNKNOWN
            and len(state_history) >= 6
            and state_history[-1] == state_history[-3] == state_history[-5]
            and state_history[-2] == state_history[-4] == state_history[-6]
            and state_history[-1] != state_history[-2]
        ):
            log.warning(
                "Phát hiện ping-pong %s<->%s -> ép hồi phục UNKNOWN",
                state_history[-1].value, state_history[-2].value,
            )
            state = S.UNKNOWN
            state_history.clear()

        # Xoay vòng tài nguyên: random ngô, đá, vàng, gỗ trong 4 lượt đầu, nếu nhiều hơn thì random 1 trong 4
        if getattr(config, "ORIGINAL_RESOURCE", None) is None:
            config.ORIGINAL_RESOURCE = config.RESOURCE_TAB

        if config.ORIGINAL_RESOURCE == "cycle":
            if False and not getattr(config, "CYCLE_RESOURCES", None):
                config.CYCLE_RESOURCES = ["corn", "stone", "gold", "wood"]
                random.shuffle(config.CYCLE_RESOURCES)
                log.info("Khởi tạo chu kỳ tài nguyên ngẫu nhiên cho nhân vật: %s", config.CYCLE_RESOURCES)

            if not getattr(config, "CYCLE_RESOURCES", None):
                config.CYCLE_RESOURCES = list(_CYCLE_FARM_RESOURCES)

            if dispatched_count < len(config.CYCLE_RESOURCES):
                current_resource = config.CYCLE_RESOURCES[dispatched_count]
            else:
                current_resource = random.choice(config.CYCLE_RESOURCES)

            current_resource = _cycle_farm_resource_for_dispatch(dispatched_count)

            if config.RESOURCE_TAB != current_resource:
                config.RESOURCE_TAB = current_resource
                log.info(
                    "Xoay vòng tài nguyên (cycle) -> Đạo thứ %d chọn: %s",
                    dispatched_count + 1, current_resource.upper()
                )

        try:
            result = _dispatch_to_handler(
                device, screen, state, stuck_count,
            )
        except Exception:
            log.exception("Handler crash")
            if time.monotonic() >= device._back_locked_until:
                log.info("Handler crash -> bấm BACK để thoát trạng thái lỗi")
                try:
                    device.key("BACK")
                except Exception:
                    pass
            else:
                remaining = device._back_locked_until - time.monotonic()
                log.warning("Handler crash -> BACK bị khoá còn %.0fs (sau bật game/chuyển nhân vật)", remaining)
            pause(2.0)
            continue

        if result.goal_reached:
            dispatched_count += 1
            # After every dispatch, snapshot + OCR the n/N badge: this
            # auto-detects MAX_SLOTS and uses the GAME'S count as the
            # source of truth (more reliable than local counting since
            # the user may have had marches running before bot start).
            pause(0.8)
            try:
                post_screen = device.snapshot()
                n, mx = read_slot_badge(post_screen)
                if mx is not None and mx != config.MAX_SLOTS:
                    log.info(
                        "Tự dò sức chứa hàng chờ: %d (trước %d)",
                        mx, config.MAX_SLOTS,
                    )
                    config.MAX_SLOTS = mx
                if n is not None:
                    dispatched_count = n
            except Exception:
                log.exception("OCR huy hiệu sau khi gửi quân thất bại")
            log.info(
                "=== Đã gửi quân! tổng=%d/%d ===",
                dispatched_count, config.MAX_SLOTS,
            )
            if dispatched_count >= config.MAX_SLOTS:
                log.info("Hàng chờ đã đầy (%d/%d) sau khi gửi quân thành công. Hoàn thành chu trình FARM.", dispatched_count, config.MAX_SLOTS)
                _finish_current_workflow(remaining_workflows, "farm", "dispatch success full")
                continue

            # Cơ chế vào city rồi lại về world (tránh bám đuôi camera)
            enable_toggle = getattr(config, "ENABLE_CITY_WORLD_TOGGLE", True)
            prob = getattr(config, "CITY_WORLD_TOGGLE_PROBABILITY", 0.5)
            if enable_toggle:
                rand_val = random.random()
                if rand_val < prob:
                    log.info("Cơ chế City-World được kích hoạt ngẫu nhiên (%.2f < %.2f)", rand_val, prob)
                    _go_home_then_world(device)
                else:
                    log.info("Bỏ qua cơ chế City-World lần này (%.2f >= %.2f)", rand_val, prob)
            else:
                log.info("Cơ chế City-World đã bị tắt trong cấu hình.")
            wait_sec = random.randint(config.DELAY_AFTER_DISPATCH_MIN, config.DELAY_AFTER_DISPATCH_MAX)
            log.info("Sau khi gửi quân, chờ %d giây trước chu kỳ tiếp theo...", wait_sec)
            pause(float(wait_sec))
            last_state = None
            stuck_count = 0
            continue

        if result.slots_full:
            log.info("Hàng chờ đã đầy (slots_full) được phát hiện bởi handler. Hoàn thành chu trình FARM.")
            _finish_current_workflow(remaining_workflows, "farm", "handler slots_full")
            continue

        pause(result.sleep_after, result.sleep_after + 0.5)

    log.info(
        "Bot dừng. Tổng số lượt đã gửi quân: %d. Workflow con lai: %s",
        dispatched_count,
        remaining_workflows,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rok-bot")
    parser.add_argument("--serial", required=True, help="ADB serial")
    parser.add_argument("--max-iter", type=int, default=None)
    parser.add_argument(
        "--target-level", type=int, default=config.TARGET_LEVEL,
        help=(
            "Slider level the bot will try to set before searching "
            f"(default {config.TARGET_LEVEL})."
        ),
    )
    parser.add_argument(
        "--resource",
        choices=list(config._RESOURCE_TAB_X_PCT.keys())
        + [
            "cycle_random", "cycle_1", "cycle_2", "cycle_3", "cycle_4", "cycle_5",
            "ngo", "food", "crop",
        ],
        default=config.RESOURCE_TAB,
        help=(
            f"Resource tab to gather (default '{config.RESOURCE_TAB}'). "
            "barb=Người man rỡ, corn=Ngô (Đất trồng), wood=Trại xẻ gỗ, "
            "stone=Trầm tích đá, gold=Trầm tích vàng."
        ),
    )
    parser.add_argument(
        "--max-slots", type=int, default=config.MAX_SLOTS,
        help=f"March-queue capacity (default {config.MAX_SLOTS}).",
    )
    parser.add_argument(
        "--farm-scenario",
        choices=["random", "1", "2", "3"],
        default=config.FARM_SCENARIO,
        help="Cycle farm scenario: random, 1, 2, or 3.",
    )
    parser.add_argument(
        "--skip-level-adjust", action="store_true",
        help=(
            "Skip slider OCR + adjust; trust whatever level the panel "
            "already shows."
        ),
    )
    parser.add_argument(
        "--turn-wait-min", type=int,
        default=config.TURN_WAIT_SEC // 60,
        help=(
            "Minutes to sleep between queue-status checks once the "
            "queue is full (default 60)."
        ),
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("airtest", "PIL", "paddle", "paddleocr", "paddlex"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    config.TARGET_LEVEL = args.target_level
    config.MAX_SLOTS = args.max_slots
    res_map = {"ngo": "corn", "food": "corn", "crop": "corn"}
    args.resource = res_map.get(args.resource, args.resource)
    from core.config_io import split_resource_and_farm_scenario
    resource, farm_scenario = split_resource_and_farm_scenario(
        args.resource,
        args.farm_scenario,
    )
    config.RESOURCE_TAB = resource
    config.FARM_SCENARIO = farm_scenario
    config.SKIP_LEVEL_ADJUST = args.skip_level_adjust
    config.TURN_WAIT_SEC = args.turn_wait_min * 60
    log.info(
        "Cấu hình: tài nguyên=%s cấp=%d slot=%d bỏ-chỉnh-cấp=%s "
        "đợi-mỗi-lượt(phút)=%d",
        config.RESOURCE_TAB, config.TARGET_LEVEL, config.MAX_SLOTS,
        config.SKIP_LEVEL_ADJUST, args.turn_wait_min,
    )

    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    device = Device(args.serial, TEMPLATES_DIR)
    run(device, max_iterations=args.max_iter)
    return 0
