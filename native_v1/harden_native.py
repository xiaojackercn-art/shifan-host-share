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


def replace_last(text: str, source: str, target: str, label: str) -> str:
    index = text.rfind(source)
    if index < 0:
        raise RuntimeError(f"upstream changed at {label}")
    return text[:index] + target + text[index + len(source):]


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


def patch_input_hot_path(root: Path) -> None:
    path = root / "src-tauri" / "src" / "input.rs"
    text = path.read_text(encoding="utf-8")
    text = text.replace("const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 8;", "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 4;", 1)
    text = text.replace("const DRAG_MOVE_SEND_INTERVAL_MS: u64 = 8;", "const DRAG_MOVE_SEND_INTERVAL_MS: u64 = 4;", 1)
    text = text.replace("MsgWaitForMultipleObjects(0, std::ptr::null(), 0, 20, QS_ALLINPUT)", "MsgWaitForMultipleObjects(0, std::ptr::null(), 0, 8, QS_ALLINPUT)", 1)

    text = replace_last(
        text,
        "    active: Mutex<Option<ActiveTarget>>,\n    remote_active: Arc<AtomicBool>,",
        "    active: Mutex<Option<ActiveTarget>>,\n    keyboard_target: Mutex<Option<InputTarget>>,\n    remote_active: Arc<AtomicBool>,",
        "Windows capture context",
    )
    text = replace_last(
        text,
        "            active: Mutex::new(None),\n            remote_active,",
        "            active: Mutex::new(None),\n            keyboard_target: Mutex::new(None),\n            remote_active,",
        "Windows capture context init",
    )
    keyboard_lookup = """    let active = context
        .active
        .lock()
        .ok()
        .and_then(|active| active.as_ref().map(|active| active.target.clone()));
    let Some(target) = active else {"""
    keyboard_replacement = """    let target = context
        .keyboard_target
        .lock()
        .ok()
        .and_then(|target| target.clone());
    let Some(target) = target else {"""
    text = replace_last(text, keyboard_lookup, keyboard_replacement, "Windows keyboard target lookup")
    text = replace_last(
        text,
        "        *active = Some(active_target);\n        if let Ok(mut anchor_state) = context.anchor.lock() {",
        "        if let Ok(mut keyboard_target) = context.keyboard_target.lock() {\n            *keyboard_target = Some(active_target.target.clone());\n        }\n        *active = Some(active_target);\n        if let Ok(mut anchor_state) = context.anchor.lock() {",
        "Windows edge crossing",
    )
    text = replace_last(
        text,
        "            *active = None;\n            context.remote_active.store(false, Ordering::Relaxed);",
        "            *active = None;\n            clear_windows_keyboard_target(context);\n            context.remote_active.store(false, Ordering::Relaxed);",
        "Windows edge return",
    )
    text = replace_last(
        text,
        "    context.remote_active.store(false, Ordering::Relaxed);\n    context.just_crossed.store(false, Ordering::Relaxed);",
        "    clear_windows_keyboard_target(context);\n    context.remote_active.store(false, Ordering::Relaxed);\n    context.just_crossed.store(false, Ordering::Relaxed);",
        "Windows release",
    )
    text = text.replace(
        '#[cfg(target_os = "windows")]\nfn cached_windows_input_desktop_is_default() -> bool {',
        '#[cfg(target_os = "windows")]\nfn clear_windows_keyboard_target(context: &WindowsCaptureContext) {\n    if let Ok(mut target) = context.keyboard_target.lock() {\n        *target = None;\n    }\n}\n\n#[cfg(target_os = "windows")]\nfn cached_windows_input_desktop_is_default() -> bool {',
        1,
    )
    path.write_text(text, encoding="utf-8")


def patch_windows_injection(root: Path) -> None:
    path = root / "src-tauri" / "src" / "windows_input.rs"
    text = path.read_text(encoding="utf-8")
    start = text.find("pub fn inject_mouse_move(")
    end = text.find("pub fn inject_mouse_button(", start)
    if start < 0 or end < 0:
        raise RuntimeError("upstream mouse injection changed")
    mouse_move = '''pub fn inject_mouse_move(x: i32, y: i32, _drag_button: Option<MouseButton>) {
    use windows_sys::Win32::UI::WindowsAndMessaging::SetCursorPos;
    unsafe {
        let _ = SetCursorPos(x, y);
    }
}

'''
    text = text[:start] + mouse_move + text[end:]
    text = text.replace(
        "        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, MAPVK_VK_TO_VSC,",
        "        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,",
        1,
    )
    old = """    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;

    // Use SendInput instead of keybd_event: same reason as inject_mouse_button
    // — keybd_event was silently dropping key events from the helper's spawned
    // thread, leaving the keyboard dead while mouse moves still worked.
    let input = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: key_code,
                wScan: scan,
                dwFlags: dw_flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };"""
    new = """    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;
    let (virtual_key, scan_code) = if scan != 0 {
        dw_flags |= KEYEVENTF_SCANCODE;
        (0, scan)
    } else {
        (key_code, 0)
    };

    let input = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: virtual_key,
                wScan: scan_code,
                dwFlags: dw_flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };"""
    if old not in text:
        raise RuntimeError("upstream keyboard injection changed")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


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
    patch_input_hot_path(root)
    patch_windows_injection(root)
    patch_visible_copy(root)
    print("ShifanAI product hardening applied")


if __name__ == "__main__":
    main()
