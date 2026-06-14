"""Argparse build + dispatch — entry point của CLI.

Khai báo mọi subparser ở đây để dễ tra cứu. KHÔNG chứa business
logic — mọi command function nằm trong ``cli/commands/``.
"""
from __future__ import annotations

import argparse

from core import bot as bot_engine

from .commands.bot import cmd_bot
from .commands.capture import cmd_capture
from .commands.detect import cmd_detect
from .commands.devices import cmd_devices
from .commands.fleet import cmd_fleet
from .commands.run import cmd_run
from .commands.status import cmd_status
from .logging_setup import setup_logging
from .paths import DEFAULT_DB


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mini_game", description="Tự động hoá game Android",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help="Đường dẫn DB SQLite",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    _build_run_parser(sub)
    _build_devices_parser(sub)
    _build_status_parser(sub)
    _build_capture_parser(sub)
    _build_bot_parser(sub)
    _build_fleet_parser(sub)
    _build_detect_parser(sub)

    return parser


def _build_run_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run", help="Chạy scenario YAML legacy trên các thiết bị",
    )
    p.add_argument("--serial", help="Ghi đè 1 thiết bị: serial ADB")
    p.add_argument(
        "--scenario", help="Ghi đè 1 thiết bị: tên file scenario",
    )
    p.set_defaults(func=cmd_run)


def _build_devices_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("devices", help="Liệt kê thiết bị ADB đang nối")
    p.set_defaults(func=cmd_devices)


def _build_status_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "status", help="Xem thiết bị + lượt chạy gần đây",
    )
    p.set_defaults(func=cmd_status)


def _build_capture_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("capture", help="Chụp ảnh để cắt template")
    p.add_argument(
        "--serial",
        help="Serial thiết bị (mặc định: đầu devices.yaml)",
    )
    p.add_argument(
        "--out",
        help="Đường dẫn lưu (mặc định: screenshot_current.png)",
    )
    p.set_defaults(func=cmd_capture)


def _build_bot_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "bot",
        help=(
            "Chạy bot RoK gather. Không truyền --serial -> "
            "hỏi tham số trong terminal."
        ),
    )
    p.add_argument(
        "--serial",
        help=(
            "Serial thiết bị. Bỏ trống -> bot hỏi tham số "
            "trong terminal."
        ),
    )
    p.add_argument(
        "--interactive", action="store_true",
        help="Ép vào chế độ hỏi-đáp dù đã truyền --serial",
    )
    p.add_argument(
        "--max-iter", type=int, default=None,
        help="Dừng sau N vòng (mặc định: chạy mãi)",
    )
    p.add_argument(
        "--target-level", type=int, default=None,
        help=(
            "Cấp tài nguyên trên slider "
            "(mặc định lấy từ devices.yaml hoặc 5)."
        ),
    )
    p.add_argument(
        "--resource",
        choices=["barb", "corn", "wood", "stone", "gold", "cycle", "ngo", "food", "crop"],
        default=None,
        help=(
            "Tab tài nguyên (mặc định lấy từ devices.yaml hoặc 'wood'). "
            "barb=Người man rỡ, corn=Ngô/Lúa (Đất trồng), wood=Trại xẻ gỗ, "
            "stone=Trầm tích đá, gold=Trầm tích vàng, "
            "cycle=Xoay vòng (Ngô/Đá/Vàng/2 Gỗ)."
        ),
    )
    p.add_argument(
        "--max-slots", type=int, default=None,
        help=(
            "Sức chứa hàng chờ (mặc định lấy từ devices.yaml hoặc 4, "
            "sẽ tự dò qua OCR huy hiệu)."
        ),
    )
    p.add_argument(
        "--skip-level-adjust", action="store_true",
        help=(
            "Không OCR + chỉnh slider. Giữ nguyên cấp panel đang "
            "hiển thị. Hữu ích khi slider đã đúng cấp hoặc template "
            "+/- không ổn."
        ),
    )
    p.add_argument(
        "--turn-wait-min", type=int,
        default=None,
        help=(
            "Số phút ngủ giữa các lần kiểm tra hàng chờ khi đầy "
            "(mặc định lấy từ devices.yaml hoặc 60)."
        ),
    )
    p.add_argument(
        "--log-file", default=None,
        help=(
            "Ghi log ra file đường dẫn này (vẫn in stdout). "
            "Dùng cho fleet để mỗi máy có log riêng."
        ),
    )
    p.add_argument(
        "--control-mode", choices=["adb", "physical_mouse"], default=None,
        help="Chế độ điều khiển giả lập: adb hoặc physical_mouse (chiếm chuột thật PC, mặc định lấy từ devices.yaml hoặc adb)",
    )
    p.add_argument(
        "--only-claim-vip", action="store_true",
        help="Chỉ chạy nhận rương/điểm VIP hàng ngày rồi dừng lại",
    )
    p.add_argument(
        "--enable-vip-claim", action="store_true",
        help="Bật nhận VIP tự động, chọn ngẫu nhiên thứ tự chạy trước/sau khi farm",
    )
    p.set_defaults(func=cmd_bot)


def _build_fleet_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "fleet",
        help=(
            "Chạy bot SONG SONG cho mọi máy trong devices.yaml "
            "(mỗi máy 1 subprocess, log riêng)"
        ),
    )
    p.add_argument(
        "--sequential", action="store_true",
        help="Chạy TUẦN TỰ từng thiết bị thay vì chạy song song cùng lúc",
    )
    p.set_defaults(func=cmd_fleet)


def _build_detect_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "detect", help="Nhận diện trạng thái 1 lần (không chạm)",
    )
    p.add_argument(
        "--serial", help="Serial thiết bị (mặc định: đầu devices.yaml)",
    )
    p.set_defaults(func=cmd_detect)


def run(argv: list[str] | None = None) -> int:
    """Entry point gọi từ ``main.py``."""
    import sys
    if argv is None:
        argv = sys.argv[1:]

    # Nếu chạy trực tiếp (nhấp đúp chuột file EXE) mà không truyền đối số nào
    if not argv:
        print("Không tìm thấy lệnh. Tự động khởi chạy bot Tuần tự (fleet --sequential)...")
        argv = ["fleet", "--sequential"]

    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level)
    return args.func(args)
