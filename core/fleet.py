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


def _force_utf8_stdout() -> None:
    """Windows console mặc định cp1252 không in được tiếng Việt từ
    reader thread -> ép stdout/stderr về UTF-8 (replace nếu fail)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


@dataclass(frozen=True)
class FleetMember:
    """1 dòng trong devices.yaml — máy + tham số CLI cho bot."""
    name: str
    serial: str
    bot_args: list[str]


class _Worker:
    """Quản lý 1 subprocess bot + thread đọc stdout in console."""

    def __init__(
        self,
        member: FleetMember,
        python_exe: str,
        main_script: Path,
        log_file: Path,
    ) -> None:
        self.member = member
        self.python_exe = python_exe
        self.main_script = main_script
        self.log_file = log_file
        self.proc: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None

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

    logs_dir = project_root / logs_dir_name
    logs_dir.mkdir(parents=True, exist_ok=True)

    workers: list[_Worker] = []
    for m in members:
        w = _Worker(
            member=m,
            python_exe=python_exe,
            main_script=project_root / main_script,
            log_file=logs_dir / f"{m.serial}.log",
        )
        workers.append(w)

    # Đường dẫn STOP flag riêng cho TỪNG con — fleet KHÔNG dùng
    # STOP.flag global (xem docstring đầu module).
    per_device_flags = [
        project_root / f"STOP_{w.member.serial}.flag" for w in workers
    ]

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
            return
        state["stopping"] = True
        state["first_signal_time"] = now
        log.warning(
            "Nhận Ctrl+C -> báo dừng từng máy, đợi thoát nhẹ "
            "(Ctrl+C lần 2 trong 5s để giết cứng)",
        )
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

    # Đợi tới khi mọi worker thoát.
    try:
        while True:
            alive = [w for w in workers if w.is_alive()]
            if not alive:
                break
            if state["stopping"]:
                # Đã ra tín hiệu dừng — đếm ngược timeout graceful.
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
    log.info("Fleet đã dừng. Mã thoát từng máy: %s", exit_codes)
    # Parent return 0 nếu mọi con thoát code 0 hoặc do user dừng (130).
    bad = [
        (name, rc) for name, rc in exit_codes
        if rc not in (0, 130, -2, -15, None)
    ]
    return 1 if bad else 0
