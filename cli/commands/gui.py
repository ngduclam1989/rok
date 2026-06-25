"""`python main.py gui` — Khởi chạy giao diện cấu hình trực quan trên trình duyệt."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from core.config_io import save_bot_fleet_config, get_bluestacks_devices_from_conf
from ..paths import DEVICES_FILE

log = logging.getLogger(__name__)

# Global variables for managing the bot subprocess and logs
bot_process: subprocess.Popen | None = None
bot_logs: list[str] = []
bot_logs_lock = threading.Lock()
bot_thread: threading.Thread | None = None


def append_log(line: str) -> None:
    with bot_logs_lock:
        bot_logs.append(line)
        # Cap log buffer size to 500 lines
        if len(bot_logs) > 500:
            bot_logs.pop(0)


def log_reader_thread(proc: subprocess.Popen) -> None:
    assert proc.stdout is not None
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            append_log(line.strip())
    except Exception as e:
        log.error("Lỗi đọc log từ subprocess: %s", e)
    finally:
        proc.stdout.close()


class GUIRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: any) -> None:
        # Override to suppress default HTTP server log noise in the CLI
        pass

    def do_GET(self) -> None:
        # Route logic for serving static frontend files
        root_dir = Path(__file__).resolve().parents[2] / "assets" / "gui"
        
        if self.path == "/" or self.path == "/index.html":
            self.serve_static_file(root_dir / "index.html", "text/html; charset=utf-8")
        elif self.path == "/style.css":
            self.serve_static_file(root_dir / "style.css", "text/css; charset=utf-8")
        elif self.path == "/app.js":
            self.serve_static_file(root_dir / "app.js", "application/javascript; charset=utf-8")
        elif self.path == "/api/config":
            self.handle_get_config()
        elif self.path == "/api/bot/status":
            self.handle_bot_status()
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self) -> None:
        if self.path == "/api/config":
            self.handle_save_config()
        elif self.path == "/api/bluestacks/scan":
            self.handle_scan_bluestacks()
        elif self.path == "/api/bot/start":
            self.handle_bot_start()
        elif self.path == "/api/bot/stop":
            self.handle_bot_stop()
        else:
            self.send_error(404, "Endpoint Not Found")

    def serve_static_file(self, filepath: Path, content_type: str) -> None:
        if not filepath.exists():
            self.send_error(404, f"File {filepath.name} not found")
            return
        
        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def handle_get_config(self) -> None:
        try:
            if DEVICES_FILE.exists():
                data = yaml.safe_load(DEVICES_FILE.read_text(encoding="utf-8")) or {}
            else:
                data = {"defaults": {}, "devices": []}
            
            # Ensure proper keys exist
            if "defaults" not in data:
                data["defaults"] = {}
            if "devices" not in data or data["devices"] is None:
                data["devices"] = []

            self.send_json_response(200, data)
        except Exception as e:
            self.send_json_response(500, {"error": f"Không thể đọc cấu hình: {e}"})

    def handle_save_config(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            config_data = json.loads(post_data.decode("utf-8"))

            save_bot_fleet_config(DEVICES_FILE, config_data)
            self.send_json_response(200, {"status": "success", "message": "Đã lưu cấu hình thành công!"})
        except Exception as e:
            self.send_json_response(500, {"error": f"Không thể lưu cấu hình: {e}"})

    def handle_scan_bluestacks(self) -> None:
        try:
            devices = get_bluestacks_devices_from_conf()
            self.send_json_response(200, {"status": "success", "devices": devices})
        except Exception as e:
            self.send_json_response(500, {"error": f"Lỗi quét thiết bị Bluestacks: {e}"})

    def handle_bot_start(self) -> None:
        global bot_process, bot_logs, bot_thread
        
        if bot_process is not None and bot_process.poll() is None:
            self.send_json_response(400, {"error": "Bot đang chạy rồi!"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode("utf-8")) if content_length else {}

            mode = params.get("mode", "sequential")
            cmd = [sys.executable, "main.py", "fleet"]
            if mode == "sequential":
                cmd.append("--sequential")

            # Reset log buffer
            with bot_logs_lock:
                bot_logs.clear()
                bot_logs.append(f"--- BẮT ĐẦU CHẠY BOT ({mode.upper()}) ---")

            log.info("Khởi chạy subprocess: %s", " ".join(cmd))
            bot_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
            )

            # Start reading thread
            bot_thread = threading.Thread(target=log_reader_thread, args=(bot_process,), daemon=True)
            bot_thread.start()

            self.send_json_response(200, {"status": "success", "message": "Đã khởi chạy bot thành công!"})
        except Exception as e:
            self.send_json_response(500, {"error": f"Không thể khởi chạy bot: {e}"})

    def handle_bot_stop(self) -> None:
        global bot_process
        if bot_process is None or bot_process.poll() is not None:
            self.send_json_response(400, {"error": "Bot chưa chạy hoặc đã dừng!"})
            return

        try:
            # On windows, terminate is standard
            bot_process.terminate()
            append_log("--- ĐÃ GỬI TÍN HIỆU DỪNG BOT ---")
            
            # Wait up to 5s for graceful termination
            for _ in range(50):
                if bot_process.poll() is not None:
                    break
                time.sleep(0.1)
            
            if bot_process.poll() is None:
                bot_process.kill()
                append_log("--- ĐÃ CƯỠNG CHẾ DỪNG BOT (KILL) ---")

            bot_process = None
            self.send_json_response(200, {"status": "success", "message": "Đã dừng bot!"})
        except Exception as e:
            self.send_json_response(500, {"error": f"Lỗi khi dừng bot: {e}"})

    def handle_bot_status(self) -> None:
        global bot_process, bot_logs
        is_running = bot_process is not None and bot_process.poll() is None
        
        with bot_logs_lock:
            logs_copy = list(bot_logs)

        self.send_json_response(200, {
            "running": is_running,
            "logs": logs_copy
        })

    def send_json_response(self, status_code: int, data: dict) -> None:
        try:
            response = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        except Exception as e:
            log.error("Lỗi gửi phản hồi JSON: %s", e)


def cmd_gui(args: argparse.Namespace) -> int:
    port = 5000
    server_address = ("", port)
    
    # Ensure assets directory exists
    assets_dir = Path(__file__).resolve().parents[2] / "assets" / "gui"
    assets_dir.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer(server_address, GUIRequestHandler)
    print(f"=== ĐANG CHẠY WEB GUI TẠI: http://127.0.0.1:{port} ===")
    print("Nhấn Ctrl+C trong terminal này để tắt giao diện.")
    
    # Auto-open browser in a separate thread so server can start listening immediately
    threading.Thread(target=lambda: webbrowser.open(f"http://127.0.0.1:{port}"), daemon=True).start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang tắt Web GUI server...")
        if bot_process is not None and bot_process.poll() is None:
            bot_process.terminate()
            bot_process.wait()
    return 0
