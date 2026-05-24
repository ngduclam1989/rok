"""mini_game — entry point cho CLI tự động chơi game Android.

File này CỐ TÌNH ngắn. Mọi business logic + UI thực sự nằm trong
``cli/`` và ``core/``. Đây chỉ là entry để ``python main.py`` hoạt động.

Kiến trúc:
    cli/                    PRESENTATION (giao diện)
        parser.py           argparse build + dispatch
        commands/           1 file / subcommand
        prompts.py          input helper + wizard tương tác
        logging_setup.py    cấu hình logging
        paths.py            đường dẫn project chung
    core/                   DOMAIN + APPLICATION (logic)
        bot/                state-machine bot (RoK gather)
        fleet.py            multi-device orchestrator
        config_io.py        đọc/ghi devices.yaml
        device.py, ocr.py, store/, runner.py, scenario.py
"""
from __future__ import annotations

import sys

# Reconfigure stdout and stderr to use UTF-8 to prevent UnicodeEncodeError on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from cli import run

if __name__ == "__main__":
    sys.exit(run())
