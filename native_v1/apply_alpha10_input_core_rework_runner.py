#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import apply_alpha10_input_core_rework as overlay


def replace_first(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count < 1:
        raise RuntimeError(f"{label}: expected at least one match, found 0")
    return text.replace(old, new, 1)


def patch_windows_injection_final(root: Path) -> None:
    path = root / "src-tauri" / "src" / "windows_input.rs"
    text = path.read_text(encoding="utf-8")

    primary_old = '''        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput VK path");
            }
            return;
        }'''
    primary_new = '''        if SendInput(1, &primary, std::mem::size_of::<INPUT>() as i32) != 0 {
            crate::input::note_keyboard_injection_result(true, None);
            if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                log::info!("[diag] first remote keyboard event injected through SendInput VK path");
            }
            return;
        }'''
    text = replace_first(text, primary_old, primary_new, "alpha10 primary key injection diagnostics")

    fallback_old = '''            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through SendInput scan-code fallback");
                }
                return;
            }
        }
        note_injection_refused("key", primary_error);'''
    fallback_new = '''            if SendInput(1, &fallback, std::mem::size_of::<INPUT>() as i32) != 0 {
                crate::input::note_keyboard_injection_result(true, None);
                if !FIRST_REMOTE_KEY_INJECTED.swap(true, Ordering::Relaxed) {
                    log::info!("[diag] first remote keyboard event injected through SendInput scan-code fallback");
                }
                return;
            }
        }
        let final_error = windows_sys::Win32::Foundation::GetLastError();
        crate::input::note_keyboard_injection_result(false, Some(final_error));
        note_injection_refused("key", if final_error == 0 { primary_error } else { final_error });'''
    text = replace_first(text, fallback_old, fallback_new, "alpha10 fallback key injection diagnostics")
    path.write_text(text, encoding="utf-8")


overlay.replace_once = replace_first
overlay.patch_windows_injection = patch_windows_injection_final

if __name__ == "__main__":
    overlay.main()
