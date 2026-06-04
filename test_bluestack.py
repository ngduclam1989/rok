import sys
import logging
import os

# Thêm thư mục gốc vào sys.path để python nhận diện core
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.bot.bluestack import start_bluestack, stop_bluestack

# Cấu hình log hiển thị ra console
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")

if len(sys.argv) < 3:
    print("Cách dùng:")
    print("  python test_bluestack.py start <serial_hoặc_port>")
    print("  python test_bluestack.py stop <serial_hoặc_port>")
    print("\nVí dụ:")
    print("  python test_bluestack.py start 127.0.0.1:5555")
    print("  python test_bluestack.py stop 127.0.0.1:5555")
    sys.exit(1)

action = sys.argv[1].lower()
target = sys.argv[2]

if action == "start":
    start_bluestack(target)
elif action == "stop":
    stop_bluestack(target)
else:
    print(f"Hành động không hợp lệ: {action}. Chỉ dùng 'start' hoặc 'stop'.")
