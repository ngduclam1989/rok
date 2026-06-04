"""Main loop + navigation helpers + CLI entry point.

``run(device, max_iterations)`` is the public entrypoint — it sets up
signal handling, walks the state machine, and orchestrates the
dispatch / poll-for-slot / sleep cycle.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta

import numpy as np

from core import ocr
from core.device import Device

from . import config
from .constants import CAPTURES_DIR, STOP_FLAG, TEMPLATES_DIR
from .detection import detect_state, is_lock_screen
from .geometry import pct_to_px, region_pct_to_px, tap_template
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
    reset_slider_state,
)
from .readers import read_march_panel_times, read_slot_badge
from .signals import (
    install_signal_handler,
    pause,
    register_serial,
    should_stop,
    sleep_with_stop_check,
    sleep_with_stop_check_exact,
)
from .state import S

log = logging.getLogger(__name__)


def _cleanup_captures() -> None:
    """Delete successful PNG images in captures/, only keeping the FAILED ones."""
    try:
        if not CAPTURES_DIR.exists():
            return
        for p in CAPTURES_DIR.glob("*.png"):
            if "FAILED" not in p.name:
                p.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Lỗi dọn dẹp ảnh captures thành công: %s", e)


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
            time.sleep(20.0)
            continue

        if state == S.LOCK_SCREEN:
            log.info("Game đang khoá -> mở khoá")
            handle_lock_screen(device, screen)
            time.sleep(2.5)
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
            time.sleep(2.5)
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

        # State UNKNOWN: Khởi động game com.rok.gp.vn tự động
        log.warning("Đang ở %s -> Tự động khởi động game...", state.value)
        device.start_game()
        time.sleep(15.0)

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
    time.sleep(2.5)

    try:
        screen = device.snapshot()
    except Exception:
        log.exception("Snapshot lần 2 trong cleanup thất bại")
        return
    ocr.clear_cache()
    _tap_map_toggle(screen)
    time.sleep(2.5)

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
        else:
            x, y = pct_to_px(screen, 97.0, 5.0)
            device.tap(x, y)
            time.sleep(0.5)
            try:
                device.key("BACK")
            except Exception:
                pass
        time.sleep(1.5)
    log.warning(
        "Không đưa về được world sau %d lần thử -> bỏ qua",
        max_attempts,
    )


def _handle_queue_full(device: Device, switched_account: bool) -> bool:
    """Xử lý khi hàng chờ đầy: đổi acc hoặc tắt giả lập nếu cả 2 acc đều đầy.

    Trả về True nếu đổi acc thành công để tiếp tục chạy, False nếu dừng bot và tắt giả lập.
    """
    log.info("=== Hàng chờ của tài khoản hiện tại đã đầy (%d/%d)! ===", config.MAX_SLOTS, config.MAX_SLOTS)
    _return_to_world(device, max_attempts=4)
    _cleanup_captures()

    if switched_account:
        log.info("=== Cả 2 tài khoản đều đã đầy hàng chờ/hoàn thành! Đang dừng bot... ===")
        return False

    log.info("=== Tiến hành chuyển sang tài khoản thứ 2... ===")
    success = handle_switch_account(device)
    if success:
        log.info("Chuyển tài khoản thành công! Đợi 10s cho game load tài khoản mới...")
        time.sleep(10.0)
        return True
    else:
        log.warning("Chuyển tài khoản thất bại! Đang dừng bot...")
        return False


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





def run(device: Device, max_iterations: int | None = None) -> None:
    install_signal_handler()
    register_serial(device.serial)
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
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

    # B2: mở game, chờ 10s cho game ổn định
    log.info("B2: Mở game Rise of Kingdoms (com.rok.gp.vn)...")
    try:
        device._adb_shell("monkey", "-p", "com.rok.gp.vn", "-c", "android.intent.category.LAUNCHER", "1")
    except Exception as e:
        log.error("Không thể mở game qua monkey: %s", e)

    log.info("Đang chờ 10s cho giao diện game ổn định...")
    time.sleep(10.0)

    # B3: ấn vào giữa màn hình
    log.info("B3: Ấn vào giữa màn hình...")
    try:
        screen = device.snapshot()
        h, w = screen.shape[:2]
        cx, cy = int(w * 0.5), int(h * 0.5)
        device.tap(cx, cy)
    except Exception as e:
        log.warning("Không chụp được màn hình, dùng tọa độ mặc định (1200, 540): %s", e)
        try:
            device.tap(1200, 540)
        except Exception:
            pass
    time.sleep(5.0)

    # Normalise to WORLD before entering the main loop.
    _initial_navigate_to_world(device)

    last_state: S | None = None
    stuck_count = 0
    iteration = 0
    dispatched_count = 0
    state_history: list[S] = []
    reset_slider_state()
    switched_account = False

    # Read the n/N badge once on startup so we know the current queue
    # state (user may already have marches out) and the account's
    # real MAX_SLOTS (varies with VIP / talents).
    try:
        init_screen = device.snapshot()
        ocr.clear_cache()
        n0, mx0 = read_slot_badge(init_screen)
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
                "Không đọc được huy hiệu ban đầu -> coi như 0/%d",
                config.MAX_SLOTS,
            )
            dispatched_count = 0
    except Exception:
        log.exception("Đọc huy hiệu ban đầu thất bại")
        dispatched_count = 0

    # Nếu hàng chờ đã đầy từ đầu:
    if dispatched_count >= config.MAX_SLOTS and not should_stop():
        success = _handle_queue_full(device, switched_account)
        if not success:
            return

        switched_account = True
        log.info("Bắt đầu lại quy trình farm từ đầu với tài khoản mới...")
        _initial_navigate_to_world(device)

        # Reset trạng thái
        last_state = None
        stuck_count = 0
        dispatched_count = 0
        reset_slider_state()

        # Đọc lại huy hiệu ban đầu cho tài khoản mới
        try:
            init_screen = device.snapshot()
            ocr.clear_cache()
            n0, mx0 = read_slot_badge(init_screen)
            if mx0 is not None and mx0 > 0:
                config.MAX_SLOTS = mx0
            if n0 is not None:
                dispatched_count = n0
                log.info("Hàng chờ tài khoản mới ban đầu: %d/%d", n0, config.MAX_SLOTS)
            else:
                log.warning("Không đọc được huy hiệu tài khoản mới -> coi như 0/%d", config.MAX_SLOTS)
                dispatched_count = 0
        except Exception:
            log.exception("Đọc huy hiệu tài khoản mới thất bại")
            dispatched_count = 0

        if dispatched_count >= config.MAX_SLOTS:
            _handle_queue_full(device, switched_account)
            return

    while not should_stop():
        iteration += 1
        if max_iterations and iteration > max_iterations:
            log.info(
                "Đã đạt giới hạn %d vòng lặp -> dừng", max_iterations,
            )
            break

        log.info(
            "=== vòng %d (đã gửi=%d) ===",
            iteration, dispatched_count,
        )

        # Cứ 5 vòng kiểm tra xem game còn mở hay không, nếu đã mất thì mở lại
        if iteration > 1 and iteration % 5 == 0:
            log.info("Kiểm tra định kỳ xem ứng dụng game còn chạy không...")
            if not device.is_game_running():
                log.warning("Phát hiện ứng dụng game đã bị đóng hoặc crash! Đang tự động khởi động lại...")
                device.start_game()
                time.sleep(15.0)
                _initial_navigate_to_world(device)

        t0 = time.monotonic()
        try:
            screen = device.snapshot()
        except Exception:
            log.exception("Chụp màn hình thất bại! Thiết bị có thể đã offline. Tiến hành tự động khôi phục kết nối...")
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
                
                # Tự động khởi chạy lại game
                device.start_game()
                time.sleep(15.0)
            except Exception as re_err:
                log.error("Tự động khôi phục kết nối thất bại: %s. Thử lại sau 5s...", re_err)
                time.sleep(5.0)
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
                        success = _handle_queue_full(device, switched_account)
                        if not success:
                            return
                        switched_account = True
                        log.info("Bắt đầu lại quy trình farm từ đầu với tài khoản mới...")
                        _initial_navigate_to_world(device)
                        last_state = None
                        stuck_count = 0
                        dispatched_count = 0
                        reset_slider_state()

                        # Đọc lại huy hiệu ban đầu cho tài khoản mới
                        try:
                            init_screen = device.snapshot()
                            ocr.clear_cache()
                            n0, mx0 = read_slot_badge(init_screen)
                            if mx0 is not None and mx0 > 0:
                                config.MAX_SLOTS = mx0
                            if n0 is not None:
                                dispatched_count = n0
                                log.info("Hàng chờ tài khoản mới ban đầu: %d/%d", n0, config.MAX_SLOTS)
                            else:
                                log.warning("Không đọc được huy hiệu tài khoản mới -> coi như 0/%d", config.MAX_SLOTS)
                                dispatched_count = 0
                        except Exception:
                            dispatched_count = 0

                        if dispatched_count >= config.MAX_SLOTS:
                            _handle_queue_full(device, switched_account)
                            return
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

        # === ĐOẠN CODE MỚI: Xoay vòng tài nguyên (1 ngô, 1 đá, 1 vàng, 2 gỗ) ===
        if getattr(config, "ORIGINAL_RESOURCE", None) is None:
            config.ORIGINAL_RESOURCE = config.RESOURCE_TAB

        if config.ORIGINAL_RESOURCE == "cycle":
            cycle_list = ["corn", "stone", "gold", "wood", "wood"]
            current_resource = cycle_list[dispatched_count % len(cycle_list)]
            if config.RESOURCE_TAB != current_resource:
                config.RESOURCE_TAB = current_resource
                log.info(
                    "Xoay vòng tài nguyên (cycle) -> Đạo thứ %d chọn: %s",
                    dispatched_count + 1, current_resource.upper()
                )
        # =======================================================================

        try:
            result = _dispatch_to_handler(
                device, screen, state, stuck_count,
            )
        except Exception:
            log.exception("Handler crash -> bấm BACK khẩn cấp")
            try:
                device.key("BACK")
            except Exception:
                pass
            time.sleep(2.0)
            continue

        if result.goal_reached:
            dispatched_count += 1
            # After every dispatch, snapshot + OCR the n/N badge: this
            # auto-detects MAX_SLOTS and uses the GAME'S count as the
            # source of truth (more reliable than local counting since
            # the user may have had marches running before bot start).
            time.sleep(1.5)
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
                success = _handle_queue_full(device, switched_account)
                if not success:
                    return

                switched_account = True
                log.info("Bắt đầu lại quy trình farm từ đầu với tài khoản mới...")
                _initial_navigate_to_world(device)

                # Reset trạng thái
                last_state = None
                stuck_count = 0
                dispatched_count = 0
                reset_slider_state()

                # Đọc lại huy hiệu ban đầu cho tài khoản mới
                try:
                    init_screen = device.snapshot()
                    ocr.clear_cache()
                    n0, mx0 = read_slot_badge(init_screen)
                    if mx0 is not None and mx0 > 0:
                        config.MAX_SLOTS = mx0
                    if n0 is not None:
                        dispatched_count = n0
                        log.info("Hàng chờ tài khoản mới ban đầu: %d/%d", n0, config.MAX_SLOTS)
                    else:
                        log.warning("Không đọc được huy hiệu tài khoản mới -> coi như 0/%d", config.MAX_SLOTS)
                        dispatched_count = 0
                except Exception:
                    log.exception("Đọc huy hiệu tài khoản mới thất bại")
                    dispatched_count = 0

                if dispatched_count >= config.MAX_SLOTS:
                    _handle_queue_full(device, switched_account)
                    return
                continue

            _go_home_then_world(device)
            log.info("Nghỉ ngắn 1-2s trước chu kỳ thu thập tiếp theo")
            pause(1, 2)
            last_state = None
            stuck_count = 0
            continue

        if result.slots_full:
            success = _handle_queue_full(device, switched_account)
            if not success:
                return

            switched_account = True
            log.info("Bắt đầu lại quy trình farm từ đầu với tài khoản mới...")
            _initial_navigate_to_world(device)

            # Reset trạng thái
            last_state = None
            stuck_count = 0
            dispatched_count = 0
            reset_slider_state()

            # Đọc lại huy hiệu ban đầu cho tài khoản mới
            try:
                init_screen = device.snapshot()
                ocr.clear_cache()
                n0, mx0 = read_slot_badge(init_screen)
                if mx0 is not None and mx0 > 0:
                    config.MAX_SLOTS = mx0
                if n0 is not None:
                    dispatched_count = n0
                    log.info("Hàng chờ tài khoản mới ban đầu: %d/%d", n0, config.MAX_SLOTS)
                else:
                    log.warning("Không đọc được huy hiệu tài khoản mới -> coi như 0/%d", config.MAX_SLOTS)
                    dispatched_count = 0
            except Exception:
                log.exception("Đọc huy hiệu tài khoản mới thất bại")
                dispatched_count = 0

            if dispatched_count >= config.MAX_SLOTS:
                _handle_queue_full(device, switched_account)
                return
            continue

        pause(result.sleep_after, result.sleep_after + 0.5)

    # Best-effort: leave the game on WORLD so a subsequent restart
    # doesn't begin stuck inside a popup/panel.
    _return_to_world(device, max_attempts=6)
    _cleanup_captures()
    log.info(
        "Bot dừng. Tổng số lượt đã gửi quân: %d", dispatched_count,
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
        choices=list(config._RESOURCE_TAB_X_PCT.keys()) + ["ngo", "food", "crop"],
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
    config.RESOURCE_TAB = args.resource
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
