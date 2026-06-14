"""Bluestacks instance manager.

Allows starting and stopping Bluestacks instances based on ADB serial/port.
"""
from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import time
import winreg
import psutil

log = logging.getLogger(__name__)


def get_bluestacks_paths() -> dict[str, str]:
    """Get the path to HD-Player.exe and bluestacks.conf from registry or defaults."""
    install_dir = r"C:\Program Files\BlueStacks_nxt"
    user_dir = r"C:\ProgramData\BlueStacks_nxt"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt") as key:
            try:
                install_dir = winreg.QueryValueEx(key, "InstallDir")[0]
            except Exception:
                pass
            try:
                user_dir = winreg.QueryValueEx(key, "UserDir")[0]
            except Exception:
                pass
    except Exception:
        pass
    return {
        "hd_player": os.path.join(install_dir, "HD-Player.exe"),
        "conf": os.path.join(user_dir, "bluestacks.conf")
    }


def get_instance_name_by_port(port: str | int) -> str | None:
    """Parse bluestacks.conf to find the instance name matching the given ADB port."""
    port_str = str(port).strip()
    try:
        target_port = int(port_str)
    except ValueError:
        return None

    paths = get_bluestacks_paths()
    conf_path = paths["conf"]
    if not os.path.exists(conf_path):
        log.error("Không tìm thấy file cấu hình Bluestacks tại: %s", conf_path)
        return None

    # Line format: bst.instance.Pie64.status.adb_port="5555" hoặc bst.instance.Pie64.adb_port="5555"
    pattern = re.compile(r'bst\.instance\.([a-zA-Z0-9_]+)(?:\.status)?\.adb_port="(\d+)"')
    candidates = []
    try:
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    inst_name, adb_port = match.groups()
                    p_val = int(adb_port)
                    if p_val == target_port:
                        return inst_name
                    if abs(p_val - target_port) <= 2:
                        candidates.append((inst_name, abs(p_val - target_port)))
    except Exception as e:
        log.error("Lỗi khi đọc file cấu hình Bluestacks: %s", e)

    if candidates:
        # Sắp xếp để lấy máy ảo có độ lệch cổng nhỏ nhất
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]
    return None


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Check if the given port is open on host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def start_bluestack(serial_or_port: str | int, timeout: int = 40) -> bool:
    """Start the Bluestacks instance matching the given port or serial.

    Waits until the ADB port is open and the device state is online before returning.
    """
    s = str(serial_or_port).strip()
    port_str = s.split(":")[-1] if ":" in s else s
    try:
        port = int(port_str)
    except ValueError:
        log.error("Cổng không hợp lệ: %s", port_str)
        return False

    instance_name = get_instance_name_by_port(port)
    if not instance_name:
        log.error("Không tìm thấy instance Bluestacks nào cho cổng %d", port)
        return False

    def _wait_for_adb_online(adb_port: int, wait_timeout: float = 40.0) -> bool:
        log.info("Đang chờ thiết bị 127.0.0.1:%d chuyển sang trạng thái online...", adb_port)
        try:
            from airtest.core.android.adb import ADB
            adb_path = ADB().adb_path
        except Exception:
            adb_path = "adb"
        
        state_start = time.time()
        from .signals import pause
        while time.time() - state_start < wait_timeout:
            try:
                # Force disconnect first, then connect to clear any stuck 'offline' states
                subprocess.run([adb_path, "disconnect", f"127.0.0.1:{adb_port}"], capture_output=True, check=False)
                subprocess.run([adb_path, "connect", f"127.0.0.1:{adb_port}"], capture_output=True, check=False)
                
                res = subprocess.run([adb_path, "-s", f"127.0.0.1:{adb_port}", "get-state"], capture_output=True, text=True, check=False)
                state = res.stdout.strip()
                if state == "device":
                    log.info("Thiết bị 127.0.0.1:%d đã online và sẵn sàng.", adb_port)
                    return True
            except Exception as e:
                log.warning("Lỗi khi kết nối/kiểm tra trạng thái ADB: %s", e)
            pause(2.0)
        log.error("Thiết bị 127.0.0.1:%d vẫn báo offline sau %d giây.", adb_port, wait_timeout)
        return False

    paths = get_bluestacks_paths()
    hd_player = paths["hd_player"]
    if not os.path.exists(hd_player):
        log.error("Không tìm thấy HD-Player.exe tại: %s", hd_player)
        return False

    # Check if this specific instance is already running
    is_running = False
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            if proc.info['name'] == 'HD-Player.exe' and proc.info['cmdline']:
                cmdline = proc.info['cmdline']
                match = False
                if '--instance' in cmdline:
                    idx = cmdline.index('--instance')
                    if idx + 1 < len(cmdline) and cmdline[idx+1] == instance_name:
                        match = True
                else:
                    # Nếu chạy thủ công không có --instance, mặc định là instance chính (Pie64, Nougat32, Rvc64)
                    # Hoặc nếu chỉ có đúng 1 HD-Player.exe đang chạy trên toàn hệ thống
                    is_only_one = len([p for p in psutil.process_iter(['name']) if p.info['name'] == 'HD-Player.exe']) == 1
                    if is_only_one or instance_name in ["Pie64", "Nougat32", "Rvc64"]:
                        match = True
                
                if match:
                    is_running = True
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if is_running:
        log.info("Instance Bluestacks '%s' đã đang chạy.", instance_name)
        if is_port_open(port):
            return _wait_for_adb_online(port)
        log.info("Cổng ADB %d chưa mở, đợi kết nối...", port)
    else:
        log.info("Đang khởi động Bluestacks instance: %s...", instance_name)
        try:
            subprocess.Popen([hd_player, "--instance", instance_name])
        except Exception as e:
            log.error("Lỗi khởi chạy Bluestacks: %s", e)
            return False

    # Wait for the ADB port to open
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_open(port):
            log.info("Khởi động thành công! Cổng ADB %d đã mở.", port)
            return _wait_for_adb_online(port)
        from .signals import pause
        pause(2.0)

    log.error("Quá thời gian chờ %d giây nhưng cổng ADB %d vẫn chưa mở.", timeout, port)
    return False


def stop_bluestack(serial_or_port: str | int) -> bool:
    """Stop the Bluestacks instance matching the given port or serial."""
    s = str(serial_or_port).strip()
    port_str = s.split(":")[-1] if ":" in s else s
    try:
        port = int(port_str)
    except ValueError:
        log.error("Cổng không hợp lệ: %s", port_str)
        return False

    instance_name = get_instance_name_by_port(port)
    if not instance_name:
        log.error("Không tìm thấy instance Bluestacks nào cho cổng %d", port)
        return False

    log.info("Đang tắt Bluestacks instance: %s...", instance_name)
    killed = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] == 'HD-Player.exe' and proc.info['cmdline']:
                cmdline = proc.info['cmdline']
                match = False
                if '--instance' in cmdline:
                    idx = cmdline.index('--instance')
                    if idx + 1 < len(cmdline) and cmdline[idx+1] == instance_name:
                        match = True
                else:
                    # Nếu chạy thủ công không có --instance, mặc định là instance chính (Pie64, Nougat32, Rvc64)
                    # Hoặc nếu chỉ có đúng 1 HD-Player.exe đang chạy trên toàn hệ thống
                    is_only_one = len([p for p in psutil.process_iter(['name']) if p.info['name'] == 'HD-Player.exe']) == 1
                    if is_only_one or instance_name in ["Pie64", "Nougat32", "Rvc64"]:
                        match = True
                
                if match:
                    log.info("Đang tắt process PID %d...", proc.info['pid'])
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if killed:
        log.info("Đã tắt Bluestacks instance %s thành công.", instance_name)
        return True
    else:
        log.info("Không tìm thấy instance %s đang chạy.", instance_name)
        return False
