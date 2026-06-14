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


def auto_correct_serial(name: str, serial: str) -> str:
    """Tự động kiểm tra và sửa port của serial dựa trên file bluestacks.conf nếu có sai lệch."""
    import sys
    if sys.platform != "win32":
        return serial

    import os
    import re
    import winreg
    
    # 1. Lấy đường dẫn bluestacks.conf
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
    conf_path = os.path.join(user_dir, "bluestacks.conf")
    if not os.path.exists(conf_path):
        return serial

    # 2. Đọc bluestacks.conf để lấy mapping port
    ports = {}          # instance_name -> port
    display_names = {}  # instance_name -> display_name
    
    port_pattern = re.compile(r'bst\.instance\.([a-zA-Z0-9_]+)(?:\.status)?\.adb_port="(\d+)"')
    name_pattern = re.compile(r'bst\.instance\.([a-zA-Z0-9_]+)\.display_name="([^"]+)"')
    
    try:
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m_port = port_pattern.search(line)
                if m_port:
                    inst_name, port = m_port.groups()
                    ports[inst_name] = int(port)
                m_name = name_pattern.search(line)
                if m_name:
                    inst_name, display_name = m_name.groups()
                    display_names[inst_name] = display_name.strip()
    except Exception:
        return serial

    bs_mapping = {}
    for inst_name, port in ports.items():
        bs_mapping[inst_name.lower()] = port
        if inst_name in display_names:
            bs_mapping[display_names[inst_name].lower()] = port

    # 3. Phân tích serial hiện tại
    host = "127.0.0.1"
    port_str = serial
    if ":" in serial:
        host, port_str = serial.split(":", 1)
    
    try:
        current_port = int(port_str)
    except ValueError:
        return serial

    # Nếu cổng hiện tại đang mở/hoạt động, giữ nguyên không tự động sửa
    from core.bot.bluestack import is_port_open
    try:
        if is_port_open(current_port, host=host):
            return serial
    except Exception:
        pass

    # 4. Tìm port đúng
    correct_port = None
    dev_name_lower = name.lower().strip()
    
    # Thử tìm theo display_name/instance_name trực tiếp
    if dev_name_lower in bs_mapping:
        correct_port = bs_mapping[dev_name_lower]
    else:
        # Thử tìm theo chữ số trong tên
        dev_digits = "".join(re.findall(r'\d+', dev_name_lower))
        if dev_digits and dev_digits in bs_mapping:
            correct_port = bs_mapping[dev_digits]
            
    # Thử tìm theo độ lệch cổng nhỏ (<= 2)
    if correct_port is None:
        for bs_port in bs_mapping.values():
            if abs(bs_port - current_port) <= 2:
                correct_port = bs_port
                break

    if correct_port is not None and correct_port != current_port:
        new_serial = f"{host}:{correct_port}"
        log.warning(
            "[AutoCorrect] Thiết bị '%s' cấu hình serial %s lệch với Bluestacks. Tự động sửa thành: %s",
            name, serial, new_serial
        )
        return new_serial

    return serial


def save_corrected_devices_yaml(devices_file: Path, corrections: dict[str, str]) -> None:
    """Cập nhật các serial bị sai trực tiếp trong file devices.yaml để lưu trữ lâu dài."""
    if not devices_file.exists() or not corrections:
        return
    try:
        content = devices_file.read_text(encoding="utf-8")
        updated = False
        for old_serial, new_serial in corrections.items():
            if old_serial in content and new_serial not in content:
                content = content.replace(old_serial, new_serial)
                updated = True
        if updated:
            devices_file.write_text(content, encoding="utf-8")
            log.info("[AutoCorrect] Đã cập nhật tự động các cổng mới vào file %s", devices_file.name)
    except Exception as e:
        log.error("[AutoCorrect] Không thể ghi đè file cấu hình devices.yaml: %s", e)


def get_bluestacks_devices_from_conf() -> list[dict[str, str]]:
    """Quét bluestacks.conf và trả về danh sách các thiết bị với name và serial."""
    import sys
    if sys.platform != "win32":
        return []

    import os
    import re
    import winreg

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
    conf_path = os.path.join(user_dir, "bluestacks.conf")
    if not os.path.exists(conf_path):
        return []

    ports = {}          # instance_name -> port
    display_names = {}  # instance_name -> display_name

    port_pattern = re.compile(r'bst\.instance\.([a-zA-Z0-9_]+)(?:\.status)?\.adb_port="(\d+)"')
    name_pattern = re.compile(r'bst\.instance\.([a-zA-Z0-9_]+)\.display_name="([^"]+)"')

    try:
        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m_port = port_pattern.search(line)
                if m_port:
                    inst_name, port = m_port.groups()
                    ports[inst_name] = int(port)
                m_name = name_pattern.search(line)
                if m_name:
                    inst_name, display_name = m_name.groups()
                    display_names[inst_name] = display_name.strip()
    except Exception:
        return []

    devices_list = []
    for inst_name, port in ports.items():
        name = display_names.get(inst_name, inst_name)
        devices_list.append({
            "name": name,
            "serial": f"127.0.0.1:{port}"
        })

    # Sắp xếp các thiết bị theo tên (ví dụ: 1 -> 2 -> 3 -> 4)
    def sort_key(d):
        name = d["name"]
        try:
            return (0, int(name))
        except ValueError:
            return (1, name)
            
    devices_list.sort(key=sort_key)
    return devices_list


def load_global_settings(devices_file: Path) -> None:
    """Đọc các cài đặt toàn cục từ devices.yaml và ghi đè vào core.bot.config."""
    if not devices_file.exists():
        return
    try:
        raw = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}
        # Đọc từ phần settings hoặc defaults làm fallback
        settings = raw.get("settings") or raw.get("defaults") or {}
        
        from core.bot import config
        
        mapping = {
            "cycle_wait_min": "CYCLE_WAIT_MIN",
            "cycle_wait_variance_min": "CYCLE_WAIT_VARIANCE_MIN",
            "bg_action_interval_min": "BG_ACTION_INTERVAL_MIN",
            "bg_action_interval_max": "BG_ACTION_INTERVAL_MAX",
            "delay_after_popup_min": "DELAY_AFTER_POPUP_MIN",
            "delay_after_popup_max": "DELAY_AFTER_POPUP_MAX",
            "delay_after_dispatch_min": "DELAY_AFTER_DISPATCH_MIN",
            "delay_after_dispatch_max": "DELAY_AFTER_DISPATCH_MAX",
            "enable_city_world_toggle": "ENABLE_CITY_WORLD_TOGGLE",
            "city_world_toggle_probability": "CITY_WORLD_TOGGLE_PROBABILITY",
            "enable_input_lock": "ENABLE_INPUT_LOCK",
            "save_drag_path_images": "SAVE_DRAG_PATH_IMAGES",
            "enable_vip_claim": "ENABLE_VIP_CLAIM",
        }
        
        for yaml_key, config_key in mapping.items():
            if yaml_key in settings:
                val = settings[yaml_key]
                try:
                    if config_key in ("ENABLE_CITY_WORLD_TOGGLE", "ENABLE_INPUT_LOCK", "SAVE_DRAG_PATH_IMAGES", "ENABLE_VIP_CLAIM"):
                        parsed_val = bool(val)
                    elif config_key == "CITY_WORLD_TOGGLE_PROBABILITY":
                        parsed_val = float(val)
                    else:
                        parsed_val = int(val)
                    setattr(config, config_key, parsed_val)
                    log.info("[Config] Đã nạp %s = %s", config_key, str(parsed_val))
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        log.error("Không thể nạp cài đặt toàn cục từ devices.yaml: %s", e)


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
    load_global_settings(devices_file)
    raw = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}

    # Merge defaults: bot block của 1 device override defaults của file.
    file_defaults = dict(_BOT_CONFIG_DEFAULTS)
    for k, v in (raw.get("defaults") or {}).items():
        if k in file_defaults:
            file_defaults[k] = v

    devices_data = raw.get("devices")
    if not devices_data:
        log.info("[AutoDetect] Không tìm thấy danh sách 'devices' trong cấu hình. Tự động lấy danh sách từ Bluestacks...")
        devices_data = get_bluestacks_devices_from_conf()

    corrections = {}
    out: list[BotDeviceConfig] = []
    for d in devices_data:
        if "serial" not in d:
            log.warning("Bỏ qua mục thiết bị thiếu 'serial': %r", d)
            continue
        
        name = str(d.get("name", d["serial"]))
        old_serial = str(d["serial"])
        
        # Tự động sửa cổng nếu sai lệch
        new_serial = auto_correct_serial(name, old_serial)
        if new_serial != old_serial:
            corrections[old_serial] = new_serial

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
            name=name,
            serial=new_serial,
            resource=str(cfg["resource"]),
            target_level=int(cfg["target_level"]),
            max_slots=int(cfg["max_slots"]),
            skip_level_adjust=bool(cfg["skip_level_adjust"]),
            turn_wait_min=int(cfg["turn_wait_min"]),
            control_mode=str(cfg["control_mode"]),
        ))
        
    if corrections:
        save_corrected_devices_yaml(devices_file, corrections)
        
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
    
    devices_data = raw.get("devices")
    if not devices_data:
        # Scenario engine yêu cầu yaml config nên không tự động nhận diện thiết bị
        devices_data = []

    corrections = {}
    out: list[DeviceConfig] = []
    for d in devices_data:
        # Schema mới (có 'bot:' block) không có 'scenario' -> bỏ qua.
        if "scenario" not in d:
            continue
        name = str(d["name"])
        old_serial = str(d["serial"])
        
        # Tự động sửa cổng nếu sai lệch
        new_serial = auto_correct_serial(name, old_serial)
        if new_serial != old_serial:
            corrections[old_serial] = new_serial

        out.append(DeviceConfig(
            name=name,
            serial=new_serial,
            scenario=str(d["scenario"]),
        ))
        
    if corrections:
        save_corrected_devices_yaml(devices_file, corrections)
        
    return out


def first_device_serial(devices_file: Path) -> str | None:
    """Lấy serial của thiết bị đầu tiên trong devices.yaml.

    Dùng làm default khi user chạy lệnh KHÔNG truyền --serial.
    Trả None nếu file không tồn tại hoặc không có thiết bị nào.
    """
    if not devices_file.exists():
        return None
    load_global_settings(devices_file)
    try:
        raw = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}
    except Exception:
        log.exception("Đọc %s thất bại", devices_file)
        return None
    
    devices = raw.get("devices")
    if not devices:
        devices = get_bluestacks_devices_from_conf()

    if not devices:
        return None
        
    serial = devices[0].get("serial")
    if not serial:
        return None
    name = str(devices[0].get("name", ""))
    serial_str = str(serial)
    
    # Tự động sửa cổng nếu sai lệch
    new_serial = auto_correct_serial(name, serial_str)
    if new_serial != serial_str:
        save_corrected_devices_yaml(devices_file, {serial_str: new_serial})
        
    return new_serial
