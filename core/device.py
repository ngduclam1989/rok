"""ADB / Airtest device wrapper with template matching and input."""
from __future__ import annotations

import logging
import subprocess
import time
import warnings
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

    def __init__(
        self,
        serial: str,
        templates_dir: Path,
        control_mode: str = "adb",
        scrcpy_window_path: str | None = None,
    ) -> None:
        self.serial = serial
        self.templates_dir = templates_dir
        self.control_mode = control_mode
        self._hwnd = None
        self._top_hwnd = None
        self._scrcpy_client = None
        self._scrcpy_available = False
        self._scrcpy_window_proc: subprocess.Popen[bytes] | None = None
        self._scrcpy_window_log_path: Path | None = None

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
        log.info("Đã kết nối thiết bị %s (adb=%s, control_mode=%s)", serial, self._adb_path, control_mode)

        if control_mode == "physical_mouse":
            self._hwnd = self._find_hwnd()
            if self._hwnd:
                log.info("[%s] Đã tìm thấy HWND Bluestacks: %s (cha: %s)", serial, self._hwnd, self._top_hwnd)
            else:
                log.error("[%s] KHÔNG tìm thấy HWND Bluestacks cho thiết bị này. Sẽ dùng ADB làm dự phòng.", serial)

        if control_mode == "scrcpy":
            self._start_scrcpy_client()

        if scrcpy_window_path:
            self._start_scrcpy_window(scrcpy_window_path)

    def _start_scrcpy_window(self, scrcpy_window_path: str) -> None:
        """Open an external scrcpy window for watching and manual control."""
        raw_path = str(scrcpy_window_path).strip().strip('"')
        if not raw_path:
            log.warning(
                "[%s] open_scrcpy_window=true nhung scrcpy_path dang rong",
                self.serial,
            )
            return

        scrcpy_path = Path(raw_path)
        if not scrcpy_path.is_absolute():
            scrcpy_path = Path(__file__).resolve().parent.parent / scrcpy_path
        if scrcpy_path.is_dir() or scrcpy_path.suffix == "":
            scrcpy_path = scrcpy_path / "scrcpy.exe"

        if not scrcpy_path.exists():
            log.error(
                "[%s] Khong tim thay scrcpy.exe tai: %s",
                self.serial,
                scrcpy_path,
            )
            return

        cmd = [
            str(scrcpy_path),
            "--serial",
            self.serial,
            "--stay-awake",
            "--max-fps",
            "15",
            "--window-title",
            f"RoK Bot - {self.serial}",
        ]
        creationflags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        project_root = Path(__file__).resolve().parent.parent
        logs_dir = project_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        safe_serial = str(self.serial).replace(":", "_").replace(".", "_")
        self._scrcpy_window_log_path = logs_dir / f"scrcpy_{safe_serial}.log"

        try:
            with self._scrcpy_window_log_path.open("ab") as scrcpy_log:
                self._scrcpy_window_proc = subprocess.Popen(
                    cmd,
                    cwd=str(scrcpy_path.parent),
                    stdout=scrcpy_log,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )  # noqa: S603 - user-configured local executable

            time.sleep(0.5)
            exit_code = self._scrcpy_window_proc.poll()
            if exit_code is not None:
                detail = ""
                try:
                    detail = self._scrcpy_window_log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    ).strip()
                except Exception:
                    detail = ""
                self._scrcpy_window_proc = None
                log.error(
                    "[%s] scrcpy.exe thoat ngay voi ma %s. Log: %s",
                    self.serial,
                    exit_code,
                    detail or self._scrcpy_window_log_path,
                )
                return

            log.info(
                "[%s] Da mo cua so scrcpy: %s (log=%s)",
                self.serial,
                scrcpy_path,
                self._scrcpy_window_log_path,
            )
        except Exception as e:
            self._scrcpy_window_proc = None
            log.error(
                "[%s] Khong the mo cua so scrcpy (%s): %s",
                self.serial,
                scrcpy_path,
                e,
            )

    def _start_scrcpy_client(self) -> None:
        """Start scrcpy video/control sockets for low-latency capture and input."""
        try:
            warnings.filterwarnings(
                "ignore",
                message="pkg_resources is deprecated as an API.*",
                category=UserWarning,
            )
            import scrcpy

            if not getattr(scrcpy.Client, "_rok_stream_loop_patched", False):
                original_stream_loop = scrcpy.Client._Client__stream_loop

                def guarded_stream_loop(client):
                    try:
                        original_stream_loop(client)
                    except Exception as exc:
                        client.alive = False
                        device = getattr(client, "device", None)
                        serial = getattr(device, "serial", None) or getattr(device, "_serial", None) or "unknown"
                        log.warning(
                            "[%s] scrcpy video stream lỗi (%s). Sẽ dùng ADB dự phòng.",
                            serial,
                            exc,
                        )

                scrcpy.Client._Client__stream_loop = guarded_stream_loop
                scrcpy.Client._rok_stream_loop_patched = True

            self._scrcpy_client = scrcpy.Client(
                device=self.serial,
                max_fps=15,
                bitrate=4_000_000,
                stay_awake=True,
            )
            self._scrcpy_client.start(threaded=True)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if self._scrcpy_client.last_frame is not None:
                    self._scrcpy_available = True
                    break
                time.sleep(0.05)
            if self._scrcpy_available:
                log.info("[%s] Đã kích hoạt scrcpy control + video stream", self.serial)
            elif not bool(getattr(self._scrcpy_client, "alive", False)):
                self._scrcpy_client = None
                log.warning(
                    "[%s] scrcpy stream da dung trong luc khoi dong; dung ADB du phong.",
                    self.serial,
                )
            else:
                log.warning(
                    "[%s] scrcpy đã khởi động nhưng chưa có frame; tạm dùng ADB snapshot cho đến khi stream sẵn sàng",
                    self.serial,
                )
        except Exception as e:
            self._scrcpy_client = None
            self._scrcpy_available = False
            log.error(
                "[%s] Không thể khởi tạo scrcpy client: %s. Sẽ dùng ADB dự phòng.",
                self.serial,
                e,
            )

    def _scrcpy_ready(self) -> bool:
        return (
            self.control_mode == "scrcpy"
            and self._scrcpy_client is not None
            and bool(getattr(self._scrcpy_client, "alive", True))
        )

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
        if self._scrcpy_ready():
            frame = self._scrcpy_client.last_frame
            if frame is not None:
                self._scrcpy_available = True
                return frame.copy()

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

    def _find_hwnd(self) -> int | None:
        """Tìm HWND của cửa sổ Bluestacks ứng với cổng ADB hiện tại."""
        try:
            import win32gui
            import win32process
            import psutil
            from core.bot.bluestack import get_instance_name_by_port

            s = str(self.serial).strip()
            port_str = s.split(":")[-1] if ":" in s else s
            try:
                port = int(port_str)
            except ValueError:
                return None

            instance_name = get_instance_name_by_port(port)
            if not instance_name:
                log.warning("[%s] Không tìm thấy tên instance Bluestacks cho cổng %d", self.serial, port)
                return None

            target_pid = None
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'HD-Player.exe' and proc.info['cmdline']:
                        cmdline = proc.info['cmdline']
                        if '--instance' in cmdline:
                            idx = cmdline.index('--instance')
                            if idx + 1 < len(cmdline) and cmdline[idx+1] == instance_name:
                                target_pid = proc.info['pid']
                                break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not target_pid:
                log.warning("[%s] Không tìm thấy process HD-Player.exe cho instance '%s'", self.serial, instance_name)
                return None

            top_hwnds = []
            def enum_windows_callback(hwnd, extra):
                if win32gui.IsWindowVisible(hwnd):
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid == target_pid:
                        title = win32gui.GetWindowText(hwnd)
                        cls = win32gui.GetClassName(hwnd)
                        # Bluestacks sử dụng lớp cửa sổ bắt đầu bằng 'Qt' hoặc có BlueStacks trong tiêu đề
                        if title and (cls.startswith("Qt") or "BlueStacks" in title):
                            top_hwnds.append(hwnd)
                return True

            win32gui.EnumWindows(enum_windows_callback, None)
            if not top_hwnds:
                return None

            top_hwnd = top_hwnds[0]
            
            # Tìm cửa sổ con thực sự vẽ màn hình game (lớp BlueStacksApp) để làm mốc tọa độ không bị lệch do toolbar
            render_hwnd = [None]
            def enum_child_callback(hwnd, _):
                cls = win32gui.GetClassName(hwnd)
                if cls == "BlueStacksApp" or "BlueStacks" in cls:
                    render_hwnd[0] = hwnd
                    return False  # stop enum
                return True
                
            try:
                win32gui.EnumChildWindows(top_hwnd, enum_child_callback, None)
            except Exception:
                pass
                
            self._top_hwnd = top_hwnd
            return render_hwnd[0] if render_hwnd[0] else top_hwnd
        except Exception as e:
            log.error("[%s] Lỗi khi tìm HWND Bluestacks: %s", self.serial, e)
        return None

    def _get_pc_coords(self, game_x: int, game_y: int) -> tuple[int, int] | None:
        """Quy đổi tọa độ game sang tọa độ màn hình PC của cửa sổ Bluestacks."""
        try:
            import win32gui
            # Lấy kích thước ảnh chụp hiện tại làm hệ tọa độ của game
            snap = self.snapshot()
            game_h, game_w = snap.shape[:2]

            rect = win32gui.GetClientRect(self._hwnd)
            left, top = win32gui.ClientToScreen(self._hwnd, (0, 0))
            right, bottom = win32gui.ClientToScreen(self._hwnd, (rect[2], rect[3]))

            win_w = right - left
            win_h = bottom - top

            pc_x = left + int(game_x * win_w / game_w)
            pc_y = top + int(game_y * win_h / game_h)
            return pc_x, pc_y
        except Exception as e:
            log.error("[%s] Lỗi quy đổi tọa độ chuột: %s", self.serial, e)
            return None

    def _physical_click(self, game_x: int, game_y: int) -> None:
        import win32gui
        import win32api
        import win32con
        
        # Đưa Bluestacks lên trước bằng cửa sổ cha
        try:
            win32gui.SetForegroundWindow(self._top_hwnd)
            time.sleep(0.05)
        except Exception:
            pass

        coords = self._get_pc_coords(game_x, game_y)
        if coords:
            pc_x, pc_y = coords
            log.debug("[%s] physical click (%d, %d)", self.serial, pc_x, pc_y)
            
            from core.bot.input_lock import move_lock_position_smooth, reset_lock_position
            move_lock_position_smooth(pc_x, pc_y, duration=0.15)
            time.sleep(0.05)  # Chờ chuột di chuyển tới vị trí khóa ổn định
            
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, pc_x, pc_y, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, pc_x, pc_y, 0, 0)
            time.sleep(0.05)  # Chờ Windows nhận sự kiện nhấc chuột trước khi nhả khóa
            
            reset_lock_position()

    def _physical_long_click(self, game_x: int, game_y: int, duration_ms: int) -> None:
        import win32gui
        import win32api
        import win32con
        
        try:
            win32gui.SetForegroundWindow(self._top_hwnd)
            time.sleep(0.05)
        except Exception:
            pass

        coords = self._get_pc_coords(game_x, game_y)
        if coords:
            pc_x, pc_y = coords
            log.debug("[%s] physical long click (%d, %d) %dms", self.serial, pc_x, pc_y, duration_ms)
            
            from core.bot.input_lock import move_lock_position_smooth, reset_lock_position
            move_lock_position_smooth(pc_x, pc_y, duration=0.15)
            time.sleep(0.05)
            
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, pc_x, pc_y, 0, 0)
            time.sleep(duration_ms / 1000.0)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, pc_x, pc_y, 0, 0)
            time.sleep(0.05)
            
            reset_lock_position()

    def _physical_swipe(self, game_x1: int, game_y1: int, game_x2: int, game_y2: int, duration_ms: int) -> None:
        import win32gui
        import win32api
        import win32con
        
        try:
            win32gui.SetForegroundWindow(self._top_hwnd)
            time.sleep(0.05)
        except Exception:
            pass

        coords1 = self._get_pc_coords(game_x1, game_y1)
        coords2 = self._get_pc_coords(game_x2, game_y2)
        if coords1 and coords2:
            pc_x1, pc_y1 = coords1
            pc_x2, pc_y2 = coords2
            log.debug("[%s] physical swipe (%d, %d) -> (%d, %d)", self.serial, pc_x1, pc_y1, pc_x2, pc_y2)
            
            from core.bot.input_lock import move_lock_position_smooth, reset_lock_position
            
            # Move smoothly to the start, then drag along the Bezier path.
            move_lock_position_smooth(pc_x1, pc_y1, duration=0.15)
            time.sleep(0.05)
            
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, pc_x1, pc_y1, 0, 0)
            time.sleep(0.05)
            
            move_lock_position_smooth(
                pc_x2,
                pc_y2,
                duration=max(0.05, duration_ms / 1000.0),
            )
                
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, pc_x2, pc_y2, 0, 0)
            time.sleep(0.05)
            
            reset_lock_position()

    def _resolve_press_coords(self, x: int, y: int) -> tuple[int, int]:
        """Resolve the final coordinate to press before any ADB/mouse action."""
        from core.mouse import get_gaussian_click_coords

        press_x, press_y = get_gaussian_click_coords(x, y)
        log.debug(
            "[%s] press coords resolved: target=(%d,%d) gaussian=(%d,%d)",
            self.serial,
            x,
            y,
            press_x,
            press_y,
        )
        return press_x, press_y

    def tap(self, x: int, y: int) -> None:
        press_x, press_y = self._resolve_press_coords(x, y)
        if self._scrcpy_ready():
            try:
                import scrcpy

                self._scrcpy_client.control.touch(
                    int(press_x),
                    int(press_y),
                    scrcpy.ACTION_DOWN,
                )
                self._scrcpy_client.control.touch(
                    int(press_x),
                    int(press_y),
                    scrcpy.ACTION_UP,
                )
                return
            except Exception as e:
                log.warning("[%s] scrcpy tap lỗi (%s), fallback ADB", self.serial, e)
        if self.control_mode == "physical_mouse" and self._hwnd:
            self._physical_click(press_x, press_y)
        else:
            self._adb_shell("input", "tap", str(int(press_x)), str(int(press_y)))

    def long_tap(self, x: int, y: int, duration_ms: int = 150) -> None:
        """Long tap via zero-distance swipe."""
        press_x, press_y = self._resolve_press_coords(x, y)
        log.debug(
            "[%s] long_tap press=(%d,%d) %dms",
            self.serial,
            press_x,
            press_y,
            duration_ms,
        )
        if self._scrcpy_ready():
            try:
                import scrcpy

                self._scrcpy_client.control.touch(
                    int(press_x),
                    int(press_y),
                    scrcpy.ACTION_DOWN,
                )
                time.sleep(max(0, duration_ms) / 1000.0)
                self._scrcpy_client.control.touch(
                    int(press_x),
                    int(press_y),
                    scrcpy.ACTION_UP,
                )
                return
            except Exception as e:
                log.warning("[%s] scrcpy long_tap lỗi (%s), fallback ADB", self.serial, e)
        if self.control_mode == "physical_mouse" and self._hwnd:
            self._physical_long_click(press_x, press_y, duration_ms)
        else:
            self._adb_shell(
                "input", "swipe",
                str(int(press_x)), str(int(press_y)),
                str(int(press_x)), str(int(press_y)),
                str(int(duration_ms)),
            )

    def save_swipe_path_image(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Capture screenshot and draw the mouse swipe path from (x1, y1) to (x2, y2)."""
        try:
            from core.bot import config
            if not getattr(config, "SAVE_DEBUG_IMAGES", False):
                return

            screen = self.snapshot()
            if screen is None:
                return

            from core.bot.constants import CAPTURES_DIR
            out_dir = CAPTURES_DIR / "mouse_paths"
            out_dir.mkdir(parents=True, exist_ok=True)

            from core.mouse import mouse_bez
            points = mouse_bez((x1, y1), (x2, y2), deviation=8, speed=1)
            pts = np.array([[int(round(pt[0])), int(round(pt[1]))] for pt in points], dtype=np.int32)
            pts = pts.reshape((-1, 1, 2))

            drawn = screen.copy()

            # Draw the curve trajectory in neon green
            cv2.polylines(drawn, [pts], isClosed=False, color=(0, 255, 0), thickness=3, lineType=cv2.LINE_AA)

            # Draw starting point (green circle with white center)
            cv2.circle(drawn, (int(x1), int(y1)), 8, (0, 255, 0), -1, lineType=cv2.LINE_AA)
            cv2.circle(drawn, (int(x1), int(y1)), 3, (255, 255, 255), -1, lineType=cv2.LINE_AA)

            # Draw ending point (red circle)
            cv2.circle(drawn, (int(x2), int(y2)), 8, (0, 0, 255), -1, lineType=cv2.LINE_AA)

            # Draw direction arrow at the end of the path
            if len(points) >= 2:
                p_last = (int(x2), int(y2))
                p_prev = (int(round(points[-2][0])), int(round(points[-2][1])))
                for pt in reversed(points[:-1]):
                    px, py = int(round(pt[0])), int(round(pt[1]))
                    dist = ((px - p_last[0])**2 + (py - p_last[1])**2)**0.5
                    if dist >= 20:
                        p_prev = (px, py)
                        break
                cv2.arrowedLine(drawn, p_prev, p_last, (0, 0, 255), 3, cv2.LINE_AA, 0, 0.45)

            # Add label text on screen
            label = f"Swipe: ({x1},{y1}) -> ({x2},{y2})"
            cv2.putText(drawn, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

            import datetime
            safe_serial = str(self.serial).replace(":", "_").replace(".", "_")
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            filename = f"path_{safe_serial}_{timestamp}_{x1}_{y1}_to_{x2}_{y2}.png"
            out_path = out_dir / filename
            cv2.imwrite(str(out_path), drawn)
            log.info("[%s] Saved mouse path screenshot: %s", self.serial, out_path.name)
        except Exception as e:
            log.exception("[%s] Failed to save mouse path screenshot: %s", self.serial, e)

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
        self.save_swipe_path_image(x1, y1, x2, y2)
        if self._scrcpy_ready():
            try:
                self._scrcpy_client.control.swipe(
                    int(x1),
                    int(y1),
                    int(x2),
                    int(y2),
                    move_steps_delay=max(0.001, duration_ms / 1000.0 / 60.0),
                )
                return
            except Exception as e:
                log.warning("[%s] scrcpy swipe lỗi (%s), fallback ADB", self.serial, e)
        if self.control_mode == "physical_mouse" and self._hwnd:
            self._physical_swipe(x1, y1, x2, y2, duration_ms)
        else:
            self._adb_shell(
                "input", "swipe",
                str(int(x1)), str(int(y1)),
                str(int(x2)), str(int(y2)),
                str(int(duration_ms)),
            )

    def key(self, name: str) -> None:
        if name.upper() == "BACK":
            locked_until = getattr(self, "_back_locked_until", 0.0)
            if time.monotonic() < locked_until:
                remaining = locked_until - time.monotonic()
                log.warning("[%s] Nút BACK bị chặn do đang trong thời gian khoá (còn %.0fs)", self.serial, remaining)
                return
        log.debug("[%s] key %s", self.serial, name)
        if self._scrcpy_ready():
            keycodes = {
                "BACK": 4,
                "HOME": 3,
                "MENU": 82,
                "POWER": 26,
                "ENTER": 66,
            }
            key_name = name.upper()
            keycode = keycodes.get(key_name)
            if keycode is None and key_name.startswith("KEYCODE_"):
                keycode = keycodes.get(key_name.removeprefix("KEYCODE_"))
            if keycode is not None:
                try:
                    import scrcpy

                    self._scrcpy_client.control.keycode(keycode, scrcpy.ACTION_DOWN)
                    self._scrcpy_client.control.keycode(keycode, scrcpy.ACTION_UP)
                    return
                except Exception as e:
                    log.warning("[%s] scrcpy key lỗi (%s), fallback ADB", self.serial, e)
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
        self.close()
        try:
            self._adb_shell("am", "force-stop", "com.rok.gp.vn")
            log.info("[%s] Đã đóng ứng dụng game com.rok.gp.vn", self.serial)
        except Exception as e:
            log.error("Không thể đóng game: %s", e)

    def close(self) -> None:
        """Release local resources without closing the Android app."""
        if self._scrcpy_window_proc is not None:
            try:
                if self._scrcpy_window_proc.poll() is None:
                    self._scrcpy_window_proc.terminate()
            except Exception:
                log.debug(
                    "[%s] Khong the dong cua so scrcpy",
                    self.serial,
                    exc_info=True,
                )
            finally:
                self._scrcpy_window_proc = None

        if self._scrcpy_client is not None:
            try:
                self._scrcpy_client.stop()
            except Exception:
                log.debug("[%s] Không thể stop scrcpy client", self.serial, exc_info=True)
            finally:
                self._scrcpy_client = None
                self._scrcpy_available = False

