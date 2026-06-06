"""Application layer: đọc/ghi cấu hình thiết bị từ devices.yaml.

Tách khỏi UI (cli/) và domain (core/bot/) để:
  * Logic load config có thể test độc lập, không cần argparse.
  * UI (cli/) chỉ gọi 1 hàm đơn — không phải đọc YAML thủ công.
  * Nhiều entry point khác nhau (CLI, fleet, future web UI) cùng
    dùng chung 1 loader.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.runner import DeviceConfig

log = logging.getLogger(__name__)


# Các giá trị mặc định cho từng trường bot config.
# Trùng tên với CLI flag của subcommand `bot`.
_BOT_CONFIG_DEFAULTS: dict[str, object] = {
    "resource": "wood",
    "target_level": 5,
    "max_slots": 4,
    "skip_level_adjust": False,
    "turn_wait_min": 60,
    "control_mode": "adb",
}

def normalize_resource(res: str) -> str:
    r = str(res).strip().lower()
    if r in ("ngo", "food", "crop", "dattrong", "corn"):
        return "corn"
    return r


_VALID_RESOURCES = frozenset({"barb", "corn", "wood", "stone", "gold", "cycle"})


@dataclass(frozen=True)
class BotDeviceConfig:
    """1 máy + cấu hình bot đầy đủ.

    Dùng cho `cmd_fleet` và bất kỳ ai cần spawn `python main.py bot`
    với đối số CLI chuẩn cho 1 thiết bị.
    """

    name: str
    serial: str
    resource: str
    target_level: int
    max_slots: int
    skip_level_adjust: bool
    turn_wait_min: int
    control_mode: str

    def to_bot_cli_args(self) -> list[str]:
        """Chuyển thành đối số CLI cho `python main.py bot ...`."""
        args = [
            "--serial", self.serial,
            "--resource", self.resource,
            "--target-level", str(self.target_level),
            "--max-slots", str(self.max_slots),
            "--turn-wait-min", str(self.turn_wait_min),
            "--control-mode", self.control_mode,
        ]
        if self.skip_level_adjust:
            args.append("--skip-level-adjust")
        return args


def load_bot_fleet_config(devices_file: Path) -> list[BotDeviceConfig]:
    """Đọc devices.yaml schema mới (bot fleet).

    Schema:
        defaults:
          resource: wood
          target_level: 5
          ...
        devices:
          - name: phone-1
            serial: ABC
            # không có 'bot' -> dùng defaults
          - name: phone-2
            serial: DEF
            bot:
              resource: stone
              target_level: 7
    """
    if not devices_file.exists():
        raise FileNotFoundError(
            f"Thiếu {devices_file}. Copy devices.yaml.example "
            "thành devices.yaml rồi điền serial máy của bạn.",
        )
    raw = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}

    # Merge defaults: bot block của 1 device override defaults của file.
    file_defaults = dict(_BOT_CONFIG_DEFAULTS)
    for k, v in (raw.get("defaults") or {}).items():
        if k in file_defaults:
            file_defaults[k] = v

    out: list[BotDeviceConfig] = []
    for d in raw.get("devices", []):
        if "serial" not in d:
            log.warning("Bỏ qua mục thiết bị thiếu 'serial': %r", d)
            continue
        cfg = dict(file_defaults)
        for k, v in (d.get("bot") or {}).items():
            if k in cfg:
                cfg[k] = v

        cfg["resource"] = normalize_resource(cfg["resource"])
        if cfg["resource"] not in _VALID_RESOURCES:
            raise ValueError(
                f"Thiết bị {d.get('name', d['serial'])}: "
                f"resource='{cfg['resource']}' không hợp lệ. "
                f"Phải là một trong: {sorted(_VALID_RESOURCES)}",
            )

        out.append(BotDeviceConfig(
            name=str(d.get("name", d["serial"])),
            serial=str(d["serial"]),
            resource=str(cfg["resource"]),
            target_level=int(cfg["target_level"]),
            max_slots=int(cfg["max_slots"]),
            skip_level_adjust=bool(cfg["skip_level_adjust"]),
            turn_wait_min=int(cfg["turn_wait_min"]),
            control_mode=str(cfg["control_mode"]),
        ))
    return out


def load_legacy_devices_config(
    devices_file: Path,
) -> list[DeviceConfig]:
    """Đọc devices.yaml schema CŨ (scenario YAML based).

    Dùng cho `cmd_run` — vẫn giữ tương thích với scenario engine cũ.
    Schema cũ:
        devices:
          - name: phone-1
            serial: ABC
            scenario: rok_gather_wood.yaml
    """
    if not devices_file.exists():
        raise FileNotFoundError(
            f"Thiếu {devices_file}. Cập nhật devices.yaml với "
            "serial máy của bạn.",
        )
    raw = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}
    out: list[DeviceConfig] = []
    for d in raw.get("devices", []):
        # Schema mới (có 'bot:' block) không có 'scenario' -> bỏ qua.
        if "scenario" not in d:
            continue
        out.append(DeviceConfig(
            name=str(d["name"]),
            serial=str(d["serial"]),
            scenario=str(d["scenario"]),
        ))
    return out


def first_device_serial(devices_file: Path) -> str | None:
    """Lấy serial của thiết bị đầu tiên trong devices.yaml.

    Dùng làm default khi user chạy lệnh KHÔNG truyền --serial.
    Trả None nếu file không tồn tại hoặc không có thiết bị nào.
    """
    if not devices_file.exists():
        return None
    try:
        raw = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}
    except Exception:
        log.exception("Đọc %s thất bại", devices_file)
        return None
    devices = raw.get("devices") or []
    if not devices:
        return None
    serial = devices[0].get("serial")
    return str(serial) if serial else None
