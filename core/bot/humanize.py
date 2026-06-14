"""Chế độ giả lập hành vi người thật (humanize).

Cung cấp các khoảng nghỉ ngẫu nhiên và cờ cấu hình để bot hoạt động tự nhiên hơn.
"""
from __future__ import annotations

import random
import time

def human_thinking_pause() -> None:
    """Pause ngắn ngẫu nhiên từ 0.4s đến 1.1s để giả lập suy nghĩ."""
    time.sleep(random.uniform(0.4, 1.1))

def human_inter_action_pause() -> None:
    """Pause ngắn ngẫu nhiên từ 0.05s đến 0.3s để giả lập thao tác nhanh."""
    time.sleep(random.uniform(0.05, 0.30))

def is_enabled() -> bool:
    """Kiểm tra xem chế độ humanize có bật không."""
    return True
