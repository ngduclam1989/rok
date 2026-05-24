"""ADB / Airtest device wrapper with template matching and input."""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from airtest.core.android.android import Android
from PIL import Image

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TapResult:
    matched: bool
    position: tuple[int, int] | None
    confidence: float


class Device:
    """Single Android device controlled via ADB + airtest.

    Coordinate system contract:
      * `snapshot()` returns an array sized to the CURRENT display rotation
        (e.g. 2400x1080 BGR when the phone is in landscape).
      * `tap()` / `swipe()` accept coords in that SAME space — they go
        through `adb shell input tap/swipe`, which respects the live
        rotation. We bypass airtest's MINITOUCH because its native-vs-
        rotated coord handling differs across devices and was the root
        cause of taps landing in the wrong place on this Samsung A71.
    """

    def __init__(self, serial: str, templates_dir: Path) -> None:
        self.serial = serial
        self.templates_dir = templates_dir

        if ":" in serial:
            try:
                from airtest.core.android.adb import ADB
                adb_path = ADB().adb_path
                subprocess.run([adb_path, "connect", serial], capture_output=True, check=False)
            except Exception:
                pass

        self._dev = Android(
            serialno=serial,
            cap_method="MINICAP",
            touch_method="MINITOUCH",
        )
        # Reuse airtest's resolved adb path so we don't depend on PATH.
        self._adb_path = self._dev.adb.adb_path
        log.info("Đã kết nối thiết bị %s (adb=%s)", serial, self._adb_path)

    def _adb_shell(self, *args: str) -> str:
        cmd = [self._adb_path, "-s", self.serial, "shell", *args]
        out = subprocess.run(  # noqa: S603 - airtest-resolved adb
            cmd, capture_output=True, text=True, check=False,
        )
        return out.stdout

    def info(self) -> dict[str, Any]:
        """Return model + screen size from a live snapshot.

        Reading the snapshot guarantees we get dimensions in the CURRENT
        display orientation (airtest's `display_info` returns native
        portrait values even on a rotated device, which breaks percent-
        based coords).
        """
        try:
            model = (
                self._dev.adb.shell("getprop ro.product.model").strip() or None
            )
        except Exception:
            log.exception("Đọc model thất bại cho %s", self.serial)
            model = None
        snap = self.snapshot()
        # numpy shape is (H, W, C)
        screen_h, screen_w = int(snap.shape[0]), int(snap.shape[1])
        return {
            "model": model,
            "screen_w": screen_w,
            "screen_h": screen_h,
        }

    def snapshot(self) -> np.ndarray:
        """Capture current screen as a BGR numpy array.

        Uses `adb shell screencap -p` because airtest's minicap setup
        sometimes fails on this device (the `mv` rename step errors out),
        falling back to javacap which returns the NATIVE portrait buffer
        even when the device is rotated. Going straight through screencap
        always returns the live display orientation, which keeps our
        snapshot / OCR / tap coords in a single coordinate system.
        """
        proc = subprocess.run(  # noqa: S603 - airtest-resolved adb
            [
                self._adb_path, "-s", self.serial,
                "exec-out", "screencap", "-p",
            ],
            capture_output=True,
            check=True,
        )
        img = Image.open(BytesIO(proc.stdout)).convert("RGB")
        arr = np.array(img)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def tap(self, x: int, y: int) -> None:
        log.debug("[%s] tap (%d,%d)", self.serial, x, y)
        self._adb_shell("input", "tap", str(int(x)), str(int(y)))

    def long_tap(self, x: int, y: int, duration_ms: int = 150) -> None:
        """Long tap via zero-distance swipe.

        Some buttons (slider minus/plus on this game) only register
        when held for a few frames — a single `input tap` is too fast
        and gets ignored. We model long-tap as a swipe with the same
        start/end coords for `duration_ms` milliseconds.
        """
        log.debug(
            "[%s] long_tap (%d,%d) %dms", self.serial, x, y, duration_ms
        )
        self._adb_shell(
            "input", "swipe",
            str(int(x)), str(int(y)),
            str(int(x)), str(int(y)),
            str(int(duration_ms)),
        )

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> None:
        log.debug(
            "[%s] swipe (%d,%d)->(%d,%d) %dms",
            self.serial, x1, y1, x2, y2, duration_ms,
        )
        self._adb_shell(
            "input", "swipe",
            str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)),
            str(int(duration_ms)),
        )

    def key(self, name: str) -> None:
        log.debug("[%s] key %s", self.serial, name)
        self._adb_shell("input", "keyevent", name.upper())

    def keep_awake(
        self,
        brightness: int | None = None,
        timeout_ms: int = 1_800_000,
    ) -> None:
        """Kéo dài thời gian tắt màn của Android.

        Mặc định KHÔNG đụng độ sáng (giữ độ sáng user đang đặt) — máy
        sẽ mát hơn khi độ sáng thấp. Chỉ khi truyền `brightness` mới
        chỉnh độ sáng.

        Mặc định timeout 30 phút (vừa đủ để bot ngủ 1h vẫn còn bật vài
        lần sleep cycle).
        """
        try:
            if brightness is not None:
                # IMPORTANT: tắt auto-brightness trước; nếu auto bật,
                # ghi screen_brightness sẽ bị cảm biến ánh sáng đè.
                self._adb_shell(
                    "settings", "put", "system",
                    "screen_brightness_mode", "0",
                )
                self._adb_shell(
                    "settings", "put", "system",
                    "screen_brightness", str(brightness),
                )
            self._adb_shell(
                "settings", "put", "system",
                "screen_off_timeout", str(timeout_ms),
            )
            log.info(
                "[%s] giữ máy sáng: độ sáng=%s, tắt màn sau=%ds",
                self.serial,
                "giữ nguyên" if brightness is None else str(brightness),
                timeout_ms // 1000,
            )
        except Exception:
            log.exception("Giữ máy sáng thất bại")

    def find_template(
        self,
        name: str,
        threshold: float = 0.8,
    ) -> tuple[int, int] | None:
        screen = self.snapshot()
        return self.find_template_in(name, screen, threshold)

    def find_template_in(
        self,
        name: str,
        screen: np.ndarray,
        threshold: float = 0.8,
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[int, int] | None:
        """Match `name` template against an already-captured screen.

        Direct cv2.matchTemplate with TM_CCOEFF_NORMED — we enforce the
        threshold ourselves because airtest's Template wraps multiple
        matchers and its threshold filtering has been unreliable on our
        test screens (template matched at conf 0.74 even when asked for
        threshold=0.8).

        `region` optionally constrains the search area as (x1,y1,x2,y2)
        in pixel coords. Returns the template-center coords in FULL
        screen space (not region-local).
        """
        path = self.templates_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        tpl_img = cv2.imread(str(path))
        if tpl_img is None:
            raise FileNotFoundError(f"Failed to read template: {path}")

        if region is not None:
            x1, y1, x2, y2 = region
            haystack = screen[y1:y2, x1:x2]
            ox, oy = x1, y1
        else:
            haystack = screen
            ox, oy = 0, 0

        th, tw = tpl_img.shape[:2]
        hh, hw = haystack.shape[:2]
        if th > hh or tw > hw:
            return None
        result = cv2.matchTemplate(haystack, tpl_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold:
            return None
        cx = ox + int(max_loc[0]) + tw // 2
        cy = oy + int(max_loc[1]) + th // 2
        return cx, cy

    def find_template_conf(
        self,
        name: str,
        screen: np.ndarray,
        region: tuple[int, int, int, int] | None = None,
    ) -> tuple[tuple[int, int], float] | None:
        """Like find_template_in but returns (position, confidence).

        Useful for debugging / threshold tuning.
        """
        path = self.templates_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        tpl_img = cv2.imread(str(path))
        if tpl_img is None:
            raise FileNotFoundError(f"Failed to read template: {path}")
        if region is not None:
            x1, y1, x2, y2 = region
            haystack = screen[y1:y2, x1:x2]
            ox, oy = x1, y1
        else:
            haystack = screen
            ox, oy = 0, 0
        th, tw = tpl_img.shape[:2]
        hh, hw = haystack.shape[:2]
        if th > hh or tw > hw:
            return None
        result = cv2.matchTemplate(haystack, tpl_img, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        cx = ox + int(max_loc[0]) + tw // 2
        cy = oy + int(max_loc[1]) + th // 2
        return (cx, cy), float(max_val)

    def exists(
        self, name: str, threshold: float = 0.8
    ) -> bool:
        return self.find_template(name, threshold) is not None

    def tap_template(
        self,
        name: str,
        threshold: float = 0.8,
        timeout: float = 0.0,
        poll_interval: float = 0.5,
    ) -> TapResult:
        """Find a template on screen and tap its center.

        If timeout > 0, retries until the template is visible or
        the deadline passes.
        """
        deadline = time.monotonic() + timeout
        while True:
            pos = self.find_template(name, threshold)
            if pos is not None:
                self.tap(*pos)
                return TapResult(
                    matched=True, position=pos, confidence=threshold
                )
            if time.monotonic() >= deadline:
                return TapResult(
                    matched=False, position=None, confidence=0.0
                )
            time.sleep(poll_interval)

    def start_game(self) -> None:
        """Tự động khởi chạy ứng dụng Rise of Kingdoms (com.rok.gp.vn) qua ADB."""
        from core.store import restart_game_app
        restart_game_app(self)

    def is_game_running(self) -> bool:
        """Kiểm tra xem ứng dụng game Rise of Kingdoms (com.rok.gp.vn) có đang chạy hay không."""
        try:
            pid_str = self._adb_shell("pidof", "com.rok.gp.vn").strip()
            return len(pid_str) > 0
        except Exception:
            return True

    def shutdown(self) -> None:
        """Tắt/đóng ứng dụng game trên thiết bị."""
        try:
            self._adb_shell("am", "force-stop", "com.rok.gp.vn")
            log.info("[%s] Đã đóng ứng dụng game com.rok.gp.vn", self.serial)
        except Exception as e:
            log.error("Không thể đóng game: %s", e)

