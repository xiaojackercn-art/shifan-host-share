from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any

APP_DIR_NAME = ".shifan_host_share"
DEFAULT_PORT = 24861


def _new_key() -> str:
    raw = base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        path = base / "ShifanAIHostShare"
    else:
        path = Path.home() / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def default_config() -> dict[str, Any]:
    return {
        "port": DEFAULT_PORT,
        "mouse_key": _new_key(),
        "keyboard_key": _new_key(),
        "peer": {
            "host": "",
            "port": DEFAULT_PORT,
            "mouse_key": "",
            "keyboard_key": "",
            "direction": "right",
            "mouse_enabled": True,
            "keyboard_enabled": True,
        },
    }


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        cfg = default_config()
        save_config(cfg)
        return cfg
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cfg = default_config()
        save_config(cfg)
        return cfg

    defaults = default_config()
    cfg.setdefault("port", defaults["port"])
    cfg.setdefault("mouse_key", defaults["mouse_key"])
    cfg.setdefault("keyboard_key", defaults["keyboard_key"])
    peer = cfg.setdefault("peer", {})
    for key, value in defaults["peer"].items():
        peer.setdefault(key, value)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    path = config_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def regenerate_local_keys(cfg: dict[str, Any]) -> None:
    cfg["mouse_key"] = _new_key()
    cfg["keyboard_key"] = _new_key()
    save_config(cfg)
