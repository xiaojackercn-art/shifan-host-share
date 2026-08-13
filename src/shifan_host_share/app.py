from __future__ import annotations

import sys
from pathlib import Path

import webview

from .api import AppApi
from .deskflow_engine import resource_root

APP_NAME = "视饭AI:主机共享"


def web_dir() -> Path:
    if getattr(sys, "frozen", False):
        candidates = [
            resource_root() / "web",
            Path(getattr(sys, "_MEIPASS", resource_root())) / "web",
            Path(getattr(sys, "_MEIPASS", resource_root())) / "shifan_host_share" / "web",
        ]
        for candidate in candidates:
            if (candidate / "index.html").exists():
                return candidate
        raise FileNotFoundError(f"应用界面资源缺失：{candidates}")
    return Path(__file__).resolve().parent / "web"


def run() -> None:
    api = AppApi()
    index = web_dir() / "index.html"
    window = webview.create_window(
        APP_NAME,
        url=index.as_uri(),
        js_api=api,
        width=1120,
        height=760,
        min_size=(960, 680),
        resizable=True,
        background_color="#08111f",
        text_select=False,
    )
    window.events.closed += lambda: api.close()
    webview.start(debug=False, private_mode=False)
