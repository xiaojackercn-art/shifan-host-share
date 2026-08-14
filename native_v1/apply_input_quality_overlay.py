#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    input_path = root / "src-tauri" / "src" / "input.rs"
    input_rs = input_path.read_text(encoding="utf-8")

    # 250 Hz motion sampling. The transport coalesces pending mouse motion, so
    # increasing sampling frequency improves responsiveness without creating a
    # stale-packet backlog when the WAN path momentarily slows down.
    input_rs = replace_once(
        input_rs,
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 8;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 8;",
        "const MOUSE_MOVE_SEND_INTERVAL_MS: u64 = 4;\nconst DRAG_MOVE_SEND_INTERVAL_MS: u64 = 4;",
        "250Hz pointer cadence",
    )

    # Mouse motion is replaceable state; buttons, wheel and keyboard events are
    # state transitions and must remain non-coalesced.
    input_rs = replace_once(
        input_rs,
        ") -> bool {\n    let mut packet_context = input_packet_context(target, event, layout_state);",
        ") -> bool {\n    let low_latency_mouse = matches!(&event, InputEvent::MouseMove { .. });\n    let mut packet_context = input_packet_context(target, event, layout_state);",
        "classify realtime mouse packet",
    )
    input_rs = replace_once(
        input_rs,
        "    match quic_transport.send_datagram(peer, payload) {\n        Ok(()) => {",
        "    let send_result = if low_latency_mouse {\n        quic_transport.send_latest_datagram(peer, payload)\n    } else {\n        quic_transport.send_datagram(peer, payload)\n    };\n\n    match send_result {\n        Ok(()) => {",
        "route mouse motion to coalescing transport",
    )

    # WAN keyboard events used to leave the cached input target and reconstruct
    # a peer from Device.host. WAN devices intentionally store host as
    # wan://<endpoint>/<cluster>/<secret>; rebuilding a socket-like address from
    # that value made the keyboard path differ from the already-working mouse
    # path. Keep WAN keys on the same authenticated cached target as pointer
    # events. Modifier remapping can still consult the live layout when available.
    input_rs = replace_once(
        input_rs,
        '''    if !matches!(event, InputEvent::Key { .. }) {
        return fallback_context(event);
    }

    let layout = match layout_state.try_lock() {''',
        '''    if !matches!(event, InputEvent::Key { .. }) {
        return fallback_context(event);
    }

    if target.target_addr.starts_with("wan:") {
        let event = match layout_state.try_lock() {
            Ok(layout) => remap_event_for_target_layout(event, target, &layout),
            Err(_) => event,
        };
        return fallback_context(event);
    }

    let layout = match layout_state.try_lock() {''',
        "keep WAN keyboard on cached peer",
    )
    input_path.write_text(input_rs, encoding="utf-8")

    # Use physical scan-code injection on Windows. This is the same class of
    # input Windows receives from a real keyboard and avoids applications that
    # ignore virtual-key-only synthetic events. Fall back to virtual-key mode
    # only for keys that do not have a scan-code mapping.
    windows_input_path = root / "src-tauri" / "src" / "windows_input.rs"
    windows_input = windows_input_path.read_text(encoding="utf-8")
    old_inject_key = '''pub fn inject_key(key_code: u16, down: bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, MAPVK_VK_TO_VSC,
    };

    let mut dw_flags = if down { 0 } else { KEYEVENTF_KEYUP };
    if is_extended_key_vk(key_code) {
        dw_flags |= KEYEVENTF_EXTENDEDKEY;
    }

    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;

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
    };
    unsafe {
        if SendInput(1, &input, std::mem::size_of::<INPUT>() as i32) == 0 {
            note_injection_refused("key", windows_sys::Win32::Foundation::GetLastError());
        }
    }
}
'''
    new_inject_key = '''pub fn inject_key(key_code: u16, down: bool) {
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT,
        KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,
    };

    let mut dw_flags = if down { 0 } else { KEYEVENTF_KEYUP };
    if is_extended_key_vk(key_code) {
        dw_flags |= KEYEVENTF_EXTENDEDKEY;
    }

    let scan = unsafe { MapVirtualKeyW(key_code as u32, MAPVK_VK_TO_VSC) } as u16;
    let (w_vk, w_scan, flags) = if scan != 0 {
        (0, scan, dw_flags | KEYEVENTF_SCANCODE)
    } else {
        (key_code, 0, dw_flags)
    };

    let input = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: w_vk,
                wScan: w_scan,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };
    unsafe {
        if SendInput(1, &input, std::mem::size_of::<INPUT>() as i32) == 0 {
            note_injection_refused("key", windows_sys::Win32::Foundation::GetLastError());
        }
    }
}
'''
    windows_input = replace_once(
        windows_input,
        old_inject_key,
        new_inject_key,
        "Windows scan-code keyboard injection",
    )
    windows_input_path.write_text(windows_input, encoding="utf-8")

    # Ship a Chinese-only NSIS UI. Tauri otherwise defaults to English when no
    # installer language list is specified.
    conf_path = root / "src-tauri" / "tauri.conf.json"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    nsis = conf.setdefault("bundle", {}).setdefault("windows", {}).setdefault("nsis", {})
    nsis["languages"] = ["SimpChinese"]
    nsis["displayLanguageSelector"] = False
    conf_path.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("input quality and Chinese installer overlay applied")


if __name__ == "__main__":
    main()
