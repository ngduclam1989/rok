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
    paths = get_bluestacks_paths()
    conf_path = paths["conf"]
    if not os.path.exists(conf_path):
        log.error("Không tìm thấy file cấu hình Bluestacks tại: %s", conf_path)
        return None

    # Line format: bst.instance.Pie64.status.adb_port="5555"
    pattern = re.compile(r'bst\.instance\.([a-zA-Z0-9_]+)\.status\.adb_port="(\d+)"')
    try:
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    inst_name, adb_port = match.groups()
                    if adb_port == port_str:
                        return inst_name
    except Exception as e:
        log.error("Lỗi khi đọc file cấu hình Bluestacks: %s", e)
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

    Waits until the ADB port is open before returning.
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
                if '--instance' in cmdline:
                    idx = cmdline.index('--instance')
                    if idx + 1 < len(cmdline) and cmdline[idx+1] == instance_name:
                        is_running = True
                        break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if is_running:
        log.info("Instance Bluestacks '%s' đã đang chạy.", instance_name)
        if is_port_open(port):
            return True
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
            # Try to run adb connect
            try:
                from airtest.core.android.adb import ADB
                adb_path = ADB().adb_path
                subprocess.run([adb_path, "connect", f"127.0.0.1:{port}"], capture_output=True, check=False)
            except Exception:
                pass
            return True
        time.sleep(2)

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
                if '--instance' in cmdline:
                    idx = cmdline.index('--instance')
                    if idx + 1 < len(cmdline) and cmdline[idx+1] == instance_name:
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
