"""Input helper + interactive wizard cho bot subcommand.

Tách hoàn toàn khỏi command/argparse — bất kỳ ai muốn dùng wizard
(vd. tương lai gắn web UI) chỉ cần gọi ``run_bot_wizard()`` trên
một namespace chứa các giá trị mặc định.
"""
from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class BotArgsLike(Protocol):
    """Bất kỳ object nào có các trường này đều dùng được — argparse
    Namespace, dataclass, dict-like wrapper... tuỳ caller."""
    serial: str | None
    resource: str
    target_level: int
    max_iter: int | None
    turn_wait_min: int
    skip_level_adjust: bool


# Nhãn tiếng Việt cho mỗi resource tab — chỉ dùng để xác nhận với
# user sau khi họ chọn.
RESOURCE_LABELS = {
    "barb": "Người man rỡ",
    "corn": "Ngô/Lúa (Đất trồng)",
    "wood": "Trại xẻ gỗ",
    "stone": "Trầm tích đá",
    "gold": "Trầm tích vàng",
    "cycle": "Xoay vòng (Ngô/Đá/Vàng/2 Gỗ)",
}


# ---------------------------------------------------------------------------
# Primitive prompts
# ---------------------------------------------------------------------------

def prompt_default(label: str, default: str) -> str:
    """Hỏi 1 dòng input. Enter -> trả về default."""
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def prompt_choice(
    label: str, choices: list[str], default: str,
) -> str:
    options = "/".join(choices)
    while True:
        raw = input(
            f"{label} ({options}) [{default}]: ",
        ).strip().lower()
        if not raw:
            return default
        if raw in choices:
            return raw
        print(f"  Vui lòng chọn 1 trong: {options}")


def prompt_int(
    label: str, default: int, min_v: int, max_v: int,
) -> int:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
        except ValueError:
            print("  Phải nhập số nguyên")
            continue
        if min_v <= val <= max_v:
            return val
        print(f"  Giá trị phải nằm trong [{min_v}, {max_v}]")


def prompt_yes_no(label: str, default: bool) -> bool:
    dft = "y" if default else "n"
    while True:
        raw = input(f"{label} (y/n) [{dft}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes", "co", "có"):
            return True
        if raw in ("n", "no", "khong", "không"):
            return False
        print("  Vui lòng trả lời y/n")


# ---------------------------------------------------------------------------
# Wizard: gom các prompt cho bot subcommand
# ---------------------------------------------------------------------------

def run_bot_wizard(
    args: BotArgsLike, *, default_serial: str | None = None,
) -> None:
    """Hỏi từng tham số trong terminal khi user không truyền qua CLI.

    Chỉ hỏi tham số CHƯA được cấp ở CLI; vd. nếu user truyền
    ``--serial`` thì không hỏi serial. Trên mỗi field, mutate trực
    tiếp vào ``args``.
    """
    sys.stdout.write(
        "\n=== Cấu hình bot (Enter để dùng mặc định) ===\n",
    )

    if args.serial is None:
        if not default_serial:
            args.serial = input("Serial thiết bị ADB: ").strip()
        else:
            args.serial = prompt_default(
                "Serial thiết bị ADB", default_serial,
            )

    res_map = {"ngo": "corn", "food": "corn", "crop": "corn"}
    args.resource = res_map.get(args.resource, args.resource)

    args.resource = prompt_choice(
        "Tài nguyên (barb/corn/wood/stone/gold/cycle)",
        list(RESOURCE_LABELS.keys()),
        args.resource,
    )
    sys.stdout.write(f"  -> {RESOURCE_LABELS[args.resource]}\n")

    args.target_level = prompt_int(
        "Cấp tài nguyên muốn gom", args.target_level, 1, 50,
    )

    if args.max_iter is None:
        v = prompt_int(
            "Số vòng tối đa (0 = chạy mãi)", 0, 0, 100000,
        )
        args.max_iter = None if v == 0 else v

    args.turn_wait_min = prompt_int(
        "Đợi mỗi lượt khi hàng chờ đầy (phút)",
        args.turn_wait_min, 1, 720,
    )

    args.skip_level_adjust = prompt_yes_no(
        "Bỏ qua chỉnh cấp slider?", args.skip_level_adjust,
    )

    sys.stdout.write("=== Bắt đầu ===\n\n")
