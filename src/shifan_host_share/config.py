from __future__ import annotations

import json
import os
import platform
import secrets
from pathlib import Path

APP_DIR = "ShifanAIHostShare"
DEFAULT_KVM_PORT = 24800


def app_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_pair_code(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def format_pair_code(value: str) -> str:
    raw = normalize_pair_code(value)[:12]
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def format_pair_code_input(value: str) -> str:
    raw = normalize_pair_code(value)[:12]
    formatted = "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))
    if len(raw) in {4, 8} and len(raw) < 12:
        formatted += "-"
    return formatted


def new_pair_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return format_pair_code(raw)


def new_device_id() -> str:
    return secrets.token_hex(8).upper()


def default_config() -> dict:
    return {
        "version": 3,
        "device_id": new_device_id(),
        "pair_code": new_pair_code(),
        "kvm_port": DEFAULT_KVM_PORT,
        "peer": {
            "host": "",
            "pair_code": "",
            "direction": "right",
            "device_name": "",
            "device_id": "",
        },
    }


def load_config() -> dict:
    path = app_data_dir() / "config.json"
    cfg = default_config()
    if path.exists():
        try:
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k not in {"peer", "control_port"}})
                if isinstance(data.get("peer"), dict):
                    cfg["peer"].update(data["peer"])
        except Exception:
            pass
    cfg["version"] = 3
    cfg["kvm_port"] = DEFAULT_KVM_PORT
    cfg.pop("control_port", None)
    if not normalize_pair_code(cfg.get("pair_code", "")):
        cfg["pair_code"] = new_pair_code()
    if not cfg.get("device_id"):
        cfg["device_id"] = new_device_id()
    save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    path = app_data_dir() / "config.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def regenerate_pair_code(cfg: dict) -> str:
    cfg["pair_code"] = new_pair_code()
    save_config(cfg)
    return cfg["pair_code"]
