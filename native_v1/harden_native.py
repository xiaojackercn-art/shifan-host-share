#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def replace_text(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    original = text
    for source, target in replacements:
        text = text.replace(source, target)
    if text != original:
        path.write_text(text, encoding="utf-8")


def patch_tauri(root: Path) -> None:
    path = root / "src-tauri" / "tauri.conf.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for window in data.setdefault("app", {}).setdefault("windows", []):
        window["width"] = 1360
        window["height"] = 880
        window["minWidth"] = 1080
        window["minHeight"] = 720
        window["resizable"] = True
    nsis = data.setdefault("bundle", {}).setdefault("windows", {}).setdefault("nsis", {})
    nsis["languages"] = ["SimpChinese"]
    nsis["displayLanguageSelector"] = False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_windows_installer(root: Path) -> None:
    path = root / "src-tauri" / "nsis-hooks.nsh"
    replace_text(path, [
        ("ShifanAI Host ShareInputService", "MyKVMInputService"),
        ('DetailPrint "Closing running mykvm instances..."', 'DetailPrint "正在关闭运行中的视饭AI主机共享..."'),
        ('DetailPrint "Stopping ShifanAI Host Share input service..."', 'DetailPrint "正在停止键鼠输入服务..."'),
        ('DetailPrint "Freeing input helper for replacement..."', 'DetailPrint "正在准备更新键鼠输入组件..."'),
        ('DetailPrint "Restarting ShifanAI Host Share input service if installed..."', 'DetailPrint "正在启动键鼠输入服务..."'),
        ('DetailPrint "Removing ShifanAI Host Share input service..."', 'DetailPrint "正在移除键鼠输入服务..."'),
        ('DetailPrint "Configuring Windows Defender Firewall for mykvm..."', 'DetailPrint "正在配置 Windows 防火墙..."'),
    ])


def patch_input_cadence(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    replace_text(path, [
        ("const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 8;", "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 4;"),
        ("const DRAG_MOVE_SEND_INTERVAL_MS: u64 = 8;", "const DRAG_MOVE_SEND_INTERVAL_MS: u64 = 4;"),
        ("MsgWaitForMultipleObjects(0, std::ptr::null(), 0, 20, QS_ALLINPUT)", "MsgWaitForMultipleObjects(0, std::ptr::null(), 0, 8, QS_ALLINPUT)"),
    ])


def patch_visible_copy(root: Path) -> None:
    replace_text(root / "src" / "i18n.ts", [
        ('eyebrow: "Settings"', 'eyebrow: "设置"'),
        ('simplifiedChinese: "cn 中文简体"', 'simplifiedChinese: "中文（简体）"'),
        ('inputServiceEyebrow: "Windows LocalSystem"', 'inputServiceEyebrow: "Windows 系统级输入服务"'),
    ])


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: harden_native.py <native-upstream-root>")
    root = Path(sys.argv[1]).resolve()
    patch_tauri(root)
    patch_windows_installer(root)
    patch_input_cadence(root)
    patch_visible_copy(root)
    print("ShifanAI product hardening applied")


if __name__ == "__main__":
    main()
