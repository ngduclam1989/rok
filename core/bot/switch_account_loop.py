"""Standalone switch-account stress loop."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from pathlib import Path

import cv2

from core.config_io import load_bot_fleet_config
from core.device import Device

from . import config
from .runtime import _handle_logo_18_check, _prepare_world_only
from .handlers.navigation import (
    handle_switch_account,
    handle_switch_to_first_account,
    reset_account_run_tracking,
)

log = logging.getLogger(__name__)


def _load_accounts(path: Path) -> list[str]:
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except Exception as err:
        log.warning("Khong doc duoc account list %s: %s", path, err)
        return []


def _save_failure_screen(device: Device, out_dir: Path, loop_index: int) -> None:
    try:
        screen = device.snapshot()
    except Exception as err:
        log.warning("[switch-loop] Khong chup duoc man fail: %s", err)
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_serial = str(device.serial).replace(":", "_").replace(".", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out_dir / f"switch_loop_fail_{safe_serial}_L{loop_index}_{stamp}.png"
    try:
        cv2.imwrite(str(out), screen)
        log.info("[switch-loop] Da luu anh fail: %s", out)
    except Exception as err:
        log.warning("[switch-loop] Luu anh fail loi: %s", err)


def _seed_phase(accounts: list[str], phase: str) -> None:
    if not accounts:
        reset_account_run_tracking()
        return
    if phase == "reverse":
        reset_account_run_tracking(accounts[-1])
        log.info("[switch-loop] Phase reverse: seed first=%s", accounts[-1])
    elif phase == "force_forward_start":
        reset_account_run_tracking(accounts[0])
        from .handlers import navigation as nav

        nav._USED_ACCOUNTS.update(accounts)
        log.info("[switch-loop] Phase force_forward_start: force wrap ve %s", accounts[0])
    else:
        reset_account_run_tracking(accounts[0])
        log.info("[switch-loop] Phase forward: seed first=%s", accounts[0])


def run_switch_account_loop(
    *,
    serial: str,
    templates_dir: Path,
    devices_file: Path,
    account_file: Path,
    control_mode: str | None = None,
    loops: int = 0,
    wait_after_switch_sec: float = 60.0,
    fail_sleep_min_sec: float = 20.0,
    fail_sleep_max_sec: float = 35.0,
    kill_after_fails: int = 5,
    save_fail_screens: bool = True,
    open_game: bool = True,
) -> int:
    """Run only the account-switch flow repeatedly.

    loops=0 means forever. The loop alternates:
    forward 6->...->last, wrap last->6, reverse 6->...->last, then repeat.
    """
    if control_mode is None:
        try:
            fleet_cfg = load_bot_fleet_config(devices_file)
            dev_cfg = next((c for c in fleet_cfg if c.serial == serial), None)
            control_mode = dev_cfg.control_mode if dev_cfg else "scrcpy"
        except Exception:
            control_mode = "scrcpy"

    accounts = _load_accounts(account_file)
    phase = "forward"
    _seed_phase(accounts, phase)

    device = Device(serial, templates_dir, control_mode=control_mode)
    consecutive_fails = 0
    completed = 0
    interrupted = False

    try:
        if open_game:
            log.info("[switch-loop] Mo game truoc khi bat dau...")
            device.start_game()

        while loops <= 0 or completed < loops:
            loop_index = completed + 1
            log.info(
                "[switch-loop] === loop %d%s phase=%s fails=%d ===",
                loop_index,
                "" if loops <= 0 else f"/{loops}",
                phase,
                consecutive_fails,
            )
            try:
                _handle_logo_18_check(device)
                _prepare_world_only(device)
                result = handle_switch_account(device, wrap_to_first=True)
            except KeyboardInterrupt:
                interrupted = True
                raise
            except Exception as err:
                log.exception("[switch-loop] Loi trong loop chuyen acc: %s", err)
                result = "failed"

            log.info("[switch-loop] loop %d result=%s", loop_index, result)
            completed += 1

            if result == "failed":
                consecutive_fails += 1
                if save_fail_screens:
                    _save_failure_screen(device, Path("core/tmp/switch_loop"), loop_index)
                if consecutive_fails > kill_after_fails:
                    log.warning(
                        "[switch-loop] Fail lien tiep %d > %d -> kill app, mo lai game, retry tiep",
                        consecutive_fails,
                        kill_after_fails,
                    )
                    try:
                        device.shutdown()
                    except Exception:
                        pass
                    time.sleep(3.0)
                    device.start_game()
                    consecutive_fails = 0
                else:
                    wait_fail = random.uniform(fail_sleep_min_sec, fail_sleep_max_sec)
                    log.warning("[switch-loop] Fail -> cho %.1fs roi retry", wait_fail)
                    time.sleep(wait_fail)
                continue

            consecutive_fails = 0
            if result == "wrapped":
                if phase == "forward":
                    phase = "reverse"
                elif phase == "reverse":
                    phase = "force_forward_start"
                else:
                    phase = "forward"
                _seed_phase(accounts, phase)

            if wait_after_switch_sec > 0:
                log.info("[switch-loop] Cho %.1fs cho account moi load...", wait_after_switch_sec)
                time.sleep(wait_after_switch_sec)
    finally:
        if loops > 0 and not interrupted and accounts:
            log.info("[switch-loop] Da chay xong %d loop -> ep dua ve account dau: %s", completed, accounts[0])
            try:
                _handle_logo_18_check(device)
                _prepare_world_only(device)
                result = handle_switch_to_first_account(device)
                log.info("[switch-loop] Ket qua dua ve account dau: %s", result)
                if result != "failed" and wait_after_switch_sec > 0:
                    log.info("[switch-loop] Cho %.1fs cho account dau load on dinh...", wait_after_switch_sec)
                    time.sleep(wait_after_switch_sec)
            except Exception:
                log.exception("[switch-loop] Dua ve account dau sau khi chay xong that bai")
        try:
            device.close()
        except Exception:
            pass

    return 0
