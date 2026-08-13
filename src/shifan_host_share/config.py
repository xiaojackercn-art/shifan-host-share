from __future__ import annotations

import json
import os
import platform
import secrets
from pathlib import Path

APP_DIR = "ShifanAIHostShare"
DEFAULT_CONTROL_PORT = 35999
DEFAULT_KVM_PORT = 24861


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


def new_pair_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def new_device_id() -> str:
    return secrets.token_hex(8).upper()


def default_config() -> dict:
    return {
        "version": 2,
        "device_id": new_device_id(),
        "pair_code": new_pair_code(),
        "control_port": DEFAULT_CONTROL_PORT,
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
                cfg.update({k: v for k, v in data.items() if k != "peer"})
                if isinstance(data.get("peer"), dict):
                    cfg["peer"].update(data["peer"])
        except Exception:
            pass
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
