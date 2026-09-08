"""Fleet orchestrator — chạy bot cho nhiều thiết bị, mỗi máy 1 subprocess.

Thiết kế:
  * Process-isolated: mỗi máy chạy `python main.py bot --serial X ...`
    trong subprocess riêng. 1 máy crash KHÔNG kéo máy khác chết.
  * Mỗi máy có file log riêng `logs/<serial>.log`, đồng thời mọi dòng
    log của subprocess được đọc qua stdout và in console với prefix
    "thiết bị <tên>: ..." để user biết máy nào đang nói gì.
  * Ctrl+C ở parent -> ghi `STOP_<serial>.flag` cho TỪNG con của
    fleet -> con đó thấy + thoát nhẹ nhàng (return-to-world +
    cleanup). Parent đợi tối đa 30s rồi SIGTERM con nào còn lì.
  * Muốn dừng riêng 1 máy: tạo `STOP_<serial>.flag` của máy đó.
  * CỐ TÌNH KHÔNG dùng `STOP.flag` global, vì đó là nút dừng "kill
    mọi bot trên máy" do user kiểm soát — fleet không được tự ghi
    vào nó, sẽ vô tình dừng các bot standalone khác đang chạy.
  * Auto-restart: khi subprocess crash (exit code ≠ 0), fleet chờ 5
    phút rồi kiểm tra thiết bị kết nối + game đang chạy trước khi
    khởi động lại. Tối đa 10 lần restart mỗi thiết bị.
"""
from __future__ import annotations

import logging
import os
import signal as _signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Package name game Rise of Kingdoms
_GAME_PACKAGE = "com.rok.gp.vn"
# Thời gian chờ trước khi restart (giây)
_RESTART_DELAY_SEC = 5 * 60  # 5 phút
# Thời gian chờ retry khi thiết bị chưa kết nối (giây)
_RETRY_DELAY_SEC = 60  # 1 phút
# Giới hạn số lần restart mỗi thiết bị
_MAX_RESTARTS = 10


def _force_utf8_stdout() -> None:
    """Windows console mặc định cp1252 không in được tiếng Việt từ
    reader thread -> ép stdout/stderr về UTF-8 (replace nếu fail)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _resolve_adb_path() -> str:
    """Tìm đường dẫn adb.exe. Ưu tiên tools/scrcpy/adb.exe trong project."""
    project_adb = Path(__file__).resolve().parent.parent / "tools" / "scrcpy" / "adb.exe"
    if project_adb.exists():
        return str(project_adb)
    # Fallback: dùng adb của airtest
    try:
        from airtest.core.android.adb import ADB
        return ADB.get_adb_path()
    except Exception:
        return "adb"


@dataclass(frozen=True)
class FleetMember:
    """1 dòng trong devices.yaml — máy + tham số CLI cho bot."""
    name: str
    serial: str
    bot_args: list[str]


class _Worker:
    """Quản lý 1 subprocess bot + thread đọc stdout in console.

    Hỗ trợ auto-restart khi subprocess crash.
    """

    def __init__(
        self,
        member: FleetMember,
        python_exe: str,
        main_script: Path,
        log_file: Path,
        adb_path: str,
    ) -> None:
        self.member = member
        self.python_exe = python_exe
        self.main_script = main_script
        self.log_file = log_file
        self.adb_path = adb_path
        self.proc: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None

        # Auto-restart state
        self.restart_at: float | None = None  # Thời điểm sẽ restart (epoch)
        self.restart_count: int = 0           # Đếm số lần đã restart
        self.gave_up: bool = False            # True nếu đã vượt giới hạn restart

    def start(self) -> None:
        import sys
        if getattr(sys, "frozen", False):
            # When frozen as an EXE, sys.executable (python_exe) is RoKBot.exe.
            # We must not pass main_script (main.py) as an argument to the EXE.
            cmd = [
                self.python_exe,
                "bot",
                *self.member.bot_args,
                "--log-file", str(self.log_file),
            ]
        else:
            cmd = [
                self.python_exe,
                str(self.main_script),
                "bot",
                *self.member.bot_args,
                "--log-file", str(self.log_file),
            ]
        log.info(
            "thiết bị %s: khởi động subprocess (serial=%s)",
            self.member.name, self.member.serial,
        )
        # text=True + bufsize=1 -> line-buffered reads.
        # stderr=STDOUT -> không cần thread thứ 2 cho stderr.
        # encoding utf-8 để không bóp meo dấu tiếng Việt.
        # PYTHONIOENCODING=utf-8 ép child stdout cũng dùng UTF-8
        # (mặc định Windows = cp1252, sẽ crash khi log tiếng Việt).
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(  # noqa: S603 - controlled cmd
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        self.reader = threading.Thread(
            target=self._pump_stdout,
            name=f"reader-{self.member.name}",
            daemon=True,
        )
        self.reader.start()

    def _pump_stdout(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        prefix = f"thiết bị {self.member.name}:"
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            # In ra console parent với prefix tên máy.
            sys.stdout.write(f"{prefix} {line}\n")
            sys.stdout.flush()

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def has_pending_restart(self) -> bool:
        """Worker đã chết nhưng đang chờ restart."""
        return self.restart_at is not None and not self.gave_up

    def returncode(self) -> int | None:
        return self.proc.poll() if self.proc is not None else None

    def terminate(self) -> None:
        """Gửi SIGTERM (Windows: TerminateProcess) — dùng khi
        graceful-stop không kịp."""
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                log.exception(
                    "thiết bị %s: terminate thất bại", self.member.name,
                )

    def wait(self, timeout: float) -> bool:
        """Đợi subprocess kết thúc. Trả True nếu đã kết thúc."""
        if self.proc is None:
            return True
        try:
            self.proc.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def cancel_restart(self) -> None:
        """Hủy lịch restart (khi user Ctrl+C)."""
        self.restart_at = None

    # ── Device / Game health checks ──────────────────────────────

    def is_device_connected(self) -> bool:
        """Kiểm tra thiết bị có đang online qua ADB không."""
        try:
            result = subprocess.run(
                [self.adb_path, "devices"],
                capture_output=True, text=True, check=False, timeout=10,
            )
            for line in result.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == self.member.serial and parts[1] == "device":
                    return True
        except Exception as exc:
            log.debug(
                "thiết bị %s: lỗi khi kiểm tra kết nối ADB: %s",
                self.member.name, exc,
            )
        return False

    def is_game_running(self) -> bool:
        """Kiểm tra game com.rok.gp.vn có đang chạy trên thiết bị không."""
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.member.serial,
                 "shell", "pidof", _GAME_PACKAGE],
                capture_output=True, text=True, check=False, timeout=10,
            )
            pid = result.stdout.strip()
            return bool(pid and pid.isdigit())
        except Exception as exc:
            log.debug(
                "thiết bị %s: lỗi khi kiểm tra game: %s",
                self.member.name, exc,
            )
        return False

    def launch_game(self) -> bool:
        """Khởi chạy game com.rok.gp.vn trên thiết bị.

        Returns True nếu lệnh chạy thành công (không đảm bảo game
        đã load xong — caller nên chờ thêm).
        """
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.member.serial,
                 "shell", "monkey", "-p", _GAME_PACKAGE,
                 "-c", "android.intent.category.LAUNCHER", "1"],
                capture_output=True, text=True, check=False, timeout=15,
            )
            ok = result.returncode == 0
            if ok:
                log.info(
                    "thiết bị %s: đã gửi lệnh khởi chạy game %s",
                    self.member.name, _GAME_PACKAGE,
                )
            else:
                log.warning(
                    "thiết bị %s: khởi chạy game thất bại (rc=%s): %s",
                    self.member.name, result.returncode,
                    result.stderr.strip() or result.stdout.strip(),
                )
            return ok
        except Exception as exc:
            log.warning(
                "thiết bị %s: exception khi khởi chạy game: %s",
                self.member.name, exc,
            )
        return False

    def schedule_restart(self, delay_sec: float = _RESTART_DELAY_SEC) -> None:
        """Lên lịch restart sau delay_sec giây."""
        if self.restart_count >= _MAX_RESTARTS:
            log.error(
                "thiết bị %s: ĐÃ RESTART %d LẦN (tối đa %d). "
                "Bỏ qua thiết bị này — kiểm tra lại thủ công.",
                self.member.name, self.restart_count, _MAX_RESTARTS,
            )
            self.gave_up = True
            self.restart_at = None
            return
        self.restart_at = time.time() + delay_sec
        mins = delay_sec / 60.0
        log.warning(
            "thiết bị %s: sẽ tự khởi động lại sau %.0f phút (lần %d/%d)",
            self.member.name, mins, self.restart_count + 1, _MAX_RESTARTS,
        )

    def try_restart(self) -> bool:
        """Thử restart worker nếu đã đến giờ.

        Returns True nếu đã restart thành công.
        Returns False nếu chưa đến giờ hoặc chưa sẵn sàng.
        """
        if self.restart_at is None or self.gave_up:
            return False

        now = time.time()
        if now < self.restart_at:
            return False  # Chưa đến giờ

        # Đã đến giờ restart — kiểm tra thiết bị
        if not self.is_device_connected():
            log.warning(
                "thiết bị %s: chưa kết nối ADB, thử lại sau %ds",
                self.member.name, _RETRY_DELAY_SEC,
            )
            self.restart_at = now + _RETRY_DELAY_SEC
            return False

        # Kiểm tra game có đang chạy không
        if not self.is_game_running():
            log.info(
                "thiết bị %s: game %s chưa chạy — đang khởi chạy...",
                self.member.name, _GAME_PACKAGE,
            )
            self.launch_game()
            log.info(
                "thiết bị %s: chờ 15s cho game khởi động...",
                self.member.name,
            )
            # Đặt lại restart_at để chờ 15s nữa (game cần thời gian load)
            self.restart_at = now + 15.0
            return False

        # Thiết bị online + game đang chạy → restart!
        self.restart_count += 1
        self.restart_at = None
        log.info(
            "thiết bị %s: KHỞI ĐỘNG LẠI bot (lần %d/%d)",
            self.member.name, self.restart_count, _MAX_RESTARTS,
        )
        self.start()
        return True


def run_fleet(
    members: list[FleetMember],
    *,
    project_root: Path,
    python_exe: str = sys.executable,
    main_script: str = "main.py",
    logs_dir_name: str = "logs",
    graceful_timeout_sec: float = 30.0,
) -> int:
    """Chạy fleet bot. Trả về exit code (0 nếu tất cả thoát êm)."""
    _force_utf8_stdout()
    if not members:
        log.warning(
            "Không có máy nào trong devices.yaml -> không có gì để chạy",
        )
        return 1

    adb_path = _resolve_adb_path()
    logs_dir = project_root / logs_dir_name
    logs_dir.mkdir(parents=True, exist_ok=True)

    workers: list[_Worker] = []
    for m in members:
        w = _Worker(
            member=m,
            python_exe=python_exe,
            main_script=project_root / main_script,
            log_file=logs_dir / f"{m.serial}.log",
            adb_path=adb_path,
        )
        workers.append(w)

    # Đường dẫn STOP flag riêng cho TỪNG con — fleet KHÔNG dùng
    # STOP.flag global (xem docstring đầu module).
    per_device_flags = [
        project_root / f"STOP_{w.member.serial}.flag" for w in workers
    ]

    # Exit code do user dừng (Ctrl+C / SIGTERM / flag).
    _USER_STOP_CODES = frozenset({0, 130, -2, -15})

    # Cài signal handler PARENT: Ctrl+C -> ghi STOP_<serial>.flag
    # cho từng con để con thoát nhẹ. Lần Ctrl+C thứ 2 trong 5s ->
    # SIGTERM cứng tất cả con.
    state = {"stopping": False, "first_signal_time": 0.0}

    def _on_signal(signum: int, _frame: object) -> None:
        now = time.time()
        if state["stopping"] and (now - state["first_signal_time"]) < 5.0:
            log.warning(
                "Ctrl+C lần 2 -> SIGTERM tất cả subprocess",
            )
            for w in workers:
                w.terminate()
                w.cancel_restart()
            return
        state["stopping"] = True
        state["first_signal_time"] = now
        log.warning(
            "Nhận Ctrl+C -> báo dừng từng máy, đợi thoát nhẹ "
            "(Ctrl+C lần 2 trong 5s để giết cứng)",
        )
        # Hủy mọi pending restart
        for w in workers:
            w.cancel_restart()
        for f in per_device_flags:
            try:
                f.write_text("stop", encoding="utf-8")
            except Exception:
                log.exception("Ghi %s thất bại", f.name)

    try:
        _signal.signal(_signal.SIGINT, _on_signal)
        _signal.signal(_signal.SIGTERM, _on_signal)
    except Exception:
        log.exception("Cài signal handler thất bại")

    # Khởi động tất cả subprocess.
    for w in workers:
        w.start()

    log.info(
        "Fleet đã khởi động %d máy. Nhấn Ctrl+C để dừng tất cả. "
        "Hoặc tạo STOP_<serial>.flag để dừng riêng 1 máy.",
        len(workers),
    )

    # Theo dõi worker nào đã detect crash (tránh log + schedule lặp)
    _detected_dead: set[str] = set()

    # Đợi tới khi mọi worker thoát (và không có pending restart nào).
    try:
        while True:
            alive = [w for w in workers if w.is_alive()]
            pending = [w for w in workers if w.has_pending_restart()]

            # Nếu không còn ai chạy VÀ không có ai pending restart → xong
            if not alive and not pending:
                break

            if state["stopping"]:
                # User đã Ctrl+C — chỉ đợi alive workers thoát
                if not alive:
                    break
                wait_until = (
                    state["first_signal_time"] + graceful_timeout_sec
                )
                remain = wait_until - time.time()
                if remain <= 0:
                    log.warning(
                        "Quá %ss graceful -> SIGTERM máy còn lì: %s",
                        graceful_timeout_sec,
                        [w.member.name for w in alive],
                    )
                    for w in alive:
                        w.terminate()
                    # Cho thêm 5s sau terminate.
                    for w in alive:
                        w.wait(5.0)
                    break
                time.sleep(0.5)
                continue

            # ── Phát hiện worker crash và lên lịch restart ──
            for w in workers:
                if w.is_alive() or w.has_pending_restart() or w.gave_up:
                    continue
                wid = w.member.serial
                if wid in _detected_dead:
                    continue

                rc = w.returncode()
                if rc is None:
                    continue  # Chưa chạy lần nào

                if rc in _USER_STOP_CODES:
                    # Thoát do user dừng — không restart
                    _detected_dead.add(wid)
                    log.info(
                        "thiết bị %s: thoát bình thường (mã %s)",
                        w.member.name, rc,
                    )
                    continue

                # Crash! Lên lịch restart
                _detected_dead.add(wid)
                log.error(
                    "thiết bị %s: subprocess CRASH (mã thoát %s)",
                    w.member.name, rc,
                )
                w.schedule_restart()

            # ── Thực hiện restart nếu đã đến giờ ──
            for w in workers:
                if w.has_pending_restart():
                    restarted = w.try_restart()
                    if restarted:
                        # Xóa khỏi detected để theo dõi lại
                        _detected_dead.discard(w.member.serial)

            time.sleep(0.5)
    finally:
        # Dọn các STOP_<serial>.flag của fleet để lần sau chạy lại
        # không bị dừng ngay từ flag rác.
        for f in per_device_flags:
            if f.exists():
                try:
                    f.unlink()
                except Exception:
                    log.exception("Xoá %s thất bại", f.name)

    # Báo cáo exit code từng máy.
    exit_codes: list[tuple[str, int | None]] = [
        (w.member.name, w.returncode()) for w in workers
    ]
    restart_info = [
        (w.member.name, w.restart_count) for w in workers if w.restart_count > 0
    ]
    log.info("Fleet đã dừng. Mã thoát từng máy: %s", exit_codes)
    if restart_info:
        log.info("Số lần restart: %s", restart_info)
    # Parent return 0 nếu mọi con thoát code 0 hoặc do user dừng (130).
    bad = [
        (name, rc) for name, rc in exit_codes
        if rc not in (0, 130, -2, -15, None)
    ]
    return 1 if bad else 0
